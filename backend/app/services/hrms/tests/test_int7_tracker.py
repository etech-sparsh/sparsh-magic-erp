"""Phase INT-7 -- the internal requisition tracker (Annexure C, spec §35).

Annexure C's first efficiency item asks for "a shared internal requisition tracker (status,
scores, budget approval date) visible to HR, Department Head, and Management". The screen
existed and showed five columns. This covers the service that answers the question people
actually open a tracker with: where has everything got to, and what is late.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. IT NEVER WRITES. Asserted by grepping this module's source, exactly as the analytics
     read-only test does.
  2. IT IS BATCHED. Every collection is read ONCE for the page, not once per row. A tracker
     that issues eight queries per requisition gets slower with every vacancy ever raised.
  3. IT IS SCOPED LIKE THE LIST IT SITS BESIDE. A user must never see a row here they could
     not open there -- same company filter, same visibility rule.
  4. THE CLIENT TRACK IS ABSENT. This is the INTERNAL tracker; a client requisition has no
     budget gate, no scorecard and no shortlist committee to report on.
  5. THE SLA CELL SAYS WHAT IT COUNTS. It covers the milestone-anchored rows only, and the
     payload declares that rather than letting a reader assume it covers everything.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int7_tracker   (from backend/)
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

C1 = "COMPANY-ONE"
C2 = "COMPANY-TWO"
NOW = datetime.now(timezone.utc)


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    # `_source_collection` + `role` are what `hrms_role` reads first. Without them every
    # fake user resolves to None, `_visibility_filter` returns {} and the EMPLOYEE scoping
    # assertion below would pass for the wrong reason.
    HR = {"_id": ObjectId(), "full_name": "Priya HR", "email": "hr@example.com",
          "_source_collection": "learners", "role": "clientuser",
          "governance_role": "HR", "company_id": C1}
    EMP = {"_id": ObjectId(), "full_name": "Ravi Employee", "email": "emp@example.com",
           "_source_collection": "learners", "role": "clientuser",
           "governance_role": "IMPLEMENTOR", "company_id": C1}

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_tracker_service as TR
    import app.services.hrms_config_service as CFG
    import app.services.hrms_holiday_service as HOL
    import app.services.hrms_sla_service as SLA
    for mod in (TR, CFG, HOL, SLA):
        mod.get_collection = mongo.get_collection

    INT = "internal"

    reqs = store.setdefault(M.COLL_REQUISITIONS, FakeCollection())
    reqs.docs.extend([
        # R1 -- the full journey: budget approved, scorecard approved, candidates,
        # shortlist finalised, offer accepted, joined, on probation.
        {"request_no": "R1", "company_id": C1, "requisition_track": INT,
         "department_id": "D1", "department_name": "Operations",
         "designation_name": "Ops Executive", "designation_id": "66aa00000000000000000001",
         "vacancy": 2, "created_by_name": "Meera HOD", "assignee_name": "Priya HR",
         "created_at": ago(40), "required_date": "2026-10-01",
         "approval_status": M.ReqApproval.APPROVED.value,
         "closing_status": M.ReqClosing.OPEN.value,
         "budget_approved_at": ago(38), "budget_approved_by_name": "Anita MD",
         "approved_headcount": 2,
         "approved_salary_band_min": 400000, "approved_salary_band_max": 700000,
         "sla_actuals": {"budget_approved": ago(38), "scorecard_approved": ago(37),
                         "shortlist_ready": ago(20), "final_selection": ago(15),
                         "offer_released": ago(14)}},

        # R2 -- raised and stuck: no budget approval at all, and long overdue for one.
        {"request_no": "R2", "company_id": C1, "requisition_track": INT,
         "department_id": "D2", "department_name": "Finance",
         "designation_name": "Accounts Officer", "designation_level": "junior",
         "vacancy": 1, "created_by_name": "Sunil HOD",
         "created_at": ago(30),
         "approval_status": M.ReqApproval.PENDING_BUDGET.value,
         "closing_status": M.ReqClosing.OPEN.value,
         "budget_approved_at": None,
         "approved_salary_band_min": None, "approved_salary_band_max": None,
         "sla_actuals": {}},

        # R3 -- raised yesterday: nothing has happened yet and nothing is late.
        {"request_no": "R3", "company_id": C1, "requisition_track": INT,
         "department_id": "D1", "department_name": "Operations",
         "designation_name": "Ops Lead", "designation_level": "managerial",
         "vacancy": 1, "created_by_name": "Meera HOD",
         "created_at": ago(1),
         "approval_status": M.ReqApproval.PENDING_HR_VERIFICATION.value,
         "closing_status": M.ReqClosing.OPEN.value,
         "sla_actuals": {}},

        # A CLIENT-track requisition, and one belonging to another company.
        {"request_no": "RC", "company_id": C1, "designation_name": "Analyst",
         "created_at": ago(10), "approval_status": M.ReqApproval.APPROVED.value,
         "closing_status": M.ReqClosing.OPEN.value, "sla_actuals": {}},
        {"request_no": "RX", "company_id": C2, "requisition_track": INT,
         "designation_name": "Elsewhere", "created_at": ago(5),
         "approval_status": M.ReqApproval.APPROVED.value,
         "closing_status": M.ReqClosing.OPEN.value, "sla_actuals": {}},
    ])

    # The seniority band lives on the designation MASTER -- a requisition carries only
    # `designation_id`. The tracker resolves the band through the master with the model's
    # own reading, so an UNBANDED designation must read as the default (mid).
    store.setdefault(M.COLL_DESIGNATIONS, FakeCollection()).docs.extend([
        {"_id": "66aa00000000000000000001", "company_id": C1,
         "name": "Ops Executive"},                        # no band -> default (mid)
    ])

    store.setdefault(M.COLL_POSITION_SCORECARDS, FakeCollection()).docs.extend([
        {"scr_no": "SCR-001", "company_id": C1, "request_no": "R1",
         "status": M.ScorecardStatus.APPROVED.value},
        {"scr_no": "SCR-002", "company_id": C1, "request_no": "R2",
         "status": M.ScorecardStatus.DRAFT.value},
    ])
    store.setdefault(M.COLL_JOB_POSTINGS, FakeCollection()).docs.extend([
        {"company_id": C1, "request_no": "R1", "code": "AB-123XYZ"},
    ])
    store.setdefault(M.COLL_CANDIDATES, FakeCollection()).docs.extend([
        {"uk": "CAN-001", "company_id": C1, "request_no": "R1", "candidate_name": "A",
         "application_status": M.AppStatus.EMPLOYEE_CREATED.value},
        {"uk": "CAN-002", "company_id": C1, "request_no": "R1", "candidate_name": "B",
         "application_status": M.AppStatus.SELECTED.value},
        {"uk": "CAN-003", "company_id": C1, "request_no": "R1", "candidate_name": "C",
         "application_status": M.AppStatus.INTERVIEW_SCHEDULED.value},
        {"uk": "CAN-004", "company_id": C1, "request_no": "R1", "candidate_name": "D",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"uk": "CAN-005", "company_id": C1, "request_no": "R1", "candidate_name": "E",
         "application_status": M.AppStatus.APPLIED.value},
        {"uk": "CAN-006", "company_id": C1, "request_no": "R1", "candidate_name": "F",
         "application_status": M.AppStatus.REJECTED.value},
    ])
    store.setdefault(M.COLL_SHORTLIST_REVIEWS, FakeCollection()).docs.extend([
        {"slr_no": "SLR-001", "company_id": C1, "request_no": "R1",
         "outcome": M.ShortlistOutcome.PENDING.value, "decided_at": None},
        {"slr_no": "SLR-002", "company_id": C1, "request_no": "R1",
         "outcome": M.ShortlistOutcome.FINALISED.value, "decided_at": ago(20)},
    ])
    store.setdefault(M.COLL_INTERVIEWS, FakeCollection()).docs.extend([
        {"company_id": C1, "request_no": "R1", "status": M.InterviewStatus.COMPLETED.value},
        {"company_id": C1, "request_no": "R1", "status": M.InterviewStatus.COMPLETED.value},
        {"company_id": C1, "request_no": "R1", "status": M.InterviewStatus.SCHEDULED.value},
    ])
    store.setdefault(M.COLL_OFFERS, FakeCollection()).docs.extend([
        {"offer_no": "OFR-001", "company_id": C1, "request_no": "R1", "uk": "CAN-006",
         "candidate_name": "F", "status": M.OfferStatus.DECLINED.value},
        {"offer_no": "OFR-002", "company_id": C1, "request_no": "R1", "uk": "CAN-001",
         "candidate_name": "A", "status": M.OfferStatus.ACCEPTED.value,
         "joining_date": "2026-09-01"},
    ])
    store.setdefault(M.COLL_ONBOARDING, FakeCollection()).docs.extend([
        {"company_id": C1, "request_no": "R1", "joining_date": "2026-09-01"},
    ])
    store.setdefault(M.COLL_PROBATION_REVIEWS, FakeCollection()).docs.extend([
        {"prb_no": "PRB-001", "company_id": C1, "request_no": "R1",
         "ends_on": "2027-03-01", "outcome": M.ProbationOutcome.PENDING.value},
    ])
    store.setdefault(M.COLL_EXCEPTIONS, FakeCollection()).docs.extend([
        {"exc_no": "EXC-001", "company_id": C1, "request_no": "R1",
         "exception_type": M.ExceptionType.REFERENCE_WAIVED.value,
         "status": M.ExceptionStatus.APPROVED.value},
        {"exc_no": "EXC-002", "company_id": C1, "request_no": "R1",
         "exception_type": M.ExceptionType.EXTENDED_TAT.value,
         "status": M.ExceptionStatus.PENDING.value},
    ])

    # =========================================================================
    section("1. Scope -- internal track, this company, this user")
    # =========================================================================
    out = await TR.tracker(HR, C1)
    keys = [r["request_no"] for r in out["rows"]]
    check("three internal requisitions are tracked", len(out["rows"]) == 3)
    check("the CLIENT-track requisition is absent -- it has no budget gate, no scorecard "
          "and no shortlist committee for this tracker to report on", "RC" not in keys)
    check("the other company's requisition is absent", "RX" not in keys)
    check("all three are present", set(keys) == {"R1", "R2", "R3"})
    # FakeCursor.sort() is a no-op in the shared harness, so asserting the ORDER through it
    # would prove nothing either way. What is worth pinning is that the service asks for the
    # right one -- newest first, which is the order a tracker is read in.
    import inspect as _i
    check("the service sorts newest-first at the database, not in the browser",
          'sort("created_at", -1)' in _i.getsource(TR.tracker))
    check("the total counts the scoped set, not everything", out["total"] == 3)

    # -- The same visibility rule the requisition list uses --
    reqs.docs.append({"request_no": "R4", "company_id": C1, "requisition_track": INT,
                      "designation_name": "Raised by an employee",
                      "created_by": str(EMP["_id"]), "created_at": ago(2),
                      "approval_status": M.ReqApproval.PENDING_HR_VERIFICATION.value,
                      "closing_status": M.ReqClosing.OPEN.value, "sla_actuals": {}})
    emp_rows = (await TR.tracker(EMP, C1))["rows"]
    check("a plain EMPLOYEE sees only the requisition they raised -- the tracker cannot "
          "become a way around the list's own scoping",
          [r["request_no"] for r in emp_rows] == ["R4"])
    check("HR still sees all four", len((await TR.tracker(HR, C1))["rows"]) == 4)
    reqs.docs = [d for d in reqs.docs if d["request_no"] != "R4"]

    # =========================================================================
    section("2. The row -- every stage rolled up")
    # =========================================================================
    rows = {r["request_no"]: r for r in (await TR.tracker(HR, C1))["rows"]}
    r1 = rows["R1"]

    check("identity: department, position, level, seats -- the band resolved through "
          "the designation MASTER, and an unbanded designation reads as the default (mid), "
          "never as null",
          r1["department_name"] == "Operations"
          and r1["designation_name"] == "Ops Executive"
          and r1["designation_level"] == "mid" and r1["vacancy"] == 2)
    check("who raised it and who owns it",
          r1["raised_by_name"] == "Meera HOD" and r1["hr_owner_name"] == "Priya HR")

    check("budget: approved, when, by whom, and the band",
          r1["budget"]["approved"] is True
          and r1["budget"]["approved_by_name"] == "Anita MD"
          and r1["budget"]["band_min"] == 400000
          and r1["budget"]["band_max"] == 700000)
    check("Annexure C asks specifically for the BUDGET APPROVAL DATE, and it is there",
          r1["budget"]["approved_at"] is not None)

    check("scorecard: the APPROVED one is surfaced, not whichever was found first",
          r1["scorecard"]["approved"] is True
          and r1["scorecard"]["scr_no"] == "SCR-001")
    check("sourcing counts the postings", r1["sourcing"]["postings"] == 1)

    check("candidate counts are by STAGE RANK, so a rejected candidate is counted where "
          "they entered rather than inflating the shortlist",
          r1["candidates"]["total"] == 6
          and r1["candidates"]["shortlisted"] == 4
          and r1["candidates"]["interviewed"] == 3
          and r1["candidates"]["selected"] == 2
          and r1["candidates"]["joined"] == 1)

    check("shortlist: the FINALISED sitting wins over the pending one",
          r1["shortlist"]["status"] == M.ShortlistOutcome.FINALISED.value
          and r1["shortlist"]["slr_no"] == "SLR-002")
    check("interviews: total and completed",
          r1["interviews"]["total"] == 3 and r1["interviews"]["completed"] == 2)
    check("offer: the ACCEPTED one wins over the declined one -- history is real but a "
          "tracker cell should show the live offer",
          r1["offer"]["status"] == M.OfferStatus.ACCEPTED.value
          and r1["offer"]["offer_no"] == "OFR-002")
    check("joining date and probation end are carried",
          r1["joining_date"] == "2026-09-01" and r1["probation"]["ends_on"] == "2027-03-01")
    check("exceptions are split into open and approved -- one needs somebody to act, the "
          "other is a decision already taken",
          r1["exceptions"]["open"] == 1 and r1["exceptions"]["approved"] == 1
          and len(r1["exceptions"]["types"]) == 2)

    # -- A requisition with nothing against it reports empty, not missing --
    r3 = rows["R3"]
    check("a brand-new requisition reports zeroes rather than nulls a screen has to guess at",
          r3["candidates"]["total"] == 0 and r3["sourcing"]["postings"] == 0
          and r3["exceptions"]["open"] == 0)
    check("and no budget approval", r3["budget"]["approved"] is False)
    check("and no scorecard", r3["scorecard"]["approved"] is False
          and r3["scorecard"]["scr_no"] is None)

    # =========================================================================
    section("3. The SLA cell")
    # =========================================================================
    check("R2 was raised 30 days ago with no budget approval, so it is BREACHED",
          rows["R2"]["sla"]["status"] == "breached")
    check("and it names WHICH milestone",
          "budget_approved" in rows["R2"]["sla"]["breached"])
    check("and by how much", rows["R2"]["sla"]["days_over"] > 0)
    check("R3 was raised yesterday, so it is on track",
          rows["R3"]["sla"]["status"] == "on_track")
    check("and it names what is owed NEXT, so the row says what to do",
          rows["R3"]["sla"]["next_key"] == "budget_approved"
          and rows["R3"]["sla"]["next_due_on"] is not None)
    check("R1 met every milestone it reached", rows["R1"]["sla"]["status"] == "met")
    check("the payload DECLARES what the SLA cell counts rather than letting a reader "
          "assume it covers the per-joiner deadlines too",
          "milestone" in (await TR.tracker(HR, C1))["sla_basis"].lower())

    # -- It follows the company's configured targets (INT-5) --
    from bson import ObjectId as _OID
    MD = {"_id": _OID(), "full_name": "Anita MD"}
    import app.services.hrms_audit_service as AUD
    AUD.get_collection = mongo.get_collection
    # BOTH clocks that start at the raise date must move: R2 is 30 days old, so it is
    # overdue on the budget milestone AND the shortlist one. Raising only the budget target
    # would leave the row breached on the shortlist -- which is the tracker being right, not
    # the config being ignored.
    await CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"budget_approved": 90,
                                                                "shortlist_ready": 90}})
    rows2 = {r["request_no"]: r for r in (await TR.tracker(HR, C1))["rows"]}
    check("raising the company's targets to 90 days clears R2's breach -- the tracker "
          "reads the CONFIGURED targets, not the module defaults",
          rows2["R2"]["sla"]["status"] == "on_track")
    await CFG.reset_config(MD, C1)
    back = {r["request_no"]: r for r in (await TR.tracker(HR, C1))["rows"]}
    check("and resetting brings the breach back",
          back["R2"]["sla"]["status"] == "breached")

    # =========================================================================
    section("4. Filters")
    # =========================================================================
    check("by department",
          {r["request_no"] for r in (await TR.tracker(HR, C1, department_id="D1"))["rows"]}
          == {"R1", "R3"})
    check("by approval status",
          [r["request_no"] for r in
           (await TR.tracker(HR, C1, status=M.ReqApproval.PENDING_BUDGET.value))["rows"]]
          == ["R2"])
    check("by SLA health -- the question a tracker is opened with",
          [r["request_no"] for r in (await TR.tracker(HR, C1, sla="breached"))["rows"]]
          == ["R2"])
    paged = await TR.tracker(HR, C1, limit=2)
    check("paging returns a page and the full total",
          len(paged["rows"]) == 2 and paged["total"] == 3)
    check("the page size is capped", (await TR.tracker(HR, C1, limit=9999))["limit"]
          == TR.MAX_TRACKER_ROWS)

    # =========================================================================
    section("5. It never writes, and it does not fan out per row")
    # =========================================================================
    import inspect
    source = inspect.getsource(TR)
    for token in ("insert_", "update_", "delete_"):
        check(f"the tracker source contains no `{token}` -- a tracker that writes is not a "
              f"tracker", token not in source)

    reads = {"n": 0}
    real_find = FakeCollection.find

    def counting_find(self, query=None, projection=None):
        reads["n"] += 1
        return real_find(self, query, projection)

    FakeCollection.find = counting_find
    await TR.tracker(HR, C1)
    with_three = reads["n"]

    # Double the requisitions; the read count must not double with them.
    for n in range(4, 12):
        reqs.docs.append({"request_no": f"R{n}", "company_id": C1,
                          "requisition_track": INT, "designation_name": f"Role {n}",
                          "created_at": ago(3), "sla_actuals": {},
                          "approval_status": M.ReqApproval.APPROVED.value,
                          "closing_status": M.ReqClosing.OPEN.value})
    reads["n"] = 0
    out = await TR.tracker(HR, C1)
    with_eleven = reads["n"]
    FakeCollection.find = real_find

    check("eleven requisitions are tracked", len(out["rows"]) == 11)
    check(f"and the read count did not grow with them ({with_three} -> {with_eleven}) -- "
          f"every collection is read ONCE for the page", with_eleven == with_three)
    check("the read count is a small constant, not a multiple of the row count",
          with_eleven <= 12)

    # -- An empty page short-circuits rather than issuing $in: [] reads --
    reads["n"] = 0
    FakeCollection.find = counting_find
    empty = await TR.tracker(HR, "COMPANY-WITH-NOTHING")
    FakeCollection.find = real_find
    check("a company with no internal requisitions returns an empty page",
          empty["rows"] == [] and empty["total"] == 0)
    check("and issues no follow-up reads at all", reads["n"] <= 1)
    check("while still declaring its basis", bool(empty["sla_basis"]))

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
