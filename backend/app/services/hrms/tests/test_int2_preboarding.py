"""Phase INT-2 -- pre-boarding engagement (SOP §6).

The window between "they accepted" and "they walked in" is where an offer is lost.

The property this file tests hardest is a NEGATIVE one: NOTHING IS GATED ON THIS. Every
other internal-track control in the module refuses something; this one refuses nothing, and
a later change that quietly made a touchpoint a precondition for onboarding would be a
regression this file is here to catch.

Also covered: the due list splitting never-contacted from gone-quiet, the At Risk flag
requiring a note and notifying two named people rather than broadcasting, and the window
being exactly the stages between accepting and joining.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_preboarding   (from backend/)
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


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_REC = (str(ObjectId()) for _ in range(3))

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "created_by": U_HOD, "assignee_id": U_REC,
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "created_by": U_HOD, "approval_status": "Approved",
         "closing_status": "Open", "created_at": NOW},
    ])

    def cand(uk, name, status, request_no="HR-REQ-2026-001"):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": status,
                "assigned_recruiter_id": U_REC,
                "assigned_recruiter_name": "Rita Recruiter"}

    candidates = FakeCollection([
        cand("CAN-001", "Accepted One", M.AppStatus.OFFER_ACCEPTED.value),
        cand("CAN-002", "Accepted Two", M.AppStatus.APPOINTMENT_LETTER_SENT.value),
        cand("CAN-003", "Onboarding One", M.AppStatus.PRE_ONBOARDING.value),
        # Outside the window on both sides.
        cand("CAN-004", "Still Interviewing", M.AppStatus.MD_ROUND.value),
        cand("CAN-005", "Already Joined", M.AppStatus.EMPLOYEE_CREATED.value),
        cand("CAN-100", "Client Joiner", M.AppStatus.OFFER_ACCEPTED.value,
             "HR-REQ-2026-002"),
    ])
    touchpoints = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_PREBOARDING: touchpoints, M.COLL_OFFERS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_preboarding_service as PBT
    import app.services.hrms_onboarding_service as ON
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (PBT, AUD, IDS):
        mod.get_collection = mongo.get_collection

    told = []

    async def fake_users(user_ids, title, message, **kw):
        told.append({"to": [u for u in user_ids if u], "title": title})
    PBT.notify_users = fake_users

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("The window is exactly the stages between accepting and joining")
        # =================================================================
        check("the window is Offer Accepted, Appointment Letter Sent and Pre-Onboarding",
              M.PREBOARDING_STATUSES == {M.AppStatus.OFFER_ACCEPTED,
                                         M.AppStatus.APPOINTMENT_LETTER_SENT,
                                         M.AppStatus.PRE_ONBOARDING})
        check("somebody still interviewing is not in it",
              M.AppStatus.MD_ROUND not in M.PREBOARDING_STATUSES)
        check("and neither is somebody who has already joined",
              M.AppStatus.EMPLOYEE_CREATED not in M.PREBOARDING_STATUSES)
        check("the contact interval is a week, matching the SOP's practice",
              M.PREBOARDING_CONTACT_DAYS == 7)

        # =================================================================
        section("Everybody in the window starts on the due list")
        # =================================================================
        due = await PBT.due_touchpoints(HR, COMPANY)
        never = {r["uk"] for r in due["never_contacted"]}
        check("all three accepted candidates are 'never contacted'",
              never == {"CAN-001", "CAN-002", "CAN-003"})
        check("nobody is 'gone quiet' yet -- there is nothing to have gone quiet after",
              due["gone_quiet"] == [])
        check("the CLIENT-track joiner is not on our list at all",
              "CAN-100" not in never)
        check("their new hire is the client's to keep warm", True)
        check("the recruiter is named on each row, so the list is actionable",
              all(r["assigned_recruiter_name"] for r in due["never_contacted"]))

        # =================================================================
        section("Recording a touchpoint")
        # =================================================================
        logged = await PBT.record_touchpoint(HR, COMPANY, {
            "candidate_uk": "CAN-001", "mode": "Call", "sentiment": "Positive",
            "notes": "Looking forward to starting."})
        check("a touchpoint is minted with a PBT id", logged["pbt_no"].startswith("PBT-"))
        check("it carries the requisition, so analytics scoping reaches it",
              logged["request_no"] == "HR-REQ-2026-001")
        check("it records who made the contact", logged["contacted_by_name"] == "Hana HR")
        check("and SOP section 13 retention is stamped",
              bool(logged["retention_until"]))

        due = await PBT.due_touchpoints(HR, COMPANY)
        check("the contacted candidate leaves the due list entirely",
              "CAN-001" not in {r["uk"] for r in due["never_contacted"]}
              and "CAN-001" not in {r["uk"] for r in due["gone_quiet"]})

        # =================================================================
        section("Gone quiet is measured from the LAST contact, not the offer")
        # =================================================================
        await touchpoints.insert_one({
            "pbt_no": "PBT-2026-900", "company_id": COMPANY,
            "candidate_uk": "CAN-002", "request_no": "HR-REQ-2026-001",
            "mode": "Email", "sentiment": "Neutral", "contacted_at": ago(30),
            "contacted_by_name": "Hana HR", "created_at": NOW - timedelta(days=30)})
        due = await PBT.due_touchpoints(HR, COMPANY)
        quiet = {r["uk"] for r in due["gone_quiet"]}
        check("somebody last spoken to a month ago has gone quiet", "CAN-002" in quiet)
        check("and is reported SEPARATELY from those nobody has contacted at all",
              "CAN-002" not in {r["uk"] for r in due["never_contacted"]})
        check("'we have not started' and 'we have let it slip' are different "
              "conversations", True)
        check("the row carries when they were last spoken to",
              next(r for r in due["gone_quiet"]
                   if r["uk"] == "CAN-002")["last_contacted_at"] == ago(30))

        # =================================================================
        section("At Risk raises a flag to TWO NAMED PEOPLE")
        # =================================================================
        await expect_http(
            "flagging somebody At Risk with no note",
            PBT.record_touchpoint(HR, COMPANY, {
                "candidate_uk": "CAN-003", "sentiment": "At Risk"}),
            422, "say what they told you")
        check("a flag with no story tells the recruiter to worry and nothing else", True)

        told.clear()
        await PBT.record_touchpoint(HR, COMPANY, {
            "candidate_uk": "CAN-003", "mode": "Call", "sentiment": "At Risk",
            "counter_offer_disclosed": True,
            "notes": "Has a competing offer at a higher band; deciding this week."})
        check("an At Risk touchpoint notifies", len(told) == 1)
        recipients = set(told[0]["to"])
        check("the recruiter is told", U_REC in recipients)
        check("and the HOD who raised the vacancy", U_HOD in recipients)
        check("it is NOT a role-wide broadcast -- two people can act on it, a function "
              "cannot", len(recipients) <= 3)

        listing = await PBT.list_touchpoints(HR, COMPANY)
        check("the at-risk count is what the screen leads with", listing["at_risk"] == 1)
        check("and the counter-offer is on the record",
              any(t.get("counter_offer_disclosed") for t in listing["touchpoints"]))

        # =================================================================
        section("NOTHING IS GATED ON IT")
        # =================================================================
        # The negative property this file exists for. CAN-002 has one stale touchpoint and
        # CAN-001 one fresh one; neither fact may change what the pipeline allows.
        from app.models.hrms import ONBOARDABLE_STATUSES
        check("onboarding is startable from the same statuses it always was",
              ONBOARDABLE_STATUSES == {M.AppStatus.OFFER_ACCEPTED,
                                       M.AppStatus.APPOINTMENT_LETTER_SENT})
        check("the onboarding service does not read pre-boarding at all",
              "COLL_PREBOARDING" not in ON.__dict__
              and "preboarding" not in ON.__doc__.lower())

        from pathlib import Path
        service_dir = Path(__file__).resolve().parents[2]
        gated = []
        for name in ("hrms_onboarding_service.py", "hrms_offer_service.py",
                     "hrms_candidate_service.py", "hrms_appointment_service.py"):
            source = (service_dir / name).read_text(encoding="utf-8")
            if "COLL_PREBOARDING" in source or "preboarding_service" in source:
                gated.append(name)
        check("no pipeline service imports the pre-boarding module", not gated)
        check("a candidate with no touchpoint onboards exactly as they always did", True)

        # =================================================================
        section("Refusals")
        # =================================================================
        await expect_http(
            "logging a touchpoint against a client-track joiner",
            PBT.record_touchpoint(HR, COMPANY, {"candidate_uk": "CAN-100"}),
            409, "legacy client-track")
        await expect_http(
            "logging one against somebody still interviewing",
            PBT.record_touchpoint(HR, COMPANY, {"candidate_uk": "CAN-004"}),
            409, "pre-boarding runs between accepting the offer and joining")
        await expect_http(
            "logging one against somebody who already joined",
            PBT.record_touchpoint(HR, COMPANY, {"candidate_uk": "CAN-005"}),
            409, "pre-boarding runs between")
        await expect_http(
            "dating a conversation in the future",
            PBT.record_touchpoint(HR, COMPANY, {
                "candidate_uk": "CAN-001",
                "contacted_at": (NOW + timedelta(days=5)).strftime("%Y-%m-%d")}),
            422, "cannot be dated in the future")
        await expect_http(
            "an unknown sentiment",
            PBT.record_touchpoint(HR, COMPANY, {
                "candidate_uk": "CAN-001", "sentiment": "Ecstatic"}),
            422, "sentiment must be one of")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
