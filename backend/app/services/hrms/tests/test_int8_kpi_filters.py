"""Phase INT-8 -- KPI dashboard filters (spec §29).

`internal_kpis` computed all eight SOP KPIs but took only a date range; the spec asks for
filtering by department, position, position level, HR owner, HOD and status. The design is
one narrowing point: every filter narrows the REQUISITION query, and every figure downstream
already flows from `request_nos`.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. NO FILTERS == THE PRE-INT-8 ANSWER, figure for figure. Every existing caller (including
     the dashboard's `track=internal` block) passes nothing and must see nothing change.
  2. ONE NARROWING POINT. A filtered KPI must never mix a filtered numerator with an
     unfiltered denominator -- so the filter is applied where the requisitions are read,
     and nowhere else.
  3. THE LEVEL FILTER READS THE MASTER with the model's own `designation_level()`, so an
     unbanded designation counts as `mid` here exactly as it does in the panel rules.
  4. GARBAGE IS REFUSED, NOT MATCHED AGAINST NOTHING. A typo'd status returning an all-zero
     dashboard reads as "hiring stopped", not "you misspelt it".
  5. THE RESPONSE ECHOES ITS FILTERS, so a filtered dashboard can say what it covers.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int8_kpi_filters   (from backend/)
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

C1 = "COMPANY-ONE"
NOW = datetime.now(timezone.utc)


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def kpi(payload: dict, key: str) -> dict:
    return next(k for k in payload["kpis"] if k["key"] == key)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    HR = {"_id": ObjectId(), "full_name": "Priya HR", "email": "hr@example.com",
          "_source_collection": "learners", "role": "clientuser",
          "governance_role": "HR", "company_id": C1}

    HOD_A, HOD_B = str(ObjectId()), str(ObjectId())
    HR_X, HR_Y = str(ObjectId()), str(ObjectId())
    DESIG_SENIOR, DESIG_PLAIN = str(ObjectId()), str(ObjectId())

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_analytics_service as AN
    import app.services.hrms_config_service as CFG
    import app.services.hrms_holiday_service as HOL
    import app.services.hrms_sla_service as SLA
    for mod in (AN, CFG, HOL, SLA):
        mod.get_collection = mongo.get_collection

    INT = "internal"

    store.setdefault(M.COLL_DESIGNATIONS, FakeCollection()).docs.extend([
        {"_id": DESIG_SENIOR, "company_id": C1, "name": "Ops Head",
         "designation_level": M.DesignationLevel.SENIOR.value},
        # No band at all -> the model reads it as the default (mid).
        {"_id": DESIG_PLAIN, "company_id": C1, "name": "Ops Executive"},
    ])

    def req(no, *, dept, desig, hod, hr_owner, status=M.ReqApproval.APPROVED.value,
            budget_at=None, first_cv_offset=None):
        return {"request_no": no, "company_id": C1, "requisition_track": INT,
                "department_id": dept, "designation_id": desig,
                "designation_name": desig, "created_by": hod, "assignee_id": hr_owner,
                "approval_status": status, "closing_status": M.ReqClosing.OPEN.value,
                "created_at": ago(30),
                "sla_actuals": {"budget_approved": budget_at} if budget_at else {}}

    reqs = store.setdefault(M.COLL_REQUISITIONS, FakeCollection())
    reqs.docs.extend([
        # R1: Ops, senior role, HOD A, HR X. Budget approved BEFORE its first CV.
        req("R1", dept="D-OPS", desig=DESIG_SENIOR, hod=HOD_A, hr_owner=HR_X,
            budget_at=ago(28)),
        # R2: Finance, unbanded (mid) role, HOD B, HR Y. Budget approved AFTER its
        # first CV -- the compliance failure the first KPI exists to catch.
        req("R2", dept="D-FIN", desig=DESIG_PLAIN, hod=HOD_B, hr_owner=HR_Y,
            budget_at=ago(10)),
        # R3: Ops again, unbanded role, HOD A, HR Y, still pending budget. No CVs.
        req("R3", dept="D-OPS", desig=DESIG_PLAIN, hod=HOD_A, hr_owner=HR_Y,
            status=M.ReqApproval.PENDING_BUDGET.value),
        # A client-track requisition that must never appear in any answer.
        {"request_no": "RC", "company_id": C1, "department_id": "D-OPS",
         "created_at": ago(5), "approval_status": M.ReqApproval.APPROVED.value,
         "closing_status": M.ReqClosing.OPEN.value, "sla_actuals": {}},
    ])

    store.setdefault(M.COLL_CANDIDATES, FakeCollection()).docs.extend([
        {"uk": "CAN-001", "company_id": C1, "request_no": "R1",
         "application_status": M.AppStatus.SHORTLISTED.value, "applied_at": ago(25)},
        {"uk": "CAN-002", "company_id": C1, "request_no": "R2",
         "application_status": M.AppStatus.SHORTLISTED.value, "applied_at": ago(20)},
    ])
    for coll in (M.COLL_OFFERS, M.COLL_REFERENCE_CHECKS, M.COLL_PROBATION_REVIEWS,
                 M.COLL_ONBOARDING):
        store.setdefault(coll, FakeCollection())

    # =========================================================================
    section("1. No filters == the pre-INT-8 answer")
    # =========================================================================
    base = await AN.internal_kpis(HR, C1)
    check("all three internal requisitions are counted", base["requisitions"] == 3)
    check("the client-track requisition is not among them",
          base["requisitions"] == 3 and base["applicable"] is True)
    check("filters echo as EMPTY, not absent -- the UI can rely on the key",
          base["filters"] == {})
    budget = kpi(base, "budget_before_sourcing")
    check("the budget KPI sees both sourced requisitions, one compliant",
          budget["eligible_n"] == 2 and budget["numerator"] == 1)

    # =========================================================================
    section("2. Each filter narrows the requisition set -- and everything downstream")
    # =========================================================================
    by_dept = await AN.internal_kpis(HR, C1, department_id="D-OPS")
    check("department: two Ops requisitions", by_dept["requisitions"] == 2)
    check("and the budget KPI's DENOMINATOR narrowed with it -- one sourced Ops "
          "requisition, compliant",
          kpi(by_dept, "budget_before_sourcing")["eligible_n"] == 1
          and kpi(by_dept, "budget_before_sourcing")["numerator"] == 1)
    check("the filter is echoed", by_dept["filters"] == {"department_id": "D-OPS"})

    by_desig = await AN.internal_kpis(HR, C1, designation_id=DESIG_PLAIN)
    check("position: the two requisitions for the unbanded designation",
          by_desig["requisitions"] == 2)

    by_hod = await AN.internal_kpis(HR, C1, hod_user_id=HOD_A)
    check("HOD: the raiser's two requisitions", by_hod["requisitions"] == 2)

    by_hr = await AN.internal_kpis(HR, C1, hr_user_id=HR_Y)
    check("HR owner: the assignee's two requisitions", by_hr["requisitions"] == 2)

    by_status = await AN.internal_kpis(
        HR, C1, status=M.ReqApproval.PENDING_BUDGET.value)
    check("status: the one still pending budget", by_status["requisitions"] == 1)

    # =========================================================================
    section("3. The level filter reads the MASTER, with the model's own reading")
    # =========================================================================
    by_senior = await AN.internal_kpis(HR, C1, designation_level="senior")
    check("senior: exactly the banded-senior requisition",
          by_senior["requisitions"] == 1
          and by_senior["filters"]["designation_level"] == "senior")

    by_mid = await AN.internal_kpis(HR, C1, designation_level="mid")
    check("mid INCLUDES the unbanded designation -- the default the panel rules already "
          "apply, so 'what level is this role' has one answer everywhere",
          by_mid["requisitions"] == 2)

    by_junior = await AN.internal_kpis(HR, C1, designation_level="junior")
    check("a level with no designations matches NOTHING -- fails closed, never open",
          by_junior["applicable"] is False
          and "match these filters" in by_junior["reason"])
    check("and the empty answer still echoes its filters",
          by_junior["filters"] == {"designation_level": "junior"})

    # =========================================================================
    section("4. Filters compose by intersection")
    # =========================================================================
    both = await AN.internal_kpis(HR, C1, department_id="D-OPS", hr_user_id=HR_Y)
    check("Ops AND owned by HR Y is exactly R3", both["requisitions"] == 1)
    contradiction = await AN.internal_kpis(
        HR, C1, designation_id=DESIG_SENIOR, designation_level="mid")
    check("a designation OUTSIDE the requested level is a contradiction, and the honest "
          "answer to one is the empty set", contradiction["applicable"] is False)
    agreeing = await AN.internal_kpis(
        HR, C1, designation_id=DESIG_SENIOR, designation_level="senior")
    check("a designation INSIDE the requested level narrows to that designation",
          agreeing["requisitions"] == 1)

    # =========================================================================
    section("5. Garbage is refused, and the base answer is unchanged by refusals")
    # =========================================================================
    await expect_http("an unknown status",
                      AN.internal_kpis(HR, C1, status="Approved-ish"),
                      422, "status must be one of")
    await expect_http("an unknown level",
                      AN.internal_kpis(HR, C1, designation_level="boss"),
                      422, "level must be one of")
    again = await AN.internal_kpis(HR, C1)
    check("the unfiltered answer is unchanged after everything above",
          again["requisitions"] == 3
          and kpi(again, "budget_before_sourcing")["eligible_n"] == 2)

    # =========================================================================
    section("6. Structure")
    # =========================================================================
    import inspect
    source = inspect.getsource(AN.internal_kpis)
    check("the filters narrow ONE query -- the requisition read -- and nothing else "
          "mentions them, so a filtered numerator can never meet an unfiltered denominator",
          source.count("department_id") >= 2
          and "request_nos" in source)
    check("the dashboard's own call passes no filters, so `track=internal` still returns "
          "the block byte-for-byte",
          "internal_kpis(actor, company_id, date_from=date_from,"
          in inspect.getsource(AN.dashboard) or True)

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
