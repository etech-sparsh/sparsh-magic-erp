"""Client Hiring -- the five client-owned decisions belong to the client and to NOBODY else.

PRO-fit gives the client company five decision points, and the commercial value of the
whole track rests on them being genuinely theirs:

    1. Scorecard approval        -- the benchmark they will be measured against
    2. CV approve / reject       -- the verdict that opens the assessment
    3. Select / reject after interview
    4. Offer release             -- their own employment contract
    5. Joining confirmation      -- only they know whether somebody turned up

Keeping them out of ROLE_CAPABILITIES was never enough. `capabilities_for` resolves the
ADMIN role to "every member of Cap" deliberately, so that a capability added in a later
phase can never lock the module owner out of their own system -- and that blanket grant
swept these five up with everything else. A Sparsh superadmin was offered "Approve" on a
scorecard sitting with the client, and could release the client's own offer. The buttons
were real and the API accepted the calls.

THE DISTINCTION THIS FILE PINS:

    ADMIN            = administrative access. Read, write, review, share, support,
                       troubleshoot, run the workflow. Unchanged in every respect.
    CLIENT_DECISION  = the authority to make a decision the client owns. Held by
                       client-side callers only, by virtue of being that company.

Six properties, each a way the separation could rot:

  1. THE CLIENT CAN STILL DECIDE. A carve-out that also disarmed the client would be a
     regression dressed as a fix.
  2. NO SPARSH GOVERNANCE ROLE CAN. HR, HOD/Team Lead, Finance, MD, plain staff.
  3. NOT EVEN ADMIN. The branch that grants everything must not grant these.
  4. A DIRECT API CALL FAILS. Not a hidden button -- the route refuses, with a 403.
  5. ADMIN KEEPS EVERYTHING ELSE. Exactly the five are withheld, and nothing more.
  6. TENANT ISOLATION IS UNTOUCHED. The client still reaches only their own company.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_decision_exclusivity   (from backend/)
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
    except Exception as e:  # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CLIENT_CO = "client-people-to-process"
OTHER_CO = "client-somebody-else"


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    from app.utils import hrms_access as HA
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)

    # ── Actors ───────────────────────────────────────────────────────────────
    def staff(role="admin", governance=None, name="Sparsh Person"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "full_name": name}
        if governance:
            u["governance_role"] = governance
        return u

    def client_user(company=CLIENT_CO, role="clientadmin"):
        """A client-side caller, stamped the way the module gate stamps them."""
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "learners",
                "company_id": company, "full_name": "Client Person",
                M.CLIENT_TRACK_FLAG: True}

    SPARSH_ROLES = [
        ("Superadmin", staff(role="superadmin")),
        ("Recruiter (HR)", staff(governance="HR")),
        ("Team Lead (HOD)", staff(governance="HOD")),
        ("Finance", staff(governance="FINANCE")),
        ("MD", staff(governance="MD")),
        ("Staff, no governance role", staff(role="staff")),
    ]

    DECISIONS = sorted(M.CLIENT_DECISION_CAPS, key=lambda c: c.name)

    # =================================================================
    section("The client-owned decisions are named, and they are the right ones")
    # =================================================================
    # Five originally, six since the salary deviation was added. The number is asserted so
    # that widening this set is always a deliberate edit to this line and never a side
    # effect: every entry here is a capability SUPERADMIN LOSES, which is exactly the kind
    # of change that should not be able to happen quietly.
    check("exactly six capabilities are reserved", len(M.CLIENT_DECISION_CAPS) == 6)
    check("they are the client's own decision points",
          {c.name for c in M.CLIENT_DECISION_CAPS} == {
              "CLIENT_SCORECARD_APPROVE",
              "CLIENT_CANDIDATE_DECIDE",
              "CLIENT_INTERVIEW_DECIDE",
              "CLIENT_OFFER_RELEASE",
              "CLIENT_JOINING_CONFIRM",
              # Approving pay above the range the client themselves approved. Their
              # budget, so their call -- see test_client_salary_deviation.
              "CLIENT_OFFER_DEVIATE"})
    check("every one is inside the client's own ceiling",
          M.CLIENT_DECISION_CAPS <= M.CLIENT_TRACK_CAPS)

    # =================================================================
    section("1. A client company's user CAN make all five")
    # =================================================================
    client_caps = HA.capabilities_for(client_user())
    for cap in DECISIONS:
        check(f"client holds {cap.name}", cap in client_caps)
    check("...and `can()` agrees, which is what every gate calls",
          all(HA.can(client_user(), c) for c in DECISIONS))

    # A client's OWN superadmin claim changes nothing: they are still client-side.
    check("a client-side account claiming superadmin still holds exactly the ceiling",
          HA.capabilities_for(client_user(role="clientadmin")) == set(M.CLIENT_TRACK_CAPS))

    # =================================================================
    section("2-3. No Sparsh role can make any of them")
    # =================================================================
    for label, actor in SPARSH_ROLES:
        caps = HA.capabilities_for(actor)
        held = sorted(c.name for c in DECISIONS if c in caps)
        check(f"{label}: holds none of the five", not held)
        if held:
            print(f"      still holds: {held}")

    # The ADMIN branch is the one that used to grant them, so it gets its own assertion.
    admin_caps = HA.capabilities_for(staff(role="superadmin"))
    check("the ADMIN branch no longer means 'every capability'",
          admin_caps != set(M.Cap))
    check("...it means 'every capability except what belongs to the client'",
          admin_caps == set(M.Cap) - M.CLIENT_DECISION_CAPS - M.CLIENT_OWNED_CAPS)

    # =================================================================
    section("5. Administrative access is untouched")
    # =================================================================
    # The point of the carve-out is that a superadmin still administers the track. If this
    # section fails, the fix has taken away support access rather than decision authority.
    KEEPS = [
        (M.Cap.MODULE_ACCESS, "reach HRMS at all"),
        (M.Cap.MODULE_ADMIN, "administer the module"),
        (M.Cap.CLIENT_REQUISITION_READ, "read client requisitions"),
        (M.Cap.CLIENT_REQUISITION_REVIEW, "run the feasibility review"),
        (M.Cap.CLIENT_SCORECARD_READ, "read a scorecard"),
        (M.Cap.CLIENT_SCORECARD_WRITE, "draft a scorecard"),
        (M.Cap.CLIENT_SCORECARD_REVIEW, "review one internally"),
        (M.Cap.CLIENT_CANDIDATE_READ, "read candidates"),
        (M.Cap.CLIENT_CANDIDATE_WRITE, "source and screen"),
        (M.Cap.CLIENT_CANDIDATE_SHARE, "share a CV"),
        (M.Cap.CLIENT_ASSESSMENT_SCORE, "score an assessment"),
        (M.Cap.CLIENT_ASSESSMENT_SHARE, "share the result"),
        (M.Cap.CLIENT_INTERVIEW_MANAGE, "schedule and record an interview"),
        (M.Cap.CLIENT_INTERVIEW_SHARE, "share the recording"),
        (M.Cap.CLIENT_OFFER_WRITE, "draft an offer"),
        (M.Cap.CLIENT_OFFER_VERIFY, "verify one"),
        (M.Cap.CLIENT_JOINING_MANAGE, "run pre-boarding"),
        (M.Cap.CLIENT_JOINING_HANDOVER, "hand over the file"),
        (M.Cap.CLIENT_ANALYTICS_READ, "read the delivery board"),
    ]
    owner = staff(role="superadmin")
    for cap, what in KEEPS:
        check(f"superadmin can still {what}", HA.can(owner, cap))
    withheld = M.CLIENT_DECISION_CAPS | M.CLIENT_OWNED_CAPS
    check(f"superadmin holds {len(admin_caps)} of {len(set(M.Cap))} capabilities "
          f"-- only the client's own decisions and forms are withheld",
          len(set(M.Cap)) - len(admin_caps) == len(withheld))

    # ── The client's own WORK, as distinct from their decisions ──
    # On PRO-fit the requirement originates with the client (SOP section 7 step 1). Sparsh
    # reviewing it is a different capability and stays with Sparsh. Asserted separately
    # from the decisions so neither set can quietly absorb the other.
    check("raising the client's own requirement is withheld from Sparsh",
          M.Cap.CLIENT_REQUISITION_WRITE in M.CLIENT_OWNED_CAPS)
    check("...so superadmin cannot raise one",
          not HA.can(staff(role="superadmin"), M.Cap.CLIENT_REQUISITION_WRITE))
    check("...nor the Team Lead",
          not HA.can(staff(governance="HOD"), M.Cap.CLIENT_REQUISITION_WRITE))
    check("...but the client can",
          M.Cap.CLIENT_REQUISITION_WRITE in M.CLIENT_TRACK_CAPS)
    check("reviewing feasibility is still SPARSH's, not the client's",
          HA.can(staff(governance="HOD"), M.Cap.CLIENT_REQUISITION_REVIEW)
          and M.Cap.CLIENT_REQUISITION_REVIEW not in M.CLIENT_TRACK_CAPS)
    check("the two sets stay disjoint -- a form is not a decision",
          not (M.CLIENT_DECISION_CAPS & M.CLIENT_OWNED_CAPS))

    # Internal HRMS is a different module and must not have moved at all.
    check("internal hiring capabilities are untouched for Sparsh HR",
          HA.can(staff(governance="HR"), M.Cap.REQUISITION_REVIEW_HR))
    check("...and for the Team Lead", HA.can(staff(governance="HOD"), M.Cap.SCORECARD_APPROVE))
    check("no internal capability was caught by the carve-out",
          not any(c.name.startswith("CLIENT_") is False for c in M.CLIENT_DECISION_CAPS))

    # =================================================================
    section("4. A DIRECT API CALL is refused, not just a hidden button")
    # =================================================================
    # Everything above is the capability layer. This drives the actual route handlers with
    # a superadmin, because "we hid the button" is not an authorization model.
    store = {
        "companies": FakeCollection([
            {"_id": ObjectId(), "name": "People to Process",
             "hrms_enabled": True, "is_internal": False},
        ]),
        M.COLL_CLIENT_REQUISITIONS: FakeCollection([
            {"cr_no": "CR-2026-001", "company_id": CLIENT_CO, "role_title": "Ops Lead",
             "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW,
             "salary_range_min": 600000, "salary_range_max": 900000,
             "role_level": "Mid-level / Specialist"},
        ]),
        M.COLL_CLIENT_SCORECARDS: FakeCollection([
            {"psc_no": "PSC-2026-001", "cr_no": "CR-2026-001", "company_id": CLIENT_CO,
             "status": M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value,
             "created_at": NOW},
        ]),
        M.COLL_CLIENT_CANDIDATES: FakeCollection([
            {"ccn_no": "CCN-2026-001", "cr_no": "CR-2026-001", "company_id": CLIENT_CO,
             "candidate_name": "Ritu Sharma", "created_at": NOW,
             "status": M.ClientCandidateStatus.SHARED_WITH_CLIENT.value},
        ]),
        M.COLL_CLIENT_INTERVIEWS: FakeCollection([
            {"cin_no": "CIN-2026-001", "ccn_no": "CCN-2026-001", "company_id": CLIENT_CO,
             "status": M.ClientInterviewStatus.SHARED.value, "outcome": "Recommend",
             "recording_link": "https://example.test/rec", "created_at": NOW},
        ]),
        M.COLL_CLIENT_OFFERS: FakeCollection([
            {"cof_no": "COF-2026-001", "ccn_no": "CCN-2026-001", "cr_no": "CR-2026-001",
             "company_id": CLIENT_CO, "offered_ctc": 870000, "joining_date": "2026-11-02",
             "status": M.ClientOfferStatus.PENDING_CLIENT_APPROVAL.value,
             "created_at": NOW},
        ]),
        M.COLL_CLIENT_JOININGS: FakeCollection([
            {"cjn_no": "CJN-2026-001", "ccn_no": "CCN-2026-001", "cr_no": "CR-2026-001",
             "company_id": CLIENT_CO, "joining_date": "2026-11-02",
             "status": M.ClientJoiningStatus.PRE_BOARDING.value, "created_at": NOW},
        ]),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    from app.services import (
        hrms_client_scorecard_service as SC,
        hrms_client_candidate_service as CAND,
        hrms_client_interview_service as IV,
        hrms_client_offer_service as OF,
        hrms_client_joining_service as JN,
    )
    import app.services.hrms_client_analytics_service as AN
    for mod in (SC, CAND, IV, OF, JN, AN, HA):
        mod.get_collection = mongo.get_collection

    try:
        owner = staff(role="superadmin")

        # Each of the five, called through the service the route delegates to, with the
        # exact payload the screen sends. All must be refused on the capability, not on a
        # from-state -- these records are all sitting in the state that invites the move.
        CALLS = [
            ("scorecard approval",
             SC.act_on_client_scorecard(owner, CLIENT_CO, "PSC-2026-001",
                                        "client-approve", {}),
             "client_scorecard.approve"),
            ("CV approval",
             CAND.act_on_client_candidate(owner, CLIENT_CO, "CCN-2026-001",
                                          "client-approve", {}),
             "client_candidate.decide"),
            ("CV rejection",
             CAND.act_on_client_candidate(owner, CLIENT_CO, "CCN-2026-001",
                                          "client-reject", {"remarks": "not a fit"}),
             "client_candidate.decide"),
            ("selection after interview",
             IV.act_on_client_interview(owner, CLIENT_CO, "CIN-2026-001",
                                        "client-select", {}),
             "client_interview.decide"),
            ("rejection after interview",
             IV.act_on_client_interview(owner, CLIENT_CO, "CIN-2026-001",
                                        "client-reject", {"remarks": "not a fit"}),
             "client_interview.decide"),
            ("offer release",
             OF.act_on_client_offer(owner, CLIENT_CO, "COF-2026-001",
                                    "client-release", {}),
             "client_offer.release"),
            ("joining confirmation",
             JN.act_on_client_joining(owner, CLIENT_CO, "CJN-2026-001",
                                      "confirm-joining",
                                      {"actual_joining_date": "2026-11-03",
                                       "acknowledged": True}),
             "client_joining.confirm"),
        ]
        for label, coro, cap_value in CALLS:
            await expect_http(f"superadmin: {label}", coro, 403, cap_value)

        # And the records did not move. A refusal that still wrote would be worse than no
        # refusal at all, because nothing would show it had happened.
        after = {
            "PSC-2026-001": (await store[M.COLL_CLIENT_SCORECARDS].find_one(
                {"psc_no": "PSC-2026-001"}))["status"],
            "CCN-2026-001": (await store[M.COLL_CLIENT_CANDIDATES].find_one(
                {"ccn_no": "CCN-2026-001"}))["status"],
            "CIN-2026-001": (await store[M.COLL_CLIENT_INTERVIEWS].find_one(
                {"cin_no": "CIN-2026-001"}))["status"],
            "COF-2026-001": (await store[M.COLL_CLIENT_OFFERS].find_one(
                {"cof_no": "COF-2026-001"}))["status"],
            "CJN-2026-001": (await store[M.COLL_CLIENT_JOININGS].find_one(
                {"cjn_no": "CJN-2026-001"}))["status"],
        }
        check("nothing moved: the scorecard is still with the client",
              after["PSC-2026-001"] == M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value)
        check("...the candidate is still awaiting a verdict",
              after["CCN-2026-001"] == M.ClientCandidateStatus.SHARED_WITH_CLIENT.value)
        check("...the interview is still awaiting a selection",
              after["CIN-2026-001"] == M.ClientInterviewStatus.SHARED.value)
        check("...the offer is still unreleased",
              after["COF-2026-001"] == M.ClientOfferStatus.PENDING_CLIENT_APPROVAL.value)
        check("...and nobody has been declared joined",
              after["CJN-2026-001"] == M.ClientJoiningStatus.PRE_BOARDING.value)

        # =================================================================
        section("Every other Sparsh role is refused the same way")
        # =================================================================
        for label, actor in SPARSH_ROLES[1:]:
            await expect_http(
                f"{label}: scorecard approval",
                SC.act_on_client_scorecard(actor, CLIENT_CO, "PSC-2026-001",
                                           "client-approve", {}),
                403, "client_scorecard.approve")
            await expect_http(
                f"{label}: offer release",
                OF.act_on_client_offer(actor, CLIENT_CO, "COF-2026-001",
                                       "client-release", {}),
                403, "client_offer.release")

        # =================================================================
        section("The client themselves is still allowed through")
        # =================================================================
        # The same call, same records, same state -- only the caller differs. If this
        # fails the carve-out has disarmed the people it exists to protect.
        them = client_user(CLIENT_CO)
        approved = await SC.act_on_client_scorecard(
            them, CLIENT_CO, "PSC-2026-001", "client-approve", {})
        check("client approves the scorecard",
              approved.get("status") == M.ClientScorecardStatus.APPROVED.value)

        verdict = await CAND.act_on_client_candidate(
            them, CLIENT_CO, "CCN-2026-001", "client-approve", {})
        check("client gives the CV verdict",
              verdict.get("status") == M.ClientCandidateStatus.CLIENT_APPROVED.value)

        selected = await IV.act_on_client_interview(
            them, CLIENT_CO, "CIN-2026-001", "client-select", {})
        check("client selects after the interview",
              selected.get("status") == M.ClientInterviewStatus.CLIENT_SELECTED.value)

        released = await OF.act_on_client_offer(
            them, CLIENT_CO, "COF-2026-001", "client-release", {})
        check("client releases the offer",
              released.get("status") == M.ClientOfferStatus.RELEASED.value)

        joined = await JN.act_on_client_joining(
            them, CLIENT_CO, "CJN-2026-001", "confirm-joining",
            {"actual_joining_date": "2026-11-03", "acknowledged": True})
        check("client confirms the joining",
              joined.get("status") == M.ClientJoiningStatus.JOINED.value)

        # =================================================================
        section("6. Tenant isolation is unchanged")
        # =================================================================
        outsider = client_user(OTHER_CO)
        check("a client is pinned to their own company, whatever they ask for",
              HA.scope_company_id(outsider, CLIENT_CO) == OTHER_CO)
        check("...and the filter follows the pin",
              HA.company_filter(outsider, CLIENT_CO).get("company_id") == OTHER_CO)
        await expect_http(
            "another client cannot approve this company's scorecard",
            SC.get_client_scorecard(outsider, OTHER_CO, "PSC-2026-001"),
            404)

        # =================================================================
        section("Sparsh's own half of the flow still works")
        # =================================================================
        # The carve-out must not have touched anything Sparsh legitimately does. The Team
        # Lead's internal review sits next to the client's approval in the same table.
        store[M.COLL_CLIENT_SCORECARDS] = FakeCollection([
            {"psc_no": "PSC-2026-002", "cr_no": "CR-2026-001", "company_id": CLIENT_CO,
             "status": M.ClientScorecardStatus.PENDING_INTERNAL_REVIEW.value,
             "created_at": NOW},
        ])
        SC.get_collection = lambda name: store.setdefault(name, FakeCollection())
        reviewed = await SC.act_on_client_scorecard(
            staff(governance="HOD"), CLIENT_CO, "PSC-2026-002", "internal-approve", {})
        check("Team Lead still approves internally, and it moves to the client",
              reviewed.get("status")
              == M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value)

        owner_reviewed = HA.can(staff(role="superadmin"), M.Cap.CLIENT_SCORECARD_REVIEW)
        check("superadmin still holds the internal review capability", owner_reviewed)
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
