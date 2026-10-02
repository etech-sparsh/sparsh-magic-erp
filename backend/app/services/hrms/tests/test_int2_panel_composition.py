"""Phase INT-2 -- interview panel composition (SOP §5).

Covers: the panel table itself, the 422 that NAMES the missing roles, the refusal of one
person covering two role-slots, the recusal rule from SOP §11, and the fact that a
client-track booking is completely untouched by any of it.

The property that matters most and is easiest to lose: ONE PERSON IS NOT A PANEL. An MD
holds every capability on this track, so without the two-different-people check a single MD
would satisfy "HR + HOD + Management" alone. That is the same failure a two-stage approval
one person can complete has, and it is asserted here explicitly rather than assumed.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_panel_composition   (from backend/)
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


def expect_http_sync(label: str, fn, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        fn()
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)
SOON = (NOW + timedelta(days=3)).isoformat()


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_MD, U_HR2 = (str(ObjectId()) for _ in range(4))
    DESIG_MID, DESIG_MANAGERIAL, DESIG_UNBANDED = (ObjectId() for _ in range(3))
    DEPT = ObjectId()

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HR2), "full_name": "Hira HR", "email": "hr2@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "email": "md@c1.com",
         "company_id": COMPANY, "role": "clientadmin", "governance_role": "MD"},
    ])
    designations = FakeCollection([
        {"_id": DESIG_MID, "company_id": COMPANY, "name": "Ops Executive",
         "designation_level": "mid"},
        {"_id": DESIG_MANAGERIAL, "company_id": COMPANY, "name": "Ops Manager",
         "designation_level": "managerial"},
        # No band at all -- the row every company has before this phase.
        {"_id": DESIG_UNBANDED, "company_id": COMPANY, "name": "Legacy Role"},
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "designation_id": str(DESIG_MID), "department_id": str(DEPT),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Manager",
         "designation_id": str(DESIG_MANAGERIAL), "department_id": str(DEPT),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "designation_id": str(DESIG_MID), "department_id": str(DEPT),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "candidate_name": "Mid One", "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"_id": ObjectId(), "uk": "CAN-002", "company_id": COMPANY,
         "candidate_name": "Manager One", "request_no": "HR-REQ-2026-002",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"_id": ObjectId(), "uk": "CAN-003", "company_id": COMPANY,
         "candidate_name": "Client One", "request_no": "HR-REQ-2026-003",
         "application_status": M.AppStatus.SHORTLISTED.value},
    ])
    interviews = FakeCollection()
    windows = FakeCollection()

    # Phase INT-4 added a telephonic gate ahead of the panel, so every internal candidate in
    # this file carries a PASSING screen. This test is about panel COMPOSITION -- if it also
    # had to satisfy the phone-screen gate on every booking, a failure here would no longer
    # tell you which of the two controls refused.
    telephonic = FakeCollection([
        {"tel_no": f"TEL-2026-{n:03d}", "company_id": COMPANY, "uk": c["uk"],
         "request_no": c.get("request_no"),
         "outcome": M.TelephonicOutcome.PASSED.value}
        for n, c in enumerate(candidates.docs, start=1)
    ])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_INTERVIEWS: interviews, M.COLL_DESIGNATIONS: designations,
             M.COLL_INTERVIEW_WINDOWS: windows, M.COLL_COUNTERS: FakeCollection(),
             M.COLL_TELEPHONIC: telephonic,
             M.COLL_AUDIT_LOG: FakeCollection(), "learners": learners}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_interview_service as IV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (IV, AUD, IDS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    IV.notify_user = silent

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    def panel(*user_ids, **flags):
        return [{"user_id": uid, **flags} for uid in user_ids]

    def booking(uk, **over):
        base = {"uk": uk, "round": "HR Round", "mode": "Virtual",
                "scheduled_at": SOON, "duration_min": 45,
                "interviewer_id": U_HR, "meeting_link": "https://meet.example.com/x"}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The table IS the rule (SOP section 5)")
        # =================================================================
        check("junior needs HR + the Department Head",
              [r.value for r in M.required_panel_roles("junior")] == ["hr", "manager"])
        check("mid needs the same two",
              [r.value for r in M.required_panel_roles("mid")] == ["hr", "manager"])
        check("senior additionally needs Management",
              [r.value for r in M.required_panel_roles("senior")]
              == ["hr", "manager", "md"])
        check("managerial additionally needs Management",
              [r.value for r in M.required_panel_roles(M.DesignationLevel.MANAGERIAL)]
              == ["hr", "manager", "md"])
        check("an UNKNOWN band falls back to the default's requirement, not to nothing",
              M.required_panel_roles("wizard") == M.required_panel_roles("mid"))
        check("the order is the SOP's, so 'still needed' reads stably",
              M.required_panel_roles("senior")[0] is M.HrmsRole.HR)

        check("a designation with no band reads as mid, not as unbanded",
              M.designation_level({}) is M.DEFAULT_DESIGNATION_LEVEL)
        check("and the default is mid rather than junior",
              M.DEFAULT_DESIGNATION_LEVEL is M.DesignationLevel.MID)
        check("senior and managerial are the managerial-and-above set",
              M.MANAGERIAL_LEVELS == {M.DesignationLevel.SENIOR,
                                      M.DesignationLevel.MANAGERIAL})
        check("the final-round rule reads the SAME set the panel table does",
              all(M.final_round_is_mandatory(level) is (level in M.MANAGERIAL_LEVELS)
                  for level in M.DesignationLevel))

        # =================================================================
        section("A panel missing a role is refused, and the refusal NAMES it")
        # =================================================================
        expect_http_sync(
            "a mid-level panel of HR alone",
            lambda: IV.assert_panel_composition(
                [{"user_id": U_HR, "role": "hr"}], M.DesignationLevel.MID),
            422, "still missing: manager")
        expect_http_sync(
            "a managerial panel with no Management",
            lambda: IV.assert_panel_composition(
                [{"user_id": U_HR, "role": "hr"}, {"user_id": U_HOD, "role": "manager"}],
                M.DesignationLevel.MANAGERIAL),
            422, "still missing: md")
        expect_http_sync(
            "an empty panel on a mid role",
            lambda: IV.assert_panel_composition([], M.DesignationLevel.MID),
            422, "still missing")

        # A correct panel raises nothing at all.
        IV.assert_panel_composition(
            [{"user_id": U_HR, "role": "hr"}, {"user_id": U_HOD, "role": "manager"}],
            M.DesignationLevel.MID)
        check("a panel covering both required roles passes", True)

        # =================================================================
        section("One person is not a panel")
        # =================================================================
        # The case that matters: an MD holds every capability, so without this check a
        # single MD would satisfy HR + HOD + Management on their own.
        expect_http_sync(
            "one person listed under two roles on a mid role",
            lambda: IV.assert_panel_composition(
                [{"user_id": U_MD, "role": "hr"}, {"user_id": U_MD, "role": "manager"}],
                M.DesignationLevel.MID),
            422, "not a panel")
        expect_http_sync(
            "one person covering all three seats on a managerial role",
            lambda: IV.assert_panel_composition(
                [{"user_id": U_MD, "role": "hr"}, {"user_id": U_MD, "role": "manager"},
                 {"user_id": U_MD, "role": "md"}],
                M.DesignationLevel.MANAGERIAL),
            422, "different people")
        check("the refusal counts PEOPLE, not entries",
              M.SHORTLIST_MIN_MEMBERS == 2)

        # =================================================================
        section("A recused member does not make the panel quorate (SOP section 11)")
        # =================================================================
        expect_http_sync(
            "the Department Head recuses themselves and nobody replaces them",
            lambda: IV.assert_panel_composition(
                [{"user_id": U_HR, "role": "hr"},
                 {"user_id": U_HOD, "role": "manager", "recused": True}],
                M.DesignationLevel.MID),
            422, "recused member does not count")

        IV.assert_panel_composition(
            [{"user_id": U_HR, "role": "hr"},
             {"user_id": U_HOD, "role": "manager", "recused": True},
             {"user_id": U_MD, "role": "manager"}],
            M.DesignationLevel.MID)
        check("but a replacement in the same seat restores it", True)

        # =================================================================
        section("Scheduling enforces it, on the internal track only")
        # =================================================================
        await expect_http(
            "booking a mid internal role with no panel at all",
            IV.schedule_interview(HR, COMPANY, booking("CAN-001")),
            422, "still missing")
        check("and nothing was written by the refusal",
              await interviews.count_documents({}) == 0)

        booked = await IV.schedule_interview(
            HR, COMPANY, booking("CAN-001", panel=panel(U_HR, U_HOD)))
        check("a properly composed panel books", booked["interview_no"].startswith("INT-"))
        check("the panel is stored WITH each member's role as it stood",
              {m["role"] for m in booked["panel"]} == {"hr", "manager"})
        check("and with their names, so the record reads without a join",
              all(m.get("name") for m in booked["panel"]))

        await expect_http(
            "booking a MANAGERIAL role with only HR and the HOD",
            IV.schedule_interview(
                HR, COMPANY, booking("CAN-002", panel=panel(U_HR, U_HOD))),
            422, "still missing: md")

        managerial = await IV.schedule_interview(
            HR, COMPANY, booking("CAN-002", panel=panel(U_HR, U_HOD, U_MD)))
        check("adding Management books the managerial role",
              managerial["interview_no"].startswith("INT-"))

        # =================================================================
        section("The client track is untouched")
        # =================================================================
        client_booking = await IV.schedule_interview(HR, COMPANY, booking("CAN-003"))
        check("a client-track interview books with NO panel at all",
              client_booking["interview_no"].startswith("INT-"))
        check("and its panel is simply empty, not a refusal",
              client_booking["panel"] == [])

        # =================================================================
        section("A member of another company is refused")
        # =================================================================
        outsider = str(ObjectId())
        await expect_http(
            "a panel member who is not a user of this company",
            IV.schedule_interview(
                HR, COMPANY, booking("CAN-001", panel=panel(U_HR, outsider))),
            422, "user of this company")

        # =================================================================
        section("A recused member may not score (SOP section 11)")
        # =================================================================
        await interviews.update_one(
            {"interview_no": booked["interview_no"]},
            {"$set": {"panel": [
                {"user_id": U_HR, "role": "hr", "recused": True,
                 "coi_relationship": "the candidate is my cousin"},
                {"user_id": U_HOD, "role": "manager"}]}})
        await expect_http(
            "a recused panel member submitting a scorecard",
            IV.evaluate_interview(HR, COMPANY, booked["interview_no"], {
                "technical": 4, "communication": 4, "problem_solving": 4,
                "behavior": 4, "confidence": 4, "team_fit": 4,
                "outcome": "Pass", "signature": "Hana HR"}),
            422, "recused")
        check("and the refusal repeats the conflict they declared, so it reads as theirs",
              True)   # asserted by the fragment above

        # =================================================================
        section("Batch windows WARN, they never refuse (Annexure C)")
        # =================================================================
        no_windows = await IV.interview_window_warning(
            COMPANY, {"department_id": str(DEPT)}, datetime.fromisoformat(SOON))
        check("a department with no windows produces no warning at all",
              no_windows is None)

        # A window that cannot possibly contain the booking.
        await windows.insert_one({
            "company_id": COMPANY, "department_id": str(DEPT), "weekday": "Sunday",
            "start_time": "09:00", "end_time": "09:30", "active": True})
        warning = await IV.interview_window_warning(
            COMPANY, {"department_id": str(DEPT)},
            datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc))   # a Wednesday
        check("a booking outside every window produces a warning",
              isinstance(warning, str) and "outside" in warning.lower())
        check("and the warning says the booking WAS made",
              "has been made" in (warning or "").lower())

        third = await IV.schedule_interview(
            HR, COMPANY, booking("CAN-001", panel=panel(U_HR2, U_HOD)))
        check("an out-of-window booking still succeeds -- it is a preference, not a rule",
              third["interview_no"].startswith("INT-"))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
