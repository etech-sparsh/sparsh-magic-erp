"""HRMS > Client Hiring, step 7 — reference check and the offer.

PRO-fit SOP sections 15, 16 and 17, and the section 8 approval matrix.

-- Section 16 is a checkpoint, and it is enforced ---------------------------------------
"Before offer release, the recruiter must confirm: (a) client's final selection in
writing, (b) agreed compensation is within the MRF-approved salary range, and (c) ... Any
deviation from the approved salary range requires Team Lead and client HOD sign-off."

All three are checks here rather than a list somebody reads:

  (a) the client's selection, which step 6 recorded
  (b) the figure, against the range the client themselves put on the Manpower Requisition
  (c) section 15's reference check, for managerial and above

-- Section 17: the CLIENT releases the letter -------------------------------------------
The matrix reads "Offer letter release -- Recruiter: Facilitate, Team Lead: Verify docs,
Client: Approve & Issue". So the recruiter prepares, the Team Lead verifies, and the
client issues. No Sparsh role holds the release capability, which is what stops
"Approve & Issue" quietly becoming something the supplier does on the client's behalf.

Section 17 also states that no verbal offer is valid, which is why acceptance is recorded
against a RELEASED offer with a date, rather than being a status somebody sets.

-- Reference checks stay at Sparsh --------------------------------------------------------
Section 15 shares the background check and culture score with the client AFTER joining. A
referee's candid remarks about somebody who may never be hired are not part of that, so
the reference capabilities are absent from the client ceiling entirely.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CANDIDATE_ACTIONED, AUDIT_CLIENT_OFFER_ACTIONED,
    AUDIT_CLIENT_OFFER_CREATED, AUDIT_CLIENT_OFFER_UPDATED,
    AUDIT_CLIENT_REFERENCE_RECORDED, CLIENT_OFFER_EDITABLE,
    CLIENT_OFFER_TRANSITIONS, CLIENT_OFFER_VISIBLE_TO_CLIENT,
    CLIENT_REFERENCE_CLEARS, CLIENT_REFERENCE_REQUIRED_LEVELS, CLIENT_TRACK_FLAG,
    COLL_CLIENT_CANDIDATES, COLL_CLIENT_OFFERS, COLL_CLIENT_REFERENCE_CHECKS,
    COLL_CLIENT_REQUISITIONS, ENTITY_CLIENT_CANDIDATE, ENTITY_CLIENT_OFFER,
    ENTITY_CLIENT_REFERENCE, Cap, ClientCandidateStatus, ClientOfferStatus,
    ClientReferenceOutcome, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

MAX_CTC = 1_000_000_000

# The negotiation notes are Sparsh's working record of what was said to get to a figure.
# The client sees the figure and the terms, which is what they are approving.
CLIENT_VISIBLE_FIELDS = (
    "cof_no", "company_id", "ccn_no", "cr_no", "candidate_name", "designation",
    "offered_ctc", "joining_date", "terms", "status", "salary_range_min",
    "salary_range_max", "verification", "client_release", "acceptance",
    # The deviation request is ADDRESSED to the client -- the reason Sparsh gave and the
    # decision they made on it. Withholding either would be asking them to approve a
    # number with no argument attached.
    "deviation",
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


def _money(value, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount <= 0 or amount > MAX_CTC:
        raise HTTPException(status_code=422, detail=f"{label} is not a plausible figure.")
    return round(amount, 2)


# ═════════════════════════════════════════════════════════════
# Reference checks (SOP section 15) — Sparsh only
# ═════════════════════════════════════════════════════════════
async def list_client_references(actor: dict, company_id: Optional[str], *,
                                 ccn_no: str = None, limit: int = 200) -> dict:
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    if ccn_no:
        query["ccn_no"] = ccn_no
    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_REFERENCE_CHECKS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {"client_reference_checks": out, "total": len(out)}


async def record_client_reference(actor: dict, company_id: str, payload: dict) -> dict:
    """Record one reference (SOP section 15: last employer, conduct, reason for leaving)."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    ccn_no = clean_text(payload.get("ccn_no"), limit=40)
    referee = clean_text(payload.get("referee_name"), limit=180)
    if not ccn_no or not referee:
        raise HTTPException(
            status_code=422,
            detail=("Record who the reference was taken from. An anonymous reference is "
                    "not a reference."))

    candidate = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
    try:
        outcome = ClientReferenceOutcome(raw or ClientReferenceOutcome.POSITIVE.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=("Outcome must be one of: "
                    + ", ".join(o.value for o in ClientReferenceOutcome) + "."))

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if outcome is not ClientReferenceOutcome.POSITIVE and not remarks:
        raise HTTPException(
            status_code=422,
            detail=(f'Record what was said. A "{outcome.value}" reference with no note '
                    f"cannot be acted on by whoever reads it next."))

    checked_on = clean_text(payload.get("checked_on"), limit=10)
    if checked_on and not is_iso_date(checked_on):
        raise HTTPException(
            status_code=422, detail="The check date must be a valid YYYY-MM-DD date.")

    now = datetime.now(timezone.utc)
    crf_no = await next_business_id("client_reference", str(company_id), now.year)
    doc = {
        "crf_no": crf_no,
        "company_id": str(company_id),
        "ccn_no": ccn_no,
        "cr_no": candidate.get("cr_no"),
        "candidate_name": candidate.get("candidate_name"),
        "referee_name": referee,
        "referee_organisation": clean_text(payload.get("referee_organisation"), limit=180),
        "relationship": clean_text(payload.get("relationship"), limit=140),
        "referee_contact": clean_text(payload.get("referee_contact"), limit=180),
        "outcome": outcome.value,
        "checked_on": checked_on or now.strftime("%Y-%m-%d"),
        "remarks": remarks,
        "recorded_by": str(actor.get("_id") or ""),
        "recorded_by_name": _actor_name(actor),
        "created_at": now,
    }
    await get_collection(COLL_CLIENT_REFERENCE_CHECKS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_REFERENCE_RECORDED, ENTITY_CLIENT_REFERENCE, crf_no,
                f'{outcome.value} for {candidate.get("candidate_name")}', company_id)
    return _out(doc)


async def _reference_state(company_id: str, ccn_no: str, requisition: dict) -> dict:
    """Whether section 15's pre-offer reference applies here, and whether it is met.

    Returned rather than raised so a screen can show "waiting on a reference" while the
    offer is still being drafted, and only the RELEASE is refused.
    """
    level = (requisition or {}).get("role_level")
    required = level in CLIENT_REFERENCE_REQUIRED_LEVELS
    rows = await get_collection(COLL_CLIENT_REFERENCE_CHECKS).find(
        {"company_id": str(company_id), "ccn_no": ccn_no}).to_list(50)
    cleared = any(r.get("outcome") in CLIENT_REFERENCE_CLEARS for r in rows)
    return {"role_level": level, "required": required,
            "on_record": len(rows), "cleared": cleared,
            "satisfied": (not required) or cleared}


# ═════════════════════════════════════════════════════════════
# The offer (SOP sections 16-17)
# ═════════════════════════════════════════════════════════════
async def _require_visible(actor: dict, company_id: str, cof_no: str) -> dict:
    doc = await get_collection(COLL_CLIENT_OFFERS).find_one(
        {"cof_no": cof_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Offer not found.")
    if (_is_client_side(actor)
            and doc.get("status") not in CLIENT_OFFER_VISIBLE_TO_CLIENT):
        raise HTTPException(status_code=404, detail="Offer not found.")
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


async def list_client_offers(actor: dict, company_id: Optional[str], *,
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
        allowed = sorted(CLIENT_OFFER_VISIBLE_TO_CLIENT)
        query["status"] = ({"$in": allowed} if not status
                           else (status if status in CLIENT_OFFER_VISIBLE_TO_CLIENT
                                 else "__none__"))
    elif status:
        query["status"] = status

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_OFFERS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [(_client_view(r) if client_side else _out(r)) for r in rows]
    return {
        "client_offers": out,
        "total": len(out),
        # A deviation request sits with Client HR exactly as an offer awaiting release
        # does, so it counts as waiting on the client -- otherwise the one stage that
        # needs their attention most would show a zero on the board.
        "awaiting_client": sum(
            1 for r in out
            if r.get("status") in (ClientOfferStatus.PENDING_CLIENT_APPROVAL.value,
                                   ClientOfferStatus.PENDING_DEVIATION.value)),
    }


async def get_client_offer(actor: dict, company_id: str, cof_no: str) -> dict:
    doc = await _require_visible(actor, company_id, cof_no)
    return _client_view(doc) if _is_client_side(actor) else _out(doc)


async def create_client_offer(actor: dict, company_id: str, payload: dict) -> dict:
    """Prepare the terms. Only for somebody the client has selected."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    ccn_no = clean_text(payload.get("ccn_no"), limit=40)
    if not ccn_no:
        raise HTTPException(status_code=422, detail="Choose a candidate.")

    live = await get_collection(COLL_CLIENT_OFFERS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no,
         "status": {"$ne": ClientOfferStatus.DECLINED.value}})
    if live:
        raise HTTPException(
            status_code=409,
            detail=(f'{live.get("candidate_name") or ccn_no} already has an offer '
                    f'({live["cof_no"]}, {live["status"]}).'))

    # Section 16 (a) -- the client's final selection, which step 6 recorded.
    from app.services.hrms_client_interview_service import assert_offer_stage_allowed
    candidate = await assert_offer_stage_allowed(company_id, ccn_no)

    requisition = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": candidate.get("cr_no"), "company_id": str(company_id)}) or {}
    offered = _money(payload.get("offered_ctc"), "The offered CTC")
    joining = clean_text(payload.get("joining_date"), limit=10)
    if joining and not is_iso_date(joining):
        raise HTTPException(
            status_code=422, detail="The joining date must be a valid YYYY-MM-DD date.")

    now = datetime.now(timezone.utc)
    cof_no = await next_business_id("client_offer", str(company_id), now.year)
    doc = {
        "cof_no": cof_no,
        "company_id": str(company_id),
        "ccn_no": ccn_no,
        "cr_no": candidate.get("cr_no"),
        "candidate_name": candidate.get("candidate_name"),
        "designation": (clean_text(payload.get("designation"), limit=180)
                        or requisition.get("role_title")),
        "offered_ctc": offered,
        # The range AS IT STOOD, stamped on the offer. A later change to the requisition
        # must not rewrite what this offer was checked against.
        "salary_range_min": requisition.get("salary_range_min"),
        "salary_range_max": requisition.get("salary_range_max"),
        "role_level": requisition.get("role_level"),
        "joining_date": joining,
        "terms": clean_text(payload.get("terms"), limit=8000),
        "negotiation_notes": None,
        "status": ClientOfferStatus.DRAFT.value,
        "verification": None, "client_release": None, "acceptance": None,
        "deviation": None,
        "prepared_by": str(actor.get("_id") or ""),
        "prepared_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_OFFERS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_OFFER_CREATED, ENTITY_CLIENT_OFFER, cof_no,
                f'{doc["candidate_name"]} at {offered:,.0f}', company_id)
    return _out(doc)


async def update_client_offer(actor: dict, company_id: str, cof_no: str,
                              payload: dict) -> dict:
    """Amend the terms while the offer is still a draft."""
    current = await _require_visible(actor, company_id, cof_no)
    if current.get("status") not in CLIENT_OFFER_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=(f'{cof_no} is "{current.get("status")}" and cannot be edited. '
                    f"Have it returned to draft first."))

    updates: dict = {}
    if payload.get("offered_ctc") is not None:
        updates["offered_ctc"] = _money(payload["offered_ctc"], "The offered CTC")
    if payload.get("joining_date") is not None:
        joining = clean_text(payload["joining_date"], limit=10)
        if joining and not is_iso_date(joining):
            raise HTTPException(
                status_code=422,
                detail="The joining date must be a valid YYYY-MM-DD date.")
        updates["joining_date"] = joining
    for field, limit in (("designation", 180), ("terms", 8000),
                         ("negotiation_notes", 8000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_OFFERS).update_one(
        {"cof_no": cof_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_OFFER_UPDATED, ENTITY_CLIENT_OFFER, cof_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_offer(actor, company_id, cof_no)


async def offer_checkpoint(company_id: str, offer: dict) -> dict:
    """SOP section 16's three conditions, as a readable state.

    Returned rather than raised so the offer screen can show what is outstanding while it
    is being prepared, and only the SUBMIT is refused. One function, so the screen and the
    gate can never disagree about what "ready" means.
    """
    requisition = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": offer.get("cr_no"), "company_id": str(company_id)}) or {}
    reference = await _reference_state(company_id, offer["ccn_no"], requisition)

    lo, hi = offer.get("salary_range_min"), offer.get("salary_range_max")
    ctc = offer.get("offered_ctc")
    within = True
    if lo is not None and hi is not None and ctc is not None:
        within = float(lo) <= float(ctc) <= float(hi)

    # The range is reported SEPARATELY from everything else, because it is the one
    # condition with its own way forward: a salary deviation request to Client HR. The
    # others have to be fixed before the offer moves at all.
    outstanding = []
    range_gap = None
    if not within:
        range_gap = (
            f"{ctc:,.0f} is outside the range the client approved "
            f"({float(lo):,.0f} to {float(hi):,.0f})")
        outstanding.append(
            range_gap + "; send a salary deviation request to Client HR")
    other = []
    if not reference["satisfied"]:
        other.append(
            f'a reference check — section 15 asks for one before offer release on a '
            f'"{reference["role_level"]}" role')
    outstanding.extend(other)
    return {"within_approved_range": within, "reference": reference,
            # `outstanding` and `ready` keep their existing meaning exactly: everything
            # blocking the ORDINARY submit. The two keys below are additions for the
            # deviation path, not a redefinition of the two above.
            "outstanding": outstanding, "ready": not outstanding,
            "range_gap": range_gap,
            "deviation_blockers": other,
            "deviation_ready": not other}


async def act_on_client_offer(actor: dict, company_id: str, cof_no: str,
                              action: str, payload: dict = None) -> dict:
    payload = payload or {}
    spec = CLIENT_OFFER_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_OFFER_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, cof_no)
    status = current.get("status")
    if status in (ClientOfferStatus.ACCEPTED.value, ClientOfferStatus.DECLINED.value):
        raise HTTPException(
            status_code=409,
            detail=f'{cof_no} is "{status}" and is closed.')
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{cof_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(status_code=422, detail="Say why.")

    # Section 16 -- the checkpoint, enforced at the point the offer leaves the recruiter.
    if action == "submit-for-verification":
        state = await offer_checkpoint(company_id, current)
        if not state["ready"]:
            raise HTTPException(
                status_code=409,
                detail=("Section 16's offer checkpoint is not met. Outstanding: "
                        + "; ".join(state["outstanding"]) + "."))

    # The deviation request is for an offer that is ACTUALLY outside the range. An offer
    # that fits has an ordinary route and does not get to borrow Client HR's attention.
    if action == "submit-deviation":
        state = await offer_checkpoint(company_id, current)
        if state["within_approved_range"]:
            raise HTTPException(
                status_code=422,
                detail=(f"{cof_no} is inside the range the client approved, so it does "
                        f'not need a deviation. Use "submit-for-verification".'))
        # Everything section 16 asks for EXCEPT the range still applies. A deviation is
        # permission to pay more, not permission to skip the reference check.
        if not state["deviation_ready"]:
            raise HTTPException(
                status_code=409,
                detail=("Section 16 still asks for: "
                        + "; ".join(state["deviation_blockers"])
                        + ". A salary deviation covers the figure, nothing else."))

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    stamp = {"remarks": remarks, "by": str(actor.get("_id") or ""),
             "by_name": _actor_name(actor), "at": now}

    # A return records ITS OWN reason and clears the OTHER side's approval.
    #
    # Both halves matter. The reason is the most useful thing on a returned offer, so
    # wiping it would throw away the only instruction the recruiter has. The other side's
    # approval, meanwhile, was given to a version that is about to be rewritten, and a
    # record still showing "verified" against changed terms is a claim about a document
    # nobody will read again.
    if action == "submit-deviation":
        # `remarks` is the case being put to Client HR, and the figures are stamped
        # alongside it so the record still reads correctly years later, when the
        # requisition's own numbers are long out of context.
        updates["deviation"] = {
            "requested": {**stamp},
            "offered_ctc": current.get("offered_ctc"),
            "salary_range_min": current.get("salary_range_min"),
            "salary_range_max": current.get("salary_range_max"),
            "decision": None,
        }
    if action in ("deviation-approve", "deviation-reject"):
        existing = dict(current.get("deviation") or {})
        existing["decision"] = {**stamp,
                                "decision": action.replace("deviation-", "")}
        updates["deviation"] = existing

    if action in ("verify", "return"):
        updates["verification"] = {**stamp, "decision": action}
        if action == "return":
            updates["client_release"] = None
            # A return reopens the terms, so an approval given for the OLD figure is no
            # longer an approval of anything. Same reasoning as clearing `client_release`
            # above: a record still showing "approved" against changed terms is a claim
            # about a document nobody will read again. Re-submitting re-asks Client HR.
            updates["deviation"] = None
    if action in ("client-release", "client-return"):
        updates["client_release"] = {**stamp, "decision": action}
        if action == "client-return":
            updates["verification"] = None
            updates["deviation"] = None

    if action == "record-acceptance":
        # Section 17: no verbal offer is valid, and the recruiter confirms the written
        # acceptance AND the joining date. Both are required here for that reason.
        accepted_on = clean_text(payload.get("accepted_on"), limit=10)
        joining = clean_text(payload.get("joining_date"), limit=10) \
            or current.get("joining_date")
        for value, label in ((accepted_on, "acceptance date"), (joining, "joining date")):
            if not value:
                raise HTTPException(
                    status_code=422,
                    detail=(f"Record the {label}. Section 17 asks the recruiter to "
                            f"confirm the written acceptance and the joining date; a "
                            f"verbal offer is not valid."))
            if not is_iso_date(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"The {label} must be a valid YYYY-MM-DD date.")
        updates["joining_date"] = joining
        updates["acceptance"] = {**stamp, "accepted_on": accepted_on,
                                 "joining_date": joining}
    if action == "record-decline":
        updates["acceptance"] = {**stamp, "declined": True}

    result = await get_collection(COLL_CLIENT_OFFERS).update_one(
        {"cof_no": cof_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this offer. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_OFFER_ACTIONED, ENTITY_CLIENT_OFFER, cof_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    stage = {"client-release": ClientCandidateStatus.OFFER_RELEASED,
             "record-acceptance": ClientCandidateStatus.OFFER_ACCEPTED,
             "record-decline": ClientCandidateStatus.OFFER_DECLINED,
             # Client HR refusing the deviation ends this candidate's run at THIS client
             # and nothing more. `Client Rejected` is already an Available Candidates pool
             # state (CLIENT_CANDIDATE_POOL), so the existing reject flow takes it from
             # here: the person stays sourced, re-shareable to a client whose range fits.
             "deviation-reject": ClientCandidateStatus.CLIENT_REJECTED}.get(action)
    if stage:
        await _move_candidate(actor, company_id, current["ccn_no"], stage,
                              f"offer {cof_no} {action.replace('-', ' ')}")

    fresh = await get_collection(COLL_CLIENT_OFFERS).find_one(
        {"cof_no": cof_no, "company_id": str(company_id)})
    return _client_view(fresh) if _is_client_side(actor) else _out(fresh)


# ─────────────────────────────────────────────────────────────
# The gate step 8 asks
# ─────────────────────────────────────────────────────────────
async def assert_preboarding_allowed(company_id: str, ccn_no: str) -> dict:
    """Pre-boarding begins once a written acceptance is on record (SOP sections 17-19)."""
    doc = await get_collection(COLL_CLIENT_OFFERS).find_one(
        {"company_id": str(company_id), "ccn_no": ccn_no,
         "status": ClientOfferStatus.ACCEPTED.value})
    if doc:
        return _out(doc)
    raise HTTPException(
        status_code=409,
        detail=("Pre-boarding begins once the candidate's written acceptance and joining "
                "date are on record. Section 17: no verbal offer is valid."))
