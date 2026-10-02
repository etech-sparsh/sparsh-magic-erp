"""
IRM ▸ attendance import/export and the punctuality it feeds.

Attendance is IMPORTED, never entered. There is deliberately no endpoint that marks a day
by hand: punctuality is an evaluation input, so every punch has to trace back to whatever
the biometric/HR export said rather than to somebody's memory of it. `import_attendance`
is the only writer of COLL_IRM_ATTENDANCE.

    present    the day has an IN punch
    late_in    IN  is later   than shift start + grace
    early_out  OUT is earlier than shift end   - grace
    punctual   present, both punches recorded, neither late nor early

    Punctuality % = punctual days ÷ days present × 100

A day with no OUT punch counts as present but NOT punctual — a half-recorded day cannot be
shown to have been worked in full — and is reported separately as `missing_out` so the
number is explainable rather than mysteriously low.

Re-importing is safe: rows are upserted on (company, person, date), so a corrected file
replaces the day it covers and leaves every other day alone.
"""
import io
import logging
import re
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

from app.db.mongodb import get_collection
from app.models.irm import (
    COLL_IRM_ATTENDANCE, COLL_IRM_CONFIG,
    default_shift,
)

logger = logging.getLogger(__name__)

# Header aliases, lower-cased and stripped of spaces/underscores before matching. Import
# files come from whichever device the client runs, so the column names are never stable —
# matching on a family of names is what stops every new client needing a code change.
COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "employee_id": ("employeeid", "empid", "empcode", "employeecode", "code", "staffid"),
    "email":       ("email", "emailid", "emailaddress", "mail"),
    "name":        ("name", "employeename", "fullname", "staffname", "person"),
    "date":        ("date", "attendancedate", "punchdate", "day"),
    "in_time":     ("intime", "in", "punchin", "checkin", "firstin", "instamp"),
    "out_time":    ("outtime", "out", "punchout", "checkout", "lastout", "outstamp"),
}

EXPORT_COLUMNS = ["Employee ID", "Name", "Email", "Date", "In Time", "Out Time",
                  "Late In", "Early Out", "Punctual"]


def columns_for(people: Dict[str, dict]) -> List[str]:
    """The columns a template/export should carry for THIS roster.

    Employee ID is the importer's first and most reliable matcher, but only for a company that
    actually holds employee codes. Where none are stored the column can never match anything —
    it is an empty column inviting somebody to type codes this system does not know, and a
    wrong code is worse than a blank one because it can land a row on the wrong person. So it
    is offered only when at least one person on the roster has a code; Email and Name carry the
    matching otherwise. The importer still ACCEPTS the column (and its aliases) from whatever
    file a client's device produces — this decides only what we hand out.
    """
    if any((p or {}).get("employee_id") for p in (people or {}).values()):
        return list(EXPORT_COLUMNS)
    return [c for c in EXPORT_COLUMNS if c != "Employee ID"]


def _norm_header(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _map_columns(columns) -> Dict[str, str]:
    """{canonical_field: actual_column_name} for whatever the file happens to call them."""
    found: Dict[str, str] = {}
    for col in columns:
        key = _norm_header(col)
        for field, aliases in COLUMN_ALIASES.items():
            if field in found:
                continue
            if key in aliases:
                found[field] = col
                break
    return found


def _to_date(value) -> Optional[str]:
    """Any of the shapes a date arrives in → 'YYYY-MM-DD', or None if unreadable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "nat", "none"):
        return None
    # Excel hands dates back as 'YYYY-MM-DD 00:00:00' as often as not.
    raw = raw.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# "6:30 PM", "6:30pm", "6:30 p.m." — the tail of a 12-hour time, however it was typed.
_MERIDIEM_RE = re.compile(r"\s*([ap])\.?\s*m\.?\s*$", re.IGNORECASE)


def _to_hhmm(value) -> Optional[str]:
    """Any of the shapes a punch time arrives in → 'HH:MM' (24-hour), or None when absent.

    Excel is the awkward one: a cell formatted as a time comes back as a datetime, as a
    `time`, or as a fraction of a day (0.4 == 09:36) depending on how it was written.

    Text cells are the other awkward one, because people write clock times the way they say
    them. "6:30 PM" is 18:30 and must not be read as 06:30 — a twelve-hour error scores as an
    early-out on every day of the month and nothing about the import looks wrong.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)):
        # A bare number is only a time if it is a fraction of a day; anything else is junk.
        if 0 <= float(value) < 1:
            minutes = int(round(float(value) * 24 * 60))
            return f"{minutes // 60:02d}:{minutes % 60:02d}"
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "nat", "none", "-", "--"):
        return None
    # Take the AM/PM off first — otherwise the split below throws away the time and keeps
    # the "PM", and the whole cell reads as unparseable.
    meridiem = None
    match = _MERIDIEM_RE.search(raw)
    if match:
        meridiem = match.group(1).lower()
        raw = raw[:match.start()].strip()
    if " " in raw:                      # '2026-08-11 09:41:00'
        raw = raw.split(" ")[-1]
    raw = raw.replace(".", ":")
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if meridiem and not (1 <= hh <= 12):
        return None                     # "19:30 PM" is not a time anybody meant
    if meridiem == "p" and hh < 12:
        hh += 12
    elif meridiem == "a" and hh == 12:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _text(value) -> str:
    """A cell as clean text, with the blanks pandas invents treated as blank.

    A blank Excel cell arrives as float('nan'), which is truthy — so `value or ""` keeps it
    and str() turns it into the literal string "nan". Everything that reads an identity
    column goes through here, so a missing Employee ID reads as absent rather than as a
    person called "nan".
    """
    if value is None:
        return ""
    # A column of numeric employee codes containing even ONE blank is typed as float by
    # pandas, so code 101 arrives as 101.0 and no longer matches the stored "101". Render a
    # whole number as a whole number. (Identity columns only — punch times take their own
    # path through _to_hhmm, where a fraction of a day is meaningful.)
    if isinstance(value, float) and not isinstance(value, bool) and value.is_integer():
        return str(int(value))
    raw = str(value).strip()
    return "" if raw.lower() in ("nan", "nat", "none") else raw


def _minutes(hhmm: Optional[str]) -> Optional[int]:
    if not hhmm:
        return None
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


# ─────────────────────────────────────────────────────────────
# Shift rule
# ─────────────────────────────────────────────────────────────
async def get_shift(company_id: str) -> dict:
    """The company's shift rule, falling back to the module defaults.

    Stored on the company's own irm_configs row as an additive `shift` sub-document, so a
    company that has never opened the setting keeps working and nothing existing is
    rewritten to introduce it.
    """
    doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    shift = default_shift()
    for key, value in ((doc or {}).get("shift") or {}).items():
        if key in shift:
            shift[key] = value
    return shift


async def save_shift(company_id: str, shift: dict, user: dict) -> dict:
    await get_collection(COLL_IRM_CONFIG).update_one(
        {"company_id": str(company_id)},
        {"$set": {
            "company_id": str(company_id),
            "shift": shift,
            "shift_updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
            "shift_updated_at": datetime.utcnow(),
        },
         "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )
    return await get_shift(company_id)


def evaluate_day(in_time: Optional[str], out_time: Optional[str], shift: dict) -> dict:
    """Classify one day's punches against the shift. Pure — the same inputs always give
    the same verdict, which is what makes the import and the export agree."""
    grace = int(shift.get("grace_minutes") or 0)
    start = _minutes(shift.get("start")) or 0
    end = _minutes(shift.get("end")) or 0
    in_m, out_m = _minutes(in_time), _minutes(out_time)

    present = in_m is not None
    late_in = bool(present and in_m > start + grace)
    early_out = bool(out_m is not None and out_m < end - grace)
    missing_out = bool(present and out_m is None)
    punctual = bool(present and not late_in and not missing_out and not early_out)
    return {"present": present, "late_in": late_in, "early_out": early_out,
            "missing_out": missing_out, "punctual": punctual}


# ─────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────
def _read_frame(content: bytes, filename: str):
    import pandas as pd
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    return pd.read_excel(io.BytesIO(content))


async def import_attendance(company_id: str, content: bytes, filename: str,
                            people: Dict[str, dict], user: dict) -> dict:
    """Load punch rows for a company, matching each to a person on the roster.

    A row that cannot be matched is REPORTED, never guessed at and never silently dropped:
    attendance that lands on the wrong person is worse than attendance that fails to land,
    because the first is invisible and the second is not.
    """
    try:
        frame = _read_frame(content, filename)
    except Exception as e:
        raise ValueError(f"Could not read that file: {e}")

    cols = _map_columns(list(frame.columns))
    if "date" not in cols:
        raise ValueError("The file needs a Date column.")
    if "in_time" not in cols:
        raise ValueError("The file needs an In Time column.")
    if not ({"employee_id", "email", "name"} & set(cols)):
        raise ValueError("The file needs an Employee ID, Email or Name column to match people.")

    # Three ways to reach a person, most reliable first. Name is last because it is the
    # only one that is not unique, and it is matched case-insensitively.
    by_emp = {str(p["employee_id"]).strip().lower(): pid
              for pid, p in people.items() if p.get("employee_id")}
    by_email = {str(p["email"]).strip().lower(): pid
                for pid, p in people.items() if p.get("email")}
    by_name = {str(p["name"]).strip().lower(): pid
               for pid, p in people.items() if p.get("name")}

    shift = await get_shift(company_id)
    col = get_collection(COLL_IRM_ATTENDANCE)

    imported = updated = skipped = 0
    unmatched: List[dict] = []
    seen_unmatched = set()

    for _idx, raw in frame.iterrows():
        def cell(field):
            name = cols.get(field)
            return raw[name] if name and name in raw else None

        date = _to_date(cell("date"))
        if not date:
            skipped += 1
            continue

        pid = None
        for field, table in (("employee_id", by_emp), ("email", by_email), ("name", by_name)):
            key = _text(cell(field)).lower()
            if key and key in table:
                pid = table[key]
                break
        if not pid:
            # Name the row by whatever it DID carry, so the report says which person to fix
            # rather than just how many rows failed.
            label = (_text(cell("employee_id"))
                     or _text(cell("email"))
                     or _text(cell("name"))
                     or "(blank)")
            if label not in seen_unmatched:
                seen_unmatched.add(label)
                unmatched.append({"identifier": label})
            skipped += 1
            continue

        in_time = _to_hhmm(cell("in_time"))
        out_time = _to_hhmm(cell("out_time"))
        if not in_time:
            skipped += 1          # no IN punch is not a day worked, it is a blank row
            continue

        verdict = evaluate_day(in_time, out_time, shift)
        res = await col.update_one(
            {"company_id": str(company_id), "person_id": pid, "date": date},
            {"$set": {
                "company_id": str(company_id),
                "person_id": pid,
                "date": date,
                "period": date[:7],
                "in_time": in_time,
                "out_time": out_time,
                **verdict,
                "imported_by": (user or {}).get("full_name") or (user or {}).get("email"),
                "imported_at": datetime.utcnow(),
                "source_file": filename,
            }},
            upsert=True,
        )
        if res.upserted_id is not None:
            imported += 1
        else:
            updated += 1

    logger.info("IRM attendance import [company=%s file=%s]: %d new, %d updated, %d skipped",
                company_id, filename, imported, updated, skipped)
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "unmatched": unmatched[:25],
        "unmatched_count": len(unmatched),
        "shift": shift,
    }


# ─────────────────────────────────────────────────────────────
# Scoring input + export
# ─────────────────────────────────────────────────────────────
async def attendance_totals(company_id: str, period: str,
                            people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {present, punctual, late_in, early_out, missing_out}} for the month.

    The stored verdict is recomputed from the punches rather than trusted, so changing the
    shift rule re-scores history on the next read instead of needing every file re-imported.
    """
    shift = await get_shift(company_id)
    totals = {pid: {"present": 0, "punctual": 0, "late_in": 0,
                    "early_out": 0, "missing_out": 0} for pid in people}

    rows = await get_collection(COLL_IRM_ATTENDANCE).find({
        "company_id": str(company_id), "period": str(period),
    }).to_list(20000)

    for r in rows:
        cell = totals.get(str(r.get("person_id")))
        if cell is None:
            continue      # imported for someone no longer on the active roster
        verdict = evaluate_day(r.get("in_time"), r.get("out_time"), shift)
        if not verdict["present"]:
            continue
        cell["present"] += 1
        for key in ("punctual", "late_in", "early_out", "missing_out"):
            if verdict[key]:
                cell[key] += 1
    return totals


async def export_attendance(company_id: str, period: Optional[str],
                            people: Dict[str, dict]) -> bytes:
    """The stored punches as an .xlsx, in exactly the shape the importer reads back.

    Round-tripping matters: the export is how an admin corrects a bad import, so a file
    that cannot be re-imported would make the pair useless.
    """
    import pandas as pd

    query = {"company_id": str(company_id)}
    if period:
        query["period"] = str(period)
    rows = await get_collection(COLL_IRM_ATTENDANCE).find(query).sort("date", 1).to_list(50000)
    shift = await get_shift(company_id)

    columns = columns_for(people)
    records = []
    for r in rows:
        person = people.get(str(r.get("person_id"))) or {}
        verdict = evaluate_day(r.get("in_time"), r.get("out_time"), shift)
        records.append({
            "Employee ID": person.get("employee_id") or "",
            "Name": person.get("name") or "",
            "Email": person.get("email") or "",
            "Date": r.get("date") or "",
            "In Time": r.get("in_time") or "",
            "Out Time": r.get("out_time") or "",
            "Late In": "Yes" if verdict["late_in"] else "No",
            "Early Out": "Yes" if verdict["early_out"] else "No",
            "Punctual": "Yes" if verdict["punctual"] else "No",
        })

    frame = pd.DataFrame(records, columns=columns)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Attendance")
    buffer.seek(0)
    return buffer.getvalue()


def blank_template() -> bytes:
    """An empty file with the expected headers, for a company with nothing imported yet.

    Without it the export of an empty month is a zero-row sheet with no columns, which
    tells an admin nothing about what to fill in.
    """
    return roster_template({})


def roster_template(people: Dict[str, dict]) -> bytes:
    """The import template: the expected headers, plus one row per person on the roster.

    Pre-filling the identity columns is the point. The importer matches on Employee ID,
    then Email, then Name, and the commonest way an import fails is a file whose employee
    codes are not the ones this system holds — every row lands in `unmatched` and nothing
    scores. Handing back the identifiers that WILL match turns that from a debugging
    session into a copy-paste.

    Date, In Time and Out Time are left blank: one row per person per day is what the
    importer expects, so these rows are the starting point rather than the whole month.

    The Employee ID column appears only for a roster that has employee codes — see columns_for.
    """
    import pandas as pd

    columns = columns_for(people)
    records = [{
        "Employee ID": p.get("employee_id") or "",
        "Name": p.get("name") or "",
        "Email": p.get("email") or "",
        "Date": "",
        "In Time": "",
        "Out Time": "",
        # Derived by the importer from the punches and the shift, never read from the file.
        # Present so the template and the export are the same shape and round-trip cleanly.
        "Late In": "",
        "Early Out": "",
        "Punctual": "",
    } for p in sorted(people.values(), key=lambda x: (x.get("name") or "").lower())]

    frame = pd.DataFrame(records, columns=columns)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Attendance")
    buffer.seek(0)
    return buffer.getvalue()
