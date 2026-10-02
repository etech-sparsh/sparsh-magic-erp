"""HRMS > Client Hiring, steps 8-9 — pre-boarding, joining, handover, closure.

PRO-fit SOP sections 18, 19 and 20. The last stretch: keeping an accepted candidate warm
until Day 1, recording that they turned up, and handing their file to the client's own HR
team — which is what closes the requisition.

-- Pre-boarding is engagement, not a gate -----------------------------------------------
Section 19 asks the recruiter to stay in periodic contact to manage counter-offer and
drop-out risk. Touchpoints are therefore a LOG, and nothing is blocked for want of one.
Making them a gate would punish the candidate for the recruiter being busy, and would turn
a useful signal into a box somebody ticks to unblock themselves. A touchpoint marked
at-risk is the one thing worth surfacing.

-- The client confirms joining, in writing ----------------------------------------------
Section 18: "the client/HR confirms candidate joining in writing". So CONFIRM is the
client's capability and no Sparsh role holds it. Sparsh can record that somebody dropped
out; it cannot declare that somebody started.

-- Closure follows the handover, and only the handover ---------------------------------
Section 20: the requisition is closed "only after this handover". So closure is not a
button. It happens as a consequence of the handover note being shared, and the handover
itself cannot be shared until the four items section 20 names are actually confirmed.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CANDIDATE_ACTIONED, AUDIT_CLIENT_JOINING_ACTIONED,
    AUDIT_CLIENT_JOINING_OPENED, AUDIT_CLIENT_JOINING_UPDATED, AUDIT_CLIENT_REQ_ACTIONED,
    AUDIT_CLIENT_TOUCHPOINT, CLIENT_HANDOVER_ITEMS, CLIENT_JOINING_TRANSITIONS,
    CLIENT_TRACK_FLAG, COLL_CLIENT_CANDIDATES, COLL_CLIENT_JOININGS,
    COLL_CLIENT_REQUISITIONS, ENTITY_CLIENT_CANDIDATE, ENTITY_CLIENT_JOINING,
    ENTITY_CLIENT_REQUISITION, Cap, ClientCandidateStatus, ClientJoiningStatus,
    ClientReqStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

MAX_TOUCHPOINTS = 50

# The contact log is Sparsh's working record of calls to a candidate — what they said
# about a counter-offer, how wobbly they sounded. The client sees everything else.
CLIENT_VISIBLE_FIELDS = (
    "cjn_no", "company_id", "ccn_no", "cr_no", "cof_no", "candidate_name",
    "joining_date", "actual_joining_date", "client_requirements_ready",
    "background_check_result", "culture_score", "handover_note",
    *[key for key, _ in CLIENT_HANDOVER_ITEMS],
    "status", "joining_confirmation", "handover", "at_risk",
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


def _date(value, label: str) -> Optional[str]:
    value = clean_text(value, limit=10)
    if value and not is_iso_date(value):
        raise HTTPException(
            status_code=422, detail=f"The {label} must be a valid YYYY-MM-DD date.")
    return value


async def _require_visible(actor: dict, company_id: str, cjn_no: str) -> dict:
    doc = await get_collection(COLL_CLIENT_JOININGS).find_one(
        {"cjn_no": cjn_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Joining record not found.")
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
async def list_client_joinings(actor: dict, company_id: Optional[str], *,
                               ccn_no: str = None, status: str = None,
                               limit: int = 200) -> dict:
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    elif _is_client_side(actor):
        raise HTTPException(status_code=403, detail="No company in scope.")
    if ccn_no:
        query["ccn_no"] = ccn_no
    if status:
        query["status"] = status

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_JOININGS).find(query).sort(
        "created_at", -1).to_list(limit)
    client_side = _is_client_side(actor)
    out = [(_client_view(r) if client_side else _out(r)) for r in rows]
    return {
        "client_joinings": out,
        "total": len(out),
        # Section 19's whole purpose: who is wobbling before Day 1.
        "at_risk": sum(1 for r in out if r.get("at_risk")),
        "awaiting_confirmation": sum(
            1 for r in out
            if r.get("status") == ClientJoiningStatus.PRE_BOARDING.value),
    }


async def get_client_joining(actor: dict, company_id: str, cjn_no: str) -> dict:
    doc = await _require_visible(actor, company_id, cjn_no)
    return _client_view(doc) if _is_client_side(actor) else _out(doc)


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
async def open_client_joining(actor: dict, company_id: str, payload: dict) -> dict:
    """Open pre-boarding. Only once a written acceptance is on record."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    ccn_no = clean_text(payload.get("ccn_no"), limit=40)
    if not ccn_no:
        raise HTTPException(status_code=422, detail="Choose a candidate.")

    existing = await get_collection(COLL_CLIENT_JOININGS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{existing.get("candidate_name") or ccn_no} is already in '
                    f'pre-boarding ({existing["cjn_no"]}, {existing["status"]}).'))

    # THE GATE. Section 17: no verbal offer is valid, so pre-boarding starts from a
    # recorded written acceptance and its joining date.
    from app.services.hrms_client_offer_service import assert_preboarding_allowed
    offer = await assert_preboarding_allowed(company_id, ccn_no)

    now = datetime.now(timezone.utc)
    cjn_no = await next_business_id("client_joining", str(company_id), now.year)
    doc = {
        "cjn_no": cjn_no,
        "company_id": str(company_id),
        "ccn_no": ccn_no,
        "cr_no": offer.get("cr_no"),
        "cof_no": offer.get("cof_no"),
        "candidate_name": offer.get("candidate_name"),
        "joining_date": (_date(payload.get("joining_date"), "joining date")
                         or offer.get("joining_date")),
        "actual_joining_date": None,
        "client_requirements_ready": False,
        "touchpoints": [],
        "at_risk": False,
        "background_check_result": None,
        "culture_score": None,
        "handover_note": None,
        **{key: False for key, _ in CLIENT_HANDOVER_ITEMS},
        "status": ClientJoiningStatus.PRE_BOARDING.value,
        "joining_confirmation": None,
        "handover": None,
        "opened_by": str(actor.get("_id") or ""),
        "opened_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_JOININGS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_JOINING_OPENED, ENTITY_CLIENT_JOINING, cjn_no,
                f'{doc["candidate_name"]} joining {doc["joining_date"]}', company_id)
    await _move_candidate(actor, company_id, ccn_no,
                          ClientCandidateStatus.PRE_BOARDING,
                          f"pre-boarding {cjn_no} opened")
    return _out(doc)


async def record_touchpoint(actor: dict, company_id: str, cjn_no: str,
                            payload: dict) -> dict:
    """SOP section 19 — one periodic contact. A log, never a gate."""
    current = await _require_visible(actor, company_id, cjn_no)
    if current.get("status") != ClientJoiningStatus.PRE_BOARDING.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{cjn_no} is "{current.get("status")}". Pre-boarding contact is for '
                    f"the window between acceptance and Day 1."))
    touchpoints = list(current.get("touchpoints") or [])
    if len(touchpoints) >= MAX_TOUCHPOINTS:
        raise HTTPException(
            status_code=409,
            detail=f"{cjn_no} already has {MAX_TOUCHPOINTS} touchpoints on record.")

    now = datetime.now(timezone.utc)
    at_risk = bool(payload.get("at_risk"))
    notes = clean_text(payload.get("notes"), limit=4000)
    if at_risk and not notes:
        raise HTTPException(
            status_code=422,
            detail=("Say what they said. Flagging somebody at risk with no note gives "
                    "whoever picks this up nothing to act on."))
    touchpoints.append({
        "contacted_on": _date(payload.get("contacted_on"), "contact date")
                        or now.strftime("%Y-%m-%d"),
        "channel": clean_text(payload.get("channel"), limit=60),
        "at_risk": at_risk,
        "notes": notes,
        "by_name": _actor_name(actor),
        "at": now,
    })
    await get_collection(COLL_CLIENT_JOININGS).update_one(
        {"cjn_no": cjn_no, "company_id": str(company_id)},
        # `at_risk` on the record is the LATEST reading, not a latch: somebody talked
        # round after a wobble is not still at risk, and a flag that only ever goes on
        # would make the worklist useless within a month.
        {"$set": {"touchpoints": touchpoints, "at_risk": at_risk, "updated_at": now}})
    await audit(actor, AUDIT_CLIENT_TOUCHPOINT, ENTITY_CLIENT_JOINING, cjn_no,
                ("at risk: " if at_risk else "") + (notes or "contacted"), company_id)
    return await get_client_joining(actor, company_id, cjn_no)


async def update_client_joining(actor: dict, company_id: str, cjn_no: str,
                                payload: dict) -> dict:
    """Joining date, client-side readiness, and section 20's post-joining results."""
    current = await _require_visible(actor, company_id, cjn_no)
    if current.get("status") in (ClientJoiningStatus.COMPLETED.value,
                                 ClientJoiningStatus.DROPPED.value):
        raise HTTPException(
            status_code=409,
            detail=f'{cjn_no} is "{current.get("status")}" and is closed.')

    updates: dict = {}
    if payload.get("joining_date") is not None:
        updates["joining_date"] = _date(payload["joining_date"], "joining date")
    if payload.get("client_requirements_ready") is not None:
        updates["client_requirements_ready"] = bool(payload["client_requirements_ready"])
    for field, limit in (("background_check_result", 2000), ("handover_note", 8000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("culture_score") is not None:
        try:
            score = float(payload["culture_score"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="The culture score must be a number.")
        if not 0 <= score <= 5:
            raise HTTPException(
                status_code=422, detail="The culture score runs from 0 to 5.")
        updates["culture_score"] = round(score, 2)
    for key, _label in CLIENT_HANDOVER_ITEMS:
        if payload.get(key) is not None:
            updates[key] = bool(payload[key])

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_JOININGS).update_one(
        {"cjn_no": cjn_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_JOINING_UPDATED, ENTITY_CLIENT_JOINING, cjn_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_joining(actor, company_id, cjn_no)


# ─────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────
def _assert_handover_ready(doc: dict) -> None:
    """SOP section 20 — the file, the scorecards, the records, the verification status."""
    missing = [label for key, label in CLIENT_HANDOVER_ITEMS if not doc.get(key)]
    if not doc.get("handover_note"):
        missing.append("the handover note itself")
    if missing:
        raise HTTPException(
            status_code=422,
            detail=("Section 20 hands the client's HR team a complete file so they can "
                    "carry on without asking. Still needed: " + ", ".join(missing) + "."))


async def _close_requisition(actor: dict, company_id: str, cr_no: str,
                             cjn_no: str) -> None:
    """Section 20: the requisition is closed only after the handover.

    Done here rather than exposed as an action, so closure cannot happen before the thing
    the SOP conditions it on.
    """
    if not cr_no:
        return
    coll = get_collection(COLL_CLIENT_REQUISITIONS)
    req = await coll.find_one({"cr_no": cr_no, "company_id": str(company_id)})
    if not req or req.get("status") == ClientReqStatus.CLOSED.value:
        return
    previous = req.get("status")
    await coll.update_one(
        {"cr_no": cr_no, "company_id": str(company_id)},
        {"$set": {"status": ClientReqStatus.CLOSED.value,
                  "closed_at": datetime.now(timezone.utc),
                  "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_CLIENT_REQ_ACTIONED, ENTITY_CLIENT_REQUISITION, cr_no,
                f"{previous} -> {ClientReqStatus.CLOSED.value} "
                f"(handover {cjn_no} completed)", company_id)


async def act_on_client_joining(actor: dict, company_id: str, cjn_no: str,
                                action: str, payload: dict = None) -> dict:
    payload = payload or {}
    spec = CLIENT_JOINING_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_JOINING_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, cjn_no)
    status = current.get("status")
    if status in (ClientJoiningStatus.COMPLETED.value,
                  ClientJoiningStatus.DROPPED.value):
        raise HTTPException(
            status_code=409, detail=f'{cjn_no} is "{status}" and is closed.')
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{cjn_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail=("Say why they did not join. A drop-out with no reason recorded is a "
                    "lesson nobody learns."))

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    stamp = {"remarks": remarks, "by": str(actor.get("_id") or ""),
             "by_name": _actor_name(actor), "at": now}

    if action == "confirm-joining":
        # Section 18 wants the date they actually started and the candidate's own
        # acknowledgement, both recorded rather than assumed.
        actual = _date(payload.get("actual_joining_date"), "actual joining date")
        if not actual:
            raise HTTPException(
                status_code=422,
                detail=("Record the date they actually started. Section 18 confirms "
                        "joining in writing, and a confirmation with no date confirms "
                        "nothing."))
        if not payload.get("acknowledged"):
            raise HTTPException(
                status_code=422,
                detail=("Confirm the candidate's own acknowledgement of joining "
                        "(section 18)."))
        updates["actual_joining_date"] = actual
        updates["joining_confirmation"] = {**stamp, "actual_joining_date": actual,
                                           "acknowledged": True}
    if action == "share-handover":
        _assert_handover_ready(current)
        updates["handover"] = stamp

    result = await get_collection(COLL_CLIENT_JOININGS).update_one(
        {"cjn_no": cjn_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this record. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_JOINING_ACTIONED, ENTITY_CLIENT_JOINING, cjn_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    stage = {"confirm-joining": ClientCandidateStatus.JOINED,
             "record-drop": ClientCandidateStatus.DROPPED}.get(action)
    if stage:
        await _move_candidate(actor, company_id, current["ccn_no"], stage,
                              f"{cjn_no} {action.replace('-', ' ')}")
    if action == "share-handover":
        await _close_requisition(actor, company_id, current.get("cr_no"), cjn_no)

    fresh = await get_collection(COLL_CLIENT_JOININGS).find_one(
        {"cjn_no": cjn_no, "company_id": str(company_id)})
    return _client_view(fresh) if _is_client_side(actor) else _out(fresh)
