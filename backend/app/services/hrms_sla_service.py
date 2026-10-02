"""HRMS > SLA / TAT tracking (internal recruitment track).

SOP §8 gives six milestones and a target for each. This module answers two questions about
them: how long did it take, and is anything late.

-- Working days, and which days those are ---------------------------------------------------
Targets are in WORKING days. Weekends are ALWAYS excluded. Public holidays are excluded only
for a company that has opted in and keeps a calendar (Phase INT-6, `honour_holidays`).

The opt-in is the design, not a hedge. Holidays are per-company and per-region, so two
entities looking at the same three-day gap can legitimately disagree about whether a
requisition breached -- and the answer is to let each say which days it does not work, not to
force one answer on both. It ships OFF because turning it on CHANGES WHETHER EXISTING
REQUISITIONS READ AS BREACHED, which is a business decision with a visible date rather than
something that should arrive with a deploy.

The calendar is HRMS's own (`hrms_holidays`), never the ERP's global `holidays` master --
that collection has no company_id, so one admin's edit would move every entity's due dates.
See hrms_holiday_service.

`GET /requisitions/{no}/sla` reports `counts_holidays` and a plain-English `basis`, so nobody
has to read this comment to know what the figure in front of them counts.

-- Computed on read, never stored --------------------------------------------------------
Only the ACTUAL timestamps are stored, stamped by the services at the moment each milestone
happens (see the `sla_actuals.*` writes in the requisition, candidate, interview and offer
services). Targets, elapsed days and breach status are derived here every time.

Storing a computed breach flag would mean a requisition that is late today is still marked
late after somebody extends the deadline, and a target changed in the SOP would need a
migration to take effect. Derivation costs microseconds and cannot go stale.

-- Two milestones are not measured in working days ------------------------------------------
Induction is due on the joining DATE (Day 1), and the probation review before the probation
END date. Both are absolute dates the records already carry.

Phase INT-2 brings them INTO the SLA table rather than leaving them as a hand-written extra
pass. The table carries an explicit `anchor` discriminator -- "milestone" or "date" -- and
this module picks an evaluator per row. That matters for one concrete reason:
`sweep_open_breaches()` iterates whatever `sla_for` returns, so the date-anchored rows are
picked up by the breach sweep with no new sweep code, and a seventh milestone added later is
a table entry rather than a third code path.

The two evaluators differ in what they can honestly report. A milestone row knows how long
something TOOK (working days between two stamps). A date row does not -- there is no start,
only a deadline -- so its `target_working_days` and `working_days_taken` are null rather than
a number invented to fill the column.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    ANCHOR_DATE, ANCHOR_MILESTONE, AUDIT_SLA_BREACHED, COLL_ONBOARDING,
    COLL_PROBATION_REVIEWS, COLL_REQUISITIONS, ENTITY_REQUISITION, SLA_MILESTONES,
    STAMPABLE_MILESTONES, ProbationOutcome, REQUISITION_TRACK_INTERNAL,
)
from app.services.hrms_audit_service import audit

# Saturday and Sunday. Named rather than inlined as `>= 5`, because the next person to read
# it should not have to remember which end of the week Python's weekday() starts at.
WEEKEND = {5, 6}

# The furthest either working-day walk will step before giving up. A real target is days or
# weeks; this only bites if a calendar marks so much of the year non-working that the walk
# cannot finish, which is a data error rather than a case to support.
MAX_CALENDAR_SPAN_DAYS = 2000


def _as_date(value):
    """A UTC date from a datetime, an ISO string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_working(day, holidays: Optional[set]) -> bool:
    """Whether one date is time somebody had to work with.

    `holidays` of None means this company does not honour a calendar -- weekends only, which
    is the pre-INT-6 answer and the default. An EMPTY SET is a different answer: it honours a
    calendar that happens to have no dates in it. See `holiday_set` for why those must not
    collapse into one.
    """
    if day.weekday() in WEEKEND:
        return False
    return not (holidays and day.isoformat() in holidays)


def working_days_between(start, end, holidays: Optional[set] = None) -> Optional[int]:
    """Working days from `start` to `end`, counting neither endpoint twice.

    Same-day is 0. A Friday to the following Monday is 1, not 3 -- the weekend is not time
    anybody had to work with. Returns None if either end is unreadable, and a NEGATIVE count
    if `end` precedes `start`, which is a data problem the caller should see rather than one
    this function should quietly clamp to zero.

    ── Phase INT-6 ── `holidays` is a set of ISO dates this company does not work. It is an
    ARGUMENT rather than a lookup because this function is PURE and a great deal depends on
    that: the tests walk it directly, and a version that reached into the database for a
    company row could not be called from a report or a test without one.
    """
    first, last = _as_date(start), _as_date(end)
    if first is None or last is None:
        return None
    sign = 1
    if last < first:
        first, last, sign = last, first, -1

    days = 0
    cursor = first
    while cursor < last:
        cursor += timedelta(days=1)
        if _is_working(cursor, holidays):
            days += 1
    return days * sign


def add_working_days(start, count: int, holidays: Optional[set] = None):
    """The date `count` working days after `start`. Non-working days are skipped, not consumed.

    Bounded rather than unbounded: a calendar that somehow marked every day non-working would
    otherwise spin forever. `MAX_CALENDAR_SPAN_DAYS` is far past any real target, so hitting
    it means the calendar is wrong, and returning the date reached is more useful than
    hanging.
    """
    cursor = _as_date(start)
    if cursor is None:
        return None
    remaining = max(0, int(count))
    guard = 0
    while remaining and guard < MAX_CALENDAR_SPAN_DAYS:
        cursor += timedelta(days=1)
        guard += 1
        if _is_working(cursor, holidays):
            remaining -= 1
    # A target landing on a non-working day is pulled BACK to the previous working one, so
    # "due Saturday" -- or due on a holiday -- never appears on a report.
    guard = 0
    while not _is_working(cursor, holidays) and guard < MAX_CALENDAR_SPAN_DAYS:
        cursor -= timedelta(days=1)
        guard += 1
    return cursor


def _status(target_days: int, started, actual, today,
            holidays: Optional[set] = None) -> tuple:
    """(status, working_days_taken, days_over) for one milestone."""
    if started is None:
        # The clock has not begun: the milestone this one is measured from has not happened.
        return "not_started", None, None
    if actual is not None:
        taken = working_days_between(started, actual, holidays)
        if taken is None:
            return "unknown", None, None
        return ("met" if taken <= target_days else "breached",
                taken, max(0, taken - target_days))
    elapsed = working_days_between(started, today, holidays)
    if elapsed is None:
        return "unknown", None, None
    if elapsed > target_days:
        return "overdue", elapsed, elapsed - target_days
    return "pending", elapsed, 0


async def sla_for(company_id: str, req: dict, *, config: dict = None,
                  calendar: Optional[set] = None) -> dict:
    """Every milestone for one requisition: target, actual, and whether it was met.

    Returns a `not_applicable` payload for a client requisition rather than raising -- the
    caller is usually a screen rendering whatever it was given, and an error for "this track
    has no SLA" would be an exception used as a value.
    """
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return {"request_no": (req or {}).get("request_no"),
                "applicable": False,
                "reason": "Legacy client-track requisition: not part of hiring.",
                "milestones": []}

    actuals = req.get("sla_actuals") or {}
    raised_at = req.get("created_at")
    today = datetime.now(timezone.utc)

    # ── Phase INT-5 ── this company's targets, which are the shipped ones unless it has
    # said otherwise. `config` is accepted pre-resolved so a caller sweeping hundreds of
    # requisitions reads the settings row ONCE rather than once per requisition.
    from app.services.hrms_config_service import sla_target_days
    from app.services.hrms_holiday_service import holiday_set
    resolved = config if config is not None else company_id
    targets = await sla_target_days(resolved)
    # ── Phase INT-6 ── None means this company does not honour a calendar (weekends only,
    # the default); a SET means it does, even when the set is empty. Accepted pre-resolved
    # for the same reason `targets` is: a sweep reads it once, not once per requisition.
    holidays = (calendar if calendar is not None
                else await holiday_set(resolved, company_id))

    # One loop over ONE table. The discriminator picks the evaluator; nothing here knows
    # which milestones happen to be of which kind, which is what keeps a seventh one a data
    # change rather than a third branch.
    rows = []
    for spec in SLA_MILESTONES:
        if spec["anchor"] == ANCHOR_MILESTONE:
            rows.append(_milestone_row(spec, actuals, raised_at, today, targets,
                                       holidays))
        elif spec["anchor"] == ANCHOR_DATE:
            rows += await _date_rows(company_id, req, spec, today)
        else:
            # An unknown anchor is a programming error, and reporting the milestone as
            # "unknown" is more honest than silently dropping it from a compliance figure.
            rows.append({"key": spec["key"], "label": spec["label"],
                         "target_working_days": None, "measured_from": None,
                         "started_at": None, "due_on": None, "actual_at": None,
                         "status": "unknown", "working_days_taken": None,
                         "working_days_over": None})

    breached = [r for r in rows if r["status"] in ("breached", "overdue")]
    return {
        "request_no": req.get("request_no"),
        "applicable": True,
        # Reported rather than assumed. A reader must never have to guess which basis
        # produced the number in front of them, and the two bases give different answers
        # about the same three-day gap.
        "counts_holidays": holidays is not None,
        "holidays_in_calendar": (len(holidays) if holidays is not None else None),
        "basis": ("Working days, excluding weekends and this company's own holiday calendar."
                  if holidays is not None else
                  "Working days, excluding weekends. This company does not honour a holiday "
                  "calendar -- see HRMS settings."),
        "milestones": rows,
        "breached": [r["key"] for r in breached],
        "on_track": not breached,
        "as_of": today,
    }


def _milestone_row(spec: dict, actuals: dict, raised_at, today: datetime,
                   targets: dict = None, holidays: Optional[set] = None) -> dict:
    """Evaluate a MILESTONE-anchored row: N working days after a preceding stamp.

    `measured_from` of None means the clock starts at the requisition itself, which is the
    only case where the start is not another milestone.

    `targets` is this company's target table (Phase INT-5). Falling back to the spec's own
    number when a key is absent keeps this function callable with no config at all, which is
    what every pre-INT-5 test does and what the module default is.
    """
    measured_from = spec.get("measured_from")
    target_days = (targets or {}).get(spec["key"], spec["target_days"])
    started = raised_at if measured_from is None else actuals.get(measured_from)
    actual = actuals.get(spec["key"])
    status, taken, over = _status(target_days, started, actual, today, holidays)
    return {
        "key": spec["key"],
        "label": spec["label"],
        "anchor": ANCHOR_MILESTONE,
        "target_working_days": target_days,
        "measured_from": measured_from or "requisition raised",
        "started_at": started,
        "due_on": (add_working_days(started, target_days, holidays).isoformat()
                   if started is not None else None),
        "actual_at": actual,
        "status": status,
        "working_days_taken": taken,
        "working_days_over": over,
    }


# How a date-anchored obligation is judged DONE, per milestone key.
#
# A table rather than a branch, for the same reason SLA_MILESTONES is one: "what counts as
# having done the induction" is a rule, and a rule belongs somewhere a reader can find it
# rather than inside the loop that happens to apply it.
#
# Each entry takes the record and returns (done, actual_at).
def _induction_done(doc: dict) -> tuple:
    items = [i for i in (doc.get("checklist") or []) if i.get("induction")]
    if not items:
        # A client-track onboarding has no induction items at all. Returning None here is
        # what makes the row disappear rather than report a breach nobody owes.
        return None, None
    if not all(i.get("done") for i in items):
        return False, None
    stamps = [i.get("done_at") for i in items if i.get("done_at")]
    return True, (max(stamps) if stamps else None)


def _probation_done(doc: dict) -> tuple:
    decided = doc.get("outcome") != ProbationOutcome.PENDING.value
    return decided, (doc.get("confirmed_at") if decided else None)


DATE_MILESTONE_DONE = {
    "induction_due":        _induction_done,
    "probation_review_due": _probation_done,
}


async def _date_rows(company_id: str, req: dict, spec: dict, today: datetime) -> list:
    """Evaluate a DATE-anchored row: due ON a date the record carries.

    One row PER RECORD, not one per requisition. A requisition that hired three people owes
    three inductions, and an aggregate "induction done" would hide the one person nobody
    inducted -- which is the only case the milestone exists to catch.

    Shaped honestly: `target_working_days` and `working_days_taken` are null, because there
    is no elapsed-time target here and reporting one would be inventing a number.
    """
    request_no = req.get("request_no")
    is_done = DATE_MILESTONE_DONE.get(spec["key"])
    if not is_done:
        return []

    id_field, name_field, due_field = spec["id_field"], spec["name_field"], spec["due_field"]
    docs = await get_collection(spec["collection"]).find(
        {"company_id": str(company_id), "request_no": request_no}).to_list(200)

    today_date = today.date()
    rows = []
    for doc in docs:
        done, actual = is_done(doc)
        if done is None:
            continue                       # not applicable to this record
        due = _as_date(doc.get(due_field))
        if done:
            # Met LATE is still a breach: the whole point of a date-anchored milestone is
            # that Day 1 was Day 1. Only a stamp we can actually read is judged, though --
            # an induction ticked with no timestamp reads as met rather than as a breach
            # somebody cannot investigate.
            actual_date = _as_date(actual)
            status = ("breached" if (due is not None and actual_date is not None
                                     and actual_date > due) else "met")
        elif due is not None and today_date > due:
            status = "overdue"
        else:
            status = "pending"
        rows.append({
            # Suffixed with the record id: one requisition legitimately has several of
            # these, and a shared key would make the breach guard fire once for all of them.
            "key": f'{spec["key"]}:{doc.get(id_field)}',
            "milestone": spec["key"],
            "label": f'{spec["label"]} — {doc.get(name_field) or doc.get(id_field)}',
            "anchor": ANCHOR_DATE,
            "target_working_days": None,
            "measured_from": spec["measured_from"],
            "started_at": None,
            "due_on": due.isoformat() if due else None,
            "actual_at": actual,
            "status": status,
            "working_days_taken": None,
            "working_days_over": None,
        })
    return rows


# ─────────────────────────────────────────────────────────────
# Stamping and escalation
# ─────────────────────────────────────────────────────────────
async def stamp(company_id: str, request_no: str, key: str, *,
                when: datetime = None, once: bool = True) -> bool:
    """Record that a milestone happened. Returns True if this call was the one that set it.

    `once` is the default because a milestone is a FIRST occurrence: the second offer on a
    requisition is not a second breach of the same three-day target, and overwriting the
    stamp would make a late requisition look punctual.
    """
    if not request_no:
        return False
    # A date-anchored milestone has nothing to stamp -- its due date IS a field on another
    # record -- so stamping one would write a value `sla_for` never reads and quietly make a
    # caller think it had recorded something. Loud, because it is a programming error.
    if key not in STAMPABLE_MILESTONES and key != "final_selection":
        raise ValueError(
            f"'{key}' is not a stampable SLA milestone. Stampable: "
            f"{', '.join(sorted(STAMPABLE_MILESTONES))} (plus 'final_selection', which is a "
            f"clock START rather than a milestone of its own).")
    coll = get_collection(COLL_REQUISITIONS)
    query = {"request_no": request_no, "company_id": str(company_id)}
    if once:
        query[f"sla_actuals.{key}"] = None
    result = await coll.update_one(
        query, {"$set": {f"sla_actuals.{key}": when or datetime.now(timezone.utc)}})
    return result.modified_count > 0


async def stamp_if_internal(actor: Optional[dict], company_id: str, request_no: str,
                            key: str, *, when: datetime = None) -> None:
    """Stamp a milestone on an internal requisition, and escalate if it landed late.

    Best-effort by contract: SLA reporting must never be the reason a real operation fails.
    A stamp that does not happen shows up as a missing actual, which reads as overdue -- the
    safe direction for a compliance figure to fail in.
    """
    try:
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": request_no, "company_id": str(company_id)})
        if not req:
            return
        track = req.get("requisition_track")
        if track != REQUISITION_TRACK_INTERNAL:
            return
        if not await stamp(company_id, request_no, key, when=when):
            return
        fresh = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": request_no, "company_id": str(company_id)})
        await escalate_if_breached(actor, company_id, fresh, key)
    except Exception as e:
        print(f"[WARN] HRMS SLA stamp failed for {request_no}/{key}: {e}")


async def escalate_if_breached(actor: Optional[dict], company_id: str, req: dict,
                               key: str, *, config: dict = None,
                               calendar: Optional[set] = None) -> bool:
    """Notify HR and Management when a milestone is recorded late. Returns True if it fired.

    Fires ONCE per milestone, guarded by `sla_escalated`. An alert that repeats every time a
    figure is recomputed trains people to ignore it, which is worse than not alerting at all.
    """
    report = await sla_for(company_id, req, config=config, calendar=calendar)
    row = next((r for r in report.get("milestones", []) if r["key"] == key), None)
    if not row or row["status"] not in ("breached", "overdue"):
        return False
    if key in set(req.get("sla_escalated") or []):
        return False

    request_no = req.get("request_no")
    await get_collection(COLL_REQUISITIONS).update_one(
        {"request_no": request_no, "company_id": str(company_id)},
        {"$addToSet": {"sla_escalated": key}})

    # Two milestone kinds, two honest sentences. A date-anchored row has no elapsed time to
    # report, and printing "took None working days against a target of None" is how a
    # compliance alert becomes noise somebody learns to ignore.
    if row.get("anchor") == ANCHOR_DATE:
        detail = (f'{row["label"]} was due on {row.get("due_on") or "an unrecorded date"} '
                  f'({row["measured_from"]}) and is {row["status"]}.')
    else:
        over = row.get("working_days_over")
        detail = (f'{row["label"]} took {row.get("working_days_taken")} working day(s) '
                  f'against a target of {row["target_working_days"]}'
                  + (f" -- {over} over." if over else "."))
    await audit(actor, AUDIT_SLA_BREACHED, ENTITY_REQUISITION, request_no, detail,
                company_id)

    from app.services.hrms_notify_service import notify_hrms_role
    await notify_hrms_role(
        company_id, ["HR", "MD"],
        f"SLA breached on {request_no}",
        f'{detail} ({req.get("designation_name") or "the role"})',
        kind="warning", link=f"/hrms/requisitions/{request_no}", email=True)
    return True


async def sweep_open_breaches(actor: Optional[dict], company_id: str, *,
                              notify: bool = True, config: dict = None) -> dict:
    """Find internal requisitions with an OVERDUE, still-incomplete milestone.

    The other half of breach detection. `escalate_if_breached` catches a milestone recorded
    late; this catches the more dangerous case -- one that has not been recorded at all,
    where nothing happens to trigger an alert precisely because nothing is happening.

    Driven daily by `hrms_scheduler_service` (Phase INT-3), which the ERP's existing
    reminder loop calls. Still safe to call by hand: `escalate_if_breached` guards on
    `sla_escalated`, so a milestone already announced is never announced twice.

    It is deliberately not fired from an HTTP request -- that would make alerting depend on
    somebody opening a screen.
    """
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id),
         "requisition_track": REQUISITION_TRACK_INTERNAL,
         "closing_status": "Open"}).to_list(1000)

    # Resolved ONCE for the whole sweep. Reading it inside the loop would be one settings
    # read per open requisition, and would also let a mid-sweep edit judge the first half of
    # the run against different targets from the second.
    from app.services.hrms_config_service import config_for
    from app.services.hrms_holiday_service import holiday_set
    resolved = config if config is not None else await config_for(company_id)
    # The calendar is read ONCE for the whole sweep, for the same two reasons the config is:
    # one read instead of one per requisition, and one basis for the whole run.
    calendar = await holiday_set(resolved, company_id)

    breaches, notified = [], 0
    for req in reqs:
        report = await sla_for(company_id, req, config=resolved, calendar=calendar)
        for row in report.get("milestones", []):
            if row["status"] != "overdue":
                continue
            breaches.append({"request_no": req.get("request_no"),
                             "designation": req.get("designation_name"),
                             "milestone": row["key"], "label": row["label"],
                             "due_on": row["due_on"],
                             "working_days_over": row["working_days_over"]})
            if notify and await escalate_if_breached(actor, company_id, req, row["key"],
                                                     config=resolved, calendar=calendar):
                notified += 1

    return {"checked": len(reqs), "breaches": breaches, "notified": notified,
            "as_of": datetime.now(timezone.utc)}
