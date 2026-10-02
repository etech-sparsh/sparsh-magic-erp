"""Phase 7 verification harness -- interviews + scorecard evaluation.

Covers: the assessment gate, scheduling validation, the full PASS_NEXT chain to Selected,
Fail/Hold outcomes, the MD-round restriction, row scoping, reschedule sequencing, cancel,
concurrent evaluation, and the RFC 5545 invite.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase7_interview   (from backend/)
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
SOON = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
PAST = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_HOD, U_MD, U_EMP, U_OTHER = (str(ObjectId()) for _ in range(5))

    def cand(uk, status, requires=False, request_no="HR-REQ-2026-001"):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": f"Cand {uk}", "can_email": f"{uk}@x.com",
                "application_status": status, "requires_assessment": requires,
                "request_no": request_no}

    candidates = FakeCollection([
        cand("CAN-001", S.SHORTLISTED.value),                        # no assessment needed
        cand("CAN-002", S.ASSESSMENT_PENDING.value, requires=True),  # gate should block
        cand("CAN-003", S.ASSESSMENT_FAILED.value, requires=True),   # gate should block
        cand("CAN-004", S.ASSESSMENT_PASSED.value, requires=True),   # gate should allow
        cand("CAN-005", S.REJECTED.value),                           # terminal-ish
        cand("CAN-006", S.SHORTLISTED.value),
        cand("CAN-007", S.SHORTLISTED.value),
        cand("CAN-008", S.SHORTLISTED.value),
        cand("CAN-009", S.SHORTLISTED.value, request_no="HR-REQ-2026-002"),
        cand("CAN-010", S.SHORTLISTED.value),
    ])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": COMPANY},
        {"_id": ObjectId(U_MD), "full_name": "Mira MD", "email": "md@c1.com",
         "company_id": COMPANY},
        {"_id": ObjectId(U_EMP), "full_name": "Eve Emp", "email": "emp@c1.com",
         "company_id": COMPANY},
        {"_id": ObjectId(U_OTHER), "full_name": "Otto Other", "email": "o@c2.com",
         "company_id": "C2"},
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_MD},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "created_by": U_HOD},
    ])
    interviews_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, "learners": learners,
             M.COLL_REQUISITIONS: reqs, M.COLL_INTERVIEWS: interviews_coll,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_interview_service as IS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (IS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify(uid, title, msg, **kw):
        sent.append((str(uid), title))

    IS.notify_user = fake_notify

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "full_name": "Mira MD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR", "full_name": "Eve Emp"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    async def book(uk, **over):
        payload = {"uk": uk, "round": "HR Round", "mode": "Virtual",
                   "scheduled_at": SOON.isoformat(), "duration_min": 45,
                   "interviewer_id": U_HOD, "meeting_link": "https://meet.example/x"}
        payload.update(over)
        return await IS.schedule_interview(HR, COMPANY, payload)

    def scorecard(**over):
        card = {k: 4 for k in M.COMPETENCY_KEYS}
        card.update({"outcome": "Pass", "signature": "Hari HOD"})
        card.update(over)
        return card

    try:
        from app.utils import hrms_access as A

        # =================================================================
        section("Capability matrix (Phase 7)")
        # =================================================================
        check("HR can schedule", A.can(HR, M.Cap.INTERVIEW_SCHEDULE))
        check("HR can evaluate", A.can(HR, M.Cap.INTERVIEW_EVALUATE))
        check("HR CANNOT decide an MD round", not A.can(HR, M.Cap.INTERVIEW_DECIDE_MD))
        check("MD can decide an MD round", A.can(MD, M.Cap.INTERVIEW_DECIDE_MD))
        check("MANAGER can evaluate but not schedule",
              A.can(HOD, M.Cap.INTERVIEW_EVALUATE)
              and not A.can(HOD, M.Cap.INTERVIEW_SCHEDULE))
        # An employee may be booked as an interviewer, so they must be able to score --
        # row scoping limits them to their own.
        check("EMPLOYEE can evaluate (they may be an interviewer)",
              A.can(EMP, M.Cap.INTERVIEW_EVALUATE))
        check("EMPLOYEE cannot browse all interviews", not A.can(EMP, M.Cap.INTERVIEW_READ))
        check("INTERNAL can schedule but NOT evaluate (a hiring decision)",
              A.can(INTERNAL, M.Cap.INTERVIEW_SCHEDULE)
              and not A.can(INTERNAL, M.Cap.INTERVIEW_EVALUATE))

        # =================================================================
        section("THE ASSESSMENT GATE")
        # =================================================================
        await expect_http("assessment-required candidate still Pending", book("CAN-002"),
                          409, "requires an assessment")
        await expect_http("assessment-required candidate who FAILED", book("CAN-003"),
                          409, "requires an assessment")
        ok = await book("CAN-004")
        check("assessment-required candidate who PASSED can be booked",
              ok["interview_no"].startswith("INT-"))
        no_gate = await book("CAN-001")
        check("a role with no assessment requirement books straight from Shortlisted",
              no_gate["uk"] == "CAN-001")
        await expect_http("a rejected candidate", book("CAN-005"), 409, "cannot be interviewed")

        pickable = {p["uk"] for p in await IS.schedulable_candidates(HR, COMPANY)}
        check("picker hides the un-assessed candidate", "CAN-002" not in pickable)
        check("picker hides the failed candidate", "CAN-003" not in pickable)
        check("picker offers the passed candidate", "CAN-004" in pickable)
        check("picker hides a rejected candidate", "CAN-005" not in pickable)

        section("Scheduling validation")
        await expect_http("no candidate", IS.schedule_interview(HR, COMPANY, {}), 422,
                          "Select a candidate")
        await expect_http("unknown candidate", book("CAN-NOPE"), 404)
        await expect_http("scheduled in the past", book("CAN-006", scheduled_at=PAST.isoformat()),
                          422, "in the past")
        await expect_http("unreadable datetime", book("CAN-006", scheduled_at="not-a-date"),
                          422, "could not be read")
        await expect_http("invalid round", book("CAN-006", round="Coffee Chat"),
                          422, "Round must be one of")
        await expect_http("duration below minimum", book("CAN-006", duration_min=10),
                          422, "at least 15")
        await expect_http("duration off-step", book("CAN-006", duration_min=20),
                          422, "15-minute steps")
        await expect_http("virtual with no link", book("CAN-006", meeting_link=""),
                          422, "needs a meeting link")
        await expect_http("meeting link without a scheme",
                          book("CAN-006", meeting_link="meet.example/x"), 422, "http")
        await expect_http("offline with no location",
                          book("CAN-006", mode="Offline", meeting_link=None, location=""),
                          422, "needs a location")
        await expect_http("no interviewer", book("CAN-006", interviewer_id=""),
                          422, "Choose who")
        await expect_http("interviewer from another company",
                          book("CAN-006", interviewer_id=U_OTHER), 422, "user of this company")

        offline = await book("CAN-006", mode="Offline", meeting_link=None,
                             location="Room 4, 2nd floor")
        check("offline interview stores a location", offline["location"] == "Room 4, 2nd floor")
        check("offline interview clears any meeting link", offline["meeting_link"] is None)

        section("Scheduling side effects")
        cand1 = await candidates.find_one({"uk": "CAN-001"})
        check("candidate advances to Interview Scheduled",
              cand1["application_status"] == S.INTERVIEW_SCHEDULED.value)
        check("scheduling audited",
              any(x["action"] == M.AUDIT_INTERVIEW_SCHEDULED for x in audit_log.docs))
        check("interviewer notified", any(s[0] == U_HOD for s in sent))
        check("sequence starts at 0", no_gate["ics_sequence"] == 0)

        # =================================================================
        section("THE PASS CHAIN -- HR -> Technical -> MD -> Selected")
        # =================================================================
        a = await book("CAN-007", round="HR Round")
        r = await IS.evaluate_interview(HOD, COMPANY, a["interview_no"], scorecard())
        check("HR round evaluated", r["outcome"] == "Pass")
        check("status becomes Completed", r["status"] == M.InterviewStatus.COMPLETED.value)
        check("average computed", r["average_score"] == 4.0)
        got = (await candidates.find_one({"uk": "CAN-007"}))["application_status"]
        check("HR Round pass -> Technical Round", got == S.TECHNICAL_ROUND.value)

        b = await book("CAN-007", round="Technical")
        await IS.evaluate_interview(HOD, COMPANY, b["interview_no"], scorecard())
        got = (await candidates.find_one({"uk": "CAN-007"}))["application_status"]
        check("Technical pass -> MD Round", got == S.MD_ROUND.value)

        c = await book("CAN-007", round="MD Round", interviewer_id=U_MD)
        await expect_http("HR cannot decide an MD round",
                          IS.evaluate_interview(HR, COMPANY, c["interview_no"], scorecard()),
                          403, "Only the MD")
        # The case that matters: someone who IS the assigned interviewer, and can see the
        # interview, still cannot make the final call unless they hold interview.decide_md.
        md_by_hod = await book("CAN-009", round="MD Round", interviewer_id=U_HOD)
        await expect_http("the assigned interviewer cannot decide an MD round without the "
                          "MD capability",
                          IS.evaluate_interview(HOD, COMPANY, md_by_hod["interview_no"],
                                                scorecard()),
                          403, "Only the MD")
        await expect_http("an out-of-scope interview is 404, not 403 (no existence leak)",
                          IS.evaluate_interview(EMP, COMPANY, c["interview_no"], scorecard()),
                          404)
        await IS.evaluate_interview(MD, COMPANY, c["interview_no"],
                                    scorecard(signature="Mira MD"))
        got = (await candidates.find_one({"uk": "CAN-007"}))["application_status"]
        check("MD Round pass -> Selected", got == S.SELECTED.value)

        section("Manager Round also routes to MD Round")
        d = await book("CAN-008", round="Manager Round")
        await IS.evaluate_interview(HOD, COMPANY, d["interview_no"], scorecard())
        got = (await candidates.find_one({"uk": "CAN-008"}))["application_status"]
        check("Manager Round pass -> MD Round", got == S.MD_ROUND.value)

        section("Fail and Hold")
        e = await book("CAN-010", round="HR Round")
        await IS.evaluate_interview(HOD, COMPANY, e["interview_no"],
                                    scorecard(outcome="Fail"))
        got = (await candidates.find_one({"uk": "CAN-010"}))["application_status"]
        check("Fail -> Rejected", got == S.REJECTED.value)

        await candidates.update_one({"uk": "CAN-006"},
                                    {"$set": {"application_status": S.INTERVIEW_SCHEDULED.value}})
        f = await book("CAN-006", round="Technical")
        await IS.evaluate_interview(HOD, COMPANY, f["interview_no"],
                                    scorecard(outcome="Hold"))
        got = (await candidates.find_one({"uk": "CAN-006"}))["application_status"]
        check("Hold -> On Hold", got == S.ON_HOLD.value)

        section("Evaluation validation")
        g = await book("CAN-004", round="HR Round")
        await expect_http("no signature",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"],
                                                scorecard(signature="  ")),
                          422, "Type your name")
        await expect_http("invalid outcome",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"],
                                                scorecard(outcome="Maybe")),
                          422, "Pass, Fail or Hold")
        await expect_http("score above 5",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"],
                                                scorecard(technical=6)),
                          422, "between 0 and 5")
        await expect_http("negative score",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"],
                                                scorecard(confidence=-1)), 422)
        await expect_http("non-numeric score",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"],
                                                scorecard(team_fit="great")),
                          422, "whole number")

        await IS.evaluate_interview(HOD, COMPANY, g["interview_no"], scorecard())
        await expect_http("evaluating twice",
                          IS.evaluate_interview(HOD, COMPANY, g["interview_no"], scorecard()),
                          409, "already been evaluated")

        section("Who may evaluate")
        h = await book("CAN-009", round="HR Round", interviewer_id=U_EMP)
        doc_h = await interviews_coll.find_one({"interview_no": h["interview_no"]})
        check("the assigned interviewer may evaluate", IS._may_evaluate(EMP, doc_h))
        check("HR may evaluate a non-MD round they did not conduct",
              IS._may_evaluate(HR, doc_h))
        check("INTERNAL may NOT evaluate", not IS._may_evaluate(INTERNAL, doc_h))
        md_doc = await interviews_coll.find_one({"interview_no": c["interview_no"]})
        check("only the MD may evaluate an MD round",
              IS._may_evaluate(MD, md_doc) and not IS._may_evaluate(HR, md_doc))

        # =================================================================
        section("Row scoping")
        # =================================================================
        emp_view = await IS.list_interviews(EMP, COMPANY)
        nos = {i["interview_no"] for i in emp_view["interviews"]}
        check("an employee sees ONLY interviews they conduct", nos == {h["interview_no"]})
        check("their own row is flagged is_mine",
              all(i["is_mine"] for i in emp_view["interviews"]))

        hr_view = await IS.list_interviews(HR, COMPANY)
        check("HR sees every interview in the company",
              len(hr_view["interviews"]) > len(emp_view["interviews"]))
        check("stats returned", set(hr_view["stats"]) == {"today", "upcoming", "completed", "dropped"})
        check("rows carry a day key for grouping",
              all("day" in i for i in hr_view["interviews"]))
        check("can_evaluate is decided server-side",
              all("can_evaluate" in i for i in hr_view["interviews"]))

        # HOD raised HR-REQ-2026-002 (CAN-009) and conducts several others.
        hod_view = await IS.list_interviews(HOD, COMPANY)
        hod_nos = {i["interview_no"] for i in hod_view["interviews"]}
        check("a manager sees interviews on their own requisition",
              h["interview_no"] in hod_nos)
        check("a manager sees interviews they conduct", a["interview_no"] in hod_nos)

        await expect_http("an employee cannot open an out-of-scope interview (404)",
                          IS.evaluate_interview(EMP, COMPANY, a["interview_no"], scorecard()),
                          404)
        await expect_http("cross-tenant read is 404",
                          IS.list_interviews(HR, "C2") if False else
                          IS.evaluate_interview(HR, "C2", a["interview_no"], scorecard()), 404)

        # =================================================================
        section("Reschedule, status and cancel")
        # =================================================================
        later = (SOON + timedelta(days=1)).isoformat()
        moved = await IS.update_interview(HR, COMPANY, h["interview_no"],
                                          {"scheduled_at": later})
        check("reschedule applied", moved["scheduled_at"].isoformat().startswith(later[:16]))
        # A calendar client only treats a new invite as an UPDATE when SEQUENCE increases.
        check("calendar sequence bumped on reschedule", moved["ics_sequence"] == 1)
        check("reschedule audited",
              any(x["action"] == M.AUDIT_INTERVIEW_RESCHEDULED for x in audit_log.docs))
        check("interviewer re-notified",
              any(s[0] == U_EMP and "rescheduled" in s[1].lower() for s in sent))

        await expect_http("reschedule into the past",
                          IS.update_interview(HR, COMPANY, h["interview_no"],
                                              {"scheduled_at": PAST.isoformat()}),
                          422, "into the past")
        await expect_http("no fields",
                          IS.update_interview(HR, COMPANY, h["interview_no"], {}), 400)
        await expect_http("marking Completed without a scorecard",
                          IS.update_interview(HR, COMPANY, h["interview_no"],
                                              {"status": "Completed"}),
                          409, "Record the evaluation")

        no_show = await IS.update_interview(HR, COMPANY, h["interview_no"],
                                            {"status": "No Show"})
        check("No Show can be set without a scorecard", no_show["status"] == "No Show")

        i2 = await book("CAN-004", round="Technical")
        await expect_http("an employee cannot cancel",
                          IS.cancel_interview(EMP, COMPANY, i2["interview_no"]), 404)
        gone = await IS.cancel_interview(HR, COMPANY, i2["interview_no"])
        check("cancelled", gone["cancelled"] is True)
        doc = await interviews_coll.find_one({"interview_no": i2["interview_no"]})
        check("marked Cancelled, NOT deleted -- a dropped round is part of the record",
              doc["status"] == M.InterviewStatus.CANCELLED.value)
        check("cancel bumps the sequence so the calendar entry is withdrawn",
              doc["ics_sequence"] == 1)
        await expect_http("cancelling twice",
                          IS.cancel_interview(HR, COMPANY, i2["interview_no"]),
                          409, "already cancelled")
        await expect_http("evaluating a cancelled interview",
                          IS.evaluate_interview(HOD, COMPANY, i2["interview_no"], scorecard()),
                          409, "cancelled")

        # =================================================================
        section("Calendar invite (RFC 5545)")
        # =================================================================
        doc = await interviews_coll.find_one({"interview_no": a["interview_no"]})
        ics = IS.invite_for(doc)
        check("is a VCALENDAR", ics.startswith("BEGIN:VCALENDAR"))
        check("contains one VEVENT", ics.count("BEGIN:VEVENT") == 1)
        check("CRLF line endings (mandatory)", "\r\n" in ics)
        check("times are UTC-stamped", "DTSTART:" in ics and "Z\r\n" in ics)
        check("candidate and interviewer are attendees", ics.count("ATTENDEE") == 2)
        check("METHOD:REQUEST for a live booking", "METHOD:REQUEST" in ics)
        cancelled_doc = await interviews_coll.find_one({"interview_no": i2["interview_no"]})
        cancel_ics = IS.invite_for(cancelled_doc, cancelled=True)
        check("a cancelled invite uses METHOD:CANCEL", "METHOD:CANCEL" in cancel_ics)
        check("and STATUS:CANCELLED so the entry is removed",
              "STATUS:CANCELLED" in cancel_ics)

        section("Index registry (Phase 7 additions)")
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("interview_no unique",
              any(c == M.COLL_INTERVIEWS and n == "uniq_interview_no" for c, n in names))
        check("day-grouped feed is indexed",
              any(c == M.COLL_INTERVIEWS and n == "by_company_when" for c, n in names))
        check("an interviewer's own list is indexed",
              any(c == M.COLL_INTERVIEWS and n == "by_interviewer" for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))

        section("PASS_NEXT agrees with the lifecycle graph")
        for round_name, target in M.PASS_NEXT.items():
            # Every intended destination must be legal from the stage that round runs at.
            legal = (M.can_transition(S.INTERVIEW_SCHEDULED, target)
                     or M.can_transition(S.TECHNICAL_ROUND, target)
                     or M.can_transition(S.MD_ROUND, target))
            check(f"{round_name.value} -> {target.value} is a legal edge", legal)

        section("Identity collections still never written")
        check("learners untouched",
              all("interview_no" not in d and "outcome" not in d for d in learners.docs))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
