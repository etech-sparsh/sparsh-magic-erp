"""Phase 11-R Item 3 verification harness -- appointment letters.

Covers: the Offer-Accepted gate, one live letter per candidate, draft versioning, the
send/cancel lifecycle, the candidate's pipeline stage, the public page (a Generated letter
is invisible), first-sight tracking, acknowledgement with a required signature, CTC
redaction, and the lifecycle-table wiring that keeps the funnel honest.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_appointments   (from backend/)
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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_HOD = str(ObjectId()), str(ObjectId())

    def cand(uk, status, request_no="HR-REQ-2026-001"):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": f"Cand {uk}", "can_email": f"{uk}@x.com",
                "application_status": status, "request_no": request_no}

    candidates = FakeCollection([
        cand("CAN-001", S.OFFER_ACCEPTED.value),
        cand("CAN-002", S.SELECTED.value),                       # not accepted yet
        cand("CAN-003", S.OFFER_ACCEPTED.value),
        cand("CAN-004", S.OFFER_ACCEPTED.value, "HR-REQ-2026-002"),
    ])
    offers_coll = FakeCollection([
        {"_id": ObjectId(), "offer_no": "OFR-2026-001", "company_id": COMPANY,
         "uk": "CAN-001", "status": M.OfferStatus.ACCEPTED.value, "ctc": 900000,
         "joining_date": FUTURE, "designation": "Analyst", "company_name": "Acme",
         "location": "Pune"},
        {"_id": ObjectId(), "offer_no": "OFR-2026-003", "company_id": COMPANY,
         "uk": "CAN-003", "status": M.OfferStatus.ACCEPTED.value, "ctc": 700000,
         "joining_date": FUTURE, "designation": "Engineer"},
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_HOD, "designation_name": "Analyst", "department_name": "Ops",
         "work_location": "Pune"},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "created_by": U_HR, "designation_name": "Engineer"},
    ])
    appts = FakeCollection()
    links_coll = FakeCollection()
    docs_coll = FakeCollection()
    types_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_OFFERS: offers_coll,
             M.COLL_REQUISITIONS: reqs, M.COLL_APPOINTMENTS: appts,
             M.COLL_LINKS: links_coll, M.COLL_DOCUMENTS: docs_coll,
             M.COLL_DOCUMENT_TYPES: types_coll, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_appointment_service as APS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    import app.services.hrms_document_service as DS
    for mod in (APS, AUD, IDS, LS, DS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    APS.notify_user = fake_notify_user
    APS.notify_hrms_role = fake_notify_role

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    INTERNAL = {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff"}

    try:
        # =================================================================
        section("The Offer-Accepted gate")
        # =================================================================
        # Widened to include Pre-Onboarding: onboarding now opens automatically the instant
        # an offer is accepted (BA Functional Design §7.5), so a candidate no longer rests
        # at Offer Accepted -- without this, an appointment letter could never legally be
        # issued at all. Pre-Onboarding is strictly LATER in the same forward chain, so it
        # still means exactly what this gate asks: "has accepted an offer".
        check("Offer Accepted or later (Pre-Onboarding) may be appointed",
              APS.APPOINTABLE_STATUSES == {S.OFFER_ACCEPTED, S.PRE_ONBOARDING})
        await expect_http("appointing a merely Selected candidate",
                          APS.create_appointment(HR, COMPANY, {"uk": "CAN-002"}),
                          409, "accepted their offer")
        await expect_http("appointing an unknown candidate",
                          APS.create_appointment(HR, COMPANY, {"uk": "CAN-999"}), 404)
        await expect_http("no candidate chosen",
                          APS.create_appointment(HR, COMPANY, {}), 422)

        eligible = await APS.eligible_candidates(HR, COMPANY)
        uks = {c["uk"] for c in eligible}
        check("eligible lists accepted candidates", {"CAN-001", "CAN-003"} <= uks)
        check("it excludes a candidate who has not accepted", "CAN-002" not in uks)
        check("terms are suggested from the accepted offer",
              next(c for c in eligible if c["uk"] == "CAN-001")["suggested_ctc"] == 900000)

        # =================================================================
        section("Generate")
        # =================================================================
        appt = await APS.create_appointment(HR, COMPANY, {"uk": "CAN-001"})
        check("an appointment number is minted",
              appt["appointment_no"].startswith("APT-"))
        check("it starts Generated",
              appt["status"] == M.AppointmentStatus.GENERATED.value)
        check("terms default from the ACCEPTED OFFER, not retyped",
              appt["ctc"] == 900000 and appt["joining_date"] == FUTURE
              and appt["designation"] == "Analyst")
        check("the department comes from the requisition", appt["department"] == "Ops")
        check("an access code is minted", len(appt["access_code"]) >= 20)
        check("the offer it follows is recorded", appt["offer_no"] == "OFR-2026-001")
        check("generation is audited",
              any(a["action"] == M.AUDIT_APPOINTMENT_GENERATED for a in audit_log.docs))

        await expect_http("a second live letter for the same candidate",
                          APS.create_appointment(HR, COMPANY, {"uk": "CAN-001"}),
                          409, "already has an appointment letter")

        # =================================================================
        section("Only a Generated letter is editable")
        # =================================================================
        check("the editable set is exactly Generated",
              M.EDITABLE_APPOINTMENT_STATUSES == {M.AppointmentStatus.GENERATED})
        edited = await APS.update_appointment(HR, COMPANY, appt["appointment_no"],
                                              {"location": "Mumbai"})
        check("an edit lands", edited["location"] == "Mumbai")
        check("the version is bumped", edited["version"] == 2)
        check("the previous body is archived", len(edited["history"]) == 1)
        await expect_http("an empty edit",
                          APS.update_appointment(HR, COMPANY, appt["appointment_no"], {}),
                          400)
        await expect_http("a negative CTC",
                          APS.update_appointment(HR, COMPANY, appt["appointment_no"],
                                                 {"ctc": -5}),
                          422)
        await expect_http("a malformed joining date",
                          APS.update_appointment(HR, COMPANY, appt["appointment_no"],
                                                 {"joining_date": "31-12-2026"}),
                          422)

        # =================================================================
        section("Send")
        # =================================================================
        await expect_http("sending with no signature",
                          APS.send_appointment(HR, COMPANY, appt["appointment_no"], {}),
                          422, "signatory")

        out = await APS.send_appointment(HR, COMPANY, appt["appointment_no"],
                                         {"signature": "R. Mehta"})
        check("the letter is Sent", out["status"] == M.AppointmentStatus.SENT.value)
        check("the signature is recorded", out["signature"] == "R. Mehta")

        moved = await candidates.find_one({"uk": "CAN-001"})
        check("the candidate advances to Appointment Letter Sent",
              moved["application_status"] == S.APPOINTMENT_LETTER_SENT.value)
        check("the stage move is audited",
              any(a["action"] == M.AUDIT_STAGE_CHANGED
                  and "Appointment Letter Sent" in (a.get("detail") or "")
                  for a in audit_log.docs))

        registered = await links_coll.find_one({"code": appt["access_code"]})
        check("the public link is registered (Item 1)",
              registered is not None and registered["kind"] == "appointment")

        filed = [d for d in docs_coll.docs
                 if d.get("reference") == appt["appointment_no"]]
        check("the letter is filed as a document (Item 2)", len(filed) == 1)
        check("it is filed against the candidate",
              filed[0]["owner_id"] == "CAN-001" and filed[0]["owner_type"] == "candidate")
        check("HR is notified",
              any(kind == "role" and "sent" in title.lower()
                  for kind, _who, title in sent))

        await expect_http("sending twice",
                          APS.send_appointment(HR, COMPANY, appt["appointment_no"],
                                               {"signature": "R. Mehta"}),
                          409, "already")
        await expect_http("editing after sending",
                          APS.update_appointment(HR, COMPANY, appt["appointment_no"],
                                                 {"location": "Delhi"}),
                          409, "no longer be edited")

        # =================================================================
        section("The public page")
        # =================================================================
        draft = await APS.create_appointment(HR, COMPANY, {"uk": "CAN-003"})
        await expect_http("a GENERATED letter on the public page (invisible)",
                          APS.get_public_appointment(draft["access_code"]),
                          404, "not valid")
        await expect_http("an unknown code",
                          APS.get_public_appointment("nope0000000000000000"), 404)

        page = await APS.get_public_appointment(appt["access_code"])
        check("the candidate can read their letter", page["ok"] is True)
        check("the body is rendered with the placeholders filled",
              "{designation}" not in page["content"] and "Analyst" in page["content"])
        for leak in ("company_id", "request_no", "uk", "offer_no", "access_code"):
            check(f"the public payload omits {leak}", leak not in page)

        after_view = await appts.find_one({"appointment_no": appt["appointment_no"]})
        check("first sight moves Sent -> Pending Acknowledgement",
              after_view["status"] == M.AppointmentStatus.PENDING_ACK.value)
        await APS.get_public_appointment(appt["access_code"])
        again = await appts.find_one({"appointment_no": appt["appointment_no"]})
        check("re-reading does not walk the status backwards",
              again["status"] == M.AppointmentStatus.PENDING_ACK.value)

        # =================================================================
        section("Acknowledgement")
        # =================================================================
        await expect_http("acknowledging with no signature",
                          APS.acknowledge_appointment(appt["access_code"], {}),
                          422, "full name")

        # §7.5 Stage 7 -- the NDA, Code of Conduct and required policies are signed with
        # the letter, and one signature must not silently stand for all of them.
        public = await APS.get_public_appointment(appt["access_code"])
        check("the joiner is shown the employment documents to sign",
              [d["doc"] for d in public["documents"]]
              == list(M.EMPLOYMENT_DOCUMENTS))
        check("and which of them are required",
              [d["required"] for d in public["documents"]]
              == list(M.EMPLOYMENT_DOCUMENTS.values()))

        await expect_http("signing without accepting the required documents",
                          APS.acknowledge_appointment(
                              appt["access_code"], {"signature": "Cand CAN-001"}),
                          422, "read and accept each document")
        await expect_http("accepting only some of them",
                          APS.acknowledge_appointment(
                              appt["access_code"],
                              {"signature": "Cand CAN-001",
                               "documents": ["Non-Disclosure Agreement"]}),
                          422, "Code of Conduct")

        required_docs = [d for d, req in M.EMPLOYMENT_DOCUMENTS.items() if req]
        ack = await APS.acknowledge_appointment(
            appt["access_code"], {"signature": "Cand CAN-001", "note": "Looking forward",
                                  "documents": required_docs})
        check("the acknowledgement is recorded",
              ack["status"] == M.AppointmentStatus.ACKNOWLEDGED.value)
        signed = await appts.find_one({"appointment_no": appt["appointment_no"]})
        check("each accepted document is stamped in its own right",
              all(d["acknowledged_at"] for d in signed["document_acks"]
                  if d["doc"] in required_docs))
        check("the same signature is recorded against each one",
              all(d["signature"] == "Cand CAN-001" for d in signed["document_acks"]
                  if d["doc"] in required_docs))
        check("an optional document left unticked stays unsigned",
              all(d["acknowledged_at"] is None for d in signed["document_acks"]
                  if d["doc"] not in required_docs))
        stored = await appts.find_one({"appointment_no": appt["appointment_no"]})
        check("the signature is kept",
              stored["acknowledgement_signature"] == "Cand CAN-001")
        check("acknowledgement is audited",
              any(a["action"] == M.AUDIT_APPOINTMENT_ACK for a in audit_log.docs))
        check("the filed document is flipped to Verified",
              next(d for d in docs_coll.docs
                   if d.get("reference") == appt["appointment_no"])["status"]
              == M.DocumentStatus.VERIFIED.value)

        await expect_http("acknowledging twice",
                          APS.acknowledge_appointment(appt["access_code"],
                                                      {"signature": "Cand CAN-001"}),
                          409, "already")

        # =================================================================
        section("Cancel")
        # =================================================================
        await expect_http("cancelling an ACKNOWLEDGED letter",
                          APS.cancel_appointment(HR, COMPANY, appt["appointment_no"], {}),
                          409, "already been acknowledged")

        cancelled = await APS.cancel_appointment(
            HR, COMPANY, draft["appointment_no"], {"reason": "wrong terms"})
        check("a letter can be cancelled", cancelled["cancelled"] is True)
        await expect_http("cancelling twice",
                          APS.cancel_appointment(HR, COMPANY, draft["appointment_no"], {}),
                          409, "already cancelled")
        fresh = await APS.create_appointment(HR, COMPANY, {"uk": "CAN-003"})
        check("a cancelled letter does not block a fresh one",
              fresh["appointment_no"] != draft["appointment_no"])

        # =================================================================
        section("CTC redaction and row scope")
        # =================================================================
        listing = await APS.list_appointments(HR, COMPANY)
        check("HR sees the CTC", listing["ctc_visible"] is True)
        internal_view = await APS.list_appointments(INTERNAL, COMPANY)
        check("Sparsh support does NOT see the CTC",
              internal_view["ctc_visible"] is False)
        check("the figure is OMITTED, not blanked",
              all("ctc" not in a for a in internal_view["appointments"]))

        mgr = await APS.list_appointments(HOD, COMPANY)
        check("a manager is told their view is narrowed",
              mgr["scoped_to_own_requisitions"] is True)
        check("a manager sees only their own requisitions",
              all(a["request_no"] == "HR-REQ-2026-001" for a in mgr["appointments"]))

        # =================================================================
        section("Lifecycle wiring -- the tables agree")
        # =================================================================
        check("Offer Accepted -> Appointment Letter Sent is legal",
              M.can_transition(S.OFFER_ACCEPTED, S.APPOINTMENT_LETTER_SENT))
        check("Appointment Letter Sent -> Pre-Onboarding is legal",
              M.can_transition(S.APPOINTMENT_LETTER_SENT, S.PRE_ONBOARDING))
        check("the DIRECT Offer Accepted -> Pre-Onboarding edge is kept "
              "(the letter is optional)",
              M.can_transition(S.OFFER_ACCEPTED, S.PRE_ONBOARDING))
        check("it is onboardable", S.APPOINTMENT_LETTER_SENT in M.ONBOARDABLE_STATUSES)
        check("it counts as filling the vacancy", S.APPOINTMENT_LETTER_SENT in M.FILLED_STATUSES)
        check("it ranks in the accepted band, not above it",
              M.STAGE_RANK[S.APPOINTMENT_LETTER_SENT] == M.STAGE_RANK[S.OFFER_ACCEPTED] == 7)
        check("it appears in exactly one pipeline column",
              sum(1 for _k, _l, ss in M.PIPELINE_COLUMNS
                  if S.APPOINTMENT_LETTER_SENT in ss) == 1)
        check("it has a journey colour",
              S.APPOINTMENT_LETTER_SENT in M.JOURNEY_STATUS_KINDS)
        check("it is on the journey rail",
              any(S.APPOINTMENT_LETTER_SENT in ss for _l, ss in M.JOURNEY_RAIL))
        check("the funnel is still monotonic",
              all(a[2] < b[2] for a, b in zip(M.FUNNEL_STAGES, M.FUNNEL_STAGES[1:])))

        # =================================================================
        section("Capabilities")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR holds read, write and send",
              can(HR, M.Cap.APPOINTMENT_READ) and can(HR, M.Cap.APPOINTMENT_WRITE)
              and can(HR, M.Cap.APPOINTMENT_SEND))
        check("Sparsh support reads but cannot commit the client",
              can(INTERNAL, M.Cap.APPOINTMENT_READ)
              and not can(INTERNAL, M.Cap.APPOINTMENT_SEND))
        check("a manager reads only",
              can(HOD, M.Cap.APPOINTMENT_READ)
              and not can(HOD, M.Cap.APPOINTMENT_WRITE))
        check("send is a SEPARATE capability from write",
              M.Cap.APPOINTMENT_SEND.value != M.Cap.APPOINTMENT_WRITE.value)

        # =================================================================
        section("Public surface declarations")
        # =================================================================
        from app.utils.hrms_public_guard import RATE_LIMITS
        check("the appointment view is rate limited", "appointment-view" in RATE_LIMITS)
        check("acknowledgement is rate limited more tightly",
              RATE_LIMITS["appointment-ack"][0] < RATE_LIMITS["appointment-view"][0])
        idx = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES
               if c == M.COLL_APPOINTMENTS]
        check("the access code is unique", ("hrms_appointments", "uniq_access_code") in idx)
        check("one letter per candidate is enforced at the DB level",
              ("hrms_appointments", "uniq_candidate") in idx)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
