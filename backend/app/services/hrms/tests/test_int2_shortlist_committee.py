"""Phase INT-2 -- the internal shortlisting committee (SOP §5).

"HR and the Department Head shall jointly finalise the shortlist before the final
interview."

Covers: the two-roles-two-people rule, the gate it puts on `Selected`, the exception that
lifts it, the freeze on a decided sitting, and the refusal of a client-track requisition.

The property worth testing hardest: FINALISING is what lifts the gate, not convening. A
committee that met and did not decide has decided nothing, and a system that treated the
meeting as the decision would let the control be satisfied by putting a date in a diary.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_shortlist_committee   (from backend/)
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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HR2, U_HOD, U_MD, U_FIN = (str(ObjectId()) for _ in range(5))

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HR2), "full_name": "Hira HR", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "company_id": COMPANY,
         "role": "clientadmin", "governance_role": "MD"},
        {"_id": ObjectId(U_FIN), "full_name": "Farid Finance", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "FINANCE"},
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
    ])

    def cand(uk, request_no, name, **over):
        base = {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": M.AppStatus.MD_ROUND.value}
        base.update(over)
        return base

    candidates = FakeCollection([
        cand("CAN-001", "HR-REQ-2026-001", "Internal One",
             scorecard_score=4.2, scorecard_band="Strong"),
        cand("CAN-002", "HR-REQ-2026-001", "Internal Two", scorecard_score=3.2),
        cand("CAN-003", "HR-REQ-2026-001", "Internal Three"),
        # Named by no sitting and covered by no exception -- the control case for
        # "a waiver is as narrow as it was written".
        cand("CAN-004", "HR-REQ-2026-001", "Internal Four"),
        cand("CAN-100", "HR-REQ-2026-002", "Client One"),
    ])
    shortlists = FakeCollection()
    exceptions = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_SHORTLIST_REVIEWS: shortlists, M.COLL_EXCEPTIONS: exceptions,
             M.COLL_INTERVIEWS: FakeCollection(), M.COLL_DESIGNATIONS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": learners}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_exception_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (SL, CS, EX, AUD, IDS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    CS.notify_user = silent

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")

    def members(*uids):
        return [{"user_id": u, "decision": "Agree"} for u in uids]

    try:
        # =================================================================
        section("Capability shape -- Finance is deliberately absent")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR may convene a committee", can(HR, M.Cap.SHORTLIST_WRITE))
        check("the HOD may too -- SOP section 5 puts them ON it",
              can(actor(U_HOD, "HOD"), M.Cap.SHORTLIST_WRITE))
        check("the MD may too", can(MD, M.Cap.SHORTLIST_WRITE))
        check("FINANCE may NOT -- it approves what a role costs, never who fills it",
              not can(actor(U_FIN, "FINANCE"), M.Cap.SHORTLIST_READ)
              and not can(actor(U_FIN, "FINANCE"), M.Cap.SHORTLIST_WRITE))

        # =================================================================
        section("Two roles, and two DIFFERENT people")
        # =================================================================
        check("the SOP's roles are HR and the Department Head",
              [r.value for r in M.SHORTLIST_COMMITTEE_ROLES] == ["hr", "manager"])

        state = SL.committee_state([{"user_id": U_HR, "role": "hr"}])
        check("HR alone is not a committee", not state["complete"])
        check("and the state NAMES what is missing",
              state["outstanding_roles"] == ["manager"])

        state = SL.committee_state([
            {"user_id": U_MD, "role": "hr"}, {"user_id": U_MD, "role": "manager"}])
        check("one person under two roles is not a committee either",
              not state["complete"])
        check("and says so as a second-member problem, not a missing-role one",
              "second" in " ".join(state["outstanding_roles"]).lower())

        state = SL.committee_state([
            {"user_id": U_HR, "role": "hr"}, {"user_id": U_HOD, "role": "manager"}])
        check("HR and the HOD, two people, IS a committee", state["complete"])

        state = SL.committee_state([
            {"user_id": U_HR, "role": "hr"},
            {"user_id": U_HOD, "role": "manager", "recused": True}])
        check("a recused member does not make it quorate", not state["complete"])

        # =================================================================
        section("Convening decides nothing")
        # =================================================================
        convened = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "HR-REQ-2026-001",
            "candidate_uks": ["CAN-001", "CAN-002"],
            "committee_members": members(U_HR, U_HOD),
            "outcome": "Pending"})
        SLR = convened["slr_no"]
        check("a sitting is minted with an SLR id", SLR.startswith("SLR-"))
        check("it starts Pending", convened["outcome"] == "Pending")
        check("and carries no decision timestamp", convened["decided_at"] is None)
        check("the retention floor is stamped (SOP section 13)",
              bool(convened["retention_until"]))

        check("the decision guide re-bands from the SCORE, not the stored label",
              [g["decision_guide_band"] for g in convened["decision_guide"]]
              == ["Strong", "Hold"])

        # =================================================================
        section("Finalising is what lifts the gate")
        # =================================================================
        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        await expect_http(
            "selecting a candidate whose sitting is only CONVENED",
            SL.assert_shortlist_cleared(
                COMPANY, await candidates.find_one({"uk": "CAN-001"}), req),
            409, "not been finalised by the shortlisting committee")

        # Final Commit: the outcome is DERIVED from the members' verdicts, so asking for
        # "Selected" on an all-Agree committee records exactly that. See test_final_commit.
        await SL.update_shortlist_review(HR, COMPANY, SLR, {"outcome": "Selected"})
        await SL.assert_shortlist_cleared(
            COMPANY, await candidates.find_one({"uk": "CAN-001"}), req)
        check("once committed, the named candidate passes", True)

        await expect_http(
            "a candidate the sitting did NOT name",
            SL.assert_shortlist_cleared(
                COMPANY, await candidates.find_one({"uk": "CAN-003"}), req),
            409, "not been finalised")

        # =================================================================
        section("An incomplete committee cannot finalise")
        # =================================================================
        lone = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "HR-REQ-2026-001",
            "candidate_uks": ["CAN-003"],
            "committee_members": members(U_HR),
            "outcome": "Pending"})
        await expect_http(
            "committing with HR alone on the committee",
            SL.update_shortlist_review(HR, COMPANY, lone["slr_no"],
                                       {"outcome": "Selected"}),
            422, "two different people")

        await expect_http(
            "convening AND committing in one call with an incomplete committee",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "HR-REQ-2026-001", "candidate_uks": ["CAN-003"],
                "committee_members": members(U_HR), "outcome": "Selected"}),
            422, "two different people")

        await expect_http(
            "committing a sitting that names nobody",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "HR-REQ-2026-001", "candidate_uks": [],
                "committee_members": members(U_HR, U_HOD), "outcome": "Selected"}),
            422, "name the candidates")

        await expect_http(
            "recording a NEW sitting with the pre-Final-Commit vocabulary",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "HR-REQ-2026-001", "candidate_uks": ["CAN-003"],
                "committee_members": members(U_HR, U_HOD), "outcome": "Finalised"}),
            422, "before Final Commit")

        # =================================================================
        section("A decided sitting is frozen")
        # =================================================================
        await expect_http(
            "editing a sitting that has already been committed",
            SL.update_shortlist_review(HR, COMPANY, SLR, {"outcome": "Rejected"}),
            409, "already decided")
        check("a second decision is a second sitting, not an edit of the first", True)

        # =================================================================
        section("Only an APPROVED exception lifts it")
        # =================================================================
        check("the shortlist gate maps to the Relaxed Scorecard type",
              M.EXCEPTION_UNBLOCKS["shortlist"]
              == M.ExceptionType.RELAXED_SCORECARD.value)
        check("and that ONE type now lifts two gates, visibly rather than by accident",
              set(M.gates_for_exception_type(M.ExceptionType.RELAXED_SCORECARD.value))
              == {"scorecard", "shortlist"})

        raised = await EX.raise_exception(HR, COMPANY, {
            "request_no": "HR-REQ-2026-001", "uk": "CAN-003",
            "exception_type": "Relaxed Scorecard",
            "reason": "Sole applicant with a scarce skill; the HOD is on leave."})
        await expect_http(
            "a PENDING exception lifts nothing",
            SL.assert_shortlist_cleared(
                COMPANY, await candidates.find_one({"uk": "CAN-003"}), req),
            409, "not been finalised")

        await EX.decide_exception(MD, COMPANY, raised["exc_no"], {
            "decision": "Approved", "signature": "Meera MD", "remarks": "Agreed."})
        await SL.assert_shortlist_cleared(
            COMPANY, await candidates.find_one({"uk": "CAN-003"}), req)
        check("an APPROVED exception lets that candidate through", True)

        await expect_http(
            "another candidate riding the first one's exception",
            SL.assert_shortlist_cleared(
                COMPANY, await candidates.find_one({"uk": "CAN-004"}), req),
            409, "not been finalised")
        check("a waiver is exactly as narrow as it was written", True)

        # =================================================================
        section("The client track has no committee at all")
        # =================================================================
        await expect_http(
            "convening a committee on a client requisition",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "HR-REQ-2026-002", "candidate_uks": ["CAN-100"],
                "committee_members": members(U_HR, U_HOD)}),
            409, "legacy client-track")

        client_req = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        await SL.assert_shortlist_cleared(
            COMPANY, await candidates.find_one({"uk": "CAN-100"}), client_req)
        check("and a client-track candidate is not gated by one", True)

        # =================================================================
        section("A candidate from another requisition cannot be named")
        # =================================================================
        await expect_http(
            "naming a candidate who is on a different vacancy",
            SL.create_shortlist_review(HR, COMPANY, {
                "request_no": "HR-REQ-2026-001", "candidate_uks": ["CAN-100"],
                "committee_members": members(U_HR, U_HOD)}),
            422, "not a candidate on")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
