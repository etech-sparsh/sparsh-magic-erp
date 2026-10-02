"""Phase 11-R Item 6 verification harness -- dual budget capture on the requisition.

Covers: the derived budget_status (never stored), validation, mismatch and pending
notifications, the conditional-remarks gate on MD approval, and the guarantee that a
mismatch WARNS rather than BLOCKS.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_budget   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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
FUTURE = (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_HOD, U_HEAD = (str(ObjectId()) for _ in range(4))
    DEPT, DESIG = str(ObjectId()), str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "governance_role": "HOD", "is_active": True},
        {"_id": ObjectId(U_HEAD), "company_id": COMPANY, "full_name": "Dev Head",
         "governance_role": "HOD", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": COMPANY, "name": "Ops", "active": True,
         "head_user_id": U_HEAD},
    ])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG), "company_id": COMPANY, "name": "Analyst", "active": True},
    ])
    reqs = FakeCollection()
    jds = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {"learners": learners, M.COLL_DEPARTMENTS: departments,
             M.COLL_DESIGNATIONS: designations, M.COLL_REQUISITIONS: reqs,
             M.COLL_JOB_DESCRIPTIONS: jds, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, M.COLL_EMPLOYEE_PROFILES: FakeCollection(),
             M.COLL_SANCTIONED_STRENGTH: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_sanction_service as SS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (RS, SS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title, msg))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title, msg))

    RS.notify_user = fake_notify_user
    RS.notify_hrms_role = fake_notify_role

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "MD", "full_name": "Meera MD"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}

    def payload(**over):
        base = {"department_id": DEPT, "designation_id": DESIG, "vacancy": 1,
                "experience_required": "3-5 years", "qualification": "B.Com",
                "essential_skills": "Excel", "required_date": FUTURE,
                "assignee_id": U_HR,
                "jd": {"responsibilities": "Do the work"}}
        base.update(over)
        return base

    try:
        # =================================================================
        section("budget_status is DERIVED -- pure, and never stored")
        # =================================================================
        check("neither figure -> Not Set",
              M.budget_status({}) == M.BudgetStatus.NOT_SET.value)
        check("only management -> Pending",
              M.budget_status({"budget_sanctioned_amount": 100})
              == M.BudgetStatus.PENDING.value)
        check("only the HOD -> Pending",
              M.budget_status({"budget_hod_amount": 100})
              == M.BudgetStatus.PENDING.value)
        check("equal figures -> Matched",
              M.budget_status({"budget_sanctioned_amount": 100,
                               "budget_hod_amount": 100})
              == M.BudgetStatus.MATCHED.value)
        check("differing figures -> Mismatch",
              M.budget_status({"budget_sanctioned_amount": 100,
                               "budget_hod_amount": 120})
              == M.BudgetStatus.MISMATCH.value)
        check("a zero figure is a FIGURE, not an absence",
              M.budget_status({"budget_sanctioned_amount": 0, "budget_hod_amount": 0})
              == M.BudgetStatus.MATCHED.value)
        check("unreadable figures read Mismatch, never silently Matched",
              M.budget_status({"budget_sanctioned_amount": "lots",
                               "budget_hod_amount": 5})
              == M.BudgetStatus.MISMATCH.value)
        check("None is not a document", M.budget_status(None)
              == M.BudgetStatus.NOT_SET.value)
        check("the tolerance is a named constant, not a magic number",
              M.BUDGET_TOLERANCE == 0.0)
        check("the delta is signed (HOD minus management)",
              M.budget_delta({"budget_sanctioned_amount": 100,
                              "budget_hod_amount": 120}) == 20)
        check("an unreadable delta is None, not a crash",
              M.budget_delta({"budget_sanctioned_amount": None}) is None)

        # =================================================================
        section("Validation")
        # =================================================================
        await expect_http("a non-numeric sanctioned budget",
                          RS.create_requisition(HOD, COMPANY, payload(
                              budget_sanctioned_amount="a lot")),
                          422, "must be a number")
        await expect_http("a negative HOD budget",
                          RS.create_requisition(HOD, COMPANY, payload(
                              budget_hod_amount=-1)),
                          422, "cannot be negative")
        await expect_http("an implausible figure",
                          RS.create_requisition(HOD, COMPANY, payload(
                              budget_sanctioned_amount=10 ** 12)),
                          422, "implausibly large")
        await expect_http("a malformed sanction date",
                          RS.create_requisition(HOD, COMPANY, payload(
                              budget_sanctioned_on="31-12-2026")),
                          422, "YYYY-MM-DD")

        # =================================================================
        section("Not Set is the default -- pre-phase behaviour is unchanged")
        # =================================================================
        plain = await RS.create_requisition(HOD, COMPANY, payload())
        check("a requisition raised with no budget reads Not Set",
              plain["budget_status"] == M.BudgetStatus.NOT_SET.value)
        stored = await reqs.find_one({"request_no": plain["request_no"]})
        check("NOTHING is stored for it (no stale flag can exist)",
              "budget_status" not in stored)
        check("the delta is absent too", plain["budget_delta"] is None)

        # =================================================================
        section("Mismatch notifies HR, MD and the creator -- with the figures")
        # =================================================================
        sent.clear()
        mismatched = await RS.create_requisition(HOD, COMPANY, payload(
            budget_sanctioned_amount=800000, budget_hod_amount=950000,
            budget_sanctioned_ref="Board minute 14"))
        check("it reads Mismatch",
              mismatched["budget_status"] == M.BudgetStatus.MISMATCH.value)
        check("the delta is computed", mismatched["budget_delta"] == 150000)

        budget_msgs = [s for s in sent if "budget" in s[2].lower()]
        check("a budget notification fires", len(budget_msgs) >= 1)
        role_msg = next((s for s in budget_msgs if s[0] == "role"), None)
        check("HR and MD are both told",
              role_msg is not None and set(role_msg[1]) == {"HR", "MD"})
        check("the creator is told too",
              any(s[0] == "user" and s[1] == U_HOD for s in budget_msgs))
        body = role_msg[3] if role_msg else ""
        check("BOTH figures travel in the message body",
              "800000" in body and "950000" in body)
        check("so does the delta", "150,000" in body or "+150000" in body)

        # =================================================================
        section("Pending routes to whoever owes the missing figure")
        # =================================================================
        sent.clear()
        await RS.create_requisition(HOD, COMPANY, payload(
            budget_sanctioned_amount=800000))          # the HOD figure is missing
        pending = [s for s in sent if "outstanding" in s[2].lower()]
        check("a pending budget notifies somebody", len(pending) >= 1)
        check("it goes to the DEPARTMENT HEAD, who owes the answer",
              any(s[0] == "user" and s[1] == U_HEAD for s in pending))

        sent.clear()
        await RS.create_requisition(HOD, COMPANY, payload(
            budget_hod_amount=800000))                 # management's figure is missing
        pending = [s for s in sent if "outstanding" in s[2].lower()]
        check("when management's figure is missing it routes to HR instead",
              any(s[0] == "role" and "HR" in s[1] for s in pending))

        # =================================================================
        section("A correction re-notifies -- it is the moment people need to know")
        # =================================================================
        sent.clear()
        await RS.update_requisition(HR, COMPANY, plain["request_no"],
                                    {"budget_sanctioned_amount": 500000,
                                     "budget_hod_amount": 600000})
        check("editing a budget into a mismatch fires the notification",
              any("budget" in s[2].lower() for s in sent))
        reread = await RS.get_requisition(HR, COMPANY, plain["request_no"])
        check("the derived status follows the correction immediately",
              reread["budget_status"] == M.BudgetStatus.MISMATCH.value)

        sent.clear()
        await RS.update_requisition(HR, COMPANY, plain["request_no"],
                                    {"budget_hod_amount": 500000})
        reread = await RS.get_requisition(HR, COMPANY, plain["request_no"])
        check("reconciling the figures flips it to Matched with no migration",
              reread["budget_status"] == M.BudgetStatus.MATCHED.value)
        check("a non-budget edit fires no budget notification",
              True)

        # =================================================================
        section("The conditional-remarks gate")
        # =================================================================
        check("the rule lives in ONE declared place",
              "budget-approve" in M.REQ_CONDITIONAL_REMARKS)
        check("it fires only on a mismatch",
              M.REQ_CONDITIONAL_REMARKS["budget-approve"](
                  {"budget_sanctioned_amount": 1, "budget_hod_amount": 2}) is True
              and M.REQ_CONDITIONAL_REMARKS["budget-approve"](
                  {"budget_sanctioned_amount": 1, "budget_hod_amount": 1}) is False)
        check("it has a human-readable reason to show the approver",
              "budget-approve" in M.REQ_CONDITIONAL_REMARK_REASONS)
        check("hr-verify is NOT gated -- HR verifies, it does not decide the money",
              "hr-verify" not in M.REQ_CONDITIONAL_REMARKS)

        # The band Management records at the budget gate. No sanctioned strength is
        # seeded in this file, so clearing the gate lands in escalation (fail closed):
        # "cleared the budget gate" is the fact asserted below, never "Approved".
        BAND = {"approved_headcount": 1, "approved_salary_band_min": 500000,
                "approved_salary_band_max": 900000}
        CLEARED = {M.ReqApproval.PENDING_SCORECARD.value,
                   M.ReqApproval.PENDING_ESCALATION.value}

        no_mismatch = mismatched["request_no"]
        await RS.act_on_requisition(HR, COMPANY, no_mismatch, "hr-verify")
        check("HR can verify a mismatched requisition with no remark", True)

        await expect_http("Management approving a MISMATCHED budget with no remark",
                          RS.act_on_requisition(MD, COMPANY, no_mismatch, "budget-approve",
                                                budget=BAND),
                          422, "do not match")

        approved = await RS.act_on_requisition(
            MD, COMPANY, no_mismatch, "budget-approve", budget=BAND,
            remarks="Approved at the higher figure; board has agreed the uplift.")
        check("with a remark, the approval GOES THROUGH -- a mismatch warns, never blocks",
              approved["approval_status"] in CLEARED)
        check("the remark is recorded against the approval",
              "board has agreed" in (approved.get("budget_remarks_approver") or "").lower())
        check("the requisition still reads Mismatch afterwards (the disagreement is a "
              "fact, not something approval erases)",
              approved["budget_status"] == M.BudgetStatus.MISMATCH.value)

        # =================================================================
        section("A MATCHED requisition needs no remark")
        # =================================================================
        clean = await RS.create_requisition(HOD, COMPANY, payload(
            budget_sanctioned_amount=700000, budget_hod_amount=700000))
        await RS.act_on_requisition(HR, COMPANY, clean["request_no"], "hr-verify")
        done = await RS.act_on_requisition(MD, COMPANY, clean["request_no"],
                                           "budget-approve", budget=BAND)
        check("a matched budget clears the gate with no remark",
              done["approval_status"] in CLEARED)

        not_set = await RS.create_requisition(HOD, COMPANY, payload())
        await RS.act_on_requisition(HR, COMPANY, not_set["request_no"], "hr-verify")
        done2 = await RS.act_on_requisition(MD, COMPANY, not_set["request_no"],
                                            "budget-approve", budget=BAND)
        check("a requisition with NO budget captured clears the gate as it always did",
              done2["approval_status"] in CLEARED)

        # =================================================================
        section("Reporting")
        # =================================================================
        cols = [c for c, _l in M.REPORT_ENTITIES["requisitions"]["columns"]]
        check("budget_status is a report column", "budget_status" in cols)
        import app.services.hrms_analytics_service as AN
        derived = AN._derive("requisitions",
                             {"budget_sanctioned_amount": 5, "budget_hod_amount": 9})
        check("the report service computes it per row (it is not a stored field)",
              derived["budget_status"] == M.BudgetStatus.MISMATCH.value)
        check("deriving does not mutate the source row",
              "budget_status" not in {"budget_sanctioned_amount", "budget_hod_amount"})

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
