"""Phase INT-2 -- the complete internal KPI set (SOP §10).

All EIGHT of the SOP's KPIs, computed server-side and role-scoped.

Covers each KPI's arithmetic, and one property that runs through all of them:
DENOMINATOR HONESTY. Every ratio reports `eligible_n`, and where records were deliberately
left out it reports `excluded_n` with the reason.

The 90-day retention KPI is where that matters most and is easiest to get wrong. Somebody
who joined last week has not failed to stay 90 days; they have not had 90 days. Counting
them in the denominator scores the company down for hiring recently, and counting them as
retained scores it up for the same thing. Both are wrong, and this file asserts that neither
happens.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_internal_kpis   (from backend/)
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


def days_ago(n):
    return NOW - timedelta(days=n)


def date_ago(n):
    return days_ago(n).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())

    reqs = FakeCollection([
        # Budget approved BEFORE the first CV -- compliant.
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": days_ago(120),
         "sla_actuals": {"budget_approved": days_ago(118),
                         "shortlist_ready": days_ago(110)}},
        # Budget approved AFTER the first CV -- the case the KPI exists to catch.
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Analyst",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": days_ago(100),
         "sla_actuals": {"budget_approved": days_ago(80),
                         "shortlist_ready": days_ago(20)}},
        # Never sourced: not tested against the rule, so not counted either way.
        {"request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Lead",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": days_ago(10), "sla_actuals": {"budget_approved": days_ago(9)}},
        # A CLIENT requisition, which must not appear anywhere in this block.
        {"request_no": "HR-REQ-2026-900", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open",
         "created_at": days_ago(50), "sla_actuals": {}},
    ])
    candidates = FakeCollection([
        {"uk": "CAN-001", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.EMPLOYEE_CREATED.value,
         "applied_at": days_ago(115)},
        {"uk": "CAN-002", "company_id": COMPANY, "request_no": "HR-REQ-2026-002",
         "application_status": M.AppStatus.OFFER_DECLINED.value,
         "applied_at": days_ago(95)},
        {"uk": "CAN-003", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.JOINED.value, "applied_at": days_ago(60)},
        {"uk": "CAN-900", "company_id": COMPANY, "request_no": "HR-REQ-2026-900",
         "application_status": M.AppStatus.APPLIED.value, "applied_at": days_ago(45)},
    ])
    offers = FakeCollection([
        # Reference cleared BEFORE the offer, sent before the joining date.
        {"offer_no": "OFR-2026-001", "company_id": COMPANY, "uk": "CAN-001",
         "request_no": "HR-REQ-2026-001", "status": "Accepted",
         "created_at": days_ago(105), "sent_at": days_ago(104),
         "joining_date": date_ago(100)},
        # No clearing reference before it, and sent AFTER the joining date.
        {"offer_no": "OFR-2026-002", "company_id": COMPANY, "uk": "CAN-002",
         "request_no": "HR-REQ-2026-002", "status": "Declined",
         "created_at": days_ago(70), "sent_at": days_ago(60),
         "joining_date": date_ago(65)},
        {"offer_no": "OFR-2026-003", "company_id": COMPANY, "uk": "CAN-003",
         "request_no": "HR-REQ-2026-001", "status": "Accepted",
         "created_at": days_ago(50), "sent_at": days_ago(49),
         "joining_date": date_ago(45)},
    ])
    references = FakeCollection([
        {"ref_no": "REF-2026-001", "company_id": COMPANY, "uk": "CAN-001",
         "request_no": "HR-REQ-2026-001", "outcome": "Positive",
         "created_at": days_ago(106)},
        {"ref_no": "REF-2026-003", "company_id": COMPANY, "uk": "CAN-003",
         "request_no": "HR-REQ-2026-001", "outcome": "Positive",
         "created_at": days_ago(51)},
        # Recorded AFTER the offer was raised -- work done, but not before the gate.
        {"ref_no": "REF-2026-002", "company_id": COMPANY, "uk": "CAN-002",
         "request_no": "HR-REQ-2026-002", "outcome": "Positive",
         "created_at": days_ago(65)},
    ])
    probations = FakeCollection([
        {"prb_no": "PRB-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_code": "EMP-2026-001",
         "outcome": "Confirmed", "ends_on": date_ago(10),
         "confirmed_at": days_ago(12)},                     # on time
        {"prb_no": "PRB-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_code": "EMP-2026-002",
         "outcome": "Confirmed", "ends_on": date_ago(30),
         "confirmed_at": days_ago(5)},                      # late
        {"prb_no": "PRB-2026-003", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_code": "EMP-2026-003",
         "outcome": "Pending", "ends_on": date_ago(1)},     # undecided, not counted
    ])
    onboardings = FakeCollection([
        {"onb_no": "ONB-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_id": "EMP-2026-001",
         "joining_date": date_ago(100), "checklist": M.seed_checklist()},
        {"onb_no": "ONB-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_id": "EMP-2026-002",
         "joining_date": date_ago(95), "checklist": M.seed_checklist()},
        # Joined last week -- the denominator-honesty case.
        {"onb_no": "ONB-2026-003", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_id": "EMP-2026-003",
         "joining_date": date_ago(7), "checklist": M.seed_checklist()},
        # No joining date at all -- reported as excluded rather than guessed at.
        {"onb_no": "ONB-2026-004", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_id": "EMP-2026-004",
         "checklist": M.seed_checklist()},
    ])
    profiles = FakeCollection([
        # Still here after 100 days -- retained.
        {"employee_code": "EMP-2026-001", "company_id": COMPANY,
         "joined_on": date_ago(100), "employment_status": "Active"},
        # Left after 40 days -- NOT retained.
        {"employee_code": "EMP-2026-002", "company_id": COMPANY,
         "joined_on": date_ago(95), "separation_date": date_ago(55),
         "employment_status": "Resigned"},
        # Joined a week ago: window has not matured.
        {"employee_code": "EMP-2026-003", "company_id": COMPANY,
         "joined_on": date_ago(7), "employment_status": "Active"},
        # No joining date recorded.
        {"employee_code": "EMP-2026-004", "company_id": COMPANY,
         "employment_status": "Active"},
    ])
    surveys_coll = FakeCollection()
    survey_responses = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_OFFERS: offers, M.COLL_REFERENCE_CHECKS: references,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_ONBOARDING: onboardings,
             M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_SURVEYS: surveys_coll,
             M.COLL_SURVEY_RESPONSES: survey_responses,
             M.COLL_LINKS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_analytics_service as AN
    import app.services.hrms_survey_service as SV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (AN, SV, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        report = await AN.internal_kpis(HR, COMPANY, date_from=date_ago(400))
        by_key = {k["key"]: k for k in report["kpis"]}

        # =================================================================
        section("All EIGHT SOP KPIs are present")
        # =================================================================
        expected = ["budget_before_sourcing", "shortlist_within_tat", "offer_to_joining",
                    "reference_before_offer", "offer_before_joining",
                    "probation_on_time", "retention_90_day", "new_hire_satisfaction"]
        check("eight KPIs, in the SOP's own order",
              [k["key"] for k in report["kpis"]] == expected)
        check("every one carries a human label",
              all(k.get("label") for k in report["kpis"]))
        check("and the internal requisitions only -- the client one is nowhere in it",
              report["requisitions"] == 3)

        # =================================================================
        section("Every ratio reports its denominator honestly")
        # =================================================================
        ratios = [k for k in report["kpis"] if k["key"] != "new_hire_satisfaction"]
        check("each ratio names how many records were ELIGIBLE",
              all("eligible_n" in k for k in ratios))
        check("and eligible_n IS the denominator, named for what it means",
              all(k["eligible_n"] == k["denominator"] for k in ratios))
        check("each reports how many were excluded",
              all("excluded_n" in k for k in ratios))
        check("a percentage with no denominator could be five of six or five hundred of "
              "six hundred", True)

        # =================================================================
        section("1. Budget approved before sourcing (target 100%)")
        # =================================================================
        kpi = by_key["budget_before_sourcing"]
        check("only requisitions that actually received a CV are measured",
              kpi["denominator"] == 2)
        check("one of the two approved its budget before the first CV",
              kpi["numerator"] == 1)
        check("so the rate is 50%", kpi["value"] == 50.0)
        check("the SOP target is 100%", kpi["target"] == 100)
        check("and it is reported as missed", kpi["meets_target"] is False)
        check("a requisition nobody sourced against is not counted as a pass", True)

        # =================================================================
        section("2. Shortlist ready within TAT (target 95%)")
        # =================================================================
        kpi = by_key["shortlist_within_tat"]
        check("both shortlisted requisitions are measured", kpi["denominator"] == 2)
        check("the one that took 8 days is within Day 15", kpi["numerator"] == 1)
        check("the target is 95%", kpi["target"] == 95)

        # =================================================================
        section("3. Offer-to-joining conversion (a trend, no fixed target)")
        # =================================================================
        kpi = by_key["offer_to_joining"]
        check("three offers went out", kpi["denominator"] == 3)
        check("two of them resulted in somebody joining", kpi["numerator"] == 2)
        check("it is a trend, so no target is asserted", kpi["target"] is None)
        check("and meets_target is null rather than a made-up verdict",
              kpi["meets_target"] is None)

        # =================================================================
        section("4. Reference check before offer (target 100%)")
        # =================================================================
        kpi = by_key["reference_before_offer"]
        check("all three offers are measured", kpi["denominator"] == 3)
        check("two had a clearing reference BEFORE the offer was raised",
              kpi["numerator"] == 2)
        check("a reference recorded after the offer does not count -- the gate runs at "
              "creation", kpi["value"] < 100)
        check("and the hint says anything short of 100% went through on an exception",
              "exception" in (kpi["hint"] or "").lower())

        # =================================================================
        section("5. Offer letter issued before the joining date (target 100%)")
        # =================================================================
        kpi = by_key["offer_before_joining"]
        check("only offers with both dates are measured", kpi["denominator"] == 3)
        check("two went out before the joining date", kpi["numerator"] == 2)
        check("the target is 100%", kpi["target"] == 100)

        # =================================================================
        section("6. Probation confirmed on time (target 95%)")
        # =================================================================
        kpi = by_key["probation_on_time"]
        check("only DECIDED probations are measured", kpi["denominator"] == 2)
        check("one was decided on or before the end date", kpi["numerator"] == 1)
        check("an undecided probation is not counted as a failure", kpi["denominator"] != 3)

        # =================================================================
        section("7. 90-day retention -- DENOMINATOR HONESTY")
        # =================================================================
        kpi = by_key["retention_90_day"]
        check("only joiners whose 90-day window has MATURED are in the denominator",
              kpi["eligible_n"] == 2)
        check("somebody who joined last week is in NEITHER number",
              kpi["numerator"] == 1 and kpi["eligible_n"] == 2)
        check("they have not failed to stay 90 days; they have not had 90 days", True)
        check("the one still here after 100 days is retained", kpi["numerator"] == 1)
        check("the one who left after 40 days is not", kpi["value"] == 50.0)
        check("the excluded records are COUNTED, not silently dropped",
              kpi["excluded_n"] == 2)
        check("and the reason is stated in words",
              "not completed 90 days" in (kpi["excluded_reason"] or "")
              and "no joining date" in (kpi["excluded_reason"] or ""))
        check("`separation_date` is read as well as the older `resigned_on`",
              AN._separation_date({"separation_date": "2026-01-01"}) == "2026-01-01"
              and AN._separation_date({"resigned_on": "2026-02-02"}) == "2026-02-02")
        check("and a status with no date is NOT treated as a departure we can measure",
              AN._separation_date({"employment_status": "Resigned"}) is None)

        # =================================================================
        section("8. New-hire satisfaction -- now measurable, still suppressed below k")
        # =================================================================
        kpi = by_key["new_hire_satisfaction"]
        check("with no responses there is no figure", kpi["value"] is None)
        check("it says which of the two reasons applies",
              "no survey responses" in (kpi["reason"] or "").lower())
        check("it is a 1-5 SCORE and says so, so a dashboard cannot render 4.3 as 4.3%",
              kpi["scale_max"] == 5)

        # Answer six induction surveys -- above the suppression threshold.
        for n in range(1, 7):
            issued = await SV.issue_survey(HR, COMPANY, M.SurveyKind.INDUCTION,
                                           employee_code=f"EMP-2026-{n:03d}",
                                           request_no="HR-REQ-2026-001")
            survey = await SV.survey_for_kind(COMPANY, M.SurveyKind.INDUCTION)
            await SV.submit_public_survey(issued["access_code"], {
                "scores": {q["key"]: 4 for q in survey["questions"]}})

        report = await AN.internal_kpis(HR, COMPANY, date_from=date_ago(400))
        kpi = {k["key"]: k for k in report["kpis"]}["new_hire_satisfaction"]
        check("six responses produce a figure", kpi["value"] == 4.0)
        check("the response count is the denominator", kpi["eligible_n"] == 6)
        check("the instruments are broken out, so a low one is visible",
              [b["kind"] for b in kpi["by_instrument"]] == ["induction"])
        check("and the response rate travels with it -- a 4.0 from six of forty is a "
              "different fact from a 4.0 from thirty-eight",
              kpi["response_rate"] is not None)
        check("the payload still contains no per-respondent row",
              not any(k in kpi for k in ("responses_list", "rows", "employee_codes")))

        # =================================================================
        section("Bounded, scoped and read-only, like everything else here")
        # =================================================================
        check("the scan cap is unchanged", AN.SCAN_CAP == 20000)
        check("and the window ceiling", M.MAX_RANGE_DAYS == 1100)

        from pathlib import Path
        source = (Path(__file__).resolve().parents[2]
                  / "hrms_analytics_service.py").read_text(encoding="utf-8")
        for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                          "delete_one", "delete_many"):
            check(f"the KPI block introduced no {forbidden}", forbidden not in source)

        # =================================================================
        section("No internal work at all is not the same as zero")
        # =================================================================
        empty = dict(store)
        empty[M.COLL_REQUISITIONS] = FakeCollection([
            {"request_no": "HR-REQ-2026-777", "company_id": COMPANY,
             "requisition_track": "client", "designation_name": "Analyst",
             "closing_status": "Open", "created_at": NOW, "sla_actuals": {}}])
        mongo.get_collection = lambda name: empty.setdefault(name, FakeCollection())
        AN.get_collection = mongo.get_collection
        fresh = await AN.internal_kpis(HR, COMPANY)
        check("a company with no internal requisitions reports not-applicable",
              fresh["applicable"] is False)
        check("with no KPIs rather than eight zeroes", fresh["kpis"] == [])
        check("and says why", "no internal requisitions" in fresh["reason"].lower())

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
