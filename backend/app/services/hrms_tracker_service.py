"""HRMS ▸ the internal requisition tracker (Phase INT-7, Annexure C + spec §35).

Annexure C, first efficiency item: *"Maintain a shared internal requisition tracker (status,
scores, budget approval date) visible to HR, Department Head, and Management."*

The screen existed and showed five columns -- requisition, seats, approved band, waiting on,
actions. That answers "what is this requisition" and not the question people actually open a
tracker with, which is **where has everything got to, and what is late**. This service answers
that one, in one row per requisition.

-- READ-ONLY, and structurally so ------------------------------------------------------------
Nothing here writes. `test_int7_tracker` greps this module's SOURCE TEXT for the three write
prefixes, exactly as `test_phase10_analytics` does for the analytics service. The check is on
the text, not the behaviour, so **naming a write method anywhere in this file -- including in
a comment or a docstring -- fails the test**. That is deliberate: a grep nobody can talk their
way around is worth more than one that reads intent.

-- BATCHED, because the obvious implementation is quadratic ------------------------------------
A row needs candidate counts, scorecard state, shortlist state, interview state, offer state,
joining and probation dates, exceptions and SLA. Fetching those per requisition is eight
queries times N, and N grows with every vacancy the company ever raised.

So every collection is read ONCE for the whole page with `request_no: {"$in": [...]}`, and the
rows are assembled in memory. Eight queries for the page, whatever N is. The `$in` list is
built from the already-scoped requisition page, so it can never widen the scope -- and an
empty page short-circuits rather than issuing eight `$in: []` reads.

-- The SLA column is MILESTONE-anchored only ---------------------------------------------------
`sla_for` also evaluates two DATE-anchored milestones (induction on Day 1, the probation
review before its end date), and those are per-RECORD: one requisition that hired three people
owes three inductions. They cannot honestly collapse into one requisition-level cell, and
fetching them would put two more queries per row back into the loop this service exists to
avoid. So the tracker reports the milestone rows -- which need no query at all, being computed
from `sla_actuals` -- and `GET /requisitions/{no}/sla` remains the full picture. The payload
says so in `sla_basis` rather than leaving a reader to assume the cell covers everything.
"""
from datetime import datetime, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    ANCHOR_MILESTONE, AppStatus, COLL_CANDIDATES, COLL_EXCEPTIONS, COLL_INTERVIEWS,
    COLL_JOB_POSTINGS, COLL_OFFERS, COLL_ONBOARDING, COLL_POSITION_SCORECARDS,
    COLL_PROBATION_REVIEWS, COLL_REQUISITIONS, COLL_SHORTLIST_REVIEWS, SLA_MILESTONES,
    COLL_DESIGNATIONS, STAGE_RANK, ExceptionStatus, InterviewStatus, OfferStatus,
    ProbationOutcome, REQUISITION_TRACK_INTERNAL, ScorecardStatus, ShortlistOutcome,
    designation_level,
)

# One page of the tracker. Deliberately smaller than the analytics SCAN_CAP: this is a screen
# somebody reads, not an export, and a thousand-row table helps nobody.
MAX_TRACKER_ROWS = 200

# Statuses that mean a candidate is past the interview stage. Read from STAGE_RANK rather than
# listed, so a stage added later cannot silently stop counting.
_SELECTED_RANK = STAGE_RANK[AppStatus.SELECTED]
_INTERVIEW_RANK = STAGE_RANK[AppStatus.INTERVIEW_SCHEDULED]
_SHORTLIST_RANK = STAGE_RANK[AppStatus.SHORTLISTED]

JOINED_STATUSES = {AppStatus.JOINED.value, AppStatus.EMPLOYEE_CREATED.value,
                   AppStatus.PROBATION_CONFIRMED.value}


def _rank(status) -> int:
    try:
        return STAGE_RANK.get(AppStatus(status), 0)
    except (ValueError, TypeError):
        return 0


def _group(rows: list, key: str = "request_no") -> dict:
    out: dict = {}
    for row in rows:
        out.setdefault(row.get(key), []).append(row)
    return out


def _sla_summary(req: dict, targets: dict, holidays: Optional[set],
                 today: datetime) -> dict:
    """The milestone-anchored SLA picture for one requisition, computed with no query.

    Returns the worst status on the requisition plus the NEXT thing owed, because those are
    the two facts a tracker row has room for: is this late, and what is it waiting on.
    """
    from app.services.hrms_sla_service import _milestone_row

    actuals = req.get("sla_actuals") or {}
    raised_at = req.get("created_at")

    rows = [_milestone_row(spec, actuals, raised_at, today, targets, holidays)
            for spec in SLA_MILESTONES if spec["anchor"] == ANCHOR_MILESTONE]

    breached = [r for r in rows if r["status"] in ("breached", "overdue")]
    # The next thing owed is the first row still running. Rows are in SOP order, which is the
    # order they fall due, so "first pending" is the right one to surface.
    pending = next((r for r in rows if r["status"] == "pending"), None)
    nxt = pending or next((r for r in rows if r["status"] == "not_started"), None)

    if breached:
        status = "breached"
    elif pending:
        status = "on_track"
    elif all(r["status"] in ("met", "not_started") for r in rows):
        status = "met" if any(r["status"] == "met" for r in rows) else "not_started"
    else:
        status = "unknown"

    return {
        "status": status,
        "breached": [r["key"] for r in breached],
        "breached_labels": [r["label"] for r in breached],
        "next_key": (nxt or {}).get("key"),
        "next_label": (nxt or {}).get("label"),
        "next_due_on": (nxt or {}).get("due_on"),
        "days_elapsed": (nxt or {}).get("working_days_taken"),
        "days_over": max([r.get("working_days_over") or 0 for r in breached], default=0),
    }


async def tracker(actor: dict, company_id: str, *, status: str = None,
                  department_id: str = None, sla: str = None,
                  limit: int = 100, skip: int = 0) -> dict:
    """One row per internal requisition, with every stage rolled up.

    Scoped exactly as the requisition list is -- same company filter, same visibility rule --
    so a user never sees a row here they could not open there.
    """
    from app.services.hrms_config_service import config_for, sla_target_days
    from app.services.hrms_holiday_service import holiday_set
    from app.services.hrms_requisition_service import _visibility_filter

    limit = max(1, min(int(limit or 100), MAX_TRACKER_ROWS))
    skip = max(0, int(skip or 0))

    query = {"company_id": str(company_id),
             "requisition_track": REQUISITION_TRACK_INTERNAL}
    query.update(_visibility_filter(actor))
    if status:
        query["approval_status"] = status
    if department_id:
        query["department_id"] = department_id

    coll = get_collection(COLL_REQUISITIONS)
    total = await coll.count_documents(query)
    reqs = await coll.find(query).sort("created_at", -1).skip(skip).limit(
        limit).to_list(limit)

    if not reqs:
        return {"rows": [], "total": total, "limit": limit, "skip": skip,
                "sla_basis": _basis(None),
                "as_of": datetime.now(timezone.utc)}

    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    scope = {"company_id": str(company_id), "request_no": {"$in": request_nos}}

    # ── Eight reads for the whole page, not eight per row ──
    scorecards = _group(await get_collection(COLL_POSITION_SCORECARDS).find(
        scope, {"request_no": 1, "scr_no": 1, "status": 1}).to_list(MAX_TRACKER_ROWS * 3))
    postings = _group(await get_collection(COLL_JOB_POSTINGS).find(
        scope, {"request_no": 1, "code": 1, "status": 1}).to_list(MAX_TRACKER_ROWS * 3))
    candidates = _group(await get_collection(COLL_CANDIDATES).find(
        scope, {"request_no": 1, "uk": 1, "candidate_name": 1,
                "application_status": 1}).to_list(MAX_TRACKER_ROWS * 50))
    shortlists = _group(await get_collection(COLL_SHORTLIST_REVIEWS).find(
        scope, {"request_no": 1, "slr_no": 1, "outcome": 1,
                "decided_at": 1}).to_list(MAX_TRACKER_ROWS * 3))
    interviews = _group(await get_collection(COLL_INTERVIEWS).find(
        scope, {"request_no": 1, "status": 1}).to_list(MAX_TRACKER_ROWS * 20))
    offers = _group(await get_collection(COLL_OFFERS).find(
        scope, {"request_no": 1, "offer_no": 1, "status": 1, "uk": 1,
                "candidate_name": 1, "joining_date": 1}).to_list(MAX_TRACKER_ROWS * 5))
    onboardings = _group(await get_collection(COLL_ONBOARDING).find(
        scope, {"request_no": 1, "joining_date": 1, "status": 1}).to_list(
        MAX_TRACKER_ROWS * 5))
    probations = _group(await get_collection(COLL_PROBATION_REVIEWS).find(
        scope, {"request_no": 1, "prb_no": 1, "ends_on": 1,
                "outcome": 1}).to_list(MAX_TRACKER_ROWS * 5))
    exceptions = _group(await get_collection(COLL_EXCEPTIONS).find(
        scope, {"request_no": 1, "status": 1,
                "exception_type": 1}).to_list(MAX_TRACKER_ROWS * 5))

    # The seniority band lives on the designation MASTER, not the requisition -- reading
    # `req["designation_level"]` returns nothing on real documents. One read for the page,
    # resolved with the model's own `designation_level()` so an unbanded designation reads
    # as the default (mid) here exactly as it does in the panel rules.
    level_rows = await get_collection(COLL_DESIGNATIONS).find(
        {"company_id": str(company_id)},
        {"_id": 1, "designation_level": 1}).to_list(2000)
    levels = {str(r["_id"]): designation_level(r).value for r in level_rows}

    company_config = await config_for(company_id)
    targets = await sla_target_days(company_config)
    holidays = await holiday_set(company_config, company_id)
    today = datetime.now(timezone.utc)

    rows = [_row(req, today, targets, holidays, levels,
                 scorecards.get(req.get("request_no")) or [],
                 postings.get(req.get("request_no")) or [],
                 candidates.get(req.get("request_no")) or [],
                 shortlists.get(req.get("request_no")) or [],
                 interviews.get(req.get("request_no")) or [],
                 offers.get(req.get("request_no")) or [],
                 onboardings.get(req.get("request_no")) or [],
                 probations.get(req.get("request_no")) or [],
                 exceptions.get(req.get("request_no")) or [])
            for req in reqs]

    if sla:
        rows = [r for r in rows if r["sla"]["status"] == sla]

    return {
        "rows": rows,
        "total": total,
        "limit": limit,
        "skip": skip,
        "sla_basis": _basis(holidays),
        "as_of": today,
    }


def _basis(holidays: Optional[set]) -> str:
    """What the SLA cell counts, said out loud rather than left to be assumed."""
    days = ("working days, excluding weekends and this company's holiday calendar"
            if holidays is not None else "working days, excluding weekends")
    return (f"Milestone SLA only ({days}). Induction and probation-review deadlines are "
            f"per-joiner rather than per-requisition -- see the requisition's own SLA view.")


def _row(req: dict, today, targets: dict, holidays: Optional[set], levels: dict,
         scorecards: list, postings: list, candidates: list, shortlists: list,
         interviews: list, offers: list, onboardings: list, probations: list,
         exceptions: list) -> dict:
    """Assemble one tracker row. Pure -- every collection has already been read."""
    ranks = [_rank(c.get("application_status")) for c in candidates]

    # The band stamped at the budget gate IS the authority; the salary-band master is a
    # convenience. Same rule the offer check follows.
    band_min = req.get("approved_salary_band_min")
    band_max = req.get("approved_salary_band_max")
    budget_approved_at = req.get("budget_approved_at")

    approved_card = next((s for s in scorecards
                          if s.get("status") == ScorecardStatus.APPROVED.value), None)
    latest_card = approved_card or (scorecards[0] if scorecards else None)

    finalised = next((s for s in shortlists
                      if s.get("outcome") == ShortlistOutcome.FINALISED.value), None)
    latest_shortlist = finalised or (shortlists[0] if shortlists else None)

    # The offer that matters is the one furthest along: accepted beats sent beats draft. A
    # revoked or declined offer is real history but is not what a tracker cell should show
    # while a live one exists.
    offer_rank = {OfferStatus.ACCEPTED.value: 4, OfferStatus.SENT.value: 3,
                  OfferStatus.DRAFT.value: 2, OfferStatus.DECLINED.value: 1,
                  OfferStatus.REVOKED.value: 0}
    live_offer = max(offers, key=lambda o: offer_rank.get(o.get("status"), 0), default=None)

    joiners = [c for c in candidates if c.get("application_status") in JOINED_STATUSES]
    joining_date = (live_offer or {}).get("joining_date") or next(
        (o.get("joining_date") for o in onboardings if o.get("joining_date")), None)

    pending_probation = next((p for p in probations
                              if p.get("outcome") == ProbationOutcome.PENDING.value), None)
    probation = pending_probation or (probations[0] if probations else None)

    open_exceptions = [e for e in exceptions
                       if e.get("status") == ExceptionStatus.PENDING.value]
    approved_exceptions = [e for e in exceptions
                           if e.get("status") == ExceptionStatus.APPROVED.value]

    return {
        # Identity
        "request_no": req.get("request_no"),
        "company_id": req.get("company_id"),
        "department_id": req.get("department_id"),
        "department_name": req.get("department_name"),
        "designation_name": req.get("designation_name"),
        "designation_level": levels.get(str(req.get("designation_id") or "")),
        "vacancy": req.get("vacancy"),
        "raised_by_name": req.get("created_by_name"),
        "hr_owner_name": req.get("assignee_name") or req.get("hr_reviewed_by_name"),
        "raised_at": req.get("created_at"),
        "required_date": req.get("required_date"),

        # Where it is
        "approval_status": req.get("approval_status"),
        "closing_status": req.get("closing_status"),

        # Money
        "budget": {
            "approved": budget_approved_at is not None,
            "approved_at": budget_approved_at,
            "approved_by_name": req.get("budget_approved_by_name"),
            "approved_headcount": req.get("approved_headcount"),
            "band_min": band_min,
            "band_max": band_max,
        },

        # The rubric
        "scorecard": {
            "status": (latest_card or {}).get("status"),
            "scr_no": (latest_card or {}).get("scr_no"),
            "approved": approved_card is not None,
        },

        # Sourcing and the pipeline
        "sourcing": {"postings": len(postings),
                     "codes": [p.get("code") for p in postings if p.get("code")]},
        "candidates": {
            "total": len(candidates),
            "shortlisted": sum(1 for r in ranks if r >= _SHORTLIST_RANK),
            "interviewed": sum(1 for r in ranks if r >= _INTERVIEW_RANK),
            "selected": sum(1 for r in ranks if r >= _SELECTED_RANK),
            "joined": len(joiners),
        },
        "shortlist": {
            "status": (latest_shortlist or {}).get("outcome"),
            "slr_no": (latest_shortlist or {}).get("slr_no"),
            "decided_at": (latest_shortlist or {}).get("decided_at"),
        },
        "interviews": {
            "total": len(interviews),
            "completed": sum(1 for i in interviews
                             if i.get("status") == InterviewStatus.COMPLETED.value),
        },
        "offer": {
            "status": (live_offer or {}).get("status"),
            "offer_no": (live_offer or {}).get("offer_no"),
            "candidate_name": (live_offer or {}).get("candidate_name"),
        },

        # After the hire
        "joining_date": joining_date,
        "probation": {
            "prb_no": (probation or {}).get("prb_no"),
            "ends_on": (probation or {}).get("ends_on"),
            "outcome": (probation or {}).get("outcome"),
        },

        # Governance
        "sla": _sla_summary(req, targets, holidays, today),
        "exceptions": {
            "open": len(open_exceptions),
            "approved": len(approved_exceptions),
            "types": sorted({e.get("exception_type") for e in exceptions
                             if e.get("exception_type")}),
        },
    }
