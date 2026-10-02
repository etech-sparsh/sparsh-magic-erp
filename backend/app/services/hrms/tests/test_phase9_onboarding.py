"""Phase 9 verification harness -- onboarding and the employee handover.

Covers: the Offer-Accepted gate, the pre-onboarding public form, server-side PAN-or-Aadhaar
enforcement, the two-kind checklist, background verification driving `bg_cleared` in both
directions, the blockers on issuing an Employee ID, the handover into the employee master
WITHOUT a login, and linking that record to an account later.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase9_onboarding   (from backend/)
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
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_MD, U_HOD, U_EMP, U_NEW = (str(ObjectId()) for _ in range(5))
    DEPT, DESIG = str(ObjectId()), str(ObjectId())

    def cand(uk, status, **extra):
        d = {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
             "candidate_name": f"Cand {uk}", "can_email": f"{uk.lower()}@x.com",
             "can_contact": "9876543210", "application_status": status,
             "request_no": "HR-REQ-2026-001"}
        d.update(extra)
        return d

    candidates = FakeCollection([
        cand("CAN-001", S.OFFER_ACCEPTED.value),
        cand("CAN-002", S.SELECTED.value),              # accepted nothing yet
        cand("CAN-003", S.OFFER_ACCEPTED.value),
        cand("CAN-004", S.OFFER_ACCEPTED.value),
        cand("CAN-005", S.OFFER_ACCEPTED.value),
        cand("CAN-006", S.INTERVIEW_SCHEDULED.value),
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "designation_name": "Analyst", "department_id": DEPT, "designation_id": DESIG,
         "assignee_id": U_HOD, "vacancy": 5, "closing_status": M.ReqClosing.OPEN.value},
    ])
    offers = FakeCollection([
        {"_id": ObjectId(), "offer_no": "OFR-2026-001", "company_id": COMPANY,
         "uk": "CAN-001", "status": M.OfferStatus.ACCEPTED.value,
         "designation": "Senior Analyst", "joining_date": FUTURE},
    ])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR",
         "is_active": True},
        {"_id": ObjectId(U_NEW), "full_name": "Cand CAN-001", "email": "can-001@x.com",
         "company_id": COMPANY, "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_EMP), "full_name": "Eve Emp", "email": "emp@c1.com",
         "company_id": COMPANY, "role": "clientuser", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": COMPANY, "name": "Analytics", "active": True}])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG), "company_id": COMPANY, "name": "Analyst", "active": True}])
    onboardings = FakeCollection()
    profiles = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_OFFERS: offers, M.COLL_ONBOARDING: onboardings,
             M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_DEPARTMENTS: departments,
             M.COLL_DESIGNATIONS: designations, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, "learners": learners, "staff": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_employee_service as ES
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    # §7.5 Stage 4: the onboarding case reads its background status THROUGH the
    # background service, so that service has to see the same fake store.
    import app.services.hrms_background_service as BGV
    import app.services.hrms_probation_service as PB
    import app.services.hrms_reference_service as REF
    for mod in (OB, ES, AUD, IDS, BGV, REF, PB):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    OB.notify_user = fake_notify_user
    OB.notify_hrms_role = fake_notify_role

    uploaded = []

    def fake_s3(stream, name, mime):
        uploaded.append(name)
        return {"key": f"k/{name}"}

    import app.services.s3_service as S3
    original_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = fake_s3

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "full_name": "Mira MD"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    def upload(name="pan.pdf", mime="application/pdf", data="aGVsbG8=", doc_type=None):
        d = {"name": name, "mime_type": mime, "data": data}
        if doc_type:
            d["doc_type"] = doc_type
        return d

    # One upload per REQUIRED joining document (§7.5). The submission is refused while any
    # required type is missing, so the happy path has to satisfy the catalogue.
    def required_uploads():
        return [upload(name=f"doc{i}.pdf", doc_type=label)
                for i, label in enumerate(
                    k for k, required in M.ONBOARD_DOC_TYPES.items() if required)]

    GOOD = {"pan": "abcde1234f", "aadhaar": "1234 5678 9012",
            "date_of_birth": "1995-04-17", "gender": "Female",
            "bank_name": "HDFC", "bank_account": "12345678", "bank_ifsc": "hdfc0001234",
            "emergency_contact_name": "Ravi", "emergency_contact_phone": "9000000000",
            "emergency_contact_relation": "Father",
            "references": [{"name": "Prof R", "relation": "Mentor", "phone": "9111111111"}],
            "documents": required_uploads()}

    def submission(**over):
        d = {k: v for k, v in GOOD.items()}
        d.update(over)
        return d

    try:
        from app.utils import hrms_access as A

        # =================================================================
        section("Capability matrix (Phase 9)")
        # =================================================================
        for label, user in (("HR", HR), ("MD", MD), ("INTERNAL", INTERNAL)):
            check(f"{label} can read, write and generate an Employee ID",
                  A.can(user, M.Cap.ONBOARDING_READ)
                  and A.can(user, M.Cap.ONBOARDING_WRITE)
                  and A.can(user, M.Cap.ONBOARDING_GENERATE_ID))
        check("MANAGER can read but not write",
              A.can(HOD, M.Cap.ONBOARDING_READ)
              and not A.can(HOD, M.Cap.ONBOARDING_WRITE)
              and not A.can(HOD, M.Cap.ONBOARDING_GENERATE_ID))
        check("EMPLOYEE has no onboarding capability at all",
              not A.can(EMP, M.Cap.ONBOARDING_READ)
              and not A.can(EMP, M.Cap.ONBOARDING_WRITE))
        check("generate_id is a SEPARATE capability from write",
              M.Cap.ONBOARDING_GENERATE_ID.value != M.Cap.ONBOARDING_WRITE.value)

        # =================================================================
        section("The Offer-Accepted gate")
        # =================================================================
        # Phase 11-R Item 3 adds APPOINTMENT_LETTER_SENT, which sits strictly AFTER Offer
        # Accepted. The property this test actually guards is that onboarding cannot begin
        # before the candidate has agreed to join -- so it is asserted as "every onboardable
        # stage is at or past Offer Accepted", which is the rule, rather than as a pinned
        # set, which was only its Phase 9 instance.
        check("nothing before Offer Accepted is onboardable",
              M.ONBOARDABLE_STATUSES == {S.OFFER_ACCEPTED, S.APPOINTMENT_LETTER_SENT}
              and all(M.stage_rank(s) >= M.stage_rank(S.OFFER_ACCEPTED)
                      for s in M.ONBOARDABLE_STATUSES))
        check("the graph agrees: Offer Accepted -> Pre-Onboarding",
              M.can_transition(S.OFFER_ACCEPTED, S.PRE_ONBOARDING))
        check("the graph refuses Selected -> Pre-Onboarding, which is why Selected is out",
              not M.can_transition(S.SELECTED, S.PRE_ONBOARDING))

        await expect_http("onboarding a Selected candidate",
                          OB.start_onboarding(HR, COMPANY, {"uk": "CAN-002"}),
                          409, "accepted an offer")
        await expect_http("onboarding a mid-interview candidate",
                          OB.start_onboarding(HR, COMPANY, {"uk": "CAN-006"}), 409)
        await expect_http("unknown candidate",
                          OB.start_onboarding(HR, COMPANY, {"uk": "CAN-NOPE"}), 404)
        await expect_http("no candidate",
                          OB.start_onboarding(HR, COMPANY, {}), 422, "Choose a candidate")
        await expect_http("a candidate from another company",
                          OB.start_onboarding(HR, OTHER, {"uk": "CAN-001"}), 404)

        # =================================================================
        section("Starting an onboarding")
        # =================================================================
        ob1 = await OB.start_onboarding(HR, COMPANY, {"uk": "CAN-001"})
        no1 = ob1["onb_no"]
        check("ONB number minted", no1.startswith("ONB-"))
        check("status starts at Pre-Onboarding",
              ob1["status"] == M.OnboardStatus.PRE_ONBOARDING.value)
        check("pre-onboarding status starts Pending",
              ob1["pre_status"] == M.PreOnboardStatus.PENDING.value)
        check("background check starts Pending",
              ob1["bg_verification"] == M.BgVerification.PENDING.value)
        check("access code is 128-bit", len(ob1["access_code"]) >= 20)
        check("checklist seeded with every declared item, induction items appended",
              len(ob1["checklist"]) == len(M.ONBOARD_CHECKLIST) + len(M.INDUCTION_CHECKLIST))
        check("no checklist item starts done",
              not any(i["done"] for i in ob1["checklist"]))
        check("progress reports 0 of the full checklist",
              ob1["progress"] == {"done": 0, "total": len(ob1["checklist"]), "percent": 0})
        check("designation taken from the ACCEPTED OFFER, not the requisition",
              ob1["designation"] == "Senior Analyst")
        check("joining date inherited from the offer", ob1["joining_date"] == FUTURE)
        check("department carried from the requisition", ob1["department_id"] == DEPT)
        check("reporting manager defaults to the requisition owner",
              ob1["reporting_manager_id"] == U_HOD)
        check("candidate advanced to Pre-Onboarding",
              (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
              == S.PRE_ONBOARDING.value)
        check("start audited",
              any(x["action"] == M.AUDIT_ONBOARD_STARTED for x in audit_log.docs))
        check("HR notified", any(r == "role" for r, *_ in sent))

        await expect_http("starting a second onboarding for the same person",
                          OB.start_onboarding(HR, COMPANY, {"uk": "CAN-001"}),
                          409, "already being onboarded")
        await expect_http("a malformed joining date",
                          OB.start_onboarding(HR, COMPANY,
                                              {"uk": "CAN-003", "joining_date": "17-04-2026"}),
                          422, "YYYY-MM-DD")

        onboardable = await OB.onboardable_candidates(HR, COMPANY)
        uks = {c["uk"] for c in onboardable}
        check("CAN-001 is no longer onboardable once started", "CAN-001" not in uks)
        check("CAN-003/4/5 are offered", {"CAN-003", "CAN-004", "CAN-005"} <= uks)
        check("a Selected candidate is not offered", "CAN-002" not in uks)

        # =================================================================
        section("The access code is a credential, not list data")
        # =================================================================
        listed = await OB.list_onboardings(HR, COMPANY)
        check("list returns the onboarding", len(listed) == 1)
        check("access_code ABSENT from the list payload", "access_code" not in listed[0])
        check("submission ABSENT from the list payload", "submission" not in listed[0])
        check("progress present on the list row",
              listed[0]["progress"]["total"] == len(M.ONBOARD_CHECKLIST) + len(M.INDUCTION_CHECKLIST))
        detail = await OB.get_onboarding(HR, COMPANY, no1)
        check("access_code present on the DETAIL payload", bool(detail.get("access_code")))

        # =================================================================
        section("The public form -- reads")
        # =================================================================
        code = ob1["access_code"]
        pub = await OB.get_public_onboarding(code)
        check("public read succeeds", pub["ok"] is True)
        check("shows the new hire their own name", pub["candidate_name"] == "Cand CAN-001")
        check("shows the role", pub["designation"] == "Senior Analyst")
        check("not yet submitted", pub["already_submitted"] is False)
        for leaked in ("company_id", "uk", "onb_no", "offer_no", "request_no", "checklist",
                       "bg_verification", "access_code", "submission", "employee_id"):
            check(f"public payload does not leak `{leaked}`", leaked not in pub)
        await expect_http("an unknown code", OB.get_public_onboarding("nope"), 404)
        # Operator injection is stopped at the ROUTE, before the value can reach a query --
        # rule 2 of the public router. Asserted here against the guard itself, and
        # end-to-end through HTTP in test_phase9_integration.
        from app.utils.hrms_public_guard import validate_access_code
        from fastapi import HTTPException as _HE
        for payload in ({"$ne": None}, {"$gt": ""}, "short", "has/slash", None):
            try:
                validate_access_code(payload)
                check(f"guard rejects {payload!r}", False)
            except _HE as e:
                check(f"guard rejects {payload!r}", e.status_code == 404)

        # =================================================================
        section("The public form -- PAN or Aadhaar, enforced SERVER-SIDE")
        # =================================================================
        await expect_http("neither PAN nor Aadhaar",
                          OB.submit_public_onboarding(code, submission(pan="", aadhaar="")),
                          422, "PAN or your Aadhaar")
        await expect_http("a malformed PAN",
                          OB.submit_public_onboarding(code, submission(pan="ABC", aadhaar="")),
                          422, "PAN is not valid")
        await expect_http("a short Aadhaar",
                          OB.submit_public_onboarding(code, submission(pan="", aadhaar="123")),
                          422, "12 digits")
        await expect_http("a malformed IFSC",
                          OB.submit_public_onboarding(code, submission(bank_ifsc="XX")),
                          422, "IFSC")
        await expect_http("a non-numeric bank account",
                          OB.submit_public_onboarding(code, submission(bank_account="12ab34")),
                          422, "digits")
        await expect_http("a date of birth in the future",
                          OB.submit_public_onboarding(code, submission(date_of_birth=FUTURE)),
                          422, "in the past")
        await expect_http("a malformed date of birth",
                          OB.submit_public_onboarding(code, submission(date_of_birth="1995/04/17")),
                          422, "YYYY-MM-DD")
        await expect_http("an unknown gender",
                          OB.submit_public_onboarding(code, submission(gender="Wizard")),
                          422, "gender")
        await expect_http("too many references",
                          OB.submit_public_onboarding(
                              code, submission(references=[{"name": f"R{i}"} for i in range(9)])),
                          422, "maximum")
        await expect_http("too many documents",
                          OB.submit_public_onboarding(
                              code, submission(documents=[upload(f"d{i}.pdf") for i in range(20)])),
                          422, "maximum")
        await expect_http("an executable disguised as a document",
                          OB.submit_public_onboarding(
                              code, submission(documents=[upload("x.exe", "application/x-msdownload")])),
                          415)
        check("nothing was written by any rejected submission",
              (await onboardings.find_one({"onb_no": no1}))["pre_status"]
              == M.PreOnboardStatus.PENDING.value)

        # =================================================================
        section("The public form -- a good submission")
        # =================================================================
        out = await OB.submit_public_onboarding(code, submission())
        check("submission accepted", out["ok"] is True)
        stored = await onboardings.find_one({"onb_no": no1})
        check("status becomes Submitted",
              stored["pre_status"] == M.PreOnboardStatus.SUBMITTED.value)
        check("PAN normalised to upper case", stored["submission"]["pan"] == "ABCDE1234F")
        check("Aadhaar spaces stripped", stored["submission"]["aadhaar"] == "123456789012")
        check("IFSC normalised to upper case",
              stored["submission"]["bank_ifsc"] == "HDFC0001234")
        check("reference recorded", len(stored["submission"]["references"]) == 1)
        check("document stored with its source",
              stored["documents"][0]["source"] == "candidate")
        check("every required document actually uploaded",
              uploaded == [f"onboard_doc{i}.pdf" for i in range(len(uploaded))]
              and len(uploaded) == sum(1 for r in M.ONBOARD_DOC_TYPES.values() if r))
        check("each stored document carries its type",
              sorted(d["doc_type"] for d in stored["documents"])
              == sorted(k for k, r in M.ONBOARD_DOC_TYPES.items() if r))
        check("submission audited",
              any(x["action"] == M.AUDIT_ONBOARD_SUBMITTED for x in audit_log.docs))
        check("HR notified of the submission",
              any(t.startswith("Pre-onboarding submitted") for _, _, t in sent))

        await expect_http("submitting twice",
                          OB.submit_public_onboarding(code, submission()),
                          409, "already been submitted")
        pub2 = await OB.get_public_onboarding(code)
        check("the form now reports already_submitted", pub2["already_submitted"] is True)

        # =================================================================
        section("The checklist has two kinds of item")
        # =================================================================
        check("three items are system-owned",
              M.SYSTEM_CHECKLIST_KEYS == {"employee_id", "documents_verified", "bg_cleared"})
        check("every system key is a real checklist key",
              M.SYSTEM_CHECKLIST_KEYS <= set(M.CHECKLIST_KEYS))
        for key in sorted(M.SYSTEM_CHECKLIST_KEYS):
            await expect_http(f"hand-ticking `{key}`",
                              OB.set_checklist(HR, COMPANY, no1, {"key": key, "done": True}),
                              409, "automatically")
        await expect_http("an unknown checklist key",
                          OB.set_checklist(HR, COMPANY, no1,
                                           {"key": "make_tea", "done": True}),
                          422, "Unknown checklist item")

        after = await OB.set_checklist(HR, COMPANY, no1,
                                       {"key": "asset_issued", "done": True})
        item = next(i for i in after["checklist"] if i["key"] == "asset_issued")
        check("a human item can be ticked", item["done"] is True)
        check("who ticked it is recorded", item["done_by"] == "Hana HR")
        check("when is recorded", item["done_at"] is not None)
        check("progress moves to 1 of 12", after["progress"]["done"] == 1)

        reopened = await OB.set_checklist(HR, COMPANY, no1,
                                          {"key": "asset_issued", "done": False})
        item = next(i for i in reopened["checklist"] if i["key"] == "asset_issued")
        check("un-ticking clears the attribution too",
              item["done"] is False and item["done_by"] is None and item["done_at"] is None)
        await OB.set_checklist(HR, COMPANY, no1, {"key": "asset_issued", "done": True})

        # =================================================================
        section("Background verification drives its checklist item BOTH ways")
        # =================================================================
        bg = await OB.update_bg(HR, COMPANY, no1,
                                {"bg_verification": M.BgVerification.CLEARED, "note": "ok"})
        check("bg_cleared ticks when the check clears",
              next(i for i in bg["checklist"] if i["key"] == "bg_cleared")["done"] is True)
        bg = await OB.update_bg(HR, COMPANY, no1,
                                {"bg_verification": M.BgVerification.FLAGGED})
        check("bg_cleared UN-ticks when the clearance is withdrawn",
              next(i for i in bg["checklist"] if i["key"] == "bg_cleared")["done"] is False)
        check("a flag notifies HR and MD",
              any("flagged" in t.lower() for _, _, t in sent))
        await expect_http("an unknown background outcome",
                          OB.update_bg(HR, COMPANY, no1, {"bg_verification": "Vibes"}),
                          422, "Unknown")

        # =================================================================
        section("Blockers on issuing an Employee ID")
        # =================================================================
        await expect_http("generating an ID while the background check is flagged",
                          OB.generate_employee_id(HR, COMPANY, no1), 409, "flagged")
        blockers = (await OB.get_onboarding(HR, COMPANY, no1))["id_blockers"]
        check("the blocker is explained in prose, not just a boolean",
              any("flagged" in b.lower() for b in blockers))
        check("verification is also listed as a blocker",
              any("verified" in b.lower() for b in blockers))

        await OB.update_bg(HR, COMPANY, no1, {"bg_verification": M.BgVerification.CLEARED})
        await expect_http("generating an ID before the documents are verified",
                          OB.generate_employee_id(HR, COMPANY, no1), 409, "not been verified")

        # ── §7.5 Stage 3 -- per-document verification ──
        section("Document verification (§7.5 Stage 3)")
        tasks = {t["doc_type"]: t
                 for t in (await OB.get_onboarding(HR, COMPANY, no1))["document_tasks"]}
        check("every uploaded document starts Pending",
              all(t["status"] == M.DocStatus.PENDING.value
                  for t in tasks.values() if t["uploaded"]))
        check("an uploaded document records its version",
              tasks["PAN card"]["version"] == 1)

        await expect_http("a verdict on a document nobody uploaded",
                          OB.review_document(HR, COMPANY, no1,
                                             {"doc_type": "No such document",
                                              "status": M.DocStatus.VERIFIED}),
                          404, "uploaded")
        await expect_http("an unknown verdict",
                          OB.review_document(HR, COMPANY, no1,
                                             {"doc_type": "PAN card", "status": "Maybe"}),
                          422, "Pending, Verified, Rejected or Exception")
        await expect_http("rejecting with no reason",
                          OB.review_document(HR, COMPANY, no1,
                                             {"doc_type": "PAN card",
                                              "status": M.DocStatus.REJECTED}),
                          422, "Say why")
        await expect_http("an exception with no reason",
                          OB.review_document(HR, COMPANY, no1,
                                             {"doc_type": "PAN card",
                                              "status": M.DocStatus.EXCEPTION}),
                          422, "Say why")

        rejected = await OB.review_document(
            HR, COMPANY, no1, {"doc_type": "PAN card", "status": M.DocStatus.REJECTED,
                               "note": "The scan is unreadable."})
        pan = next(d for d in rejected["documents"] if d["doc_type"] == "PAN card")
        check("a rejection is recorded on the document",
              pan["status"] == M.DocStatus.REJECTED.value)
        check("who reviewed it is recorded", pan["reviewed_by"] == "Hana HR")
        check("the reason is kept", pan["review_note"] == "The scan is unreadable.")
        check("the verdict is appended to the document's history",
              [h["status"] for h in pan["history"]]
              == [M.DocStatus.PENDING.value, M.DocStatus.REJECTED.value])

        await expect_http("verifying the file while a mandatory document is rejected",
                          OB.verify_documents(HR, COMPANY, no1), 409, "rejected")

        # A replacement arrives: the old version is RETAINED, the new one is v2 and starts
        # unreviewed again.
        await OB.add_documents(HR, COMPANY, no1,
                               {"documents": [upload(name="pan-v2.pdf",
                                                     doc_type="PAN card")]})
        after = await OB.get_onboarding(HR, COMPANY, no1)
        pans = [d for d in after["documents"] if d["doc_type"] == "PAN card"]
        check("the replaced version is retained, not overwritten", len(pans) == 2)
        check("the replacement is version 2",
              sorted(d["version"] for d in pans) == [1, 2])
        check("the superseded version keeps its rejection",
              next(d for d in pans if d["version"] == 1)["status"]
              == M.DocStatus.REJECTED.value)
        check("the task row reads the CURRENT version",
              next(t for t in after["document_tasks"]
                   if t["doc_type"] == "PAN card")["status"]
              == M.DocStatus.PENDING.value)

        for label in (k for k, req in M.ONBOARD_DOC_TYPES.items() if req):
            await OB.review_document(HR, COMPANY, no1,
                                     {"doc_type": label, "status": M.DocStatus.VERIFIED})

        # An OPTIONAL document left Pending must not block anybody.
        check("an optional document left pending is not a blocker",
              not any("Previous employment" in b
                      for b in (await OB.get_onboarding(HR, COMPANY, no1))["id_blockers"]))

        verified = await OB.verify_documents(HR, COMPANY, no1)
        check("verification sets pre-status to Verified",
              verified["pre_status"] == M.PreOnboardStatus.VERIFIED.value)
        check("documents_verified ticks as a consequence",
              next(i for i in verified["checklist"]
                   if i["key"] == "documents_verified")["done"] is True)
        check("who verified is recorded", verified["verified_by"] == "Hana HR")
        check("verification audited",
              any(x["action"] == M.AUDIT_ONBOARD_VERIFIED for x in audit_log.docs))

        # ── §7.5 Stage 4 -- BGV lives INSIDE the onboarding case ──
        section("BGV / reference verification (§7.5 Stage 4)")
        case = await OB.get_onboarding(HR, COMPANY, no1)
        check("the case carries a verification block",
              isinstance(case.get("verification"), dict))
        check("with nothing recorded, the case shows no checks",
              case["verification"]["checks"] == [])

        bgv = store[M.COLL_BACKGROUND_CHECKS]
        await bgv.insert_one({
            "bgv_no": "BGV-TEST-1", "company_id": COMPANY, "uk": "CAN-001",
            "check_type": list(M.REQUIRED_BACKGROUND_CHECKS)[0].value,
            "status": M.BackgroundCheckStatus.FLAGGED.value,
            "created_at": "2026-01-01T00:00:00+00:00"})

        await OB.sync_verification(COMPANY, "CAN-001")
        synced = await OB.get_onboarding(HR, COMPANY, no1)
        check("a flagged check drives the case to Flagged",
              synced["bg_verification"] == M.BgVerification.FLAGGED.value)
        check("bg_cleared un-ticks with it",
              next(i for i in synced["checklist"]
                   if i["key"] == "bg_cleared")["done"] is False)
        check("the case shows the check itself, not just a status",
              len(synced["verification"]["checks"]) == 1)
        check("and says which check is flagged",
              len(synced["verification"]["flagged"]) == 1)

        await expect_http("typing over a status the records own",
                          OB.update_bg(HR, COMPANY, no1,
                                       {"bg_verification": M.BgVerification.CLEARED}),
                          409, "follows it")

        # Clear it the only way that works: through the record.
        await bgv.update_one({"bgv_no": "BGV-TEST-1"},
                             {"$set": {"status": M.BackgroundCheckStatus.CLEARED.value}})
        await OB.sync_verification(COMPANY, "CAN-001")
        after = await OB.get_onboarding(HR, COMPANY, no1)
        check("clearing the check moves the case off Flagged",
              after["bg_verification"] != M.BgVerification.FLAGGED.value)

        # Back to a clean slate so the rest of the run is unaffected.
        await bgv.delete_one({"bgv_no": "BGV-TEST-1"})
        await OB.update_bg(HR, COMPANY, no1,
                           {"bg_verification": M.BgVerification.CLEARED})
        check("with no verification file, the field is settable again",
              (await OB.get_onboarding(HR, COMPANY, no1))["bg_verification"]
              == M.BgVerification.CLEARED.value)

        # ── §7.5 Stage 5 -- onboarding completeness ──
        section("Onboarding completeness (§7.5 Stage 5)")
        comp = (await OB.get_onboarding(HR, COMPANY, no1))["completeness"]
        group_keys = [g["key"] for g in comp["groups"]]
        check("all six groups the BA document names are scored",
              group_keys == ["documents", "personal", "bank", "statutory", "bgv", "tasks"])
        check("the percentage is derived from the items, not stored",
              comp["percent"] == int(round(comp["done"] * 100 / comp["total"])))
        check("it is not yet complete -- joining tasks are outstanding",
              comp["percent"] < 100)
        check("every unmet item is named, not just counted",
              len(comp["missing"]) == comp["total"] - comp["done"])
        check("each missing entry says which group it belongs to",
              all(":" in m for m in comp["missing"]))

        check("documents scored from the verified/exception set",
              next(g for g in comp["groups"] if g["key"] == "documents")["percent"] == 100)
        check("bank details read off the submission",
              next(g for g in comp["groups"] if g["key"] == "bank")["percent"] == 100)
        check("a joiner with no UAN is not marked incomplete for it",
              next(g for g in comp["groups"] if g["key"] == "statutory")["percent"] == 100)
        check("BGV counts as met when this company runs no checks for them",
              next(g for g in comp["groups"] if g["key"] == "bgv")["percent"] == 100)

        # Ticking a human task moves the number, and only by that one item.
        before = comp["percent"]
        await OB.set_checklist(HR, COMPANY, no1,
                               {"key": "email_created", "done": True})
        after_comp = (await OB.get_onboarding(HR, COMPANY, no1))["completeness"]
        check("completing one task raises the percentage",
              after_comp["percent"] > before)
        check("and removes exactly that item from the missing list",
              len(after_comp["missing"]) == len(comp["missing"]) - 1)

        listed = await OB.list_onboardings(HR, COMPANY)
        row = next(r for r in listed if r["onb_no"] == no1)
        check("the board carries the same figure, so HR can scan for who is behind",
              row["completeness"]["percent"] == after_comp["percent"])
        check("the list still withholds the submission it computed from",
              "submission" not in row)

        await OB.update_details(HR, COMPANY, no1, {"joining_date": None})
        await expect_http("generating an ID with no joining date",
                          OB.generate_employee_id(HR, COMPANY, no1), 409, "joining date")
        await OB.update_details(HR, COMPANY, no1, {"joining_date": FUTURE})

        # ── §7.5 Stage 6 -- joining day ──
        section("Joining day (§7.5 Stage 6)")
        await expect_http("issuing an ID before anybody confirmed they turned up",
                          OB.generate_employee_id(HR, COMPANY, no1), 409,
                          "Joining has not been confirmed")
        await expect_http("confirming with no date",
                          OB.confirm_joining(HR, COMPANY, no1, {"actual_doj": ""}),
                          422, "YYYY-MM-DD")
        await expect_http("confirming a joining that has not happened yet",
                          OB.confirm_joining(HR, COMPANY, no1, {"actual_doj": FUTURE}),
                          422, "cannot be in the future")

        TODAY = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        joined = await OB.confirm_joining(HR, COMPANY, no1, {
            "actual_doj": TODAY, "note": "Reported at 9am.",
            "unit": "Head Office", "grade": "L3", "work_location": "Indore",
            "employment_type": M.EmploymentType.FULL_TIME,
            "employment_status": M.EmploymentStatus.ACTIVE,
            "payroll_group": "Monthly - India"})
        check("the ACTUAL joining date is recorded", joined["actual_doj"] == TODAY)
        check("and kept apart from the planned date",
              joined["joining_date"] == FUTURE and joined["actual_doj"] != FUTURE)
        check("who confirmed it is recorded",
              joined["joining_confirmed_by"] == "Hana HR")
        check("the assignment is held on the case",
              joined["grade"] == "L3" and joined["payroll_group"] == "Monthly - India")

        # ── §7.5 Stage 8 -- IT / Admin / Manager tasks ──
        section("Joining tasks by owner (§7.5 Stage 8)")
        items = {i["key"]: i for i in joined["checklist"]}
        check("IT owns the account and access tasks",
              items["email_created"]["owner"] == M.TASK_OWNER_IT
              and items["system_access"]["owner"] == M.TASK_OWNER_IT)
        check("asset issue is IT's, workspace is Admin's",
              items["asset_issued"]["owner"] == M.TASK_OWNER_IT
              and items["workspace"]["owner"] == M.TASK_OWNER_ADMIN)
        check("induction and the team introduction are the manager's",
              items["induction"]["owner"] == M.TASK_OWNER_MANAGER
              and items["buddy_assigned"]["owner"] == M.TASK_OWNER_MANAGER)
        check("HR keeps the items it actually owns",
              items["offer_signed"]["owner"] == M.TASK_OWNER_HR
              and items["bg_cleared"]["owner"] == M.TASK_OWNER_HR)

        check("confirming joining assigns every IT/Admin/Manager task",
              all(i["assigned_at"] for i in joined["checklist"]
                  if i["owner"] in M.TASKS_ASSIGNED_AT_JOINING))
        check("HR's own items are NOT assigned by joining -- they ran from case open",
              all(i["assigned_at"] is None for i in joined["checklist"]
                  if i["owner"] == M.TASK_OWNER_HR))
        check("the owners are told what is now theirs",
              any("IT tasks" in t for _, _, t in sent)
              or any("IT tasks" in str(x) for x in sent))

        check("no blockers remain",
              (await OB.get_onboarding(HR, COMPANY, no1))["can_generate_id"] is True)

        # =================================================================
        section("The handover -- an employee WITHOUT a login")
        # =================================================================
        before_learners = len(learners.docs)
        done = await OB.generate_employee_id(HR, COMPANY, no1)
        emp_code = done["employee_id"]
        check("Employee ID minted", emp_code.startswith("EMP-"))
        check("onboarding moves to Onboarding",
              done["status"] == M.OnboardStatus.ONBOARDING.value)
        check("employee_id checklist item ticks",
              next(i for i in done["checklist"] if i["key"] == "employee_id")["done"] is True)

        profile = await profiles.find_one({"employee_code": emp_code})
        check("an employee profile now exists", profile is not None)
        check("`user_id` is ABSENT, not null -- a null value would still be indexed",
              "user_id" not in profile)
        check("identity captured as a snapshot",
              profile["identity_snapshot"]["name"] == "Cand CAN-001")
        check("traceable back to the candidate", profile["source_uk"] == "CAN-001")
        check("employment starts Active",
              profile["employment_status"] == M.EmploymentStatus.ACTIVE.value)
        # §7.5 Stage 6: the employee starts from the date they ACTUALLY joined, not the
        # date that was planned. Tenure, probation and payroll all run off this.
        check("the ACTUAL joining date is what the employee record carries",
              profile["joined_on"] == TODAY and profile["joined_on"] != FUTURE)
        check("the assignment made at joining carried across",
              profile["grade"] == "L3"
              and profile["work_location"] == "Indore"
              and profile["payroll_group"] == "Monthly - India"
              and profile["unit"] == "Head Office")
        # ── §7.5 Stage 9 -- conversion keeps the recruitment history ──
        check("the candidate record still exists after conversion",
              await candidates.find_one({"uk": "CAN-001", "company_id": COMPANY})
              is not None)
        check("the employee points back to the candidate they came from",
              profile["source_uk"] == "CAN-001")
        by_code = await ES.get_employee_by_code(HR, COMPANY, emp_code)
        check("a joiner with no login can still be opened by employee code",
              by_code is not None and by_code["employee_code"] == emp_code)
        check("and that view carries the link back to recruitment",
              by_code["source_uk"] == "CAN-001")

        # ── §7.5 Stage 10 -- probation opens at joining, for EVERY joiner ──
        prb = await store[M.COLL_PROBATION_REVIEWS].find_one(
            {"company_id": COMPANY, "employee_code": emp_code})
        check("a probation review is opened automatically at joining",
              prb is not None)
        check("and the onboarding carries the internal track discriminator",
              (await onboardings.find_one({"onb_no": no1})).get("requisition_track")
              == "internal")
        check("it runs from the ACTUAL joining date, not the planned one",
              prb["started_on"] == TODAY and prb["started_on"] != FUTURE)
        check("the end date is derived from the configured policy",
              prb["ends_on"] == PB._add_months(TODAY, M.DEFAULT_PROBATION_MONTHS))
        check("and it opens Pending -- joining confirms nobody",
              prb["outcome"] == M.ProbationOutcome.PENDING.value)

        check("department carried across", profile["department_id"] == DEPT)
        check("PAN carried from the submission", profile["pan"] == "ABCDE1234F")
        check("bank details carried from the submission",
              profile["bank_ifsc"] == "HDFC0001234")
        check("NOTHING was written to `learners`", len(learners.docs) == before_learners)
        check("NOTHING was written to `staff`", len(store["staff"].docs) == 0)
        check("candidate advanced to Joined",
              (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
              == S.JOINED.value)
        check("issuance audited",
              any(x["action"] == M.AUDIT_EMPLOYEE_ID_ISSUED for x in audit_log.docs))

        await expect_http("issuing a second Employee ID",
                          OB.generate_employee_id(HR, COMPANY, no1),
                          409, "already been issued")

        # =================================================================
        section("The new hire is visible in the directory immediately")
        # =================================================================
        directory = await ES.list_employees(HR, COMPANY)
        row = next((r for r in directory["employees"] if r["employee_code"] == emp_code), None)
        check("the unlinked employee appears in the directory", row is not None)
        check("named from the snapshot", row["name"] == "Cand CAN-001")
        check("flagged as awaiting a login", row["pending_user_link"] is True)
        check("user_id is None rather than a broken id", row["user_id"] is None)
        check("the directory counts them", directory["pending_links"] >= 1)
        check("the account picker does not crash on a profile with no user_id",
              isinstance(await ES.list_linkable_users(HR, COMPANY), list))

        # =================================================================
        section("Linking a login account later")
        # =================================================================
        await expect_http("linking an unknown employee",
                          ES.link_user(HR, COMPANY, "EMP-NOPE", U_NEW), 404)
        await expect_http("linking an unknown user",
                          ES.link_user(HR, COMPANY, emp_code, str(ObjectId())), 404)
        linked = await ES.link_user(HR, COMPANY, emp_code, U_NEW)
        check("the record is now linked", linked["user_id"] == U_NEW)
        check("identity now comes from the user document", linked["name"] == "Cand CAN-001")
        check("no longer pending", linked.get("pending_user_link") is False)
        check("linking audited",
              any(x["action"] == M.AUDIT_EMPLOYEE_LINKED for x in audit_log.docs))
        await expect_http("linking the same record twice",
                          ES.link_user(HR, COMPANY, emp_code, U_EMP),
                          409, "already linked")

        # =================================================================
        section("Completion")
        # =================================================================
        current = await OB.get_onboarding(HR, COMPANY, no1)
        for item in current["checklist"]:
            if not item["done"] and item["key"] not in M.SYSTEM_CHECKLIST_KEYS:
                current = await OB.set_checklist(HR, COMPANY, no1,
                                                 {"key": item["key"], "done": True})
        check("every item is done",
              current["progress"]["done"] == current["progress"]["total"])
        check("onboarding auto-completes",
              current["status"] == M.OnboardStatus.COMPLETED.value)
        check("candidate reaches Employee Created",
              (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
              == S.EMPLOYEE_CREATED.value)
        check("completion audited",
              any(x["action"] == M.AUDIT_ONBOARD_COMPLETED for x in audit_log.docs))

        await expect_http("editing a completed onboarding",
                          OB.set_checklist(HR, COMPANY, no1,
                                           {"key": "induction", "done": False}),
                          409, "complete")
        await expect_http("uploading to a completed onboarding",
                          OB.add_documents(HR, COMPANY, no1, {"documents": [upload()]}),
                          409, "complete")
        await expect_http("the public form after completion",
                          OB.get_public_onboarding(code), 410)

        # =================================================================
        section("HR-side upload path")
        # =================================================================
        ob2 = await OB.start_onboarding(HR, COMPANY, {"uk": "CAN-003",
                                                      "joining_date": FUTURE})
        no2 = ob2["onb_no"]
        await expect_http("verifying before anything is submitted",
                          OB.verify_documents(HR, COMPANY, no2), 409, "nothing to verify")
        await expect_http("uploading nothing",
                          OB.add_documents(HR, COMPANY, no2, {"documents": []}),
                          422, "at least one")
        added = await OB.add_documents(HR, COMPANY, no2,
                                       {"documents": [upload("aadhaar.pdf")]})
        check("HR upload recorded with its own source",
              added["documents"][0]["source"] == "hr")
        check("HR upload does NOT count as the candidate submitting",
              added["pre_status"] == M.PreOnboardStatus.PENDING.value)

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        await expect_http("reading an onboarding from another company",
                          OB.get_onboarding(HR, OTHER, no2), 404)
        await expect_http("editing an onboarding from another company",
                          OB.update_details(HR, OTHER, no2, {"joining_date": FUTURE}), 404)
        await expect_http("issuing an Employee ID cross-tenant",
                          OB.generate_employee_id(HR, OTHER, no2), 404)
        check("the other company sees nothing",
              await OB.list_onboardings(HR, OTHER) == [])

        # =================================================================
        section("Declared shape")
        # =================================================================
        names = [(c, o.get("name")) for c, _, o in M.HRMS_INDEXES]
        for want in ("uniq_onb_no", "uniq_access_code", "uniq_candidate",
                     "by_company_status", "uniq_employee_id"):
            check(f"hrms_onboarding index `{want}` declared",
                  any(c == M.COLL_ONBOARDING and n == want for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))
        uniq_user = next(o for c, k, o in M.HRMS_INDEXES
                         if c == M.COLL_EMPLOYEE_PROFILES and o.get("name") == "uniq_user")
        check("uniq_user is SPARSE so unlinked employees can coexist",
              uniq_user.get("sparse") is True and uniq_user.get("unique") is True)
        check("`employee` id format declared", "employee" in M.ID_FORMATS)
        check("checklist keys are unique",
              len(M.CHECKLIST_KEYS) == len(set(M.CHECKLIST_KEYS)))
        check("seed_checklist is pure -- two calls do not share state",
              M.seed_checklist() is not M.seed_checklist()
              and M.seed_checklist() == M.seed_checklist())

        # =================================================================
        section("Provisioning reconciles a changed index definition")
        # =================================================================
        # Mongo does not alter an existing index when its options change -- it raises
        # IndexOptionsConflict (85). Phase 9 made `uniq_user` sparse, so a database
        # provisioned by Phase 2 still carries the NON-sparse definition, under which the
        # second onboarding-created employee (no `user_id` key) would collide on null.
        import app.db.mongodb as mongodb

        class _FakeIndexColl:
            def __init__(self, conflicting, code=85):
                self.conflicting = set(conflicting)
                self.code = code
                self.created, self.dropped = [], []

            async def create_index(self, keys, **options):
                name = options.get("name")
                if name in self.conflicting:
                    self.conflicting.discard(name)   # a drop would clear the conflict
                    err = Exception(
                        "An existing index has the same name as the requested index.")
                    err.code = self.code
                    raise err
                self.created.append((name, options.get("sparse")))

            async def drop_index(self, name):
                self.dropped.append(name)

        class _FakeDb:
            def __init__(self, coll):
                self.coll = coll

            async def list_collection_names(self):
                return [c for c, _, _ in M.HRMS_INDEXES]

            def __getitem__(self, _name):
                return self.coll

        coll = _FakeIndexColl({"uniq_user"})
        await mongodb._ensure_hrms_collections(_FakeDb(coll))
        check("the conflicting index is DROPPED rather than left stale",
              coll.dropped == ["uniq_user"])
        check("and recreated with the sparse option the spec declares",
              ("uniq_user", True) in coll.created)
        check("every other declared index is created exactly once",
              len(coll.created) == len(M.HRMS_INDEXES))

        # A non-conflict failure must NOT trigger a drop -- dropping an index because of a
        # duplicate in the data would destroy the constraint that found the problem.
        class _AlwaysFails(_FakeIndexColl):
            async def create_index(self, keys, **options):
                err = Exception("E11000 duplicate key error")
                err.code = 11000
                raise err

        coll2 = _AlwaysFails([])
        await mongodb._ensure_hrms_collections(_FakeDb(coll2))
        check("a duplicate-key failure never drops the index", coll2.dropped == [])

        # Atlas raises 86 (IndexKeySpecsConflict), not 85, when only the options differ.
        # Matching just one code is how this fix silently failed the first time -- the live
        # smoke in Phase 10 caught it. Both codes must reconcile.
        for code in (85, 86):
            coll3 = _FakeIndexColl({"uniq_user"}, code=code)
            await mongodb._ensure_hrms_collections(_FakeDb(coll3))
            check(f"conflict code {code} is reconciled, not just warned about",
                  coll3.dropped == ["uniq_user"]
                  and ("uniq_user", True) in coll3.created)

        section("Lifecycle edges Phase 9 depends on")
        check("Pre-Onboarding -> Joined", M.can_transition(S.PRE_ONBOARDING, S.JOINED))
        check("Joined -> Employee Created",
              M.can_transition(S.JOINED, S.EMPLOYEE_CREATED))
        # Phase INT-15 gave a hire exactly one onward edge, for the internal track's
        # probation confirmation. What Phase 9 actually depends on is that onboarding is the
        # LAST thing that moves a candidate -- nothing here may reject or re-park a hire.
        check("Employee Created leads only to the probation confirmation",
              M.allowed_next_statuses(S.EMPLOYEE_CREATED) == {S.PROBATION_CONFIRMED})
        check("and onboarding can never undo a hire",
              not any(M.can_transition(S.EMPLOYEE_CREATED, t)
                      for t in (S.REJECTED, S.ON_HOLD, S.DUPLICATE, S.JOINED)))
    finally:
        mongo.get_collection = original
        S3.upload_file_to_s3_with_key = original_s3

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
