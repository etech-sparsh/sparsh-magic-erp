"""Final Commit -- the committee's decision, derived rather than chosen.

The stage the SOP puts after the interviews and before an offer. Three outcomes, and the
whole point of this phase is that NOBODY PICKS THEM. They follow from two facts the system
already holds: what each approver said, and how senior the role is.

  * HR and the Department Head both approve        -> Selected
  * either one does not approve                    -> Rejected
  * managerial or above, final round not yet passed -> Final Interview Required

The properties worth testing hardest:

  1. A sitting cannot be recorded as Selected over an objection. Before this phase the
     outcome was free text from a dropdown, so "Finalised" could be written on a sitting the
     Department Head had objected to and nothing would contradict it.
  2. A managerial commit routes to the final interview rather than selecting -- and, once
     that round is passed, the SAME sitting clears the selection gate. Getting this wrong
     strands every senior hire one step short of an offer, which is the trap
     SHORTLIST_CLEARS_SELECTION documents.
  3. A recused member is not an approver. Their objection must not reject the sitting they
     stood down from.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_final_commit   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
NOW = datetime.now(timezone.utc)


def pure_matrix() -> None:
    """The rule on its own, with no database anywhere near it."""
    from app.models.hrms import (
        DesignationLevel, ShortlistOutcome, final_commit_outcome,
    )
    agree = [{"role": "hr", "decision": "Agree"},
             {"role": "manager", "decision": "Agree"}]
    hr_objects = [{"role": "hr", "decision": "Object"},
                  {"role": "manager", "decision": "Agree"}]
    hod_objects = [{"role": "hr", "decision": "Agree"},
                   {"role": "manager", "decision": "Object"}]
    recused_objector = [{"role": "hr", "decision": "Agree"},
                        {"role": "manager", "decision": "Object", "recused": True}]

    section("The rule itself -- pure, no I/O")
    for level in (DesignationLevel.JUNIOR, DesignationLevel.MID):
        check(f"{level.value}: both approve -> Selected",
              final_commit_outcome(agree, level=level) is ShortlistOutcome.SELECTED)
    for level in (DesignationLevel.SENIOR, DesignationLevel.MANAGERIAL):
        check(f"{level.value}: both approve -> Final Interview Required",
              final_commit_outcome(agree, level=level)
              is ShortlistOutcome.FINAL_INTERVIEW_REQUIRED)
        check(f"{level.value}: round already passed -> Selected",
              final_commit_outcome(agree, level=level, final_round_passed=True)
              is ShortlistOutcome.SELECTED)

    check("HR does not approve -> Rejected",
          final_commit_outcome(hr_objects, level=DesignationLevel.JUNIOR)
          is ShortlistOutcome.REJECTED)
    check("the Department Head does not approve -> Rejected",
          final_commit_outcome(hod_objects, level=DesignationLevel.JUNIOR)
          is ShortlistOutcome.REJECTED)
    check("an objection outranks seniority (managerial + object -> Rejected)",
          final_commit_outcome(hod_objects, level=DesignationLevel.MANAGERIAL)
          is ShortlistOutcome.REJECTED)
    check("a RECUSED member's objection does not reject the sitting",
          final_commit_outcome(recused_objector, level=DesignationLevel.JUNIOR)
          is ShortlistOutcome.SELECTED)
    check("an unbanded role falls back to the default band, not a crash",
          final_commit_outcome(agree, level=None) in tuple(ShortlistOutcome))


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    pure_matrix()

    U_HR, U_HOD, U_HOD2, U_MD = (str(ObjectId()) for _ in range(4))
    D_JUNIOR, D_MANAGER = ObjectId(), ObjectId()

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_HOD2), "full_name": "Hema HOD", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "company_id": COMPANY,
         "role": "clientadmin", "governance_role": "MD"},
    ])
    designations = FakeCollection([
        {"_id": D_JUNIOR, "company_id": COMPANY, "designation_name": "Ops Executive",
         "designation_level": M.DesignationLevel.JUNIOR.value},
        {"_id": D_MANAGER, "company_id": COMPANY, "designation_name": "Ops Manager",
         "designation_level": M.DesignationLevel.MANAGERIAL.value},
    ])
    reqs = FakeCollection([
        {"request_no": "R-JUN", "company_id": COMPANY, "requisition_track": "internal",
         "designation_id": str(D_JUNIOR), "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "R-MGR", "company_id": COMPANY, "requisition_track": "internal",
         "designation_id": str(D_MANAGER), "designation_name": "Ops Manager",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
    ])

    def cand(uk, request_no, name, status=M.AppStatus.TECHNICAL_ROUND.value):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": status, "scorecard_score": 4.1}

    candidates = FakeCollection([
        cand("CAN-J1", "R-JUN", "Junior One"),
        cand("CAN-J2", "R-JUN", "Junior Two"),
        cand("CAN-J3", "R-JUN", "Junior Three"),
        cand("CAN-M1", "R-MGR", "Manager One"),
    ])
    interviews = FakeCollection()
    shortlists = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_SHORTLIST_REVIEWS: shortlists, M.COLL_EXCEPTIONS: FakeCollection(),
             M.COLL_INTERVIEWS: interviews, M.COLL_DESIGNATIONS: designations,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": learners, "staff": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_exception_service as EX
    import app.services.hrms_interview_service as IV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HACC
    for mod in (SL, CS, EX, IV, AUD, IDS, HACC):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    CS.notify_user = silent

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HR = actor(U_HR, "HR")

    def committee(hr_says="Agree", hod_says="Agree", hod_recused=False):
        return [{"user_id": U_HR, "decision": hr_says},
                {"user_id": U_HOD, "decision": hod_says, "recused": hod_recused}]

    async def status_of(uk):
        row = await candidates.find_one({"uk": uk, "company_id": COMPANY})
        return (row or {}).get("application_status")

    try:
        # =================================================================
        section("Both approve a junior role -- Selected, and the candidate moves")
        # =================================================================
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-J1"],
            "committee_members": committee(), "outcome": "Selected"})
        check("outcome recorded as Selected",
              rec["outcome"] == M.ShortlistOutcome.SELECTED.value)
        check("the candidate is now Selected",
              await status_of("CAN-J1") == M.AppStatus.SELECTED.value)
        check("the rationale is frozen on the record",
              bool((rec.get("commit_rationale") or {}).get("because")))
        check("no candidate was skipped", "warning" not in rec)

        # =================================================================
        section("An objection rejects, whatever the caller asked for")
        # =================================================================
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-J2"],
            "committee_members": committee(hod_says="Object"),
            # The caller ASKS for Selected. The verdicts say otherwise, and the verdicts win.
            "outcome": "Selected"})
        check("asking for Selected over an objection records Rejected",
              rec["outcome"] == M.ShortlistOutcome.REJECTED.value)
        check("the candidate is Rejected",
              await status_of("CAN-J2") == M.AppStatus.REJECTED.value)
        check("the rationale names who did not approve",
              "Hari HOD" in (rec.get("commit_rationale") or {}).get("because", ""))

        # =================================================================
        section("A recused objector is not an approver")
        # =================================================================
        # Standing down costs the committee its quorum unless somebody else covers the role.
        # That refusal is correct and worth pinning: one person is not a two-role committee.
        await expect_http(
            "recusing the only Head leaves the committee inquorate",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "R-JUN", "candidate_uks": ["CAN-J3"],
                "committee_members": committee(hod_says="Object", hod_recused=True),
                "outcome": "Selected"}),
            422, "two different people")

        # With a second Head sitting in, the recused objection must simply not count.
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-J3"],
            "committee_members": [
                {"user_id": U_HR, "decision": "Agree"},
                {"user_id": U_HOD, "decision": "Object", "recused": True},
                {"user_id": U_HOD2, "decision": "Agree"}],
            "outcome": "Selected"})
        check("the recused member's objection does not reject the sitting",
              rec["outcome"] == M.ShortlistOutcome.SELECTED.value)
        check("the candidate is Selected",
              await status_of("CAN-J3") == M.AppStatus.SELECTED.value)

        # =================================================================
        section("A managerial role routes to the final interview")
        # =================================================================
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-MGR", "candidate_uks": ["CAN-M1"],
            "committee_members": committee(), "outcome": "Selected"})
        check("both approved, yet the outcome is Final Interview Required",
              rec["outcome"] == M.ShortlistOutcome.FINAL_INTERVIEW_REQUIRED.value)
        check("the candidate sits at Final Interview Required",
              await status_of("CAN-M1") == M.AppStatus.FINAL_INTERVIEW_REQUIRED.value)
        check("the rationale says it is the seniority of the role",
              "final interview" in
              (rec.get("commit_rationale") or {}).get("because", "").lower())

        # =================================================================
        section("A candidate already IN the final round is not reported as stuck")
        # =================================================================
        # Passing an earlier round advances them to MD Round automatically, so the commit
        # arrives to find them already where it was routing them. That is the normal
        # managerial path, and it must not come back as "could not be moved".
        await candidates.insert_one(cand("CAN-M2", "R-MGR", "Manager Two",
                                         status=M.AppStatus.MD_ROUND.value))
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-MGR", "candidate_uks": ["CAN-M2"],
            "committee_members": committee(), "outcome": "Selected"})
        check("the outcome still routes to the final round",
              rec["outcome"] == M.ShortlistOutcome.FINAL_INTERVIEW_REQUIRED.value)
        check("and nothing is reported as skipped", "warning" not in rec)
        check("they stay in the round they are already sitting",
              await status_of("CAN-M2") == M.AppStatus.MD_ROUND.value)

        # =================================================================
        section("That same sitting clears the selection gate once the round is passed")
        # =================================================================
        mgr_req = await reqs.find_one({"request_no": "R-MGR"})
        mgr_cand = await candidates.find_one({"uk": "CAN-M1"})
        # The shortlist gate must PASS here -- the committee did agree -- and the final
        # round gate is the one still holding. Two gates, two questions, and conflating
        # them is what would strand this candidate.
        cleared = True
        try:
            await SL.assert_shortlist_cleared(COMPANY, mgr_cand, mgr_req)
        except Exception:
            cleared = False
        check("the shortlist gate passes on a Final Interview Required sitting", cleared)

        await expect_http(
            "the final-round gate is what still refuses",
            IV.assert_final_round_complete(COMPANY, mgr_cand, mgr_req), 409, "final")

        await interviews.insert_one({
            "company_id": COMPANY, "uk": "CAN-M1", "interview_no": "INT-1",
            "round": M.FINAL_ROUND.value, "outcome": "Pass"})
        passed = True
        try:
            await IV.assert_final_round_complete(COMPANY, mgr_cand, mgr_req)
        except Exception:
            passed = False
        check("once the round is passed, both gates are satisfied", passed and cleared)

        # =================================================================
        section("The legacy vocabulary is readable history, not a choice")
        # =================================================================
        await expect_http(
            "recording a new sitting as 'Finalised'",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "R-JUN", "candidate_uks": ["CAN-J1"],
                "committee_members": committee(), "outcome": "Finalised"}),
            422, "before Final Commit")
        check("a legacy Finalised sitting still clears the gate",
              M.ShortlistOutcome.FINALISED.value in M.SHORTLIST_CLEARS_SELECTION)
        check("Final Interview Required clears it too",
              M.ShortlistOutcome.FINAL_INTERVIEW_REQUIRED.value
              in M.SHORTLIST_CLEARS_SELECTION)
        check("Rejected does NOT clear it",
              M.ShortlistOutcome.REJECTED.value not in M.SHORTLIST_CLEARS_SELECTION)

        # =================================================================
        section("Committing needs a real committee and named candidates")
        # =================================================================
        await expect_http(
            "one person cannot commit alone",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "R-JUN", "candidate_uks": ["CAN-J1"],
                "committee_members": [{"user_id": U_HR, "decision": "Agree"}],
                "outcome": "Selected"}),
            422, "two different people")
        await expect_http(
            "a commit naming nobody",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "R-JUN", "candidate_uks": [],
                "committee_members": committee(), "outcome": "Selected"}),
            422, "name the candidates")

        # =================================================================
        section("Convening still decides nothing, and the preview says what would happen")
        # =================================================================
        pending = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-J1"],
            "committee_members": committee()})
        check("a convened sitting is Pending",
              pending["outcome"] == M.ShortlistOutcome.PENDING.value)
        fresh = await SL.get_shortlist_review(COMPANY, pending["slr_no"])
        check("a pending sitting carries a live preview of the outcome",
              (fresh.get("commit_preview") or {}).get("outcome")
              == M.ShortlistOutcome.SELECTED.value)

        decided = await SL.update_shortlist_review(
            HR, COMPANY, pending["slr_no"], {"outcome": "Selected"})
        check("deciding it later records the derived outcome",
              decided["outcome"] == M.ShortlistOutcome.SELECTED.value)
        await expect_http(
            "a decided sitting is frozen",
            SL.update_shortlist_review(HR, COMPANY, pending["slr_no"],
                                       {"outcome": "Rejected"}),
            409, "already decided")

        # =================================================================
        section("The status graph knows the new stage")
        # =================================================================
        FIR = M.AppStatus.FINAL_INTERVIEW_REQUIRED
        check("Technical Round -> Final Interview Required is legal",
              M.can_transition(M.AppStatus.TECHNICAL_ROUND.value, FIR.value))
        check("Final Interview Required -> MD Round is legal",
              M.can_transition(FIR.value, M.AppStatus.MD_ROUND.value))
        check("Final Interview Required -> Selected is legal",
              M.can_transition(FIR.value, M.AppStatus.SELECTED.value))
        check("Final Interview Required -> Rejected is always available",
              M.can_transition(FIR.value, M.AppStatus.REJECTED.value))
        check("it is not counted as selected in the funnel",
              M.STAGE_RANK[FIR] < M.STAGE_RANK[M.AppStatus.SELECTED])
        check("it appears on the interview column of the board",
              any(FIR in stages for key, _label, stages in M.PIPELINE_COLUMNS
                  if key == "interview"))
    finally:
        mongo.get_collection = original

    total, passed_n = len(results), sum(results)
    print(f"\n{'=' * 62}\n  {passed_n}/{total} checks passed\n{'=' * 62}")
    if passed_n != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
