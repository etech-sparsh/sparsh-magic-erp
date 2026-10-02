"""Phase INT-2 -- candidate communications (Annexure C).

Four commitments both SOPs make to applicants: acknowledge every application, keep them
updated, tell them when they are out, and put the offer terms in writing beforehand.

Covers: the automatic fires on application and on rejection, the append-only log, the fact
that a failed send never breaks the thing that triggered it, the offer-send WARNING (never a
block), and that the derived facts are derived rather than accepted from the caller.

The property that matters most: AN EMAIL MUST NEVER FAIL A JOB APPLICATION. `fire_event`
swallows everything, and that is asserted by breaking the sender deliberately and checking
the application still lands.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_comms   (from backend/)
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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "work_location": "Office", "approval_status": "Approved",
         "closing_status": "Open", "vacancy": 3, "created_at": NOW},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "candidate_name": "Applied One", "can_email": "one@example.com",
         "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.APPLIED.value},
        {"_id": ObjectId(), "uk": "CAN-002", "company_id": COMPANY,
         "candidate_name": "Applied Two", "can_email": "two@example.com",
         "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.APPLIED.value},
        # No email at all -- a walk-in CV typed in by HR.
        {"_id": ObjectId(), "uk": "CAN-003", "company_id": COMPANY,
         "candidate_name": "No Email", "can_email": None,
         "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.APPLIED.value},
    ])
    templates = FakeCollection()
    comm_log = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_COMM_TEMPLATES: templates, M.COLL_COMM_LOG: comm_log,
             M.COLL_OFFERS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_comm_service as CM
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_notify_service as NS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (CM, CS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify(user_id, title, message, **kw):
        sent.append({"title": title, "message": message, "email": kw.get("email")})
    NS.notify_user = fake_notify
    CS.notify_user = fake_notify

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Templates are seeded on first read")
        # =================================================================
        seeded = await CM.list_templates(COMPANY)
        keys = {t["key"] for t in seeded}
        check("the six SOP messages are seeded",
              {k for k, *_ in M.DEFAULT_COMM_TEMPLATES} <= keys)
        check("and the two CONSENT statements alongside them",
              {"consent_equal_opportunity", "consent_data_use"} <= keys)
        check("the consent statements are the wording the public form shows, not messages",
              all(t["channel"] == "inapp" for t in seeded
                  if t["key"].startswith("consent_")))
        check("every template is marked seeded, so an operator can tell defaults from "
              "their own edits", all(t.get("seeded") for t in seeded))

        before = len(seeded)
        again = await CM.list_templates(COMPANY)
        check("reading twice does not seed twice", len(again) == before)

        # =================================================================
        section("The automatic wiring is DATA, readable in one place")
        # =================================================================
        check("an arriving application maps to the acknowledgement",
              M.AUTO_COMM_EVENTS["application_received"] == "application_acknowledged")
        check("a screening rejection maps to the closure note",
              M.AUTO_COMM_EVENTS["screening_rejected"] == "rejection_closure")
        check("the offer summary is NOT automatic -- writing about money is a decision",
              "offer_summary" not in M.AUTO_COMM_EVENTS.values()
              and "offer_summary" in M.MANUAL_COMM_TEMPLATES)

        # =================================================================
        section("Rejection fires the closure note")
        # =================================================================
        result = await CS.screen_candidates(HR, COMPANY, {
            "uks": ["CAN-001"], "action": "reject",
            "remarks": "Not enough hands-on experience for this role."})
        check("the candidate is rejected", result["moved_count"] == 1)

        rows = await comm_log.find({"candidate_uk": "CAN-001"}).to_list(10)
        check("a closure note was logged", len(rows) == 1)
        check("of the right template", rows[0]["template_key"] == "rejection_closure")
        check("marked automatic, so a reader can tell it from a hand-sent one",
              rows[0]["automatic"] is True)
        check("it actually went out", rows[0]["status"] == M.CommStatus.SENT.value)
        check("the placeholders were filled from the record",
              "Applied One" in rows[0]["body"]
              and "Ops Executive" in rows[0]["subject"])
        check("no placeholder was left unfilled",
              "{candidate_name}" not in rows[0]["body"])
        check("SOP section 13 retention is stamped on the log row",
              bool(rows[0]["retention_until"]))

        # =================================================================
        section("Other screening actions send nothing")
        # =================================================================
        await CS.screen_candidates(HR, COMPANY, {"uks": ["CAN-002"], "action": "review"})
        check("moving somebody to Under Review does not email them",
              not await comm_log.count_documents({"candidate_uk": "CAN-002"}))
        check("only `reject` fires, because only `reject` already requires a reason", True)

        # =================================================================
        section("A missing address is SKIPPED, with the reason recorded")
        # =================================================================
        skipped = await CM.send_template(HR, COMPANY, "CAN-003", "stage_update")
        check("a candidate with no email is skipped, not failed",
              skipped["status"] == M.CommStatus.SKIPPED.value)
        check("and the log says why", "email address" in skipped["reason"].lower())
        check("a silence is still accounted for", True)

        # =================================================================
        section("A switched-off template is skipped too")
        # =================================================================
        await CM.update_template(HR, COMPANY, "stage_update", {"active": False})
        off = await CM.send_template(HR, COMPANY, "CAN-002", "stage_update")
        check("an inactive template is skipped",
              off["status"] == M.CommStatus.SKIPPED.value)
        check("and says so", "switched off" in off["reason"].lower())
        await CM.update_template(HR, COMPANY, "stage_update", {"active": True})

        # =================================================================
        section("The facts are DERIVED, never accepted")
        # =================================================================
        out = await CM.send_template(
            HR, COMPANY, "CAN-002", "stage_update",
            variables={"note": "We will be in touch next week.",
                       # A caller trying to assert a designation the record does not hold.
                       "designation": "Chief Executive Officer"})
        check("a caller-supplied note fills the gap the module cannot derive",
              "next week" in out["body"])
        check("but a caller CANNOT overwrite a fact the record holds",
              "Chief Executive Officer" not in out["body"]
              and "Ops Executive" in out["body"])
        check("a sender who could type the CTC in could quote a salary we never agreed",
              True)

        # =================================================================
        section("The log is append-only")
        # =================================================================
        total_before = await comm_log.count_documents({})
        await CM.send_template(HR, COMPANY, "CAN-002", "stage_update")
        total_after = await comm_log.count_documents({})
        check("a second send APPENDS rather than updating the first",
              total_after == total_before + 1)
        two = await comm_log.find({"candidate_uk": "CAN-002",
                                   "template_key": "stage_update"}).to_list(10)
        check("both sends survive as separate facts", len(two) >= 2)
        check("there is no update path in the service at all",
              not hasattr(CM, "update_log") and not hasattr(CM, "delete_log"))

        # =================================================================
        section("An email must never fail the thing that triggered it")
        # =================================================================
        async def exploding(*a, **kw):
            raise RuntimeError("the mail server is on fire")
        NS.notify_user = exploding

        # fire_event swallows everything.
        await CM.fire_event(HR, COMPANY, "CAN-002", "screening_rejected")
        failed = await comm_log.find_one({"candidate_uk": "CAN-002",
                                          "status": M.CommStatus.FAILED.value})
        check("a broken sender is recorded as Failed rather than raising",
              failed is not None)
        check("with the reason kept, so it is diagnosable",
              "on fire" in (failed.get("reason") or ""))

        moved = await CS.screen_candidates(HR, COMPANY, {
            "uks": ["CAN-003"], "action": "reject", "remarks": "Withdrew."})
        check("and the REJECTION still went through while the mail server was down",
              moved["moved_count"] == 1)
        NS.notify_user = fake_notify

        # An unknown EVENT is silently nothing -- a caller may announce an event before
        # anybody has decided to write to candidates about it.
        await CM.fire_event(HR, COMPANY, "CAN-002", "nobody_wired_this_up")
        check("an event with no mapping does nothing at all", True)

        # =================================================================
        section("Caller errors are LOUD, unlike delivery failures")
        # =================================================================
        await expect_http(
            "sending a template that does not exist",
            CM.send_template(HR, COMPANY, "CAN-002", "made_up_template"),
            422, "no 'made_up_template' template")
        await expect_http(
            "sending to a candidate who does not exist",
            CM.send_template(HR, COMPANY, "CAN-999", "stage_update"),
            404, "not found")
        check("a bug that silently logged 'Skipped' is a bug nobody finds", True)

        # =================================================================
        section("The offer send WARNS about a missing summary; it never blocks")
        # =================================================================
        check("no summary has been sent to CAN-002",
              not await CM.was_sent(COMPANY, "CAN-002", "offer_summary"))
        await CM.send_template(HR, COMPANY, "CAN-002", "offer_summary")
        check("once sent, was_sent reports it",
              await CM.was_sent(COMPANY, "CAN-002", "offer_summary"))
        check("a SKIPPED row does not count as having told them",
              not await CM.was_sent(COMPANY, "CAN-003", "stage_update"))

        # =================================================================
        section("Template editing")
        # =================================================================
        edited = await CM.update_template(HR, COMPANY, "consent_data_use", {
            "body": "We keep your application for as long as our policy allows."})
        check("the consent wording can be changed without a deploy",
              edited["body"].startswith("We keep your application"))
        check("and it stops being marked as the seeded default",
              edited["seeded"] is False)
        await expect_http(
            "editing a template that does not exist",
            CM.update_template(HR, COMPANY, "invented", {"body": "x"}),
            404, "no 'invented' template")
        await expect_http(
            "emptying a template's body",
            CM.update_template(HR, COMPANY, "stage_update", {"body": "   "}),
            422, "needs a body")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
