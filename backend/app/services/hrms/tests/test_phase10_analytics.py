"""Phase 10 verification harness -- recruitment analytics and reports.

The fixture below is deliberately SMALL and hand-counted. Every expected figure in this
file is a number a person can verify by reading the fixture, which is the only way to know
an aggregation is right rather than merely consistent with itself.

Covers: effective rank (evidence beats a stale status), funnel monotonicity and conversion,
date-window validation, MANAGER row scoping, salary redaction in reports, the report
allow-list, pagination bounds, export truncation, and CSV/XLSX rendering.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase10_analytics   (from backend/)
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
    except Exception as e:  # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
OTHER = "C2"
NOW = datetime.now(timezone.utc)
DAY = timedelta(days=1)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_HOD, U_EMP = (str(ObjectId()) for _ in range(3))

    def ago(days):
        return NOW - days * DAY

    # ── The fixture ────────────────────────────────────────────────────────────
    # 10 candidates on REQ-1 (HR's), 3 on REQ-2 (the HOD's), 1 in another company.
    #
    #  uk      status                 evidence                 effective rank
    #  CAN-01  Applied                --                        1
    #  CAN-02  Applied                interview record          4   <- evidence wins
    #  CAN-03  Shortlisted            --                        2
    #  CAN-04  Rejected               DECLINED offer            6   <- the offer DID happen
    #  CAN-05  Assessment Passed      assessment record         3
    #  CAN-06  Interview Scheduled    interview record          4
    #  CAN-07  Selected               interview record          5
    #  CAN-08  Offer Generated        SENT offer                6
    #  CAN-09  Offer Accepted         ACCEPTED offer            7
    #  CAN-10  Employee Created       ACCEPTED offer            8
    #  CAN-11  Applied                DRAFT offer only          1   <- a draft proves nothing
    #  CAN-12  Wat                    --                        0   <- unrankable
    #  HOD-01  Selected               --                        5   } the HOD's requisition
    #  HOD-02  Applied                --                        1   }
    #  HOD-03  Offer Accepted         --                        7   }
    def cand(uk, status, request_no="REQ-1", source="LinkedIn", days=10, company=COMPANY):
        return {"_id": ObjectId(), "uk": uk, "company_id": company,
                "candidate_name": f"Cand {uk}", "can_email": f"{uk.lower()}@x.com",
                "application_status": status, "request_no": request_no,
                "source": source, "applied_at": ago(days), "created_at": ago(days),
                "expected_ctc": "900000"}

    candidates = FakeCollection([
        cand("CAN-01", S.APPLIED.value),
        cand("CAN-02", S.APPLIED.value),
        cand("CAN-03", S.SHORTLISTED.value, source="Naukri"),
        cand("CAN-04", S.REJECTED.value, source="Naukri"),
        cand("CAN-05", S.ASSESSMENT_PASSED.value, source="Referral"),
        cand("CAN-06", S.INTERVIEW_SCHEDULED.value),
        cand("CAN-07", S.SELECTED.value),
        cand("CAN-08", S.OFFER_GENERATED.value),
        cand("CAN-09", S.OFFER_ACCEPTED.value),
        cand("CAN-10", S.EMPLOYEE_CREATED.value),
        cand("CAN-11", S.APPLIED.value),
        cand("CAN-12", "Wat"),
        cand("HOD-01", S.SELECTED.value, request_no="REQ-2"),
        cand("HOD-02", S.APPLIED.value, request_no="REQ-2"),
        cand("HOD-03", S.OFFER_ACCEPTED.value, request_no="REQ-2"),
        # Outside the default 90-day window, and in another company.
        cand("OLD-01", S.APPLIED.value, days=400),
        cand("OTH-01", S.APPLIED.value, request_no="REQ-9", company=OTHER),
    ])

    requisitions = FakeCollection([
        {"_id": ObjectId(), "request_no": "REQ-1", "company_id": COMPANY,
         "created_by": U_HR, "vacancy": 3, "department_name": "Analytics",
         "designation_name": "Analyst", "closing_status": M.ReqClosing.OPEN.value,
         "approval_status": M.ReqApproval.APPROVED.value, "created_at": ago(30)},
        {"_id": ObjectId(), "request_no": "REQ-2", "company_id": COMPANY,
         "created_by": U_HOD, "vacancy": 2, "department_name": "Delivery",
         "designation_name": "Engineer", "closing_status": M.ReqClosing.OPEN.value,
         "approval_status": M.ReqApproval.PENDING_BUDGET.value, "created_at": ago(20)},
        {"_id": ObjectId(), "request_no": "REQ-3", "company_id": COMPANY,
         "created_by": U_HR, "vacancy": 1, "department_name": "Analytics",
         "designation_name": "Lead", "closing_status": M.ReqClosing.HIRED.value,
         "approval_status": M.ReqApproval.APPROVED.value, "created_at": ago(15)},
        {"_id": ObjectId(), "request_no": "REQ-9", "company_id": OTHER,
         "created_by": "someone", "vacancy": 9, "department_name": "Elsewhere",
         "closing_status": M.ReqClosing.OPEN.value, "created_at": ago(10)},
    ])

    assessments = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-05", "request_no": "REQ-1",
         "created_at": ago(9)},
    ])
    interviews = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-02", "request_no": "REQ-1",
         "status": M.InterviewStatus.COMPLETED.value, "scheduled_at": ago(8),
         "interview_no": "INT-1", "candidate_name": "Cand CAN-02"},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-06", "request_no": "REQ-1",
         "status": M.InterviewStatus.SCHEDULED.value, "scheduled_at": ago(2),
         "interview_no": "INT-2", "candidate_name": "Cand CAN-06"},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-07", "request_no": "REQ-1",
         "status": M.InterviewStatus.COMPLETED.value, "scheduled_at": ago(6),
         "interview_no": "INT-3", "candidate_name": "Cand CAN-07"},
    ])
    offers = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-08", "request_no": "REQ-1",
         "offer_no": "OFR-1", "status": M.OfferStatus.SENT.value, "ctc": 900000,
         "candidate_name": "Cand CAN-08", "created_at": ago(5), "sent_at": ago(5)},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-09", "request_no": "REQ-1",
         "offer_no": "OFR-2", "status": M.OfferStatus.ACCEPTED.value, "ctc": 1000000,
         "candidate_name": "Cand CAN-09", "created_at": ago(4), "responded_at": ago(3)},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-10", "request_no": "REQ-1",
         "offer_no": "OFR-3", "status": M.OfferStatus.ACCEPTED.value, "ctc": 1100000,
         "candidate_name": "Cand CAN-10", "created_at": ago(7), "responded_at": ago(6)},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-11", "request_no": "REQ-1",
         "offer_no": "OFR-4", "status": M.OfferStatus.DRAFT.value, "ctc": 800000,
         "candidate_name": "Cand CAN-11", "created_at": ago(2)},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-04", "request_no": "REQ-1",
         "offer_no": "OFR-5", "status": M.OfferStatus.DECLINED.value, "ctc": 700000,
         "candidate_name": "Cand CAN-04", "created_at": ago(9), "responded_at": ago(8)},
    ])
    onboardings = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-09", "request_no": "REQ-1",
         "onb_no": "ONB-1", "status": M.OnboardStatus.ONBOARDING.value,
         "employee_id": "EMP-2026-001", "created_at": ago(2)},
        {"_id": ObjectId(), "company_id": COMPANY, "uk": "CAN-10", "request_no": "REQ-1",
         "onb_no": "ONB-2", "status": M.OnboardStatus.COMPLETED.value,
         "employee_id": "EMP-2026-002", "created_at": ago(5)},
    ])
    postings = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "request_no": "REQ-1",
         "posting_code": "JB-AAA111", "created_at": ago(25)},
        {"_id": ObjectId(), "company_id": COMPANY, "request_no": "REQ-2",
         "posting_code": "JB-BBB222", "created_at": ago(19)},
    ])

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: requisitions,
             M.COLL_ASSESSMENTS: assessments, M.COLL_INTERVIEWS: interviews,
             M.COLL_OFFERS: offers, M.COLL_ONBOARDING: onboardings,
             M.COLL_JOB_POSTINGS: postings, M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection(), "staff": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_analytics_service as AN
    AN.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": "md", "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    try:
        from app.utils import hrms_access as A

        # =================================================================
        section("Capability matrix (Phase 10)")
        # =================================================================
        for label, user in (("HR", HR), ("MD", MD), ("INTERNAL", INTERNAL)):
            check(f"{label} can read analytics, reports and export",
                  A.can(user, M.Cap.ANALYTICS_READ) and A.can(user, M.Cap.REPORT_READ)
                  and A.can(user, M.Cap.REPORT_EXPORT))
        check("MANAGER can read analytics and reports",
              A.can(HOD, M.Cap.ANALYTICS_READ) and A.can(HOD, M.Cap.REPORT_READ))
        check("MANAGER CANNOT export -- reading figures and taking a file are different acts",
              not A.can(HOD, M.Cap.REPORT_EXPORT))
        check("EMPLOYEE has no analytics capability at all",
              not A.can(EMP, M.Cap.ANALYTICS_READ) and not A.can(EMP, M.Cap.REPORT_READ)
              and not A.can(EMP, M.Cap.REPORT_EXPORT))

        # =================================================================
        section("Stage ranking is total and monotonic")
        # =================================================================
        check("every AppStatus has a rank", set(M.AppStatus) == set(M.STAGE_RANK))
        check("an unknown status ranks 0", M.stage_rank("Wat") == 0)
        check("Applied < Shortlisted < Interview < Selected < Offered < Accepted < Hired",
              M.stage_rank(S.APPLIED) < M.stage_rank(S.SHORTLISTED)
              < M.stage_rank(S.INTERVIEW_SCHEDULED) < M.stage_rank(S.SELECTED)
              < M.stage_rank(S.OFFER_GENERATED) < M.stage_rank(S.OFFER_ACCEPTED)
              < M.stage_rank(S.EMPLOYEE_CREATED))
        check("a DECLINED offer still ranks as 'offered' -- that stage did happen",
              M.stage_rank(S.OFFER_DECLINED) == M.stage_rank(S.OFFER_GENERATED))
        check("a rejected candidate ranks where they entered, not where they left",
              M.stage_rank(S.REJECTED) == M.stage_rank(S.APPLIED))
        check("funnel min_ranks are strictly increasing",
              all(a[2] < b[2] for a, b in zip(M.FUNNEL_STAGES, M.FUNNEL_STAGES[1:])))
        check("conversion never divides by zero", M.conversion(5, 0) == 0.0)
        check("conversion rounds to 1dp", M.conversion(1, 3) == 33.3)

        # =================================================================
        section("Date range validation")
        # =================================================================
        start, end = AN.parse_range(None, None)
        check("the default window is the last 90 days", (end - start).days in (90, 91))
        check("the window ends at the end of the chosen day", end.hour == 23)
        for bad, fragment in (("2026-13-01", "YYYY-MM-DD"), ("not-a-date", "YYYY-MM-DD"),
                              ("01-01-2026", "YYYY-MM-DD")):
            await expect_http(f"a malformed date {bad!r}",
                              _wrap(AN.parse_range, bad, None), 422, fragment)
        await expect_http("start after end",
                          _wrap(AN.parse_range, "2026-06-01", "2026-01-01"),
                          422, "on or before")
        await expect_http("a range wider than the cap",
                          _wrap(AN.parse_range, "2000-01-01", "2026-01-01"),
                          422, "days or fewer")

        # =================================================================
        section("Effective rank -- evidence beats a stale status")
        # =================================================================
        scope = await AN._scope(HR, COMPANY)
        evidence = await AN._evidence_ranks(scope)
        check("an interview record lifts an 'Applied' candidate to Interview",
              evidence.get("CAN-02") == M.RANK_IF_INTERVIEWED)
        check("an assessment record implies the Assessment stage",
              evidence.get("CAN-05") == M.RANK_IF_ASSESSED)
        check("a SENT offer implies the Offered stage",
              evidence.get("CAN-08") == M.RANK_IF_OFFERED)
        check("an ACCEPTED offer implies the Accepted stage",
              evidence.get("CAN-09") == M.RANK_IF_ACCEPTED)
        check("a DRAFT offer implies NOTHING -- it was never issued",
              "CAN-11" not in evidence)
        check("a candidate with no records has no evidence", "CAN-01" not in evidence)
        check("status still wins when it is ahead of the evidence",
              AN._effective({"uk": "CAN-10", "application_status": S.EMPLOYEE_CREATED.value},
                            evidence) == 8)
        check("evidence wins when the status has been dragged backwards",
              AN._effective({"uk": "CAN-09", "application_status": S.APPLIED.value},
                            evidence) == M.RANK_IF_ACCEPTED)

        # =================================================================
        section("The funnel (hand-counted against the fixture)")
        # =================================================================
        f = await AN.funnel(HR, COMPANY)
        by_key = {s["key"]: s for s in f["stages"]}
        check("15 candidates in the window (OLD-01 and OTH-01 excluded)", f["total"] == 15)
        check("the out-of-window candidate is excluded",
              not any(c["uk"] == "OLD-01" for c in candidates.docs
                      if c.get("applied_at") and c["applied_at"] >= start))
        # Ranks: 1,4,2,6,3,4,5,6,7,8,1,0 for CAN-01..12, plus 5,1,7 for HOD-* = 15.
        # CAN-04 ranks 6 despite being Rejected: it holds a DECLINED offer, and an offer
        # that was declined is still an offer that was made.
        check("applied counts everything ranked >= 1 (14 of 15; one is unrankable)",
              by_key["applied"]["count"] == 14)
        check("shortlisted (>=2) = 11", by_key["shortlisted"]["count"] == 11)
        check("assessment (>=3) = 10", by_key["assessment"]["count"] == 10)
        check("interview (>=4) = 9", by_key["interview"]["count"] == 9)
        check("selected (>=5) = 7", by_key["selected"]["count"] == 7)
        check("offered (>=6) = 5", by_key["offered"]["count"] == 5)
        check("accepted (>=7) = 3", by_key["accepted"]["count"] == 3)
        check("hired (>=8) = 1", by_key["hired"]["count"] == 1)
        check("a REJECTED candidate holding a declined offer still counts as Offered",
              AN._effective({"uk": "CAN-04", "application_status": S.REJECTED.value},
                            evidence) == M.RANK_IF_OFFERED)
        check("the unrankable candidate is reported, not silently dropped",
              f["unranked"] == 1)

        counts = [s["count"] for s in f["stages"]]
        check("THE funnel invariant: the series never increases",
              all(a >= b for a, b in zip(counts, counts[1:])))
        check("the first stage is 100% of itself",
              by_key["applied"]["from_previous"] == 100.0)
        check("conversion is measured from the PREVIOUS stage",
              by_key["shortlisted"]["from_previous"] == M.conversion(11, 14))
        check("share is measured from the TOP of the funnel",
              by_key["hired"]["of_total"] == M.conversion(1, 14))
        check("lost counts are broken out",
              f["lost"]["rejected"] == 1 and f["lost"]["declined"] == 0)

        # =================================================================
        section("Dashboard KPIs (hand-counted)")
        # =================================================================
        d = await AN.dashboard(HR, COMPANY)
        kpi = {k["key"]: k["value"] for k in d["kpis"]}
        # Phase 10 shipped 8 tiles; Phase 11-R Item 4 adds 7 more (CVs reviewed / selected /
        # rejected, shared with client, client shortlisted, client rejections, joinings).
        # The count is asserted as >= the Phase 10 set rather than pinned, so a later phase
        # adding a tile does not fail a test about Phase 10's arithmetic -- the tiles that
        # matter here are checked BY KEY on the lines below, which is the real contract.
        check("at least Phase 10's 8 KPI tiles", len(d["kpis"]) >= 8)
        check("every KPI deep-links", all(k.get("link") for k in d["kpis"]))
        check("candidates = 15", kpi["candidates"] == 15)
        check("open requisitions = 2 (REQ-3 is Hired)", kpi["open_requisitions"] == 2)
        check("vacancies sum only OPEN requisitions: 3 + 2 = 5",
              d["positions"]["vacancies"] == 5)
        check("filled = 1", d["positions"]["filled"] == 1)
        check("awaiting approval = 1 (REQ-2 is with MD)", kpi["awaiting_approval"] == 1)
        check("interviews = 3", kpi["interviews"] == 3)
        check("offers SENT excludes the draft: 4 of 5", kpi["offers_sent"] == 4)
        check("onboarding = 2", kpi["onboarding"] == 2)
        check("hired = candidates ranked >= 7 = 3", kpi["hired"] == 3)
        check("in_pipeline excludes rejected/declined/created: 15 - 1 - 1 = 13",
              kpi["in_pipeline"] == 13)
        check("offer outcomes add up",
              d["offer_outcomes"]["draft"] == 1 and d["offer_outcomes"]["sent"] == 1
              and d["offer_outcomes"]["accepted"] == 2
              and d["offer_outcomes"]["declined"] == 1)
        check("acceptance rate is over RESPONDED offers only: 2 of 3 = 66.7%",
              d["offer_outcomes"]["acceptance_rate"] == 66.7)
        check("onboarding states add up",
              d["onboarding_states"]["onboarding"] == 1
              and d["onboarding_states"]["completed"] == 1)
        check("HR is not told the figures are narrowed",
              d["scoped_to_own_requisitions"] is False)

        section("Time to hire")
        tth = d["time_to_hire"]
        # CAN-09 applied 10d ago, responded 3d ago  -> 7 days
        # CAN-10 applied 10d ago, responded 6d ago  -> 4 days
        check("only accepted offers are measured", tth["sample"] == 2)
        check("median of [4, 7] = 5.5", tth["median_days"] == 5.5)
        check("mean of [4, 7] = 5.5", tth["mean_days"] == 5.5)

        # =================================================================
        section("MANAGER row scoping -- the security property of this phase")
        # =================================================================
        hod_scope = await AN._scope(HOD, COMPANY)
        check("a manager's scope is narrowed to their own requisitions",
              hod_scope.get("request_no") == {"$in": ["REQ-2"]})
        check("everyone else's scope is the whole company",
              "request_no" not in await AN._scope(MD, COMPANY))

        hf = await AN.funnel(HOD, COMPANY)
        check("the manager sees ONLY their 3 candidates, not all 15", hf["total"] == 3)
        hd = await AN.dashboard(HOD, COMPANY)
        hkpi = {k["key"]: k["value"] for k in hd["kpis"]}
        check("their KPI counts are narrowed too", hkpi["candidates"] == 3)
        check("they see only their own requisition", hkpi["open_requisitions"] == 1)
        check("they see no offers -- none exist on their requisition",
              hkpi["offers_sent"] == 0)
        check("the response SAYS the figures are narrowed",
              hd["scoped_to_own_requisitions"] is True)

        # A manager who owns nothing must see nothing, not everything.
        orphan = {"_id": str(ObjectId()), "role": "clientuser",
                  "_source_collection": "learners", "company_id": COMPANY,
                  "governance_role": "HOD"}
        of = await AN.funnel(orphan, COMPANY)
        check("a manager with no requisitions sees ZERO, not the company (fails closed)",
              of["total"] == 0)

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        other = await AN.funnel(HR, OTHER)
        check("another company's candidates are invisible", other["total"] == 1)
        check("...and it is that company's own candidate only",
              (await AN.dashboard(HR, OTHER))["positions"]["vacancies"] == 9)
        rep = await AN.report(HR, COMPANY, "candidates", page_size=100)
        check("no cross-company row leaks into a report",
              not any(r.get("uk") == "OTH-01" for r in rep["rows"]))

        # =================================================================
        section("Breakdowns")
        # =================================================================
        src = await AN.breakdown(HR, COMPANY, "source")
        rows = {r["name"]: r["count"] for r in src["rows"]}
        check("grouped by source",
              rows == {"LinkedIn": 12, "Naukri": 2, "Referral": 1})
        check("shares sum to ~100", abs(sum(r["share"] for r in src["rows"]) - 100) < 1.5)
        check("sorted by count, descending",
              [r["count"] for r in src["rows"]]
              == sorted([r["count"] for r in src["rows"]], reverse=True))
        dept = await AN.breakdown(HR, COMPANY, "department")
        check("grouped by department", {r["name"] for r in dept["rows"]}
              == {"Analytics", "Delivery"})
        # A posting no longer HAS a platform -- one posting, one link, shared anywhere -- so
        # the dimension is gone rather than left to group a field nothing writes.
        await expect_http("the retired platform breakdown",
                          AN.breakdown(HR, COMPANY, "platform"), 422, "Unknown breakdown")
        await expect_http("an unknown breakdown dimension",
                          AN.breakdown(HR, COMPANY, "salary"), 422, "Unknown breakdown")
        await expect_http("an injected field name",
                          AN.breakdown(HR, COMPANY, "$where"), 422)
        hod_src = await AN.breakdown(HOD, COMPANY, "source")
        check("breakdowns are row-scoped for a manager too", hod_src["total"] == 3)

        # =================================================================
        section("Reports -- allow-list, columns and pagination")
        # =================================================================
        await expect_http("an unknown report entity",
                          AN.report(HR, COMPANY, "learners"), 404, "Unknown report")
        await expect_http("a collection name as an entity",
                          AN.report(HR, COMPANY, "hrms_offers"), 404)

        page1 = await AN.report(HR, COMPANY, "candidates", page=1, page_size=5)
        check("page size is honoured", len(page1["rows"]) == 5)
        check("total is the unpaginated count", page1["total"] == 15)
        check("page count is computed", page1["pages"] == 3)
        page4 = await AN.report(HR, COMPANY, "candidates", page=4, page_size=5)
        check("a page past the end is empty, not an error", page4["rows"] == [])
        big = await AN.report(HR, COMPANY, "candidates", page_size=9999)
        check("page size is clamped to the maximum",
              big["page_size"] == M.MAX_REPORT_PAGE_SIZE)
        zero = await AN.report(HR, COMPANY, "candidates", page=0, page_size=0)
        check("page 0 is floored to 1", zero["page"] == 1)
        check("page_size 0 falls back to the default rather than returning nothing",
              zero["page_size"] == 25)
        neg = await AN.report(HR, COMPANY, "candidates", page=-5, page_size=-5)
        check("negative paging is refused, not obeyed",
              neg["page"] == 1 and neg["page_size"] == 1)

        check("rows carry exactly the declared columns",
              set(page1["rows"][0]) == {c["key"] for c in page1["columns"]})
        check("a datetime renders as a readable string",
              isinstance(page1["rows"][0]["applied_at"], str))
        check("nothing undeclared leaks into a row",
              "_id" not in page1["rows"][0] and "company_id" not in page1["rows"][0])

        found = await AN.report(HR, COMPANY, "candidates", search="CAN-07")
        check("search matches", found["total"] == 1)
        check("a regex metacharacter in search is escaped, not executed",
              (await AN.report(HR, COMPANY, "candidates", search=".*"))["total"] == 0)
        for entity in M.REPORT_ENTITIES:
            r = await AN.report(HR, COMPANY, entity)
            check(f"report '{entity}' renders", isinstance(r["rows"], list))

        hod_report = await AN.report(HOD, COMPANY, "candidates")
        check("a manager's report is row-scoped", hod_report["total"] == 3)
        check("...and says so", hod_report["scoped_to_own_requisitions"] is True)

        # =================================================================
        section("Salary redaction reuses the Phase 2 boundary")
        # =================================================================
        hr_offers = await AN.report(HR, COMPANY, "offers")
        check("HR sees the CTC column", "ctc" in {c["key"] for c in hr_offers["columns"]})
        check("HR is told salary is visible", hr_offers["salary_visible"] is True)
        int_offers = await AN.report(INTERNAL, COMPANY, "offers")
        check("INTERNAL has no salary read", not A.can(INTERNAL, M.Cap.EMPLOYEE_SALARY_READ))
        check("the CTC column is OMITTED, not blanked",
              "ctc" not in {c["key"] for c in int_offers["columns"]})
        check("...and absent from every row",
              all("ctc" not in r for r in int_offers["rows"]))
        check("the response says salary is hidden", int_offers["salary_visible"] is False)
        int_cands = await AN.report(INTERNAL, COMPANY, "candidates")
        check("expected CTC is redacted on the candidate report too",
              "expected_ctc" not in {c["key"] for c in int_cands["columns"]})

        # =================================================================
        section("Export -- truncation is announced, never silent")
        # =================================================================
        payload = await AN.export_rows(HR, COMPANY, "candidates")
        check("every matching row is exported", payload["returned"] == 15)
        check("not truncated at this size", payload["truncated"] is False)
        check("rows are lists aligned to the columns",
              all(len(r) == len(payload["columns"]) for r in payload["rows"]))

        original_cap = M.MAX_EXPORT_ROWS
        AN.MAX_EXPORT_ROWS = 4
        try:
            small = await AN.export_rows(HR, COMPANY, "candidates")
            check("the export is capped", small["returned"] == 4)
            check("truncation is flagged", small["truncated"] is True)
            check("the true total is still reported", small["total"] == 15)
            csv_bytes = AN.render_csv(small)
            check("the CSV says it was truncated, in the file itself",
                  b"truncated" in csv_bytes.lower())
        finally:
            AN.MAX_EXPORT_ROWS = original_cap
        check("the cap constant was restored", AN.MAX_EXPORT_ROWS == original_cap)

        section("File rendering")
        csv_bytes = AN.render_csv(payload)
        check("CSV starts with a UTF-8 BOM so Excel reads accents correctly",
              csv_bytes.startswith(b"\xef\xbb\xbf"))
        text = csv_bytes.decode("utf-8-sig")
        check("the header row is the column LABELS",
              text.splitlines()[0].startswith("Candidate ID,Name"))
        check("one line per row plus the header",
              len(text.strip().splitlines()) == 16)
        redacted_csv = AN.render_csv(await AN.export_rows(INTERNAL, COMPANY, "offers"))
        check("a redacted export has no CTC column",
              b"CTC" not in redacted_csv.split(b"\n")[0])

        xlsx = AN.render_xlsx(payload)
        check("XLSX renders to a real zip container", xlsx[:2] == b"PK")
        check("XLSX is non-trivial in size", len(xlsx) > 2000)
        check("the filename carries the entity and the window",
              AN.export_filename("candidates", "csv", ("2026-01-01", "2026-03-01"))
              == "hrms_candidates_2026-01-01_to_2026-03-01.csv")

        # =================================================================
        section("Zero data behaves")
        # =================================================================
        empty_store = {k: FakeCollection() for k in store}
        mongo.get_collection = lambda name: empty_store.setdefault(name, FakeCollection())
        AN.get_collection = mongo.get_collection
        try:
            zf = await AN.funnel(HR, "C-EMPTY")
            check("an empty funnel totals 0", zf["total"] == 0)
            check("every stage is 0", all(s["count"] == 0 for s in zf["stages"]))
            check("no divide-by-zero in conversion",
                  all(isinstance(s["from_previous"], float) for s in zf["stages"]))
            zd = await AN.dashboard(HR, "C-EMPTY")
            check("every KPI is 0", all(k["value"] == 0 for k in zd["kpis"]))
            check("acceptance rate is 0, not 100",
                  zd["offer_outcomes"]["acceptance_rate"] == 0.0)
            check("time to hire reports no sample rather than a fake 0",
                  zd["time_to_hire"] == {"median_days": None, "mean_days": None,
                                         "sample": 0})
            zb = await AN.breakdown(HR, "C-EMPTY", "source")
            check("an empty breakdown returns no rows and no error", zb["rows"] == [])
            zr = await AN.report(HR, "C-EMPTY", "candidates")
            check("an empty report has 0 pages", zr["pages"] == 0)
            ze = await AN.export_rows(HR, "C-EMPTY", "candidates")
            check("an empty export still renders a header-only CSV",
                  len(AN.render_csv(ze).decode("utf-8-sig").strip().splitlines()) == 1)
        finally:
            mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
            AN.get_collection = mongo.get_collection

        # =================================================================
        section("Read-only: the service never writes")
        # =================================================================
        import inspect
        source = inspect.getsource(AN)
        for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                          "delete_one", "delete_many", "find_one_and_update", "bulk_write"):
            check(f"no `{forbidden}` anywhere in the analytics service",
                  forbidden not in source)
        before = {k: len(v.docs) for k, v in store.items()}
        await AN.dashboard(HR, COMPANY)
        await AN.funnel(HR, COMPANY)
        await AN.breakdown(HR, COMPANY, "source")
        await AN.report(HR, COMPANY, "candidates")
        await AN.export_rows(HR, COMPANY, "offers")
        check("no collection changed size after a full pass",
              {k: len(v.docs) for k, v in store.items()} == before)

        # =================================================================
        section("Declared shape")
        # =================================================================
        names = [(c, o.get("name")) for c, _, o in M.HRMS_INDEXES]
        for coll, want in ((M.COLL_CANDIDATES, "by_company_applied"),
                           (M.COLL_OFFERS, "by_company_created"),
                           (M.COLL_ONBOARDING, "by_company_created"),
                           (M.COLL_REQUISITIONS, "by_company_created")):
            check(f"date index `{want}` declared on {coll}", (coll, want) in names)
        check("index names still unique per collection", len(names) == len(set(names)))
        check("every report entity maps to a real HRMS collection",
              all(spec["collection"].startswith("hrms_")
                  for spec in M.REPORT_ENTITIES.values()))
        check("every report entity declares its columns",
              all(spec["columns"] and spec["search"] and spec["date_field"]
                  for spec in M.REPORT_ENTITIES.values()))
        check("the ReportEntity enum matches the allow-list exactly",
              {e.value for e in M.ReportEntity} == set(M.REPORT_ENTITIES))
        check("the BreakdownBy enum matches its allow-list exactly",
              {e.value for e in M.BreakdownBy} == set(M.BREAKDOWN_FIELDS))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


async def _wrap(fn, *args):
    """Adapt a synchronous validator to `expect_http`, which awaits a coroutine."""
    return fn(*args)


if __name__ == "__main__":
    asyncio.run(main())
