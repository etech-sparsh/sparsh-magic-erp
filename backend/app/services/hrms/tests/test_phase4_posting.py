"""Phase 4 verification harness -- job postings + public application intake.

Covers: publishing gates, one-live-link-per-JD, external link validation, computed
application counts, expiry, the public job ad, application validation, duplicate detection,
upload validation, and the public guard's rate limiter / code validator / sanitisers.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase4_posting   (from backend/)
"""
from __future__ import annotations

import asyncio

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
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection, _matches  # noqa: E402

COMPANY = "C1"


class AggCollection(FakeCollection):
    """FakeCollection plus the single $match/$group aggregation the counter uses."""

    def aggregate(self, pipeline):
        from app.services.hrms.tests.test_phase2_employee import FakeCursor
        match = next((s["$match"] for s in pipeline if "$match" in s), {})
        group = next((s["$group"] for s in pipeline if "$group" in s), None)
        rows = [d for d in self.docs if _matches(d, match)]
        if not group:
            return FakeCursor(rows)
        field = group["_id"].lstrip("$")
        counts = {}
        for d in rows:
            counts[d.get(field)] = counts.get(d.get(field), 0) + 1
        return FakeCursor([{"_id": k, "n": v} for k, v in counts.items()])


def b64(payload: bytes) -> str:
    import base64
    return base64.b64encode(payload).decode()


PDF = b"%PDF-1.4 fake resume bytes"


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    jds = FakeCollection([
        {"_id": ObjectId(), "jd_no": "JD-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "title": "Analyst",
         "status": M.JdStatus.APPROVED.value, "responsibilities": "Own the ledger.",
         "skills": "Excel", "location": "Pune"},
        {"_id": ObjectId(), "jd_no": "JD-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-002", "title": "Pending Role",
         "status": M.JdStatus.PENDING_APPROVAL.value, "responsibilities": "x"},
        # A JD now yields ONE live posting, so every publish below that must succeed needs a
        # JD of its own rather than another platform on the same one.
        *[{"_id": ObjectId(), "jd_no": f"JD-2026-{n:03d}", "company_id": COMPANY,
           "request_no": "HR-REQ-2026-001", "title": f"Spare Role {n}",
           "status": M.JdStatus.APPROVED.value, "responsibilities": "x"}
          for n in range(3, 9)],
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "department_name": "Accounts", "designation_name": "Analyst", "vacancy": 2,
         "assignee_id": "recruiter-1", "experience_required": "3y", "qualification": "B.Com"},
    ])
    postings = FakeCollection()
    candidates = AggCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()
    ratelimit = FakeCollection()

    store = {
        M.COLL_JOB_DESCRIPTIONS: jds, M.COLL_REQUISITIONS: reqs,
        M.COLL_JOB_POSTINGS: postings, M.COLL_CANDIDATES: candidates,
        M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
        M.COLL_PUBLIC_RATELIMIT: ratelimit, "learners": FakeCollection(),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_posting_service as PS
    import app.services.hrms_audit_service as AS
    import app.services.hrms_id_service as IS
    import app.utils.hrms_public_guard as G
    for mod in (PS, AS, IS, G):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    PS.notify_user = fake_notify_user
    PS.notify_hrms_role = fake_notify_role

    # Stub S3 so uploads are exercised without network or credentials.
    uploaded = []

    def fake_upload(file_obj, filename, content_type):
        data = file_obj.read()
        uploaded.append((filename, content_type, len(data)))
        return {"key": f"s3/{filename}", "url": "https://signed.example/x"}

    import app.services.s3_service as S3
    S3.upload_file_to_s3_with_key = fake_upload

    HR = {"_id": "hr", "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Publishing gate: only an APPROVED JD may be published")
        # =================================================================
        await expect_http("publishing a Pending JD", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-002"}), 409, "approved job description")
        await expect_http("publishing an unknown JD", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-9999"}), 404)
        await expect_http("no JD selected", PS.create_posting(HR, COMPANY, {}), 422)

        section("Channels: at least one is required")
        await expect_http("no channel selected", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-001"}), 422, "at least one recruitment channel")
        await expect_http("an unrecognised channel", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-001", "channels": ["Carrier Pigeon"]}),
            422, "not a recognised recruitment channel")

        section("Create drafts, publish separately")
        res = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-001", "requires_assessment": True,
            "channels": ["Job Portals", "Internal Database"]})
        posting = res["posting"]
        live_code = posting["posting_code"]
        check("creating drafts exactly one row", res["created"] == 1)
        check("code matches the public pattern",
              M.POSTING_CODE_RE.match(live_code) is not None)
        check("no platform is stored on the posting", "platform" not in posting)
        check("an auto posting carries no external url", posting["external_url"] is None)
        check("assessment flag stored", posting["requires_assessment"] is True)
        check("channels stored, de-duplicated and sorted",
              posting["channels"] == sorted({"Job Portals", "Internal Database"}))
        check("opens as Draft, not live immediately",
              posting["live_status"] == M.LiveStatus.DRAFT.value)
        check("posting_date is not set until it is actually published",
              posting["posting_date"] is None)
        check("creation audited", any(a["action"] == M.AUDIT_POSTING_CREATED for a in audit_log.docs))

        published = await PS.publish_posting(HR, COMPANY, live_code)
        check("publishing takes it Live", published["live_status"] == M.LiveStatus.LIVE.value)
        check("posting_date is stamped at publish time", published["posting_date"] == PS._today())
        check("publish audited",
              any(a["action"] == M.AUDIT_POSTING_PUBLISHED for a in audit_log.docs))
        await expect_http("publishing an already-live posting again", PS.publish_posting(
            HR, COMPANY, live_code), 409, "only a draft posting")

        section("Executive Search needs Management's approval before it can publish")
        exec_draft = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-003", "channels": ["Executive Search"]})
        check("opens Pending Management Approval, not Draft",
              exec_draft["posting"]["live_status"] == M.LiveStatus.PENDING_APPROVAL.value)
        await expect_http("publishing before Management clears it", PS.publish_posting(
            HR, COMPANY, exec_draft["posting"]["posting_code"]), 409, "management")
        MD = {"_id": "md", "role": "clientuser", "_source_collection": "learners",
              "company_id": COMPANY, "governance_role": "MD", "full_name": "Mona MD"}
        cleared = await PS.approve_exec_search(MD, COMPANY, exec_draft["posting"]["posting_code"])
        check("approval moves it to Draft, not straight to Live",
              cleared["live_status"] == M.LiveStatus.DRAFT.value)
        check("approval is audited",
              any(a["action"] == M.AUDIT_POSTING_EXEC_APPROVED for a in audit_log.docs))
        exec_live = await PS.publish_posting(MD, COMPANY, exec_draft["posting"]["posting_code"])
        check("now publishes normally", exec_live["live_status"] == M.LiveStatus.LIVE.value)
        await PS.update_posting(MD, COMPANY, exec_draft["posting"]["posting_code"],
                                {"live_status": M.LiveStatus.CLOSED.value})

        section("One LIVE link per JD")
        draft2 = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-001", "channels": ["Job Portals"]})
        check("a second draft for an already-live JD may still be created",
              draft2["created"] == 1)
        await expect_http("publishing it while the first is live", PS.publish_posting(
            HR, COMPANY, draft2["posting"]["posting_code"]), 409, "already published")
        tmp = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-003", "channels": ["Job Portals"]})
        tmp_code = tmp["posting"]["posting_code"]
        await PS.publish_posting(HR, COMPANY, tmp_code)
        await PS.update_posting(HR, COMPANY, tmp_code, {"live_status": M.LiveStatus.CLOSED.value})
        again = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-003", "channels": ["Job Portals"]})
        again_published = await PS.publish_posting(HR, COMPANY, again["posting"]["posting_code"])
        check("closing the posting frees the JD to be published again",
              again["created"] == 1 and again_published["posting_code"] != tmp_code)

        section("External link validation")
        before = len(postings.docs)
        await expect_http("external mode with no url", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-004", "channels": ["Job Portals"],
                          "apply_link_mode": "external", "external_url": ""}),
            422, "enter the application link")
        await expect_http("external url without a scheme", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-004", "channels": ["Job Portals"],
                          "apply_link_mode": "external", "external_url": "naukri.com/x"}),
            422, "http")
        await expect_http("javascript: url rejected", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-004", "channels": ["Job Portals"],
                          "apply_link_mode": "external",
                          "external_url": "javascript:alert(1)"}), 422, "http")
        check("a rejected publish writes no row", len(postings.docs) == before)
        ext_res = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-004", "channels": ["Job Portals"], "apply_link_mode": "external",
            "external_url": "https://naukri.example/job/1"})
        ext_code = ext_res["posting"]["posting_code"]
        check("an external posting keeps its url",
              ext_res["posting"]["external_url"] == "https://naukri.example/job/1")
        await PS.publish_posting(HR, COMPANY, ext_code)

        section("Client-previewed codes")
        res2 = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-005", "channels": ["Job Portals"], "code": "JB-ABC123"})
        check("a valid unused preview code is honoured",
              res2["posting"]["posting_code"] == "JB-ABC123")
        res3 = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-006", "channels": ["Job Portals"], "code": "JB-ABC123"})
        check("a DUPLICATE preview code is replaced, not reused",
              res3["posting"]["posting_code"] != "JB-ABC123")
        res4 = await PS.create_posting(HR, COMPANY, {
            "jd_no": "JD-2026-007", "channels": ["Job Portals"], "code": "not-a-code"})
        check("a malformed preview code is replaced",
              M.POSTING_CODE_RE.match(res4["posting"]["posting_code"]) is not None)
        await PS.publish_posting(HR, COMPANY, res2["posting"]["posting_code"])

        section("Expiry")
        await expect_http("expiry in the past", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-008", "channels": ["Job Portals"],
                          "expiry_date": "2020-01-01"}), 422, "past")
        await expect_http("malformed expiry", PS.create_posting(
            HR, COMPANY, {"jd_no": "JD-2026-008", "channels": ["Job Portals"],
                          "expiry_date": "01-01-2030"}), 422)

        expired_code = res2["posting"]["posting_code"]
        await postings.update_one({"posting_code": expired_code},
                                  {"$set": {"expiry_date": "2020-01-01"}})
        listed = await PS.list_postings(HR, COMPANY)
        row = next(p for p in listed["postings"] if p["posting_code"] == expired_code)
        check("a past-expiry posting reads as Expired without a cron job",
              row["live_status"] == M.LiveStatus.EXPIRED.value)
        stored = await postings.find_one({"posting_code": expired_code})
        check("the stored value is left alone (operator can still see what was set)",
              stored["live_status"] == M.LiveStatus.LIVE.value)
        await postings.update_one({"posting_code": expired_code}, {"$set": {"expiry_date": None}})

        # =================================================================
        section("Public job ad")
        # =================================================================
        ad = await PS.get_public_posting(live_code)
        check("ad returns the role", ad["title"] == "Analyst")
        check("ad includes JD content", ad["responsibilities"] == "Own the ledger.")
        check("ad includes requisition context", ad["vacancies"] == 2)
        # This response is world-readable -- internal identifiers must not be in it.
        for leak in ("company_id", "request_no", "jd_no", "requires_assessment",
                     "posted_by", "notes"):
            check(f"public ad does NOT leak {leak}", leak not in ad)

        ext = await PS.get_public_posting(ext_code)
        check("external posting signposts rather than serving a form", ext["external"] is True)
        check("external posting exposes only its destination",
              set(ext) == {"ok", "external", "external_url", "title"})

        await expect_http("unknown code", PS.get_public_posting("ZZ-ZZZZZZ"), 404, "not valid")
        await PS.update_posting(HR, COMPANY, live_code, {"live_status": M.LiveStatus.PAUSED.value})
        await expect_http("paused posting", PS.get_public_posting(live_code), 410,
                          "no longer accepting")
        await PS.update_posting(HR, COMPANY, live_code, {"live_status": M.LiveStatus.LIVE.value})

        # =================================================================
        section("Public application")
        # =================================================================
        def application(**over):
            # `referral_source` is REQUIRED: the public form asks every applicant where they
            # found the job, and that answer BECOMES the candidate's source now that a
            # posting has no platform to infer one from. It is enforced server-side because
            # a client-side "required" attribute guarantees nothing about a request.
            # Every real form submission carries it, so the fixture does too.
            base = {"candidate_name": "Asha Rao", "can_email": "Asha@Example.com",
                    "can_contact": "+91 98765 43210", "declaration": True,
                    "total_experience": "4 years", "certificates": [],
                    "referral_source": "Job Portal",
                    "resume": {"name": "cv.pdf", "mime_type": "application/pdf",
                               "data": b64(PDF)}}
            base.update(over)
            return base

        out = await PS.submit_application(live_code, application())
        check("application accepted", out["ok"] is True and out["duplicate"] is False)
        check("reference returned", out["reference"].startswith("CAN-"))
        cand = await candidates.find_one({"uk": out["reference"]})
        check("status is Applied", cand["application_status"] == M.AppStatus.APPLIED.value)
        check("email normalised to lowercase", cand["can_email"] == "asha@example.com")
        check("source comes from the applicant's answer, not the posting",
              cand["source"] == "Job Portal")
        check("assessment flag COPIED onto the candidate", cand["requires_assessment"] is True)
        check("linked to posting/jd/requisition",
              cand["posting_code"] == live_code and cand["jd_no"] == "JD-2026-001"
              and cand["request_no"] == "HR-REQ-2026-001")
        check("application audited", any(a["action"] == M.AUDIT_APPLICATION for a in audit_log.docs))
        check("HR notified", any(s[0] == "role" and "HR" in s[1] for s in sent))
        check("assigned recruiter notified too",
              any(s[0] == "user" and s[1] == "recruiter-1" for s in sent))

        section("Application validation")
        for field, value, fragment in (("candidate_name", "", "full name"),
                                       ("can_email", "not-an-email", "valid email"),
                                       ("can_email", "", "valid email"),
                                       ("can_contact", "abc", "valid phone"),
                                       ("can_contact", "", "valid phone")):
            await expect_http(f"invalid {field}={value!r}",
                              PS.submit_application(live_code, application(**{field: value})),
                              422, fragment)
        await expect_http("declaration not ticked", PS.submit_application(
            live_code, application(declaration=False)), 422, "accurate")
        await expect_http("too many certificates", PS.submit_application(
            live_code, application(certificates=[1] * 11)), 422, "at most")
        await expect_http("applying to an unknown code", PS.submit_application(
            "ZZ-ZZZZZZ", application()), 404, "not valid")
        await expect_http("applying through an external posting", PS.submit_application(
            ext_code, application()), 409, "original job board")

        section("Duplicate detection (server-side)")
        dup = await PS.submit_application(live_code, application())
        check("same email -> duplicate, not a second record", dup["duplicate"] is True)
        check("duplicate returns the ORIGINAL reference", dup["reference"] == out["reference"])
        check("only one candidate row exists", len(candidates.docs) == 1)
        dup2 = await PS.submit_application(
            live_code, application(can_email="different@example.com"))
        check("same PHONE also detected as duplicate", dup2["duplicate"] is True)
        other = await PS.submit_application(
            live_code, application(can_email="b@example.com", can_contact="9000000001"))
        check("a genuinely different applicant is accepted", other["duplicate"] is False)

        section("Application counts are computed, never stored")
        listed = await PS.list_postings(HR, COMPANY)
        row = next(p for p in listed["postings"] if p["posting_code"] == live_code)
        check("count reflects real candidates", row["application_count"] == 2)
        check("count is not persisted on the posting",
              "application_count" not in await postings.find_one({"posting_code": live_code}))
        check("stats aggregate across postings", listed["stats"]["applications"] == 2)

        section("Uploads")
        uploaded.clear()
        with_files = await PS.submit_application(live_code, application(
            can_email="c@example.com", can_contact="9000000002",
            resume=M.UploadIn(name="cv.pdf", mime_type="application/pdf", data=b64(PDF)),
            certificates=[M.UploadIn(name="deg.pdf", mime_type="application/pdf", data=b64(PDF))]))
        cand = await candidates.find_one({"uk": with_files["reference"]})
        check("resume stored", cand["resume"]["name"] == "cv.pdf")
        check("the S3 KEY is persisted, not an expiring signed URL",
              cand["resume"]["key"].startswith("s3/") and "url" not in cand["resume"])
        check("certificate stored", len(cand["certificates"]) == 1)
        check("s3 received both files", len(uploaded) == 2)

        await expect_http("disallowed MIME type", PS.submit_application(
            live_code, application(can_email="d@example.com", can_contact="9000000003",
                                   resume=M.UploadIn(name="x.exe",
                                                     mime_type="application/x-msdownload",
                                                     data=b64(b"MZ")))),
            415, "not accepted")
        await expect_http("oversized upload", PS.submit_application(
            live_code, application(can_email="e@example.com", can_contact="9000000004",
                                   resume=M.UploadIn(name="big.pdf", mime_type="application/pdf",
                                                     data="A" * (M.MAX_UPLOAD_BYTES * 4 // 3 + 5000)))),
            413, "too large")
        await expect_http("corrupt base64", PS.submit_application(
            live_code, application(can_email="f@example.com", can_contact="9000000005",
                                   resume=M.UploadIn(name="x.pdf", mime_type="application/pdf",
                                                     data="!!!not base64!!!"))),
            400, "could not be read")
        # A rejected form must not cost storage.
        uploaded.clear()
        await expect_http("invalid form with a valid file", PS.submit_application(
            live_code, application(candidate_name="",
                                   resume=M.UploadIn(name="cv.pdf", mime_type="application/pdf",
                                                     data=b64(PDF)))), 422)
        check("no upload happens when validation fails", len(uploaded) == 0)

        # =================================================================
        section("Posting lifecycle")
        # =================================================================
        paused = await PS.update_posting(HR, COMPANY, live_code,
                                         {"live_status": M.LiveStatus.PAUSED.value})
        check("pause works", paused["live_status"] == M.LiveStatus.PAUSED.value)
        await expect_http("update with no fields", PS.update_posting(
            HR, COMPANY, live_code, {}), 400)
        await expect_http("unknown posting", PS.update_posting(
            HR, COMPANY, "ZZ-ZZZZZZ", {"live_status": "Live"}), 404)
        await expect_http("repointing to a bad external url", PS.update_posting(
            HR, COMPANY, live_code, {"apply_link_mode": "external", "external_url": "ftp://x"}),
            422, "http")

        # Three applicants got through: the original, one genuinely different person, and
        # one with files. Every other submit was a duplicate or a validation failure.
        surviving = len(candidates.docs)
        check("three applicants were actually created", surviving == 3)
        gone = await PS.delete_posting(HR, COMPANY, live_code)
        check("posting deleted", gone["deleted"] is True)
        check("delete REPORTS the applications it kept",
              gone["applications_kept"] == surviving)
        check("candidates survive the posting they came through",
              len(candidates.docs) == surviving)
        await expect_http("deleting twice", PS.delete_posting(HR, COMPANY, live_code), 404)

        # =================================================================
        section("Public guard: code validation")
        # =================================================================
        check("valid code normalised to upper", G.validate_posting_code("li-abc123") == "LI-ABC123")
        for bad, why in (("", "empty"), ("../../etc/passwd", "path traversal"),
                         ("LI-ABC12", "too short"), ("LI-ABC1234", "too long"),
                         ("L1-ABC123", "digit in prefix"), ("LI_ABC123", "wrong separator"),
                         ("LI-ABC12$", "symbol")):
            expect_http_sync(f"rejects {why}", lambda b=bad: G.validate_posting_code(b),
                             404, "not valid")
        # A Mongo operator document can never reach a query, because the value must match
        # the pattern before any DB call happens.
        expect_http_sync("rejects a NoSQL operator payload",
                         lambda: G.validate_posting_code('{"$ne": null}'), 404)
        check("the 404 message is identical for malformed and missing codes",
              G.INVALID_LINK == "This application link is not valid.")

        section("Public guard: filename and text sanitising")
        check("path traversal stripped from filename",
              G.safe_filename("../../../etc/passwd") == "passwd")
        check("windows path stripped", G.safe_filename(r"C:\temp\evil.pdf") == "evil.pdf")
        check("null bytes removed", "\x00" not in G.safe_filename("a\x00b.pdf"))
        check("double-dot collapsed", ".." not in G.safe_filename("a..b..pdf"))
        check("empty name falls back", G.safe_filename("   ") == "file")
        check("filename length capped", len(G.safe_filename("x" * 500)) <= 120)
        check("control characters removed from text",
              "\x00" not in (G.clean_text("bad\x00text") or ""))
        check("text length capped", len(G.clean_text("y" * 9999, limit=100)) == 100)
        # HTML is stored inert, not escaped -- React escapes on render, and escaping here
        # would double-encode a legitimate "&" in a company name.
        check("html is stored verbatim (React escapes on render)",
              G.clean_text("<script>alert(1)</script>") == "<script>alert(1)</script>")
        check("None passes through", G.clean_text(None) is None)

        section("Public guard: rate limiting")
        ratelimit.docs.clear()
        limit, _window = G.RATE_LIMITS["apply"]
        for i in range(limit):
            await G.enforce_rate_limit("apply", "1.2.3.4")
        check(f"first {limit} requests allowed", True)
        await expect_http("the next request is throttled",
                          G.enforce_rate_limit("apply", "1.2.3.4"), 429, "too many")
        await G.enforce_rate_limit("apply", "5.6.7.8")
        check("a different IP is unaffected", True)
        await G.enforce_rate_limit("view", "1.2.3.4")
        check("a different scope is counted separately", True)

        # Availability beats perfect throttling for a public hiring form.
        class BrokenLimiter(FakeCollection):
            async def find_one_and_update(self, *a, **kw):
                raise RuntimeError("store down")

        store[M.COLL_PUBLIC_RATELIMIT] = BrokenLimiter()
        await G.enforce_rate_limit("apply", "9.9.9.9")
        check("limiter fails OPEN when its store is unavailable", True)
        store[M.COLL_PUBLIC_RATELIMIT] = ratelimit

        section("Public guard: client IP extraction")
        class Req:
            def __init__(self, headers, host="10.0.0.1"):
                self.headers = headers
                self.client = type("C", (), {"host": host})()

        check("X-Forwarded-For first hop used",
              G.client_ip(Req({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})) == "203.0.113.9")
        check("X-Real-IP fallback", G.client_ip(Req({"x-real-ip": "198.51.100.7"})) == "198.51.100.7")
        check("socket peer fallback", G.client_ip(Req({})) == "10.0.0.1")
        check("header value length-capped",
              len(G.client_ip(Req({"x-forwarded-for": "9" * 500}))) <= 64)

        section("Index registry (Phase 4 additions)")
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("posting_code unique",
              any(c == M.COLL_JOB_POSTINGS and n == "uniq_posting_code" for c, n in names))
        check("candidate uk unique",
              any(c == M.COLL_CANDIDATES and n == "uniq_uk" for c, n in names))
        check("duplicate detection is indexed on email and phone",
              any(c == M.COLL_CANDIDATES and n == "by_company_email" for c, n in names)
              and any(c == M.COLL_CANDIDATES and n == "by_company_phone" for c, n in names))
        ttl = [o for c, _k, o in M.HRMS_INDEXES if c == M.COLL_PUBLIC_RATELIMIT]
        check("rate-limit rows expire via TTL", any("expireAfterSeconds" in o for o in ttl))
        check("index names still unique per collection", len(names) == len(set(names)))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
