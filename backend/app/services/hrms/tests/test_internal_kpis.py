"""Internal recruitment track -- the KPI dashboard and the two new reports (SOP §10, §13).

Covers: the eight KPIs and their targets, the ratios behind each percentage, the honest
handling of "no data yet", the probation and exceptions report entities, and the retention
date those reports expose.

The property this file protects hardest: A RATIO WITH NO DENOMINATOR IS NOT A SCORE. Every
KPI reports its numerator and denominator, and where the denominator is zero the value is
null with a reason -- never 0% and never 100%, because both of those are claims about
performance that nothing has happened to justify.

It also pins the one KPI the module CANNOT compute. `induction_feedback` is a checklist tick,
and the SOP asks for a score. Reporting a number derived from ticks would be inventing data,
so the figure is null and says why.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_kpis   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def d(days: int) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())

    # One internal requisition raised 40 days ago, sourced properly and run to a hire; one
    # raised 40 days ago that sourced BEFORE budget approval (the control failing); and a
    # client requisition that must contribute nothing.
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": ago(40),
         "sla_actuals": {"budget_approved": ago(38), "scorecard_approved": ago(37),
                         "shortlist_ready": ago(30), "final_selection": ago(20),
                         "offer_released": ago(19)}},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": ago(40),
         # Budget approved AFTER the first CV arrived, and the shortlist took far too long.
         "sla_actuals": {"budget_approved": ago(20), "shortlist_ready": ago(2)}},
        {"request_no": "HR-REQ-2026-900", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Client Role",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": ago(40), "sla_actuals": {}},
    ])
    candidates = FakeCollection([
        {"uk": "CAN-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.EMPLOYEE_CREATED.value, "applied_at": ago(35)},
        {"uk": "CAN-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.REJECTED.value, "applied_at": ago(34)},
        # Applied BEFORE this requisition's budget was approved.
        {"uk": "CAN-003", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "application_status": M.AppStatus.OFFER_DECLINED.value, "applied_at": ago(30)},
        # Client-track candidate, must never be counted.
        {"uk": "CAN-900", "company_id": COMPANY, "request_no": "HR-REQ-2026-900",
         "application_status": M.AppStatus.JOINED.value, "applied_at": ago(30)},
    ])
    offers = FakeCollection([
        {"offer_no": "OFR-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "uk": "CAN-001", "status": M.OfferStatus.ACCEPTED.value,
         "created_at": ago(19), "sent_at": ago(19), "joining_date": d(10)},
        # Sent 5 days ago for a joining date 8 days ago: the letter went out AFTER the
        # person was due to start. A real failure the KPI must report.
        {"offer_no": "OFR-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "uk": "CAN-003", "status": M.OfferStatus.DECLINED.value,
         "created_at": ago(15), "sent_at": ago(5), "joining_date": d(8)},
    ])
    references = FakeCollection([
        # Cleared BEFORE the offer was raised -- compliant.
        {"ref_no": "REF-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "uk": "CAN-001", "outcome": "Positive", "created_at": ago(21)},
        # Recorded AFTER the offer -- not compliant, and the KPI must say so.
        {"ref_no": "REF-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "uk": "CAN-003", "outcome": "Positive", "created_at": ago(2)},
    ])
    probations = FakeCollection([
        {"prb_no": "PRB-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "employee_code": "EMP-2026-001", "outcome": M.ProbationOutcome.CONFIRMED.value,
         "ends_on": d(5), "confirmed_at": ago(6), "created_at": ago(15)},
        {"prb_no": "PRB-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "employee_code": "EMP-2026-002", "outcome": M.ProbationOutcome.CONFIRMED.value,
         "ends_on": d(10), "confirmed_at": ago(2), "created_at": ago(15)},
        {"prb_no": "PRB-003", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "employee_code": "EMP-2026-003", "outcome": M.ProbationOutcome.PENDING.value,
         "ends_on": d(-30), "confirmed_at": None, "created_at": ago(15)},
    ])
    onboardings = FakeCollection([
        {"onb_no": "ONB-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "employee_id": "EMP-2026-001", "joining_date": d(120),
         "checklist": [{**i, "done": i["key"] == "induction_feedback"}
                       for i in M.seed_checklist()]},
        {"onb_no": "ONB-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "employee_id": "EMP-2026-002", "joining_date": d(10),
         "checklist": M.seed_checklist()},
    ])
    profiles = FakeCollection([
        # Joined 120 days ago, still here -> retained.
        {"employee_code": "EMP-2026-001", "company_id": COMPANY, "joined_on": d(120),
         "resigned_on": None},
        # Joined 10 days ago -> has not had 90 days, must not count either way.
        {"employee_code": "EMP-2026-002", "company_id": COMPANY, "joined_on": d(10),
         "resigned_on": None},
    ])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_OFFERS: offers, M.COLL_REFERENCE_CHECKS: references,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_ONBOARDING: onboardings,
             M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_EXCEPTIONS: FakeCollection(),
             M.COLL_ASSESSMENTS: FakeCollection(), M.COLL_INTERVIEWS: FakeCollection(),
             M.COLL_JOB_POSTINGS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection(), "companies": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_analytics_service as AN
    import app.services.hrms_sla_service as SLA
    for mod in (AN, SLA):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("The block is opt-in")
        # =================================================================
        plain = await AN.dashboard(HR, COMPANY)
        check("a dashboard with no track asked for carries no KPI block",
              plain.get("internal_kpis") is None)
        tracked = await AN.dashboard(HR, COMPANY, track="internal")
        check("asking for the internal track adds it",
              tracked.get("internal_kpis") is not None)
        check("the existing payload is otherwise unchanged",
              set(plain) | {"internal_kpis"} == set(tracked))

        report = await AN.internal_kpis(HR, COMPANY)
        by_key = {k["key"]: k for k in report["kpis"]}
        check("it reports on internal requisitions only",
              report["requisitions"] == 2)
        check("and counts only their candidates -- the client one is absent",
              report["candidates"] == 3)
        check("all eight SOP KPIs are present", len(report["kpis"]) == 8)

        # =================================================================
        section("Every ratio shows its working")
        # =================================================================
        check("each KPI reports a numerator and a denominator",
              all("numerator" in k and "denominator" in k for k in report["kpis"]))
        check("and its SOP target where the SOP states one",
              by_key["budget_before_sourcing"]["target"] == 100
              and by_key["shortlist_within_tat"]["target"] == 95)
        check("a KPI the SOP only says to 'track monthly' carries no target",
              by_key["offer_to_joining"]["target"] is None)

        # =================================================================
        section("1. Budget approved before sourcing")
        # =================================================================
        kpi = by_key["budget_before_sourcing"]
        check("both sourced requisitions are in the denominator",
              kpi["denominator"] == 2)
        check("only the one funded BEFORE its first CV counts",
              kpi["numerator"] == 1)
        check("so the control shows as 50%, not 100%", kpi["value"] == 50.0)
        check("and it is flagged as missing its target",
              kpi["meets_target"] is False)

        # =================================================================
        section("2. Shortlist within Day 15")
        # =================================================================
        kpi = by_key["shortlist_within_tat"]
        check("both shortlisted requisitions are measured", kpi["denominator"] == 2)
        check("the one that took ~10 days passes and the ~38-day one does not",
              kpi["numerator"] == 1)

        # =================================================================
        section("3. Offer-to-joining conversion")
        # =================================================================
        kpi = by_key["offer_to_joining"]
        check("both SENT offers are counted", kpi["denominator"] == 2)
        check("only the one whose candidate joined converts", kpi["numerator"] == 1)
        check("a client-track joiner does not inflate it", kpi["numerator"] == 1)

        # =================================================================
        section("4. Reference check before offer")
        # =================================================================
        kpi = by_key["reference_before_offer"]
        check("every internal offer is measured", kpi["denominator"] == 2)
        check("a reference recorded AFTER the offer does not count as compliant",
              kpi["numerator"] == 1)
        check("the hint names the only legitimate way to be under 100%",
              "exception" in (kpi["hint"] or "").lower())

        # =================================================================
        section("5. Offer letter before the joining date")
        # =================================================================
        # OFR-002 was sent 5 days ago for a joining date 8 days ago -- the letter went out
        # AFTER the person was due to start, which is exactly what this KPI exists to catch.
        kpi = by_key["offer_before_joining"]
        check("both dated offers are measured", kpi["denominator"] == 2)
        check("an offer sent after its own joining date does NOT count as in time",
              kpi["numerator"] == 1)
        check("so the 100% target is missed", kpi["meets_target"] is False)

        # =================================================================
        section("6. Probation confirmed on time")
        # =================================================================
        kpi = by_key["probation_on_time"]
        check("only DECIDED probations are measured -- a pending one is not a failure yet",
              kpi["denominator"] == 2)
        check("the one decided before its end date counts", kpi["numerator"] == 1)

        # =================================================================
        section("7. 90-day retention")
        # =================================================================
        kpi = by_key["retention_90_day"]
        check("only a joiner who has HAD 90 days is eligible", kpi["denominator"] == 1)
        check("and they are still here", kpi["numerator"] == 1)
        check("someone who joined last week is in neither number",
              kpi["denominator"] == 1)

        # =================================================================
        section("8. New-hire satisfaction")
        # =================================================================
        # Phase INT-2 made this measurable by capturing the surveys. With no responses in
        # this fixture the KPI still refuses to invent a figure -- and now says which of the
        # two reasons applies, rather than reporting a checklist tick count as a "score".
        kpi = by_key["new_hire_satisfaction"]
        check("with no responses the score is null, not invented", kpi["value"] is None)
        check("and it says why in plain words",
              "no survey responses" in (kpi["reason"] or "").lower()
              or "fewer than" in (kpi["reason"] or "").lower())
        check("it is a 1-5 SCORE, not a percentage, and says so",
              kpi.get("scale_max") == 5)
        check("no instrument reported a figure", kpi["by_instrument"] == [])

        # =================================================================
        section("No data is not the same as zero")
        # =================================================================
        empty_store = dict(store)
        empty_store[M.COLL_REQUISITIONS] = FakeCollection([
            {"request_no": "HR-REQ-2026-777", "company_id": COMPANY,
             "requisition_track": "internal", "designation_name": "Brand new",
             "approval_status": "Pending Budget Approval", "closing_status": "Open",
             "created_at": NOW, "sla_actuals": {}}])
        empty_store[M.COLL_CANDIDATES] = FakeCollection()
        empty_store[M.COLL_OFFERS] = FakeCollection()
        empty_store[M.COLL_PROBATION_REVIEWS] = FakeCollection()
        empty_store[M.COLL_ONBOARDING] = FakeCollection()
        mongo.get_collection = lambda name: empty_store.setdefault(name, FakeCollection())
        AN.get_collection = mongo.get_collection

        fresh = await AN.internal_kpis(HR, COMPANY)
        fresh_by_key = {k["key"]: k for k in fresh["kpis"]}
        check("a KPI with nothing to measure is NULL, not 0%",
              fresh_by_key["budget_before_sourcing"]["value"] is None)
        check("nor is it 100%",
              fresh_by_key["offer_to_joining"]["value"] is None)
        check("and it says there is nothing to measure yet",
              "no qualifying records"
              in (fresh_by_key["offer_to_joining"]["reason"] or "").lower())
        check("meets_target is null when there is no value to compare",
              fresh_by_key["budget_before_sourcing"]["meets_target"] is None)

        empty_store[M.COLL_REQUISITIONS] = FakeCollection()
        none_at_all = await AN.internal_kpis(HR, COMPANY)
        check("with no internal requisitions at all the block is not applicable",
              none_at_all["applicable"] is False)
        check("and says so rather than returning eight empty rows",
              none_at_all["kpis"] == [])

        mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
        AN.get_collection = mongo.get_collection

        # =================================================================
        section("The two new reports")
        # =================================================================
        check("probation is an allow-listed report entity",
              "probation" in M.REPORT_ENTITIES)
        check("so is the exception log", "exceptions" in M.REPORT_ENTITIES)
        check("the ReportEntity enum matches the allow-list exactly",
              {e.value for e in M.ReportEntity} == set(M.REPORT_ENTITIES))

        prb_cols = [c for c, _l in M.REPORT_ENTITIES["probation"]["columns"]]
        check("the probation report carries the retention date (SOP 13)",
              "retention_until" in prb_cols)
        check("and the outcome and who decided it",
              "outcome" in prb_cols and "confirmed_by_name" in prb_cols)
        check("and the requisition, so it can be scoped like everything else",
              "request_no" in prb_cols)

        exc_cols = [c for c, _l in M.REPORT_ENTITIES["exceptions"]["columns"]]
        check("the exception report names the GATE each one lifts",
              "gate" in exc_cols)
        check("plus who asked and who granted",
              "raised_by_name" in exc_cols and "approved_by_name" in exc_cols)
        check("and the reason, which is the point of the log",
              "reason" in exc_cols)

        cand_cols = [c for c, _l in M.REPORT_ENTITIES["candidates"]["columns"]]
        check("the candidate report carries the scorecard result",
              "scorecard_score" in cand_cols and "scorecard_band" in cand_cols)

        rows = await AN.report(HR, COMPANY, "probation")
        check("the probation report runs and is scoped", rows["total"] == 3)
        rows = await AN.report(HR, COMPANY, "exceptions")
        check("so does the exception report", rows["total"] == 0)

        # =================================================================
        section("Analytics is still READ-ONLY")
        # =================================================================
        import inspect
        source = inspect.getsource(AN)
        for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                          "delete_one", "delete_many", "find_one_and_"):
            check(f"the KPI block introduced no {forbidden}", forbidden not in source)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
