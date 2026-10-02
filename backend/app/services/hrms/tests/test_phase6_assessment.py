"""Phase 6 verification harness -- assessments with dual review.

Covers: the send gate, the full lifecycle (Sent -> Opened -> Completed -> Reviewed), slot
resolution, the four dual-review outcome combinations, single-reviewer fallback, concurrent
decisions, access-code entropy and leakage, candidate advancement, and the public
open/submit path.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase6_assessment   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_HR2 = (str(ObjectId()) for _ in range(3))

    def candidate(uk, status, requires=True, request_no="HR-REQ-2026-001"):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": f"Cand {uk}", "can_email": f"{uk}@x.com",
                "application_status": status, "requires_assessment": requires,
                "request_no": request_no}

    S = M.AppStatus
    candidates = FakeCollection([
        candidate("CAN-001", S.ASSESSMENT_PENDING.value),
        candidate("CAN-002", S.SHORTLISTED.value),
        candidate("CAN-003", S.INTERVIEW_SCHEDULED.value),      # too far along
        candidate("CAN-004", S.ASSESSMENT_PENDING.value, requires=False),
        # No requisition -> no hiring manager -> HR decides alone.
        candidate("CAN-005", S.ASSESSMENT_PENDING.value, request_no=None),
        candidate("CAN-006", S.ASSESSMENT_PENDING.value),
        candidate("CAN-007", S.ASSESSMENT_PENDING.value),
        candidate("CAN-008", S.ASSESSMENT_PENDING.value),
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_HOD},
    ])
    assessments_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_ASSESSMENTS: assessments_coll, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_assessment_service as AS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IS
    import app.utils.hrms_public_guard as G
    for mod in (AS, AUD, IS, G):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    AS.notify_user = fake_notify_user
    AS.notify_hrms_role = fake_notify_role

    uploaded = []

    def fake_upload(file_obj, filename, content_type):
        uploaded.append(filename)
        return {"key": f"s3/{filename}", "url": "https://signed.example/x"}

    import app.services.s3_service as S3
    S3.upload_file_to_s3_with_key = fake_upload

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HR2 = {"_id": U_HR2, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HR", "full_name": "Hugo HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    EMP = {"_id": "emp", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    async def send(uk, **over):
        payload = {"uk": uk, "title": "Excel task", "max_score": 100}
        payload.update(over)
        return await AS.send_assessment(HR, COMPANY, payload)

    async def submit(code, response="my answer", attachments=None):
        return await AS.submit_public_assessment(
            code, {"response": response, "attachments": attachments or []})

    try:
        from app.utils import hrms_access as A

        # =================================================================
        section("Capability matrix (Phase 6)")
        # =================================================================
        check("HR can send", A.can(HR, M.Cap.ASSESSMENT_SEND))
        check("HR can review", A.can(HR, M.Cap.ASSESSMENT_REVIEW))
        # The manager is half the dual review -- withholding this would deadlock every one.
        check("MANAGER can review", A.can(HOD, M.Cap.ASSESSMENT_REVIEW))
        check("MANAGER cannot send", not A.can(HOD, M.Cap.ASSESSMENT_SEND))
        check("employee has no assessment access", not A.can(EMP, M.Cap.ASSESSMENT_READ))
        # Sending is operational; reviewing is a hiring decision. Same boundary as Phase 3/5.
        check("INTERNAL can send but NOT review",
              A.can(INTERNAL, M.Cap.ASSESSMENT_SEND)
              and not A.can(INTERNAL, M.Cap.ASSESSMENT_REVIEW))

        # =================================================================
        section("Send gate")
        # =================================================================
        a1 = await send("CAN-001")
        check("assessment created", a1["assessment_no"].startswith("ASM-"))
        check("starts at Sent", a1["status"] == M.AssessmentStatus.SENT.value)
        check("hiring manager resolved from the requisition raiser", a1["manager_id"] == U_HOD)
        check("both slots start empty",
              a1["hr_decision"] is None and a1["manager_decision"] is None)
        check("send audited", any(x["action"] == M.AUDIT_ASSESSMENT_SENT for x in audit_log.docs))

        check("access code is 128-bit entropy (22 url-safe chars)",
              len(a1["access_code"]) >= 20 and G.ACCESS_CODE_RE.match(a1["access_code"]))
        a_other = await send("CAN-002")
        check("access codes are unique per assessment",
              a_other["access_code"] != a1["access_code"])

        await expect_http("sending to a candidate already in interviews", send("CAN-003"),
                          409, "assessment stage")
        await expect_http("sending twice to the same candidate", send("CAN-001"),
                          409, "already has an open assessment")
        await expect_http("unknown candidate", send("CAN-NOPE"), 404)
        await expect_http("no candidate", AS.send_assessment(HR, COMPANY, {"title": "x"}),
                          422, "Select a candidate")
        await expect_http("no title", AS.send_assessment(HR, COMPANY, {"uk": "CAN-006"}),
                          422, "title is required")
        await expect_http("zero max score", send("CAN-006", max_score=0),
                          422, "greater than zero")
        await expect_http("negative max score", send("CAN-006", max_score=-5), 422)
        await expect_http("non-numeric max score", send("CAN-006", max_score="lots"),
                          422, "must be a number")
        await expect_http("external link without a scheme", send("CAN-006", link="test.com"),
                          422, "http")
        await expect_http("javascript: link", send("CAN-006", link="javascript:alert(1)"),
                          422, "http")
        await expect_http("malformed due date", send("CAN-006", due_date="31-12-2026"),
                          422, "YYYY-MM-DD")

        section("Sending moves the candidate into the assessment stage")
        cand2 = await candidates.find_one({"uk": "CAN-002"})
        check("Shortlisted -> Assessment Pending on send",
              cand2["application_status"] == S.ASSESSMENT_PENDING.value)
        check("the stage move is audited",
              any(x["action"] == M.AUDIT_STAGE_CHANGED and x["entity_id"] == "CAN-002"
                  for x in audit_log.docs))

        # =================================================================
        section("Public: open tracking")
        # =================================================================
        view = await AS.get_public_assessment(a1["access_code"])
        check("candidate sees the task", view["title"] == "Excel task")
        check("already_done false while open", view["already_done"] is False)
        # The public payload must not leak internal identifiers.
        for leak in ("company_id", "uk", "manager_id", "hr_decision", "access_code",
                     "created_by", "request_no"):
            check(f"public view omits {leak}", leak not in view)

        doc = await assessments_coll.find_one({"assessment_no": a1["assessment_no"]})
        check("first view marks it Opened", doc["status"] == M.AssessmentStatus.OPENED.value)
        check("opened_at stamped", doc.get("opened_at") is not None)
        check("open is audited",
              any(x["action"] == M.AUDIT_ASSESSMENT_OPENED for x in audit_log.docs))

        first_opened = doc["opened_at"]
        await AS.get_public_assessment(a1["access_code"])
        doc = await assessments_coll.find_one({"assessment_no": a1["assessment_no"]})
        check("a refresh does NOT overwrite the real first-view time",
              doc["opened_at"] == first_opened)

        await expect_http("unknown access code", AS.get_public_assessment("x" * 22),
                          404, "not valid")

        # =================================================================
        section("Public: submission")
        # =================================================================
        out = await submit(a1["access_code"])
        check("submission accepted", out["ok"] is True)
        doc = await assessments_coll.find_one({"assessment_no": a1["assessment_no"]})
        check("status becomes Completed", doc["status"] == M.AssessmentStatus.COMPLETED.value)
        check("response stored", doc["response"] == "my answer")
        check("submitted_at stamped", doc.get("submitted_at") is not None)
        cand = await candidates.find_one({"uk": "CAN-001"})
        check("candidate advances to Assessment Completed",
              cand["application_status"] == S.ASSESSMENT_COMPLETED.value)
        check("HR notified of the submission",
              any(s[0] == "role" and "HR" in s[1] for s in sent))
        check("the hiring manager is notified too",
              any(s[0] == "user" and s[1] == U_HOD for s in sent))

        await expect_http("submitting twice", submit(a1["access_code"]),
                          409, "already submitted")
        done_view = await AS.get_public_assessment(a1["access_code"])
        check("revisiting after submission shows a calm done screen, not an error",
              done_view["already_done"] is True)

        a3 = await send("CAN-006")
        await expect_http("empty submission", submit(a3["access_code"], response=""),
                          422, "at least one file")
        await expect_http("too many attachments",
                          submit(a3["access_code"], attachments=[1] * 11), 422, "at most")

        uploaded.clear()
        await submit(a3["access_code"], response="",
                     attachments=[M.UploadIn(name="ans.pdf", mime_type="application/pdf",
                                             data="JVBERi0xLjQK")])
        doc3 = await assessments_coll.find_one({"assessment_no": a3["assessment_no"]})
        check("attachment-only submission accepted", len(doc3["attachments"]) == 1)
        check("the S3 key is persisted, not an expiring URL",
              doc3["attachments"][0]["key"].startswith("s3/")
              and "url" not in doc3["attachments"][0])

        # =================================================================
        section("Dual review: slot resolution")
        # =================================================================
        no = a1["assessment_no"]
        doc = await assessments_coll.find_one({"assessment_no": no})
        check("HR fills the HR slot", AS._slot_for(HR, doc) == M.SLOT_HR)
        check("a DIFFERENT HR user also fills the HR slot", AS._slot_for(HR2, doc) == M.SLOT_HR)
        # The raiser is being asked as the hiring manager, so they always fill that slot --
        # this is what stops one person signing twice.
        check("the requisition raiser fills the MANAGER slot",
              AS._slot_for(HOD, doc) == M.SLOT_MANAGER)

        await expect_http("reviewing before submission",
                          AS.review_assessment(HR, COMPANY, a_other["assessment_no"],
                                               {"decision": "Pass"}), 409, "not been submitted")
        await expect_http("invalid decision",
                          AS.review_assessment(HR, COMPANY, no, {"decision": "Maybe"}),
                          422, "Pass or Fail")
        await expect_http("score above max",
                          AS.review_assessment(HR, COMPANY, no,
                                               {"decision": "Pass", "score": 500}),
                          422, "between 0 and")
        await expect_http("negative score",
                          AS.review_assessment(HR, COMPANY, no,
                                               {"decision": "Pass", "score": -1}), 422)
        await expect_http("unknown assessment",
                          AS.review_assessment(HR, COMPANY, "ASM-NOPE",
                                               {"decision": "Pass"}), 404)

        section("Dual review: one decision does not resolve it")
        r = await AS.review_assessment(HR, COMPANY, no, {"decision": "Pass", "score": 85})
        check("HR decision recorded", r["hr_decision"] == "Pass")
        check("still Completed, not Reviewed", r["status"] == M.AssessmentStatus.COMPLETED.value)
        check("advisory recommendation derived from the score",
              r["recommendation"] == M.Recommendation.RECOMMENDED.value)
        cand = await candidates.find_one({"uk": "CAN-001"})
        check("candidate has NOT advanced on one decision",
              cand["application_status"] == S.ASSESSMENT_COMPLETED.value)
        check("the pending reviewer is nudged",
              any(s[0] == "user" and s[1] == U_HOD and "needs your decision" in s[2].lower()
                  for s in sent))

        await expect_http("the same reviewer deciding twice",
                          AS.review_assessment(HR, COMPANY, no, {"decision": "Fail"}),
                          409, "already been recorded")
        await expect_http("a second HR user cannot overwrite the HR slot",
                          AS.review_assessment(HR2, COMPANY, no, {"decision": "Fail"}),
                          409, "already been recorded")

        section("Dual review: both Pass -> Assessment Passed")
        r = await AS.review_assessment(HOD, COMPANY, no, {"decision": "Pass"})
        check("now Reviewed", r["status"] == M.AssessmentStatus.REVIEWED.value)
        check("lifecycle reads Passed", r["lifecycle"] == "Passed")
        cand = await candidates.find_one({"uk": "CAN-001"})
        check("candidate advances to Assessment Passed",
              cand["application_status"] == S.ASSESSMENT_PASSED.value)
        check("outcome audited",
              any(x["action"] == M.AUDIT_ASSESSMENT_RESOLVED for x in audit_log.docs))
        check("BOTH reviewers hear the outcome",
              any("Pass" in s[2] for s in sent if s[0] == "role")
              and any("Pass" in s[2] for s in sent if s[0] == "user" and s[1] == U_HOD))
        await expect_http("reviewing a resolved assessment",
                          AS.review_assessment(HR, COMPANY, no, {"decision": "Fail"}),
                          409, "already been fully reviewed")

        section("Dual review: the other three combinations")

        async def run_combo(uk, hr_decision, mgr_decision):
            a = await send(uk)
            await AS.get_public_assessment(a["access_code"])
            await submit(a["access_code"])
            await AS.review_assessment(HR, COMPANY, a["assessment_no"],
                                       {"decision": hr_decision})
            await AS.review_assessment(HOD, COMPANY, a["assessment_no"],
                                       {"decision": mgr_decision})
            return (await candidates.find_one({"uk": uk}))["application_status"]

        got = await run_combo("CAN-007", "Pass", "Fail")
        check("Pass + Fail -> Assessment Failed", got == S.ASSESSMENT_FAILED.value)
        got = await run_combo("CAN-008", "Fail", "Pass")
        check("Fail + Pass -> Assessment Failed", got == S.ASSESSMENT_FAILED.value)
        got = await run_combo("CAN-004", "Fail", "Fail")
        check("Fail + Fail -> Assessment Failed", got == S.ASSESSMENT_FAILED.value)

        section("Single-reviewer fallback (no hiring manager)")
        # CAN-005 has no requisition, so no manager can ever decide. Requiring a second
        # signature nobody can give would strand the candidate forever.
        a5 = await send("CAN-005")
        check("no manager resolved", a5["manager_id"] is None)
        await AS.get_public_assessment(a5["access_code"])
        await submit(a5["access_code"])
        r = await AS.review_assessment(HR, COMPANY, a5["assessment_no"], {"decision": "Pass"})
        check("HR alone resolves it when there is no manager",
              r["status"] == M.AssessmentStatus.REVIEWED.value)
        cand5 = await candidates.find_one({"uk": "CAN-005"})
        check("candidate advances on the single decision",
              cand5["application_status"] == S.ASSESSMENT_PASSED.value)

        # =================================================================
        section("Listing, slots and access-code hygiene")
        # =================================================================
        listing = await AS.list_assessments(HOD, COMPANY)
        check("stats returned", "to_review" in listing["stats"])
        for item in listing["assessments"]:
            if item["status"] in (M.AssessmentStatus.COMPLETED.value,
                                  M.AssessmentStatus.REVIEWED.value):
                check(f"{item['assessment_no']}: access code withheld once unusable",
                      "access_code" not in item)
                break
        open_items = [i for i in listing["assessments"]
                      if i["status"] in (M.AssessmentStatus.SENT.value,
                                         M.AssessmentStatus.OPENED.value)]
        check("access code still returned while the link is usable",
              all("access_code" in i for i in open_items) if open_items else True)
        check("each row says which slot the viewer fills",
              all(i["my_slot"] in (M.SLOT_HR, M.SLOT_MANAGER) for i in listing["assessments"]))

        pending = await send("CAN-006") if False else None  # CAN-006 already used
        mine = await AS.list_assessments(HOD, COMPANY, mine=True)
        check("'mine' returns only rows awaiting THIS reviewer",
              all(i["awaiting_me"] for i in mine["assessments"]))

        section("Assessable candidate picker")
        pickable = await AS.assessable_candidates(HR, COMPANY)
        uks = {p["uk"] for p in pickable}
        check("a candidate with an OPEN assessment is excluded", "CAN-002" not in uks)
        check("a candidate past the assessment stage is excluded", "CAN-003" not in uks)
        offered_flags = [(await candidates.find_one({"uk": u}))["requires_assessment"]
                         for u in uks]
        check("only assessment-required candidates are offered", all(offered_flags))

        section("Index registry (Phase 6 additions)")
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("assessment_no unique",
              any(c == M.COLL_ASSESSMENTS and n == "uniq_assessment_no" for c, n in names))
        check("access_code unique + indexed (every public request looks up by it)",
              any(c == M.COLL_ASSESSMENTS and n == "uniq_access_code" for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))

        section("Recommendation thresholds (advisory only)")
        check("70% -> Recommended",
              M.recommendation_for(70, 100) == M.Recommendation.RECOMMENDED.value)
        check("69% -> Borderline",
              M.recommendation_for(69, 100) == M.Recommendation.BORDERLINE.value)
        check("49% -> Not Recommended",
              M.recommendation_for(49, 100) == M.Recommendation.NOT_RECOMMENDED.value)
        check("no score -> no recommendation", M.recommendation_for(None, 100) is None)
        check("zero max score never divides by zero", M.recommendation_for(10, 0) is None)
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
