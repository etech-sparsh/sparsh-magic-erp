"""HRMS > probation reviews and personnel-file closure (internal recruitment track).

The last gate on an internal hire: did this actually work out.

-- Probation lives on the EMPLOYEE, and is mirrored onto the candidate ----------------------
The review, the rating, the extension and the decision are all employment facts and belong on
the employee record. That has not changed.

What changed in Phase INT-15 is that a confirmation ALSO stamps the candidate's stage as
`Probation Confirmed`, so the recruitment record shows how the hire actually turned out
rather than stopping at `Employee Created`.

The obstacle was never the status; it was the edge. `allowed_next_statuses` grants
ALWAYS_AVAILABLE to every non-terminal stage, so making `Employee Created` non-terminal would
have made `Rejected`, `On Hold` and `Duplicate` legal from a hired employee -- on the CLIENT
track too, which shares this lifecycle. POST_HIRE_STATUSES exists for exactly that: a
post-hire stage advances, and is never parked or rejected. See models/hrms.py.

-- Opened automatically at joining ---------------------------------------------------------
A probation record nobody remembered to create is a probation nobody reviews. The employee-ID
handover opens one for every internal-track joiner, so `GET /probation/due` is answerable
from day one rather than from whenever HR gets round to it.

-- Confirmation closes the requisition ------------------------------------------------------
SOP §7: "Since there is no client handover in this vertical, the requisition is closed
internally once probation confirmation is recorded."
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PERSONNEL_FILE_CLOSED, AUDIT_PROBATION_CONFIRMED, AUDIT_PROBATION_STARTED,
    AUDIT_PROBATION_UPDATED, AUDIT_REQ_CLOSED, AUDIT_STAGE_CHANGED, COLL_CANDIDATES,
    COLL_EMPLOYEE_PROFILES, COLL_ONBOARDING,
    COLL_PROBATION_REVIEWS, COLL_REQUISITIONS, DEFAULT_PROBATION_MONTHS,
    ENTITY_CANDIDATE, ENTITY_PROBATION, ENTITY_REQUISITION, MAX_PROBATION_MONTHS,
    MIN_PROBATION_MONTHS, PROBATION_CRITERIA_KEYS, PROBATION_REVIEW_CRITERIA,
    RECOMMENDATION_OUTCOME,
    RETENTION_YEARS, AppStatus, HrReviewDecision, ProbationOutcome,
    ProbationRecommendation, ReqClosing, REQUISITION_TRACK_INTERNAL,
    can_transition, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _add_months(iso_date: str, months: int) -> str:
    """`iso_date` plus N calendar months, clamped to the end of the target month.

    31 January plus one month is 28 (or 29) February, not "31 February" and not 3 March.
    Probation ends on a date a human agreed to, so rolling into the next month would quietly
    extend somebody's probation by three days.
    """
    year, month, day = (int(p) for p in iso_date.split("-"))
    total = (year * 12) + (month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (next_month_start - timedelta(days=1)).day
    return f"{year:04d}-{month:02d}-{min(day, last_day):02d}"


def _validate_duration(months, low: int = None, high: int = None) -> int:
    """One probation duration, against this company's bounds.

    ── Phase INT-5 ── `low`/`high` come from the company configuration. They are ARGUMENTS
    with the module constants as defaults, so this stays a pure function the tests can walk
    directly and a caller with no config still gets exactly the pre-INT-5 answer.
    """
    low = MIN_PROBATION_MONTHS if low is None else low
    high = MAX_PROBATION_MONTHS if high is None else high
    try:
        value = int(months)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Probation duration must be a number.")
    if not (low <= value <= high):
        raise HTTPException(
            status_code=422,
            detail=(f"Probation must be between {low} and {high} months. "
                    f"The SOP's usual range is 3 to 6."))
    return value


def _validate_rating(value) -> Optional[float]:
    if value is None:
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="The rating must be a number.")
    if not (1 <= rating <= 5):
        raise HTTPException(
            status_code=422,
            detail="The rating is on the same 1-5 scale as the position scorecard.")
    return rating


async def _is_managerial(company_id: str, request_no: str) -> bool:
    """Whether this review's requisition is for a managerial-and-above role.

    The band lives on the designation MASTER (a requisition carries only
    `designation_id`), resolved the way the scheduler resolves it -- by banded ids, so an
    unbanded designation reads as the default (mid) and is not managerial.
    """
    if not request_no:
        return False
    from app.models.hrms import COLL_DESIGNATIONS, MANAGERIAL_LEVELS
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)},
        {"designation_id": 1})
    designation_id = str((req or {}).get("designation_id") or "")
    if not designation_id:
        return False
    rows = await get_collection(COLL_DESIGNATIONS).find(
        {"company_id": str(company_id),
         "designation_level": {"$in": [l.value for l in MANAGERIAL_LEVELS]}},
        {"_id": 1}).to_list(2000)
    return designation_id in {str(r["_id"]) for r in rows}


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_probations(actor: dict, company_id: str, *, outcome: str = None,
                          request_no: str = None, uk: str = None,
                          limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if outcome:
        query["outcome"] = outcome
    if request_no:
        query["request_no"] = request_no
    if uk:
        # Phase INT-15: reachable by candidate, so the candidate page can show how the hire
        # it is describing actually turned out.
        query["uk"] = uk
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_PROBATION_REVIEWS).find(query).sort(
        "ends_on", 1).to_list(limit)
    return {"probation_reviews": [_out(r) for r in rows], "total": len(rows)}


async def due_probations(actor: dict, company_id: str, *, within_days: int = 30) -> dict:
    """Reviews that are due or overdue.

    Split into `overdue` and `due_soon` rather than returned as one sorted list, because
    those are two different conversations: one is a missed commitment, the other is a diary
    entry. A single list sorted by date leaves the reader to work out which is which.
    """
    today = _today()
    horizon = (datetime.now(timezone.utc) + timedelta(days=max(0, int(within_days or 0)))
               ).strftime("%Y-%m-%d")
    rows = await get_collection(COLL_PROBATION_REVIEWS).find(
        {"company_id": str(company_id),
         "outcome": ProbationOutcome.PENDING.value}).sort("ends_on", 1).to_list(500)

    overdue = [_out(r) for r in rows if (r.get("ends_on") or "") < today]
    due_soon = [_out(r) for r in rows
                if today <= (r.get("ends_on") or "") <= horizon]
    return {"overdue": overdue, "due_soon": due_soon,
            "total_pending": len(rows), "as_of": today, "horizon": horizon}


async def get_probation(company_id: str, prb_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"prb_no": prb_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def open_probation(actor: dict, company_id: str, payload: dict,
                         *, silent: bool = False) -> Optional[dict]:
    """Open a probation review for an employee.

    `silent` is used by the automatic opener at employee-ID handover: a probation record that
    already exists is not an error there, it just means somebody opened it by hand first.
    Called directly (from the API) it raises instead, so a duplicate is visible.
    """
    employee_code = clean_text(payload.get("employee_code"), limit=40)
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")

    coll = get_collection(COLL_PROBATION_REVIEWS)
    existing = await coll.find_one({"company_id": str(company_id),
                                    "employee_code": employee_code})
    if existing:
        if silent:
            return None
        raise HTTPException(
            status_code=409,
            detail=(f"{employee_code} already has a probation review "
                    f"({existing.get('prb_no')})."))

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"employee_code": employee_code, "company_id": str(company_id)})
    if not profile:
        raise HTTPException(
            status_code=404, detail="No employee with that code in this company.")

    started_on = payload.get("started_on") or profile.get("joined_on") or _today()
    if not is_iso_date(started_on):
        raise HTTPException(
            status_code=422,
            detail="The probation start must be a valid date in YYYY-MM-DD format.")
    # ── Phase INT-5 ── the duration and its bounds are this company's, not the module's.
    from app.services.hrms_config_service import probation_bounds, retention_years_for
    default_months, low, high = await probation_bounds(company_id)
    months = _validate_duration(payload.get("duration_months") or default_months, low, high)

    year = datetime.now(timezone.utc).year
    prb_no = await next_business_id("probation", str(company_id), year)
    now = datetime.now(timezone.utc)
    ends_on = _add_months(started_on, months)

    doc = {
        "prb_no": prb_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        # Carried so the single analytics scope filter reaches this collection too.
        "request_no": payload.get("request_no") or profile.get("request_no"),
        # ── Phase INT-15 ── the candidate this employee came from, so confirming the
        # probation can stamp the recruitment record too (spec §35: every candidate-linked
        # collection carries `uk`). `source_uk` is the employee profile's own pointer back
        # to the hire; a manually opened probation for somebody who was never a candidate
        # in this system simply carries None and stamps nothing.
        "uk": payload.get("uk") or profile.get("source_uk"),
        "started_on": started_on,
        "duration_months": months,
        "ends_on": ends_on,
        "reviewer_id": clean_text(payload.get("reviewer_id"), limit=40)
        or profile.get("reporting_manager_id"),
        "rating": None,
        "outcome": ProbationOutcome.PENDING.value,
        "extended_to": None,
        "notes": clean_text(payload.get("notes"), limit=2000),
        "confirmed_by": None,
        "confirmed_at": None,
        # SOP §13: employment + 3 years. The floor is computed from the probation end; it is
        # a FLOOR, not a purge date -- nothing in this module ever deletes a record.
        "retention_until": _add_months(
            ends_on, 12 * await retention_years_for(company_id, "probation")),
        "created_at": now,
        "created_by": str(actor.get("_id") or "") if actor else None,
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_PROBATION_STARTED, ENTITY_PROBATION, prb_no,
                f"{employee_code}, ends {ends_on}", company_id)

    # ── Phase INT-9 ── the reviewer owns this from day one, and should not first hear of
    # it from a 30-days-left reminder. In-app only: the scheduler's tiered reminders are
    # the ones that email, and two mails about one review is one too many.
    if doc.get("reviewer_id"):
        from app.services.hrms_notify_service import notify_user
        await notify_user(
            str(doc["reviewer_id"]),
            f"Probation review {prb_no} opened",
            f'{doc.get("employee_name") or employee_code} is on probation until '
            f"{ends_on}. The confirmation decision will be yours before that date.",
            kind="info", link="/hrms/probation", email=False)
    return _out(doc)


async def update_probation(actor: dict, company_id: str, prb_no: str,
                           payload: dict) -> dict:
    coll = get_collection(COLL_PROBATION_REVIEWS)
    current = await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    if current.get("outcome") != ProbationOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{prb_no} is already "{current.get("outcome")}". A decided probation '
                    f"is a record of what was decided, not a working document."))

    updates = {}
    if payload.get("started_on") is not None:
        if not is_iso_date(payload["started_on"]):
            raise HTTPException(
                status_code=422, detail="The start must be a valid YYYY-MM-DD date.")
        updates["started_on"] = payload["started_on"]
    if payload.get("duration_months") is not None:
        from app.services.hrms_config_service import probation_bounds
        _default, low, high = await probation_bounds(company_id)
        updates["duration_months"] = _validate_duration(
            payload["duration_months"], low, high)
    if payload.get("reviewer_id") is not None:
        updates["reviewer_id"] = clean_text(payload["reviewer_id"], limit=40)
    if payload.get("rating") is not None:
        updates["rating"] = _validate_rating(payload["rating"])
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # The end date is derived, never typed. Two fields that must agree are two fields that
    # will eventually disagree.
    if {"started_on", "duration_months"} & set(updates):
        started = updates.get("started_on") or current.get("started_on")
        months = updates.get("duration_months") or current.get("duration_months")
        updates["ends_on"] = _add_months(started, int(months))
        from app.services.hrms_config_service import retention_years_for
        updates["retention_until"] = _add_months(
            updates["ends_on"], 12 * await retention_years_for(company_id, "probation"))

    # Read BEFORE the write: the driver may hand back a live reference, and the update
    # below would then mutate `current` under us -- trap 36's lesson, applied again.
    previous_reviewer = current.get("reviewer_id") or ""
    previous_ends_on = current.get("ends_on")

    # ── Phase INT-9 ── an end date moved through PATCH is the same fact as an extension:
    # the scheduler's tiers for the OLD date have burned, and without re-arming them the
    # new date is never reminded about. Reset on any real change, in either direction --
    # the scheduler marks every reached tier in one sweep, so a shortened date cannot
    # burst.
    if "ends_on" in updates and updates["ends_on"] != previous_ends_on:
        from app.models.hrms import PROBATION_REMINDED_FIELD
        updates[PROBATION_REMINDED_FIELD] = []

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"prb_no": prb_no, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_PROBATION_UPDATED, ENTITY_PROBATION, prb_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    # ── Phase INT-9 ── a review handed to a NEW reviewer must tell them, or their first
    # notice is a 7-days-left tier -- or nothing at all, if the early tiers burned while
    # the review still belonged to somebody else.
    new_reviewer = updates.get("reviewer_id")
    if new_reviewer and new_reviewer != previous_reviewer:
        from app.services.hrms_notify_service import notify_user
        await notify_user(
            str(new_reviewer),
            f"Probation review {prb_no} is now yours",
            f'{current.get("employee_name") or current.get("employee_code")} is on '
            f'probation until {updates.get("ends_on") or current.get("ends_on")}. The '
            f"confirmation decision will be yours before that date.",
            kind="info", link="/hrms/probation", email=False)
    return await get_probation(company_id, prb_no)


# ─────────────────────────────────────────────────────────────
# Phase INT-2 — statutory pre-employment checks (SOP §11)
# ─────────────────────────────────────────────────────────────
async def statutory_state(company_id: str, employee_code: str) -> dict:
    """What is outstanding on an employee's statutory checks. Read-only.

    Returned rather than raised so a screen can show "waiting on: Aadhaar Card, background
    verification" while the probation is still running, and only the CONFIRMATION is
    refused. A control the user meets for the first time at the moment it blocks them is a
    control that reads as a bug.

    Two independent things are checked, and the SOP names both:
      * the linked onboarding's background verification is `Cleared`, and
      * every document type flagged `statutory_required` is `Verified`.
    """
    from app.models.hrms import (
        COLL_DOCUMENTS, COLL_DOCUMENT_TYPES, BgVerification, DocumentOwnerType,
        DocumentStatus,
    )

    outstanding = []
    onboarding = await get_collection(COLL_ONBOARDING).find_one(
        {"company_id": str(company_id), "employee_id": employee_code},
        {"onb_no": 1, "bg_verification": 1})
    bg = (onboarding or {}).get("bg_verification")
    if not onboarding:
        # No linked onboarding at all. That is a profile created by hand rather than through
        # the pipeline, and there is no background check to read -- so this half of the gate
        # has nothing to say. Reported as unknown rather than counted as a pass OR a fail.
        bg = None
    elif bg != BgVerification.CLEARED.value:
        outstanding.append(f"Background verification is '{bg or 'Pending'}', not Cleared.")

    required_types = await get_collection(COLL_DOCUMENT_TYPES).find(
        {"company_id": str(company_id), "statutory_required": True, "active": True},
        {"name": 1}).to_list(100)
    if required_types:
        type_ids = [str(t["_id"]) for t in required_types]
        held = await get_collection(COLL_DOCUMENTS).find(
            {"company_id": str(company_id),
             "owner_type": DocumentOwnerType.EMPLOYEE.value,
             "owner_id": employee_code,
             "type_id": {"$in": type_ids}},
            {"type_id": 1, "type_name": 1, "status": 1}).to_list(200)
        verified = {str(d.get("type_id")) for d in held
                    if d.get("status") == DocumentStatus.VERIFIED.value}
        for t in required_types:
            if str(t["_id"]) not in verified:
                outstanding.append(f"{t.get('name')} is not Verified.")

    return {
        "employee_code": employee_code,
        "onb_no": (onboarding or {}).get("onb_no"),
        "bg_verification": bg,
        "required_documents": [t.get("name") for t in required_types],
        "outstanding": outstanding,
        "complete": not outstanding,
    }


async def assert_statutory_checks_complete(company_id: str, employee: dict) -> None:
    """Refuse to CONFIRM a probation whose statutory checks are still open (SOP §11).

    Confirmation is the moment employment stops being conditional, which is exactly why the
    SOP puts the checks before it rather than before joining: somebody can start work while
    a police verification is in the post, and cannot be made permanent on one.

    Bypassed only by an approved `Statutory Check Waived` exception -- there is no override
    flag, the same rule every other gate on this track follows. That is a real case (a
    verification agency that has gone quiet for three months) and it is one somebody signs.

    Silent for an employee with no requisition: an exception is scoped to a requisition, so
    without one there is nothing to raise a waiver against, and refusing forever would be a
    dead end rather than a control.
    """
    employee_code = (employee or {}).get("employee_code")
    request_no = (employee or {}).get("request_no")
    if not employee_code:
        return

    state = await statutory_state(company_id, employee_code)
    if state["complete"]:
        return

    if request_no:
        from app.services.hrms_exception_service import approved_exception_for
        if await approved_exception_for(company_id, "statutory_check", request_no):
            return

    raise HTTPException(
        status_code=409,
        detail=(f"{employee_code}'s statutory pre-employment checks are not complete, so "
                f"the probation cannot be confirmed. Outstanding: "
                f'{" ".join(state["outstanding"])} '
                + ("Clear them, or log an approved Statutory Check Waived exception."
                   if request_no else
                   "Clear them before confirming.")))


async def submit_review(actor: dict, company_id: str, prb_no: str,
                        payload: dict) -> dict:
    """The reporting manager's review and recommendation (7.5 Stage 12).

    A RECOMMENDATION, not a decision. It scores the five criteria the design names and
    proposes Confirm, Extend or Separate; HR reviews it next and an authorised approver
    decides. Before Stage 12 the manager's opinion and the company's decision were the
    same write, which left nowhere for HR to disagree and no record that they had agreed.

    Re-submittable while the review is still open: a manager who scored the wrong person,
    or who was sent back by HR, corrects it here rather than raising a second review.
    """
    coll = get_collection(COLL_PROBATION_REVIEWS)
    current = await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    if current.get("outcome") != ProbationOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f'{prb_no} was already decided ("{current.get("outcome")}").')

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this review. It decides somebody's employment.")

    raw = getattr(payload.get("recommendation"), "value", payload.get("recommendation"))
    try:
        recommendation = ProbationRecommendation(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=("A recommendation must be one of: "
                    + ", ".join(r.value for r in ProbationRecommendation) + "."))

    scores = {}
    for key in PROBATION_CRITERIA_KEYS:
        value = _validate_rating(payload.get(key))
        if value is None:
            label = dict(PROBATION_REVIEW_CRITERIA)[key]
            raise HTTPException(
                status_code=422,
                detail=f'Score "{label}" from 1 to 5. A recommendation with no assessment '
                       f"behind it cannot be reviewed by anybody else.")
        scores[key] = value

    remarks = clean_text(payload.get("remarks"), limit=2000)
    if recommendation is not ProbationRecommendation.CONFIRM and not remarks:
        word = ("extended" if recommendation is ProbationRecommendation.EXTEND
                else "separated")
        raise HTTPException(
            status_code=422,
            detail=f"Say why you are recommending they be {word}.")

    now = datetime.now(timezone.utc)
    review = {
        **scores,
        "average": round(sum(scores.values()) / len(scores), 2),
        "recommendation": recommendation.value,
        "remarks": remarks,
        "signature": signature,
        "by": str(actor.get("_id") or ""),
        "by_name": actor.get("full_name") or actor.get("email"),
        "at": now,
    }
    await coll.update_one(
        {"prb_no": prb_no, "company_id": str(company_id)},
        # A fresh recommendation invalidates any HR review of the PREVIOUS one -- HR
        # endorsed a recommendation, not a record, and the recommendation has changed.
        {"$set": {"review": review, "hr_review": None,
                  "rating": review["average"], "updated_at": now}})
    await audit(actor, AUDIT_PROBATION_CONFIRMED, ENTITY_PROBATION, prb_no,
                f"manager recommends {recommendation.value} "
                f"(avg {review['average']})", company_id)

    await _notify_hr_review_due(company_id, current, review)
    return _out(await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)}))


async def _notify_hr_review_due(company_id: str, current: dict, review: dict) -> None:
    """Tell HR a recommendation is waiting on them. Best-effort."""
    try:
        from app.services.hrms_notify_service import notify_hrms_role
        await notify_hrms_role(
            company_id, ["HR"],
            f"Probation recommendation: {current.get('employee_name')}",
            f"{review['by_name']} recommends {review['recommendation']} for "
            f"{current.get('employee_name')} ({current.get('prb_no')}). "
            f"Review it before it goes for approval.",
            link="/hrms/probation")
    except Exception as e:                          # pragma: no cover - defensive
        print(f"[WARN] HR probation notification not sent: {e}")


async def hr_review(actor: dict, company_id: str, prb_no: str, payload: dict) -> dict:
    """HR's step between the manager's recommendation and the authorised approval.

    HR endorses or returns. Returning does NOT decide anything -- it sends the review back
    to the manager, which is why the recommendation survives and only the endorsement is
    cleared. An endorsement is what the approver's gate looks for.
    """
    coll = get_collection(COLL_PROBATION_REVIEWS)
    current = await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    if current.get("outcome") != ProbationOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f'{prb_no} was already decided ("{current.get("outcome")}").')
    if not (current.get("review") or {}).get("recommendation"):
        raise HTTPException(
            status_code=409,
            detail=("There is no manager recommendation to review yet. The reporting "
                    "manager completes their review first."))

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422, detail="Type your name to sign this review.")

    raw = getattr(payload.get("decision"), "value", payload.get("decision"))
    try:
        decision = HrReviewDecision(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="An HR review either endorses the recommendation or returns it.")

    remarks = clean_text(payload.get("remarks"), limit=2000)
    if decision is HrReviewDecision.RETURNED and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say what needs to change. A review returned with no reason cannot be "
                   "acted on.")

    now = datetime.now(timezone.utc)
    record = {
        "decision": decision.value, "remarks": remarks, "signature": signature,
        "by": str(actor.get("_id") or ""),
        "by_name": actor.get("full_name") or actor.get("email"),
        "at": now,
    }
    await coll.update_one({"prb_no": prb_no, "company_id": str(company_id)},
                          {"$set": {"hr_review": record, "updated_at": now}})
    await audit(actor, AUDIT_PROBATION_CONFIRMED, ENTITY_PROBATION, prb_no,
                f"HR {decision.value.lower()} the recommendation", company_id)
    return _out(await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)}))


async def confirm_probation(actor: dict, company_id: str, prb_no: str,
                            payload: dict) -> dict:
    """Record the probation decision, and close the requisition if it is a confirmation.

    Annexure B makes the hiring manager accountable here ("Probation review & confirmation --
    Department Head: A/R"), with HR consulted and Management merely informed. The capability
    grant reflects that; this function does not re-derive it.
    """
    coll = get_collection(COLL_PROBATION_REVIEWS)
    current = await coll.find_one({"prb_no": prb_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    if current.get("outcome") != ProbationOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f'{prb_no} was already decided ("{current.get("outcome")}").')

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this decision. It ends or extends employment.")

    raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
    try:
        outcome = ProbationOutcome(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Outcome must be one of: "
                    f"{', '.join(o.value for o in ProbationOutcome if o is not ProbationOutcome.PENDING)}."))
    if outcome is ProbationOutcome.PENDING:
        raise HTTPException(
            status_code=422,
            detail="Pending is the starting state, not a decision. Confirm, extend or end it.")

    # ── §7.5 Stage 12 ── the approval chain. Manager recommends, HR reviews, and only then
    # is there an authorised decision to sign. This is the "written/system confirmation
    # through the approval process" Stage 10 insists on: reaching the end date is not a
    # decision, and neither is one person's opinion of it.
    review = current.get("review") or {}
    hr = current.get("hr_review") or {}
    if not review.get("recommendation"):
        raise HTTPException(
            status_code=409,
            detail=("The reporting manager has not completed their review yet. A probation "
                    "cannot be decided before somebody has assessed it."))
    if hr.get("decision") != HrReviewDecision.ENDORSED.value:
        raise HTTPException(
            status_code=409,
            detail=("HR has not endorsed this recommendation yet."
                    if hr.get("decision") != HrReviewDecision.RETURNED.value
                    else "HR returned this review to the manager. It has to be "
                         "resubmitted and endorsed before it can be approved."))

    remarks = clean_text(payload.get("remarks"), limit=2000)
    now = datetime.now(timezone.utc)
    updates = {
        "outcome": outcome.value,
        "rating": _validate_rating(payload.get("rating")) or current.get("rating"),
        "remarks": remarks,
        "signature": signature,
        "confirmed_by": str(actor.get("_id") or ""),
        "confirmed_by_name": actor.get("full_name") or actor.get("email"),
        "confirmed_at": now,
        "updated_at": now,
    }

    if outcome is ProbationOutcome.EXTENDED:
        extended_to = payload.get("extended_to")
        if not extended_to or not is_iso_date(extended_to):
            raise HTTPException(
                status_code=422,
                detail="An extension needs a new end date. Say when it now ends.")
        if extended_to <= (current.get("ends_on") or ""):
            raise HTTPException(
                status_code=422,
                detail=(f"The new end date must be after the current one "
                        f"({current.get('ends_on')})."))
        updates["extended_to"] = extended_to
        # An extension is not a decision, it is more time -- so the review returns to
        # Pending with a later end date, and shows up in `due` again when that date nears.
        # Recording it as a terminal "Extended" would hide the second review from everybody.
        updates["outcome"] = ProbationOutcome.PENDING.value
        updates["ends_on"] = extended_to
        updates["extension_count"] = int(current.get("extension_count") or 0) + 1
        updates["confirmed_by"] = None
        updates["confirmed_at"] = None
        updates["last_extended_at"] = now
        updates["last_extended_by"] = str(actor.get("_id") or "")
        # ── Phase INT-9 ── re-arm the scheduler's reminder tiers. They are recorded as
        # fired on the RECORD (PROBATION_REMINDED_FIELD), so without this an extended
        # probation would never be reminded about its NEW end date -- the tiers for the old
        # one already burned. An extension is a second review, and it deserves its own
        # 30/15/7/1.
        from app.models.hrms import PROBATION_REMINDED_FIELD
        updates[PROBATION_REMINDED_FIELD] = []

    if outcome is ProbationOutcome.CONFIRMED:
        # §7.5 Stage 12, Confirm branch. Defaults to the probation end date rather than
        # today: a decision signed two weeks late still takes effect from the day the
        # probation actually ended, and pay and benefits run from this date.
        effective = clean_text(payload.get("effective_from"), limit=10)             or current.get("ends_on")
        if effective and not is_iso_date(effective):
            raise HTTPException(
                status_code=422,
                detail="The confirmation effective date must be YYYY-MM-DD.")
        updates["effective_from"] = effective

    if outcome is ProbationOutcome.EXTENDED:
        # §7.5 Stage 12, Extend branch. An extension that names no next review is how a
        # probation quietly becomes indefinite, so the date is recorded; it defaults to
        # the new end date, which is when the next review is actually due.
        next_review = clean_text(payload.get("next_review_on"), limit=10)
        if next_review and not is_iso_date(next_review):
            raise HTTPException(
                status_code=422,
                detail="The next review date must be YYYY-MM-DD.")
        updates["next_review_on"] = next_review or payload.get("extended_to")

    if outcome in (ProbationOutcome.TERMINATED, ProbationOutcome.EXTENDED) and not remarks:
        raise HTTPException(
            status_code=422,
            detail=f'Record why the probation is being {"extended" if outcome is ProbationOutcome.EXTENDED else "ended"}.')

    # ── Phase INT-2 (SOP §11) ── statutory pre-employment checks before CONFIRMATION.
    #
    # Only on confirmation. Extending a probation is what you do when something is still
    # outstanding, and terminating one must never be blocked by paperwork -- gating either
    # would trap somebody in an indefinite probation because a document is missing, which
    # is worse for them than the control is worth.
    #
    # Checked BEFORE anything is written, so a refusal cannot leave a half-decided review.
    if outcome is ProbationOutcome.CONFIRMED:
        await assert_statutory_checks_complete(
            company_id, {"employee_code": current.get("employee_code"),
                         "request_no": current.get("request_no")})

    # Compare-and-swap on the Pending state, the same rule the exception log follows:
    # two deciders clicking at once must not both land -- the loser would re-close the
    # requisition, re-issue the survey and re-notify everybody about a decision already
    # taken (and possibly a DIFFERENT one).
    result = await coll.update_one(
        {"prb_no": prb_no, "company_id": str(company_id),
         "outcome": ProbationOutcome.PENDING.value},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This probation was decided by someone else. Reload and try again.")
    await audit(actor, AUDIT_PROBATION_CONFIRMED, ENTITY_PROBATION, prb_no,
                f"{outcome.value}"
                + (f" to {updates.get('extended_to')}"
                   if outcome is ProbationOutcome.EXTENDED else ""),
                company_id)

    # The employee record carries the outcome, because that is what a reader of the employee
    # asks. The probation record carries the history of how it got there.
    await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
        {"employee_code": current.get("employee_code"), "company_id": str(company_id)},
        {"$set": {"probation_status": updates["outcome"],
                  "probation_prb_no": prb_no,
                  "probation_ends_on": updates.get("ends_on") or current.get("ends_on"),
                  "probation_confirmed_at": updates.get("confirmed_at"),
                  "updated_at": now}})

    requisition_closed = False
    if outcome is ProbationOutcome.CONFIRMED:
        await _stamp_candidate_confirmed(actor, company_id, current)
        requisition_closed = await _close_requisition_on_confirmation(
            actor, company_id, current)
        # ── Phase INT-2 (SOP §10) ── the second experience survey, at the moment the SOP
        # itself names. Best-effort and idempotent per employee, so it can never be the
        # reason a confirmation fails.
        from app.models.hrms import SurveyKind
        from app.services.hrms_survey_service import issue_survey
        await issue_survey(actor, company_id, SurveyKind.PROBATION,
                           employee_code=current.get("employee_code"),
                           request_no=current.get("request_no"),
                           employee_name=current.get("employee_name"))

    # ── Phase INT-9 (spec §38, Annexure B) ── the decision is announced to the people the
    # RACI names. HR runs the next step in every branch -- the personnel file on a
    # confirmation, a second review diary on an extension, an exit on a termination.
    # Management is INFORMED, managerial+ only, and only for the decisions that stand
    # (an extension returns to Pending and will be decided again).
    from app.services.hrms_notify_service import notify_hrms_role
    who = current.get("employee_name") or current.get("employee_code")
    link = "/hrms/probation"
    if outcome is ProbationOutcome.CONFIRMED:
        # The message states only what actually happened: the closer silently declines
        # when the requisition is missing, client-track, or already closed another way,
        # and a notification describing a write that never landed is exactly the failure
        # the notify-after-write rule exists to prevent.
        await notify_hrms_role(
            company_id, ["HR"], f"Probation confirmed: {who}",
            f"{prb_no} is confirmed."
            + (" The requisition is closed." if requisition_closed else "")
            + " The personnel file can now be closed.",
            kind="success", link=link, email=True)
        if await _is_managerial(company_id, current.get("request_no")):
            await notify_hrms_role(
                company_id, ["MD"], f"Probation confirmed: {who}",
                f"{prb_no} was confirmed by "
                f'{updates.get("confirmed_by_name") or "the hiring manager"}.',
                kind="info", link=link, email=False)
    elif outcome is ProbationOutcome.EXTENDED:
        await notify_hrms_role(
            company_id, ["HR"], f"Probation extended: {who}",
            f'{prb_no} now ends on {updates.get("extended_to")}. Reason: '
            f'{remarks or "not recorded"}. The review returns to Pending and will be '
            f"reminded about again.", kind="warning", link=link, email=False)
    elif outcome is ProbationOutcome.TERMINATED:
        await notify_hrms_role(
            company_id, ["HR"], f"Probation not confirmed: {who}",
            f"{prb_no} was ended. Reason: {remarks}. HR owns the exit steps.",
            kind="warning", link=link, email=True)
        # A termination STANDS just as a confirmation does, and Annexure B informs
        # Management of managerial+ probation decisions -- ending a managerial hire is
        # not less their business than confirming one.
        if await _is_managerial(company_id, current.get("request_no")):
            await notify_hrms_role(
                company_id, ["MD"], f"Probation not confirmed: {who}",
                f'{prb_no} was ended by '
                f'{updates.get("confirmed_by_name") or "the hiring manager"}. '
                f"Reason: {remarks}",
                kind="warning", link=link, email=False)

    return await get_probation(company_id, prb_no)


async def _stamp_candidate_confirmed(actor: dict, company_id: str,
                                     probation: dict) -> bool:
    """Move the candidate record to `Probation Confirmed` (SOP §7).

    Best-effort and last-write-wins on the transition table, never a reason a confirmation
    fails: the decision is already committed by the time this runs, and a candidate row that
    was purged or never existed must not undo an employment decision.

    Guarded by `can_transition` rather than a status literal, so the one legal edge stays
    declared in the model. Anything not at `Employee Created` is left alone -- a record that
    never reached the hire is not dragged forward by a probation nobody linked correctly.
    """
    uk = probation.get("uk")
    if not uk:
        return False
    coll = get_collection(COLL_CANDIDATES)
    candidate = await coll.find_one({"uk": uk, "company_id": str(company_id)})
    if not candidate:
        return False
    current_status = candidate.get("application_status")
    if not can_transition(current_status, AppStatus.PROBATION_CONFIRMED.value):
        return False
    await coll.update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {"application_status": AppStatus.PROBATION_CONFIRMED.value,
                  "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                f"{current_status} -> {AppStatus.PROBATION_CONFIRMED.value}", company_id)
    return True


async def _close_requisition_on_confirmation(actor: dict, company_id: str,
                                             probation: dict) -> bool:
    """SOP §7: with no client handover, the requisition closes once probation is confirmed.

    Only ever closes an INTERNAL requisition that is still Open, and only to Hired. A
    requisition somebody already closed as Cancel is not quietly reopened as Hired because a
    different hire on it was confirmed months later.
    """
    request_no = probation.get("request_no")
    if not request_no:
        return False
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        return False
    track = req.get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return False
    if req.get("closing_status") != ReqClosing.OPEN.value:
        return False

    # Every seat, not just this one. A requisition raised for three people is not filled
    # because the first of them cleared probation, and closing it here would retire a role
    # still two hires short -- which then reads as "Hired" on the tracker and the KPIs while
    # recruitment is visibly still running.
    vacancy = int(req.get("vacancy") or 1)
    confirmed = await get_collection(COLL_PROBATION_REVIEWS).count_documents({
        "company_id": str(company_id), "request_no": request_no,
        "outcome": ProbationOutcome.CONFIRMED.value})
    if confirmed < vacancy:
        return False

    now = datetime.now(timezone.utc)
    # Conditioned on the state it was read in, so two confirmations landing together cannot
    # both close it and write two audit rows for one event.
    # SOP §13: retention runs from closure, so it is stamped by whoever closes.
    from app.services.hrms_candidate_service import _add_years
    from app.services.hrms_config_service import retention_years_for
    retention_until = _add_years(
        now.strftime("%Y-%m-%d"),
        await retention_years_for(company_id, "requisition"))

    result = await get_collection(COLL_REQUISITIONS).update_one(
        {"request_no": request_no, "company_id": str(company_id),
         "closing_status": ReqClosing.OPEN.value},
        {"$set": {"closing_status": ReqClosing.HIRED.value,
                  "closed_on_probation_confirmation": probation.get("prb_no"),
                  # The same field the client track stamps, so "when did this close" has
                  # one answer whatever closed it. The prb_no above says WHY.
                  "closed_at": now,
                  "retention_until": retention_until,
                  "updated_at": now}})
    if not (result.modified_count or 0):
        return False
    await audit(actor, AUDIT_REQ_CLOSED, ENTITY_REQUISITION, request_no,
                f"Hired -- {confirmed}/{vacancy} probation(s) confirmed "
                f"({probation.get('prb_no')})", company_id)
    return True


async def close_personnel_file(actor: dict, company_id: str, payload: dict) -> dict:
    """Record the personnel-file closure note (SOP §7, §9).

    The file itself is the offer, joining documents, verification reports and probation
    confirmation, each of which already lives in its own collection. What is recorded here is
    the ACT of closing it -- who checked that the set was complete, when, and what they said.
    """
    employee_code = clean_text(payload.get("employee_code"), limit=40)
    note = clean_text(payload.get("closure_note"), limit=4000)
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")
    if not note:
        raise HTTPException(
            status_code=422,
            detail="Record what was checked. An empty closure note closes nothing.")

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"employee_code": employee_code, "company_id": str(company_id)})
    if not profile:
        raise HTTPException(
            status_code=404, detail="No employee with that code in this company.")

    probation = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"employee_code": employee_code, "company_id": str(company_id)})
    if not probation or probation.get("outcome") != ProbationOutcome.CONFIRMED.value:
        raise HTTPException(
            status_code=409,
            detail=(f"{employee_code}'s probation has not been confirmed yet. The personnel "
                    f"file is closed once the confirmation is on record."))

    now = datetime.now(timezone.utc)
    await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
        {"employee_code": employee_code, "company_id": str(company_id)},
        {"$set": {"personnel_file_closed": True,
                  "personnel_file_closed_at": now,
                  "personnel_file_closed_by": str(actor.get("_id") or ""),
                  "personnel_file_closure_note": note,
                  "updated_at": now}})
    await audit(actor, AUDIT_PERSONNEL_FILE_CLOSED, ENTITY_PROBATION, employee_code,
                note[:200], company_id)
    return {"employee_code": employee_code, "personnel_file_closed": True,
            "closed_at": now, "closure_note": note}
