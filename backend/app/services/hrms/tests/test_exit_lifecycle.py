"""Exit / separation: initiation through closure, and what the last working day triggers.

This module had no test coverage at all. These checks pin the parts most likely to be got
wrong, and the ones just changed:

  * OWNERSHIP. SEPARATION_INITIATE and EXIT_INTERVIEW_SUBMIT are granted to every
    employee so they can resign and complete their own exit interview. Without an
    ownership check those grants also let anybody open a case against a colleague.
  * The LAST WORKING DAY. Access revocation and the F&F used to wait for case closure,
    which sits behind the F&F being paid -- so a leaver's login stayed live for weeks
    after they stopped coming in.
  * BR-025. Exit is not complete until handover and clearance are done or waived, and
    that has to include the laptop and the VPN account, not just the paperwork.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_exit_lifecycle   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print("  " + ("PASS" if condition else "FAIL") + "  " + label)
    return bool(condition)


def section(title: str) -> None:
    print("\n-- " + title + " --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(label + " -> " + str(status), False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(label + " -> " + str(status) + ((" ('" + fragment + "')") if fragment else ""),
              ok)
    except Exception as e:
        check(label + " -> " + str(status) + " (got " + type(e).__name__ + ": " + str(e) + ")",
              False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


def days(n: int) -> str:
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_EMP, U_OTHER = (str(ObjectId()) for _ in range(4))

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": (governance or "Plain") + " user"}

    HR = actor(U_HR, "HR")
    HOD = actor(U_HOD, "HOD")
    EMP = actor(U_EMP, "")          # a plain employee
    OTHER = actor(U_OTHER, "")      # a different plain employee

    profiles = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "employee_code": "EMP-001",
         "user_id": U_EMP, "display_name": "Leaver One", "joined_on": days(-900),
         "reporting_manager_id": U_HOD, "designation_id": None},
        {"_id": ObjectId(), "company_id": COMPANY, "employee_code": "EMP-002",
         "user_id": U_OTHER, "display_name": "Colleague Two", "joined_on": days(-800),
         "reporting_manager_id": U_HOD, "designation_id": None},
    ])
    learners = FakeCollection([
        # `reporting_manager` lives on the LOGIN row, not the HR profile -- that is where
        # _reporting_manager_id reads it from.
        {"_id": ObjectId(U_EMP), "company_id": COMPANY, "is_active": True,
         "reporting_manager": U_HOD},
        {"_id": ObjectId(U_OTHER), "company_id": COMPANY, "is_active": True,
         "reporting_manager": U_HOD},
    ])
    separations = FakeCollection()
    store = {
        M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_SEPARATIONS: separations,
        M.COLL_AUDIT_LOG: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
        "learners": learners, "staff": FakeCollection(),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_exit_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (EX, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent: list = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", ",".join(roles), title))

    import app.services.hrms_notify_service as NOT
    NOT.notify_user = fake_notify_user
    NOT.notify_hrms_role = fake_notify_role

    async def no_forfeit(company_id, employee_code, sep_no):
        return None
    import app.services.hrms_variable_pay_service as VP
    VP.forfeit_holds_for_separation = no_forfeit

    async def no_update_profile(actor_, user_id, payload, company_id):
        return None
    import app.services.hrms_employee_service as ES
    ES.update_profile = no_update_profile

    # The shared FakeCollection has no sorted find_one, and probation state is not what
    # this suite is about -- nobody here is on probation.
    async def not_on_probation(company_id, employee_code):
        return False
    EX._is_on_probation = not_on_probation

    try:
        # =================================================================
        section("An employee resigns for THEMSELVES, and nobody else")
        # =================================================================
        await expect_http(
            "an employee opening a case against a colleague",
            EX.initiate_separation(EMP, COMPANY, {
                "employee_code": "EMP-002", "exit_type": "Resignation",
                "resignation_date": days(0)}),
            403, "your own employment record")

        own = await EX.initiate_separation(EMP, COMPANY, {
            "employee_code": "EMP-001", "exit_type": "Resignation",
            "resignation_date": days(0), "reason": "Relocating."})
        SEP = own["sep_no"]
        check("an employee can resign for themselves", SEP.startswith("SEP-"))
        check("the notice obligation is calculated, not typed",
              own["calculated_notice_days"] > 0 and own["calculated_lwd"] > days(0))
        check("it explains what the calculation rests on", bool(own.get("notice_basis")))

        check("the reporting manager is told -- step 2 of the workflow",
              any(kind == "user" and uid == U_HOD and "resigned" in title.lower()
                  for kind, uid, title in sent))
        check("and HR is told, so the retention conversation can start",
              any(kind == "role" and "HR" in uid for kind, uid, title in sent))

        # HR is not restricted to their own record.
        hr_case = await EX.initiate_separation(HR, COMPANY, {
            "employee_code": "EMP-002", "exit_type": "Termination",
            "resignation_date": days(0), "reason": "Conduct."})
        check("HR raises a case for anybody", hr_case["sep_no"] != SEP)

        # =================================================================
        section("The exit interview is the leaver's own too")
        # =================================================================
        await expect_http(
            "an employee writing somebody else's exit interview",
            EX.save_exit_interview(OTHER, COMPANY, SEP, {"reason": "nosy"}),
            403, "your own employment record")
        saved = await EX.save_exit_interview(EMP, COMPANY, SEP, {
            "reason": "Relocating.", "rehire_recommended": True})
        check("the leaver completes their own", saved is not None)

        # =================================================================
        section("BR-025: closure waits for the laptop and the VPN too")
        # =================================================================
        await EX.decide_separation(HR, COMPANY, SEP, {
            "accepted": True, "recommended_lwd": own["calculated_lwd"]})
        sep_now = await separations.find_one({"sep_no": SEP})
        check("accepting sets the final last working day",
              sep_now.get("final_lwd") == own["calculated_lwd"])

        await EX.create_asset_return(HR, COMPANY, SEP, {"description": "Laptop", "category": "IT"})
        await EX.create_access_clearance(HR, COMPANY, SEP,
                                         {"system_type": "VPN", "description": "Corp VPN"})
        # Satisfy everything the gate used to check, and nothing it did not.
        for t in await EX.list_clearance_tasks(HR, COMPANY, SEP):
            await EX.act_on_clearance_task(HR, COMPANY, SEP, t["id"],
                                           {"status": "Waived", "remarks": "n/a"})
        await store[M.COLL_FNF_SETTLEMENTS].insert_one(
            {"company_id": COMPANY, "sep_no": SEP, "status": M.FnfStatus.PAID.value})

        await expect_http(
            "closing with a laptop still out",
            EX.close_separation(HR, COMPANY, SEP), 409, "not yet returned")

        for a in await EX.list_asset_returns(HR, COMPANY, SEP):
            await EX.update_asset_return(HR, COMPANY, SEP, a["ast_no"],
                                         {"status": "Returned"})
        await expect_http(
            "closing with a live VPN account",
            EX.close_separation(HR, COMPANY, SEP), 409, "not yet disabled")

        await expect_http(
            "forcing a closure without saying why",
            EX.close_separation(HR, COMPANY, SEP, force=True),
            422, "Say why")

        for i in await EX.list_access_clearances(HR, COMPANY, SEP):
            await EX.update_access_clearance(HR, COMPANY, SEP, i["id"],
                                             {"status": "Disabled"})

        # =================================================================
        section("The last working day triggers its own work")
        # =================================================================
        # Put the LWD in the past so the sweep sees it, as it would the morning after.
        await separations.update_one({"sep_no": SEP},
                                     {"$set": {"final_lwd": days(-1)}})
        await store[M.COLL_FNF_SETTLEMENTS].delete_one({"sep_no": SEP})

        out = await EX.run_lwd_sweep(COMPANY)
        check("the sweep picks up a case whose last day has passed", out["checked"] >= 1)
        check("the login is deactivated ON the last day, not at closure",
              out["access_revoked"] >= 1
              and (await learners.find_one({"_id": ObjectId(U_EMP)}))["is_active"] is False)
        check("and the F&F is opened so Finance is not waiting to be asked",
              out["fnf_opened"] >= 1)
        check("HR is told the day has arrived",
              any(kind == "role" and "last working day" in title.lower()
                  for kind, uid, title in sent))

        again = await EX.run_lwd_sweep(COMPANY)
        check("a second run does nothing -- the case is stamped as processed",
              again["checked"] == 0)

        # =================================================================
        section("Closure archives them to alumni")
        # =================================================================
        await store[M.COLL_FNF_SETTLEMENTS].update_one(
            {"sep_no": SEP}, {"$set": {"status": M.FnfStatus.PAID.value}})
        closed = await EX.close_separation(HR, COMPANY, SEP)
        check("the case closes once everything is done",
              closed["stage"] == M.SeparationStage.CLOSED.value)

        alumni = await EX.list_alumni(HR, COMPANY)
        row = next((a for a in alumni["alumni"] if a["employee_code"] == "EMP-001"), None)
        check("the leaver is written to the alumni archive", row is not None)
        check("with the one judgement worth keeping -- would we rehire them",
              row and row.get("rehire_recommended") is True)
        check("and their last working day", row and row.get("last_working_day") == days(-1))
        check("the archive does NOT copy their salary or the interview verbatim",
              row is not None and "base_salary" not in row and "reason" not in row)

        rehire = await EX.list_alumni(HR, COMPANY, rehire_only=True)
        check("the archive can be filtered to rehirable leavers",
              all(a.get("rehire_recommended") for a in rehire["alumni"]))

    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print("\n" + "=" * 60)
    print("  " + str(passed) + "/" + str(total) + " checks passed")
    print("=" * 60)
    raise SystemExit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
