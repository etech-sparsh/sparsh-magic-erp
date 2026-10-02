"""Client Hiring -- the salary deviation request (SOP section 16).

When a candidate's CTC lands outside the range the client approved on the Manpower
Requisition, the offer used to be a dead end: the submit was refused and the approved
range could not be edited, so the only way on was a brand-new requisition. This file pins
the route that replaces that dead end, and the things it must NOT disturb.

  1. THE REQUEST GOES STRAIGHT TO CLIENT HR. Draft -> Pending Salary Deviation, and the
     client can see it from that moment, because they are the one being asked.
  2. APPROVE REJOINS THE ORDINARY CHAIN. -> Pending Verification, then verify, release,
     accept, onboard, exactly as any other offer. Nothing downstream is special-cased.
  3. REJECT USES THE EXISTING REJECTION PATH. The candidate becomes `Client Rejected`,
     which is already an Available Candidates pool state. Nobody is deleted.
  4. IT IS CLIENT HR'S DECISION AND NOBODY ELSE'S. `CLIENT_OFFER_DEVIATE` sits in
     CLIENT_DECISION_CAPS, so every Sparsh role -- recruiter, Team Lead, Ops Head,
     Superadmin -- is refused it.
  5. THE APPROVED REQUISITION RANGE IS NEVER TOUCHED. Not by the request, not by the
     approval, not by the rejection. A deviation is permission for ONE offer.
  6. IT IS NOT A SHORTCUT. An offer already inside the range may not use it, and a
     deviation does not excuse section 15's reference check.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_salary_deviation   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

ACME, SPARSH = "client-acme", "sparsh-magic"


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)

    reqs = FakeCollection([
        {"cr_no": "CR-2026-001", "company_id": ACME, "role_title": "Backend Engineer",
         "role_level": M.ClientRoleLevel.MID.value,
         "salary_range_min": 900000, "salary_range_max": 1400000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
        # Managerial: section 15's reference check applies before an offer is released.
        {"cr_no": "CR-2026-002", "company_id": ACME, "role_title": "Delivery Manager",
         "role_level": M.ClientRoleLevel.MANAGERIAL.value,
         "salary_range_min": 2000000, "salary_range_max": 2600000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
    ])

    def cand(ccn, cr, name):
        return {"ccn_no": ccn, "company_id": ACME, "cr_no": cr, "candidate_name": name,
                "status": M.ClientCandidateStatus.SELECTED.value, "created_at": NOW}

    candidates = FakeCollection([
        cand("CCN-2026-001", "CR-2026-001", "Asha Expensive"),
        cand("CCN-2026-002", "CR-2026-001", "Ravi WithinRange"),
        cand("CCN-2026-003", "CR-2026-001", "Neel Rejected"),
        cand("CCN-2026-004", "CR-2026-002", "Maya Manager"),
    ])
    store = {M.COLL_CLIENT_REQUISITIONS: reqs,
             M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_CLIENT_OFFERS: FakeCollection(),
             M.COLL_CLIENT_REFERENCE_CHECKS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (OF, AUD, IDS, HA):
        mod.get_collection = mongo.get_collection

    def client(name="Acme HR"):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": ACME,
                "full_name": name, M.CLIENT_TRACK_FLAG: True}

    def sparsh(role, governance, name):
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
                "company_id": SPARSH, "governance_role": governance, "full_name": name}

    CLIENT_HR = client("Acme HR")
    RECRUITER = sparsh("admin", "HR", "Sparsh Recruiter")
    TEAM_LEAD = sparsh("admin", "HOD", "Sparsh Team Lead")
    OPS_HEAD = sparsh("admin", "MD", "Sparsh Ops Head")
    SUPERADMIN = sparsh("superadmin", "MD", "Sparsh Superadmin")

    def range_of(cr):
        row = [r for r in reqs.docs if r["cr_no"] == cr and r["company_id"] == ACME][0]
        return (row.get("salary_range_min"), row.get("salary_range_max"))

    try:
        # =================================================================
        section("4. Deciding a deviation is Client HR's, and nobody else's")
        # =================================================================
        check("Client HR holds it", HA.can(CLIENT_HR, M.Cap.CLIENT_OFFER_DEVIATE))
        for who, label in ((RECRUITER, "the recruiter"), (TEAM_LEAD, "the Team Lead"),
                           (OPS_HEAD, "the Ops Head"), (SUPERADMIN, "SUPERADMIN")):
            check(f"...{label} does not",
                  not HA.can(who, M.Cap.CLIENT_OFFER_DEVIATE))
        check("it is one of the client-exclusive decisions",
              M.Cap.CLIENT_OFFER_DEVIATE in M.CLIENT_DECISION_CAPS)
        check("Sparsh still prepares the offer itself",
              HA.can(RECRUITER, M.Cap.CLIENT_OFFER_WRITE))

        # =================================================================
        section("1. Out of range -> straight to Client HR")
        # =================================================================
        over = await OF.create_client_offer(RECRUITER, ACME, {
            "ccn_no": "CCN-2026-001", "offered_ctc": 1600000,
            "joining_date": "2026-11-01"})
        cof = over["cof_no"]
        check("the offer drafts even though it is over the range",
              over["status"] == M.ClientOfferStatus.DRAFT.value)

        state = await OF.offer_checkpoint(ACME, over)
        check("the checkpoint says it is outside the range",
              state["within_approved_range"] is False)
        check("...and points at the deviation request",
              any("deviation" in o.lower() for o in state["outstanding"]))

        await expect_http(
            "the ordinary submit is still refused",
            OF.act_on_client_offer(RECRUITER, ACME, cof, "submit-for-verification"),
            409, "checkpoint is not met")

        await expect_http(
            "a deviation request with no reason is refused",
            OF.act_on_client_offer(RECRUITER, ACME, cof, "submit-deviation"),
            422, "say why")

        asked = await OF.act_on_client_offer(
            RECRUITER, ACME, cof, "submit-deviation",
            {"remarks": "Asha is the only candidate who has run this stack at scale."})
        check("the request moves it to Pending Salary Deviation",
              asked["status"] == M.ClientOfferStatus.PENDING_DEVIATION.value)
        check("the reason is recorded",
              "only candidate" in (asked["deviation"]["requested"]["remarks"] or ""))
        check("...against the figures as they stood",
              asked["deviation"]["offered_ctc"] == 1600000
              and asked["deviation"]["salary_range_max"] == 1400000)
        check("no decision on it yet", asked["deviation"]["decision"] is None)

        check("the client can SEE it, because it is addressed to them",
              M.ClientOfferStatus.PENDING_DEVIATION.value
              in M.CLIENT_OFFER_VISIBLE_TO_CLIENT)
        seen = await OF.get_client_offer(CLIENT_HR, ACME, cof)
        check("...and the reason reaches them",
              "only candidate" in (seen.get("deviation", {})
                                   .get("requested", {}).get("remarks") or ""))

        listed = await OF.list_client_offers(CLIENT_HR, ACME)
        check("it counts as waiting on the client", listed["awaiting_client"] >= 1)

        # =================================================================
        section("5. The approved requisition range is NEVER touched")
        # =================================================================
        check("unchanged by the request", range_of("CR-2026-001") == (900000, 1400000))

        for who, label in ((RECRUITER, "the recruiter"), (TEAM_LEAD, "the Team Lead"),
                           (SUPERADMIN, "SUPERADMIN")):
            await expect_http(
                f"{label} cannot approve the deviation",
                OF.act_on_client_offer(who, ACME, cof, "deviation-approve"),
                403)

        # =================================================================
        section("2. Client HR approves -> the ordinary chain, unchanged")
        # =================================================================
        ok = await OF.act_on_client_offer(CLIENT_HR, ACME, cof, "deviation-approve",
                                          {"remarks": "Agreed for this hire only."})
        check("-> Pending Verification",
              ok["status"] == M.ClientOfferStatus.PENDING_VERIFICATION.value)
        check("the decision is stamped with who made it",
              ok["deviation"]["decision"]["decision"] == "approve"
              and ok["deviation"]["decision"]["by_name"] == "Acme HR")
        check("the range STILL has not moved", range_of("CR-2026-001") == (900000, 1400000))
        check("and the offer still carries the original range",
              ok["salary_range_max"] == 1400000)

        verified = await OF.act_on_client_offer(TEAM_LEAD, ACME, cof, "verify")
        check("the Team Lead verifies it as normal",
              verified["status"] == M.ClientOfferStatus.PENDING_CLIENT_APPROVAL.value)
        released = await OF.act_on_client_offer(CLIENT_HR, ACME, cof, "client-release")
        check("the client releases it as normal",
              released["status"] == M.ClientOfferStatus.RELEASED.value)
        accepted = await OF.act_on_client_offer(
            RECRUITER, ACME, cof, "record-acceptance",
            {"accepted_on": "2026-10-10", "joining_date": "2026-11-01"})
        check("acceptance is recorded as normal",
              accepted["status"] == M.ClientOfferStatus.ACCEPTED.value)
        moved = await candidates.find_one({"ccn_no": "CCN-2026-001", "company_id": ACME})
        check("...and the candidate reaches Offer Accepted, ready for onboarding",
              moved["status"] == M.ClientCandidateStatus.OFFER_ACCEPTED.value)

        # =================================================================
        section("3. Client HR rejects -> the EXISTING reject/available flow")
        # =================================================================
        no = await OF.create_client_offer(RECRUITER, ACME, {
            "ccn_no": "CCN-2026-003", "offered_ctc": 1550000,
            "joining_date": "2026-11-01"})
        no_cof = no["cof_no"]
        await OF.act_on_client_offer(RECRUITER, ACME, no_cof, "submit-deviation",
                                     {"remarks": "Asking well above the band."})
        turned = await OF.act_on_client_offer(CLIENT_HR, ACME, no_cof, "deviation-reject",
                                              {"remarks": "Outside what we can fund."})
        check("the offer is terminal",
              turned["status"] == M.ClientOfferStatus.DEVIATION_REJECTED.value)
        check("nothing leaves that state",
              not [a for a, spec in M.CLIENT_OFFER_TRANSITIONS.items()
                   if spec[0] == M.ClientOfferStatus.DEVIATION_REJECTED])

        person = await candidates.find_one({"ccn_no": "CCN-2026-003", "company_id": ACME})
        check("the CANDIDATE goes to the existing rejected state",
              person["status"] == M.ClientCandidateStatus.CLIENT_REJECTED.value)
        check("...which is an Available Candidates pool state",
              person["status"] in M.CLIENT_CANDIDATE_POOL)
        check("...so they are re-shareable, not deleted",
              person.get("candidate_name") == "Neel Rejected")
        check("the range is STILL untouched", range_of("CR-2026-001") == (900000, 1400000))

        # =================================================================
        section("6. It is not a shortcut")
        # =================================================================
        fits = await OF.create_client_offer(RECRUITER, ACME, {
            "ccn_no": "CCN-2026-002", "offered_ctc": 1200000,
            "joining_date": "2026-11-01"})
        await expect_http(
            "an offer INSIDE the range may not ask for a deviation",
            OF.act_on_client_offer(RECRUITER, ACME, fits["cof_no"], "submit-deviation",
                                   {"remarks": "trying it on"}),
            422, "does not need a deviation")

        senior = await OF.create_client_offer(RECRUITER, ACME, {
            "ccn_no": "CCN-2026-004", "offered_ctc": 2900000,
            "joining_date": "2026-11-01"})
        await expect_http(
            "a deviation does not excuse section 15's reference check",
            OF.act_on_client_offer(RECRUITER, ACME, senior["cof_no"], "submit-deviation",
                                   {"remarks": "worth it"}),
            409, "reference check")

        # =================================================================
        section("Nothing else moved")
        # =================================================================
        check("the requisition state machine gained no new edge",
              set(M.CLIENT_REQ_TRANSITIONS) == {
                  "submit-need-mapping", "submit-requisition", "feasibility-approve",
                  "feasibility-reject", "feasibility-return"})
        check("APPROVED is still a requisition's last stop",
              not [a for a, spec in M.CLIENT_REQ_TRANSITIONS.items()
                   if spec[0] == M.ClientReqStatus.APPROVED])
        check("the candidate state machine gained no new edge",
              "deviation-reject" not in M.CLIENT_CANDIDATE_TRANSITIONS)
        check("the five original client decisions are all still exclusive",
              {M.Cap.CLIENT_SCORECARD_APPROVE, M.Cap.CLIENT_CANDIDATE_DECIDE,
               M.Cap.CLIENT_INTERVIEW_DECIDE, M.Cap.CLIENT_OFFER_RELEASE,
               M.Cap.CLIENT_JOINING_CONFIRM} <= M.CLIENT_DECISION_CAPS)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print("\n" + "=" * 64)
    print(f"  {passed}/{len(results)} checks passed")
    print("=" * 64)
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
