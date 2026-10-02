"""Phase 5 verification harness -- candidate pipeline, screening, journey.

Covers: the lifecycle transition graph (every legal edge, and illegal jumps refused), row
scoping, duplicate flagging, screening with partial success, assessment-aware shortlisting,
forwarding, and the audit-derived journey.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase5_candidate   (from backend/)
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

    # =================================================================
    section("The lifecycle graph (pure)")
    # =================================================================
    S = M.AppStatus
    check("Applied -> Shortlisted is legal", M.can_transition(S.APPLIED, S.SHORTLISTED))
    check("Applied -> Under Review is legal", M.can_transition(S.APPLIED, S.UNDER_REVIEW))
    # The headline fix: the source allowed ANY status to be set to ANY other.
    for bad in (S.JOINED, S.SELECTED, S.OFFER_ACCEPTED, S.EMPLOYEE_CREATED,
                S.INTERVIEW_SCHEDULED, S.MD_ROUND):
        check(f"Applied -> {bad.value} is REFUSED", not M.can_transition(S.APPLIED, bad))
    check("Shortlisted -> Assessment Pending legal",
          M.can_transition(S.SHORTLISTED, S.ASSESSMENT_PENDING))
    check("Shortlisted -> Interview Scheduled legal",
          M.can_transition(S.SHORTLISTED, S.INTERVIEW_SCHEDULED))
    check("Assessment Pending -> Interview is REFUSED (must complete first)",
          not M.can_transition(S.ASSESSMENT_PENDING, S.INTERVIEW_SCHEDULED))
    check("Assessment Passed -> Interview legal",
          M.can_transition(S.ASSESSMENT_PASSED, S.INTERVIEW_SCHEDULED))
    check("Assessment Failed -> Interview is REFUSED",
          not M.can_transition(S.ASSESSMENT_FAILED, S.INTERVIEW_SCHEDULED))
    check("Selected -> Offer Generated legal", M.can_transition(S.SELECTED, S.OFFER_GENERATED))
    check("Offer Accepted -> Pre-Onboarding legal",
          M.can_transition(S.OFFER_ACCEPTED, S.PRE_ONBOARDING))
    check("Joined -> Employee Created legal", M.can_transition(S.JOINED, S.EMPLOYEE_CREATED))

    section("Always-available and terminal stages")
    for src in (S.APPLIED, S.SHORTLISTED, S.INTERVIEW_SCHEDULED, S.SELECTED, S.MD_ROUND):
        check(f"{src.value} can always be rejected", M.can_transition(src, S.REJECTED))
        check(f"{src.value} can always be held", M.can_transition(src, S.ON_HOLD))
    for terminal in M.TERMINAL_STATUSES:
        check(f"{terminal.value} is terminal (no moves out)",
              M.allowed_next_statuses(terminal) == set())
    check("On Hold can be revived", M.can_transition(S.ON_HOLD, S.SHORTLISTED))
    check("Rejected can be reopened", M.can_transition(S.REJECTED, S.UNDER_REVIEW))
    check("a status is never a transition to itself",
          all(s not in M.allowed_next_statuses(s) for s in S))
    check("an unknown target is refused", not M.can_transition(S.APPLIED, "Promoted"))
    check("every status appears in exactly one pipeline column",
          sum(len(ss) for _k, _l, ss in M.PIPELINE_COLUMNS) == len(list(S)))

    # =================================================================
    # Wire fakes
    # =================================================================
    U_HR, U_HOD, U_EMP, U_OTHER = (str(ObjectId()) for _ in range(4))

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "company_id": COMPANY,
         "email": "hr@c1.com", "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "company_id": COMPANY,
         "email": "hod@c1.com", "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_OTHER), "full_name": "Otto Other", "company_id": "C2",
         "email": "o@c2.com", "role": "clientuser"},
    ])
    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_HOD, "jd_no": "JD-2026-001", "designation_name": "Analyst"},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "created_by": U_HR, "jd_no": "JD-2026-002", "designation_name": "Manager"},
    ])
    candidates = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {"learners": learners, M.COLL_REQUISITIONS: reqs,
             M.COLL_CANDIDATES: candidates, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, "hrms_job_postings": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_candidate_service as CS
    import app.services.hrms_audit_service as AS
    import app.services.hrms_id_service as IS
    for mod in (CS, AS, IS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify(uid, title, msg, **kw):
        sent.append((str(uid), title))

    CS.notify_user = fake_notify

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}

    try:
        from app.utils import hrms_access as A
        section("Capability matrix (Phase 5)")
        check("HR can screen", A.can(HR, M.Cap.CANDIDATE_SCREEN))
        check("HOD can read", A.can(HOD, M.Cap.CANDIDATE_READ))
        check("HOD CANNOT write", not A.can(HOD, M.Cap.CANDIDATE_WRITE))
        check("HOD CANNOT screen", not A.can(HOD, M.Cap.CANDIDATE_SCREEN))
        check("employee CANNOT read candidates", not A.can(EMP, M.Cap.CANDIDATE_READ))
        # Screening is a hiring decision -- the same boundary Phase 3 drew for approvals.
        check("INTERNAL can read+write but NOT screen",
              A.can(INTERNAL, M.Cap.CANDIDATE_READ) and A.can(INTERNAL, M.Cap.CANDIDATE_WRITE)
              and not A.can(INTERNAL, M.Cap.CANDIDATE_SCREEN))

        # =================================================================
        section("Manual candidate creation")
        # =================================================================
        c1 = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Asha Rao", "can_email": "Asha@Example.com",
            "can_contact": "9876543210", "request_no": "HR-REQ-2026-001",
            "source": "Referral"})
        check("candidate created", c1["uk"].startswith("CAN-"))
        check("starts at Applied", c1["application_status"] == S.APPLIED.value)
        check("email lowercased", c1["can_email"] == "asha@example.com")
        check("linked to the requisition's JD", c1["jd_no"] == "JD-2026-001")
        check("allowed_next returned for the UI", "Shortlisted" in c1["allowed_next"])
        check("creation audited",
              any(a["action"] == M.AUDIT_CANDIDATE_ADDED for a in audit_log.docs))

        await expect_http("no name", CS.create_candidate(HR, COMPANY, {"candidate_name": " "}),
                          422, "name is required")
        await expect_http("neither email nor phone", CS.create_candidate(
            HR, COMPANY, {"candidate_name": "X"}), 422, "at least an email")
        await expect_http("bad email", CS.create_candidate(
            HR, COMPANY, {"candidate_name": "X", "can_email": "nope"}), 422, "valid email")
        await expect_http("bad phone", CS.create_candidate(
            HR, COMPANY, {"candidate_name": "X", "can_contact": "abc"}), 422, "valid phone")
        await expect_http("requisition from another company", CS.create_candidate(
            HR, COMPANY, {"candidate_name": "X", "can_contact": "9000000000",
                          "request_no": "HR-REQ-9999"}), 422, "does not exist")

        # =================================================================
        section("Stage moves are validated, not assigned")
        # =================================================================
        uk = c1["uk"]
        moved = await CS.update_candidate(HR, COMPANY, uk,
                                          {"application_status": S.SHORTLISTED.value})
        check("legal move applied", moved["application_status"] == S.SHORTLISTED.value)
        check("stage change gets its own audit line",
              any(a["action"] == M.AUDIT_STAGE_CHANGED for a in audit_log.docs))
        check("audit records both ends",
              any("Applied -> Shortlisted" in (a.get("detail") or "") for a in audit_log.docs))

        await expect_http("illegal jump to Joined", CS.update_candidate(
            HR, COMPANY, uk, {"application_status": S.JOINED.value}), 409, "cannot move")
        await expect_http("the 409 lists what IS allowed", CS.update_candidate(
            HR, COMPANY, uk, {"application_status": S.EMPLOYEE_CREATED.value}),
            409, "allowed from here")

        # Terminal really is terminal, even for HR.
        term = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Term Inal", "can_contact": "9000000009"})
        await candidates.update_one({"uk": term["uk"]},
                                    {"$set": {"application_status": S.EMPLOYEE_CREATED.value}})
        await expect_http("no move out of a terminal stage", CS.update_candidate(
            HR, COMPANY, term["uk"], {"application_status": S.REJECTED.value}), 409)

        section("Other edits")
        edited = await CS.update_candidate(HR, COMPANY, uk, {"notice_period": "30 days"})
        check("field edit applied", edited["notice_period"] == "30 days")
        await expect_http("no fields", CS.update_candidate(HR, COMPANY, uk, {}), 400)
        await expect_http("bad email on edit", CS.update_candidate(
            HR, COMPANY, uk, {"can_email": "bad"}), 422)
        assigned = await CS.update_candidate(HR, COMPANY, uk,
                                             {"assigned_recruiter_id": U_HOD})
        check("recruiter assigned", assigned["assigned_recruiter_name"] == "Hari HOD")
        check("assignee notified", any(s[0] == U_HOD for s in sent))
        await expect_http("recruiter from another company", CS.update_candidate(
            HR, COMPANY, uk, {"assigned_recruiter_id": U_OTHER}), 422, "user of this company")

        # =================================================================
        section("Row scoping")
        # =================================================================
        # HOD raised HR-REQ-2026-001 only.
        c_other_req = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Bob Beta", "can_contact": "9000000001",
            "request_no": "HR-REQ-2026-002"})
        hod_view = await CS.list_candidates(HOD, COMPANY)
        visible = {c["uk"] for c in hod_view["candidates"]}
        check("HOD sees candidates on their own requisition", uk in visible)
        check("HOD does NOT see another manager's requisition",
              c_other_req["uk"] not in visible)
        check("HOD column counts match their scope",
              sum(col["count"] for col in hod_view["columns"]) == hod_view["total"])

        hr_view = await CS.list_candidates(HR, COMPANY)
        check("HR sees the whole company", hr_view["total"] > hod_view["total"])
        await expect_http("HOD cannot open an out-of-scope candidate (404, not 403)",
                          CS.get_candidate(HOD, COMPANY, c_other_req["uk"]), 404)
        await expect_http("cross-tenant read is 404",
                          CS.get_candidate(HR, "C2", uk), 404)

        section("Search and filters")
        found = await CS.list_candidates(HR, COMPANY, search="Asha")
        check("search by name", any(c["uk"] == uk for c in found["candidates"]))
        safe = await CS.list_candidates(HR, COMPANY, search="Asha(")
        check("regex metacharacters escaped", safe["total"] == 0)
        by_req = await CS.list_candidates(HR, COMPANY, request_no="HR-REQ-2026-002")
        check("requisition filter applied",
              all(c["request_no"] == "HR-REQ-2026-002" for c in by_req["candidates"]))

        section("Duplicate flagging")
        await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Asha Rao (again)", "can_email": "asha@example.com",
            "can_contact": "9111111111"})
        listing = await CS.list_candidates(HR, COMPANY)
        dupes = [c for c in listing["candidates"] if c.get("duplicate_flag")]
        check("shared email flags BOTH records", len(dupes) >= 2)
        check("flagging is advisory only -- nothing was merged or deleted",
              len([c for c in listing["candidates"] if c["can_email"] == "asha@example.com"]) == 2)
        # Phone comparison ignores formatting.
        await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Formatted", "can_contact": "+91 98765 43210"})
        listing = await CS.list_candidates(HR, COMPANY)
        check("phone duplicates match despite formatting",
              any(c["candidate_name"] == "Formatted" and c.get("duplicate_flag")
                  for c in listing["candidates"]))

        # =================================================================
        section("Screening")
        # =================================================================
        a = await CS.create_candidate(HR, COMPANY, {"candidate_name": "S One", "can_contact": "9000001111"})
        b = await CS.create_candidate(HR, COMPANY, {"candidate_name": "S Two", "can_contact": "9000002222"})
        res = await CS.screen_candidates(HR, COMPANY, {
            "uks": [a["uk"], b["uk"]], "action": "shortlist"})
        check("bulk shortlist moved both", res["moved_count"] == 2)
        check("nothing skipped", res["skipped_count"] == 0)
        check("both are Shortlisted",
              all(m["status"] == S.SHORTLISTED.value for m in res["moved"]))

        # Assessment-aware routing -- the whole reason Phase 4 copies the flag onto the
        # candidate at apply time.
        need = await CS.create_candidate(HR, COMPANY, {"candidate_name": "Needs Test", "can_contact": "9000003333"})
        await candidates.update_one({"uk": need["uk"]}, {"$set": {"requires_assessment": True}})
        res = await CS.screen_candidates(HR, COMPANY, {"uks": [need["uk"]], "action": "shortlist"})
        check("an assessment-required candidate routes to Assessment Pending",
              res["moved"][0]["status"] == S.ASSESSMENT_PENDING.value)
        journey_rows = [x for x in audit_log.docs if x["entity_id"] == need["uk"]
                        and x["action"] == M.AUDIT_STAGE_CHANGED]
        check("the intermediate Shortlisted hop is recorded, so history stays legal",
              len(journey_rows) == 2)

        section("Screening: partial success")
        done = await CS.create_candidate(HR, COMPANY, {"candidate_name": "Done", "can_contact": "9000004444"})
        await candidates.update_one({"uk": done["uk"]},
                                    {"$set": {"application_status": S.EMPLOYEE_CREATED.value}})
        res = await CS.screen_candidates(HR, COMPANY, {
            "uks": [a["uk"], done["uk"], "CAN-NOPE"], "action": "hold"})
        check("the movable candidate moved", res["moved_count"] == 1)
        check("the terminal and missing ones are skipped, not fatal", res["skipped_count"] == 2)
        check("each skip explains itself",
              all(s.get("reason") for s in res["skipped"]))
        check("a missing candidate is reported as not found",
              any(s["reason"] == "not found" for s in res["skipped"]))
        res = await CS.screen_candidates(HR, COMPANY, {"uks": [a["uk"]], "action": "hold"})
        check("re-applying the same action is reported as already-there",
              res["skipped"][0]["reason"].startswith("already"))

        section("Screening: validation")
        await expect_http("no candidates selected", CS.screen_candidates(
            HR, COMPANY, {"uks": [], "action": "hold"}), 422, "at least one")
        await expect_http("over the bulk cap", CS.screen_candidates(
            HR, COMPANY, {"uks": ["x"] * (M.MAX_BULK_SCREEN + 1), "action": "hold"}),
            422, "at most")
        await expect_http("unknown action", CS.screen_candidates(
            HR, COMPANY, {"uks": [b["uk"]], "action": "banish"}), 422, "Invalid action")
        await expect_http("reject with no reason", CS.screen_candidates(
            HR, COMPANY, {"uks": [b["uk"]], "action": "reject"}), 422, "reason is required")
        await expect_http("forward with no recipient", CS.screen_candidates(
            HR, COMPANY, {"uks": [b["uk"]], "action": "forward"}), 422, "who to forward")
        await expect_http("forward to another company's user", CS.screen_candidates(
            HR, COMPANY, {"uks": [b["uk"]], "action": "forward", "forward_to_id": U_OTHER}),
            422, "your own company")

        section("Screening: forward assigns, it does not move")
        before = (await CS.get_candidate(HR, COMPANY, b["uk"]))["application_status"]
        res = await CS.screen_candidates(HR, COMPANY, {
            "uks": [b["uk"]], "action": "forward", "forward_to_id": U_HOD,
            "remarks": "please review"})
        after = await CS.get_candidate(HR, COMPANY, b["uk"])
        check("stage is unchanged by a forward", after["application_status"] == before)
        check("owner assigned", after["assigned_recruiter_name"] == "Hari HOD")
        check("recipient notified", any(s[0] == U_HOD for s in sent))

        section("Screening: reject with a reason")
        res = await CS.screen_candidates(HR, COMPANY, {
            "uks": [b["uk"]], "action": "reject", "remarks": "Not enough experience"})
        rejected = await CS.get_candidate(HR, COMPANY, b["uk"])
        check("rejected", rejected["application_status"] == S.REJECTED.value)
        check("reason stored", rejected["screening_remarks"] == "Not enough experience")
        check("reason captured in the audit trail",
              any("Not enough experience" in (x.get("detail") or "") for x in audit_log.docs))

        section("Screening respects row scoping")
        res = await CS.screen_candidates(HR, COMPANY, {
            "uks": [c_other_req["uk"]], "action": "hold"})
        check("HR can screen any candidate in the company", res["moved_count"] == 1)

        # =================================================================
        section("Delete guards")
        # =================================================================
        gone = await CS.delete_candidate(HR, COMPANY, a["uk"])
        check("deletable while early in the pipeline", gone["deleted"] is True)
        check("delete audited",
              any(x["action"] == M.AUDIT_CANDIDATE_DELETED for x in audit_log.docs))
        hired = await CS.create_candidate(HR, COMPANY, {"candidate_name": "Hired", "can_contact": "9000005555"})
        await candidates.update_one({"uk": hired["uk"]},
                                    {"$set": {"application_status": S.JOINED.value}})
        await expect_http("a joined candidate cannot be deleted", CS.delete_candidate(
            HR, COMPANY, hired["uk"]), 409, "hiring history")
        await expect_http("deleting a missing candidate", CS.delete_candidate(
            HR, COMPANY, "CAN-NOPE"), 404)

        # =================================================================
        section("Journey (reconstructed from the audit trail)")
        # =================================================================
        j = await CS.get_journey(HR, COMPANY, uk)
        check("candidate summary returned", j["candidate"]["uk"] == uk)
        check("rail has 7 steps", len(j["rail"]) == 7)
        check("events came from the audit log", len(j["events"]) > 0)
        check("every event has a colour kind", all(e.get("kind") for e in j["events"]))
        check("stage changes are coloured by the stage ARRIVED at",
              any(e["kind"] == "success" for e in j["events"]))
        check("rail marks reached steps",
              any(step["reached"] for step in j["rail"]))
        check("not terminal while mid-pipeline", j["terminal"] is False)

        jt = await CS.get_journey(HR, COMPANY, term["uk"])
        # Phase INT-15 gave `Employee Created` one onward edge (probation confirmation), so
        # a hire is never the last stop -- even one with no requisition at all.
        check("a hire with no requisition is NOT terminal -- probation confirmation is still to come",
              jt["terminal"] is False)
        await candidates.update_one(
            {"uk": term["uk"]},
            {"$set": {"application_status": S.PROBATION_CONFIRMED.value}})
        jt2 = await CS.get_journey(HR, COMPANY, term["uk"])
        check("and so is a confirmed hire", jt2["terminal"] is True)

        # A candidate with no audit history must still render a timeline.
        bare = await candidates.insert_one({
            "uk": "CAN-BARE", "company_id": COMPANY, "candidate_name": "Bare",
            "application_status": S.APPLIED.value, "source": "Import"})
        jb = await CS.get_journey(HR, COMPANY, "CAN-BARE")
        check("a candidate with no audit rows still gets a start anchor",
              len(jb["events"]) == 1 and jb["events"][0]["kind"] == "applied")

        await expect_http("journey respects row scoping",
                          CS.get_journey(HOD, COMPANY, c_other_req["uk"]), 404)

        section("Identity collections still never written")
        check("learners untouched",
              all("application_status" not in d and "uk" not in d for d in learners.docs))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
