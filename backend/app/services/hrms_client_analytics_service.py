"""HRMS > Client Hiring — recruitment analytics for the PRO-fit track.

Separate from the internal recruitment dashboard, and deliberately so. The two tracks
count different things: internal hiring measures an approval chain and a probation
outcome, client hiring measures delivery against a client's expectations. Putting both in
one figure would produce a number that means nothing to either audience.

-- The question this board answers -------------------------------------------------
"Where is everything, and who is holding it up." The PRO-fit flow alternates between
Sparsh and the client at almost every stage, so the useful split is not stage-by-stage
volume but WHOSE MOVE IT IS. A recruiter chasing a client, and a client wondering why
nothing has arrived, are looking at the same pipeline from opposite sides.

-- Scoping ---------------------------------------------------------------------------
Every count runs through the same company filter the record endpoints use, so a client
company sees their own engagement and nobody else's, and Sparsh staff see one client at a
time or all of them. Nothing here reads an internal requisition, candidate or employee.
"""
from typing import Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.utils.hrms_access import is_internal_user
from app.models.hrms import (
    COLL_CLIENT_ASSESSMENTS, COLL_CLIENT_CANDIDATES, COLL_CLIENT_INTERVIEWS,
    COLL_CLIENT_JOININGS, COLL_CLIENT_OFFERS, COLL_CLIENT_REQUISITIONS,
    COLL_CLIENT_SCORECARDS, ClientAssessmentStatus, ClientCandidateStatus,
    ClientInterviewStatus, ClientJoiningStatus, ClientOfferStatus,
    ClientReqStatus, ClientScorecardStatus,
)


def _scope(company_id: Optional[str]) -> dict:
    return {"company_id": str(company_id)} if company_id else {}


async def _count(coll: str, scope: dict, **extra) -> int:
    try:
        return await get_collection(coll).count_documents({**scope, **extra})
    except Exception:
        # A board that cannot count one thing should still show the rest.
        return 0


async def _tally(coll: str, field: str = "status") -> dict:
    """Count rows per company and status, in one read instead of one query per client.

    Grouped in Python rather than with an aggregation pipeline. The client track is small
    by nature -- one requisition is one vacancy at one client -- so a projection over the
    two fields costs nothing, and it keeps the board working against any storage layer
    rather than depending on a particular aggregation dialect.
    """
    try:
        rows = await get_collection(coll).find(
            {}, {"company_id": 1, field: 1}).to_list(5000)
    except Exception:
        return {}
    out: dict = {}
    for r in rows:
        bucket = out.setdefault(r.get("company_id"), {})
        value = r.get(field)
        bucket[value] = bucket.get(value, 0) + 1
    return out


async def _company_names(ids) -> dict:
    """Display names for the client companies that have any activity."""
    oids, mapping = [], {}
    for cid in ids:
        try:
            oids.append(ObjectId(str(cid)))
        except Exception:
            continue
    if not oids:
        return mapping
    try:
        rows = await get_collection("companies").find(
            {"_id": {"$in": oids}}, {"name": 1}).to_list(500)
    except Exception:
        return mapping
    for r in rows:
        mapping[str(r["_id"])] = r.get("name") or str(r["_id"])
    return mapping


async def client_companies(actor: dict, company_id: Optional[str]) -> dict:
    """The client companies this caller may look at, and whether any are switched on.

    The shared HRMS company selector cannot serve this. It lists companies with the HRMS
    module enabled, which on an in-house system means Sparsh Magic itself, and it hides
    entirely when there is only one -- so on the client track it offered nothing to pick
    and gave no hint why.

    Two sources, deliberately:
      * companies ELIGIBLE for the track (module on, and not the in-house tenant). These
        are the ones whose own users can log in and act.
      * companies that already HAVE client-track records. A company switched off after an
        engagement started still has data somebody may need to read, and dropping it from
        the picker would strand that data with no way to reach it.

    A client-side caller gets their own company and nothing else, so the picker cannot
    become a directory of who else Sparsh recruits for.
    """
    from app.utils.hrms_access import client_track_company

    if not is_internal_user(actor):
        ids = {str(company_id)} if company_id else set()
        eligible = set(ids)
        with_records = set(ids)
    else:
        rows = await get_collection("companies").find(
            {}, {"_id": 1, "hrms_enabled": 1, "is_internal": 1}).to_list(500)
        eligible = {str(r["_id"]) for r in rows
                    if r.get("hrms_enabled") and not r.get("is_internal")}
        with_records = set()
        for coll in (COLL_CLIENT_REQUISITIONS, COLL_CLIENT_CANDIDATES):
            try:
                for r in await get_collection(coll).find(
                        {}, {"company_id": 1}).to_list(5000):
                    if r.get("company_id"):
                        with_records.add(str(r["company_id"]))
            except Exception:
                pass
        ids = eligible | with_records

    names = await _company_names(ids)
    out = [{"id": cid,
            "name": names.get(cid, cid),
            "enabled": cid in eligible,
            # Whether this engagement has actually started. A picker that opens on the
            # first company alphabetically opens on an empty board whenever that company
            # happens to have nothing, which reads as "Client Hiring is empty" rather than
            # "this one client is". The screen defaults to a company with activity.
            "has_records": cid in with_records}
           for cid in sorted(ids, key=lambda c: names.get(c, c).lower())]
    return {
        "client_companies": out,
        "total": len(out),
        # What the screen needs to explain an empty picker rather than just showing one.
        "any_enabled": any(c["enabled"] for c in out),
        "any_records": any(c["has_records"] for c in out),
    }


async def by_client_breakdown() -> list:
    """One row per client company, for comparing engagements side by side.

    The board otherwise answers "how is THIS engagement going", which needs the company
    selector and one client at a time. The question a delivery lead actually asks is
    which client is moving and which is stuck, and that cannot be answered by looking at
    them one after another.

    Aggregated per collection rather than per company, so adding a client does not add a
    round of queries.

    INTERNAL CALLERS ONLY. The caller check lives at the one place this is invoked from,
    because a cross-client comparison is exactly the thing a client company must never
    see -- their own row is their business, everybody else's is not.
    """
    reqs = await _tally(COLL_CLIENT_REQUISITIONS)
    cands = await _tally(COLL_CLIENT_CANDIDATES)
    offers = await _tally(COLL_CLIENT_OFFERS)
    scorecards = await _tally(COLL_CLIENT_SCORECARDS)
    assessments = await _tally(COLL_CLIENT_ASSESSMENTS)
    interviews = await _tally(COLL_CLIENT_INTERVIEWS)
    joinings = await _tally(COLL_CLIENT_JOININGS)

    companies = set(reqs) | set(cands) | set(offers) | set(scorecards) \
        | set(assessments) | set(interviews) | set(joinings)
    names = await _company_names(companies)

    def n(tally, company, *statuses):
        row = tally.get(company) or {}
        return sum(row.get(s, 0) for s in statuses)

    out = []
    for company in companies:
        accepted = n(offers, company, ClientOfferStatus.ACCEPTED.value)
        declined = n(offers, company, ClientOfferStatus.DECLINED.value)
        decided = accepted + declined
        with_client = (
            n(cands, company, ClientCandidateStatus.SHARED_WITH_CLIENT.value)
            + n(scorecards, company,
                ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value)
            + n(assessments, company, ClientAssessmentStatus.SHARED.value)
            + n(interviews, company, ClientInterviewStatus.SHARED.value)
            + n(offers, company, ClientOfferStatus.PENDING_CLIENT_APPROVAL.value)
            + n(joinings, company, ClientJoiningStatus.PRE_BOARDING.value)
        )
        with_sparsh = (
            n(reqs, company, ClientReqStatus.PENDING_FEASIBILITY.value)
            + n(scorecards, company, ClientScorecardStatus.DRAFT.value,
                ClientScorecardStatus.PENDING_INTERNAL_REVIEW.value)
            + n(assessments, company, ClientAssessmentStatus.SENT.value,
                ClientAssessmentStatus.SUBMITTED.value,
                ClientAssessmentStatus.SCORED.value)
            + n(interviews, company, ClientInterviewStatus.SCHEDULED.value,
                ClientInterviewStatus.CONDUCTED.value)
            + n(offers, company, ClientOfferStatus.DRAFT.value,
                ClientOfferStatus.PENDING_VERIFICATION.value)
            + n(joinings, company, ClientJoiningStatus.JOINED.value)
        )
        out.append({
            "company_id": company,
            "company_name": names.get(str(company), str(company)),
            "requisitions_raised": sum((reqs.get(company) or {}).values()),
            "requisitions_live": n(reqs, company, ClientReqStatus.APPROVED.value),
            "requisitions_closed": n(reqs, company, ClientReqStatus.CLOSED.value),
            "candidates": sum((cands.get(company) or {}).values()),
            "joined": n(cands, company, ClientCandidateStatus.JOINED.value),
            "waiting_on_client": with_client,
            "waiting_on_sparsh": with_sparsh,
            "offer_acceptance_rate": (round(accepted / decided * 100, 1)
                                      if decided else None),
        })
    # Busiest engagement first: the one with most work outstanding is the one somebody
    # needs to look at, and an alphabetical list buries it.
    out.sort(key=lambda r: (r["waiting_on_client"] + r["waiting_on_sparsh"],
                            r["candidates"]), reverse=True)
    return out


async def client_recruitment_analytics(actor: dict, company_id: Optional[str]) -> dict:
    """Headline figures, the delivery funnel, and who each stage is waiting on."""
    s = _scope(company_id)

    # ── The funnel, in the order the SOP runs ────────────────────────────────────
    # Counted as "reached this stage OR went past it" would need a rank per status and
    # would double-count a rejected candidate. These are CURRENT positions instead, which
    # is what a board is actually asked: where is everybody right now.
    cand = COLL_CLIENT_CANDIDATES
    funnel = [
        {"key": "sourced", "label": "Sourced",
         "value": await _count(cand, s, status=ClientCandidateStatus.SOURCED.value)},
        {"key": "screened", "label": "Screened",
         "value": await _count(cand, s, status={"$in": [
             ClientCandidateStatus.SCREENED.value,
             ClientCandidateStatus.TELEPHONIC_PASSED.value]})},
        {"key": "shortlisted", "label": "Shortlisted",
         "value": await _count(cand, s,
                               status=ClientCandidateStatus.SHORTLISTED.value)},
        {"key": "shared", "label": "CV shared",
         "value": await _count(cand, s,
                               status=ClientCandidateStatus.SHARED_WITH_CLIENT.value)},
        {"key": "assessment", "label": "Assessment",
         "value": await _count(cand, s, status={"$in": [
             ClientCandidateStatus.CLIENT_APPROVED.value,
             ClientCandidateStatus.ASSESSMENT.value,
             ClientCandidateStatus.ASSESSMENT_REVIEWED.value]})},
        {"key": "interview", "label": "Interview",
         "value": await _count(cand, s, status=ClientCandidateStatus.INTERVIEW.value)},
        {"key": "selected", "label": "Selected",
         "value": await _count(cand, s, status=ClientCandidateStatus.SELECTED.value)},
        {"key": "offer", "label": "Offer out",
         "value": await _count(cand, s, status={"$in": [
             ClientCandidateStatus.OFFER_RELEASED.value,
             ClientCandidateStatus.OFFER_ACCEPTED.value]})},
        {"key": "joined", "label": "Joined",
         "value": await _count(cand, s, status=ClientCandidateStatus.JOINED.value)},
    ]

    # ── Whose move is it ─────────────────────────────────────────────────────────
    # The distinctive question on this track. Everything alternates between the two
    # sides, so "waiting" is only useful when it says waiting on WHOM.
    with_client = {
        "CV verdicts": await _count(
            cand, s, status=ClientCandidateStatus.SHARED_WITH_CLIENT.value),
        "scorecard approvals": await _count(
            COLL_CLIENT_SCORECARDS, s,
            status=ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value),
        "assessment results to review": await _count(
            COLL_CLIENT_ASSESSMENTS, s, status=ClientAssessmentStatus.SHARED.value),
        "recordings to watch": await _count(
            COLL_CLIENT_INTERVIEWS, s, status=ClientInterviewStatus.SHARED.value),
        "offers to issue": await _count(
            COLL_CLIENT_OFFERS, s,
            status=ClientOfferStatus.PENDING_CLIENT_APPROVAL.value),
        "joinings to confirm": await _count(
            COLL_CLIENT_JOININGS, s, status=ClientJoiningStatus.PRE_BOARDING.value),
    }
    with_sparsh = {
        "feasibility reviews": await _count(
            COLL_CLIENT_REQUISITIONS, s,
            status=ClientReqStatus.PENDING_FEASIBILITY.value),
        "scorecards to draft or review": await _count(
            COLL_CLIENT_SCORECARDS, s, status={"$in": [
                ClientScorecardStatus.DRAFT.value,
                ClientScorecardStatus.PENDING_INTERNAL_REVIEW.value]}),
        "assessments to mark": await _count(
            COLL_CLIENT_ASSESSMENTS, s, status={"$in": [
                ClientAssessmentStatus.SENT.value,
                ClientAssessmentStatus.SUBMITTED.value,
                ClientAssessmentStatus.SCORED.value]}),
        "interviews to run or deliver": await _count(
            COLL_CLIENT_INTERVIEWS, s, status={"$in": [
                ClientInterviewStatus.SCHEDULED.value,
                ClientInterviewStatus.CONDUCTED.value]}),
        "offers to prepare or verify": await _count(
            COLL_CLIENT_OFFERS, s, status={"$in": [
                ClientOfferStatus.DRAFT.value,
                ClientOfferStatus.PENDING_VERIFICATION.value]}),
        "handovers to complete": await _count(
            COLL_CLIENT_JOININGS, s, status=ClientJoiningStatus.JOINED.value),
    }

    # ── Headline ─────────────────────────────────────────────────────────────────
    raised = await _count(COLL_CLIENT_REQUISITIONS, s)
    approved = await _count(COLL_CLIENT_REQUISITIONS, s,
                            status=ClientReqStatus.APPROVED.value)
    closed = await _count(COLL_CLIENT_REQUISITIONS, s,
                          status=ClientReqStatus.CLOSED.value)
    rejected = await _count(COLL_CLIENT_REQUISITIONS, s,
                            status=ClientReqStatus.REJECTED.value)
    joined = await _count(cand, s, status=ClientCandidateStatus.JOINED.value)
    offers_out = await _count(COLL_CLIENT_OFFERS, s,
                              status=ClientOfferStatus.RELEASED.value)
    accepted = await _count(COLL_CLIENT_OFFERS, s,
                            status=ClientOfferStatus.ACCEPTED.value)
    declined = await _count(COLL_CLIENT_OFFERS, s,
                            status=ClientOfferStatus.DECLINED.value)
    dropped = await _count(cand, s, status=ClientCandidateStatus.DROPPED.value)
    at_risk = await _count(COLL_CLIENT_JOININGS, s, at_risk=True,
                           status=ClientJoiningStatus.PRE_BOARDING.value)
    cv_rejected = await _count(cand, s,
                               status=ClientCandidateStatus.CLIENT_REJECTED.value)

    decided = accepted + declined
    return {
        "headline": {
            "requisitions_raised": raised,
            "requisitions_live": approved,
            "requisitions_closed": closed,
            "requisitions_rejected": rejected,
            "candidates_sourced": await _count(cand, s),
            "joined": joined,
            "offers_out": offers_out,
            "joiners_at_risk": at_risk,
        },
        "funnel": funnel,
        "waiting_on_client": {k: v for k, v in with_client.items() if v},
        "waiting_on_sparsh": {k: v for k, v in with_sparsh.items() if v},
        "waiting_on_client_total": sum(with_client.values()),
        "waiting_on_sparsh_total": sum(with_sparsh.values()),
        # One row per client, for comparing engagements rather than stepping through
        # them. Internal callers only, and only when no single client is selected --
        # with a company in scope the board is about that engagement.
        "by_client": (await by_client_breakdown()
                      if is_internal_user(actor) and not company_id else []),
        "scope": "all_clients" if not company_id else "one_client",
        "outcomes": {
            # Offer acceptance rate, over offers the candidate actually answered. Counting
            # live offers in the denominator would make the rate sag every time one was
            # issued and improve when nothing was happening.
            "offer_acceptance_rate": (round(accepted / decided * 100, 1)
                                      if decided else None),
            "offers_accepted": accepted,
            "offers_declined": declined,
            "cv_rejected_by_client": cv_rejected,
            "dropped_before_joining": dropped,
        },
    }
