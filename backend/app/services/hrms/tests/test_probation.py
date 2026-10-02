"""Internal recruitment track -- induction, probation and personnel-file closure.

Covers: the Day-1 induction items appended to an internal onboarding only, probation records
opened automatically at joining, the review lifecycle (confirm / extend / terminate), the
requisition closing on confirmation, and personnel-file closure.

The design decision this file protects: PROBATION IS AN EMPLOYEE EVENT, NOT A CANDIDATE
STAGE. `Employee Created` stays terminal, `AppStatus` gains nothing, and FORWARD_TRANSITIONS
is untouched -- so a hired employee still cannot be "rejected" on either track. That is
asserted directly, because the tempting alternative (one more status after Employee Created)
would have quietly opened ALWAYS_AVAILABLE on a terminal stage.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_probation   (from backend/)
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
TODAY = NOW.strftime("%Y-%m-%d")


def days(n: int) -> str:
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_HOD = str(ObjectId()), str(ObjectId()), str(ObjectId())

    profiles = FakeCollection([
        {"_id": ObjectId(), "employee_code": "EMP-2026-001", "company_id": COMPANY,
         "display_name": "Internal Joiner", "joined_on": days(-200),
         "reporting_manager_id": U_HOD, "request_no": "HR-REQ-2026-001",
         # Phase INT-15: the pointer back to the hire, so confirming can stamp it.
         "source_uk": "CAN-INTERNAL-1"},
        {"_id": ObjectId(), "employee_code": "EMP-2026-002", "company_id": COMPANY,
         "display_name": "Second Joiner", "joined_on": days(-10),
         "request_no": "HR-REQ-2026-001"},
        {"_id": ObjectId(), "employee_code": "EMP-2026-003", "company_id": COMPANY,
         "display_name": "Third Joiner", "joined_on": days(-400),
         "request_no": "HR-REQ-2026-003"},
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Cancelled Role",
         "approval_status": "Approved", "closing_status": "Cancel", "created_at": NOW},
    ])
    probations = FakeCollection()
    audit_log = FakeCollection()
    candidates = FakeCollection([
        {"uk": "CAN-INTERNAL-1", "company_id": COMPANY, "candidate_name": "Internal Joiner",
         "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.EMPLOYEE_CREATED.value},
    ])

    store = {M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_REQUISITIONS: reqs,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_COUNTERS: FakeCollection(),
             M.COLL_CANDIDATES: candidates,
             M.COLL_AUDIT_LOG: audit_log, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_probation_service as PB
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (PB, AUD, IDS):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "MD", "full_name": "Meera MD"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}

    try:
        # =================================================================
        section("Phase INT-15: the one post-hire edge, and nothing else")
        # =================================================================
        # A hire may now advance to `Probation Confirmed` -- and to NOTHING else. The whole
        # risk of this change was ALWAYS_AVAILABLE leaking Rejected/On Hold/Duplicate into a
        # stage the CLIENT track shares, so that is what these checks are really about.
        check("Probation Confirmed exists as a stage",
              "Probation Confirmed" in {s.value for s in M.AppStatus})
        check("it is the ONLY thing reachable from a hire",
              M.allowed_next_statuses(M.AppStatus.EMPLOYEE_CREATED)
              == {M.AppStatus.PROBATION_CONFIRMED})
        for blocked in (M.AppStatus.REJECTED, M.AppStatus.ON_HOLD, M.AppStatus.DUPLICATE):
            check(f"a hired employee still cannot be '{blocked.value}'",
                  not M.can_transition(M.AppStatus.EMPLOYEE_CREATED.value, blocked.value))
        check("Employee Created is post-hire, not merely non-terminal",
              M.AppStatus.EMPLOYEE_CREATED in M.POST_HIRE_STATUSES)
        check("and the confirmation itself is terminal",
              M.AppStatus.PROBATION_CONFIRMED in M.TERMINAL_STATUSES
              and M.allowed_next_statuses(M.AppStatus.PROBATION_CONFIRMED) == set())
        check("nobody skips the hire to reach it",
              [s.value for s in M.AppStatus
               if M.can_transition(s.value, M.AppStatus.PROBATION_CONFIRMED.value)]
              == [M.AppStatus.EMPLOYEE_CREATED.value])
        check("the funnel gained no empty tail",
              max(M.STAGE_RANK.values()) == 8 and len(M.FUNNEL_STAGES) == 8)
        check("a confirmed hire still fills its vacancy",
              M.AppStatus.PROBATION_CONFIRMED in M.FILLED_STATUSES)

        # =================================================================
        section("Induction items -- appended to every onboarding")
        # =================================================================
        internal_list = M.seed_checklist()
        check("an onboarding gets the twelve base items plus the induction items",
              len(internal_list) == 12 + len(M.INDUCTION_CHECKLIST))
        check("they are APPENDED, so the base order is untouched",
              [i["key"] for i in internal_list][:12] == [k for k, _ in M.ONBOARD_CHECKLIST])
        check("and are flagged so the UI can group them",
              all(i.get("induction") for i in internal_list[12:]))
        check("induction feedback is one of them -- it feeds the KPI block",
              "induction_feedback" in {k for k, _ in M.INDUCTION_CHECKLIST})

        # =================================================================
        section("Opening a review")
        # =================================================================
        row = await PB.open_probation(HR, COMPANY, {"employee_code": "EMP-2026-001",
                                                    "started_on": days(-200)})
        PRB = row["prb_no"]
        check("a probation id is minted", PRB.startswith("PRB-"))
        check("it opens Pending", row["outcome"] == M.ProbationOutcome.PENDING.value)
        check("the default duration is the top of the SOP's 3-6 month range",
              row["duration_months"] == M.DEFAULT_PROBATION_MONTHS == 6)
        check("the end date is DERIVED, never typed",
              row["ends_on"] == PB._add_months(days(-200), 6))
        check("it carries the requisition, so analytics scoping reaches it",
              row["request_no"] == "HR-REQ-2026-001")
        check("and the candidate key, taken from the employee's own pointer (spec 35)",
              row["uk"] == "CAN-INTERNAL-1")
        check("a retention floor is stored (SOP 13: employment + 3 years)",
              row["retention_until"] > row["ends_on"])
        check("opening is audited",
              any(a["action"] == M.AUDIT_PROBATION_STARTED for a in audit_log.docs))

        await expect_http(
            "a second probation for the same employee",
            PB.open_probation(HR, COMPANY, {"employee_code": "EMP-2026-001"}),
            409, "already has a probation review")
        silent = await PB.open_probation(HR, COMPANY,
                                         {"employee_code": "EMP-2026-001"}, silent=True)
        check("the automatic opener is silent about one that already exists",
              silent is None)
        await expect_http(
            "a probation for an employee who does not exist",
            PB.open_probation(HR, COMPANY, {"employee_code": "EMP-9999"}),
            404, "No employee with that code")
        await expect_http(
            "a 24-month probation",
            PB.open_probation(HR, COMPANY, {"employee_code": "EMP-2026-002",
                                            "duration_months": 24}),
            422, "between 1 and 12 months")

        # =================================================================
        section("Date arithmetic clamps to the end of the month")
        # =================================================================
        check("31 Jan + 3 months is 30 April, not 31 April or 1 May",
              PB._add_months("2026-01-31", 3) == "2026-04-30")
        check("31 Dec + 1 month rolls the year",
              PB._add_months("2026-12-31", 1) == "2027-01-31")
        check("31 Mar + 11 months lands on 28 Feb in a common year",
              PB._add_months("2026-03-31", 11) == "2027-02-28")

        # =================================================================
        section("What is due, and what is overdue")
        # =================================================================
        await PB.open_probation(HR, COMPANY, {"employee_code": "EMP-2026-002",
                                              "started_on": days(-10),
                                              "duration_months": 1})
        due = await PB.due_probations(HR, COMPANY, within_days=30)
        overdue_codes = {r["employee_code"] for r in due["overdue"]}
        soon_codes = {r["employee_code"] for r in due["due_soon"]}
        check("a review whose end date has passed is OVERDUE",
              "EMP-2026-001" in overdue_codes)
        check("one falling due inside the window is DUE SOON",
              "EMP-2026-002" in soon_codes)
        check("the two are reported separately, not merged into one sorted list",
              not (overdue_codes & soon_codes))

        # ── §7.5 Stage 10, the rule the design calls out explicitly ──
        # "Completion of the probation period alone does NOT automatically confirm the
        # employee. Written/system confirmation through the approval process is required."
        overdue_row = await store[M.COLL_PROBATION_REVIEWS].find_one(
            {"prb_no": PRB, "company_id": COMPANY})
        check("a probation whose end date has PASSED is still Pending, not Confirmed",
              overdue_row["outcome"] == M.ProbationOutcome.PENDING.value
              and overdue_row["ends_on"] < days(0))
        check("nothing has stamped a confirmation on it",
              not overdue_row.get("signature") and not overdue_row.get("confirmed_by"))
        check("and the employee is not marked confirmed by the passage of time",
              (await candidates.find_one(
                  {"uk": "CAN-INTERNAL-1", "company_id": COMPANY}) or {}
               ).get("application_status") != M.AppStatus.PROBATION_CONFIRMED.value)
        check("the reminder sweep only reminds -- it holds no confirming code at all",
              "confirm_probation" not in __import__(
                  "inspect").getsource(
                  __import__("app.services.hrms_scheduler_service",
                             fromlist=["x"])))

        # =================================================================
        section("7.5 Stage 12: manager recommends, HR reviews, approver decides")
        # =================================================================
        GOOD_SCORES = {k: 4 for k in M.PROBATION_CRITERIA_KEYS}

        await expect_http(
            "deciding before anybody has reviewed it",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Confirmed", "signature": "Hari"}),
            409, "has not completed their review")
        await expect_http(
            "HR reviewing before the manager has recommended anything",
            PB.hr_review(HR, COMPANY, PRB,
                         {"decision": "Endorsed", "signature": "Hana"}),
            409, "no manager recommendation")

        await expect_http(
            "a review with no signature",
            PB.submit_review(HOD, COMPANY, PRB,
                             {**GOOD_SCORES, "recommendation": "Confirm"}),
            422, "Type your name")
        await expect_http(
            "a recommendation with a criterion left unscored",
            PB.submit_review(HOD, COMPANY, PRB,
                             {**{k: 4 for k in M.PROBATION_CRITERIA_KEYS[:-1]},
                              "recommendation": "Confirm", "signature": "Hari"}),
            422, "from 1 to 5")
        await expect_http(
            "an invented recommendation",
            PB.submit_review(HOD, COMPANY, PRB,
                             {**GOOD_SCORES, "recommendation": "Promote",
                              "signature": "Hari"}),
            422, "must be one of")
        await expect_http(
            "recommending separation with no reason",
            PB.submit_review(HOD, COMPANY, PRB,
                             {**GOOD_SCORES, "recommendation": "Separate",
                              "signature": "Hari"}),
            422, "Say why")

        reviewed = await PB.submit_review(HOD, COMPANY, PRB, {
            **GOOD_SCORES, "suitability": 5, "recommendation": "Confirm",
            "remarks": "Met the bar on every criterion.", "signature": "Hari HOD"})
        check("all five criteria are stored",
              all(k in reviewed["review"] for k in M.PROBATION_CRITERIA_KEYS))
        check("the average is derived, not typed",
              reviewed["review"]["average"] == round((4 * 4 + 5) / 5, 2))
        check("the recommendation is recorded as a recommendation",
              reviewed["review"]["recommendation"] == "Confirm")
        check("and attributed to the manager who made it",
              reviewed["review"]["by_name"] == "Hari HOD")
        check("a recommendation is NOT an outcome",
              reviewed["outcome"] == M.ProbationOutcome.PENDING.value)

        await expect_http(
            "approving a recommendation HR has not seen",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Confirmed", "signature": "Hari"}),
            409, "HR has not endorsed")

        returned = await PB.hr_review(HR, COMPANY, PRB, {
            "decision": "Returned", "remarks": "Attach the last two 1:1 notes.",
            "signature": "Hana HR"})
        check("HR can send a recommendation back",
              returned["hr_review"]["decision"] == "Returned")
        await expect_http(
            "approving a returned review",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Confirmed", "signature": "Hari"}),
            409, "returned this review")
        await expect_http(
            "returning without saying what to fix",
            PB.hr_review(HR, COMPANY, PRB,
                         {"decision": "Returned", "signature": "Hana"}),
            422, "Say what needs to change")

        # The manager resubmits, which invalidates the stale HR review.
        again = await PB.submit_review(HOD, COMPANY, PRB, {
            **GOOD_SCORES, "suitability": 5, "recommendation": "Confirm",
            "remarks": "1:1 notes attached.", "signature": "Hari HOD"})
        check("resubmitting clears the previous HR review rather than keeping it",
              again.get("hr_review") is None)

        endorsed = await PB.hr_review(HR, COMPANY, PRB, {
            "decision": "Endorsed", "signature": "Hana HR"})
        check("HR endorsement is recorded and signed",
              endorsed["hr_review"]["decision"] == "Endorsed"
              and endorsed["hr_review"]["signature"] == "Hana HR")
        check("endorsing still does not decide the probation",
              endorsed["outcome"] == M.ProbationOutcome.PENDING.value)

        # =================================================================
        section("Confirming")
        # =================================================================
        await expect_http(
            "confirming without signing",
            PB.confirm_probation(HOD, COMPANY, PRB, {"outcome": "Confirmed"}),
            422, "Type your name")
        await expect_http(
            "confirming with 'Pending' as the outcome",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Pending", "signature": "Hari"}),
            422, "not a decision")
        await expect_http(
            "a rating outside the 1-5 scale",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Confirmed", "rating": 9,
                                  "signature": "Hari"}),
            422, "1-5 scale")

        done = await PB.confirm_probation(HOD, COMPANY, PRB, {
            "outcome": "Confirmed", "rating": 4.2, "signature": "Hari HOD",
            "remarks": "Met the bar on every criterion."})
        check("the confirmation takes effect from the probation end date by default",
              done["effective_from"] == done["ends_on"])
        check("the manager recommendation survives beside the decision",
              done["review"]["recommendation"] == "Confirm")
        check("and so does the HR endorsement that cleared it",
              done["hr_review"]["decision"] == "Endorsed")
        check("the outcome is recorded",
              done["outcome"] == M.ProbationOutcome.CONFIRMED.value)
        check("it is signed and attributable", done["confirmed_by"] == U_HOD)
        check("confirmation is audited",
              any(a["action"] == M.AUDIT_PROBATION_CONFIRMED for a in audit_log.docs))

        profile = await profiles.find_one({"employee_code": "EMP-2026-001"})
        check("the EMPLOYEE record carries the outcome -- that is what a reader asks",
              profile["probation_status"] == M.ProbationOutcome.CONFIRMED.value)
        check("and points back at the review that decided it",
              profile["probation_prb_no"] == PRB)

        # -- Phase INT-15 -- the recruitment record learns how the hire turned out.
        cand = await candidates.find_one({"uk": "CAN-INTERNAL-1"})
        check("confirming moves the CANDIDATE to Probation Confirmed",
              cand["application_status"] == M.AppStatus.PROBATION_CONFIRMED.value)
        check("the stage change is audited like any other",
              any(a["action"] == M.AUDIT_STAGE_CHANGED
                  and a["entity_id"] == "CAN-INTERNAL-1"
                  and "Probation Confirmed" in a["detail"] for a in audit_log.docs))

        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("confirming CLOSES the internal requisition as Hired (SOP 7)",
              req["closing_status"] == M.ReqClosing.HIRED.value)
        check("and records which confirmation closed it",
              req["closed_on_probation_confirmation"] == PRB)

        await expect_http(
            "deciding an already-decided probation",
            PB.confirm_probation(HOD, COMPANY, PRB,
                                 {"outcome": "Terminated", "signature": "Hari"}),
            409, "already decided")
        await expect_http(
            "editing a decided probation",
            PB.update_probation(HR, COMPANY, PRB, {"notes": "second thoughts"}),
            409, "not a working document")

        # =================================================================
        section("Extending is more time, not a verdict")
        # =================================================================
        second = await probations.find_one({"employee_code": "EMP-2026-002"})
        PRB2 = second["prb_no"]
        # §7.5 Stage 12: an extension goes through the same chain a confirmation does.
        await PB.submit_review(HOD, COMPANY, PRB2, {
            **{k: 3 for k in M.PROBATION_CRITERIA_KEYS},
            "recommendation": "Extend",
            "remarks": "Progressing, but not yet consistent.", "signature": "Hari HOD"})
        await PB.hr_review(HR, COMPANY, PRB2,
                           {"decision": "Endorsed", "signature": "Hana HR"})
        await expect_http(
            "extending with no new end date",
            PB.confirm_probation(HOD, COMPANY, PRB2,
                                 {"outcome": "Extended", "signature": "Hari",
                                  "remarks": "Needs longer"}),
            422, "needs a new end date")
        await expect_http(
            "extending to a date BEFORE the current end",
            PB.confirm_probation(HOD, COMPANY, PRB2,
                                 {"outcome": "Extended", "extended_to": days(-5),
                                  "signature": "Hari", "remarks": "Needs longer"}),
            422, "must be after the current one")
        await expect_http(
            "extending with no reason",
            PB.confirm_probation(HOD, COMPANY, PRB2,
                                 {"outcome": "Extended", "extended_to": days(90),
                                  "signature": "Hari"}),
            422, "Record why")

        extended = await PB.confirm_probation(HOD, COMPANY, PRB2, {
            "outcome": "Extended", "extended_to": days(90), "signature": "Hari HOD",
            "remarks": "Two more months to show consistency."})
        check("an extension returns the review to PENDING, not a terminal 'Extended'",
              extended["outcome"] == M.ProbationOutcome.PENDING.value)
        check("the end date moves out", extended["ends_on"] == days(90))
        check("and the extension is counted", extended["extension_count"] == 1)
        check("so it will surface as due again when the new date nears",
              extended["outcome"] == M.ProbationOutcome.PENDING.value)

        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("an extension does NOT close the requisition",
              req["closing_status"] == M.ReqClosing.HIRED.value)  # closed by PRB earlier

        # =================================================================
        section("A closed requisition is not reopened")
        # =================================================================
        third = await PB.open_probation(HR, COMPANY, {"employee_code": "EMP-2026-003",
                                                      "started_on": days(-400)})
        await PB.submit_review(HOD, COMPANY, third["prb_no"], {
            **{k: 4 for k in M.PROBATION_CRITERIA_KEYS},
            "recommendation": "Confirm", "signature": "Hari HOD"})
        await PB.hr_review(HR, COMPANY, third["prb_no"],
                           {"decision": "Endorsed", "signature": "Hana HR"})
        await PB.confirm_probation(HOD, COMPANY, third["prb_no"], {
            "outcome": "Confirmed", "signature": "Hari HOD"})
        cancelled = await reqs.find_one({"request_no": "HR-REQ-2026-003"})
        check("a requisition someone CANCELLED stays cancelled",
              cancelled["closing_status"] == M.ReqClosing.CANCEL.value)

        # =================================================================
        section("Personnel-file closure")
        # =================================================================
        await expect_http(
            "closing a file with an empty note",
            PB.close_personnel_file(HR, COMPANY, {"employee_code": "EMP-2026-001",
                                                  "closure_note": "  "}),
            422, "closes nothing")
        await expect_http(
            "closing a file before probation is confirmed",
            PB.close_personnel_file(HR, COMPANY, {"employee_code": "EMP-2026-002",
                                                  "closure_note": "All present."}),
            409, "has not been confirmed yet")

        closed = await PB.close_personnel_file(
            HR, COMPANY, {"employee_code": "EMP-2026-001",
                          "closure_note": "Offer, joining documents, BGV and confirmation "
                                          "all filed."})
        check("the file closes once confirmation is on record",
              closed["personnel_file_closed"] is True)
        profile = await profiles.find_one({"employee_code": "EMP-2026-001"})
        check("the note is kept, not just a flag",
              "BGV" in profile["personnel_file_closure_note"])
        check("closure is audited",
              any(a["action"] == M.AUDIT_PERSONNEL_FILE_CLOSED for a in audit_log.docs))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
