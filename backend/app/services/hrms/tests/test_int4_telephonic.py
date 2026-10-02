"""Phase INT-4 -- telephonic screening (SOP step 5, Annexure B "Telephonic screening").

The one stage in the SOP's process flow that had no code at all. Covers the record, the
scoring, the status moves and -- the part that makes it a control rather than a form -- the
gate on interview scheduling.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. THE CLIENT TRACK IS UNTOUCHED. The gate returns early on a client requisition, and the
     Shortlisted -> Interview edge it used before still exists.
  2. RECORDED IS NOT CLEARED. A `No Answer` screen is a real record of a real attempt and
     opens nothing, exactly as an "Unable to Verify" reference does not open the offer gate.
  3. THE FUNNEL STAYS MONOTONIC. Both new statuses rank 2, WITH Shortlisted -- a phone screen
     is a decision about a shortlisted candidate, not a further stage.
  4. AN IN-FLIGHT CANDIDATE IS NOT GATED RETROACTIVELY. Somebody already being interviewed
     when this shipped cannot be stranded behind a call nobody can go back and make.
  5. A MISSING RATING IS NOT A ZERO. The score re-normalises over what was actually rated.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int4_telephonic   (from backend/)
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
REQ_INT = "HR-REQ-2026-001"      # internal
REQ_CLI = "HR-REQ-2026-002"      # client
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    HR = {"_id": ObjectId(), "full_name": "Priya HR", "email": "hr@example.com"}

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_telephonic_service as TEL
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (TEL, AUD, IDS):
        mod.get_collection = mongo.get_collection

    seq = {"n": 0}

    async def fake_id(kind, company_id, year=None):
        seq["n"] += 1
        return f"TEL-2026-{seq['n']:03d}"

    TEL.next_business_id = fake_id

    reqs = store.setdefault(M.COLL_REQUISITIONS, FakeCollection())
    reqs.docs.extend([
        {"request_no": REQ_INT, "company_id": COMPANY, "designation_name": "Ops Executive",
         "requisition_track": "internal"},
        # No `requisition_track` key at all -- the pre-internal shape, which `track_of`
        # must keep reading as the client track.
        {"request_no": REQ_CLI, "company_id": COMPANY, "designation_name": "Analyst"},
    ])

    candidates = store.setdefault(M.COLL_CANDIDATES, FakeCollection())

    def add_candidate(uk, request_no, status=M.AppStatus.SHORTLISTED.value):
        candidates.docs.append({
            "uk": uk, "company_id": COMPANY, "candidate_name": f"Candidate {uk}",
            "request_no": request_no, "application_status": status,
            "can_contact": "+91 00000 00001"})

    for n in range(1, 9):
        add_candidate(f"CAN-00{n}", REQ_INT)
    add_candidate("CAN-C01", REQ_CLI)

    # =========================================================================
    section("1. The status graph -- additive, ranked WITH Shortlisted")
    # =========================================================================
    check("both statuses exist",
          M.AppStatus.TELEPHONIC_PASSED.value == "Telephonic Passed"
          and M.AppStatus.TELEPHONIC_REJECTED.value == "Telephonic Rejected")
    check("EVERY AppStatus has a STAGE_RANK -- an unranked status is counted in totals and "
          "credited to no funnel stage",
          all(s in M.STAGE_RANK for s in M.AppStatus))
    check("both rank 2, WITH Shortlisted",
          M.STAGE_RANK[M.AppStatus.TELEPHONIC_PASSED] == 2
          and M.STAGE_RANK[M.AppStatus.TELEPHONIC_REJECTED] == 2
          and M.STAGE_RANK[M.AppStatus.SHORTLISTED] == 2)
    check("they do NOT out-rank assessment, so the funnel stays monotonic",
          M.STAGE_RANK[M.AppStatus.TELEPHONIC_PASSED]
          < M.STAGE_RANK[M.AppStatus.ASSESSMENT_PENDING])
    check("Shortlisted -> Telephonic Passed is legal",
          M.can_transition(M.AppStatus.SHORTLISTED, M.AppStatus.TELEPHONIC_PASSED))
    check("Telephonic Passed -> Interview is legal",
          M.can_transition(M.AppStatus.TELEPHONIC_PASSED, M.AppStatus.INTERVIEW_SCHEDULED))
    check("Telephonic Passed -> Assessment is legal (Annexure B puts the test after the call)",
          M.can_transition(M.AppStatus.TELEPHONIC_PASSED, M.AppStatus.ASSESSMENT_PENDING))
    check("Telephonic Rejected is REVIVABLE, not a dead end",
          M.can_transition(M.AppStatus.TELEPHONIC_REJECTED, M.AppStatus.UNDER_REVIEW))
    check("the DIRECT Shortlisted -> Interview edge still exists -- the client track is not "
          "forced through a phone screen by the shape of the graph",
          M.can_transition(M.AppStatus.SHORTLISTED, M.AppStatus.INTERVIEW_SCHEDULED))
    check("neither new status is terminal",
          M.AppStatus.TELEPHONIC_PASSED not in M.TERMINAL_STATUSES
          and M.AppStatus.TELEPHONIC_REJECTED not in M.TERMINAL_STATUSES)

    # =========================================================================
    section("2. Recording a call, and what it moves")
    # =========================================================================
    rec = await TEL.create_screening(HR, COMPANY, {
        "uk": "CAN-001", "notice_period_days": 30, "expected_ctc": 600000,
        "current_location": "Pune", "availability": "Immediate",
        "communication": 4, "role_understanding": 4, "motivation": 4, "suitability": 4,
        "outcome": "Passed", "comments": "Strong on process detail.", "duration_minutes": 12,
    })
    check("a business id was minted", rec["tel_no"] == "TEL-2026-001")
    check("request_no is carried, so the analytics scope filter reaches this collection",
          rec["request_no"] == REQ_INT)
    check("uk is carried too", rec["uk"] == "CAN-001")
    check("the caller is recorded", rec["screened_by_name"] == "Priya HR")
    check("a retention floor was stamped", bool(rec["retention_until"]))
    check("retention is ONE year -- candidate data, not employee data",
          rec["retention_until"].startswith(str(int(TODAY[:4]) + 1)))
    check("all four ratings equal 4.0 -> score 4.0", rec["score"] == 4.0)
    check("the band is SURFACED using the same score_band() the scorecard uses",
          rec["band"] == "Strong")
    moved = await candidates.find_one({"uk": "CAN-001"})
    check("a passed call moves the candidate to Telephonic Passed",
          moved["application_status"] == M.AppStatus.TELEPHONIC_PASSED.value)
    check("the move is reported back to the caller",
          rec["candidate_moved_to"] == M.AppStatus.TELEPHONIC_PASSED.value)
    check("the act was audited",
          any(r.get("action") == M.AUDIT_TELEPHONIC_RECORDED
              for r in store[M.COLL_AUDIT_LOG].docs))

    rej = await TEL.create_screening(HR, COMPANY, {
        "uk": "CAN-002", "outcome": "Rejected",
        "comments": "Wants a client-facing role; this one is back office."})
    check("a rejected call moves the candidate to Telephonic Rejected",
          (await candidates.find_one({"uk": "CAN-002"}))["application_status"]
          == M.AppStatus.TELEPHONIC_REJECTED.value)
    check("an unrated screen scores None, not 0.0 -- no score is honest, zero is not",
          rej["score"] is None and rej["band"] is None)

    noans = await TEL.create_screening(HR, COMPANY, {
        "uk": "CAN-003", "outcome": "No Answer"})
    check("a No Answer screen is RECORDED", noans["tel_no"] == "TEL-2026-003")
    check("but it moves the candidate NOWHERE -- a call nobody picked up has decided nothing",
          (await candidates.find_one({"uk": "CAN-003"}))["application_status"]
          == M.AppStatus.SHORTLISTED.value
          and noans["candidate_moved_to"] is None)

    # =========================================================================
    section("3. Validation")
    # =========================================================================
    await expect_http("no candidate",
                      TEL.create_screening(HR, COMPANY, {"uk": ""}), 422, "select a candidate")
    await expect_http("unknown candidate",
                      TEL.create_screening(HR, COMPANY, {"uk": "CAN-NOPE"}), 404)
    await expect_http("a rejection with no note",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "outcome": "Rejected"}),
                      422, "record why")
    await expect_http("a rating above the scale",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "communication": 7}),
                      422, "between 1 and 5")
    await expect_http("a rating below the scale",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "communication": 0}),
                      422, "between 1 and 5")
    await expect_http("a future screening date",
                      TEL.create_screening(
                          HR, COMPANY,
                          {"uk": "CAN-004",
                           "screened_on": (datetime.now(timezone.utc)
                                           + timedelta(days=2)).strftime("%Y-%m-%d")}),
                      422, "future")
    await expect_http("a negative notice period",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "notice_period_days": -5}),
                      422, "negative")
    await expect_http("a three-hour 'brief call'",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "duration_minutes": 400}),
                      422, "panel interview")
    await expect_http("an unknown outcome",
                      TEL.create_screening(HR, COMPANY,
                                           {"uk": "CAN-004", "outcome": "Maybe"}),
                      422, "outcome must be one of")
    check("none of the refusals left a record behind",
          len(store[M.COLL_TELEPHONIC].docs) == 3)

    # =========================================================================
    section("4. Scoring -- weighted, and re-normalised over what was rated")
    # =========================================================================
    check("the weights sum to 1.0",
          round(sum(w for _, _, w in M.TELEPHONIC_CRITERIA), 6) == 1.0)
    partial = await TEL.create_screening(HR, COMPANY, {
        "uk": "CAN-004", "communication": 5, "role_understanding": 3, "outcome": "Passed"})
    # 0.30 and 0.30 re-normalise to 0.5 each -> (5 + 3) / 2 = 4.0
    check("two rated dimensions score over THOSE dimensions, not out of four -- a blank is "
          "missing information, not a zero", partial["score"] == 4.0)
    weighted = await TEL.create_screening(HR, COMPANY, {
        "uk": "CAN-005", "communication": 5, "role_understanding": 5,
        "motivation": 1, "suitability": 1, "outcome": "Passed"})
    check("understanding the role outweighs sounding motivated (0.30+0.30 vs 0.20+0.20)",
          weighted["score"] == 3.4)
    check("3.4 bands as Hold, not Strong -- read from the SAME four-band table the "
          "position scorecard uses", weighted["band"] == "Hold"
          and M.score_band(3.4) == "Hold")

    # =========================================================================
    section("5. Editing rescores, and can move the candidate")
    # =========================================================================
    edited = await TEL.update_screening(HR, COMPANY, "TEL-2026-004", {"motivation": 5})
    check("editing one rating rescores the whole screen",
          edited["score"] != partial["score"])
    check("and rebands it from the new score",
          edited["band"] == M.score_band(edited["score"]))
    await expect_http("flipping to Rejected with no note",
                      TEL.update_screening(HR, COMPANY, "TEL-2026-003",
                                           {"outcome": "Rejected"}),
                      422, "record why")
    flipped = await TEL.update_screening(HR, COMPANY, "TEL-2026-003",
                                        {"outcome": "Passed"})
    check("a No Answer upgraded to Passed moves the candidate",
          flipped["candidate_moved_to"] == M.AppStatus.TELEPHONIC_PASSED.value
          and (await candidates.find_one({"uk": "CAN-003"}))["application_status"]
          == M.AppStatus.TELEPHONIC_PASSED.value)
    await expect_http("editing a screening that does not exist",
                      TEL.update_screening(HR, COMPANY, "TEL-9999", {"motivation": 3}), 404)

    # =========================================================================
    section("6. Several calls per candidate, and the clearance read")
    # =========================================================================
    await TEL.create_screening(HR, COMPANY, {"uk": "CAN-006", "outcome": "No Answer"})
    check("no clearance from a No Answer",
          await TEL.clearing_screening(COMPANY, "CAN-006") is None)
    await TEL.create_screening(HR, COMPANY, {"uk": "CAN-006", "outcome": "No Answer"})
    await TEL.create_screening(HR, COMPANY, {"uk": "CAN-006", "outcome": "Passed"})
    cleared = await TEL.clearing_screening(COMPANY, "CAN-006")
    check("a third attempt that PASSES clears the candidate", cleared is not None)
    listing = await TEL.list_screenings(HR, COMPANY, uk="CAN-006")
    check("all three attempts are kept -- which is what shows how much chasing a hire took",
          listing["total"] == 3)
    check("the outstanding-attempt count is surfaced",
          listing["awaiting_retry"] == 2)
    check("TELEPHONIC_CLEARS_INTERVIEW is Passed alone",
          M.TELEPHONIC_CLEARS_INTERVIEW == {"Passed"})

    # =========================================================================
    section("7. THE GATE on interview scheduling")
    # =========================================================================
    interviews = store.setdefault(M.COLL_INTERVIEWS, FakeCollection())
    req_int = await reqs.find_one({"request_no": REQ_INT})
    req_cli = await reqs.find_one({"request_no": REQ_CLI})

    # -- The client track is silent, at every candidate state --
    cand_cli = await candidates.find_one({"uk": "CAN-C01"})
    await TEL.assert_telephonic_cleared(COMPANY, cand_cli, req_cli)
    check("the gate is SILENT on a client requisition -- no screen, no refusal", True)
    await TEL.assert_telephonic_cleared(COMPANY, cand_cli, {})
    check("and silent on a requisition with NO track field at all (the pre-internal shape)",
          True)

    # -- The internal track refuses --
    cand_007 = await candidates.find_one({"uk": "CAN-007"})
    await expect_http(
        "an internal candidate with no screening at all",
        TEL.assert_telephonic_cleared(COMPANY, cand_007, req_int), 409, "no telephonic")

    cand_002 = await candidates.find_one({"uk": "CAN-002"})
    await expect_http(
        "an internal candidate whose only screening was REJECTED",
        TEL.assert_telephonic_cleared(COMPANY, cand_002, req_int), 409, "none of which passed")

    # -- A passing screen opens it --
    cand_001 = await candidates.find_one({"uk": "CAN-001"})
    await TEL.assert_telephonic_cleared(COMPANY, cand_001, req_int)
    check("a passing screen opens the gate", True)

    # -- An approved exception opens it, and nothing else does --
    excs = store.setdefault(M.COLL_EXCEPTIONS, FakeCollection())
    check("the gate has an exception type of its own",
          M.EXCEPTION_UNBLOCKS["telephonic"] == M.ExceptionType.TELEPHONIC_WAIVED.value)
    excs.docs.append({
        "exc_no": "EXC-2026-001", "company_id": COMPANY, "request_no": REQ_INT,
        "uk": "CAN-007", "exception_type": M.ExceptionType.TELEPHONIC_WAIVED.value,
        "status": M.ExceptionStatus.PENDING.value})
    await expect_http(
        "a PENDING exception does not open the gate",
        TEL.assert_telephonic_cleared(COMPANY, cand_007, req_int), 409)
    await excs.update_one({"exc_no": "EXC-2026-001"},
                          {"$set": {"status": M.ExceptionStatus.APPROVED.value}})
    await TEL.assert_telephonic_cleared(COMPANY, cand_007, req_int)
    check("an APPROVED exception opens it -- the only sanctioned bypass on this track", True)

    cand_008 = await candidates.find_one({"uk": "CAN-008"})
    await expect_http(
        "and it does NOT leak to the next candidate on the same requisition",
        TEL.assert_telephonic_cleared(COMPANY, cand_008, req_int), 409)

    # -- An in-flight candidate is not gated retroactively --
    interviews.docs.append({"interview_no": "INT-2026-001", "company_id": COMPANY,
                            "uk": "CAN-008", "request_no": REQ_INT})
    await TEL.assert_telephonic_cleared(COMPANY, cand_008, req_int)
    check("a candidate ALREADY being interviewed is not gated -- shipping this phase cannot "
          "strand somebody behind a call nobody can go back and make", True)

    # -- Structural: no override flag anywhere --
    import inspect
    source = inspect.getsource(TEL)
    check("the service accepts no override/force/skip flag -- an approved record is the only "
          "bypass",
          not any(tok in source for tok in ("force=", "override=", "skip_gate")))

    # =========================================================================
    section("8. The work queue is internal-track only")
    # =========================================================================
    queue = await TEL.screenable_candidates(HR, COMPANY)
    ukeys = {r["uk"] for r in queue}
    check("the client-track candidate is absent -- the client process has no phone-screen "
          "step, and offering one invites a record nothing gates on",
          "CAN-C01" not in ukeys)
    check("candidates already cleared by a call are absent",
          "CAN-001" not in ukeys and "CAN-006" not in ukeys)
    check("a shortlisted, unscreened internal candidate is present", "CAN-007" in ukeys)
    check("attempt counts are carried so repeat chasing is visible",
          all("attempts" in r for r in queue))

    # -- Fails closed when there are no internal requisitions at all --
    saved = list(reqs.docs)
    reqs.docs[:] = [r for r in saved
                    if r.get("requisition_track") != "internal"]
    check("no internal requisitions -> an empty queue, never every candidate",
          await TEL.screenable_candidates(HR, COMPANY) == [])
    reqs.docs[:] = saved

    # =========================================================================
    section("9. Capabilities follow Annexure B")
    # =========================================================================
    R = M.ROLE_CAPABILITIES
    check('HR is "R" on telephonic screening -> holds WRITE',
          M.Cap.TELEPHONIC_WRITE in R[M.HrmsRole.HR])
    check('the HOD is "I" -> READ but NOT write',
          M.Cap.TELEPHONIC_READ in R[M.HrmsRole.MANAGER]
          and M.Cap.TELEPHONIC_WRITE not in R[M.HrmsRole.MANAGER])
    check("the MD holds both -- a governance chain whose top authority cannot act is a trap",
          M.Cap.TELEPHONIC_READ in R[M.HrmsRole.MD]
          and M.Cap.TELEPHONIC_WRITE in R[M.HrmsRole.MD])
    check("Sparsh staff (INTERNAL) read but never record -- they support the hiring, they do "
          "not run it",
          M.Cap.TELEPHONIC_READ in R[M.HrmsRole.INTERNAL]
          and M.Cap.TELEPHONIC_WRITE not in R[M.HrmsRole.INTERNAL])
    check("FINANCE holds NEITHER -- it approves what a role costs, never who fills it, and "
          "this is candidate-level hiring detail (the same call reference checks made)",
          M.Cap.TELEPHONIC_READ not in R[M.HrmsRole.FINANCE]
          and M.Cap.TELEPHONIC_READ not in R[M.HrmsRole.EMPLOYEE])

    # =========================================================================
    section("10. Retention and the purge")
    # =========================================================================
    check("a retention period is declared", M.RETENTION_YEARS["telephonic"] == 1)
    target = next((t for t in M.PURGE_TARGETS if t[0] == M.COLL_TELEPHONIC), None)
    check("the collection is a purge target", target is not None)
    check("it REDACTS rather than deletes", target[1] == "tel_no"
          and target[3] == M.PURGE_REDACT)
    check("what the candidate said about money and notice is among the redacted fields",
          "expected_ctc" in target[4] and "comments" in target[4])
    check("indexes are declared, and NOT unique per candidate (a second call is normal)",
          any(c == M.COLL_TELEPHONIC for c, _, _ in M.HRMS_INDEXES)
          and not any(c == M.COLL_TELEPHONIC and k == [("company_id", 1), ("uk", 1)]
                      and o.get("unique") for c, k, o in M.HRMS_INDEXES))

    # =========================================================================
    section("11. The interview service actually calls the gate")
    # =========================================================================
    import app.services.hrms_interview_service as IV
    iv_source = inspect.getsource(IV)
    check("hrms_interview_service imports and calls assert_telephonic_cleared -- without "
          "this the stage is a form, not a control",
          "assert_telephonic_cleared" in iv_source)
    check("and it is inside the internal-track branch, so the client path never reaches it",
          iv_source.index("assert_telephonic_cleared")
          > iv_source.index("if _is_internal(req):"))

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
