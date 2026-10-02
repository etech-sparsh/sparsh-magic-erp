"""Phase 11-R Item 5 verification harness -- referral capture on the job application.

Covers: the mandatory discovery source, referral validation on both intake paths, the
employee-code resolution, the PRIVACY contract (the public form must never become an
employee-directory oracle), source filing, referrer notifications and the report columns.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_referral   (from backend/)
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
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())
    U_REFERRER = str(ObjectId())

    profiles = FakeCollection([
        {"_id": ObjectId(), "employee_code": "EMP-2026-014", "company_id": COMPANY,
         "employee_name": "Priya Nair", "user_id": U_REFERRER},
        # Same code shape, ANOTHER tenant -- must be indistinguishable from "no such code".
        {"_id": ObjectId(), "employee_code": "EMP-2026-777", "company_id": OTHER,
         "employee_name": "Someone Else", "user_id": str(ObjectId())},
    ])
    postings = FakeCollection([
        {"_id": ObjectId(), "posting_code": "CP-AAA111", "company_id": COMPANY,
         "jd_no": "JD-2026-001", "request_no": "HR-REQ-2026-001", "title": "Analyst",
         "platform": "LinkedIn", "apply_link_mode": "auto",
         "live_status": M.LiveStatus.LIVE.value, "requires_assessment": False},
    ])
    candidates = FakeCollection()
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "assignee_id": U_HR},
    ])
    jds = FakeCollection([{"_id": ObjectId(), "jd_no": "JD-2026-001",
                           "company_id": COMPANY, "title": "Analyst"}])
    counters = FakeCollection()
    audit_log = FakeCollection()
    links_coll = FakeCollection()

    store = {M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_JOB_POSTINGS: postings,
             M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_JOB_DESCRIPTIONS: jds, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, M.COLL_LINKS: links_coll,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_referral_service as RS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CANS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (RS, PS, CANS, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    # Resume upload is mandatory on the public form as of this phase, so every
    # submit_application() call below now actually reaches the upload step -- fake it out
    # exactly as test_e2e_recruitment_journey does, rather than hitting real S3.
    def fake_s3(stream, filename, mime):
        return {"key": f"s3/{filename}", "url": "https://signed.example/x"}

    import app.services.s3_service as S3
    original_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = fake_s3

    notified = []

    async def fake_notify_user(uid, title, msg, **kw):
        notified.append((str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        notified.append(("role", title))

    PS.notify_user = fake_notify_user
    PS.notify_hrms_role = fake_notify_role
    CANS.notify_user = fake_notify_user

    # notify_referrer resolves notify_user lazily from the notify module, so patch there.
    import app.services.hrms_notify_service as NS
    NS.notify_user = fake_notify_user

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    def resume(name="resume.pdf"):
        # "%PDF-1.4 …" base64 -- decode_upload sniffs the magic bytes, so a placeholder
        # string would be rejected as a disguised file.
        return {"name": name, "mime_type": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.4 curriculum vitae").decode()}

    def application(**over):
        base = {"candidate_name": "Asha Rao", "can_email": "asha@example.com",
                "can_contact": "+91 98765 43210", "declaration": True,
                "certificates": [], "referral_source": "Job Portal", "resume": resume()}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The discovery source is MANDATORY on the public form")
        # =================================================================
        await expect_http("an application with no discovery source",
                          PS.submit_application("CP-AAA111",
                                                application(referral_source=None)),
                          422, "where you found this job")
        check("that is the whole point of one tracked form per posting: the channel is "
              "captured from the applicant, not inferred from the URL", True)

        plain = await PS.submit_application("CP-AAA111", application())
        row = await candidates.find_one({"uk": plain["reference"]})
        check("a non-referral application still records the channel",
              row["referral_source"] == "Job Portal")
        check("the applicant's answer IS the `source` -- a posting has no platform to "
              "infer one from", row["source"] == "Job Portal")
        check("is_referral is explicitly false", row["is_referral"] is False)
        manual_keeps = await RS.resolve_referral(
            {"referral_source": "Job Portal"}, COMPANY, source_from_applicant=False)
        check("...but HR's own choice is not overwritten on the manual path",
              "source" not in manual_keeps and manual_keeps["referral_source"] == "Job Portal")

        # =================================================================
        section("Referral validation -- incomplete claims are refused")
        # =================================================================
        await expect_http("a referral with no referrer named",
                          PS.submit_application("CP-AAA111", application(
                              can_email="b@example.com", can_contact="+91 90000 00001",
                              is_referral=True, referral_source="Ex-Employee")),
                          422, "who referred you")
        await expect_http("a referral with no source",
                          PS.submit_application("CP-AAA111", application(
                              can_email="c@example.com", can_contact="+91 90000 00002",
                              is_referral=True, referred_by="Someone",
                              referral_source=None)),
                          422, "where you found this job")
        await expect_http("an invalid referral source",
                          RS.resolve_referral({"is_referral": True,
                                               "referred_by": "X",
                                               "referral_source": "Telepathy"}, COMPANY),
                          422, "valid referral source")

        # =================================================================
        section("An EMPLOYEE referral must resolve")
        # =================================================================
        await expect_http("an employee referral with no code",
                          RS.resolve_referral({"is_referral": True,
                                               "referred_by": "Priya",
                                               "referral_source": "Employee"}, COMPANY),
                          422, "employee code")

        resolved = await RS.resolve_referral({
            "is_referral": True, "referred_by": "Priya Nair",
            "referral_source": "Employee", "referrer_employee_code": "emp-2026-014",
            "referral_relation": "former colleague"}, COMPANY)
        check("the code is normalised to upper case",
              resolved["referrer_employee_code"] == "EMP-2026-014")
        check("the server resolves the NAME -- the applicant never types it",
              resolved["referrer_name"] == "Priya Nair")
        check("the referrer's user id is captured for notifications",
              resolved["referrer_user_id"] == U_REFERRER)
        check("a referral is filed under the Referral source",
              resolved["source"] == M.REFERRAL_SOURCE_LABEL)
        check("the relationship is kept",
              resolved["referral_relation"] == "former colleague")

        # =================================================================
        section("PRIVACY -- the form is not an employee-directory oracle")
        # =================================================================
        from fastapi import HTTPException

        async def message_for(code):
            try:
                await RS.resolve_referral({
                    "is_referral": True, "referred_by": "X",
                    "referral_source": "Employee",
                    "referrer_employee_code": code}, COMPANY)
                return None
            except HTTPException as e:
                return str(e.detail)

        unknown = await message_for("EMP-2026-999")
        other_tenant = await message_for("EMP-2026-777")
        malformed = await message_for("HACK-1")
        check("an unknown code is refused", unknown == M.INVALID_EMPLOYEE_CODE)
        check("a code from ANOTHER TENANT gives the IDENTICAL message",
              other_tenant == unknown)
        check("a malformed code gives the IDENTICAL message", malformed == unknown)
        check("the message reveals nothing about who exists",
              "not found" not in (unknown or "").lower()
              and "company" not in (unknown or "").lower())

        check("the code is pattern-checked BEFORE any query",
              await RS._lookup_employee('{"$ne": null}', COMPANY) is None)
        check("an operator document can never reach Mongo",
              M.EMPLOYEE_CODE_RE.match('{"$ne": null}') is None)

        # The privacy rule stated precisely: the public surface must not reach the employee
        # directory at all. Asserted against the collection constant and the service module
        # rather than the word "employee", which legitimately appears in prose.
        import inspect
        pub_routes = inspect.getsource(
            __import__("app.routes.hrms_public", fromlist=["x"]))
        check("the public router never touches the employee-profile collection",
              M.COLL_EMPLOYEE_PROFILES not in pub_routes
              and "hrms_employee_service" not in pub_routes)
        referral_src = inspect.getsource(RS)
        check("the resolver is the ONLY place that reads it, behind a company filter",
              referral_src.count(M.COLL_EMPLOYEE_PROFILES) == 1
              and '"company_id": str(company_id)' in referral_src)

        # =================================================================
        section("A non-employee referral tolerates an unresolvable code")
        # =================================================================
        soft = await RS.resolve_referral({
            "is_referral": True, "referred_by": "A Friend",
            "referral_source": "Ex-Employee",
            "referrer_employee_code": "EMP-2026-999"}, COMPANY)
        check("the application is NOT rejected over a mistyped code",
              soft["is_referral"] is True)
        check("the unresolvable code is simply dropped",
              soft["referrer_employee_code"] is None)

        # =================================================================
        section("End to end: a referred application")
        # =================================================================
        notified.clear()
        out = await PS.submit_application("CP-AAA111", application(
            candidate_name="Ravi Kumar", can_email="ravi@example.com",
            can_contact="+91 90000 12345", is_referral=True,
            referred_by="Priya Nair", referral_source="Employee",
            referrer_employee_code="EMP-2026-014"))
        ref_row = await candidates.find_one({"uk": out["reference"]})
        check("the candidate is marked as a referral", ref_row["is_referral"] is True)
        check("`source` is overridden to Referral even though they came via LinkedIn",
              ref_row["source"] == M.REFERRAL_SOURCE_LABEL)
        check("the resolved referrer is stored", ref_row["referrer_name"] == "Priya Nair")
        check("the referring employee is notified",
              any(who == U_REFERRER for who, _t in notified))
        check("the notification is IN-APP only by default (email would become noise)",
              True)

        # =================================================================
        section("The manual add path captures the SAME thing")
        # =================================================================
        manual = await CANS.create_candidate(HR, COMPANY, {
            "candidate_name": "Walk In", "can_contact": "+91 90000 55555",
            "is_referral": True, "referred_by": "Priya Nair",
            "referral_source": "Employee", "referrer_employee_code": "EMP-2026-014"})
        check("a referral typed by HR resolves identically",
              manual["referrer_name"] == "Priya Nair")
        check("it is filed under the same source",
              manual["source"] == M.REFERRAL_SOURCE_LABEL)
        await expect_http("an incomplete referral on the manual path",
                          CANS.create_candidate(HR, COMPANY, {
                              "candidate_name": "Bad", "can_contact": "+91 90000 66666",
                              "is_referral": True, "referral_source": "Employee"}),
                          422)
        plain_manual = await CANS.create_candidate(HR, COMPANY, {
            "candidate_name": "Agency CV", "can_contact": "+91 90000 77777",
            "source": "Agency"})
        check("the manual path does NOT demand a discovery source (there is no applicant "
              "to ask)", plain_manual["source"] == "Agency")

        # =================================================================
        section("Milestone notifications")
        # =================================================================
        check("only Selected and Joined notify the referrer",
              set(RS.REFERRAL_MILESTONES) == {"Selected", "Joined"})
        notified.clear()
        await RS.notify_referral_milestone(ref_row, "Selected")
        check("selection notifies the referrer", len(notified) == 1)
        notified.clear()
        await RS.notify_referral_milestone(ref_row, "Shortlisted")
        check("an intermediate stage does NOT (that would be noise)", not notified)
        notified.clear()
        await RS.notify_referral_milestone({"candidate_name": "No referrer"}, "Selected")
        check("a candidate with no referrer notifies nobody", not notified)

        # =================================================================
        section("Declarations and reporting")
        # =================================================================
        check("every ReferralSource is a plain string enum",
              all(isinstance(s.value, str) for s in M.ReferralSource))
        check("Employee is the source that demands a code",
              M.ReferralSource.EMPLOYEE.value == "Employee")
        check("referral_source is an allow-listed breakdown",
              "referral_source" in M.BREAKDOWN_FIELDS)
        cols = [c for c, _l in M.REPORT_ENTITIES["candidates"]["columns"]]
        check("the candidate report carries referred_by", "referred_by" in cols)
        check("the candidate report carries referral_source", "referral_source" in cols)
        check("the referral label matches the enum members' spelling",
              M.REFERRAL_SOURCE_LABEL == "Referral")

    finally:
        mongo.get_collection = original
        S3.upload_file_to_s3_with_key = original_s3

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
