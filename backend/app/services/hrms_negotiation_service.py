"""HRMS ▸ salary negotiation (internal recruitment track, SOP step 9, spec §16).

"Salary negotiation within internally approved budget." The RULE has been enforced since
the internal track shipped: `hrms_offer_service.assert_within_band` refuses an offer outside
the band stamped on the requisition at its budget gate, and the only way past it is a fresh
approval -- a re-approved budget or an approved *Offer Outside Budget* exception.

What was missing was the RECORD. Negotiation is rounds: the candidate asks, HR proposes, the
band says yes or no, somebody goes back. None of that was written down anywhere, so the offer
arrived with a number and no history of how it got there, and spec §16's "display clearly
whether the negotiated salary is within / above / below the approved budget" had nothing to
display against.

-- THE GATE DOES NOT MOVE ---------------------------------------------------------------------
Recording a round decides nothing. A round above the band is recorded as `above` and Management
is told -- it is not refused, because the conversation is allowed to happen; it is the OFFER
that may not. `assert_within_band` stays exactly where it is, and the verdict here is computed
by the same comparison (`negotiation_verdict` in the model), so the two can never disagree
about one number.

-- Internal track only, and only after the budget gate ---------------------------------------
A client-track candidate has no approved band to negotiate within, and an internal requisition
that has not cleared the budget gate has none either: SOP step 9 is "within internally approved
budget", and there is no such thing before step 2. Both are 409, not silent -- a round recorded
against no band would be a number with no meaning.

-- The band is stamped on every round -------------------------------------------------------
`band_min`/`band_max` are copied onto the round as they stood when it was recorded. A later
budget re-approval changes the requisition's band; it does not rewrite history, and a reader
of round 2 should see the band round 2 was judged against.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_NEGOTIATION_RECORDED, COLL_CANDIDATES, COLL_NEGOTIATIONS, COLL_REQUISITIONS,
    ENTITY_NEGOTIATION, MAX_NEGOTIATION_ROUNDS, NEGOTIATION_ABOVE, NEGOTIATION_BELOW,
    NEGOTIATION_WITHIN, REQUISITION_TRACK_INTERNAL, negotiation_verdict,
)
from app.services.hrms_audit_service import audit
# The SAME row scoping the candidate pipeline applies: a hiring manager sees rounds on the
# requisitions they raised and nothing else, failing closed. Imported rather than copied,
# so the two cannot drift.
from app.services.hrms_candidate_service import _require_visible, _scope_filter
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text

# A figure no real salary reaches. The offer service draws the same line; a proposal past
# it is a typo, not a negotiation.
MAX_PLAUSIBLE_CTC = 1_000_000_000


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _money(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _validate_money(value, *, label: str) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    try:
        figure = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    import math
    if not math.isfinite(figure):
        # NaN passes every `<` and `>` test and is not JSON; one would read as "within"
        # and then break every read of the collection.
        raise HTTPException(status_code=422, detail=f"{label} must be a finite number.")
    if figure <= 0:
        raise HTTPException(status_code=422, detail=f"{label} must be greater than zero.")
    if figure > MAX_PLAUSIBLE_CTC:
        raise HTTPException(status_code=422, detail=f"{label} is implausibly large.")
    return round(figure, 2)


async def _requisition_with_band(company_id: str, candidate: dict) -> dict:
    """The candidate's requisition, refused unless it is internal with an approved band."""
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": candidate.get("request_no"), "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That candidate's requisition does not exist.")
    track = req.get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        raise HTTPException(
            status_code=409,
            detail=f'{req.get("request_no")} is a legacy client-track requisition and is not part of hiring any more.')
    if req.get("approved_salary_band_min") is None or req.get("approved_salary_band_max") is None:
        raise HTTPException(
            status_code=409,
            detail=(f'{req.get("request_no")} has no approved salary band yet. SOP step 9 '
                    f"is negotiation WITHIN the approved budget, and there is no such thing "
                    f"before Management/Finance approve one (step 2)."))
    return req


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_rounds(actor: dict, company_id: str, *, uk: str = None,
                      request_no: str = None, limit: int = 100) -> dict:
    from app.models.hrms import HrmsRole
    from app.utils.hrms_access import hrms_role

    query = {"company_id": str(company_id)}
    # Row scoping BEFORE the caller's filters, so a filter can only narrow what the actor
    # may already see -- the same composition rule every other scoped list follows.
    query.update(await _scope_filter(actor, company_id))
    if uk:
        query["uk"] = uk
    if request_no:
        query["request_no"] = request_no
    limit = max(1, min(int(limit or 100), 500))
    rows = await get_collection(COLL_NEGOTIATIONS).find(query).sort(
        "recorded_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    # Ordered here as well as at the database, so the answer does not depend on which
    # order a cursor happened to return.
    out.sort(key=lambda r: str(r.get("recorded_at") or ""), reverse=True)
    return {"rounds": out, "total": len(out),
            "above_band": sum(1 for r in out if r.get("verdict") == NEGOTIATION_ABOVE),
            "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER}


async def get_round(company_id: str, neg_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_NEGOTIATIONS).find_one(
        {"neg_no": neg_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def negotiation_for(actor: dict, company_id: str, uk: str) -> dict:
    """The comparison surface spec §16 asks for: the band, the latest round, and whether an
    offer at that figure would pass the gate today.

    `offer_would_pass` is computed from the SAME facts the offer gate reads -- the band on the
    requisition now (not the band stamped on the round) and the presence of an approved
    Offer Outside Budget exception -- so what this screen says and what the offer does cannot
    diverge. It is a preview, not a promise: the gate is still asked at the offer.
    """
    # 404 for a candidate outside the actor's scope, not 403: a 403 would confirm the
    # record exists. The helper is the candidate pipeline's own.
    candidate = await _require_visible(actor, company_id, uk)

    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": candidate.get("request_no"), "company_id": str(company_id)}) or {}
    track = req.get("requisition_track")
    band_min = req.get("approved_salary_band_min")
    band_max = req.get("approved_salary_band_max")

    rows = await get_collection(COLL_NEGOTIATIONS).find(
        {"company_id": str(company_id), "uk": uk}).sort("round", 1).to_list(
        MAX_NEGOTIATION_ROUNDS + 1)
    rounds = [_out(r) for r in rows]
    # Sorted here too: "latest" is positional, and must not depend on cursor order.
    rounds.sort(key=lambda r: int(r.get("round") or 0))
    latest = rounds[-1] if rounds else None

    # Judged against the band AS IT STANDS, which is what the offer gate will read. A round
    # recorded before a budget re-approval may carry a different stamped band, and both
    # facts are shown: what it was judged against then, and what it would face now.
    current_verdict = (negotiation_verdict(latest.get("proposed_ctc"), band_min, band_max)
                       if latest else None)

    waiver = None
    if track == REQUISITION_TRACK_INTERNAL and req.get("request_no"):
        from app.services.hrms_exception_service import approved_exception_for
        waiver = await approved_exception_for(
            company_id, "salary_band", req.get("request_no"), uk)

    if track != REQUISITION_TRACK_INTERNAL:
        would_pass, reason = False, "Legacy client-track requisition: not part of hiring."
    elif band_min is None or band_max is None:
        # Mirrors the gate exactly: `assert_within_band` does NOT refuse an internal
        # requisition with no band recorded (it can only be one approved before the band
        # gate existed, and failing closed would strand it). Saying NO here while the
        # offer would go through is the divergence this surface exists to prevent. No
        # round can be recorded against it either -- `record_round` refuses -- so the
        # honest answer is "the gate does not apply, and that is a gap to fix".
        would_pass, reason = True, (
            "This requisition carries no approved salary band, so the band gate does not "
            "apply to it -- it predates the budget gate or its band was never recorded. "
            "Re-record the budget approval with a band before negotiating against one.")
    elif latest is None:
        would_pass, reason = None, "No round recorded yet."
    elif current_verdict == NEGOTIATION_WITHIN:
        would_pass, reason = True, "The latest proposal sits inside the approved band."
    elif waiver:
        would_pass, reason = True, (f'{waiver.get("exc_no")} (Offer Outside Budget) is '
                                    f"approved for this candidate.")
    else:
        would_pass, reason = False, (
            f"The latest proposal is {current_verdict} the approved band. Re-approve the "
            f"budget at the new figure, or log an approved Offer Outside Budget exception.")

    return {
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "request_no": req.get("request_no"),
        "designation_name": req.get("designation_name"),
        "requisition_track": track,
        "band": {"min": band_min, "max": band_max,
                 "approved_at": req.get("budget_approved_at"),
                 "approved_by_name": req.get("budget_approved_by_name")},
        "candidate_expectation": next(
            (r.get("candidate_expectation") for r in reversed(rounds)
             if r.get("candidate_expectation") is not None), None),
        "latest_round": latest,
        "latest_verdict_now": current_verdict,
        "rounds": rounds,
        "round_count": len(rounds),
        "waiver": waiver,
        "offer_would_pass": would_pass,
        "offer_gate_note": reason,
    }


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
async def record_round(actor: dict, company_id: str, payload: dict) -> dict:
    """Record one round. Decides nothing; the offer gate is still the control."""
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    req = await _requisition_with_band(company_id, candidate)
    proposed = _validate_money(payload.get("proposed_ctc"), label="The proposed CTC")
    if proposed is None:
        raise HTTPException(status_code=422, detail="A round needs a proposed CTC.")
    expectation = _validate_money(payload.get("candidate_expectation"),
                                  label="The candidate's expectation")
    notes = clean_text(payload.get("notes"), limit=2000)

    coll = get_collection(COLL_NEGOTIATIONS)
    prior = await coll.find({"company_id": str(company_id), "uk": uk}).to_list(
        MAX_NEGOTIATION_ROUNDS + 1)
    if len(prior) >= MAX_NEGOTIATION_ROUNDS:
        raise HTTPException(
            status_code=409,
            detail=(f"{uk} already has {MAX_NEGOTIATION_ROUNDS} rounds on record. A "
                    f"negotiation that long is a decision nobody is taking -- escalate it."))
    round_no = max([int(r.get("round") or 0) for r in prior], default=0) + 1

    band_min, band_max = req["approved_salary_band_min"], req["approved_salary_band_max"]
    verdict = negotiation_verdict(proposed, band_min, band_max)

    year = datetime.now(timezone.utc).year
    neg_no = await next_business_id("negotiation", str(company_id), year)
    now = datetime.now(timezone.utc)

    from app.services.hrms_config_service import retention_years_for
    years = await retention_years_for(company_id, "negotiation")
    # 29 February plus N years is not a date; the 28th is the honest floor. Every other
    # day keeps its own number -- the sibling services clamp only that one day.
    day = 28 if (now.month == 2 and now.day == 29) else now.day
    doc = {
        "neg_no": neg_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        # Carried so the single analytics scope filter reaches this collection too.
        "request_no": req.get("request_no"),
        "round": round_no,
        "candidate_expectation": expectation,
        "proposed_ctc": proposed,
        # The band AS IT STOOD. A later re-approval must not rewrite what this round was
        # judged against.
        "band_min": band_min,
        "band_max": band_max,
        "verdict": verdict,
        "notes": notes,
        "recorded_by": str((actor or {}).get("_id") or ""),
        "recorded_by_name": (actor or {}).get("full_name") or (actor or {}).get("email"),
        "recorded_at": now,
        "retention_until": f"{now.year + years:04d}-{now.month:02d}-{day:02d}",
        "created_at": now,
    }
    # The unique (company, uk, round) index is what makes two simultaneous "round 3"s one
    # winner and one retry. The loser re-reads, renumbers and inserts once more; a second
    # collision is a 409 rather than a loop.
    from pymongo.errors import DuplicateKeyError
    try:
        await coll.insert_one(dict(doc))
    except DuplicateKeyError:
        prior = await coll.find({"company_id": str(company_id), "uk": uk}).to_list(
            MAX_NEGOTIATION_ROUNDS + 1)
        if len(prior) >= MAX_NEGOTIATION_ROUNDS:
            raise HTTPException(
                status_code=409,
                detail=f"{uk} already has {MAX_NEGOTIATION_ROUNDS} rounds on record.")
        round_no = max([int(r.get("round") or 0) for r in prior], default=0) + 1
        doc["round"] = round_no
        try:
            await coll.insert_one(dict(doc))
        except DuplicateKeyError:
            raise HTTPException(
                status_code=409,
                detail="Another round was recorded for this candidate a moment ago. "
                       "Refresh and record again.")
    await audit(actor, AUDIT_NEGOTIATION_RECORDED, ENTITY_NEGOTIATION, neg_no,
                f"round {round_no} for {uk}: {_money(proposed)} ({verdict} band "
                f"{_money(band_min)}-{_money(band_max)})", company_id)

    # ── spec §38, Management: "Salary deviation" ── a proposal outside the band is the
    # moment Management/Finance learn a fresh approval will be asked for, rather than the
    # moment an offer is refused. Told once per such round; a within-band round is HR's
    # business and says nothing.
    if verdict in (NEGOTIATION_ABOVE, NEGOTIATION_BELOW):
        from app.services.hrms_notify_service import notify_hrms_role
        await notify_hrms_role(
            company_id, ["MD", "FINANCE"],
            f"Salary proposal {verdict} the approved band: {candidate.get('candidate_name')}",
            f'Round {round_no} for {req.get("designation_name") or req.get("request_no")} '
            f"proposes {_money(proposed)} against an approved band of "
            f"{_money(band_min)} to {_money(band_max)}. An offer at this figure will need "
            f"the budget re-approved or an approved Offer Outside Budget exception.",
            kind="warning", link="/hrms/negotiations", email=True)

    return _out(doc)
