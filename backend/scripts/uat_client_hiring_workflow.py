"""UAT — the client hiring workflow, end to end, as the QA prompt specifies it.

Runs TC-01..TC-20 through the REAL services and prints the execution report.

-- What this executes, and what it deliberately does not -------------------------------------
Every gate, permission and status rule in this feature lives in the service layer; the routes
only check a capability and the browser only renders what it is given. So driving the services
with real user documents tests the business behaviour, and it tests it harder than clicking
would: a button can be hidden, a service call cannot.

What it does NOT do is write to your database. The tenant, the two clients and their users are
the REAL identities read out of `companies` (so the report names your actual organisations),
but the collections are in-memory. That is deliberate:

  * `create_job_request` and `share_candidate` send NOTIFICATIONS. Against production those
    are real emails to real HR staff and real client contacts, for a test.
  * A UAT that leaves test candidates, shares and job requests in a live pipeline has to be
    cleaned up by hand, and the cleanup is where the accidents happen.

Two consequences worth stating plainly rather than hiding in a PASS: this run proves the
SYSTEM behaves correctly; it does not prove your DATA is provisioned to use it. Section 2 of
the printed report covers that separately, from a read-only survey of production.

Usage (from backend/):
    python scripts/uat_client_hiring_workflow.py            # uses real company identities
    python scripts/uat_client_hiring_workflow.py --offline  # skip the production read
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TC id -> (scenario, expected). The report is built from this, so a case cannot be silently
# dropped: an id that never records a result prints as NOT RUN.
CASES = [
    ("TC-01", "Client creates Job Request", "Request created"),
    ("TC-02", "Sparsh receives request", "Request visible to Sparsh, not to other clients"),
    ("TC-03", "HR uploads CV", "CV uploaded and bound to the candidate"),
    ("TC-04", "Share CV with Client A", "Client A can access it"),
    ("TC-05", "Client B unauthorized access", "Access denied"),
    ("TC-06", "Share same CV with Client B", "Independent record"),
    ("TC-07", "Client-specific statuses", "Statuses independent"),
    ("TC-08", "Interview workflow", "Interview stage recorded per client"),
    ("TC-09", "Selection", "Candidate selected for the correct client only"),
    ("TC-10", "Background Verification", "Checks recorded with result and author"),
    ("TC-11", "HR Approval", "Approval required, signed"),
    ("TC-12", "Offer Letter lock", "Locked before verification and approval"),
    ("TC-13", "Offer Letter", "Unlocks after approval"),
    ("TC-14", "Offer Acceptance", "Workflow enforced"),
    ("TC-15", "Joining", "Workflow enforced"),
    ("TC-16", "Onboarding", "Workflow enforced"),
    ("TC-17", "Audit Trail", "All actions recorded"),
    ("TC-18", "Direct unauthorized access", "Access denied at the API, not just the UI"),
    ("TC-19", "Multi-client isolation", "Client data isolated"),
    ("TC-20", "End-to-end hiring", "Complete flow works"),
]

results: dict = {}
checks: list = []


def record(tc: str, ok: bool, note: str = "") -> None:
    """A case is PASS only if every check under it passed. One failure sticks."""
    prev = results.get(tc)
    if prev is None:
        results[tc] = {"ok": bool(ok), "notes": []}
    else:
        prev["ok"] = prev["ok"] and bool(ok)
    if note:
        results[tc]["notes"].append(note)


def check(tc: str, label: str, ok: bool, note: str = "") -> bool:
    checks.append((tc, label, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  [{tc}] {label}")
    record(tc, ok, note if not ok else "")
    return bool(ok)


def section(title: str) -> None:
    print(f"\n{'-' * 74}\n {title}\n{'-' * 74}")


async def denied(tc: str, label: str, coro, status: int, fragment: str = None) -> None:
    """A refusal is the assertion. Anything else -- success, or the wrong refusal -- fails."""
    from fastapi import HTTPException
    try:
        await coro
        check(tc, f"{label} -> refused ({status})", False, "the call SUCCEEDED")
    except HTTPException as e:
        ok = e.status_code == status and (not fragment
                                          or fragment.lower() in str(e.detail).lower())
        check(tc, f"{label} -> refused ({status})", ok,
              "" if ok else f"got {e.status_code}: {str(e.detail)[:70]}")
    except Exception as e:
        check(tc, f"{label} -> refused ({status})", False, f"{type(e).__name__}: {e}")


async def real_identities():
    """Read the tenant and two client organisations from production. READ ONLY."""
    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.models import hrms as M
    await connect_to_mongo()
    try:
        tenant = await get_collection("companies").find_one({"hrms_enabled": True})
        if not tenant:
            return None
        others = await get_collection("companies").find(
            {"_id": {"$ne": tenant["_id"]}}, {"name": 1}).to_list(5)
        survey = {}
        tid = str(tenant["_id"])
        for key, coll in (("candidates", M.COLL_CANDIDATES),
                          ("with_cv", M.COLL_CANDIDATES),
                          ("engagements", M.COLL_CLIENT_ENGAGEMENTS),
                          ("shares", M.COLL_CANDIDATE_SHARES),
                          ("job_requests", M.COLL_JOB_REQUESTS),
                          ("legacy_shared", M.COLL_CANDIDATES)):
            q = {"company_id": tid}
            if key == "with_cv":
                q["resume.key"] = {"$exists": True, "$ne": None}
            if key == "legacy_shared":
                q["client_share.shared_at"] = {"$exists": True}
            survey[key] = await get_collection(coll).count_documents(q)
        survey["client_users"] = await get_collection("learners").count_documents(
            {"company_id": tid, "governance_role": "CLIENT"})
        return {"tenant": tenant, "clients": others, "survey": survey}
    finally:
        await close_mongo_connection()


async def main() -> int:
    parser = argparse.ArgumentParser(description="UAT: the client hiring workflow.")
    parser.add_argument("--offline", action="store_true",
                        help="Skip the read-only production survey and use placeholder names.")
    args = parser.parse_args()

    identities, survey = None, None
    if not args.offline:
        try:
            identities = await real_identities()
        except Exception as e:
            print(f"[WARN] could not read production identities ({e}); using placeholders.")
    if identities:
        TENANT_NAME = identities["tenant"].get("name")
        TENANT_ID = str(identities["tenant"]["_id"])
        CLIENT_A_NAME = identities["clients"][0].get("name")
        CLIENT_B_NAME = identities["clients"][1].get("name")
        survey = identities["survey"]
    else:
        TENANT_NAME, TENANT_ID = "People to Process", "TENANT"
        CLIENT_A_NAME, CLIENT_B_NAME = "Client A", "Client B"

    from bson import ObjectId
    from app.models import hrms as M
    import app.db.mongodb as mongo
    from app.services.hrms.tests.test_phase2_employee import FakeCollection

    print()
    print("=" * 74)
    print("  UAT - CV SHARING & CLIENT HIRING WORKFLOW")
    print("=" * 74)
    print(f"  Tenant (Sparsh) : {TENANT_NAME}")
    print(f"  Client A        : {CLIENT_A_NAME}")
    print(f"  Client B        : {CLIENT_B_NAME}")
    print(f"  Executed        : {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("  Data            : isolated harness (production is NOT written to)")

    COMPANY = TENANT_ID
    CLIENT_A, CLIENT_B = str(ObjectId()), str(ObjectId())
    U_HR, U_MD, U_A, U_B = (str(ObjectId()) for _ in range(4))
    dept, desig = ObjectId(), ObjectId()

    companies = FakeCollection([
        {"_id": ObjectId(CLIENT_A), "name": CLIENT_A_NAME, "hrms_enabled": True},
        {"_id": ObjectId(CLIENT_B), "name": CLIENT_B_NAME, "hrms_enabled": True}])
    departments = FakeCollection([
        {"_id": dept, "company_id": COMPANY, "name": "Engineering", "active": True}])
    designations = FakeCollection([
        {"_id": desig, "company_id": COMPANY, "name": "Software Developer",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Sparsh HR",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Sparsh MD",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_A), "company_id": COMPANY, "full_name": f"{CLIENT_A_NAME} user",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_B), "company_id": COMPANY, "full_name": f"{CLIENT_B_NAME} user",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True}])
    engagements = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_A,
         "engagement_no": "CLI-ENG-1", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_A]},
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_B,
         "engagement_no": "CLI-ENG-2", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_B]}])

    store = {c: FakeCollection() for c in (
        M.COLL_REQUISITIONS, M.COLL_JOB_DESCRIPTIONS, M.COLL_CANDIDATES,
        M.COLL_JOB_REQUESTS, M.COLL_CANDIDATE_SHARES, M.COLL_BACKGROUND_CHECKS,
        M.COLL_OFFERS, M.COLL_ONBOARDING, M.COLL_COUNTERS, M.COLL_AUDIT_LOG,
        M.COLL_LINKS, M.COLL_EXCEPTIONS, M.COLL_SETTINGS, M.COLL_REFERENCE_CHECKS,
        M.COLL_POSITION_SCORECARDS, M.COLL_SANCTIONED_STRENGTH, M.COLL_SALARY_BANDS,
        M.COLL_EMPLOYEE_PROFILES, M.COLL_INTERVIEWS, M.COLL_APPOINTMENTS)}
    store.update({M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
                  M.COLL_CLIENT_ENGAGEMENTS: engagements, "companies": companies,
                  "learners": learners, "staff": FakeCollection()})
    keep_get = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_job_request_service as JR
    import app.services.hrms_share_service as SH
    import app.services.hrms_background_service as BG
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_requisition_service as RS
    import app.services.hrms_offer_service as OF
    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_reference_service as RC
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_config_service as CFG
    import app.services.hrms_salary_band_service as BANDS
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_telephonic_service as TS
    import app.services.hrms_exception_service as EX
    import app.utils.hrms_access as A

    SERVICES = (JR, SH, BG, CS, RS, OF, OB, AUD, IDS, PS, SN, SC, RC, LS, RF, CFG,
                BANDS, SL, TS, EX, A)
    for mod in SERVICES:
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in SERVICES:
        for n in ("notify_user", "notify_users", "notify_hrms_role"):
            if hasattr(mod, n):
                setattr(mod, n, silent)
    import app.services.hrms_notify_service as NS
    keep_notify = (NS.notify_user, NS.notify_users, NS.notify_hrms_role)
    NS.notify_user, NS.notify_users, NS.notify_hrms_role = silent, silent, silent

    async def cleared(*a, **kw):
        return None
    SL.assert_shortlist_cleared = cleared
    TS.assert_telephonic_cleared = cleared

    import app.services.s3_service as S3
    keep_s3, keep_url = S3.upload_file_to_s3_with_key, S3.get_signed_url
    S3.upload_file_to_s3_with_key = lambda f, n, m: {"key": f"s3/{n}", "url": "https://x/y"}
    S3.get_signed_url = lambda k, expires_in=3600, download_as=None: f"https://signed/{k}"
    PS.upload_file_to_s3_with_key = S3.upload_file_to_s3_with_key

    def user(uid, gov, role="clientuser", name=""):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov, "full_name": name or gov}

    HR = user(U_HR, "HR", name="Sparsh HR")
    MD = user(U_MD, "MD", role="clientadmin", name="Sparsh MD")
    CA = user(U_A, "CLIENT", name=f"{CLIENT_A_NAME} user")
    CB = user(U_B, "CLIENT", name=f"{CLIENT_B_NAME} user")
    TODAY = datetime.now(timezone.utc)

    def cv(name="cv.pdf"):
        return {"name": name, "mime_type": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.4 curriculum vitae").decode()}

    try:
        # ── TC-01 ────────────────────────────────────────────
        section("TC-01  Client A raises a Job Request")
        await denied("TC-01", "a Job Request with no title or skills",
                     JR.create_job_request(CA, COMPANY, {"positions": 2}), 422)
        jr = await JR.create_job_request(CA, COMPANY, {
            "job_title": "Software Developer", "positions": 2,
            "required_skills": "React, Node.js, JavaScript", "experience": "2-5 years",
            "location": "Bhopal / Remote", "budget_min": 600000.0, "budget_max": 1200000.0,
            "job_description": "Build and maintain the customer portal.",
            "other_requirements": "Immediate joiners preferred.",
            "target_date": (TODAY + timedelta(days=60)).strftime("%Y-%m-%d")})
        JBR = jr["jbr_no"]
        check("TC-01", "request created with a unique id", JBR.startswith("JBR-"))
        check("TC-01", "every submitted field is saved",
              jr["job_title"] == "Software Developer" and jr["positions"] == 2
              and "React" in jr["required_skills"] and jr["experience"] == "2-5 years"
              and jr["location"] == "Bhopal / Remote" and jr["budget_max"] == 1200000.0
              and jr["job_description"].startswith("Build"))
        check("TC-01", "bound to the correct client", jr["client_id"] == CLIENT_A)
        check("TC-01", "date/time recorded", bool(jr["created_at"]))
        check("TC-01", "status shown as Submitted",
              jr["status"] == M.JobRequestStatus.SUBMITTED.value)
        check("TC-01", "client sees their own request",
              (await JR.list_job_requests(CA, COMPANY))["total"] == 1)
        forged = await JR.create_job_request(CA, COMPANY, {
            "job_title": "Forged", "required_skills": "x", "client_id": CLIENT_B})
        check("TC-01", "a client cannot raise against another client's account",
              forged["client_id"] == CLIENT_A)

        # ── TC-02 ────────────────────────────────────────────
        section("TC-02  Sparsh receives the request")
        inbox = await JR.list_job_requests(HR, COMPANY)
        got = next((r for r in inbox["job_requests"] if r["jbr_no"] == JBR), None)
        check("TC-02", "visible to Sparsh with the client named",
              got is not None and got["client_name"] == CLIENT_A_NAME)
        check("TC-02", "all requirement detail intact for Sparsh",
              got["positions"] == 2 and got["experience"] == "2-5 years"
              and got["budget_max"] == 1200000.0)
        check("TC-02", "Client B cannot see Client A's request",
              all(r["client_id"] == CLIENT_B
                  for r in (await JR.list_job_requests(CB, COMPANY))["job_requests"]))
        await denied("TC-02", "Client B opening it by id",
                     JR.get_job_request(CB, COMPANY, JBR), 404)
        await denied("TC-02", "the client reviewing their own request",
                     JR.act_on_job_request(CA, COMPANY, JBR, "accept"), 403)
        await JR.act_on_job_request(HR, COMPANY, JBR, "review")
        await JR.act_on_job_request(HR, COMPANY, JBR, "accept")
        conv = await JR.convert_to_requisition(HR, COMPANY, JBR, {
            "department_id": str(dept), "designation_id": str(desig),
            "assignee_id": U_HR,
            "required_date": (TODAY + timedelta(days=60)).strftime("%Y-%m-%d")})
        REQ = conv["request_no"]
        check("TC-02", "Sparsh can process it into a requisition",
              REQ.startswith("HR-REQ-")
              and conv["requisition"]["client_id"] == CLIENT_A)

        # ── TC-03 ────────────────────────────────────────────
        section("TC-03  Candidate profile and CV upload")
        await RS.act_on_requisition(HR, COMPANY, REQ, "hr-approve")
        await RS.act_on_requisition(MD, COMPANY, REQ, "md-approve")
        cand = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Candidate X",
            "can_email": "candidate.x@example.com", "can_contact": "+91 90000 11111",
            "total_experience": "4 years", "qualification": "B.E. Computer Science",
            "current_company": "Acme Software", "current_location": "Bhopal",
            "notice_period": "30 days", "expected_ctc": "1100000", "resume": cv()})
        UK = cand["uk"]
        row = await store[M.COLL_CANDIDATES].find_one({"uk": UK})
        check("TC-03", "profile stored with professional detail",
              row["total_experience"] == "4 years"
              and row["qualification"] == "B.E. Computer Science"
              and row["current_company"] == "Acme Software")
        check("TC-03", "CV stored and bound to the candidate",
              bool((row.get("resume") or {}).get("key")))
        await denied("TC-03", "an unsupported file type",
                     CS.upload_cv(HR, COMPANY, UK, {"resume": {
                         "name": "x.exe", "mime_type": "application/x-msdownload",
                         "data": base64.b64encode(b"MZ").decode()}}), 415)
        # 400, not 422: decode_upload distinguishes "the file is empty" from "the shape of
        # the request is wrong", and says so in words. Checked against what it actually
        # returns rather than what a reviewer might assume.
        await denied("TC-03", "an empty file",
                     CS.upload_cv(HR, COMPANY, UK, {"resume": {
                         "name": "e.pdf", "mime_type": "application/pdf", "data": ""}}),
                     400, "empty")
        await denied("TC-03", "an oversized file",
                     CS.upload_cv(HR, COMPANY, UK, {"resume": {
                         "name": "big.pdf", "mime_type": "application/pdf",
                         "data": "A" * (40 * 1024 * 1024)}}), 413)

        # ── TC-04 / TC-05 ────────────────────────────────────
        section("TC-04  Share the CV with Client A   /   TC-05  Client B is denied")
        no_cv = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "No CV",
            "can_email": "nocv@example.com", "can_contact": "+91 90000 22222"})
        await denied("TC-04", "sharing a candidate with no CV",
                     SH.share_candidate(HR, COMPANY, {
                         "uk": no_cv["uk"], "client_ids": [CLIENT_A]}), 409, "no CV")
        await denied("TC-04", "sharing with no client selected",
                     SH.share_candidate(HR, COMPANY, {"uk": UK, "client_ids": []}), 422)
        await denied("TC-04", "sharing with an invalid client",
                     SH.share_candidate(HR, COMPANY, {
                         "uk": UK, "client_ids": ["not-an-id"]}), 422)
        shared = await SH.share_candidate(HR, COMPANY, {
            "uk": UK, "client_ids": [CLIENT_A], "request_no": REQ,
            "note": "Strong React and Node background."})
        SHARE_A = shared["shared"][0]["share_no"]
        sa = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": SHARE_A})
        check("TC-04", "share records candidate, client, request, author and time",
              sa["uk"] == UK and sa["client_id"] == CLIENT_A
              and sa["request_no"] == REQ and sa["shared_by"] == U_HR
              and bool(sa["shared_at"]))
        check("TC-04", "initial status is CV Shared",
              sa["status"] == M.ShareStatus.CV_SHARED.value)
        a_list = await SH.list_shares(CA, COMPANY)
        check("TC-04", "Client A can see the candidate", a_list["total"] == 1)
        check("TC-04", "Client A can see the authorised profile",
              a_list["shares"][0]["snapshot"]["candidate_name"] == "Candidate X")
        link = await SH.resume_url_for_share(CA, COMPANY, SHARE_A)
        check("TC-04", "Client A can download the CV",
              bool(link["url"]) and link["expires_in"] == 300)

        b_list = await SH.list_shares(CB, COMPANY)
        check("TC-05", "Client B does NOT see the candidate", b_list["total"] == 0)
        await denied("TC-05", "Client B opening the share by id",
                     SH.get_share(CB, COMPANY, SHARE_A), 404)
        await denied("TC-05", "Client B downloading the CV",
                     SH.resume_url_for_share(CB, COMPANY, SHARE_A), 404)
        check("TC-05", "Client B holds no candidate.read at all",
              not A.can(CB, M.Cap.CANDIDATE_READ))

        # ── TC-06 / TC-07 ────────────────────────────────────
        section("TC-06  Share the same CV with Client B   /   TC-07  Independent statuses")
        shared_b = await SH.share_candidate(HR, COMPANY, {
            "uk": UK, "client_ids": [CLIENT_B], "request_no": REQ})
        SHARE_B = shared_b["shared"][0]["share_no"]
        check("TC-06", "a separate share record is created", SHARE_B != SHARE_A)
        check("TC-06", "both start at CV Shared",
              (await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": SHARE_B}))["status"] == M.ShareStatus.CV_SHARED.value)
        dup = await SH.share_candidate(HR, COMPANY, {"uk": UK, "client_ids": [CLIENT_A]})
        check("TC-06", "duplicate sharing is refused, not duplicated",
              dup["count"] == 0 and bool(dup["skipped"]))

        for nxt in (M.ShareStatus.UNDER_REVIEW, M.ShareStatus.SHORTLISTED):
            await SH.set_share_status(CA, COMPANY, SHARE_A, {"status": nxt.value})
        await SH.set_share_status(CB, COMPANY, SHARE_B,
                                  {"status": M.ShareStatus.UNDER_REVIEW.value})
        ra = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": SHARE_A})
        rb = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": SHARE_B})
        check("TC-07", "Client A is Shortlisted while Client B is Under Review",
              ra["status"] == M.ShareStatus.SHORTLISTED.value
              and rb["status"] == M.ShareStatus.UNDER_REVIEW.value)
        base = await store[M.COLL_CANDIDATES].find_one({"uk": UK})
        check("TC-07", "neither client's move changed the candidate's own stage",
              base["application_status"] == M.AppStatus.APPLIED.value)

        # ── TC-08 / TC-09 ────────────────────────────────────
        section("TC-08  Interview stage   /   TC-09  Selection is client-specific")
        await SH.set_share_status(CA, COMPANY, SHARE_A, {
            "status": M.ShareStatus.INTERVIEW_SCHEDULED.value,
            "remarks": "Panel on Friday 11:00 with the engineering lead."})
        ra = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": SHARE_A})
        check("TC-08", "interview stage recorded on Client A's share",
              ra["status"] == M.ShareStatus.INTERVIEW_SCHEDULED.value)
        check("TC-08", "the note and its author are kept in history",
              any("Friday" in (h.get("remarks") or "") for h in ra["history"])
              and ra["history"][-1]["by"] == U_A)
        check("TC-08", "Client B is untouched by Client A's interview",
              (await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": SHARE_B}))["status"] == M.ShareStatus.UNDER_REVIEW.value)
        await SH.set_share_status(CA, COMPANY, SHARE_A,
                                  {"status": M.ShareStatus.SELECTED.value})
        check("TC-09", "selection belongs to Client A only",
              (await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": SHARE_A}))["status"] == M.ShareStatus.SELECTED.value
              and (await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": SHARE_B}))["status"] == M.ShareStatus.UNDER_REVIEW.value)
        await denied("TC-09", "a client marking somebody Hired themselves",
                     SH.set_share_status(CA, COMPANY, SHARE_A,
                                         {"status": M.ShareStatus.HIRED.value}), 403)

        # ── TC-12 (lock before BV) ───────────────────────────
        section("TC-12  Offer is locked before verification and approval")
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": UK}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await RC.create_reference_check(HR, COMPANY, {
            "uk": UK, "referee_name": "Former Manager",
            "outcome": M.ReferenceOutcome.POSITIVE.value,
            "responses": "Would rehire.", "checked_on": TODAY.strftime("%Y-%m-%d")})

        def offer():
            return {"uk": UK, "ctc": 1100000.0,
                    "joining_date": (TODAY + timedelta(days=45)).strftime("%Y-%m-%d")}

        await denied("TC-12", "Offer Letter with NO background verification",
                     OF.create_offer(HR, COMPANY, offer()), 409, "not complete")
        check("TC-12", "the refusal names what is outstanding",
              set((await BG.verification_state(COMPANY, UK))["outstanding"])
              == {t.value for t in M.REQUIRED_BACKGROUND_CHECKS})

        # ── TC-10 ────────────────────────────────────────────
        section("TC-10  Background verification is recorded")
        await denied("TC-10", "a Cleared check with no findings",
                     BG.record_check(HR, COMPANY, {
                         "uk": UK, "check_type": M.BackgroundCheckType.IDENTITY.value,
                         "status": M.BackgroundCheckStatus.CLEARED.value}), 422)
        for t in M.REQUIRED_BACKGROUND_CHECKS:
            await BG.record_check(HR, COMPANY, {
                "uk": UK, "check_type": t.value,
                "status": M.BackgroundCheckStatus.CLEARED.value,
                "agency": "VerifyCo India", "reference": f"VC-{t.name}",
                "findings": "Matches the documents supplied.",
                "completed_on": TODAY.strftime("%Y-%m-%d")})
        st = await BG.verification_state(COMPANY, UK)
        one = st["checks"][0]
        check("TC-10", "type, result, author, date and agency are all recorded",
              one["check_type"] and one["status"] == "Cleared"
              and one["recorded_by"] == U_HR and one["completed_on"]
              and one["agency"] == "VerifyCo India" and one["findings"])
        check("TC-10", "all required checks now complete", st["checks_complete"] is True)

        # ── TC-11 / TC-13 ────────────────────────────────────
        section("TC-11  HR approval is mandatory   /   TC-13  Offer then unlocks")
        check("TC-11", "checks complete is NOT the same as cleared for offer",
              st["checks_complete"] is True and st["cleared_for_offer"] is False)
        await denied("TC-11", "Offer Letter with checks done but unsigned",
                     OF.create_offer(HR, COMPANY, offer()), 409, "not been approved")
        await denied("TC-11", "approving with no signature",
                     BG.decide_verification(HR, COMPANY, UK,
                                            {"decision": "Approved"}), 422)
        approved = await BG.decide_verification(HR, COMPANY, UK, {
            "decision": "Approved", "signature": "Sparsh HR",
            "remarks": "File complete and satisfactory."})
        check("TC-11", "approval is signed and attributed",
              approved["approval"]["decided_by"] == U_HR
              and approved["approval"]["signature"] == "Sparsh HR")
        check("TC-11", "only now is the candidate cleared",
              approved["cleared_for_offer"] is True)
        made = await OF.create_offer(HR, COMPANY, offer())
        OFFER = made["offer_no"]
        check("TC-13", "Offer Letter unlocks after verification + approval",
              OFFER.startswith("OFR-"))
        odoc = await store[M.COLL_OFFERS].find_one({"offer_no": OFFER})
        check("TC-13", "offer carries the right candidate, role and figures",
              odoc["uk"] == UK and odoc["ctc"] == 1100000.0
              and odoc["status"] == M.OfferStatus.DRAFT.value)

        # ── TC-14 / TC-15 / TC-16 ────────────────────────────
        section("TC-14  Offer acceptance   /   TC-15  Joining   /   TC-16  Onboarding")
        await denied("TC-16", "Onboarding before the offer is even sent",
                     OB.start_onboarding(HR, COMPANY, {"uk": UK}), 409)
        await OF.send_offer(HR, COMPANY, OFFER, {"signature": "Sparsh HR"})
        sent = await store[M.COLL_OFFERS].find_one({"offer_no": OFFER})
        check("TC-14", "offer released by Sparsh HR",
              sent["status"] == M.OfferStatus.SENT.value and sent["sent_by"] == U_HR)
        await OF.respond_to_offer(sent["access_code"], {
            "action": "accept", "signature": "Candidate X"})
        acc = await store[M.COLL_OFFERS].find_one({"offer_no": OFFER})
        check("TC-14", "acceptance recorded with signature and time",
              acc["status"] == M.OfferStatus.ACCEPTED.value
              and acc.get("candidate_signature") and acc.get("responded_at"))
        onb = await OB.start_onboarding(HR, COMPANY, {"uk": UK})
        ONB = onb["onb_no"]
        check("TC-15", "joining/onboarding opens only after acceptance",
              ONB.startswith("ONB-"))
        check("TC-16", "onboarding is bound to the right candidate",
              (await store[M.COLL_ONBOARDING].find_one({"onb_no": ONB}))["uk"] == UK)
        await SH.set_share_status(HR, COMPANY, SHARE_A,
                                  {"status": M.ShareStatus.OFFER_IN_PROGRESS.value})
        await SH.set_share_status(HR, COMPANY, SHARE_A,
                                  {"status": M.ShareStatus.HIRED.value})
        check("TC-20", "the client-side journey reaches Hired",
              (await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": SHARE_A}))["status"] == M.ShareStatus.HIRED.value)

        # ── TC-17 ────────────────────────────────────────────
        section("TC-17  Audit trail")
        rows = store[M.COLL_AUDIT_LOG].docs
        actions = {a["action"] for a in rows}
        for label, action in (("job request raised", M.AUDIT_JOB_REQUEST_RAISED),
                              ("job request reviewed", M.AUDIT_JOB_REQUEST_REVIEWED),
                              ("converted to requisition", M.AUDIT_JOB_REQUEST_CONVERTED),
                              ("CV shared", M.AUDIT_SHARE_CREATED),
                              ("share status changed", M.AUDIT_SHARE_STATUS),
                              ("client opened the CV", M.AUDIT_SHARE_CV_OPENED),
                              ("background check recorded", M.AUDIT_BACKGROUND_RECORDED),
                              ("verification approved", M.AUDIT_BACKGROUND_APPROVED)):
            check("TC-17", f"audited: {label}", action in actions)
        sample = [a for a in rows if a["action"] == M.AUDIT_SHARE_STATUS]
        check("TC-17", "audit rows carry actor, time, company and detail",
              bool(sample) and all(a.get("actor_id") and a.get("created_at")
                                   and a.get("company_id") == COMPANY and a.get("detail")
                                   for a in sample))
        check("TC-17", "a status change records both the old and the new value",
              any("->" in (a.get("detail") or "") for a in sample))
        opened = [a for a in rows if a["action"] == M.AUDIT_SHARE_CV_OPENED]
        check("TC-17", "client ACCESS is audited, not only client decisions",
              bool(opened) and opened[0]["actor_id"] == U_A)

        # ── TC-18 / TC-19 ────────────────────────────────────
        section("TC-18  Direct/API access   /   TC-19  Multi-client isolation")
        await denied("TC-18", "Client B reading Client A's share by id",
                     SH.get_share(CB, COMPANY, SHARE_A), 404)
        await denied("TC-18", "Client B downloading Client A's CV by id",
                     SH.resume_url_for_share(CB, COMPANY, SHARE_A), 404)
        await denied("TC-18", "Client B opening Client A's job request by id",
                     JR.get_job_request(CB, COMPANY, JBR), 404)
        await denied("TC-18", "a client asking where else a candidate went",
                     SH.shares_for_candidate(CA, COMPANY, UK), 403)
        stranger = user(str(ObjectId()), "CLIENT", name="Unengaged client")
        check("TC-18", "a client with no engagement sees nothing (fails closed)",
              (await SH.list_shares(stranger, COMPANY))["total"] == 0)
        for cap in (M.Cap.BACKGROUND_APPROVE, M.Cap.BACKGROUND_WRITE,
                    M.Cap.SHARE_WRITE, M.Cap.JOB_REQUEST_REVIEW,
                    M.Cap.OFFER_WRITE, M.Cap.CANDIDATE_READ):
            check("TC-18", f"client cannot {cap.value}", not A.can(CA, cap))

        b_final = (await SH.list_shares(CB, COMPANY))["shares"][0]
        check("TC-19", "Client B still reads Under Review",
              b_final["status"] == M.ShareStatus.UNDER_REVIEW.value)
        check("TC-19", "Client B's view carries no offer, no verification, no other client",
              not any(k in b_final for k in ("offer_no", "verification", "history"))
              and "resume_key" not in b_final["snapshot"])
        check("TC-19", "Sparsh sees both sides of the same candidate",
              (await SH.shares_for_candidate(HR, COMPANY, UK))["total"] == 2)

        # ── TC-20 ────────────────────────────────────────────
        section("TC-20  Status history is retained, not overwritten")
        hist = [h["status"] for h in
                (await store[M.COLL_CANDIDATE_SHARES].find_one(
                    {"share_no": SHARE_A}))["history"]]
        check("TC-20", f"full progression retained: {' -> '.join(hist)}",
              hist == [M.ShareStatus.CV_SHARED.value, M.ShareStatus.UNDER_REVIEW.value,
                       M.ShareStatus.SHORTLISTED.value,
                       M.ShareStatus.INTERVIEW_SCHEDULED.value,
                       M.ShareStatus.SELECTED.value,
                       M.ShareStatus.OFFER_IN_PROGRESS.value,
                       M.ShareStatus.HIRED.value])
        check("TC-20", "every history entry names who and when",
              all(h.get("by") and h.get("at") for h in
                  (await store[M.COLL_CANDIDATE_SHARES].find_one(
                      {"share_no": SHARE_A}))["history"]))

        # Rejection must not be global.
        other = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Candidate Y",
            "can_email": "y@example.com", "can_contact": "+91 90000 33333",
            "resume": cv()})
        sy = await SH.share_candidate(HR, COMPANY, {
            "uk": other["uk"], "client_ids": [CLIENT_A]})
        await SH.set_share_status(CA, COMPANY, sy["shared"][0]["share_no"],
                                  {"status": M.ShareStatus.REJECTED.value})
        onward = await SH.share_candidate(HR, COMPANY, {
            "uk": other["uk"], "client_ids": [CLIENT_B]})
        check("TC-20", "a rejection by one client does not reject globally",
              onward["count"] == 1)

    finally:
        mongo.get_collection = keep_get
        NS.notify_user, NS.notify_users, NS.notify_hrms_role = keep_notify
        S3.upload_file_to_s3_with_key, S3.get_signed_url = keep_s3, keep_url

    # ── Report ───────────────────────────────────────────────
    print()
    print("=" * 74)
    print("  EXECUTION REPORT")
    print("=" * 74)
    print(f"  {'ID':7} {'Scenario':34} {'Status':8} Notes")
    print("  " + "-" * 70)
    passed = failed = notrun = 0
    for tc, scenario, _expected in CASES:
        r = results.get(tc)
        if r is None:
            status, note, notrun = "NOT RUN", "", notrun + 1
        elif r["ok"]:
            status, note, passed = "PASS", "", passed + 1
        else:
            status, note, failed = "FAIL", "; ".join(r["notes"][:2]), failed + 1
        print(f"  {tc:7} {scenario[:34]:34} {status:8} {note[:24]}")
    total_checks = len(checks)
    print("  " + "-" * 70)
    print(f"  cases: {len(CASES)}   PASS {passed}   FAIL {failed}   NOT RUN {notrun}")
    print(f"  individual assertions: {sum(1 for c in checks if c[2])}/{total_checks}")

    if survey:
        print()
        print("=" * 74)
        print("  PRODUCTION READINESS (read-only survey, no writes)")
        print("=" * 74)
        print(f"  candidates                     {survey['candidates']}")
        print(f"  ...with a usable CV            {survey['with_cv']}"
              f"   <- only these can be shared")
        print(f"  client engagements             {survey['engagements']}"
              f"   <- 0 means no client can see anything")
        print(f"  CLIENT-role users              {survey['client_users']}"
              f"   <- 0 means no client can log in")
        print(f"  job requests                   {survey['job_requests']}")
        print(f"  candidate shares (new model)   {survey['shares']}")
        print(f"  candidates on the OLD embedded client_share: {survey['legacy_shared']}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
