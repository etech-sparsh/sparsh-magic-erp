"""HRMS ▸ the working calendar (Phase INT-6, spec §26).

SOP §8 states its targets in WORKING days. Weekends have always been excluded; public
holidays have not. This is the phase that lets a company exclude its own.

-- Why HRMS keeps its OWN calendar ----------------------------------------------------------
The ERP already has a `holidays` master, and reading it directly was the obvious
implementation and the wrong one. That collection carries **no `company_id`** -- not on read,
not on write, not even in its duplicate check. It is one global list.

Pointing per-company compliance figures at a global list would mean an admin adding a
regional festival for one entity silently moved every other entity's SLA due dates, and
nobody would see the change on the requisition that breached because of it. That is precisely
the objection recorded when this was first deferred: "two companies looking at the same
three-day gap would disagree about whether a requisition breached". A shared calendar makes
them agree on something neither chose, which is worse.

So the calendar is **per company**, opted into **per company**, and the ERP master is
available as an **import** rather than a live dependency. A company ADOPTS those dates -- an
act somebody takes, with an audit row -- and can then add or remove days without affecting
anybody else.

-- OFF by default, and that is the whole point of the flag ------------------------------------
Turning `honour_holidays` on **changes whether existing requisitions read as breached**. That
is a business decision with a visible date, not something that should arrive with a deploy.
`GET /requisitions/{no}/sla` reports `counts_holidays` so a reader never has to guess which
basis produced the number in front of them.

-- The calendar is small, and stays small ----------------------------------------------------
`MAX_HOLIDAYS` caps it. A working calendar is a year or two of dates; anything larger is an
import that went wrong, and the cap is what stops it turning every SLA computation into a
scan.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_HOLIDAY_ADDED, AUDIT_HOLIDAY_IMPORTED, AUDIT_HOLIDAY_REMOVED, COLL_HOLIDAYS,
    ENTITY_HOLIDAY, MAX_HOLIDAYS, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text

# The ERP's global master. Named here rather than inlined so the ONE place HRMS reads
# another module's collection is obvious to anybody auditing this file.
ERP_HOLIDAY_COLLECTION = "holidays"


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_holidays(company_id: str, *, year: int = None) -> dict:
    query = {"company_id": str(company_id)}
    if year:
        query["holiday_date"] = {"$regex": f"^{int(year)}-"}
    rows = await get_collection(COLL_HOLIDAYS).find(query).sort(
        "holiday_date", 1).to_list(MAX_HOLIDAYS)
    out = [_out(r) for r in rows]
    return {"holidays": out, "total": len(out), "year": year}


async def holiday_set(company_or_config, company_id: str = None) -> Optional[set]:
    """The dates SLA maths must skip for this company, or None when it skips none.

    **None and an empty set are different answers**. `None` means "this company does not honour holidays" -- the
    maths takes its weekends-only path and reports `counts_holidays: false`. An empty set
    means "it does, and has no holidays recorded" -- the maths honours a calendar that
    happens to be empty, and says so. Collapsing them would make a company that opted in but
    has not filled its calendar in indistinguishable from one that opted out, which is the
    difference between "no holidays this quarter" and "nobody set this up".

    Accepts a company id or an already-resolved config, so a caller inside a loop resolves
    once -- the same shape every other Phase INT-5 reader takes.
    """
    from app.services.hrms_config_service import honours_holidays

    if not await honours_holidays(company_or_config):
        return None

    cid = str(company_id if company_id is not None else company_or_config)
    rows = await get_collection(COLL_HOLIDAYS).find(
        {"company_id": cid}, {"holiday_date": 1}).to_list(MAX_HOLIDAYS)
    return {str(r["holiday_date"])[:10] for r in rows if r.get("holiday_date")}


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
def _validate(payload: dict) -> tuple:
    date = clean_text(payload.get("holiday_date"), limit=10)
    if not date or not is_iso_date(date):
        raise HTTPException(
            status_code=422,
            detail="A holiday needs a valid date in YYYY-MM-DD format.")
    name = clean_text(payload.get("holiday_name"), limit=140)
    if not name:
        raise HTTPException(
            status_code=422,
            detail="Name the holiday. A date with no reason on it is one nobody can "
                   "review a year later.")
    return date, name


async def add_holiday(actor: dict, company_id: str, payload: dict) -> dict:
    date, name = _validate(payload)
    coll = get_collection(COLL_HOLIDAYS)

    if await coll.find_one({"company_id": str(company_id), "holiday_date": date}):
        raise HTTPException(
            status_code=409,
            detail=f"{date} is already a non-working day on this calendar.")

    if await coll.count_documents({"company_id": str(company_id)}) >= MAX_HOLIDAYS:
        raise HTTPException(
            status_code=409,
            detail=(f"This calendar already holds {MAX_HOLIDAYS} dates, which is more than "
                    f"a working calendar should need. Remove the years you no longer "
                    f"report on."))

    doc = {
        "company_id": str(company_id),
        "holiday_date": date,
        "holiday_name": name,
        "created_at": datetime.now(timezone.utc),
        "created_by": str((actor or {}).get("_id") or "") or None,
        "created_by_name": (actor or {}).get("full_name") or (actor or {}).get("email"),
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_HOLIDAY_ADDED, ENTITY_HOLIDAY, date, name, company_id)
    return _out(doc)


async def remove_holiday(actor: dict, company_id: str, date: str) -> dict:
    coll = get_collection(COLL_HOLIDAYS)
    doc = await coll.find_one({"company_id": str(company_id), "holiday_date": date})
    if not doc:
        raise HTTPException(status_code=404, detail="No such date on this calendar.")
    await coll.delete_one({"company_id": str(company_id), "holiday_date": date})
    await audit(actor, AUDIT_HOLIDAY_REMOVED, ENTITY_HOLIDAY, date,
                doc.get("holiday_name"), company_id)
    return {"removed": date, "holiday_name": doc.get("holiday_name")}


async def import_from_erp(actor: dict, company_id: str, *, year: int = None) -> dict:
    """Copy dates from the ERP's global holidays master onto THIS company's calendar.

    A copy, deliberately, not a live read -- see the module docstring. Adopting is an act
    with an audit row; inheriting silently is not.

    Skips dates the company already has rather than failing on the first collision: an
    import run twice must be safe, and the second run's useful answer is "nothing new" rather
    than a 409 about a date somebody already agreed with.
    """
    year = int(year or datetime.now(timezone.utc).year)

    query = {"holiday_date": {"$regex": f"^{year}-"}}
    try:
        source = await get_collection(ERP_HOLIDAY_COLLECTION).find(query).to_list(
            MAX_HOLIDAYS)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not read the ERP holiday calendar: {e}")

    # `status` is the ERP master's own active/inactive flag. An inactive holiday is one
    # somebody retired, and importing it would resurrect a date they had already dropped.
    source = [h for h in source
              if (h.get("status") or "active").lower() == "active"
              and is_iso_date(str(h.get("holiday_date") or "")[:10])]

    coll = get_collection(COLL_HOLIDAYS)
    existing = {str(r["holiday_date"])[:10] for r in
                await coll.find({"company_id": str(company_id)},
                                {"holiday_date": 1}).to_list(MAX_HOLIDAYS)}

    now = datetime.now(timezone.utc)
    added, skipped = [], 0
    for row in source:
        date = str(row["holiday_date"])[:10]
        if date in existing:
            skipped += 1
            continue
        if len(existing) + len(added) >= MAX_HOLIDAYS:
            break
        added.append({
            "company_id": str(company_id),
            "holiday_date": date,
            "holiday_name": clean_text(row.get("holiday_name"), limit=140) or "Holiday",
            "imported_from_erp": True,
            "created_at": now,
            "created_by": str((actor or {}).get("_id") or "") or None,
            "created_by_name": (actor or {}).get("full_name") or (actor or {}).get("email"),
        })

    if added:
        await coll.insert_many([dict(d) for d in added])
    await audit(actor, AUDIT_HOLIDAY_IMPORTED, ENTITY_HOLIDAY, str(year),
                f"{len(added)} adopted, {skipped} already present", company_id)
    return {"year": year, "imported": len(added), "already_present": skipped,
            "available": len(source), "holidays": [_out(d) for d in added]}
