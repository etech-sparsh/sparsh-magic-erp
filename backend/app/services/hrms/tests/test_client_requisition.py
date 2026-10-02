"""Client Hiring step 1 -- Need Mapping, Manpower Requisition, feasibility review.

PRO-fit SOP section 7. The client says what it needs and what it will pay; Sparsh decides
whether the engagement is deliverable before a single CV is sourced.

Three properties this file exists to pin:

  1. THE CLIENT CANNOT PASS THEIR OWN REQUISITION. Section 7 step 3 puts a Sparsh
     feasibility and budget review between the requisition and any sourcing. A client who
     could approve their own would delete that control entirely, so WRITE and REVIEW are
     different capabilities held by different sides.
  2. A REJECTED REQUISITION CANNOT PROGRESS. Asserted against the transition table rather
     than against a service branch, because "no edge out of Rejected" is the thing that
     makes it true everywhere rather than in the one place somebody remembered.
  3. ONE CLIENT CANNOT REACH ANOTHER'S, OR SPARSH'S. Not by listing, not by guessing a
     number, not by naming a company in the query string.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_requisition   (from backend/)
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

ACME, GLOBEX, SPARSH = "client-acme", "client-globex", "sparsh-magic"

NMF = {"business_context": "Opening a second delivery centre in Pune.",
       "role_need": "Two backend engineers to staff the new pod.",
       "urgency": "High",
       "engagement_expectations": "Shortlist within three weeks."}

MRF = {"role_title": "Backend Engineer", "department_name": "Engineering",
       "reporting_line": "Delivery Head", "salary_range_min": 900000,
       "salary_range_max": 1400000, "employment_type": "Permanent", "vacancies": 2}

PASSES = {"role_clarity": True, "compensation_competitive": True,
          "timeline_realistic": True}


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    store = {M.COLL_CLIENT_REQUISITIONS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_requisition_service as CR
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (CR, AUD, IDS, HA):
        mod.get_collection = mongo.get_collection

    def client(company, name="Client Person"):
        """A client-company user, stamped by the gate as client-track."""
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company,
                "full_name": name, M.CLIENT_TRACK_FLAG: True}

    def sparsh(governance, name="Sparsh Person"):
        return {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff",
                "company_id": SPARSH, "governance_role": governance, "full_name": name}

    ACME_HR = client(ACME, "Acme Talent Lead")
    GLOBEX_HR = client(GLOBEX, "Globex Talent Lead")
    RECRUITER = sparsh("HR", "Sparsh Recruiter")
    TEAM_LEAD = sparsh("HOD", "Sparsh Team Lead")
    OPS_HEAD = sparsh("MD", "Sparsh Ops Head")

    try:
        # =================================================================
        section("Who holds what")
        # =================================================================
        check("a client may raise a requisition",
              HA.can(ACME_HR, M.Cap.CLIENT_REQUISITION_WRITE))
        check("a client may read one", HA.can(ACME_HR, M.Cap.CLIENT_REQUISITION_READ))
        check("a client may NOT review one -- the whole control",
              not HA.can(ACME_HR, M.Cap.CLIENT_REQUISITION_REVIEW))
        check("the Team Lead reviews", HA.can(TEAM_LEAD, M.Cap.CLIENT_REQUISITION_REVIEW))
        check("the Operations Head reviews",
              HA.can(OPS_HEAD, M.Cap.CLIENT_REQUISITION_REVIEW))
        check("the recruiter reads but does not review",
              HA.can(RECRUITER, M.Cap.CLIENT_REQUISITION_READ)
              and not HA.can(RECRUITER, M.Cap.CLIENT_REQUISITION_REVIEW))
        check("Sparsh staff cannot raise one on the client's behalf",
              not HA.can(RECRUITER, M.Cap.CLIENT_REQUISITION_WRITE))

        # =================================================================
        section("No other HRMS module is reachable by a client")
        # =================================================================
        for cap in (M.Cap.PAYROLL_READ, M.Cap.EMPLOYEE_READ, M.Cap.ATTENDANCE_READ,
                    M.Cap.SEPARATION_READ, M.Cap.ONBOARDING_READ,
                    M.Cap.REQUISITION_READ, M.Cap.CANDIDATE_READ,
                    M.Cap.INTERVIEW_READ, M.Cap.OFFER_READ):
            check(f"client refused {cap.value}", not HA.can(ACME_HR, cap))

        # =================================================================
        section("Need Mapping -> Manpower Requisition")
        # =================================================================
        made = await CR.create_client_requisition(ACME_HR, ACME, NMF)
        CR_NO = made["cr_no"]
        check("the client raises a Need Mapping Form", bool(CR_NO))
        check("it opens at Need Mapping",
              made["status"] == M.ClientReqStatus.NEED_MAPPING.value)
        check("and belongs to their company", made["company_id"] == ACME)

        await expect_http(
            "a Need Mapping Form with no business context",
            CR.create_client_requisition(ACME_HR, ACME, {"role_need": "somebody"}),
            422, "business context")

        await CR.act_on_client_requisition(ACME_HR, ACME, CR_NO, "submit-need-mapping", {})
        row = await CR.get_client_requisition(ACME_HR, ACME, CR_NO)
        check("submitting it moves to Manpower Requisition",
              row["status"] == M.ClientReqStatus.MANPOWER_REQUISITION.value)

        await expect_http(
            "submitting an incomplete requisition form",
            CR.act_on_client_requisition(ACME_HR, ACME, CR_NO, "submit-requisition", {}),
            422, "not complete")

        await expect_http(
            "a salary range that is upside down",
            CR.update_client_requisition(ACME_HR, ACME, CR_NO,
                                         {"salary_range_min": 900000,
                                          "salary_range_max": 500000}),
            422, "cannot be above")

        await CR.update_client_requisition(ACME_HR, ACME, CR_NO, MRF)
        row = await CR.get_client_requisition(ACME_HR, ACME, CR_NO)
        check("the client completes the Manpower Requisition Form",
              row["role_title"] == "Backend Engineer"
              and row["salary_range_max"] == 1400000)

        await CR.act_on_client_requisition(ACME_HR, ACME, CR_NO, "submit-requisition", {})
        row = await CR.get_client_requisition(ACME_HR, ACME, CR_NO)
        check("and it goes to Sparsh for feasibility",
              row["status"] == M.ClientReqStatus.PENDING_FEASIBILITY.value)
        check("the client can no longer edit it",
              row["status"] not in M.CLIENT_REQ_EDITABLE)
        await expect_http(
            "...so an amendment is refused",
            CR.update_client_requisition(ACME_HR, ACME, CR_NO, {"vacancies": 9}),
            409, "no longer be edited")

        # =================================================================
        section("Sparsh reviews -- and the client cannot")
        # =================================================================
        await expect_http(
            "the CLIENT approving their own feasibility",
            CR.act_on_client_requisition(ACME_HR, ACME, CR_NO, "feasibility-approve",
                                         PASSES),
            403, "client_requisition.review")
        await expect_http(
            "the recruiter approving it",
            CR.act_on_client_requisition(RECRUITER, ACME, CR_NO, "feasibility-approve",
                                         PASSES),
            403, "client_requisition.review")
        await expect_http(
            "approving with no assessment recorded",
            CR.act_on_client_requisition(TEAM_LEAD, ACME, CR_NO, "feasibility-approve", {}),
            422, "still needed")
        await expect_http(
            "approving while a check is marked failed",
            CR.act_on_client_requisition(TEAM_LEAD, ACME, CR_NO, "feasibility-approve",
                                         {**PASSES, "compensation_competitive": False}),
            409, "did not pass")

        done = await CR.act_on_client_requisition(
            TEAM_LEAD, ACME, CR_NO, "feasibility-approve",
            {**PASSES, "remarks": "Pay is competitive; three weeks is realistic."})
        check("the Team Lead approves it",
              done["status"] == M.ClientReqStatus.APPROVED.value)
        check("the assessment is on the record",
              done["feasibility"]["role_clarity"] is True
              and done["feasibility"]["reviewed_by_name"] == "Sparsh Team Lead")
        check("only now may the Position Scorecard stage begin",
              await CR.is_activated(ACME, CR_NO))

        # =================================================================
        section("A rejected requisition cannot progress")
        # =================================================================
        second = await CR.create_client_requisition(ACME_HR, ACME, NMF)
        two = second["cr_no"]
        await CR.act_on_client_requisition(ACME_HR, ACME, two, "submit-need-mapping", {})
        await CR.update_client_requisition(ACME_HR, ACME, two, MRF)
        await CR.act_on_client_requisition(ACME_HR, ACME, two, "submit-requisition", {})

        await expect_http(
            "rejecting with no reason",
            CR.act_on_client_requisition(TEAM_LEAD, ACME, two, "feasibility-reject", {}),
            422, "say why")
        rejected = await CR.act_on_client_requisition(
            TEAM_LEAD, ACME, two, "feasibility-reject",
            {"remarks": "The band is thirty per cent below market for this role."})
        check("it is rejected", rejected["status"] == M.ClientReqStatus.REJECTED.value)
        check("the Position Scorecard stage stays shut",
              not await CR.is_activated(ACME, two))

        # The actor must HOLD the action's capability, or a 403 fires first and the
        # refusal under test is never reached. Client actions go to the client, review
        # actions to Sparsh.
        for action, spec in M.CLIENT_REQ_TRANSITIONS.items():
            mover = ACME_HR if spec[2] == "CLIENT_REQUISITION_WRITE" else OPS_HEAD
            await expect_http(
                f'a rejected requisition refuses "{action}"',
                CR.act_on_client_requisition(mover, ACME, two, action,
                                             {**PASSES, "remarks": "trying anyway"}),
                409, "cannot progress")
        check("no transition leads out of Rejected, by the table",
              not [a for a, s in M.CLIENT_REQ_TRANSITIONS.items()
                   if s[0] is M.ClientReqStatus.REJECTED])

        # =================================================================
        section("Returned for correction is not a rejection")
        # =================================================================
        third = await CR.create_client_requisition(ACME_HR, ACME, NMF)
        three = third["cr_no"]
        await CR.act_on_client_requisition(ACME_HR, ACME, three, "submit-need-mapping", {})
        await CR.update_client_requisition(ACME_HR, ACME, three, MRF)
        await CR.act_on_client_requisition(ACME_HR, ACME, three, "submit-requisition", {})
        back = await CR.act_on_client_requisition(
            TEAM_LEAD, ACME, three, "feasibility-return",
            {"remarks": "Confirm the reporting line before we source."})
        check("it goes back to the client, still alive",
              back["status"] == M.ClientReqStatus.MANPOWER_REQUISITION.value)
        check("and the client may edit it again",
              back["status"] in M.CLIENT_REQ_EDITABLE)

        # =================================================================
        section("Tenant isolation -- the part that must not be merely hidden")
        # =================================================================
        globex_own = await CR.create_client_requisition(GLOBEX_HR, GLOBEX, NMF)
        mine = await CR.list_client_requisitions(ACME_HR, ACME)
        check("a client lists only their own",
              all(r["company_id"] == ACME for r in mine["client_requisitions"]))
        check("...and Globex's row is not among them",
              not any(r["company_id"] == GLOBEX
                      for r in mine["client_requisitions"]))

        # Numbers are sequenced PER COMPANY on purpose, so a client cannot infer another
        # client's hiring volume from gaps in their own. Both tenants therefore start at
        # the same number, and asking for it resolves to YOUR row, never theirs.
        same_number = await CR.get_client_requisition(
            ACME_HR, ACME, globex_own["cr_no"])
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)

        await expect_http(
            "a number that exists in no tenant of theirs",
            CR.get_client_requisition(ACME_HR, ACME, "CR-2026-999"), 404, "not found")
        await expect_http(
            "...and acting on it",
            CR.act_on_client_requisition(ACME_HR, ACME, "CR-2026-999",
                                         "submit-need-mapping", {}), 404, "not found")

        # The route hands the service `scope_company_id(...)`, so a company named in the
        # query string never becomes the scope for a client-side caller.
        check("naming another company in the query is ignored",
              HA.scope_company_id(ACME_HR, GLOBEX) == ACME)
        check("...including Sparsh Magic's own tenant",
              HA.scope_company_id(ACME_HR, SPARSH) == ACME)

        await expect_http(
            "a client-side caller with no company in scope sees nothing",
            CR.list_client_requisitions(ACME_HR, None), 403, "no company in scope")

        every = await CR.list_client_requisitions(OPS_HEAD, None)
        check("Sparsh staff see the queue across clients",
              {r["company_id"] for r in every["client_requisitions"]} == {ACME, GLOBEX})
        waiting = [r for r in every["client_requisitions"]
                   if r["status"] == M.ClientReqStatus.PENDING_FEASIBILITY.value]
        check("and the queue count matches what is actually waiting",
              every["pending_feasibility"] == len(waiting))

        # =================================================================
        section("Internal Hiring is a different track entirely")
        # =================================================================
        check("client requisitions live in their own collection",
              M.COLL_CLIENT_REQUISITIONS != M.COLL_REQUISITIONS)
        # "Approved" and "Rejected" are ordinary English and appear on both tracks; that
        # is not a leak. What must not be shared is the machinery -- the collection, the
        # transition table and the stages either side of the shared words.
        check("with stages of its own that the internal chain has no notion of",
              {M.ClientReqStatus.NEED_MAPPING.value,
               M.ClientReqStatus.MANPOWER_REQUISITION.value,
               M.ClientReqStatus.PENDING_FEASIBILITY.value}
              .isdisjoint({s.value for s in M.ReqApproval}))
        check("and their own transition table",
              set(M.CLIENT_REQ_TRANSITIONS) & set(M.INTERNAL_REQ_TRANSITIONS) == set())
        check("the internal chain is untouched",
              set(M.INTERNAL_REQ_TRANSITIONS) == {
                  "hr-verify", "hr-reject", "budget-approve", "budget-reject",
                  "escalate-approve", "escalate-reject",
                  "scorecard-approve", "scorecard-reject"})
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 66}\n  {passed}/{total} checks passed\n{'=' * 66}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
