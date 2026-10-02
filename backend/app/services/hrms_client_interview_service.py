"""HRMS > Client Hiring, step 6 — interview, recording, client selection.

PRO-fit SOP section 12 ("personal interview conducted on a recorded platform by the
internal recruitment panel") and section 14, which lists the recorded interview link among
what the client receives.

-- Sparsh conducts, the client watches --------------------------------------------------
The SOP also describes a separate client-run interview. The agreed flow replaced it: the
client watches Sparsh's recording and then selects or rejects. So there is no client-side
panel here, and the recording is a LINK to the meeting platform rather than an upload,
which is what section 14 asks for.

-- The selection is the client's ---------------------------------------------------------
This is the moment a person is chosen, and no Sparsh role holds the capability to do it.
Everything before it — scheduling, conducting, scoring, delivering — is Sparsh's.

-- Sharing needs something to watch --------------------------------------------------------
An interview cannot be delivered to the client without the recording link and an outcome.
Sending somebody a decision to make with nothing to base it on is not a handover.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CANDIDATE_ACTIONED, AUDIT_CLIENT_INTERVIEW_ACTIONED,
    AUDIT_CLIENT_INTERVIEW_SCHEDULED, AUDIT_CLIENT_INTERVIEW_UPDATED,
    CLIENT_INTERVIEW_CRITERIA, CLIENT_INTERVIEW_TRANSITIONS,
    CLIENT_INTERVIEW_VISIBLE_TO_CLIENT, CLIENT_TRACK_FLAG,
    COLL_CLIENT_CANDIDATES, COLL_CLIENT_INTERVIEWS,
    ENTITY_CLIENT_CANDIDATE, ENTITY_CLIENT_INTERVIEW,
    Cap, ClientCandidateStatus, ClientInterviewStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

MAX_PANEL = 8

# The panel's private notes never leave Sparsh. Everything else about the interview does,
# because the client is being asked to decide on it.
CLIENT_VISIBLE_FIELDS = (
    "cin_no", "company_id", "ccn_no", "cr_no", "candidate_name",
    "scheduled_at", "mode", "panel", "recording_link",
    "role_fit", "communication", "technical_depth", "culture_fit",
    "average_score", "outcome", "status", "conducted_at", "shared_at",
    "client_decision", "created_at", "updated_at",
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


def _rating(value, label: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if not 0 <= score <= 5:
        raise HTTPException(
            status_code=422, detail=f"{label} is scored from 0 to 5 (SOP section 13).")
    return round(score, 2)


def _panel(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="The panel is a list of names.")
    names = [clean_text(v, limit=140) for v in value]
    names = [n for n in names if n]
    if len(names) > MAX_PANEL:
        raise HTTPException(
            status_code=422, detail=f"A panel of more than {MAX_PANEL} is a meeting.")
    return names


def _average(doc: dict) -> Optional[float]:
    have = [float(doc[k]) for k, _ in CLIENT_INTERVIEW_CRITERIA
            if doc.get(k) is not None]
    return round(sum(have) / len(have), 2) if have else None


async def _require_visible(actor: dict, company_id: str, cin_no: str) -> dict:
    doc = await get_collection(COLL_CLIENT_INTERVIEWS).find_one(
        {"cin_no": cin_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Interview not found.")
    if (_is_client_side(actor)
            and doc.get("status") not in CLIENT_INTERVIEW_VISIBLE_TO_CLIENT):
        raise HTTPException(status_code=404, detail="Interview not found.")
    return doc


async def _move_candidate(actor: dict, company_id: str, ccn_no: str,
                          target: ClientCandidateStatus, why: str) -> None:
    coll = get_collection(COLL_CLIENT_CANDIDATES)
    candidate = await coll.find_one({"ccn_no": ccn_no, "company_id": str(company_id)})
    if not candidate or candidate.get("status") == target.value:
        return
    current = candidate.get("status")
    await coll.update_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)},
        {"$set": {"status": target.value, "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_CLIENT_CANDIDATE_ACTIONED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"{current} -> {target.value} ({why})", company_id)


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_client_interviews(actor: dict, company_id: Optional[str], *,
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
        allowed = sorted(CLIENT_INTERVIEW_VISIBLE_TO_CLIENT)
        query["status"] = ({"$in": allowed} if not status
                           else (status if status in CLIENT_INTERVIEW_VISIBLE_TO_CLIENT
                                 else "__none__"))
    elif status:
        query["status"] = status

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_INTERVIEWS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [(_client_view(r) if client_side else _out(r)) for r in rows]
    return {
        "client_interviews": out,
        "total": len(out),
        "awaiting_client": sum(
            1 for r in out if r.get("status") == ClientInterviewStatus.SHARED.value),
    }


async def get_client_interview(actor: dict, company_id: str, cin_no: str) -> dict:
    doc = await _require_visible(actor, company_id, cin_no)
    return _client_view(doc) if _is_client_side(actor) else _out(doc)


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
async def create_client_interview(actor: dict, company_id: str, payload: dict) -> dict:
    """Schedule it. Only once the client has reviewed the assessment result."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    ccn_no = clean_text(payload.get("ccn_no"), limit=40)
    if not ccn_no:
        raise HTTPException(status_code=422, detail="Choose a candidate.")
    scheduled_at = clean_text(payload.get("scheduled_at"), limit=40)
    if not scheduled_at:
        raise HTTPException(status_code=422, detail="Say when the interview is.")

    # An interview already under way or decided is not something to duplicate. A second
    # sitting after a rejection is a new candidate decision, not a second row here.
    live = await get_collection(COLL_CLIENT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no,
         "status": {"$ne": ClientInterviewStatus.CLIENT_REJECTED.value}})
    if live:
        raise HTTPException(
            status_code=409,
            detail=(f'{live.get("candidate_name") or ccn_no} already has an interview '
                    f'({live["cin_no"]}, {live["status"]}).'))

    # THE GATE. The client's review of the assessment result opens this stage.
    from app.services.hrms_client_assessment_service import assert_interview_allowed
    await assert_interview_allowed(company_id, ccn_no)

    candidate = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})

    now = datetime.now(timezone.utc)
    cin_no = await next_business_id("client_interview", str(company_id), now.year)
    doc = {
        "cin_no": cin_no,
        "company_id": str(company_id),
        "ccn_no": ccn_no,
        "cr_no": (candidate or {}).get("cr_no"),
        "psc_no": (candidate or {}).get("psc_no"),
        "candidate_name": (candidate or {}).get("candidate_name"),
        "scheduled_at": scheduled_at,
        "mode": clean_text(payload.get("mode"), limit=40) or "Virtual",
        "meeting_link": clean_text(payload.get("meeting_link"), limit=500),
        "panel": _panel(payload.get("panel")),
        "recording_link": None,
        **{key: None for key, _ in CLIENT_INTERVIEW_CRITERIA},
        "average_score": None,
        "outcome": None,
        "panel_notes": None,
        "status": ClientInterviewStatus.SCHEDULED.value,
        "conducted_at": None, "shared_at": None,
        "client_decision": None,
        "scheduled_by": str(actor.get("_id") or ""),
        "scheduled_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_INTERVIEWS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_INTERVIEW_SCHEDULED, ENTITY_CLIENT_INTERVIEW, cin_no,
                f'{doc["candidate_name"]} on {scheduled_at}', company_id)
    await _move_candidate(actor, company_id, ccn_no, ClientCandidateStatus.INTERVIEW,
                          f"interview {cin_no} scheduled")
    return _out(doc)


async def update_client_interview(actor: dict, company_id: str, cin_no: str,
                                  payload: dict) -> dict:
    """Scores, the outcome, the recording link and the panel's notes."""
    current = await _require_visible(actor, company_id, cin_no)
    if current.get("status") in CLIENT_INTERVIEW_VISIBLE_TO_CLIENT:
        raise HTTPException(
            status_code=409,
            detail=(f"{cin_no} is with the client. Changing an interview record somebody "
                    f"is deciding on would rewrite what they were shown."))

    updates: dict = {}
    for field, limit in (("scheduled_at", 40), ("mode", 40), ("meeting_link", 500),
                         ("recording_link", 500), ("panel_notes", 8000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("panel") is not None:
        updates["panel"] = _panel(payload["panel"])
    for key, label in CLIENT_INTERVIEW_CRITERIA:
        if payload.get(key) is not None:
            updates[key] = _rating(payload[key], label)
    if payload.get("outcome") is not None:
        outcome = clean_text(payload["outcome"], limit=40)
        if outcome and outcome.title() not in ("Recommend", "Do Not Recommend"):
            raise HTTPException(
                status_code=422,
                detail="The panel's outcome is Recommend or Do Not Recommend.")
        updates["outcome"] = outcome.title() if outcome else None

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["average_score"] = _average({**current, **updates})
    updates["updated_at"] = datetime.now(timezone.utc)

    await get_collection(COLL_CLIENT_INTERVIEWS).update_one(
        {"cin_no": cin_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_INTERVIEW_UPDATED, ENTITY_CLIENT_INTERVIEW, cin_no,
                ", ".join(sorted(k for k in updates
                                 if k not in ("updated_at", "average_score"))), company_id)
    return await get_client_interview(actor, company_id, cin_no)


# ─────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────
async def act_on_client_interview(actor: dict, company_id: str, cin_no: str,
                                  action: str, payload: dict = None) -> dict:
    payload = payload or {}
    spec = CLIENT_INTERVIEW_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_INTERVIEW_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, cin_no)
    status = current.get("status")
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{cin_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say why. A candidate turned down after a full interview is owed one.")

    if action == "record-outcome" and not current.get("outcome"):
        raise HTTPException(
            status_code=422,
            detail=("Record the panel's outcome first. An interview with no conclusion "
                    "leaves nothing for the client to weigh."))
    if action == "share":
        missing = []
        if not current.get("recording_link"):
            missing.append("the recording link")
        # ALL FOUR criteria, named individually. This used to test `average_score is None`,
        # which `_average` returns as soon as ONE criterion is filled -- so an interview
        # scored on role fit alone could be shared as though the panel had assessed the
        # whole person. The client weighs these four against the scorecard; three of them
        # silently blank is not a score, it is a gap the client cannot see.
        for key, label in CLIENT_INTERVIEW_CRITERIA:
            if current.get(key) is None:
                missing.append(f"the {label.lower()} score")
        if missing:
            raise HTTPException(
                status_code=422,
                detail=("Section 14 shares the recorded interview and its scores with the "
                        "client. Still needed: " + ", ".join(missing) + "."))

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    if action == "record-outcome":
        updates["conducted_at"] = now
    if action == "share":
        updates["shared_at"] = now
    if action.startswith("client-"):
        updates["client_decision"] = {
            "decision": action.split("-", 1)[1], "remarks": remarks,
            "by": str(actor.get("_id") or ""), "by_name": _actor_name(actor), "at": now}

    result = await get_collection(COLL_CLIENT_INTERVIEWS).update_one(
        {"cin_no": cin_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this interview. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_INTERVIEW_ACTIONED, ENTITY_CLIENT_INTERVIEW, cin_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    if action == "client-select":
        await _move_candidate(actor, company_id, current["ccn_no"],
                              ClientCandidateStatus.SELECTED,
                              f"selected by the client after {cin_no}")
    if action == "client-reject":
        await _move_candidate(actor, company_id, current["ccn_no"],
                              ClientCandidateStatus.CLIENT_REJECTED,
                              f"rejected by the client after {cin_no}")

    fresh = await get_collection(COLL_CLIENT_INTERVIEWS).find_one(
        {"cin_no": cin_no, "company_id": str(company_id)})
    return _client_view(fresh) if _is_client_side(actor) else _out(fresh)


# ─────────────────────────────────────────────────────────────
# The gate step 7 asks
# ─────────────────────────────────────────────────────────────
async def assert_offer_stage_allowed(company_id: str, ccn_no: str) -> dict:
    """The offer chain opens on the client's SELECTION, and nothing earlier.

    SOP section 16 requires "client's final selection in writing" before an offer is
    prepared. This is that, recorded.
    """
    candidate = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if candidate.get("status") == ClientCandidateStatus.SELECTED.value:
        return _out(candidate)
    raise HTTPException(
        status_code=409,
        detail=(f'{candidate.get("candidate_name")} is "{candidate.get("status")}". '
                f"SOP section 16 asks for the client's final selection in writing before "
                f"anything is offered."))
