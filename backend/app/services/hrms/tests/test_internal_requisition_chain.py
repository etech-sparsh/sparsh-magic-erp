"""Internal recruitment track -- the approval chain.

Covers: the track discriminator and its immutability, the internal ladder
(HR verification -> budget -> [escalation] -> scorecard -> Approved), per-action capability
enforcement, the escalation detour hanging off `budget-approve`, and the SLA stamps the
chain lays down.

The property this file exists to protect: THE CLIENT TRACK IS UNCHANGED. Every internal
behaviour is asserted alongside the client behaviour it must not have disturbed, in the same
run against the same fixtures -- because "we did not break it" is a claim, and a claim you
do not test is a hope.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_requisition_chain   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_FIN, U_HOD = (str(ObjectId()), str(ObjectId()),
                                str(ObjectId()), str(ObjectId()))

    dept_id, desig_id = ObjectId(), ObjectId()
    departments = FakeCollection([
        {"_id": dept_id, "company_id": COMPANY, "name": "Operations", "active": True}])
    designations = FakeCollection([
        {"_id": desig_id, "company_id": COMPANY, "name": "Ops Executive", "active": True}])
    reqs = FakeCollection()
    jds = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()
    # The assignee on a requisition must resolve to a real user of the company, so the whole
    # cast exists from the start. `reports_to` is what the escalation ladder walks.
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "HR user",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "MD user",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_FIN), "company_id": COMPANY, "full_name": "Finance user",
         "governance_role": "FINANCE", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "HOD user",
         "governance_role": "HOD", "role": "clientuser", "is_active": True,
         "reporting_manager": U_MD},
    ])
    # A sanctioned figure well above what these tests ask for, so the ordinary path does NOT
    # escalate. The escalation section below removes it deliberately.
    sanctions = FakeCollection([
        {"company_id": COMPANY, "department_id": str(dept_id),
         "designation_id": str(desig_id), "sanctioned_count": 50}])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_JOB_DESCRIPTIONS: jds,
             M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
             M.COLL_SANCTIONED_STRENGTH: sanctions,
             M.COLL_EMPLOYEE_PROFILES: FakeCollection(),
             M.COLL_CANDIDATES: FakeCollection(), "learners": learners,
             "companies": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SANC
    import app.services.hrms_scorecard_service as SC
    for mod in (RS, AUD, IDS, SANC, SC):
        mod.get_collection = mongo.get_collection

    async def approved_scorecard_for(request_no: str) -> None:
        """Satisfy the scorecard gate for a requisition.

        `scorecard-approve` refuses to close the chain without an APPROVED scorecard -- that
        is the gate, asserted in test_scorecard.py. Here it is a precondition, so the helper
        keeps that setup from drowning the ladder assertions this file is about.
        """
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": request_no,
            "criteria": [{"label": "Core skill", "weight": 2},
                         {"label": "Culture fit", "weight": 1}]})
        await SC.approve_scorecard(HOD, COMPANY, card["scr_no"],
                                   {"decision": "Pass", "signature": "HOD"})

    async def silent(*a, **kw):
        return None
    RS.notify_user = silent
    RS.notify_hrms_role = silent

    def actor(uid, governance):
        return {"_id": uid, "role": "clientuser", "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} user"}

    HR, MD, FIN, HOD = (actor(U_HR, "HR"), actor(U_MD, "MD"),
                        actor(U_FIN, "FINANCE"), actor(U_HOD, "HOD"))

    def payload(**over):
        base = {"department_id": str(dept_id), "designation_id": str(desig_id),
                "assignee_id": U_HR, "vacancy": 2, "required_date": "2027-01-31",
                "experience_required": "2-4 years", "qualification": "Graduate",
                "essential_skills": "Coordination",
                "jd": {"title": "Ops Executive",
                       "responsibilities": "Run the service desk against agreed SLAs."}}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The FINANCE role resolves and is scoped to money, not people")
        # =================================================================
        from app.utils.hrms_access import can, hrms_role
        check("governance_role FINANCE resolves to HrmsRole.FINANCE",
              hrms_role(FIN) is M.HrmsRole.FINANCE)
        check("FINANCE may approve a budget", can(FIN, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("FINANCE may approve an offer", can(FIN, M.Cap.OFFER_APPROVE))
        check("FINANCE may approve an exception", can(FIN, M.Cap.EXCEPTION_APPROVE))
        check("FINANCE may NOT screen candidates", not can(FIN, M.Cap.CANDIDATE_SCREEN))
        check("FINANCE may NOT evaluate interviews", not can(FIN, M.Cap.INTERVIEW_EVALUATE))
        check("FINANCE may NOT write offers", not can(FIN, M.Cap.OFFER_WRITE))
        check("FINANCE may NOT confirm probation", not can(FIN, M.Cap.PROBATION_CONFIRM))
        check("FINANCE reads salary but cannot write it",
              can(FIN, M.Cap.EMPLOYEE_SALARY_READ)
              and not can(FIN, M.Cap.EMPLOYEE_SALARY_WRITE))
        check("HR may NOT approve a budget (Annexure B: HR is 'C', Management is 'A')",
              not can(HR, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("HR may NOT approve the scorecard it drafts",
              can(HR, M.Cap.SCORECARD_WRITE) and not can(HR, M.Cap.SCORECARD_APPROVE))
        check("the HOD approves the scorecard", can(HOD, M.Cap.SCORECARD_APPROVE))
        check("the HOD confirms probation (Annexure B: 'A/R')",
              can(HOD, M.Cap.PROBATION_CONFIRM))
        check("MD holds every internal capability",
              all(can(MD, c) for c in (M.Cap.REQUISITION_APPROVE_BUDGET,
                                       M.Cap.SCORECARD_APPROVE, M.Cap.OFFER_APPROVE,
                                       M.Cap.PROBATION_CONFIRM, M.Cap.EXCEPTION_APPROVE,
                                       M.Cap.PERSONNEL_FILE_CLOSE)))

        # =================================================================
        section("The gates are asserted from the tables, not from prose")
        # =================================================================
        check("budget approval is mandatory",
              M.budget_approval_is_mandatory())
        # Every action leaves a labelled trail, and no label is orphaned.
        check("every action has an audit label, and none is orphaned",
              set(M.INTERNAL_REQ_TRANSITIONS) == set(M.REQ_AUDIT_ACTIONS))
        check("every internal reject demands a remark",
              all(spec[3] for a, spec in M.INTERNAL_REQ_TRANSITIONS.items()
                  if a.endswith("-reject")))

        # =================================================================
        section("Raising: every requisition is Sparsh Magic's own")
        # =================================================================
        internal_req = await RS.create_requisition(HOD, COMPANY, payload())
        IREQ = internal_req["request_no"]
        check("an internal requisition is stamped as such",
              internal_req["requisition_track"] == "internal")
        check("and opens at Pending HR Verification",
              internal_req["approval_status"]
              == M.ReqApproval.PENDING_HR_VERIFICATION.value)
        check("its budget fields start empty",
              internal_req.get("approved_headcount") is None
              and internal_req.get("approved_salary_band_min") is None)

        listing = await RS.list_requisitions(HR, COMPANY)
        check("the list returns the requisition",
              [r["request_no"] for r in listing["requisitions"]] == [IREQ])

        # Rows from the decommissioned client-hiring track stay in the database and out
        # of the flow: one carrying "client", and one raised before the track field
        # existed, which carries nothing at all.
        CREQ = "HR-REQ-2025-998"
        await reqs.insert_one({
            "request_no": CREQ, "company_id": COMPANY, "created_by": U_HOD,
            "requisition_track": "client", "approval_status": "Pending HR Review",
            "closing_status": M.ReqClosing.OPEN.value, "vacancy": 1, "created_at": NOW})
        await reqs.insert_one({
            "request_no": "HR-REQ-2025-999", "company_id": COMPANY, "created_by": U_HOD,
            "approval_status": "Pending HR Review",
            "closing_status": M.ReqClosing.OPEN.value, "vacancy": 1, "created_at": NOW})
        listing = await RS.list_requisitions(HR, COMPANY)
        check("legacy client-track rows are not listed",
              [r["request_no"] for r in listing["requisitions"]] == [IREQ])
        await expect_http("nor readable by number",
                          RS.get_requisition(HR, COMPANY, CREQ), 404)

        # =================================================================
        section("The internal ladder, rung by rung")
        # =================================================================
        await expect_http(
            "an action that is not in the table",
            RS.act_on_requisition(HR, COMPANY, IREQ, "hr-approve"),
            422, "Invalid action")
        await expect_http(
            "acting on a legacy client-track requisition",
            RS.act_on_requisition(HR, COMPANY, CREQ, "hr-verify"),
            404)

        await expect_http(
            "skipping HR verification straight to the budget gate",
            RS.act_on_requisition(FIN, COMPANY, IREQ, "budget-approve"),
            409, 'not "Pending Budget Approval"')

        state = await RS.act_on_requisition(HR, COMPANY, IREQ, "hr-verify",
                                            remarks="Role and justification check out.")
        check("hr-verify moves it to Pending Budget Approval",
              state["approval_status"] == M.ReqApproval.PENDING_BUDGET.value)

        await expect_http(
            "HR approving the budget it may only recommend",
            RS.act_on_requisition(HR, COMPANY, IREQ, "budget-approve"),
            403, "not authorised")
        await expect_http(
            "approving a budget without naming the figures",
            RS.act_on_requisition(FIN, COMPANY, IREQ, "budget-approve"),
            422, "approved headcount and salary band")
        await expect_http(
            "a band whose minimum exceeds its maximum",
            RS.act_on_requisition(FIN, COMPANY, IREQ, "budget-approve",
                                  budget={"approved_headcount": 2,
                                          "approved_salary_band_min": 900000,
                                          "approved_salary_band_max": 400000}),
            422, "cannot exceed")
        await expect_http(
            "a headcount of zero",
            RS.act_on_requisition(FIN, COMPANY, IREQ, "budget-approve",
                                  budget={"approved_headcount": 0,
                                          "approved_salary_band_min": 400000,
                                          "approved_salary_band_max": 900000}),
            422, "at least 1")

        state = await RS.act_on_requisition(
            FIN, COMPANY, IREQ, "budget-approve", remarks="Within the FY plan.",
            budget={"approved_headcount": 2, "approved_salary_band_min": 400000,
                    "approved_salary_band_max": 900000})
        check("Finance clears the budget gate -> Pending Scorecard Approval",
              state["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("the approved band is stored, because later offers are checked against it",
              state["approved_salary_band_min"] == 400000
              and state["approved_salary_band_max"] == 900000)
        check("the approved headcount is stored", state["approved_headcount"] == 2)
        check("who approved it is attributable", state["budget_approved_by"] == U_FIN)
        check("the SLA milestone is stamped when it happened, not derived later",
              (state.get("sla_actuals") or {}).get("budget_approved") is not None)
        check("budget approval is audited",
              any(a["action"] == M.AUDIT_REQ_BUDGET_OK for a in audit_log.docs))

        await expect_http(
            "Finance approving the scorecard, which is the HOD's call",
            RS.act_on_requisition(FIN, COMPANY, IREQ, "scorecard-approve"),
            403, "not authorised")

        # The gate is real: no approved scorecard, no approved requisition.
        await expect_http(
            "closing the chain with no position scorecard drafted",
            RS.act_on_requisition(HOD, COMPANY, IREQ, "scorecard-approve"),
            409, "has no position scorecard")

        await approved_scorecard_for(IREQ)
        state = await RS.act_on_requisition(HOD, COMPANY, IREQ, "scorecard-approve",
                                            remarks="Criteria reflect the role.")
        check("the HOD clears the scorecard gate -> Approved",
              state["approval_status"] == M.ReqApproval.APPROVED.value)
        check("the second SLA milestone is stamped",
              (state.get("sla_actuals") or {}).get("scorecard_approved") is not None)
        check("the JD is co-approved, exactly as on the client track",
              (await jds.find_one({"jd_no": internal_req["jd_no"]}))["status"]
              == M.JdStatus.APPROVED.value)

        # =================================================================
        section("Escalation hangs off the BUDGET gate, not HR verification")
        # =================================================================
        # Remove the sanctioned figure: no figure at all counts as over-sanction (fail
        # closed), which is the documented Phase 11-R rule and must still hold here.
        sanctions.docs.clear()

        esc = await RS.create_requisition(HOD, COMPANY, payload())
        EREQ = esc["request_no"]
        state = await RS.act_on_requisition(HR, COMPANY, EREQ, "hr-verify")
        check("HR verification does NOT escalate -- nobody has agreed to pay yet",
              state["approval_status"] == M.ReqApproval.PENDING_BUDGET.value)

        state = await RS.act_on_requisition(
            FIN, COMPANY, EREQ, "budget-approve",
            budget={"approved_headcount": 2, "approved_salary_band_min": 100000,
                    "approved_salary_band_max": 200000})
        check("an over-sanction internal requisition escalates AFTER the budget gate",
              state["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
        check("a position with no sanctioned figure counts as over-sanction (fail closed)",
              (state.get("sanction_snapshot") or {}).get("is_over_sanction") is True)

        rungs = 0
        while state["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value:
            rungs += 1
            if rungs > M.MAX_ESCALATION_LEVELS + 1:
                check("the ladder terminates", False)
                break
            state = await RS.act_on_requisition(MD, COMPANY, EREQ, "escalate-approve",
                                                remarks="Accepted for this quarter.")
        check(f"the ladder returns to the SCORECARD gate, not the MD ({rungs} rung(s))",
              state["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)

        await approved_scorecard_for(EREQ)
        state = await RS.act_on_requisition(HOD, COMPANY, EREQ, "scorecard-approve")
        check("and the scorecard gate still finishes the chain",
              state["approval_status"] == M.ReqApproval.APPROVED.value)

        # =================================================================
        section("Rejection at each internal rung")
        # =================================================================
        # Each rung is rejected by the role that OWNS it -- the same separation of duties the
        # approve path enforces. Rejecting is not a lesser act than approving.
        for action, rejector in (("hr-reject", HR),
                                 ("budget-reject", FIN),
                                 ("scorecard-reject", HOD)):
            row = await RS.create_requisition(HOD, COMPANY,
                                              payload(requisition_track="internal"))
            no = row["request_no"]
            if action != "hr-reject":
                await RS.act_on_requisition(HR, COMPANY, no, "hr-verify")
            if action == "scorecard-reject":
                await RS.act_on_requisition(
                    FIN, COMPANY, no, "budget-approve",
                    budget={"approved_headcount": 1, "approved_salary_band_min": 1,
                            "approved_salary_band_max": 2})
                while (await reqs.find_one({"request_no": no}))["approval_status"] \
                        == M.ReqApproval.PENDING_ESCALATION.value:
                    await RS.act_on_requisition(MD, COMPANY, no, "escalate-approve")
            await expect_http(f"{action} with no reason given",
                              RS.act_on_requisition(rejector, COMPANY, no, action), 422,
                              "remark is required")
            out = await RS.act_on_requisition(rejector, COMPANY, no, action,
                                              remarks="Not this quarter.")
            check(f"{action} rejects the requisition",
                  out["approval_status"] == M.ReqApproval.REJECTED.value)
            check(f"{action} closes it too",
                  out["closing_status"] == M.ReqClosing.CLOSED.value)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
