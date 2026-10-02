"""HRMS > Client Hiring, step 5 — the assessment.

PRO-fit SOP section 12: "Talent Fit Assessment test administered and evaluated against the
Position Scorecard", and the assessment-stage responsibility table.

-- Where it sits, and why ---------------------------------------------------------------
Your flow makes the client's CV approval the gate into this stage, and that ordering is
the point: the assessment is marked against the benchmark, so it happens only after the
client has agreed both the benchmark (step 2) and this particular person (step 4).

It ends with the client reading the result, which is what unlocks the interview. That is
an ACKNOWLEDGEMENT, not a verdict — the flow goes straight on, and the client's selection
comes later, once they have seen the interview recording.

-- Four hands on one record -------------------------------------------------------------
The SOP separates "assessment managed" from "assessment scoring", so those are different
capabilities: the person who administers a test is not always the one qualified to mark
it, and one capability could not record the difference. Delivery to the client is the Team
Lead's, as everywhere else on this track. The review is the client's and nobody at Sparsh
holds it.

-- What the client sees -----------------------------------------------------------------
The result once it is shared, and never the evaluator's own notes. Same whitelist
discipline as the CV share: absent by construction rather than stripped afterwards.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_ASSESSMENT_ACTIONED, AUDIT_CLIENT_ASSESSMENT_SENT,
    AUDIT_CLIENT_ASSESSMENT_UPDATED, AUDIT_CLIENT_CANDIDATE_ACTIONED,
    CLIENT_ASSESSMENT_TRANSITIONS, CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT,
    CLIENT_TRACK_FLAG, COLL_CLIENT_ASSESSMENTS, COLL_CLIENT_CANDIDATES,
    ENTITY_CLIENT_ASSESSMENT, ENTITY_CLIENT_CANDIDATE,
    Cap, ClientAssessmentStatus, ClientCandidateStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

# What the client receives. The evaluator's notes are deliberately absent: they are candid
# working observations, written to be read inside Sparsh.
CLIENT_VISIBLE_FIELDS = (
    "cas_no", "company_id", "ccn_no", "cr_no", "candidate_name", "title",
    "instructions", "due_on", "max_score", "score", "result", "status",
    "submitted_at", "scored_at", "shared_at", "client_review",
    "created_at", "updated_at",
)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _client_view(doc: dict) -> dict:
    return {k: doc.get(k) for k in CLIENT_VISIBLE_FIELDS if k in doc}


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _is_client_side(actor: dict) -> bool:
    if (actor or {}).get(CLIENT_TRACK_FLAG):
        return True
    return not is_internal_user(actor)


async def _require_visible(actor: dict, company_id: str, cas_no: str) -> dict:
    doc = await get_collection(COLL_CLIENT_ASSESSMENTS).find_one(
        {"cas_no": cas_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if (_is_client_side(actor)
            and doc.get("status") not in CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT):
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return doc


async def _move_candidate(actor: dict, company_id: str, ccn_no: str,
                          target: ClientCandidateStatus, why: str) -> None:
    """Advance the candidate's stage as a consequence of assessment work.

    Set here rather than exposed on the candidate's own action endpoint, so the pipeline
    can only claim an assessment that actually has a record behind it. Best-effort in the
    sense that it never rolls the assessment back: the assessment happened, and a stage
    that failed to move is a smaller problem than losing the evidence of it.
    """
    coll = get_collection(COLL_CLIENT_CANDIDATES)
    candidate = await coll.find_one({"ccn_no": ccn_no, "company_id": str(company_id)})
    if not candidate:
        return
    current = candidate.get("status")
    if current == target.value:
        return
    await coll.update_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)},
        {"$set": {"status": target.value, "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_CLIENT_CANDIDATE_ACTIONED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"{current} -> {target.value} ({why})", company_id)


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_client_assessments(actor: dict, company_id: Optional[str], *,
                                  ccn_no: str = None, status: str = None,
                                  limit: int = 200) -> dict:
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    elif _is_client_side(actor):
        raise HTTPException(status_code=403, detail="No company in scope.")
    if ccn_no:
        query["ccn_no"] = ccn_no

    client_side = _is_client_side(actor)
    if client_side:
        allowed = sorted(CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT)
        query["status"] = ({"$in": allowed} if not status
                           else (status if status in CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT
                                 else "__none__"))
    elif status:
        query["status"] = status

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_ASSESSMENTS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [(_client_view(r) if client_side else _out(r)) for r in rows]
    return {
        "client_assessments": out,
        "total": len(out),
        "awaiting_client": sum(
            1 for r in out if r.get("status") == ClientAssessmentStatus.SHARED.value),
    }


async def get_client_assessment(actor: dict, company_id: str, cas_no: str) -> dict:
    doc = await _require_visible(actor, company_id, cas_no)
    return _client_view(doc) if _is_client_side(actor) else _out(doc)


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
def _validate_score(value, max_score: float) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="The score must be a number.")
    if not 0 <= score <= float(max_score):
        raise HTTPException(
            status_code=422, detail=f"The score must be between 0 and {max_score:g}.")
    return round(score, 2)


async def create_client_assessment(actor: dict, company_id: str, payload: dict) -> dict:
    """Issue the assessment. Only for a candidate whose CV the client approved."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    ccn_no = clean_text(payload.get("ccn_no"), limit=40)
    if not ccn_no:
        raise HTTPException(status_code=422, detail="Choose a candidate.")
    title = clean_text(payload.get("title"), limit=200)
    if not title:
        raise HTTPException(
            status_code=422,
            detail="Name the assessment, so its result means something on the record.")

    # The duplicate check comes FIRST, and the order matters for the message rather than
    # for the outcome. Issuing an assessment moves the candidate on from Client Approved,
    # so a second attempt would otherwise fail the gate below and be told "the client has
    # not approved this CV" -- true of the stage, false as an explanation, and actively
    # misleading to somebody looking at the assessment they issued an hour ago.
    existing = await get_collection(COLL_CLIENT_ASSESSMENTS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{existing.get("candidate_name") or ccn_no} already has an '
                    f'assessment ({existing["cas_no"]}, {existing["status"]}).'))

    # THE GATE. Your flow: the client's CV approval is what opens this stage.
    from app.services.hrms_client_candidate_service import assert_assessment_allowed
    candidate = await assert_assessment_allowed(company_id, ccn_no)

    due_on = clean_text(payload.get("due_on"), limit=10)
    if due_on and not is_iso_date(due_on):
        raise HTTPException(
            status_code=422, detail="The due date must be a valid YYYY-MM-DD date.")
    try:
        max_score = float(payload.get("max_score") or 5)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="The maximum score must be a number.")
    if max_score <= 0:
        raise HTTPException(status_code=422, detail="The maximum score must be positive.")

    now = datetime.now(timezone.utc)
    cas_no = await next_business_id("client_assessment", str(company_id), now.year)
    doc = {
        "cas_no": cas_no,
        "company_id": str(company_id),
        "ccn_no": ccn_no,
        "cr_no": candidate.get("cr_no"),
        "psc_no": candidate.get("psc_no"),
        "candidate_name": candidate.get("candidate_name"),
        "title": title,
        "instructions": clean_text(payload.get("instructions"), limit=8000),
        "due_on": due_on,
        "max_score": round(max_score, 2),
        "submission_reference": None,
        "score": None,
        "result": None,
        "evaluator_notes": None,
        "status": ClientAssessmentStatus.SENT.value,
        "submitted_at": None, "scored_at": None, "shared_at": None,
        "scored_by_name": None,
        "client_review": None,
        "issued_by": str(actor.get("_id") or ""),
        "issued_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_ASSESSMENTS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_ASSESSMENT_SENT, ENTITY_CLIENT_ASSESSMENT, cas_no,
                f'{title} issued to {candidate.get("candidate_name")}', company_id)
    await _move_candidate(actor, company_id, ccn_no, ClientCandidateStatus.ASSESSMENT,
                          f"assessment {cas_no} issued")
    return _out(doc)


async def update_client_assessment(actor: dict, company_id: str, cas_no: str,
                                   payload: dict) -> dict:
    """Record the submission, the mark and the evaluator's reasoning."""
    current = await _require_visible(actor, company_id, cas_no)
    if current.get("status") in CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT:
        raise HTTPException(
            status_code=409,
            detail=(f"{cas_no} is with the client. Changing a result somebody is reading "
                    f"would rewrite what they were shown."))

    updates: dict = {}
    for field, limit in (("title", 200), ("instructions", 8000),
                         ("submission_reference", 500), ("evaluator_notes", 8000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("due_on") is not None:
        due_on = clean_text(payload["due_on"], limit=10)
        if due_on and not is_iso_date(due_on):
            raise HTTPException(
                status_code=422, detail="The due date must be a valid YYYY-MM-DD date.")
        updates["due_on"] = due_on
    if payload.get("result") is not None:
        result = clean_text(payload["result"], limit=40)
        if result and result.title() not in ("Pass", "Fail"):
            raise HTTPException(
                status_code=422, detail="The result is Pass or Fail.")
        updates["result"] = result.title() if result else None
    if payload.get("score") is not None:
        # Marking needs the marking capability, whoever else may edit the paperwork.
        if not can(actor, Cap.CLIENT_ASSESSMENT_SCORE):
            raise HTTPException(
                status_code=403,
                detail=(f"Recording a score needs "
                        f"{Cap.CLIENT_ASSESSMENT_SCORE.value}, which your role does not "
                        f"hold. Administering an assessment and marking it are separate "
                        f"jobs (SOP section 12)."))
        updates["score"] = _validate_score(payload["score"],
                                           current.get("max_score") or 5)
        updates["scored_by_name"] = _actor_name(actor)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_ASSESSMENTS).update_one(
        {"cas_no": cas_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_ASSESSMENT_UPDATED, ENTITY_CLIENT_ASSESSMENT, cas_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_assessment(actor, company_id, cas_no)


# ─────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────
async def act_on_client_assessment(actor: dict, company_id: str, cas_no: str,
                                   action: str, payload: dict = None) -> dict:
    payload = payload or {}
    spec = CLIENT_ASSESSMENT_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_ASSESSMENT_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, cas_no)
    status = current.get("status")
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{cas_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(status_code=422, detail="Say why.")

    if action == "score" and current.get("score") is None:
        raise HTTPException(
            status_code=422,
            detail=("Record the score before marking it scored. A result with no figure "
                    "behind it cannot be compared with anybody else's."))
    if action == "share" and not current.get("result"):
        raise HTTPException(
            status_code=422,
            detail=("Record the Pass or Fail before sharing. A score with no verdict "
                    "leaves the client to guess what Sparsh concluded."))

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    if action == "record-submission":
        updates["submitted_at"] = now
    if action == "score":
        updates["scored_at"] = now
    if action == "share":
        updates["shared_at"] = now
    if action == "client-review":
        updates["client_review"] = {
            "remarks": remarks, "by": str(actor.get("_id") or ""),
            "by_name": _actor_name(actor), "at": now}

    result = await get_collection(COLL_CLIENT_ASSESSMENTS).update_one(
        {"cas_no": cas_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this assessment. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_ASSESSMENT_ACTIONED, ENTITY_CLIENT_ASSESSMENT, cas_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    if action == "client-review":
        await _move_candidate(actor, company_id, current["ccn_no"],
                              ClientCandidateStatus.ASSESSMENT_REVIEWED,
                              f"assessment {cas_no} reviewed by the client")

    fresh = await get_collection(COLL_CLIENT_ASSESSMENTS).find_one(
        {"cas_no": cas_no, "company_id": str(company_id)})
    return _client_view(fresh) if _is_client_side(actor) else _out(fresh)


# ─────────────────────────────────────────────────────────────
# The gate step 6 asks
# ─────────────────────────────────────────────────────────────
async def assert_interview_allowed(company_id: str, ccn_no: str) -> dict:
    """Interviews begin once the client has read the assessment result.

    Your flow puts the client's review between the result and the interview, so this is
    the question step 6 asks rather than re-deriving it.
    """
    doc = await get_collection(COLL_CLIENT_ASSESSMENTS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no})
    if not doc:
        raise HTTPException(
            status_code=409,
            detail=(f"{ccn_no} has no assessment on record. SOP section 12 puts the "
                    f"Talent Fit Assessment before the interview."))
    if doc.get("status") == ClientAssessmentStatus.REVIEWED.value:
        return _out(doc)
    raise HTTPException(
        status_code=409,
        detail=(f'{doc["cas_no"]} is "{doc.get("status")}". The interview stage opens '
                f"once the client has reviewed the assessment result."))
