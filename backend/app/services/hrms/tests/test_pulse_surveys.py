"""30-day and 90-day pulse surveys (BA/Functional Design 22.4, business rule BR-027).

The rule this file exists to protect is BR-027: THE SURVEYS ARE ANCHORED TO THE ACTUAL DOJ
AND NOTHING ELSE. They must not shift, and must not vanish, because some other part of
onboarding finished early or was never created at all -- a closed checklist, a confirmed
probation, an absent orientation plan. The sweep therefore reads `joined_on` off the
employee profile directly, and these checks assert that it keeps firing with every one of
those neighbouring records closed or missing.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_pulse_surveys   (from backend/)
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print("  " + ("PASS" if condition else "FAIL") + "  " + label)
    return bool(condition)


def section(title: str) -> None:
    print("\n-- " + title + " --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


def days(n: int) -> str:
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    profiles = FakeCollection([
        # Just short of 30 days -- nothing is due for them yet.
        {"_id": ObjectId(), "employee_code": "EMP-001", "company_id": COMPANY,
         "display_name": "Too Early", "joined_on": days(-29),
         "employment_status": "Active"},
        # Past 30, short of 90.
        {"_id": ObjectId(), "employee_code": "EMP-002", "company_id": COMPANY,
         "display_name": "Thirty Day", "joined_on": days(-31),
         "employment_status": "Active"},
        # Past both.
        {"_id": ObjectId(), "employee_code": "EMP-003", "company_id": COMPANY,
         "display_name": "Ninety Day", "joined_on": days(-95),
         "employment_status": "Active"},
        # Past both, but gone -- a leaver is not surveyed.
        {"_id": ObjectId(), "employee_code": "EMP-004", "company_id": COMPANY,
         "display_name": "Resigned Person", "joined_on": days(-95),
         "employment_status": "Resigned"},
        # No joining date at all: skipped, never crashed on.
        {"_id": ObjectId(), "employee_code": "EMP-005", "company_id": COMPANY,
         "display_name": "No DOJ", "joined_on": None,
         "employment_status": "Active"},
    ])
    responses = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_PULSE_RESPONSES: responses,
             M.COLL_AUDIT_LOG: audit_log, M.COLL_SETTINGS: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_pulse_service as PS
    import app.services.hrms_audit_service as AUD
    for mod in (PS, AUD):
        mod.get_collection = mongo.get_collection

    try:
        D30 = M.PulseMilestone.DAY_30.value
        D90 = M.PulseMilestone.DAY_90.value

        # =================================================================
        section("The milestones are 30 and 90 days, measured from the DOJ")
        # =================================================================
        check("the module knows exactly two milestones",
              set(PS.MILESTONE_DAYS) == {D30, D90})
        check("and they are 30 and 90 days",
              PS.MILESTONE_DAYS[D30] == 30 and PS.MILESTONE_DAYS[D90] == 90)

        # =================================================================
        section("Issuance is driven by the DOJ alone")
        # =================================================================
        out = await PS.run_issue_sweep(COMPANY)
        issued = {(r["employee_code"], r["milestone"]) for r in responses.docs}

        check("somebody 29 days in gets nothing yet",
              ("EMP-001", D30) not in issued)
        check("somebody 31 days in gets their 30-day survey",
              ("EMP-002", D30) in issued)
        check("and not the 90-day one they have not reached",
              ("EMP-002", D90) not in issued)
        check("somebody 95 days in gets BOTH -- a missed milestone is not lost",
              ("EMP-003", D30) in issued and ("EMP-003", D90) in issued)
        check("a resigned employee is not surveyed",
              not any(code == "EMP-004" for code, _ in issued))
        check("an employee with no joining date is skipped, not crashed on",
              not any(code == "EMP-005" for code, _ in issued))
        check("the sweep reports what it did", out["issued"] == len(issued))
        check("each issue opens Issued, not answered",
              all(r["status"] == M.PulseResponseStatus.ISSUED.value
                  for r in responses.docs))
        check("issuance is audited",
              any(a["action"] == M.AUDIT_PULSE_ISSUED for a in audit_log.docs))

        # =================================================================
        section("Re-running does not re-issue")
        # =================================================================
        before = len(responses.docs)
        await PS.run_issue_sweep(COMPANY)
        check("a second sweep on the same day issues nothing new",
              len(responses.docs) == before)

        # =================================================================
        section("BR-027: closing other onboarding work does not cancel a survey")
        # =================================================================
        # Everything a survey might wrongly have been made to depend on, closed or absent.
        store[M.COLL_ONBOARDING] = FakeCollection([
            {"onb_no": "ONB-1", "company_id": COMPANY, "employee_code": "EMP-006",
             "status": M.OnboardStatus.COMPLETED.value,
             "checklist": [{"key": "induction", "done": True}]},
        ])
        store[M.COLL_PROBATION_REVIEWS] = FakeCollection([
            {"prb_no": "PRB-1", "company_id": COMPANY, "employee_code": "EMP-006",
             "outcome": M.ProbationOutcome.CONFIRMED.value},
        ])
        # ...and no orientation assignment at all for this person.
        await profiles.insert_one(
            {"_id": ObjectId(), "employee_code": "EMP-006", "company_id": COMPANY,
             "display_name": "Everything Closed Early", "joined_on": days(-95),
             "employment_status": "Active"})

        await PS.run_issue_sweep(COMPANY)
        after = {(r["employee_code"], r["milestone"]) for r in responses.docs}
        check("a completed onboarding does not suppress the 30-day survey",
              ("EMP-006", D30) in after)
        check("nor a confirmed probation the 90-day one",
              ("EMP-006", D90) in after)

        src = inspect.getsource(PS.run_issue_sweep)
        check("the sweep reads the employee profile, nothing task-shaped",
              "COLL_EMPLOYEE_PROFILES" in src)
        check("and never consults onboarding, probation or orientation",
              not any(w in src for w in
                      ("COLL_ONBOARDING", "checklist", "PROBATION", "orientation")))

        # =================================================================
        section("The questions are the company's own")
        # =================================================================
        questions = await PS.get_questions(COMPANY)
        check("a company with none configured falls back to the defaults",
              list(questions) == list(M.DEFAULT_PULSE_QUESTIONS))

    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print("\n" + "=" * 60)
    print("  " + str(passed) + "/" + str(total) + " checks passed")
    print("=" * 60)
    raise SystemExit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
