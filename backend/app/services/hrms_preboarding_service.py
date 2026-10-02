"""HRMS > pre-boarding engagement (internal recruitment track, SOP §6).

The window between "they accepted" and "they walked in" is where an offer is lost. The SOP
names the practice -- stay in touch, watch for a counter-offer, make sure the joining
acknowledgement is real -- and until this phase nothing recorded that it happened.

-- NOTHING IS GATED ON THIS, deliberately --------------------------------------------------
This is engagement tracking, not a control, and the distinction is worth stating because
every other internal-track module in this codebase is a gate. A candidate with no touchpoint
onboards exactly as they always did; no status is blocked, no offer is refused, no
requisition stalls.

Making it a gate would be the wrong trade twice over. It would punish the candidate for HR
being busy, and it would turn a genuinely useful signal ("this person is wavering") into a
box somebody ticks to unblock themselves. What it does instead is put people on a due list
and raise a flag when somebody says out loud that they might not come.

-- Two things it DOES do -------------------------------------------------------------------
  1. `due_touchpoints` lists candidates in the pre-boarding window with no contact in the
     last PREBOARDING_CONTACT_DAYS days. That is a worklist, not an alarm.
  2. A touchpoint recorded as `At Risk` notifies the recruiter AND the HOD immediately. Not
     the whole HR role: this is one person's news, and broadcasting it would both be a
     privacy problem and train people to ignore the channel.

-- Internal track only ----------------------------------------------------------------------
A client-track joiner is the client's to keep warm. Recording our own pre-boarding calls
against their new hire would be tracking somebody else's employee.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PREBOARDING_LOGGED, COLL_CANDIDATES, COLL_PREBOARDING, COLL_REQUISITIONS,
    ENTITY_PREBOARDING, PREBOARDING_CONTACT_DAYS, PREBOARDING_STATUSES, RETENTION_YEARS,
    AppStatus, PreboardingMode, PreboardingSentiment, REQUISITION_TRACK_INTERNAL, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_config_service import retention_years_for
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_user, notify_users
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _add_years(iso_date: str, years: int) -> str:
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_touchpoints(actor: dict, company_id: str, *, uk: str = None,
                           request_no: str = None, sentiment: str = None,
                           limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if uk:
        query["candidate_uk"] = uk
    if request_no:
        query["request_no"] = request_no
    if sentiment:
        query["sentiment"] = sentiment
    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_PREBOARDING).find(query).sort(
        "contacted_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "touchpoints": out,
        "total": len(out),
        # The count that changes what somebody does today.
        "at_risk": sum(1 for r in out
                       if r.get("sentiment") == PreboardingSentiment.AT_RISK.value),
    }


async def due_touchpoints(actor: dict, company_id: str, *,
                          within_days: int = PREBOARDING_CONTACT_DAYS) -> dict:
    """Accepted candidates who have not been contacted lately.

    "Lately" is measured from the LATEST touchpoint, not from the offer: somebody spoken to
    on Friday is not overdue on Monday because their offer was three weeks ago.

    A candidate with NO touchpoint at all is due immediately, and is reported separately
    from one who has simply gone quiet. Those are different conversations -- one is "we have
    not started", the other is "we have let it slip" -- and one merged list leaves the reader
    to work out which is which, the same split `GET /probation/due` already draws.
    """
    within_days = max(0, int(within_days or 0))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).strftime("%Y-%m-%d")

    # Internal requisitions only. Resolved first so the candidate scan is already narrowed
    # rather than filtered afterwards.
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id),
         "requisition_track": REQUISITION_TRACK_INTERNAL},
        {"request_no": 1, "designation_name": 1}).to_list(2000)
    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    designation = {r["request_no"]: r.get("designation_name") for r in reqs}
    if not request_nos:
        return {"never_contacted": [], "gone_quiet": [], "total": 0,
                "within_days": within_days, "as_of": _today()}

    candidates = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id),
         # Fails CLOSED in the same way every other scoped read here does: an empty list is
         # an `$in: []`, matching nothing rather than everything.
         "request_no": {"$in": request_nos},
         "application_status": {"$in": [s.value for s in PREBOARDING_STATUSES]}},
        {"uk": 1, "candidate_name": 1, "request_no": 1, "application_status": 1,
         "assigned_recruiter_id": 1, "assigned_recruiter_name": 1}).to_list(2000)

    never, quiet = [], []
    for c in candidates:
        latest = await get_collection(COLL_PREBOARDING).find(
            {"company_id": str(company_id), "candidate_uk": c["uk"]}).sort(
            "contacted_at", -1).limit(1).to_list(1)
        row = {
            "uk": c["uk"],
            "candidate_name": c.get("candidate_name"),
            "request_no": c.get("request_no"),
            "designation_name": designation.get(c.get("request_no")),
            "application_status": c.get("application_status"),
            "assigned_recruiter_id": c.get("assigned_recruiter_id"),
            "assigned_recruiter_name": c.get("assigned_recruiter_name"),
            "last_contacted_at": (latest[0].get("contacted_at") if latest else None),
            "last_sentiment": (latest[0].get("sentiment") if latest else None),
        }
        if not latest:
            never.append(row)
        elif str(latest[0].get("contacted_at") or "") < cutoff:
            quiet.append(row)

    never.sort(key=lambda r: r.get("candidate_name") or "")
    quiet.sort(key=lambda r: str(r.get("last_contacted_at") or ""))
    return {"never_contacted": never, "gone_quiet": quiet,
            "total": len(never) + len(quiet),
            "within_days": within_days, "as_of": _today()}


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def record_touchpoint(actor: dict, company_id: str, payload: dict) -> dict:
    """Log one contact with a candidate who has accepted and not yet joined."""
    uk = clean_text(payload.get("candidate_uk"), limit=40)
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    req = {}
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"], "company_id": str(company_id)}) or {}
    track = req.get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} is on a requisition that '
                    f"is a legacy client-track requisition and is not part of hiring any more."))

    status = candidate.get("application_status")
    if status not in {s.value for s in PREBOARDING_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} is at "{status}". Pre-boarding runs '
                    f"between accepting the offer and joining; there is nothing to keep warm "
                    f"before or after that."))

    raw_mode = getattr(payload.get("mode"), "value", payload.get("mode"))
    try:
        mode = PreboardingMode(raw_mode or PreboardingMode.CALL.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Mode must be one of: {', '.join(m.value for m in PreboardingMode)}.")

    raw_sentiment = getattr(payload.get("sentiment"), "value", payload.get("sentiment"))
    try:
        sentiment = PreboardingSentiment(raw_sentiment or PreboardingSentiment.NEUTRAL.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Sentiment must be one of: "
                    f"{', '.join(s.value for s in PreboardingSentiment)}."))

    contacted_at = payload.get("contacted_at") or _today()
    if not is_iso_date(contacted_at):
        raise HTTPException(
            status_code=422, detail="The contact date must be a valid YYYY-MM-DD date.")
    if contacted_at > _today():
        # The same rule interviews follow: a record of a conversation that has not happened
        # is not a record.
        raise HTTPException(
            status_code=422, detail="A touchpoint cannot be dated in the future.")

    notes = clean_text(payload.get("notes"), limit=4000)
    at_risk = sentiment is PreboardingSentiment.AT_RISK
    if at_risk and not notes:
        # "At Risk" is the one value that makes somebody act, so it has to say what happened.
        # A flag with no story behind it is an alarm nobody can respond to.
        raise HTTPException(
            status_code=422,
            detail=("Say what they told you. An 'At Risk' flag with no note tells the "
                    "recruiter to worry and nothing else."))

    now = datetime.now(timezone.utc)
    pbt_no = await next_business_id("preboarding", str(company_id), now.year)

    doc = {
        "pbt_no": pbt_no,
        "company_id": str(company_id),
        "candidate_uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "request_no": candidate.get("request_no"),
        "offer_no": await _offer_no_for(company_id, uk),
        "mode": mode.value,
        "contacted_at": contacted_at,
        "contacted_by": str(actor.get("_id") or ""),
        "contacted_by_name": _actor_name(actor),
        "sentiment": sentiment.value,
        "counter_offer_disclosed": bool(payload.get("counter_offer_disclosed")),
        "notes": notes,
        # SOP §13. A touchpoint is part of the selected candidate's file, so it keeps the
        # selected-candidate floor rather than the shorter unselected one.
        "retention_until": _add_years(
            contacted_at,
            await retention_years_for(company_id, "candidate_selected")),
        "created_at": now,
    }
    await get_collection(COLL_PREBOARDING).insert_one(dict(doc))
    await audit(actor, AUDIT_PREBOARDING_LOGGED, ENTITY_PREBOARDING, pbt_no,
                f'{mode.value} with {candidate.get("candidate_name")}: {sentiment.value}'
                + (" (counter-offer disclosed)"
                   if doc["counter_offer_disclosed"] else ""),
                company_id)

    if at_risk:
        await _raise_at_risk(company_id, candidate, req, doc)
    return _out(doc)


async def _offer_no_for(company_id: str, uk: str) -> Optional[str]:
    """The offer this pre-boarding is against, if there is one.

    Carried on the touchpoint so the record reads without a join, exactly as
    `candidate_name` is. Best-effort: a candidate who reached Offer Accepted has an offer,
    but the touchpoint is worth keeping even if the lookup finds nothing.
    """
    from app.models.hrms import COLL_OFFERS, OfferStatus
    offer = await get_collection(COLL_OFFERS).find_one(
        {"company_id": str(company_id), "uk": uk,
         "status": OfferStatus.ACCEPTED.value}, {"offer_no": 1})
    return (offer or {}).get("offer_no")


async def _raise_at_risk(company_id: str, candidate: dict, req: dict,
                         touchpoint: dict) -> None:
    """Tell the recruiter and the HOD that somebody may not turn up.

    Deliberately NOT a role-wide broadcast. Two named people can act on it; the whole HR
    function cannot, and a channel that fires at everybody is one everybody mutes. It is
    also somebody's private wobble about a job, which is not company-wide news.
    """
    title = f'At risk: {candidate.get("candidate_name")} may not join'
    message = (f'{touchpoint["mode"]} on {touchpoint["contacted_at"]}: '
               f'{touchpoint.get("notes") or "no note recorded"}'
               + ("\nA counter-offer was disclosed."
                  if touchpoint.get("counter_offer_disclosed") else ""))

    recipients = [candidate.get("assigned_recruiter_id"),
                  # The HOD is the requisition's raiser: they own the vacancy, and they are
                  # the person who has to decide whether to reopen it.
                  req.get("created_by"),
                  req.get("assignee_id")]
    await notify_users([r for r in recipients if r], title, message,
                       kind="warning", link="/hrms/preboarding", email=True)
