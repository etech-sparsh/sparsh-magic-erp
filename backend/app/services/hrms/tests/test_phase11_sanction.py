"""Phase 11-R Item 7 verification harness -- replacement, sanctioned strength, escalation.

Covers: the replacement cross-field rule, the sanctioned-strength master, DERIVED actual
headcount, the over-sanction arithmetic (including the double-spend guard), the escalation
ladder built from the existing hierarchy resolver, the orphaned-raiser fail-closed path,
and -- the one rule that must never bend -- that MD approval cannot be skipped.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_sanction   (from backend/)
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

    U_HR, U_MD, U_HOD, U_L1, U_L2, U_ORPHAN, U_LEAVER = (str(ObjectId()) for _ in range(7))
    DEPT, DESIG, DESIG2 = str(ObjectId()), str(ObjectId()), str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "is_active": True},
        # HOD reports to L1, who reports to L2 -- a two-rung ladder.
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "governance_role": "HOD", "is_active": True, "reporting_manager": U_L1},
        {"_id": ObjectId(U_L1), "company_id": COMPANY, "full_name": "Leena L1",
         "governance_role": "HOD", "is_active": True, "reporting_manager": U_L2},
        {"_id": ObjectId(U_L2), "company_id": COMPANY, "full_name": "Vikram L2",
         "governance_role": "MD", "is_active": True},
        # Reports to nobody -- the orphaned-raiser case.
        {"_id": ObjectId(U_ORPHAN), "company_id": COMPANY, "full_name": "Omar Orphan",
         "governance_role": "HOD", "is_active": True},
        {"_id": ObjectId(U_LEAVER), "company_id": COMPANY, "full_name": "Leo Leaver",
         "governance_role": "IMPLEMENTOR", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": COMPANY, "name": "Ops", "active": True},
    ])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG), "company_id": COMPANY, "name": "Analyst", "active": True},
        {"_id": ObjectId(DESIG2), "company_id": COMPANY, "name": "Engineer", "active": True},
    ])
    profiles = FakeCollection([
        # Two Analysts on the payroll, one resigned (who must NOT count).
        {"_id": ObjectId(), "company_id": COMPANY, "department_id": DEPT,
         "designation_id": DESIG, "employment_status": "Active"},
        {"_id": ObjectId(), "company_id": COMPANY, "department_id": DEPT,
         "designation_id": DESIG, "employment_status": "On Notice"},
        {"_id": ObjectId(), "company_id": COMPANY, "department_id": DEPT,
         "designation_id": DESIG, "employment_status": "Resigned"},
    ])
    sanctions = FakeCollection()
    reqs = FakeCollection()
    jds = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {"learners": learners, M.COLL_DEPARTMENTS: departments,
             M.COLL_DESIGNATIONS: designations, M.COLL_EMPLOYEE_PROFILES: profiles,
             M.COLL_SANCTIONED_STRENGTH: sanctions, M.COLL_REQUISITIONS: reqs,
             M.COLL_JOB_DESCRIPTIONS: jds, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, "staff": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_sanction_service as SS
    import app.services.hrms_employee_service as ES
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (RS, SS, ES, AUD, IDS):
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
    L1 = {"_id": U_L1, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HOD", "full_name": "Leena L1"}
    ORPHAN = {"_id": U_ORPHAN, "role": "clientuser", "_source_collection": "learners",
              "company_id": COMPANY, "governance_role": "HOD", "full_name": "Omar Orphan"}

    def payload(**over):
        base = {"department_id": DEPT, "designation_id": DESIG, "vacancy": 1,
                "experience_required": "3-5 years", "qualification": "B.Com",
                "essential_skills": "Excel", "required_date": FUTURE,
                "assignee_id": U_HR, "jd": {"responsibilities": "Do the work"}}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The over-sanction arithmetic (pure)")
        # =================================================================
        check("within sanction", M.is_over_sanction(10, 5, 2, 1) is False)
        check("exactly at sanction is NOT over", M.is_over_sanction(10, 7, 2, 1) is False)
        check("one past sanction IS over", M.is_over_sanction(10, 8, 2, 1) is True)
        check("NO sanctioned figure fails CLOSED -- unauthorised headcount is exactly "
              "what should escalate",
              M.is_over_sanction(None, 0, 0, 1) is True)
        check("unreadable input fails closed too",
              M.is_over_sanction("ten", 0, 0, 1) is True)
        check("committed vacancies count -- five requisitions for one seat cannot each "
              "pass independently",
              M.is_over_sanction(5, 4, 1, 1) is True)

        # =================================================================
        section("The sanctioned-strength master")
        # =================================================================
        row = await SS.set_sanction(HR, COMPANY, {
            "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 4})
        check("a figure is stored", row["sanctioned_count"] == 4)
        check("the master names are denormalised",
              row["department_name"] == "Ops" and row["designation_name"] == "Analyst")
        check("ACTUAL is derived from payable employees only (the resigned one is out)",
              row["actual"] == 2)
        check("availability is computed", row["available"] == 2)
        check("it is not over sanction yet", row["is_over_sanction"] is False)

        again = await SS.set_sanction(HR, COMPANY, {
            "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 3})
        check("setting the same position again UPSERTS rather than duplicating",
              len([d for d in sanctions.docs if d["designation_id"] == DESIG]) == 1
              and again["sanctioned_count"] == 3)

        await expect_http("a department from nowhere",
                          SS.set_sanction(HR, COMPANY, {
                              "department_id": str(ObjectId()),
                              "designation_id": DESIG, "sanctioned_count": 1}),
                          422, "Department does not exist")
        await expect_http("a negative count",
                          SS.set_sanction(HR, COMPANY, {
                              "department_id": DEPT, "designation_id": DESIG,
                              "sanctioned_count": -1}),
                          422, "cannot be negative")
        await expect_http("a missing position",
                          SS.set_sanction(HR, COMPANY, {"sanctioned_count": 1}),
                          422, "department and a designation")

        unset = await SS.position_status(COMPANY, DEPT, DESIG2)
        check("a position with NO figure reports has_sanction false",
              unset["has_sanction"] is False)
        check("its availability is None, not a negative number ('we do not know' and "
              "'no room' must not render the same)",
              unset["available"] is None)
        check("and it is over sanction by construction", unset["is_over_sanction"] is True)

        # =================================================================
        section("Replacement")
        # =================================================================
        check("New Position is the default",
              M.RequisitionType.NEW_POSITION.value == "New Position")
        await expect_http("a Replacement naming nobody",
                          RS.create_requisition(HOD, COMPANY, payload(
                              requisition_type="Replacement",
                              replacement_reason="resigned")),
                          422, "Name the employee")
        await expect_http("a Replacement with no reason",
                          RS.create_requisition(HOD, COMPANY, payload(
                              requisition_type="Replacement",
                              replacement_for_user_id=U_LEAVER)),
                          422, "reason for the replacement")
        await expect_http("replacing somebody from another company",
                          RS.create_requisition(HOD, COMPANY, payload(
                              requisition_type="Replacement",
                              replacement_for_user_id=str(ObjectId()),
                              replacement_reason="resigned")),
                          422, "user of this company")
        await expect_http("an unknown requisition type",
                          RS.create_requisition(HOD, COMPANY, payload(
                              requisition_type="Secondment")),
                          422, "Requisition type must be")

        repl = await RS.create_requisition(HOD, COMPANY, payload(
            requisition_type="Replacement", replacement_for_user_id=U_LEAVER,
            replacement_reason="resigned", last_working_day=FUTURE))
        check("a valid replacement is raised",
              repl["requisition_type"] == "Replacement")
        check("the leaver's name is resolved and denormalised",
              repl["replacement_for_name"] == "Leo Leaver")

        await expect_http("an edit that empties out what made it valid",
                          RS.update_requisition(HR, COMPANY, repl["request_no"],
                                                {"replacement_reason": ""}),
                          422, "reason for the replacement")

        plain = await RS.create_requisition(HOD, COMPANY, payload())
        check("an ordinary requisition defaults to New Position",
              plain["requisition_type"] == "New Position")

        # =================================================================
        section("The snapshot is stored so the approver sees the figures they decided on")
        # =================================================================
        snap = plain["sanction_snapshot"]
        check("a snapshot is taken at raise time", snap is not None)
        check("it records the sanctioned figure", snap["sanctioned"] == 3)
        check("it records the actual", snap["actual"] == 2)
        check("it records what was requested", snap["requested"] == 1)
        check("it is stamped", snap["evaluated_at"] is not None)

        # The band Management records at the budget gate -- the step the over-sanction
        # ladder hangs off.
        BAND = {"approved_headcount": 1, "approved_salary_band_min": 500000,
                "approved_salary_band_max": 900000}

        async def to_budget_gate(request_no):
            await RS.act_on_requisition(HR, COMPANY, request_no, "hr-verify")
            return await RS.act_on_requisition(MD, COMPANY, request_no, "budget-approve",
                                               budget=BAND)

        # =================================================================
        section("IN-SANCTION requisitions go straight to the scorecard gate")
        # =================================================================
        await SS.set_sanction(HR, COMPANY, {
            "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 20})
        in_sanction = await RS.create_requisition(HOD, COMPANY, payload())
        check("it is not over sanction",
              in_sanction["sanction_snapshot"]["is_over_sanction"] is False)

        step1 = await RS.act_on_requisition(HR, COMPANY, in_sanction["request_no"],
                                            "hr-verify")
        check("HR verification goes to the budget gate",
              step1["approval_status"] == M.ReqApproval.PENDING_BUDGET.value)
        step2 = await RS.act_on_requisition(MD, COMPANY, in_sanction["request_no"],
                                            "budget-approve", budget=BAND)
        check("budget approval goes STRAIGHT to the scorecard gate",
              step2["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("no escalation chain is built", step2["escalation_chain"] == [])

        # =================================================================
        section("OVER-SANCTION routes through the ladder")
        # =================================================================
        await SS.set_sanction(HR, COMPANY, {
            "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 2})
        over = await RS.create_requisition(HOD, COMPANY, payload())
        check("it is flagged over sanction at raise time",
              over["sanction_snapshot"]["is_over_sanction"] is True)
        check("the raiser is warned immediately, not after HR review",
              any(s[0] == "user" and s[1] == U_HOD and "exceeds" in s[2].lower()
                  for s in sent))
        check("MD is told at raise time as well, WITH the figures",
              any(s[0] == "role" and "MD" in s[1] and "Sanctioned 2" in s[3]
                  for s in sent))

        sent.clear()
        esc = await to_budget_gate(over["request_no"])
        check("budget approval routes to PENDING ESCALATION, not to the scorecard gate",
              esc["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
        chain = esc["escalation_chain"]
        check("the ladder is built from the raiser's reporting line",
              [c["name"] for c in chain] == ["Leena L1", "Vikram L2"])
        check("the raiser is never a rung on their own ladder",
              all(c["user_id"] != U_HOD for c in chain))
        check("it starts at level 1", esc["escalation_level"] == 1)
        check("the rung that holds it is notified",
              any(s[0] == "user" and s[1] == U_L1 for s in sent))
        check("the notification carries the sanction figures",
              any("Sanctioned 2" in s[3] for s in sent if s[0] == "user"))
        check("escalation is audited",
              any(a["action"] == M.AUDIT_REQ_ESCALATED for a in audit_log.docs))

        # A rung that is not yours, and you are not MD.
        await expect_http("a manager clearing somebody else's rung",
                          RS.act_on_requisition(ORPHAN, COMPANY, over["request_no"],
                                                "escalate-approve"),
                          403, "Only they, or the MD")

        mid = await RS.act_on_requisition(L1, COMPANY, over["request_no"],
                                          "escalate-approve", "agreed, we need the head")
        check("clearing rung 1 keeps it IN escalation while rungs remain",
              mid["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
        check("the ladder advances to level 2", mid["escalation_level"] == 2)
        check("rung 1 is marked Approved",
              mid["escalation_chain"][0]["status"] == M.EscalationStatus.APPROVED.value)
        check("who acted and when is recorded",
              mid["escalation_chain"][0]["acted_at"] is not None)
        check("rung 2 is still Pending",
              mid["escalation_chain"][1]["status"] == M.EscalationStatus.PENDING.value)

        sent.clear()
        last = await RS.act_on_requisition(MD, COMPANY, over["request_no"],
                                           "escalate-approve", "approved")
        check("clearing the LAST rung hands over to the scorecard gate -- never straight "
              "to Approved",
              last["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("HR is told the ladder is exhausted",
              any(s[0] == "role" and "HR" in s[1] for s in sent))

        # =================================================================
        section("test_over_sanction_cannot_reach_approved_without_md")
        # =================================================================
        # The named assertion the phase prompt demands, checked three ways.
        check("the budget gate cannot be skipped, asserted from the table",
              M.budget_approval_is_mandatory())
        approving = [a for a, spec in M.INTERNAL_REQ_TRANSITIONS.items()
                     if spec[1] is M.ReqApproval.APPROVED]
        check("no escalation action can result in APPROVED",
              not any(a.startswith("escalate-") for a in approving))

        await SS.set_sanction(HR, COMPANY, {
            "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 2})
        probe = await RS.create_requisition(HOD, COMPANY, payload())
        await to_budget_gate(probe["request_no"])
        await expect_http("approving the scorecard while the requisition is still in escalation",
                          RS.act_on_requisition(MD, COMPANY, probe["request_no"],
                                                "scorecard-approve"),
                          409, "Pending Scorecard Approval")
        stuck = await RS.get_requisition(HR, COMPANY, probe["request_no"])
        check("it is still NOT approved",
              stuck["approval_status"] != M.ReqApproval.APPROVED.value)

        # =================================================================
        section("Escalation rejection")
        # =================================================================
        await expect_http("rejecting an escalation with no reason",
                          RS.act_on_requisition(L1, COMPANY, probe["request_no"],
                                                "escalate-reject"),
                          422, "remark is required")
        rejected = await RS.act_on_requisition(L1, COMPANY, probe["request_no"],
                                               "escalate-reject", "headcount is frozen")
        check("an escalation rejection closes the requisition",
              rejected["approval_status"] == M.ReqApproval.REJECTED.value)
        check("its JD is rejected with it",
              (await jds.find_one({"jd_no": rejected["jd_no"]}))["status"]
              == M.JdStatus.REJECTED.value)
        check("the rung records the rejection",
              rejected["escalation_chain"][0]["status"]
              == M.EscalationStatus.REJECTED.value)

        # =================================================================
        section("An orphaned raiser fails CLOSED -- never auto-approved")
        # =================================================================
        sent.clear()
        orphaned = await RS.create_requisition(ORPHAN, COMPANY, payload())
        routed = await to_budget_gate(orphaned["request_no"])
        check("with no reporting line it routes STRAIGHT TO the scorecard gate",
              routed["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("it is NOT auto-approved",
              routed["approval_status"] != M.ReqApproval.APPROVED.value)
        check("no phantom chain is invented", routed["escalation_chain"] == [])
        check("the gap is recorded in the audit trail, not swallowed",
              any(a["action"] == M.AUDIT_REQ_ESCALATED
                  and "no reporting chain" in (a.get("detail") or "").lower()
                  for a in audit_log.docs))

        # =================================================================
        section("Committed vacancies -- the double-spend guard")
        # =================================================================
        # Nothing above reaches Approved (the scorecard gate is still ahead), so seed one
        # approved, still-open requisition for this position.
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-OPEN", "company_id": COMPANY, "created_by": U_HOD,
            "department_id": DEPT, "designation_id": DESIG, "requisition_track": "internal",
            "approval_status": M.ReqApproval.APPROVED.value,
            "closing_status": M.ReqClosing.OPEN.value, "vacancy": 1})
        live = await SS.position_status(COMPANY, DEPT, DESIG)
        check("approved, still-open requisitions are counted as committed",
              live["open_requisitions"] >= 1)
        excluded = await SS.position_status(COMPANY, DEPT, DESIG,
                                            exclude_request_no="HR-REQ-2026-OPEN")
        check("a requisition is never measured against ITSELF",
              excluded["open_requisitions"] < live["open_requisitions"])

        # =================================================================
        section("Declarations")
        # =================================================================
        check("the ladder is capped", M.MAX_ESCALATION_LEVELS == 5)
        check("escalation routing is declared beside the transition table",
              M.INTERNAL_ESCALATION_ROUTING["budget-approve"]
              is M.ReqApproval.PENDING_ESCALATION)
        check("every action still has an audit label",
              set(M.INTERNAL_REQ_TRANSITIONS) <= set(M.REQ_AUDIT_ACTIONS))
        check("both escalation actions demand the escalate capability",
              all(spec[2] is M.Cap.REQUISITION_ESCALATE
                  for a, spec in M.INTERNAL_REQ_TRANSITIONS.items() if a.startswith("escalate-")))
        check("every reject still demands a remark",
              all(spec[3] for a, spec in M.INTERNAL_REQ_TRANSITIONS.items()
                  if a.endswith("-reject")))
        check("no transition leaves the declared status set",
              all(spec[0] in set(M.ReqApproval) and spec[1] in set(M.ReqApproval)
                  for spec in M.INTERNAL_REQ_TRANSITIONS.values()))

        from app.utils.hrms_access import can
        check("a hiring manager holds the escalate capability -- they ARE the ladder",
              can(HOD, M.Cap.REQUISITION_ESCALATE))
        check("MD holds it too, so a ladder cannot stall on an absent approver",
              can(MD, M.Cap.REQUISITION_ESCALATE))
        check("HR does NOT -- reviewing and escalating in one person is not a control",
              not can(HR, M.Cap.REQUISITION_ESCALATE))
        check("HR still cannot finally approve", not can(HR, M.Cap.REQUISITION_APPROVE_MD))

        idx = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES
               if c == M.COLL_SANCTIONED_STRENGTH]
        check("one figure per position is enforced at the DB level",
              ("hrms_sanctioned_strength", "uniq_company_position") in idx)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
