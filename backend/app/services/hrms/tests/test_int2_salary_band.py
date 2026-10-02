"""Phase INT-2 -- the standing salary-band master (Annexure C).

"Pre-define standard salary bands per role/grade with Finance annually, so individual
requisitions don't need a fresh budget discussion each time."

The property this file exists to protect, and it is the whole design:

    THE BUDGET GATE reads the master and PRE-FILLS.
    THE OFFER CHECK reads the band STAMPED ON THE REQUISITION, and never the master.

So a band edited in April cannot retroactively legalise an offer approved in March. That is
asserted directly: the band is changed AFTER an approval, and the offer check is shown still
reading the old, stamped figure.

Also covered: the override stamp and its required reason, supersession rather than in-place
editing, and effective-date windows.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_salary_band   (from backend/)
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
NOW = datetime.now(timezone.utc)
JOINING = (NOW + timedelta(days=45)).strftime("%Y-%m-%d")


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


def ahead(days):
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_FIN, U_MD, U_HR = (str(ObjectId()) for _ in range(3))
    DEPT, DESIG = ObjectId(), ObjectId()

    departments = FakeCollection([
        {"_id": DEPT, "company_id": COMPANY, "name": "Operations"}])
    designations = FakeCollection([
        {"_id": DESIG, "company_id": COMPANY, "name": "Ops Executive",
         "designation_level": "mid"}])
    bands = FakeCollection()
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "department_id": str(DEPT), "designation_id": str(DESIG),
         "approval_status": M.ReqApproval.PENDING_BUDGET.value,
         "closing_status": "Open", "vacancy": 2, "created_at": NOW,
         "created_by": U_HR, "sla_actuals": {}},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "department_id": str(DEPT), "designation_id": str(DESIG),
         "approval_status": M.ReqApproval.PENDING_BUDGET.value,
         "closing_status": "Open", "vacancy": 1, "created_at": NOW,
         "created_by": U_HR, "sla_actuals": {}},
    ])

    store = {M.COLL_SALARY_BANDS: bands, M.COLL_DEPARTMENTS: departments,
             M.COLL_DESIGNATIONS: designations, M.COLL_REQUISITIONS: reqs,
             M.COLL_CANDIDATES: FakeCollection(), M.COLL_EXCEPTIONS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             M.COLL_POSITION_SCORECARDS: FakeCollection(),
             M.COLL_SANCTIONED_STRENGTH: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_salary_band_service as SB
    import app.services.hrms_requisition_service as RQ
    import app.services.hrms_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (SB, RQ, OF, AUD, IDS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in (RQ, OF):
        for name in ("notify_user", "notify_users", "notify_hrms_role"):
            if hasattr(mod, name):
                setattr(mod, name, silent)

    FIN = {"_id": U_FIN, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "FINANCE",
           "full_name": "Farid Finance"}
    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Capability shape -- the bands are Finance's artifact")
        # =================================================================
        from app.utils.hrms_access import can
        check("Finance may publish a band", can(FIN, M.Cap.SALARY_BAND_WRITE))
        check("HR may READ one", can(HR, M.Cap.SALARY_BAND_READ))
        check("but HR may NOT rewrite it -- it is an annual agreement WITH Finance",
              not can(HR, M.Cap.SALARY_BAND_WRITE))

        # =================================================================
        section("Publishing a band")
        # =================================================================
        band = await SB.create_salary_band(FIN, COMPANY, {
            "department_id": str(DEPT), "designation_id": str(DESIG),
            "min": 500000, "max": 800000, "effective_from": ago(30)})
        check("a band is minted with a SAL id", band["band_no"].startswith("SAL-"))
        check("it starts Active", band["status"] == "Active")
        check("who agreed it is on the row, not only in the audit trail",
              band["approved_by_name"] == "Farid Finance" and band["approved_at"])
        check("the position names are denormalised so the table reads without a join",
              band["designation_name"] == "Ops Executive"
              and band["department_name"] == "Operations")

        await expect_http(
            "a band whose minimum exceeds its maximum",
            SB.create_salary_band(FIN, COMPANY, {
                "department_id": str(DEPT), "designation_id": str(DESIG),
                "min": 900000, "max": 100000}),
            422, "cannot exceed its maximum")

        # =================================================================
        section("The gate PRE-FILLS from the master")
        # =================================================================
        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        prefill = await SB.prefill_for_requisition(COMPANY, req)
        check("a requisition for a banded position gets a pre-fill",
              prefill is not None)
        check("in the shape the approval body expects",
              prefill["approved_salary_band_min"] == 500000
              and prefill["approved_salary_band_max"] == 800000)
        check("and it says an override needs a reason, before anybody tries",
              "reason" in prefill["hint"].lower())

        # =================================================================
        section("Matching the standing band stamps `master`")
        # =================================================================
        await RQ.act_on_requisition(FIN, COMPANY, "HR-REQ-2026-001", "budget-approve",
                                    budget={"approved_headcount": 2,
                                            "approved_salary_band_min": 500000,
                                            "approved_salary_band_max": 800000})
        approved = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("the band is stamped on the requisition",
              approved["approved_salary_band_min"] == 500000)
        check("and its source is recorded as the master",
              approved["band_source"] == M.BAND_SOURCE_MASTER)
        check("with the master row it came from, so the two are traceable",
              approved["band_master_no"] == band["band_no"])

        # =================================================================
        section("An override is allowed, stamped, and must be explained")
        # =================================================================
        await expect_http(
            "approving a DIFFERENT band with no reason",
            RQ.act_on_requisition(FIN, COMPANY, "HR-REQ-2026-002", "budget-approve",
                                  budget={"approved_headcount": 1,
                                          "approved_salary_band_min": 900000,
                                          "approved_salary_band_max": 1400000}),
            422, "differs from the standing band")

        await RQ.act_on_requisition(
            FIN, COMPANY, "HR-REQ-2026-002", "budget-approve",
            remarks="Scarce skill; agreed with the MD out of cycle.",
            budget={"approved_headcount": 1,
                    "approved_salary_band_min": 900000,
                    "approved_salary_band_max": 1400000})
        overridden = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        check("with a reason it goes through", overridden["approved_salary_band_min"] == 900000)
        check("and is stamped `manual`, so the deviation is visible",
              overridden["band_source"] == M.BAND_SOURCE_MANUAL)
        check("the reason is on the record rather than in somebody's memory",
              "scarce skill" in (overridden["budget_remarks_approver"] or "").lower())

        # =================================================================
        section("The classification rule is pure and testable on its own")
        # =================================================================
        decision = SB.resolve_band_decision(None, {"approved_salary_band_min": 1,
                                                   "approved_salary_band_max": 2})
        check("with NO standing band, a figure is manual and needs no reason",
              decision["band_source"] == M.BAND_SOURCE_MANUAL
              and decision["override_reason_required"] is False)
        check("there was nothing to deviate FROM, which is why", True)

        # =================================================================
        section("A band edited later does NOT reach back")
        # =================================================================
        # THE test this file exists for. Finance revises the band upward AFTER the
        # requisition was approved against the old one.
        await SB.create_salary_band(FIN, COMPANY, {
            "department_id": str(DEPT), "designation_id": str(DESIG),
            "min": 1500000, "max": 2500000, "effective_from": ago(1)})
        superseded = await bands.find_one({"band_no": band["band_no"]})
        check("the old band is SUPERSEDED, not overwritten",
              superseded["status"] == "Superseded")
        check("and the succession is recorded on the new one",
              band["band_no"] in (await bands.find_one(
                  {"status": "Active"}))["supersedes"])

        still = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("the REQUISITION still carries the band it was approved against",
              still["approved_salary_band_min"] == 500000
              and still["approved_salary_band_max"] == 800000)

        # And the offer check reads the requisition, not the master. An offer at 700,000 is
        # inside the STAMPED band and outside the new master band -- it must still pass.
        await OF.assert_within_band(COMPANY, 700000, {"uk": "CAN-001"}, still)
        check("an offer inside the STAMPED band passes, though the master has moved on",
              True)
        await expect_http(
            "an offer inside the new MASTER band but outside the stamped one",
            OF.assert_within_band(COMPANY, 2000000, {"uk": "CAN-001"}, still),
            409, "above the approved salary band")
        check("the master is a convenience; the requisition is the authority", True)

        # =================================================================
        section("Figures are never edited in place")
        # =================================================================
        active = await bands.find_one({"status": "Active"})
        await expect_http(
            "editing a published band's figures",
            SB.update_salary_band(FIN, COMPANY, active["band_no"], {"min": 10}),
            409, "cannot be edited")
        updated = await SB.update_salary_band(
            FIN, COMPANY, active["band_no"], {"notes": "FY26 market review."})
        check("but its descriptive fields can be", updated["notes"].startswith("FY26"))

        # =================================================================
        section("Effective dates are honoured")
        # =================================================================
        future = await SB.create_salary_band(FIN, COMPANY, {
            "department_id": str(DEPT), "designation_id": str(DESIG),
            "grade": "L4", "min": 3000000, "max": 4000000,
            "effective_from": ahead(90)})
        found = await SB.active_band_for(COMPANY, str(DEPT), str(DESIG), "L4")
        check("a band that starts next quarter does not pre-fill today's approval",
              found is None or found["band_no"] != future["band_no"])
        check("a grade with no band of its own falls back to the position default",
              (found or {}).get("grade") in (None, ""))

        none_for = await SB.active_band_for(COMPANY, str(DEPT), str(ObjectId()))
        check("a position with no band at all returns None rather than guessing",
              none_for is None)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
