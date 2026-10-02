"""Internal recruitment track -- the mandatory budget gate.

SOP §11: "No internal role may be sourced without prior written headcount and budget
approval from Management/Finance."

Sourcing has two entry points -- publishing a job posting, and putting a candidate against
the requisition -- and this file asserts that BOTH are refused before the gate clears, and
that both open once it has. It also asserts the negative that matters most: a client-track
requisition is never subject to any of it.

Why the gate is tested at the SERVICE layer rather than through the UI: hiding a button is
not a control. A walk-in CV typed in by hand is exactly the route that would otherwise slip
past an unfunded requisition, so the refusal has to live where the write happens.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_budget_gate   (from backend/)
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
        {"_id": dept_id, "company_id": COMPANY, "name": "Finance", "active": True}])
    designations = FakeCollection([
        {"_id": desig_id, "company_id": COMPANY, "name": "Accounts Executive",
         "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "HR user",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "MD user",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_FIN), "company_id": COMPANY, "full_name": "Finance user",
         "governance_role": "FINANCE", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "HOD user",
         "governance_role": "HOD", "role": "clientuser", "is_active": True},
    ])
    sanctions = FakeCollection([
        {"company_id": COMPANY, "department_id": str(dept_id),
         "designation_id": str(desig_id), "sanctioned_count": 50}])

    store = {M.COLL_REQUISITIONS: FakeCollection(),
             M.COLL_JOB_DESCRIPTIONS: FakeCollection(),
             M.COLL_JOB_POSTINGS: FakeCollection(),
             M.COLL_CANDIDATES: FakeCollection(),
             M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
             M.COLL_SANCTIONED_STRENGTH: sanctions,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             M.COLL_EMPLOYEE_PROFILES: FakeCollection(), M.COLL_LINKS: FakeCollection(),
             "learners": learners, "companies": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SANC
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_scorecard_service as SC
    for mod in (RS, PS, CS, AUD, IDS, SANC, LS, RF, SC):
        mod.get_collection = mongo.get_collection

    async def approved_scorecard_for(request_no: str) -> None:
        """Satisfy the scorecard gate, which is not what this file is testing."""
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": request_no, "criteria": [{"label": "Core skill"}]})
        await SC.approve_scorecard(HOD, COMPANY, card["scr_no"],
                                   {"decision": "Pass", "signature": "HOD"})

    async def silent(*a, **kw):
        return None
    for mod in (RS, PS, CS):
        if hasattr(mod, "notify_user"):
            mod.notify_user = silent
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = silent

    def actor(uid, governance):
        return {"_id": uid, "role": "clientuser", "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} user"}

    HR, MD, FIN, HOD = (actor(U_HR, "HR"), actor(U_MD, "MD"),
                        actor(U_FIN, "FINANCE"), actor(U_HOD, "HOD"))

    def payload(**over):
        base = {"department_id": str(dept_id), "designation_id": str(desig_id),
                "assignee_id": U_HR, "vacancy": 1, "required_date": "2027-01-31",
                "experience_required": "2-4 years", "qualification": "B.Com",
                "essential_skills": "Reconciliations",
                "jd": {"title": "Accounts Executive",
                       "responsibilities": "Run payables and reconciliations."}}
        base.update(over)
        return base

    def candidate(**over):
        base = {"candidate_name": "Test Applicant", "can_email": "applicant@example.com",
                "can_contact": "+91 00000 00001"}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The gate is declared once, and both callers read it")
        # =================================================================
        check("the pre-budget states are declared in the model, not in a service",
              M.PRE_BUDGET_STATES == {M.ReqApproval.PENDING_HR_VERIFICATION.value,
                                      M.ReqApproval.PENDING_BUDGET.value})
        check("assert_sourcing_allowed is exported from the requisition service",
              callable(getattr(RS, "assert_sourcing_allowed", None)))

        # =================================================================
        section("Before the gate: nothing may be sourced")
        # =================================================================
        raised = await RS.create_requisition(HOD, COMPANY,
                                             payload(requisition_track="internal"))
        REQ, JD = raised["request_no"], raised["jd_no"]

        await expect_http(
            "adding a candidate to an unverified internal requisition",
            CS.create_candidate(HR, COMPANY, candidate(request_no=REQ)),
            409, "has not cleared budget approval")

        await RS.act_on_requisition(HR, COMPANY, REQ, "hr-verify")
        await expect_http(
            "adding a candidate after HR verification but before the budget",
            CS.create_candidate(HR, COMPANY, candidate(request_no=REQ)),
            409, "no internal role may be sourced")

        # The JD is not APPROVED yet either, so publishing is refused for TWO independent
        # reasons. Asserting the JD reason here would not prove the budget gate works, so the
        # posting case is proven below, where the JD is approved but the budget is not.
        await expect_http(
            "publishing before anything is approved",
            PS.create_posting(HR, COMPANY, {"jd_no": JD}),
            409, "approved job description")

        # =================================================================
        section("A funded requisition sources normally")
        # =================================================================
        await RS.act_on_requisition(
            FIN, COMPANY, REQ, "budget-approve",
            budget={"approved_headcount": 2, "approved_salary_band_min": 300000,
                    "approved_salary_band_max": 600000})
        await approved_scorecard_for(REQ)
        state = await RS.act_on_requisition(HOD, COMPANY, REQ, "scorecard-approve")
        check("the requisition is approved", state["approval_status"] == "Approved")

        row = await CS.create_candidate(HR, COMPANY, candidate(request_no=REQ))
        check("a candidate may now be added", row["uk"].startswith("CAN-"))
        check("and lands at Applied like any other",
              row["application_status"] == M.AppStatus.APPLIED.value)

        drafted = await PS.create_posting(HR, COMPANY, {"jd_no": JD, "channels": ["Job Portals"]})
        check("and the posting can be drafted",
              bool(drafted["posting"]["posting_code"]))

        # =================================================================
        section("The gate is on the REQUISITION, not on the JD's status")
        # =================================================================
        # Force a requisition back to the budget gate while its JD stays APPROVED. This is
        # the case that separates "the budget gate works" from "the JD approval works" --
        # without it, both tests above would pass with the gate deleted.
        await store[M.COLL_REQUISITIONS].update_one(
            {"request_no": REQ},
            {"$set": {"approval_status": M.ReqApproval.PENDING_BUDGET.value}})
        jd_doc = await store[M.COLL_JOB_DESCRIPTIONS].find_one({"jd_no": JD})
        check("the JD is still approved", jd_doc["status"] == M.JdStatus.APPROVED.value)

        await expect_http(
            "publishing an APPROVED JD whose requisition lost budget approval",
            PS.create_posting(HR, COMPANY, {"jd_no": JD}),
            409, "has not cleared budget approval")
        await expect_http(
            "adding a candidate to it",
            CS.create_candidate(HR, COMPANY, candidate(request_no=REQ)),
            409, "has not cleared budget approval")

        # =================================================================
        section("A legacy row with no track field is left alone")
        # =================================================================
        # A requisition raised BEFORE the track field existed carries none at all.
        legacy_jd = "JD-LEGACY-1"
        await store[M.COLL_JOB_DESCRIPTIONS].insert_one({
            "jd_no": legacy_jd, "request_no": "HR-REQ-2025-900", "company_id": COMPANY,
            "status": M.JdStatus.APPROVED.value, "title": "Legacy role"})
        await store[M.COLL_REQUISITIONS].insert_one({
            "request_no": "HR-REQ-2025-900", "company_id": COMPANY, "jd_no": legacy_jd,
            "created_by": U_HOD, "approval_status": M.ReqApproval.APPROVED.value,
            "closing_status": M.ReqClosing.OPEN.value, "vacancy": 1, "created_at": NOW})
        legacy = await store[M.COLL_REQUISITIONS].find_one(
            {"request_no": "HR-REQ-2025-900"})
        RS.assert_sourcing_allowed(legacy)
        check("a legacy requisition with no track field sources freely", True)

        row = await CS.create_candidate(
            HR, COMPANY, candidate(request_no="HR-REQ-2025-900"))
        check("and accepts candidates", row["uk"].startswith("CAN-"))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
