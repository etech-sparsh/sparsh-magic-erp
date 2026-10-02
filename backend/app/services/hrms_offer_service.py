"""HRMS > offer letters and the public accept/decline page.

Issues, versions and tracks offer letters, and closes the requisition once its vacancies
are filled.

-- Only a Draft is editable -----------------------------------------------------------
Once sent, the letter the candidate is reading must not change underneath them. Edits are
therefore refused after sending; every edit while drafting archives the previous body into
`history` and bumps `version`, so what was offered at each point stays recoverable. An offer
is a document a person may act on, not a mutable row.

-- One active offer per candidate ------------------------------------------------------
Draft, Sent and Accepted all occupy the candidate. Declined and Revoked are spent, so a
fresh offer may follow a withdrawn one -- which is the real-world case (revised terms after
a negotiation).

-- Compensation is redacted the same way salary is -------------------------------------
An offer carries a CTC. Sparsh support staff can see that an offer exists and where it is in
the process, but not the number -- the same boundary Phase 2 drew for `base_salary`, reusing
the same capability rather than inventing a second rule.

-- Requisition auto-closure (Module 16) -------------------------------------------------
Accepting an offer may fill the last vacancy. `reconcile_requisition_closure` counts
candidates who have reached an accepted-or-later stage against the requisition's vacancy and
flips it to Hired. It never overrides Hold, Cancel or Closed -- a human decision outranks an
arithmetic one.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import AUDIT_OFFER_APPROVED, REQUISITION_TRACK_INTERNAL
from app.models.hrms import (
    ACTIVE_OFFER_STATUSES, AUDIT_OFFER_ACCEPTED, AUDIT_OFFER_CREATED, AUDIT_OFFER_DECLINED,
    AUDIT_OFFER_DELETED, AUDIT_OFFER_EDITED, AUDIT_OFFER_REVOKED, AUDIT_OFFER_SENT,
    AUDIT_REQ_AUTO_CLOSED, AUDIT_STAGE_CHANGED, COLL_CANDIDATES, COLL_JOB_DESCRIPTIONS,
    COLL_OFFERS, COLL_REQUISITIONS, DEFAULT_OFFER_BODY, EDITABLE_OFFER_STATUSES,
    ENTITY_CANDIDATE, ENTITY_OFFER, ENTITY_REQUISITION, FILLED_STATUSES, AppStatus, Cap,
    OfferStatus, ReqClosing, can_transition, is_iso_date, render_offer_body,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_access import can
from app.utils.hrms_public_guard import INVALID_LINK, clean_text, new_access_code

logger = logging.getLogger(__name__)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: dict) -> str:
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _out(doc: dict, *, include_ctc: bool = True) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    if not include_ctc:
        # Omitted, not nulled: a viewer must not be able to confuse "you may not see this"
        # with "no salary was offered".
        doc.pop("ctc", None)
        for entry in doc.get("history") or []:
            entry.pop("ctc", None)
    return doc


def _validate_money(value, *, label: str = "CTC") -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail=f"{label} must be greater than zero.")
    if amount > 1_000_000_000:
        raise HTTPException(status_code=422, detail=f"{label} is implausibly large.")
    return amount


def _validate_joining(value: str) -> str:
    if not value:
        raise HTTPException(status_code=422, detail="A joining date is required.")
    if not is_iso_date(value):
        raise HTTPException(
            status_code=422, detail="Joining date must be a valid date in YYYY-MM-DD format.")
    if value < _today():
        raise HTTPException(status_code=422, detail="The joining date cannot be in the past.")
    return value


async def _default_ctc(company_id: str, candidate: dict) -> Optional[float]:
    """Best available starting figure, in order of authority.

    JD -> requisition -> the candidate's own expectation. A pre-filled number the recruiter
    corrects beats an empty box they guess at, and the JD is the most considered source.
    """
    jd_no, request_no = candidate.get("jd_no"), candidate.get("request_no")
    if jd_no:
        jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one(
            {"jd_no": jd_no, "company_id": str(company_id)}, {"ctc": 1})
        value = (jd or {}).get("ctc")
        if value:
            try:
                return float(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                pass
    if request_no:
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": request_no, "company_id": str(company_id)}, {"offering_ctc": 1})
        if (req or {}).get("offering_ctc"):
            try:
                return float(req["offering_ctc"])
            except (TypeError, ValueError):
                pass
    expected = candidate.get("expected_ctc")
    if expected:
        try:
            return float(str(expected).replace(",", "").strip())
        except (TypeError, ValueError):
            pass
    return None


# -------------------------------------------------------------
# Authenticated side
# -------------------------------------------------------------
async def list_offers(actor: dict, company_id: str, *, status: str = None,
                      uk: str = None, limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if uk:
        query["uk"] = uk

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_OFFERS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)

    show_ctc = can(actor, Cap.EMPLOYEE_SALARY_READ)
    out = []
    for r in rows:
        item = _out(r, include_ctc=show_ctc)
        # The access code is a live credential -- returned only while the link still works.
        if item.get("status") != OfferStatus.SENT.value:
            item.pop("access_code", None)
        out.append(item)

    return {
        "offers": out,
        "total": len(out),
        "ctc_visible": show_ctc,
        "stats": {
            "drafts": sum(1 for o in out if o["status"] == OfferStatus.DRAFT.value),
            "awaiting": sum(1 for o in out if o["status"] == OfferStatus.SENT.value),
            "accepted": sum(1 for o in out if o["status"] == OfferStatus.ACCEPTED.value),
            "declined": sum(1 for o in out if o["status"] == OfferStatus.DECLINED.value),
        },
    }


async def offerable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who may be offered: Selected, and without a live offer already."""
    rows = await get_collection(COLL_CANDIDATES).find({
        "company_id": str(company_id),
        "application_status": AppStatus.SELECTED.value,
    }).sort("updated_at", -1).to_list(500)

    taken = {
        o["uk"] for o in await get_collection(COLL_OFFERS).find(
            {"company_id": str(company_id),
             "status": {"$in": [s.value for s in ACTIVE_OFFER_STATUSES]}},
            {"uk": 1}).to_list(500)
    }
    out = []
    for r in rows:
        if r["uk"] in taken:
            continue
        out.append({
            "uk": r["uk"], "candidate_name": r.get("candidate_name"),
            "request_no": r.get("request_no"),
            "suggested_ctc": await _default_ctc(company_id, r),
        })
    return out


# ─────────────────────────────────────────────────────────────
# Internal track — the two offer gates
# ─────────────────────────────────────────────────────────────
def _is_internal(req: dict) -> bool:
    return (req or {}).get("requisition_track") == REQUISITION_TRACK_INTERNAL


def _money(value) -> str:
    """A figure a human can check at a glance. No currency symbol: the module never asks
    which currency a company works in, and inventing one would be worse than omitting it."""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


async def assert_within_band(company_id: str, ctc: float, candidate: dict,
                             req: dict) -> None:
    """Refuse an internal offer outside the approved salary band.

    SOP §6: "Salary negotiation must stay within the internally approved budget from Step 2;
    any deviation requires fresh Management/Finance approval."

    So there are exactly two ways past this, and both leave a record: re-approve the budget
    at the new figure (which rewrites the band), or log an approved Offer Outside Budget
    exception. There is deliberately no override parameter.

    A requisition with no band recorded is not gated. That can only happen for an internal
    requisition approved before this phase existed; the budget gate makes the band mandatory
    for every one raised since, and failing closed on historical rows would strand them.
    """
    if not _is_internal(req):
        return

    band_min = req.get("approved_salary_band_min")
    band_max = req.get("approved_salary_band_max")
    if band_min is None or band_max is None:
        return
    if float(band_min) <= float(ctc) <= float(band_max):
        return

    from app.services.hrms_exception_service import approved_exception_for
    waiver = await approved_exception_for(company_id, "salary_band", req.get("request_no"),
                                          candidate.get("uk"))
    if waiver:
        # An approved exception authorises A FIGURE, not "any figure".
        #
        # Finance approving 13 lakh used to clear an offer of 30, because the approval was
        # a boolean and the gate returned the moment it found one. The ceiling is what
        # Finance actually granted, so an offer past it is refused exactly as if no
        # exception existed -- and the message says whose number it is breaching.
        from app.models.hrms import salary_exception_ceiling
        ceiling = salary_exception_ceiling(waiver)
        if ceiling is None:
            # Raised before the figure was recorded. Nothing to hold it to, so it behaves
            # as it always did rather than retrospectively blocking a granted waiver.
            return
        if float(ctc) <= ceiling:
            return
        raise HTTPException(
            status_code=409,
            detail=(f'{_money(ctc)} is more than the {_money(ceiling)} Finance approved '
                    f'for {candidate.get("candidate_name") or candidate.get("uk")} '
                    f'({waiver.get("exc_no")}). Offer at or below that figure, or raise a '
                    f"new Offer Outside Budget request at the higher one."))

    direction = "below" if float(ctc) < float(band_min) else "above"
    raise HTTPException(
        status_code=409,
        detail=(f'{_money(ctc)} is {direction} the approved salary band for '
                f'{req.get("request_no")} ({_money(band_min)} to {_money(band_max)}). '
                f"Re-approve the budget at the new figure, or log an approved "
                f"Offer Outside Budget exception."))


async def assert_offer_approved(company_id: str, offer: dict, req: dict) -> None:
    """Refuse to SEND an internal offer that Management has not approved.

    Annexure B marks "Offer approval" accountable to Management/Finance, and Table 2 calls it
    mandatory. Verifying the band is not the same act: the band says the figure is affordable,
    the approval says this offer, to this person, should go out.

    Recorded as a field rather than a new OfferStatus. `Draft -> Sent -> Accepted/Declined`
    is shared with the client track and read by the public offer page, the pipeline ranks and
    the analytics funnel; slipping an extra state into that sequence would change what an
    existing status MEANS on a track this phase is not supposed to touch.
    """
    if not _is_internal(req):
        return
    if (offer.get("offer_approval") or {}).get("approved_at"):
        return
    raise HTTPException(
        status_code=409,
        detail=(f'{offer.get("offer_no")} has not been approved yet. An internal offer '
                f"needs Management or Finance sign-off before it goes to the candidate."))


async def approve_offer(actor: dict, company_id: str, offer_no: str,
                        payload: dict) -> dict:
    """Record Management's approval of an offer. Internal track only."""
    current = await _get_offer(company_id, offer_no)
    if current["status"] != OfferStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{offer_no} is "{current["status"]}". Only a draft offer can be '
                    f"approved -- once it has gone out there is nothing left to approve."))

    req = {}
    if current.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": current["request_no"], "company_id": str(company_id)}) or {}
    if not _is_internal(req):
        raise HTTPException(
            status_code=409,
            detail=(f"{current.get('request_no')} is a legacy client-track requisition and "
                    "is not part of hiring any more; its offers cannot be approved."))

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this approval. An unsigned sign-off is not one.")

    # Re-check the band at approval time. The figure may have been edited since the offer was
    # raised, and approving a number nobody validated is exactly the hole this gate closes.
    candidate = {"uk": current.get("uk")}
    await assert_within_band(company_id, current.get("ctc"), candidate, req)

    now = datetime.now(timezone.utc)
    approval = {
        "approved_by": str(actor.get("_id") or ""),
        "approved_by_name": _actor_name(actor),
        "approved_at": now,
        "signature": signature,
        "remarks": clean_text(payload.get("remarks"), limit=2000),
        # The band as it stood when this was approved, so a later band change is visible as a
        # discrepancy rather than silently rewriting history.
        "band_min_at_approval": req.get("approved_salary_band_min"),
        "band_max_at_approval": req.get("approved_salary_band_max"),
    }
    await get_collection(COLL_OFFERS).update_one(
        {"offer_no": offer_no, "company_id": str(company_id)},
        {"$set": {"offer_approval": approval, "updated_at": now}})
    await audit(actor, AUDIT_OFFER_APPROVED, ENTITY_OFFER, offer_no,
                f"approved at {_money(current.get('ctc'))}", company_id)

    fresh = await _get_offer(company_id, offer_no)
    return _out(fresh, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def create_offer(actor: dict, company_id: str, payload: dict) -> dict:
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if candidate.get("application_status") != AppStatus.SELECTED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} is at '
                    f'"{candidate.get("application_status")}". An offer can only be raised '
                    f'for a candidate who has been Selected.'))

    existing = await get_collection(COLL_OFFERS).find_one({
        "company_id": str(company_id), "uk": uk,
        "status": {"$in": [s.value for s in ACTIVE_OFFER_STATUSES]},
    })
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} already has a live offer '
                    f'({existing["offer_no"]}, {existing["status"]}).'))

    ctc = _validate_money(payload.get("ctc"))
    joining = _validate_joining(payload.get("joining_date"))

    # When the caller asked to create AND send, both send-time refusals below happen BEFORE
    # anything is written. Same all-or-nothing rule as the multi-platform publish in Phase 4.
    send_now = bool(payload.get("send_now"))
    send_signature = clean_text(payload.get("signature"), limit=120) if send_now else None

    req = {}
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"], "company_id": str(company_id)}) or {}

    # Order matters here, and it used to be wrong.
    #
    # Create-and-send in one call cannot work on the internal track at all: Management's
    # approval happens BETWEEN the two, so there is no moment at which both are satisfied.
    # That refusal has to come FIRST. When the signature check ran first, an internal-track
    # user who clicked "send now" was told "an authorised signature is required" -- and
    # supplying one changed nothing, because the very next check refused the whole shape of
    # the request. An error message that sends somebody to do something useless is a defect
    # even when the status code is right.
    if send_now and _is_internal(req):
        raise HTTPException(
            status_code=409,
            detail=("An internal offer cannot be created and sent in one step. Save it as a "
                    "draft, have Management or Finance approve it, then send it."))

    # Validated BEFORE anything is written. Otherwise a 422 would still leave an orphaned
    # draft behind -- an operation that reports failure must not half-succeed.
    if send_now and not send_signature:
        raise HTTPException(
            status_code=422,
            detail=("Type the authorised signatory's name in the offer form to send it. "
                    "Leave it blank and use Save draft to create the offer without "
                    "sending."))

    # ── Internal track ── two gates, both checked BEFORE anything is written so a refusal
    # cannot leave a draft offer behind. Both are silent on the client track.
    #
    #   1. The reference check is mandatory (SOP §6) -- Sparsh Magic carries the employment
    #      risk directly rather than passing it to a client.
    #   2. The CTC must sit inside the band Management approved at the budget gate (SOP §6:
    #      "Salary negotiation must stay within the internally approved budget from Step 2").
    from app.services.hrms_reference_service import assert_reference_cleared
    await assert_reference_cleared(company_id, candidate, req)
    await assert_within_band(company_id, ctc, candidate, req)
    # ── Phase INT-2 ── the §5 selection gates, re-asserted at the offer.
    #
    # The candidate is already at `Selected` or this call would not have got here -- which
    # is exactly why this check is worth making a second time. A status is a label somebody
    # can set; the committee record and the MD round are facts. Asking again at the offer
    # is what makes a hand-set `Selected` useless as a way past either control.
    from app.services.hrms_candidate_service import assert_selectable
    await assert_selectable(actor, company_id, candidate)

    # ── Phase 12 ── background verification, on BOTH tracks.
    #
    #     Background Verification -> HR Approval -> Offer Letter -> Onboarding
    #
    # Placed last of the gates and still before any write, so a refusal costs nothing. It
    # asks two things: that every required check has CLEARED, and that HR has signed the
    # file off -- complete checks nobody reviewed are not an approval.
    #
    # Bypassed only by an approved `Background Verification Waived` exception, which is also
    # how a candidate already at Selected when this shipped gets through: attributably,
    # rather than because somebody set a flag.
    from app.services.hrms_background_service import assert_background_cleared
    await assert_background_cleared(company_id, candidate)

    designation = clean_text(payload.get("designation"), limit=140) \
        or req.get("designation_name") or "the role"
    company_name = clean_text(payload.get("company_name"), limit=140) or ""
    body = clean_text(payload.get("content"), limit=20000) or DEFAULT_OFFER_BODY

    year = datetime.now(timezone.utc).year
    offer_no = await next_business_id("offer", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "offer_no": offer_no,
        "access_code": new_access_code(),
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "request_no": candidate.get("request_no"),
        "designation": designation,
        "company_name": company_name,
        "location": clean_text(payload.get("location"), limit=160) or req.get("work_location"),
        "ctc": ctc,
        "joining_date": joining,
        "content": body,
        "status": OfferStatus.DRAFT.value,
        "version": 1,
        "history": [],
        "signature": None,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
    }
    # SOP §13. `COLL_OFFERS` has been a purge target since INT-2, but nothing ever stamped
    # the field the purge selects on -- so the target could never match a single row.
    # Anchored on the offer date: the SOP's "employment duration + 3 years" needs a
    # separation date, and no separation workflow exists to supply one (see the module
    # note in hrms_purge_service). This is the honest floor available today, and it is a
    # floor rather than a deadline -- the purge proposes, a person decides.
    # Imported rather than re-implemented: five services already carry a private copy of
    # this, and one of them shipped a leap-year bug the others did not. A sixth copy is a
    # sixth chance to get February wrong.
    from app.services.hrms_candidate_service import _add_years
    from app.services.hrms_config_service import retention_years_for
    doc["retention_until"] = _add_years(
        now.strftime("%Y-%m-%d"), await retention_years_for(company_id, "offer"))
    await get_collection(COLL_OFFERS).insert_one(dict(doc))

    # Phase 11-R, Item 1: register the offer link at MINT time, not send time, so a draft's
    # credential is already accounted for -- a code that exists but is not in the registry
    # is exactly the blind spot this item was raised to close. Fire-and-forget by contract.
    from app.models.hrms import LinkKind
    from app.services.hrms_link_service import register_link
    await register_link(
        company_id=company_id, kind=LinkKind.OFFER, code=doc["access_code"],
        target_type="offer", target_id=offer_no, actor=actor,
        candidate_name=candidate.get("candidate_name"),
        request_no=candidate.get("request_no"))

    await audit(actor, AUDIT_OFFER_CREATED, ENTITY_OFFER, offer_no,
                f"{designation} for {candidate.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_OFFER_CREATED, ENTITY_CANDIDATE, uk, offer_no, company_id)

    if send_now:
        return await send_offer(actor, company_id, offer_no, {"signature": send_signature})

    return _out(doc, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def _get_offer(company_id: str, offer_no: str) -> dict:
    doc = await get_collection(COLL_OFFERS).find_one(
        {"offer_no": offer_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Offer not found.")
    return doc


async def update_offer(actor: dict, company_id: str, offer_no: str, payload: dict) -> dict:
    """Edit a Draft. Archives the previous body and bumps the version."""
    current = await _get_offer(company_id, offer_no)
    if current["status"] not in {s.value for s in EDITABLE_OFFER_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail=(f'This offer is "{current["status"]}" and can no longer be edited. '
                    f'Revoke it and raise a new one if the terms have changed.'))

    updates = {}
    if payload.get("ctc") is not None:
        updates["ctc"] = _validate_money(payload["ctc"])
    if payload.get("joining_date") is not None:
        updates["joining_date"] = _validate_joining(payload["joining_date"])
    for field, limit in (("designation", 140), ("company_name", 140),
                         ("location", 160), ("signature", 120)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("content") is not None:
        body = clean_text(payload["content"], limit=20000)
        if not body:
            raise HTTPException(status_code=422, detail="The offer letter cannot be empty.")
        updates["content"] = body

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # ── Internal track ── an edited figure is a different offer from the one Management
    # approved, so the approval is withdrawn and the new figure re-checked against the band.
    # Carrying the old signature over onto a new salary would make the approval a formality.
    if "ctc" in updates:
        req = {}
        if current.get("request_no"):
            req = await get_collection(COLL_REQUISITIONS).find_one(
                {"request_no": current["request_no"],
                 "company_id": str(company_id)}) or {}
        if _is_internal(req):
            await assert_within_band(company_id, updates["ctc"],
                                     {"uk": current.get("uk")}, req)
            if current.get("offer_approval"):
                updates["offer_approval"] = None
                updates["approval_withdrawn_reason"] = (
                    f'CTC changed from {_money(current.get("ctc"))} to '
                    f'{_money(updates["ctc"])} after approval.')

    now = datetime.now(timezone.utc)
    # Archive what the letter said BEFORE this edit, so every version is recoverable.
    history = list(current.get("history") or [])
    history.append({
        "version": current.get("version", 1),
        "content": current.get("content"),
        "ctc": current.get("ctc"),
        "joining_date": current.get("joining_date"),
        "edited_at": now,
        "edited_by": _actor_name(actor),
    })
    updates["history"] = history
    updates["version"] = int(current.get("version", 1)) + 1
    updates["updated_at"] = now

    await get_collection(COLL_OFFERS).update_one(
        {"offer_no": offer_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_OFFER_EDITED, ENTITY_OFFER, offer_no,
                f"v{updates['version']}: "
                + ", ".join(sorted(k for k in updates
                                   if k not in ("history", "version", "updated_at"))),
                company_id)
    fresh = await _get_offer(company_id, offer_no)
    return _out(fresh, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def send_offer(actor: dict, company_id: str, offer_no: str, payload: dict) -> dict:
    """Issue the offer to the candidate."""
    current = await _get_offer(company_id, offer_no)
    if current["status"] != OfferStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail=f'This offer is already "{current["status"]}".')

    signature = clean_text(payload.get("signature"), limit=120) or current.get("signature")
    if not signature:
        # The letter commits the company to a salary; it must be attributable.
        raise HTTPException(
            status_code=422,
            detail="Type the authorised signatory's name to send this offer.")

    # ── Internal track ── Management's approval is mandatory before the letter goes out.
    # Checked here rather than only in the route so the direct create-and-send path and any
    # future caller are gated by the same rule.
    req = {}
    if current.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": current["request_no"], "company_id": str(company_id)}) or {}
    await assert_offer_approved(company_id, current, req)

    now = datetime.now(timezone.utc)
    # Conditional on it still being a Draft: two send clicks must not both fire.
    result = await get_collection(COLL_OFFERS).update_one(
        {"offer_no": offer_no, "company_id": str(company_id),
         "status": OfferStatus.DRAFT.value},
        {"$set": {"status": OfferStatus.SENT.value, "signature": signature,
                  "sent_at": now, "sent_by": str(actor.get("_id") or ""),
                  "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="This offer has already been sent.")

    # ── Internal track ── SLA §8 milestone 4: "offer released after final selection".
    # Stamped only for the FIRST offer on a requisition -- a second offer to a second
    # candidate is not a second breach of the same deadline, and overwriting the stamp would
    # quietly make a late requisition look punctual.
    if _is_internal(req) and not (req.get("sla_actuals") or {}).get("offer_released"):
        await get_collection(COLL_REQUISITIONS).update_one(
            {"request_no": current["request_no"], "company_id": str(company_id)},
            {"$set": {"sla_actuals.offer_released": now}})

    candidate_status = None
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": current["uk"], "company_id": str(company_id)})
    if candidate:
        candidate_status = candidate.get("application_status")
        if can_transition(candidate_status, AppStatus.OFFER_GENERATED.value):
            await get_collection(COLL_CANDIDATES).update_one(
                {"uk": current["uk"], "company_id": str(company_id)},
                {"$set": {"application_status": AppStatus.OFFER_GENERATED.value,
                          "updated_at": now}})
            await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, current["uk"],
                        f"{candidate_status} -> {AppStatus.OFFER_GENERATED.value}", company_id)

    await audit(actor, AUDIT_OFFER_SENT, ENTITY_OFFER, offer_no,
                f"sent to {current.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_OFFER_SENT, ENTITY_CANDIDATE, current["uk"], offer_no, company_id)

    # ── Phase INT-2 (Annexure C) ── "a written offer summary before the formal offer".
    #
    # A WARNING, not a block, and the letter has already gone out by the time it is raised.
    # Blocking would be wrong twice: the summary is a courtesy the SOP recommends rather
    # than a control it mandates, and refusing to send an approved offer over a missing
    # courtesy email would make somebody route the offer outside the system entirely.
    warning = None
    if _is_internal(req):
        from app.services.hrms_comm_service import was_sent
        if not await was_sent(company_id, current["uk"], "offer_summary"):
            warning = ("No written offer summary was sent to "
                       f'{current.get("candidate_name")} before this letter. The SOP asks '
                       f"for one so the terms are not a surprise; send it from the offer "
                       f"board if it is not too late to be useful.")

    fresh = await _get_offer(company_id, offer_no)
    out = _out(fresh, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))
    if warning:
        out["warning"] = warning
    return out


async def revoke_offer(actor: dict, company_id: str, offer_no: str, payload: dict) -> dict:
    """Withdraw a sent offer before the candidate responds."""
    current = await _get_offer(company_id, offer_no)
    if current["status"] != OfferStatus.SENT.value:
        raise HTTPException(
            status_code=409,
            detail=f'Only a sent offer can be revoked. This one is "{current["status"]}".')

    now = datetime.now(timezone.utc)
    reason = clean_text(payload.get("reason"), limit=2000)
    await get_collection(COLL_OFFERS).update_one(
        {"offer_no": offer_no, "company_id": str(company_id)},
        {"$set": {"status": OfferStatus.REVOKED.value, "revoked_at": now,
                  "revoke_reason": reason, "updated_at": now}})
    await audit(actor, AUDIT_OFFER_REVOKED, ENTITY_OFFER, offer_no, reason, company_id)
    await audit(actor, AUDIT_OFFER_REVOKED, ENTITY_CANDIDATE, current["uk"],
                f"{offer_no} revoked", company_id)

    # Walk the candidate back to Selected. Withdrawing the offer un-does the fact that one
    # was generated: leaving them at "Offer Generated" would both misreport reality (no
    # offer is outstanding) and strand them, since a new offer requires Selected.
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": current["uk"], "company_id": str(company_id)})
    current_status = (candidate or {}).get("application_status")
    if current_status and can_transition(current_status, AppStatus.SELECTED.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": current["uk"], "company_id": str(company_id)},
            {"$set": {"application_status": AppStatus.SELECTED.value, "updated_at": now}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, current["uk"],
                    f"{current_status} -> {AppStatus.SELECTED.value} (offer revoked)",
                    company_id)

    return {"revoked": True, "offer_no": offer_no}


async def delete_offer(actor: dict, company_id: str, offer_no: str) -> dict:
    """Delete a Draft. Anything already sent is part of the record and is never removed."""
    current = await _get_offer(company_id, offer_no)
    if current["status"] != OfferStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail=("Only a draft can be deleted. An offer that has been sent is part of "
                    "the hiring record — revoke it instead."))
    await get_collection(COLL_OFFERS).delete_one(
        {"offer_no": offer_no, "company_id": str(company_id)})
    await audit(actor, AUDIT_OFFER_DELETED, ENTITY_OFFER, offer_no,
                current.get("candidate_name"), company_id)
    return {"deleted": True, "offer_no": offer_no}


# -------------------------------------------------------------
# Requisition auto-closure (Module 16)
# -------------------------------------------------------------
async def reconcile_requisition_closure(actor: Optional[dict], company_id: str,
                                        request_no: str) -> Optional[str]:
    """Close a requisition as Hired once its vacancies are filled.

    Counts candidates at an accepted-or-later stage against `vacancy`. Returns the new
    closing status, or None if nothing changed.

    Deliberately never overrides Hold, Cancel or Closed: those are human decisions and
    outrank an arithmetic one. Only an Open requisition is auto-closed.
    """
    if not request_no:
        return None
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req or req.get("closing_status") != ReqClosing.OPEN.value:
        return None

    # ── Internal track ── an accepted offer does NOT close the requisition.
    #
    # SOP §7 closes an internal requisition on PROBATION CONFIRMATION, because with no
    # client handover the hire is not final until the person is confirmed. Closing here
    # would beat that by the whole probation period and leave
    # hrms_probation_service._close_requisition_on_confirmation with nothing to close --
    # which is exactly what it did before this guard existed.
    #
    # The vacancy is still visibly spoken for: the candidate sits at Offer Accepted or
    # later, and the tracker reports the funnel per requisition. What stays open is the
    # REQUISITION, which is the honest state -- a joiner who leaves in month two puts this
    # role back in the market, and a requisition already closed as Hired cannot say so.
    if req.get("requisition_track") == REQUISITION_TRACK_INTERNAL:
        return None

    filled = await get_collection(COLL_CANDIDATES).count_documents({
        "company_id": str(company_id), "request_no": request_no,
        "application_status": {"$in": [s.value for s in FILLED_STATUSES]},
    })
    vacancy = int(req.get("vacancy") or 1)
    if filled < vacancy:
        return None

    closed_at = datetime.now(timezone.utc)
    # SOP §13: retention runs from closure, so it is stamped by whoever closes.
    from app.services.hrms_candidate_service import _add_years
    from app.services.hrms_config_service import retention_years_for
    await get_collection(COLL_REQUISITIONS).update_one(
        {"request_no": request_no, "company_id": str(company_id),
         "closing_status": ReqClosing.OPEN.value},
        {"$set": {"closing_status": ReqClosing.HIRED.value,
                  "closed_at": closed_at,
                  "retention_until": _add_years(
                      closed_at.strftime("%Y-%m-%d"),
                      await retention_years_for(company_id, "requisition"))}})
    await audit(actor, AUDIT_REQ_AUTO_CLOSED, ENTITY_REQUISITION, request_no,
                f"{filled}/{vacancy} vacancies filled", company_id)
    await notify_hrms_role(
        company_id, ["HR", "MD"], f"Requisition {request_no} filled",
        f"All {vacancy} vacancy(s) have been filled. The requisition is now closed as Hired.",
        link="/hrms/requisitions")
    return ReqClosing.HIRED.value


# -------------------------------------------------------------
# Public side (NO authentication)
# -------------------------------------------------------------
async def get_public_offer(code: str) -> dict:
    """The offer letter behind a candidate's link."""
    doc = await get_collection(COLL_OFFERS).find_one({"access_code": code})
    # A Draft is invisible: it has not been issued, so as far as the world is concerned it
    # does not exist. Same opaque 404 as an unknown code.
    if not doc or doc["status"] == OfferStatus.DRAFT.value:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    if doc["status"] == OfferStatus.REVOKED.value:
        raise HTTPException(
            status_code=410,
            detail="This offer has been withdrawn. Please contact the hiring team.")

    body = render_offer_body(
        doc.get("content") or "",
        designation=doc.get("designation"), company=doc.get("company_name"),
        ctc=f"{doc.get('ctc'):,.0f}" if doc.get("ctc") is not None else "",
        joining_date=doc.get("joining_date"))

    return {
        "ok": True,
        "already_responded": doc["status"] in (OfferStatus.ACCEPTED.value,
                                               OfferStatus.DECLINED.value),
        "status": doc["status"],
        "offer_no": doc["offer_no"],
        "candidate_name": doc.get("candidate_name"),
        "designation": doc.get("designation"),
        "company_name": doc.get("company_name"),
        "location": doc.get("location"),
        "ctc": doc.get("ctc"),
        "joining_date": doc.get("joining_date"),
        "content": body,
        "signature": doc.get("signature"),
        "sent_at": doc.get("sent_at"),
        "responded_at": doc.get("responded_at"),
    }


async def respond_to_offer(code: str, payload: dict) -> dict:
    """Record the candidate's accept or decline."""
    doc = await get_collection(COLL_OFFERS).find_one({"access_code": code})
    if not doc or doc["status"] == OfferStatus.DRAFT.value:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc["status"] in (OfferStatus.ACCEPTED.value, OfferStatus.DECLINED.value):
        raise HTTPException(
            status_code=409, detail="You have already responded to this offer.")
    if doc["status"] != OfferStatus.SENT.value:
        raise HTTPException(
            status_code=410,
            detail="This offer has been withdrawn. Please contact the hiring team.")

    action = (payload.get("action") or "").strip().lower()
    if action not in ("accept", "decline"):
        raise HTTPException(status_code=422, detail="Choose to accept or decline.")

    signature = clean_text(payload.get("signature"), limit=120)
    if action == "accept" and not signature:
        # Accepting forms an agreement, so it is signed. Declining is not -- demanding a
        # signature from someone walking away is friction with no purpose.
        raise HTTPException(
            status_code=422, detail="Type your full name to accept this offer.")

    now = datetime.now(timezone.utc)
    new_status = (OfferStatus.ACCEPTED if action == "accept" else OfferStatus.DECLINED)
    result = await get_collection(COLL_OFFERS).update_one(
        {"access_code": code, "status": OfferStatus.SENT.value},
        {"$set": {"status": new_status.value, "responded_at": now,
                  "response_note": clean_text(payload.get("note"), limit=2000),
                  "candidate_signature": signature, "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="You have already responded to this offer.")

    company_id = doc.get("company_id")
    target = (AppStatus.OFFER_ACCEPTED if action == "accept" else AppStatus.OFFER_DECLINED)
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": doc["uk"], "company_id": company_id})
    current_status = (candidate or {}).get("application_status")
    if current_status and can_transition(current_status, target.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": doc["uk"], "company_id": company_id},
            {"$set": {"application_status": target.value, "updated_at": now}})
        await audit(None, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, doc["uk"],
                    f"{current_status} -> {target.value}", company_id)

    action_label = AUDIT_OFFER_ACCEPTED if action == "accept" else AUDIT_OFFER_DECLINED
    await audit(None, action_label, ENTITY_OFFER, doc["offer_no"],
                doc.get("candidate_name"), company_id)
    await audit(None, action_label, ENTITY_CANDIDATE, doc["uk"], doc["offer_no"], company_id)

    verb = "accepted" if action == "accept" else "declined"
    await notify_hrms_role(
        company_id, ["HR"], f"Offer {verb}: {doc.get('candidate_name')}",
        f"{doc.get('candidate_name')} has {verb} {doc['offer_no']}."
        + (f" Note: {payload.get('note')}" if payload.get("note") else ""),
        kind="success" if action == "accept" else "warning",
        link="/hrms/offers", email=True)
    if doc.get("created_by"):
        await notify_user(
            doc["created_by"], f"Offer {verb}: {doc.get('candidate_name')}",
            f"{doc['offer_no']} was {verb}.", link="/hrms/offers")

    if action == "accept":
        # The last vacancy may just have been filled.
        await reconcile_requisition_closure(None, company_id, doc.get("request_no"))

        # ── BA Functional Design §7.5 ── "Pre-boarding & Joining Document Workflow",
        # Trigger: "Offer accepted." -- the onboarding case (and the candidate's own
        # secure document-upload portal) is meant to open THE MOMENT an offer is
        # accepted, not once HR gets around to picking them from a list. Best-effort:
        # the offer has already been recorded above, and a candidate must never see
        # their acceptance fail because this fire-and-forget step hit a problem.
        try:
            from app.services.hrms_onboarding_service import start_onboarding
            await start_onboarding(None, company_id, {
                "uk": doc["uk"], "joining_date": doc.get("joining_date")})
        except HTTPException as e:
            # 409 is the expected, legal case: HR started the onboarding by hand first.
            # Anything else means the pre-joiner case did NOT open, and swallowing that
            # left a candidate who had accepted with no case and nobody aware of it.
            if e.status_code != 409:
                await notify_hrms_role(
                    company_id, ["HR"],
                    f"Pre-joiner case NOT created: {doc.get('candidate_name')}",
                    (f"{doc.get('candidate_name')} accepted {doc['offer_no']}, but their "
                     f"onboarding could not be opened automatically ({e.detail}). "
                     f"Start it by hand from the onboarding board."),
                    kind="error", link="/hrms/onboarding", email=True)
        except Exception as e:                      # pragma: no cover - defensive
            # The offer is already Accepted at this point; a failure here must never make
            # the candidate's acceptance look like it did not work.
            logger.warning("Auto onboarding failed for %s: %s", doc.get("uk"), e)
            await notify_hrms_role(
                company_id, ["HR"],
                f"Pre-joiner case NOT created: {doc.get('candidate_name')}",
                (f"{doc.get('candidate_name')} accepted {doc['offer_no']}, but their onboarding "
                 f"could not be opened automatically. Start it by hand from the "
                 f"onboarding board."),
                kind="error", link="/hrms/onboarding", email=True)

    return {
        "ok": True,
        "status": new_status.value,
        "message": ("Thank you — your acceptance has been recorded. The team will be in "
                    "touch about your onboarding."
                    if action == "accept"
                    else "Thank you for letting us know. Your response has been recorded."),
    }
