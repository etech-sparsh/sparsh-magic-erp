"""Phase 11-R Item 2 verification harness -- the document register.

Covers: type seeding + master CRUD, upload / versioning, the immutable-file rule, computed
expiry, verify-and-reject with mandatory remarks, the checklist, linked (never copied)
files, tenant scoping, MANAGER narrowing and the capability split.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_documents   (from backend/)
"""
from __future__ import annotations

import asyncio
import base64
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
OTHER = "C2"
PAST = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
FUTURE = (datetime.now(timezone.utc) + timedelta(days=200)).strftime("%Y-%m-%d")
SOON = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")


def upload(name="pan.pdf"):
    return {"name": name, "mime_type": "application/pdf",
            "data": base64.b64encode(b"a real file body").decode()}


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD = str(ObjectId()), str(ObjectId())

    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "candidate_name": "Asha Rao", "request_no": "HR-REQ-2026-001",
         "resume": {"name": "asha_cv.pdf", "key": "s3/asha_cv.pdf"},
         "photo": {"name": "asha.jpg", "key": "s3/asha.jpg"},
         "certificates": [{"name": "degree.pdf", "key": "s3/degree.pdf"}],
         "applied_at": datetime.now(timezone.utc)},
        {"_id": ObjectId(), "uk": "CAN-002", "company_id": COMPANY,
         "candidate_name": "Bala N", "request_no": "HR-REQ-2026-002"},
        {"_id": ObjectId(), "uk": "CAN-900", "company_id": OTHER, "candidate_name": "Other"},
    ])
    profiles = FakeCollection([
        {"_id": ObjectId(), "employee_code": "EMP-2026-001", "company_id": COMPANY,
         "employee_name": "Eve Emp"},
    ])
    onboarding = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "documents": [{"name": "aadhaar.pdf", "key": "s3/aadhaar.pdf"}],
         "created_at": datetime.now(timezone.utc)},
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_HOD},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "created_by": U_HR},
    ])
    docs_coll = FakeCollection()
    types_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_EMPLOYEE_PROFILES: profiles,
             M.COLL_ONBOARDING: onboarding, M.COLL_REQUISITIONS: reqs,
             M.COLL_DOCUMENTS: docs_coll, M.COLL_DOCUMENT_TYPES: types_coll,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_document_service as DS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (DS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    # S3 is stubbed: this harness tests the register's RULES, not boto3. The real
    # decode_upload still runs, so mime-type and size validation are genuinely exercised.
    async def _fake_store(up, prefix):
        from app.utils.hrms_public_guard import decode_upload
        raw, name, mime = decode_upload(up, label="Document")
        return {"file_name": name, "s3_key": f"s3/{name}", "mime_type": mime,
                "size_bytes": len(raw)}

    DS._store = _fake_store

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    INTERNAL = {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff"}

    try:
        # =================================================================
        section("Document types -- seeded on first read")
        # =================================================================
        types = await DS.list_document_types(COMPANY)
        check("a default set is seeded on first read", len(types) == len(M.DEFAULT_DOCUMENT_TYPES))
        check("seeded rows are flagged as such",
              all(t.get("seeded") for t in types))
        again = await DS.list_document_types(COMPANY)
        check("seeding fires exactly once", len(again) == len(types))

        pan = next(t for t in types if t["name"] == "PAN Card")
        check("PAN is mandatory by default", pan["mandatory"] is True)
        check("PAN applies to both kinds", pan["applies_to"] == "both")

        cand_only = await DS.list_document_types(COMPANY, applies_to="candidate")
        check("applies_to narrows the list",
              all(t["applies_to"] in ("candidate", "both") for t in cand_only))
        check("an employee-only type is excluded from the candidate list",
              "Bank Proof" not in {t["name"] for t in cand_only})

        made = await DS.create_document_type(
            HR, COMPANY, {"name": "Police Verification", "category": "Statutory",
                          "applies_to": "employee", "mandatory": False, "expires": True})
        check("a type can be created", made["name"] == "Police Verification")
        await expect_http("a duplicate name (case-insensitively)",
                          DS.create_document_type(HR, COMPANY, {"name": "police verification"}),
                          409, "already exists")
        await expect_http("an unknown applies_to",
                          DS.create_document_type(HR, COMPANY,
                                                  {"name": "X", "applies_to": "aliens"}),
                          422, "applies_to")
        await expect_http("a blank name",
                          DS.create_document_type(HR, COMPANY, {"name": "   "}), 422)

        # =================================================================
        section("Upload, versioning and the immutable file")
        # =================================================================
        doc = await DS.upload_document(HR, COMPANY, {
            "owner_type": "candidate", "owner_id": "CAN-001", "type_id": pan["id"],
            "file": upload(), "expiry_date": FUTURE})
        check("a document is created", doc["doc_no"].startswith("DOC-"))
        check("it starts Uploaded", doc["status"] == M.DocumentStatus.UPLOADED.value)
        check("version 1 is recorded", doc["current_version"] == 1)
        check("the S3 KEY is stored, never a URL",
              doc["versions"][0]["s3_key"] and "http" not in doc["versions"][0]["s3_key"])
        check("the owner name is denormalised", doc["owner_name"] == "Asha Rao")
        check("request_no rides along for the manager scope",
              doc["request_no"] == "HR-REQ-2026-001")
        check("the upload is audited",
              any(a["action"] == M.AUDIT_DOCUMENT_UPLOADED for a in audit_log.docs))

        v2 = await DS.upload_document(HR, COMPANY, {
            "owner_type": "candidate", "owner_id": "CAN-001", "type_id": pan["id"],
            "doc_no": doc["doc_no"], "file": upload("pan_clear.pdf")})
        check("supplying doc_no adds a VERSION rather than a second document",
              v2["current_version"] == 2 and len(v2["versions"]) == 2)
        check("only one register row exists for this type",
              len([d for d in docs_coll.docs if d["owner_id"] == "CAN-001"
                   and d["type_id"] == pan["id"]]) == 1)

        await DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Verified"})
        v3 = await DS.upload_document(HR, COMPANY, {
            "owner_type": "candidate", "owner_id": "CAN-001", "type_id": pan["id"],
            "doc_no": doc["doc_no"], "file": upload("pan_v3.pdf")})
        check("a NEW version clears the old verification",
              v3["status"] == M.DocumentStatus.UPLOADED.value and v3["verified_at"] is None)

        # Metadata is editable; the file is not.
        edited = await DS.update_document(HR, COMPANY, doc["doc_no"],
                                          {"remarks": "checked against the original"})
        check("metadata can be edited", edited["remarks"] == "checked against the original")
        check("editing metadata does not add a version", edited["current_version"] == 3)

        await expect_http("an expiry before the issue date",
                          DS.update_document(HR, COMPANY, doc["doc_no"],
                                             {"issue_date": FUTURE, "expiry_date": PAST}),
                          422, "before the issue date")

        # =================================================================
        section("Computed expiry -- nothing stored")
        # =================================================================
        expiring = await DS.upload_document(HR, COMPANY, {
            "owner_type": "candidate", "owner_id": "CAN-001",
            "type_id": next(t for t in types if t["name"] == "Passport")["id"],
            "file": upload("passport.pdf"), "expiry_date": PAST})
        check("a past-expiry document reads Expired",
              expiring["status"] == M.DocumentStatus.EXPIRED.value)
        raw = await docs_coll.find_one({"doc_no": expiring["doc_no"]})
        check("the stored status is untouched",
              raw["status"] == M.DocumentStatus.UPLOADED.value)
        check("Rejected outranks expiry (it is the more actionable answer)",
              DS.effective_status(
                  {"status": "Rejected", "expiry_date": PAST},
                  datetime.now(timezone.utc).strftime("%Y-%m-%d")) == "Rejected")

        # =================================================================
        section("Verify and reject")
        # =================================================================
        verified = await DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Verified"})
        check("verifying records who and when",
              verified["verified_by"] and verified["verified_at"])
        await expect_http("rejecting with no reason",
                          DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Rejected"}),
                          422, "reason is required")
        rejected = await DS.set_status(HR, COMPANY, doc["doc_no"],
                                       {"status": "Rejected", "remarks": "illegible scan"})
        check("rejecting with a reason works",
              rejected["status"] == M.DocumentStatus.REJECTED.value)
        check("rejecting clears the earlier verification",
              rejected["verified_by"] is None and rejected["verified_at"] is None)
        await expect_http("setting Expired by hand",
                          DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Expired"}),
                          422, "derived")
        await expect_http("an unknown status",
                          DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Nonsense"}),
                          422)

        # =================================================================
        section("Deletion")
        # =================================================================
        await DS.set_status(HR, COMPANY, doc["doc_no"], {"status": "Verified"})
        await expect_http("deleting a VERIFIED document",
                          DS.delete_document(HR, COMPANY, doc["doc_no"]),
                          409, "compliance record")
        await DS.set_status(HR, COMPANY, doc["doc_no"],
                            {"status": "Rejected", "remarks": "superseded"})
        gone = await DS.delete_document(HR, COMPANY, doc["doc_no"])
        check("a non-verified document can be deleted", gone["deleted"] is True)

        # =================================================================
        section("Checklist -- absence is stated, not omitted")
        # =================================================================
        cl = await DS.checklist(HR, COMPANY, "candidate", "CAN-002")
        check("every applicable type appears", len(cl["items"]) > 0)
        check("a type with nothing against it reads Pending",
              all(i["status"] == M.DocumentStatus.PENDING.value for i in cl["items"]))
        check("outstanding mandatory documents are counted",
              cl["mandatory_outstanding"] == cl["mandatory_total"] > 0)
        check("employee-only types are excluded for a candidate",
              "Bank Proof" not in {i["type_name"] for i in cl["items"]})

        # =================================================================
        section("Linked files are SURFACED, never copied")
        # =================================================================
        linked = await DS.list_linked(COMPANY, "candidate", "CAN-001")
        names = {r["file_name"] for r in linked}
        check("the application resume is surfaced", "asha_cv.pdf" in names)
        check("the photo is surfaced", "asha.jpg" in names)
        check("certificates are surfaced", "degree.pdf" in names)
        check("onboarding KYC scans are surfaced", "aadhaar.pdf" in names)
        check("every linked row is read-only", all(r["read_only"] for r in linked))
        check("every linked row is labelled as linked",
              all(r["source"] == "linked" for r in linked))
        check("linked files are NOT copied into the register",
              not any(d.get("file_name") == "asha_cv.pdf" for d in docs_coll.docs))

        # =================================================================
        section("Tenant scoping and the MANAGER narrowing")
        # =================================================================
        await expect_http("a candidate from another tenant",
                          DS.upload_document(HR, COMPANY, {
                              "owner_type": "candidate", "owner_id": "CAN-900",
                              "type_id": pan["id"], "file": upload()}),
                          422, "does not exist")
        await expect_http("an unknown owner kind",
                          DS.upload_document(HR, COMPANY, {
                              "owner_type": "ghost", "owner_id": "X",
                              "type_id": pan["id"], "file": upload()}),
                          422, "candidate or employee")

        await DS.upload_document(HR, COMPANY, {
            "owner_type": "candidate", "owner_id": "CAN-002", "type_id": pan["id"],
            "file": upload()})
        mgr = await DS.list_documents(HOD, COMPANY, owner_type="candidate")
        check("a manager is told their view is narrowed",
              mgr["scoped_to_own_requisitions"] is True)
        check("a manager sees only their own requisitions' candidates",
              all(r["request_no"] == "HR-REQ-2026-001" for r in mgr["documents"]))

        # =================================================================
        section("Filters")
        # =================================================================
        every = await DS.list_documents(HR, COMPANY, owner_type="candidate")
        check("the register lists this company's documents", every["total"] >= 2)
        expired_only = await DS.list_documents(HR, COMPANY, owner_type="candidate",
                                               status="Expired")
        check("the status filter runs on the COMPUTED status",
              all(r["status"] == "Expired" for r in expired_only["documents"]))

        await DS.upload_document(HR, COMPANY, {
            "owner_type": "employee", "owner_id": "EMP-2026-001",
            "type_id": next(t for t in types if t["name"] == "Bank Proof")["id"],
            "file": upload("bank.pdf"), "expiry_date": SOON})
        soon = await DS.list_documents(HR, COMPANY, owner_type="employee",
                                       expiring_soon=True)
        check("expiring-soon finds a document inside the horizon", soon["total"] == 1)

        # =================================================================
        section("Type deletion is refused while in use")
        # =================================================================
        await expect_http("deleting a type that documents reference",
                          DS.delete_document_type(HR, COMPANY, pan["id"]),
                          409, "inactive instead")
        unused = await DS.create_document_type(HR, COMPANY, {"name": "Never Used"})
        removed = await DS.delete_document_type(HR, COMPANY, unused["id"])
        check("an unused type can be deleted", removed["deleted"] is True)

        renamed = await DS.update_document_type(HR, COMPANY, pan["id"],
                                                {"name": "PAN Card (India)"})
        check("a rename is applied to the master", renamed["name"] == "PAN Card (India)")
        check("a rename follows through to the documents that denormalised it",
              all(d["type_name"] == "PAN Card (India)" for d in docs_coll.docs
                  if d["type_id"] == pan["id"]))

        # =================================================================
        section("System-filed documents (the Item 3 bridge)")
        # =================================================================
        await DS.file_system_document(
            HR, COMPANY, owner_type="candidate", owner_id="CAN-001",
            owner_name="Asha Rao", type_name="Appointment Letter",
            reference="APT-2026-001", request_no="HR-REQ-2026-001", verified=False)
        filed = [d for d in docs_coll.docs if d.get("reference") == "APT-2026-001"]
        check("the appointment letter is filed automatically", len(filed) == 1)
        check("it carries no S3 object (it is rendered from its own record)",
              filed[0]["versions"][0]["s3_key"] is None)
        check("its source is marked system", filed[0]["versions"][0]["source"] == "system")

        await DS.file_system_document(
            HR, COMPANY, owner_type="candidate", owner_id="CAN-001",
            owner_name="Asha Rao", type_name="Appointment Letter",
            reference="APT-2026-001", verified=True)
        filed = [d for d in docs_coll.docs if d.get("reference") == "APT-2026-001"]
        check("filing again UPDATES rather than duplicating", len(filed) == 1)
        check("acknowledgement flips it to Verified",
              filed[0]["status"] == M.DocumentStatus.VERIFIED.value)

        # =================================================================
        section("Capabilities")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR holds read, write and verify",
              can(HR, M.Cap.DOCUMENT_READ) and can(HR, M.Cap.DOCUMENT_WRITE)
              and can(HR, M.Cap.DOCUMENT_VERIFY))
        check("Sparsh support collects but does NOT attest",
              can(INTERNAL, M.Cap.DOCUMENT_WRITE)
              and not can(INTERNAL, M.Cap.DOCUMENT_VERIFY))
        check("a manager reads only",
              can(HOD, M.Cap.DOCUMENT_READ) and not can(HOD, M.Cap.DOCUMENT_WRITE))
        check("verify is a SEPARATE capability from write",
              M.Cap.DOCUMENT_VERIFY.value != M.Cap.DOCUMENT_WRITE.value)

        # =================================================================
        section("Declarations")
        # =================================================================
        check("rejection is the status that demands remarks",
              M.DOCUMENT_STATUSES_REQUIRING_REMARKS == {M.DocumentStatus.REJECTED})
        check("versions are capped", M.MAX_DOCUMENT_VERSIONS == 10)
        names_idx = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES
                     if c in (M.COLL_DOCUMENTS, M.COLL_DOCUMENT_TYPES)]
        check("doc_no is unique", ("hrms_documents", "uniq_doc_no") in names_idx)
        check("index names are unique per collection",
              len(names_idx) == len(set(names_idx)))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
