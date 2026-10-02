"""HRMS > the position scorecard (internal recruitment track).

What "good" looks like for one vacancy, agreed BEFORE anybody is interviewed.

-- Why this exists ---------------------------------------------------------------------
The client track scores candidates against six fixed competencies (technical, communication,
problem solving, behaviour, confidence, team fit). That works when the client owns the
judgement and the agency is routing CVs. It does not work for Sparsh Magic's own hiring,
where the SOP requires the bar to be written down and approved before sourcing, so that a
later "they interviewed well" cannot quietly replace the criteria the role was raised on.

So a scorecard is a per-requisition list of WEIGHTED criteria, drafted by HR, approved by the
hiring manager, and -- for managerial and above -- also by Management (Annexure B: "Position
Scorecard | Draft | Approve | Approve (managerial+)").

-- The bands are surfaced, never applied ------------------------------------------------
SOP §5 gives a scoring guide: 4.0+ strong, below 3.0 reject. This module computes the
weighted score and names its band. It does NOT move the candidate. A rubric that silently
rejects people is one nobody will trust, nobody will correct, and everybody will work around
-- so the number informs a human decision rather than replacing it.

-- One scorecard per requisition ---------------------------------------------------------
Enforced by a unique index on (company_id, request_no), not merely by this code. Two
scorecards for one vacancy means two bars, and the one that gets used is whichever the
reader happened to open.

-- Internal track only --------------------------------------------------------------------
A client-track requisition never has one. The client owns the judgement there, and inventing
an internal bar for their vacancy would be a concept with no owner.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SCORECARD_APPROVED, AUDIT_SCORECARD_CREATED, AUDIT_SCORECARD_EVALUATED,
    AUDIT_SCORECARD_UPDATED, COLL_CANDIDATES, COLL_POSITION_SCORECARDS, COLL_REQUISITIONS,
    ENTITY_CANDIDATE, ENTITY_SCORECARD, SCORE_MAX, SCORE_MIN, Cap, Decision, HrmsRole,
    REQUISITION_TRACK_INTERNAL, ScorecardCategory, ScorecardStatus, score_band,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_public_guard import clean_text

MAX_CRITERIA = 25
MIN_CRITERIA = 1
MAX_WEIGHT = 100.0


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


async def _require_internal_requisition(company_id: str, request_no: str) -> dict:
    """Resolve the requisition a scorecard belongs to, or explain why it cannot have one."""
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That requisition does not exist for this company.")
    track = req.get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        raise HTTPException(
            status_code=409,
            detail=f"{request_no} is a legacy client-track requisition and is not part of hiring any more.")
    return req


def _validate_criteria(raw) -> list:
    """Clean and check the weighted criteria.

    Weights are stored as given and normalised at scoring time rather than forced to sum to
    100 here. Insisting on a total is a data-entry tax: "SQL twice as important as culture
    fit" is the judgement being captured, and 2-and-1 says it as well as 67-and-33.
    """
    if not isinstance(raw, list) or not raw:
        raise HTTPException(
            status_code=422, detail="A scorecard needs at least one criterion.")
    if len(raw) > MAX_CRITERIA:
        raise HTTPException(
            status_code=422,
            detail=f"A scorecard can hold at most {MAX_CRITERIA} criteria.")

    seen, out = set(), []
    for item in raw:
        item = dict(item or {})
        label = clean_text(item.get("label"), limit=140)
        if not label:
            raise HTTPException(
                status_code=422, detail="Every criterion needs a label.")
        # The label is the JOIN KEY an evaluation scores against, so duplicates would make a
        # score ambiguous. Compared case-insensitively for the same reason the masters are.
        key = label.lower()
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f'"{label}" appears twice. Each criterion needs its own label.')
        seen.add(key)

        raw_category = getattr(item.get("category"), "value", item.get("category"))
        try:
            category = ScorecardCategory(raw_category or ScorecardCategory.SKILL.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Category must be one of: "
                        f"{', '.join(c.value for c in ScorecardCategory)}."))

        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f'The weight for "{label}" must be a number.')
        if weight <= 0 or weight > MAX_WEIGHT:
            raise HTTPException(
                status_code=422,
                detail=(f'The weight for "{label}" must be greater than 0 and at most '
                        f"{int(MAX_WEIGHT)}."))

        try:
            max_score = int(item.get("max_score", SCORE_MAX))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f'The maximum score for "{label}" must be a number.')
        if max_score < 1:
            raise HTTPException(
                status_code=422, detail=f'The maximum score for "{label}" must be at least 1.')

        out.append({"label": label, "category": category.value,
                    "expected_level": clean_text(item.get("expected_level"), limit=500) or None,
                    "evaluation_criteria": clean_text(item.get("evaluation_criteria"), limit=500) or None,
                    "weight": weight, "max_score": max_score,
                    "remarks": clean_text(item.get("remarks"), limit=500) or None})
    return out


def required_approvals(managerial: bool) -> list:
    """Which roles must sign a scorecard off.

    Annexure B: the hiring manager is accountable for every scorecard; Management approves as
    well for managerial and above. Returned as a list rather than a set so the order the UI
    shows them in is the order the SOP states them.
    """
    return [HrmsRole.MANAGER, HrmsRole.MD] if managerial else [HrmsRole.MANAGER]


def _approval_state(doc: dict) -> dict:
    """Who has signed, who is still needed, and whether that is enough.

    The MD may stand in for the hiring manager on a NON-managerial scorecard -- the same
    "top of the ladder can clear any rung" rule the escalation chain already uses, and for
    the same reason: an approval that stalls because one person is away is a trap.

    On a MANAGERIAL scorecard they may not, because there the two signatures ARE the control.
    One person holding both pens is not dual approval, it is single approval with extra
    steps.
    """
    managerial = bool(doc.get("managerial"))
    needed = required_approvals(managerial)
    approvals = [a for a in (doc.get("approvals") or [])
                 if a.get("decision") == Decision.PASS.value]

    signed_roles = {a.get("role") for a in approvals}
    signed_users = {a.get("user_id") for a in approvals}

    satisfied = []
    for role in needed:
        if role.value in signed_roles:
            satisfied.append(role.value)
        elif not managerial and HrmsRole.MD.value in signed_roles:
            # MD standing in for the hiring manager on an ordinary role.
            satisfied.append(role.value)

    outstanding = [r.value for r in needed if r.value not in satisfied]
    complete = not outstanding
    if managerial and complete and len(signed_users) < 2:
        # Belt and braces: two ROLES signed, but by one person. Should be impossible given
        # a user resolves to exactly one HRMS role, and cheap to refuse if it ever is not.
        complete = False
        outstanding = ["a second, independent approver"]

    return {"managerial": managerial,
            "required_roles": [r.value for r in needed],
            "signed_roles": sorted(r for r in signed_roles if r),
            "outstanding_roles": outstanding,
            "complete": complete}


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_scorecards(actor: dict, company_id: str, *, request_no: str = None,
                          status: str = None, limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if request_no:
        query["request_no"] = request_no
    if status:
        query["status"] = status
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_POSITION_SCORECARDS).find(query).sort(
        "created_at", -1).to_list(limit)
    return {"scorecards": [_out(r) for r in rows], "total": len(rows)}


async def get_scorecard(company_id: str, scr_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_POSITION_SCORECARDS).find_one(
        {"scr_no": scr_no, "company_id": str(company_id)})
    if not doc:
        return None
    out = _out(doc)
    out["approval_state"] = _approval_state(doc)
    return out


async def scorecard_for_requisition(company_id: str, request_no: str) -> Optional[dict]:
    """The scorecard a requisition is hiring against, if it has one."""
    doc = await get_collection(COLL_POSITION_SCORECARDS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def assert_scorecard_approved(company_id: str, request_no: str) -> dict:
    """Refuse to close the requisition chain without an approved scorecard.

    This is what makes the `scorecard-approve` gate real rather than nominal: without it the
    requisition could reach Approved while the bar it is hiring against was still a draft
    somebody meant to finish.
    """
    doc = await get_collection(COLL_POSITION_SCORECARDS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(
            status_code=409,
            detail=(f"{request_no} has no position scorecard yet. Draft and approve one "
                    f"before the requisition can be approved -- the scorecard IS the bar "
                    f"candidates are measured against."))
    if doc.get("status") != ScorecardStatus.APPROVED.value:
        state = _approval_state(doc)
        outstanding = ", ".join(state["outstanding_roles"]) or "approval"
        raise HTTPException(
            status_code=409,
            detail=(f'Scorecard {doc.get("scr_no")} is "{doc.get("status")}". '
                    f"Still waiting on: {outstanding}."))
    return _out(doc)


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def _can_approve_scorecards(user_id: str) -> bool:
    """Whether this user resolves to a role that may approve scorecards (MANAGER or MD).

    The requisition's raiser is usually the hiring manager, but any employee may raise one
    -- and an approval request sent to somebody who cannot approve is a dead letter while
    the real approvers hear nothing.
    """
    if not user_id:
        return False
    from bson import ObjectId
    from app.utils.hrms_access import hrms_role
    try:
        oid = ObjectId(user_id)
    except Exception:
        return False
    for coll_name in ("learners", "staff"):
        user = await get_collection(coll_name).find_one({"_id": oid})
        if user:
            return hrms_role(user) in (HrmsRole.MANAGER, HrmsRole.MD)
    return False


async def create_scorecard(actor: dict, company_id: str, payload: dict) -> dict:
    request_no = (payload.get("request_no") or "").strip()
    if not request_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")
    req = await _require_internal_requisition(company_id, request_no)

    coll = get_collection(COLL_POSITION_SCORECARDS)
    if await coll.find_one({"request_no": request_no, "company_id": str(company_id)}):
        raise HTTPException(
            status_code=409,
            detail=(f"{request_no} already has a position scorecard. Edit that one rather "
                    f"than raising a second bar for the same vacancy."))

    criteria = _validate_criteria(payload.get("criteria"))
    year = datetime.now(timezone.utc).year
    scr_no = await next_business_id("scorecard", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "scr_no": scr_no,
        "company_id": str(company_id),
        "request_no": request_no,
        # Denormalised so a scorecard list reads without joining every requisition.
        "designation_name": req.get("designation_name"),
        "department_name": req.get("department_name"),
        "title": clean_text(payload.get("title"), limit=160) or req.get("designation_name"),
        "criteria": criteria,
        "managerial": bool(payload.get("managerial")),
        "notes": clean_text(payload.get("notes"), limit=2000),
        "status": ScorecardStatus.PENDING_APPROVAL.value,
        "approvals": [],
        "created_by": str(actor.get("_id") or ""),
        "created_by_name": actor.get("full_name") or actor.get("email"),
        "created_at": now,
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_SCORECARD_CREATED, ENTITY_SCORECARD, scr_no,
                f"{len(criteria)} criteria for {request_no}", company_id)

    # ── Phase INT-9 (spec §38) ── the scorecard is now WAITING on somebody, and nobody
    # watches a queue they were not told about -- the same rule the requisition chain
    # follows. The HOD is the requisition's raiser, addressed directly; Management is a
    # role, because "the MD" is whoever holds that governance role when the letter lands.
    from app.services.hrms_notify_service import notify_hrms_role, notify_user
    link = "/hrms/scorecards"
    title = f"Scorecard {scr_no} needs approval"
    detail = (f'{doc["created_by_name"]} drafted the position scorecard for '
              f'{req.get("designation_name") or request_no}. Sourcing cannot begin '
              f"until it is approved.")
    # The raiser is USUALLY the hiring manager -- but any employee may raise a requisition
    # (the module's documented design), and a raiser who cannot approve must not be the
    # only person asked to. When they cannot, every hiring manager is asked instead.
    if await _can_approve_scorecards(str(req.get("created_by") or "")):
        await notify_user(str(req["created_by"]), title, detail,
                          kind="info", link=link, email=True)
    else:
        await notify_hrms_role(company_id, ["HOD"], title, detail,
                               kind="info", link=link, email=True)
    if doc["managerial"]:
        await notify_hrms_role(company_id, ["MD"], title,
                               detail + " This is a managerial role, so Management must "
                                        "approve it as well as the hiring manager.",
                               kind="info", link=link, email=True)

    out = _out(doc)
    out["approval_state"] = _approval_state(doc)
    return out


async def update_scorecard(actor: dict, company_id: str, scr_no: str,
                           payload: dict) -> dict:
    """Edit a scorecard that has not been approved yet.

    An APPROVED scorecard is frozen. Editing the criteria after sign-off would mean the bar
    the approver agreed to is not the bar candidates were measured against -- exactly the
    drift this whole entity exists to stop. Any change after approval means a new scorecard.
    """
    coll = get_collection(COLL_POSITION_SCORECARDS)
    current = await coll.find_one({"scr_no": scr_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    if current.get("status") == ScorecardStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(f"{scr_no} is approved and can no longer be edited. The criteria are "
                    f"what the approver signed off on."))

    updates = {}
    if payload.get("title") is not None:
        updates["title"] = clean_text(payload["title"], limit=160)
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)
    if payload.get("criteria") is not None:
        updates["criteria"] = _validate_criteria(payload["criteria"])
    if payload.get("managerial") is not None:
        updates["managerial"] = bool(payload["managerial"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # Changing the bar, or who must approve it, invalidates approvals already given -- they
    # are cleared rather than silently carried over onto different criteria.
    requeued = False
    if {"criteria", "managerial"} & set(updates):
        requeued = bool(current.get("approvals")) \
            or current.get("status") == ScorecardStatus.REJECTED.value
        updates["approvals"] = []
        updates["status"] = ScorecardStatus.PENDING_APPROVAL.value
    elif current.get("status") == ScorecardStatus.REJECTED.value:
        # Any edit to a sent-back scorecard is HR answering the feedback, so it goes back
        # into the queue. Leaving it Rejected would strand it: nobody looks at a rejected
        # document again, and the approver is never asked a second time.
        updates["status"] = ScorecardStatus.PENDING_APPROVAL.value
        requeued = True

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"scr_no": scr_no, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_SCORECARD_UPDATED, ENTITY_SCORECARD, scr_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    # ── Phase INT-9 ── a card that went BACK into the queue is waiting on somebody again,
    # and re-queueing it silently strands it exactly the way leaving it Rejected would
    # have: the approver is never asked a second time. Same recipients as creation.
    if requeued:
        from app.services.hrms_notify_service import notify_hrms_role, notify_user
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": current.get("request_no"), "company_id": str(company_id)},
            {"created_by": 1, "designation_name": 1})
        link = "/hrms/scorecards"
        title = f"Scorecard {scr_no} needs approval again"
        name = (req or {}).get("designation_name") or current.get("request_no")
        detail = (f"The scorecard for {name} was revised"
                  + (" and its earlier signatures were cleared."
                     if updates.get("approvals") == [] else " after being sent back.")
                  + " It is back in the approval queue.")
        raiser = str((req or {}).get("created_by") or "")
        if await _can_approve_scorecards(raiser):
            await notify_user(raiser, title, detail, kind="info", link=link, email=True)
        else:
            await notify_hrms_role(company_id, ["HOD"], title, detail,
                                   kind="info", link=link, email=True)
        if bool(updates.get("managerial", current.get("managerial"))):
            await notify_hrms_role(company_id, ["MD"], title, detail,
                                   kind="info", link=link, email=True)
    return await get_scorecard(company_id, scr_no)


async def approve_scorecard(actor: dict, company_id: str, scr_no: str,
                            payload: dict) -> dict:
    """Record one approval signature, and complete the scorecard once all are in.

    Returns the scorecard with its approval state, so the caller can see who is still needed
    rather than having to work it out from the list of signatures.
    """
    coll = get_collection(COLL_POSITION_SCORECARDS)
    current = await coll.find_one({"scr_no": scr_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    if current.get("status") == ScorecardStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail=f"{scr_no} is already approved.")
    already_rejected = current.get("status") == ScorecardStatus.REJECTED.value

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this approval. An unsigned sign-off is not one.")

    raw_decision = getattr(payload.get("decision"), "value", payload.get("decision"))
    try:
        decision = Decision(raw_decision or Decision.PASS.value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Decision must be Pass or Fail.")

    remarks = clean_text(payload.get("remarks"), limit=2000)
    role = hrms_role(actor)
    actor_id = str(actor.get("_id") or "")
    now = datetime.now(timezone.utc)

    if decision is Decision.FAIL:
        # A card that is already sent back cannot be sent back again -- the second Fail
        # would repeat the write, the audit row and both notifications for a state that
        # did not change. Mirrors the APPROVED guard above.
        if already_rejected:
            raise HTTPException(
                status_code=409,
                detail=f"{scr_no} was already sent back. Edit it to answer the feedback.")
        if not remarks:
            raise HTTPException(
                status_code=422,
                detail="Say why the scorecard is being sent back, so HR can act on it.")
        await coll.update_one(
            {"scr_no": scr_no, "company_id": str(company_id)},
            {"$set": {"status": ScorecardStatus.REJECTED.value, "approvals": [],
                      "rejected_by": actor_id, "rejected_at": now,
                      "rejection_remarks": remarks, "updated_at": now}})
        await audit(actor, AUDIT_SCORECARD_APPROVED, ENTITY_SCORECARD, scr_no,
                    f"sent back: {remarks}", company_id)

        # ── Phase INT-9 ── sent back is a decision somebody must ACT on. The drafter is
        # told directly; HR as a role, because they own redrafting even when the original
        # author is away.
        from app.services.hrms_notify_service import notify_hrms_role, notify_user
        title = f"Scorecard {scr_no} was sent back"
        detail = f"Reason: {remarks}"
        drafter = str(current.get("created_by") or "")
        if drafter:
            await notify_user(drafter, title, detail,
                              kind="warning", link="/hrms/scorecards", email=True)
        # HR drafts most scorecards, so without the exclusion the drafter -- already told
        # by name above -- would be told again by their own role's fan-out.
        await notify_hrms_role(company_id, ["HR"], title, detail,
                               kind="warning", link="/hrms/scorecards", email=True,
                               exclude_user_ids=[drafter] if drafter else None)
        return await get_scorecard(company_id, scr_no)

    approvals = [a for a in (current.get("approvals") or [])
                 if str(a.get("user_id")) != actor_id]
    approvals.append({
        "user_id": actor_id,
        "name": actor.get("full_name") or actor.get("email"),
        "role": role.value if role else None,
        "decision": decision.value,
        "signature": signature,
        "remarks": remarks,
        "at": now,
    })

    merged = {**current, "approvals": approvals}
    state = _approval_state(merged)
    # The state BEFORE this signature, so the notifications below fire only when the
    # signature actually moved something -- a re-sign recomputes an identical state and
    # must say nothing (this is the property the comment below promises).
    prev_state = _approval_state(current)
    updates = {"approvals": approvals, "updated_at": now}
    if state["complete"]:
        updates.update({"status": ScorecardStatus.APPROVED.value, "approved_at": now})

    # Compare-and-swap on the approvals array the merge was BUILT from: two approvers
    # signing at the same moment would otherwise each persist an array containing only
    # themselves, and the loser's signature would silently vanish. The loser here gets a
    # 409 and retries against the state that actually landed.
    result = await coll.update_one(
        {"scr_no": scr_no, "company_id": str(company_id),
         "approvals": current.get("approvals") or []},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Someone else signed this scorecard at the same moment. Reload to see "
                   "the current state, then sign again.")
    await audit(actor, AUDIT_SCORECARD_APPROVED, ENTITY_SCORECARD, scr_no,
                (f"approved by {role.value if role else 'unknown role'}"
                 + ("" if state["complete"]
                    else f"; still needed: {', '.join(state['outstanding_roles'])}")),
                company_id)

    # ── Phase INT-9 (spec §38) ── "Scorecard approval completed" goes to HR, who own the
    # next step (sourcing). A PARTIAL approval instead chases whoever is still owed: the
    # MD role if Management has not signed, the requisition's raiser if the hiring manager
    # has not. Fired only on the signature that changes the state, so signing twice cannot
    # notify twice.
    from app.services.hrms_notify_service import notify_hrms_role, notify_user
    link = "/hrms/scorecards"
    name = current.get("designation_name") or current.get("request_no")
    if state["complete"]:
        await notify_hrms_role(
            company_id, ["HR"], f"Scorecard {scr_no} is fully approved",
            f"The bar for {name} is set. Sourcing can begin once the budget gate is "
            f"cleared.", kind="success", link=link, email=True)
    elif state["outstanding_roles"] == prev_state["outstanding_roles"]:
        # The signature satisfied nothing new -- a re-sign. The chase already went out
        # when the state first moved; repeating it is how an alert becomes noise.
        pass
    else:
        outstanding = set(state["outstanding_roles"])
        if HrmsRole.MD.value in outstanding:
            await notify_hrms_role(
                company_id, ["MD"], f"Scorecard {scr_no} still needs Management",
                f"{name} is a managerial role; the hiring manager has signed and "
                f"Management's approval is the one outstanding.",
                kind="info", link=link, email=True)
        if HrmsRole.MANAGER.value in outstanding:
            req = await get_collection(COLL_REQUISITIONS).find_one(
                {"request_no": current.get("request_no"),
                 "company_id": str(company_id)}, {"created_by": 1})
            if req and req.get("created_by"):
                await notify_user(
                    str(req["created_by"]),
                    f"Scorecard {scr_no} still needs the hiring manager",
                    f"Management has signed the scorecard for {name}; your approval is "
                    f"the one outstanding.", kind="info", link=link, email=True)
    return await get_scorecard(company_id, scr_no)


# -------------------------------------------------------------
# Evaluation
# -------------------------------------------------------------
def compute_weighted(criteria: list, scores: dict, bands: dict = None) -> dict:
    """Weighted 1-5 score for one candidate against one scorecard.

    Each criterion is normalised to the 1-5 scale before weighting, so a criterion marked
    out of 10 does not silently count double. The weights are then a simple weighted mean --
    they express relative importance and never need to sum to anything in particular.

    Every criterion must be scored. A partial evaluation averaged over the criteria that
    happen to be filled in would flatter whoever was scored on their strengths alone.
    """
    if not criteria:
        raise HTTPException(
            status_code=409, detail="That scorecard has no criteria to score against.")

    by_label = {c["label"].lower(): c for c in criteria}
    provided = {str(k).strip().lower(): v for k, v in (scores or {}).items()}

    missing = [c["label"] for c in criteria if c["label"].lower() not in provided]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Score every criterion. Missing: {', '.join(missing)}.")
    unknown = [k for k in provided if k not in by_label]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(f"These are not criteria on this scorecard: "
                    f"{', '.join(sorted(unknown))}."))

    total_weight = 0.0
    accumulated = 0.0
    breakdown = []
    for criterion in criteria:
        raw = provided[criterion["label"].lower()]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail=f'The score for "{criterion["label"]}" must be a number.')
        ceiling = int(criterion.get("max_score") or SCORE_MAX)
        if value < SCORE_MIN or value > ceiling:
            raise HTTPException(
                status_code=422,
                detail=(f'The score for "{criterion["label"]}" must be between '
                        f"{SCORE_MIN} and {ceiling}."))

        normalised = (value / ceiling) * SCORE_MAX
        weight = float(criterion.get("weight") or 1.0)
        accumulated += normalised * weight
        total_weight += weight
        breakdown.append({"label": criterion["label"],
                          "category": criterion.get("category"),
                          "score": value, "max_score": ceiling,
                          "weight": weight, "normalised": round(normalised, 2)})

    weighted = round(accumulated / total_weight, 2) if total_weight else None
    return {"weighted_score": weighted, "band": score_band(weighted, bands),
            "breakdown": breakdown}


async def evaluate_candidate(actor: dict, company_id: str, uk: str,
                             payload: dict) -> dict:
    """Score one candidate against their requisition's scorecard.

    Records the result on the candidate and STOPS. The band is advice for the person reading
    it (SOP §5: 4.0+ strong, below 3.0 reject), not an instruction to the pipeline -- moving
    somebody on a computed number would put a rubric in charge of a hiring decision.
    """
    candidates = get_collection(COLL_CANDIDATES)
    candidate = await candidates.find_one({"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    request_no = candidate.get("request_no")
    if not request_no:
        raise HTTPException(
            status_code=409,
            detail=(f"{candidate.get('candidate_name')} is not attached to a requisition, "
                    f"so there is no scorecard to measure them against."))

    scorecard = await get_collection(COLL_POSITION_SCORECARDS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not scorecard:
        raise HTTPException(
            status_code=409,
            detail=f"{request_no} has no position scorecard to score against.")

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this evaluation.")

    # ── Phase INT-5 ── banded against THIS company's floors. The number is the fact; the
    # band is its reading, and a company that moved its bar reads its own scores by it.
    from app.services.hrms_config_service import score_bands_for
    result = compute_weighted(scorecard.get("criteria") or [], payload.get("scores"),
                              await score_bands_for(company_id))
    now = datetime.now(timezone.utc)
    evaluation = {
        "scr_no": scorecard.get("scr_no"),
        "weighted_score": result["weighted_score"],
        "band": result["band"],
        "breakdown": result["breakdown"],
        "remarks": clean_text(payload.get("remarks"), limit=2000),
        "signature": signature,
        "evaluated_by": str(actor.get("_id") or ""),
        "evaluated_by_name": actor.get("full_name") or actor.get("email"),
        "evaluated_at": now,
    }

    await candidates.update_one(
        {"uk": uk, "company_id": str(company_id)},
        # The flat fields are denormalised for reporting, exactly as `client_share_status` is
        # -- so a breakdown by band does not have to reach into a sub-document.
        {"$set": {"scorecard_evaluation": evaluation,
                  "scorecard_score": result["weighted_score"],
                  "scorecard_band": result["band"],
                  "updated_at": now}})
    await audit(actor, AUDIT_SCORECARD_EVALUATED, ENTITY_CANDIDATE, uk,
                f"{result['weighted_score']} ({result['band']}) "
                f"against {scorecard.get('scr_no')}", company_id)

    return {"uk": uk, "candidate_name": candidate.get("candidate_name"),
            "application_status": candidate.get("application_status"),
            **result,
            # Stated outright so no caller has to infer it from the absence of a stage move.
            "stage_changed": False,
            "guidance": ("A band is advice, not a decision. The candidate has not been "
                         "moved -- screen them as you see fit.")}
