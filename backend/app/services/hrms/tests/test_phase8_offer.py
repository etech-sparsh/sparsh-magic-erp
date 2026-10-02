"""Phase 8 verification harness -- offers + public accept/decline + requisition closure.

Covers: the Selected gate, one-live-offer-per-candidate, draft versioning, the send/revoke
lifecycle, CTC redaction, the public letter (draft invisible), accept/decline, and the
Module 16 auto-closure arithmetic.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase8_offer   (from backend/)
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
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
PAST = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere -- each has its own test
    # file (test_int12_client_track), and a failure here should name THIS file's control
    # rather than a precondition it never set up.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_MD, U_HOD = (str(ObjectId()) for _ in range(3))

    def cand(uk, status, request_no="HR-REQ-2026-001", **extra):
        d = {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
             "candidate_name": f"Cand {uk}", "can_email": f"{uk}@x.com",
             "application_status": status, "request_no": request_no,
             "jd_no": "JD-2026-001"}
        d.update(extra)
        return d

    candidates = FakeCollection([
        cand("CAN-001", S.SELECTED.value),
        cand("CAN-002", S.INTERVIEW_SCHEDULED.value),        # not Selected yet
        cand("CAN-003", S.SELECTED.value),
        cand("CAN-004", S.SELECTED.value),
        cand("CAN-005", S.SELECTED.value, expected_ctc="750000"),
        cand("CAN-006", S.SELECTED.value, request_no="HR-REQ-2026-002"),
        cand("CAN-007", S.SELECTED.value, request_no="HR-REQ-2026-002"),
    ])
    jds = FakeCollection([
        {"_id": ObjectId(), "jd_no": "JD-2026-001", "company_id": COMPANY, "ctc": "900000"},
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "designation_name": "Analyst", "vacancy": 1, "offering_ctc": 850000,
         "closing_status": M.ReqClosing.OPEN.value, "work_location": "Pune"},
        # Two vacancies -- closure must not fire until BOTH are filled.
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "designation_name": "Engineer", "vacancy": 2,
         "closing_status": M.ReqClosing.OPEN.value},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "designation_name": "OnHold", "vacancy": 1,
         "closing_status": M.ReqClosing.HOLD.value},
    ])
    offers_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_JOB_DESCRIPTIONS: jds,
             M.COLL_REQUISITIONS: reqs, M.COLL_OFFERS: offers_coll,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_offer_service as OS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (OS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    OS.notify_user = fake_notify_user
    OS.notify_hrms_role = fake_notify_role

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "full_name": "Mira MD"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    async def draft(uk, **over):
        payload = {"uk": uk, "ctc": 800000, "joining_date": FUTURE}
        payload.update(over)
        return await OS.create_offer(HR, COMPANY, payload)

    try:
        from app.utils import hrms_access as A

        # =================================================================
        section("Capability matrix (Phase 8)")
        # =================================================================
        check("HR can write and send", A.can(HR, M.Cap.OFFER_WRITE) and A.can(HR, M.Cap.OFFER_SEND))
        check("MD can write and send", A.can(MD, M.Cap.OFFER_WRITE) and A.can(MD, M.Cap.OFFER_SEND))
        check("MANAGER can read only",
              A.can(HOD, M.Cap.OFFER_READ) and not A.can(HOD, M.Cap.OFFER_WRITE)
              and not A.can(HOD, M.Cap.OFFER_SEND))
        # INTERNAL may observe the pipeline but never commits the company to a salary.
        check("INTERNAL can read but not write/send",
              A.can(INTERNAL, M.Cap.OFFER_READ) and not A.can(INTERNAL, M.Cap.OFFER_WRITE))

        # =================================================================
        section("The Selected gate")
        # =================================================================
        await expect_http("offering a candidate who is not Selected", draft("CAN-002"),
                          409, "has been Selected")
        await expect_http("unknown candidate", draft("CAN-NOPE"), 404)
        await expect_http("no candidate", OS.create_offer(HR, COMPANY, {}), 422,
                          "Select a candidate")

        o1 = await draft("CAN-001")
        check("draft created", o1["offer_no"].startswith("OFR-"))
        check("starts as Draft", o1["status"] == M.OfferStatus.DRAFT.value)
        check("version starts at 1", o1["version"] == 1)
        check("designation defaults from the requisition", o1["designation"] == "Analyst")
        check("location defaults from the requisition", o1["location"] == "Pune")
        check("access code is 128-bit", len(o1["access_code"]) >= 20)
        check("creation audited",
              any(x["action"] == M.AUDIT_OFFER_CREATED for x in audit_log.docs))

        await expect_http("a second live offer for the same candidate", draft("CAN-001"),
                          409, "already has a live offer")

        section("Money and date validation")
        await expect_http("zero CTC", draft("CAN-003", ctc=0), 422, "greater than zero")
        await expect_http("negative CTC", draft("CAN-003", ctc=-1), 422)
        await expect_http("non-numeric CTC", draft("CAN-003", ctc="lots"), 422, "must be a number")
        await expect_http("absurd CTC", draft("CAN-003", ctc=10**12), 422, "implausibly")
        await expect_http("no joining date", draft("CAN-003", joining_date=""),
                          422, "joining date is required")
        await expect_http("malformed joining date", draft("CAN-003", joining_date="31-12-2026"),
                          422, "YYYY-MM-DD")
        await expect_http("joining date in the past", draft("CAN-003", joining_date=PAST),
                          422, "cannot be in the past")

        section("Suggested CTC comes from the most considered source")
        offerable = await OS.offerable_candidates(HR, COMPANY)
        by_uk = {c["uk"]: c for c in offerable}
        check("CAN-001 already has an offer, so is not offerable", "CAN-001" not in by_uk)
        # JD (900000) outranks the requisition (850000) and the candidate's ask.
        check("JD CTC wins over the requisition", by_uk["CAN-003"]["suggested_ctc"] == 900000.0)

        # =================================================================
        section("Draft editing is versioned")
        # =================================================================
        edited = await OS.update_offer(HR, COMPANY, o1["offer_no"],
                                       {"content": "Revised terms.", "ctc": 950000})
        check("edit applied", edited["content"] == "Revised terms.")
        check("version bumped to 2", edited["version"] == 2)
        check("previous body archived", len(edited["history"]) == 1)
        check("history records what the letter said BEFORE the edit",
              edited["history"][0]["ctc"] == 800000.0)
        check("history records who edited it",
              edited["history"][0]["edited_by"] == "Hana HR")
        await OS.update_offer(HR, COMPANY, o1["offer_no"], {"content": "Third version."})
        again = await offers_coll.find_one({"offer_no": o1["offer_no"]})
        check("every edit archives another version", len(again["history"]) == 2)
        check("version now 3", again["version"] == 3)

        await expect_http("empty letter body",
                          OS.update_offer(HR, COMPANY, o1["offer_no"], {"content": "   "}),
                          422, "cannot be empty")
        await expect_http("no fields",
                          OS.update_offer(HR, COMPANY, o1["offer_no"], {}), 400)
        await expect_http("unknown offer",
                          OS.update_offer(HR, COMPANY, "OFR-NOPE", {"content": "x"}), 404)

        # =================================================================
        section("Sending")
        # =================================================================
        await expect_http("sending with no signature",
                          OS.send_offer(HR, COMPANY, o1["offer_no"], {}),
                          422, "authorised signatory")
        issued = await OS.send_offer(HR, COMPANY, o1["offer_no"], {"signature": "Mira MD"})
        check("status becomes Sent", issued["status"] == M.OfferStatus.SENT.value)
        check("signature stored", issued["signature"] == "Mira MD")
        got = (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
        check("candidate advances to Offer Generated", got == S.OFFER_GENERATED.value)
        check("send audited", any(x["action"] == M.AUDIT_OFFER_SENT for x in audit_log.docs))

        await expect_http("sending twice",
                          OS.send_offer(HR, COMPANY, o1["offer_no"], {"signature": "X"}),
                          409, "already")
        # This is the point of versioning: the candidate may be reading it.
        await expect_http("editing after sending",
                          OS.update_offer(HR, COMPANY, o1["offer_no"], {"content": "sneaky"}),
                          409, "no longer be edited")
        await expect_http("deleting a sent offer",
                          OS.delete_offer(HR, COMPANY, o1["offer_no"]),
                          409, "revoke it instead")

        section("Create-and-send in one action")
        o2 = await draft("CAN-003", send_now=True, signature="Mira MD")
        check("created and sent together", o2["status"] == M.OfferStatus.SENT.value)

        # An operation that reports failure must not half-succeed: validating the signature
        # only AFTER inserting would leave an orphaned draft behind.
        before = len(offers_coll.docs)
        await expect_http("send_now with no signature",
                          draft("CAN-004", send_now=True), 422, "authorised signatory")
        check("nothing was written when create-and-send failed validation",
              len(offers_coll.docs) == before)

        # =================================================================
        section("CTC redaction follows the salary boundary")
        # =================================================================
        hr_list = await OS.list_offers(HR, COMPANY)
        check("HR sees CTC", hr_list["ctc_visible"] is True)
        check("CTC present on rows", all("ctc" in o for o in hr_list["offers"]))
        internal_list = await OS.list_offers(INTERNAL, COMPANY)
        check("INTERNAL does not see CTC", internal_list["ctc_visible"] is False)
        check("CTC OMITTED, not nulled",
              all("ctc" not in o for o in internal_list["offers"]))
        check("archived versions are redacted too",
              all("ctc" not in h for o in internal_list["offers"] for h in (o.get("history") or [])))
        check("access code returned only while the link is live",
              all(("access_code" in o) == (o["status"] == M.OfferStatus.SENT.value)
                  for o in hr_list["offers"]))

        # =================================================================
        section("The public letter")
        # =================================================================
        draft_only = await draft("CAN-004")
        await expect_http("a DRAFT is invisible publicly (same 404 as an unknown code)",
                          OS.get_public_offer(draft_only["access_code"]), 404, "not valid")
        await expect_http("unknown code", OS.get_public_offer("z" * 22), 404)

        public = await OS.get_public_offer(issued["access_code"])
        check("letter returned", public["offer_no"] == o1["offer_no"])
        check("placeholders rendered", "{designation}" not in (public["content"] or ""))
        check("already_responded false while awaiting", public["already_responded"] is False)
        for leak in ("company_id", "uk", "request_no", "access_code", "created_by", "history"):
            check(f"public letter omits {leak}", leak not in public)

        section("Accept / decline")
        await expect_http("accepting with no signature",
                          OS.respond_to_offer(issued["access_code"], {"action": "accept"}),
                          422, "type your full name")
        await expect_http("an unknown action",
                          OS.respond_to_offer(issued["access_code"], {"action": "maybe"}),
                          422, "accept or decline")

        accepted = await OS.respond_to_offer(
            issued["access_code"], {"action": "accept", "signature": "Cand CAN-001"})
        check("accepted", accepted["status"] == M.OfferStatus.ACCEPTED.value)
        got = (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
        # BA Functional Design §7.5: onboarding opens automatically the moment an offer is
        # accepted (trigger: "Offer accepted"), which itself advances the candidate straight
        # on to Pre-Onboarding -- accepting no longer leaves them resting at Offer Accepted.
        check("candidate advances to Pre-Onboarding (onboarding auto-starts on acceptance)",
              got == S.PRE_ONBOARDING.value)
        onb = await mongo.get_collection(M.COLL_ONBOARDING).find_one({"uk": "CAN-001"})
        check("an onboarding case was actually opened", onb is not None)
        check("HR notified", any(s[0] == "role" for s in sent))
        check("acceptance audited",
              any(x["action"] == M.AUDIT_OFFER_ACCEPTED for x in audit_log.docs))
        await expect_http("responding twice",
                          OS.respond_to_offer(issued["access_code"],
                                              {"action": "decline"}), 409, "already responded")

        # Declining needs no signature -- demanding one from someone walking away is
        # friction with no purpose.
        declined = await OS.respond_to_offer(
            o2["access_code"], {"action": "decline", "note": "Accepted another role"})
        check("declined without a signature", declined["status"] == M.OfferStatus.DECLINED.value)
        got = (await candidates.find_one({"uk": "CAN-003"}))["application_status"]
        check("candidate moves to Offer Declined", got == S.OFFER_DECLINED.value)
        stored = await offers_coll.find_one({"offer_no": o2["offer_no"]})
        check("the candidate's note is kept",
              stored["response_note"] == "Accepted another role")

        section("Revoke")
        o3 = await draft("CAN-005")
        await expect_http("revoking a draft",
                          OS.revoke_offer(HR, COMPANY, o3["offer_no"], {}),
                          409, "Only a sent offer")
        await OS.send_offer(HR, COMPANY, o3["offer_no"], {"signature": "Mira MD"})
        gone = await OS.revoke_offer(HR, COMPANY, o3["offer_no"], {"reason": "Role frozen"})
        check("revoked", gone["revoked"] is True)
        await expect_http("a revoked link is Gone, not merely invalid",
                          OS.get_public_offer(o3["access_code"]), 410, "withdrawn")
        await expect_http("responding to a revoked offer",
                          OS.respond_to_offer(o3["access_code"],
                                              {"action": "accept", "signature": "X"}),
                          410, "withdrawn")
        # Revoking must also walk the candidate back, or they are stranded: no live offer,
        # yet unable to receive one (a new offer requires Selected).
        walked_back = (await candidates.find_one({"uk": "CAN-005"}))["application_status"]
        check("revoking returns the candidate to Selected", walked_back == S.SELECTED.value)
        o3b = await draft("CAN-005")
        check("so revised terms can be issued after a revoke",
              o3b["offer_no"] != o3["offer_no"])

        section("Delete a draft")
        deleted = await OS.delete_offer(HR, COMPANY, draft_only["offer_no"])
        check("draft deleted", deleted["deleted"] is True)
        await expect_http("deleting twice",
                          OS.delete_offer(HR, COMPANY, draft_only["offer_no"]), 404)

        # =================================================================
        section("Requisition auto-closure (Module 16)")
        # =================================================================
        req1 = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("a 1-vacancy requisition closes as Hired once its offer is accepted",
              req1["closing_status"] == M.ReqClosing.HIRED.value)
        check("auto-closure audited",
              any(x["action"] == M.AUDIT_REQ_AUTO_CLOSED for x in audit_log.docs))
        check("HR and MD are told", any(s[0] == "role" and "HR" in s[1] for s in sent))

        # HR-REQ-2026-002 has TWO vacancies.
        o6 = await draft("CAN-006")
        await OS.send_offer(HR, COMPANY, o6["offer_no"], {"signature": "Mira MD"})
        await OS.respond_to_offer(o6["access_code"],
                                  {"action": "accept", "signature": "Cand CAN-006"})
        req2 = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        check("a 2-vacancy requisition stays Open after ONE acceptance",
              req2["closing_status"] == M.ReqClosing.OPEN.value)

        o7 = await draft("CAN-007")
        await OS.send_offer(HR, COMPANY, o7["offer_no"], {"signature": "Mira MD"})
        await OS.respond_to_offer(o7["access_code"],
                                  {"action": "accept", "signature": "Cand CAN-007"})
        req2 = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        check("it closes once BOTH vacancies are filled",
              req2["closing_status"] == M.ReqClosing.HIRED.value)

        # A human decision outranks the arithmetic.
        result = await OS.reconcile_requisition_closure(HR, COMPANY, "HR-REQ-2026-003")
        check("a Hold requisition is never auto-closed", result is None)
        req3 = await reqs.find_one({"request_no": "HR-REQ-2026-003"})
        check("its status is untouched", req3["closing_status"] == M.ReqClosing.HOLD.value)
        check("re-running closure on an already-Hired requisition is a no-op",
              await OS.reconcile_requisition_closure(HR, COMPANY, "HR-REQ-2026-001") is None)
        check("a missing requisition is handled",
              await OS.reconcile_requisition_closure(HR, COMPANY, None) is None)

        # =================================================================
        section("Letter templating is inert")
        # =================================================================
        rendered = M.render_offer_body(
            "Role {designation} at {company}, {ctc}, from {joining_date}. Unknown {oops}",
            designation="Analyst", company="Acme", ctc="9,00,000", joining_date="2026-09-01")
        check("known placeholders filled", "Analyst" in rendered and "Acme" in rendered)
        check("an unknown placeholder renders harmlessly", "{oops}" in rendered)
        check("a stray brace does not raise",
              isinstance(M.render_offer_body("50% of {", designation="", company="",
                                             ctc="", joining_date=""), str))

        section("Index registry (Phase 8 additions)")
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("offer_no unique",
              any(c == M.COLL_OFFERS and n == "uniq_offer_no" for c, n in names))
        check("access_code unique",
              any(c == M.COLL_OFFERS and n == "uniq_access_code" for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))

        section("Lifecycle edges agree with the Phase 5 graph")
        check("Selected -> Offer Generated",
              M.can_transition(S.SELECTED, S.OFFER_GENERATED))
        check("Offer Generated -> Accepted",
              M.can_transition(S.OFFER_GENERATED, S.OFFER_ACCEPTED))
        check("Offer Generated -> Declined",
              M.can_transition(S.OFFER_GENERATED, S.OFFER_DECLINED))
        check("Offer Accepted -> Pre-Onboarding (Phase 9's entry point)",
              M.can_transition(S.OFFER_ACCEPTED, S.PRE_ONBOARDING))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
