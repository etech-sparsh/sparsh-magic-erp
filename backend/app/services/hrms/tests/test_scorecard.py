"""Internal recruitment track -- the position scorecard.

Covers: drafting and the one-per-requisition rule, weighted scoring and normalisation, the
SOP's 4.0 / 3.0 bands, approval routing (hiring manager always; Management as well for
managerial+), the freeze on an approved scorecard, and the gate it puts on the requisition
chain.

The property that matters most and is easiest to lose: THE BAND IS ADVICE. Scoring a
candidate must never move them. A rubric wired to the pipeline is a rubric that makes hiring
decisions nobody signed, so the absence of a stage move is asserted explicitly rather than
assumed.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_scorecard   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_HOD, U_HOD2 = (str(ObjectId()), str(ObjectId()),
                                 str(ObjectId()), str(ObjectId()))

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "department_name": "Operations", "created_by": U_HOD,
         "approval_status": M.ReqApproval.PENDING_SCORECARD.value,
         "closing_status": "Open", "vacancy": 1, "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Manager",
         "department_name": "Operations", "created_by": U_HOD,
         "approval_status": M.ReqApproval.PENDING_SCORECARD.value,
         "closing_status": "Open", "vacancy": 1, "created_at": NOW},
        # A client-track requisition, which may never have one.
        {"request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "created_by": U_HOD, "approval_status": "Pending MD Approval",
         "closing_status": "Open", "vacancy": 1, "created_at": NOW},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "candidate_name": "Test One", "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"_id": ObjectId(), "uk": "CAN-002", "company_id": COMPANY,
         "candidate_name": "Test Two", "request_no": None,
         "application_status": M.AppStatus.APPLIED.value},
    ])
    scorecards_coll = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_POSITION_SCORECARDS: scorecards_coll,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: audit_log,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (SC, AUD, IDS):
        mod.get_collection = mongo.get_collection

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")
    HOD = actor(U_HOD, "HOD")
    HOD2 = actor(U_HOD2, "HOD")

    CRITERIA = [
        {"label": "SQL", "category": "skill", "weight": 3, "max_score": 5},
        {"label": "Years in role", "category": "experience", "weight": 2, "max_score": 5},
        {"label": "Culture fit", "category": "culture_fit", "weight": 1, "max_score": 5},
    ]

    try:
        # =================================================================
        section("Weighted scoring and the SOP's bands")
        # =================================================================
        strong = SC.compute_weighted(
            [{"label": "A", "weight": 2, "max_score": 5},
             {"label": "B", "weight": 1, "max_score": 5}],
            {"A": 5, "B": 2})
        check("weights are a weighted MEAN, not a sum (5 and 2 at 2:1 -> 4.0)",
              strong["weighted_score"] == 4.0)
        check("4.0 is 'Strong' (SOP: 4.0+ strong)", strong["band"] == "Strong")

        # Phase INT-2 aligned the guide with BOTH SOPs, which define FOUR bands, not three:
        # >=4.0 Strong, 3.5-3.9 Consider, 3.0-3.4 Hold, <3.0 Reject. The boundaries are
        # asserted directly against score_band, because compute_weighted can only produce
        # the scores its criteria allow and the boundaries are the whole point.
        for value, expected in ((4.0, "Strong"), (3.9, "Consider"), (3.5, "Consider"),
                                (3.4, "Hold"), (3.0, "Hold"), (2.99, "Reject")):
            check(f"{value} bands as '{expected}'", M.score_band(value) == expected)
        check("an unscored candidate has no band at all, rather than a bad one",
              M.score_band(None) is None)
        check("the guide the UI renders names the same four bands the function returns",
              [row["band"] for row in M.SCORE_BAND_GUIDE]
              == ["Strong", "Consider", "Hold", "Reject"])

        mid = SC.compute_weighted([{"label": "A", "weight": 1, "max_score": 5}], {"A": 3})
        check("3.0 is 'Hold', NOT a reject (the SOP rejects BELOW 3.0)",
              mid["band"] == "Hold")
        low = SC.compute_weighted([{"label": "A", "weight": 1, "max_score": 5}], {"A": 2})
        check("below 3.0 is 'Reject'", low["band"] == "Reject")

        # A criterion marked out of 10 must not silently count double.
        norm = SC.compute_weighted(
            [{"label": "Out of ten", "weight": 1, "max_score": 10},
             {"label": "Out of five", "weight": 1, "max_score": 5}],
            {"Out of ten": 10, "Out of five": 5})
        check("a max_score of 10 is normalised to the 1-5 scale, not counted double",
              norm["weighted_score"] == 5.0)

        expect_http_sync(
            "scoring only some of the criteria",
            lambda: SC.compute_weighted(CRITERIA, {"SQL": 4}), 422, "Score every criterion")
        expect_http_sync(
            "scoring a criterion the scorecard does not have",
            lambda: SC.compute_weighted(CRITERIA,
                                        {"SQL": 4, "Years in role": 4, "Culture fit": 4,
                                         "Vibes": 5}),
            422, "not criteria on this scorecard")
        expect_http_sync(
            "a score above the criterion's maximum",
            lambda: SC.compute_weighted(CRITERIA,
                                        {"SQL": 9, "Years in role": 4, "Culture fit": 4}),
            422, "must be between")

        # =================================================================
        section("Drafting")
        # =================================================================
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": "HR-REQ-2026-001", "criteria": CRITERIA,
            "title": "Ops Executive bar"})
        SCR = card["scr_no"]
        check("a scorecard id is minted", SCR.startswith("SCR-"))
        check("it opens Pending Approval, never Draft-and-forgotten",
              card["status"] == M.ScorecardStatus.PENDING_APPROVAL.value)
        check("the requisition's designation rides along for the list view",
              card["designation_name"] == "Ops Executive")
        check("drafting is audited",
              any(a["action"] == M.AUDIT_SCORECARD_CREATED for a in audit_log.docs))

        await expect_http(
            "a second scorecard for the same requisition",
            SC.create_scorecard(HR, COMPANY,
                                {"request_no": "HR-REQ-2026-001", "criteria": CRITERIA}),
            409, "already has a position scorecard")
        await expect_http(
            "a scorecard for a CLIENT-track requisition",
            SC.create_scorecard(HR, COMPANY,
                                {"request_no": "HR-REQ-2026-003", "criteria": CRITERIA}),
            409, "legacy client-track")
        await expect_http(
            "a scorecard with no criteria",
            SC.create_scorecard(HR, COMPANY,
                                {"request_no": "HR-REQ-2026-002", "criteria": []}),
            422, "at least one criterion")
        await expect_http(
            "two criteria with the same label",
            SC.create_scorecard(HR, COMPANY, {
                "request_no": "HR-REQ-2026-002",
                "criteria": [{"label": "SQL"}, {"label": "sql"}]}),
            422, "appears twice")
        await expect_http(
            "a criterion weighted zero",
            SC.create_scorecard(HR, COMPANY, {
                "request_no": "HR-REQ-2026-002",
                "criteria": [{"label": "SQL", "weight": 0}]}),
            422, "greater than 0")

        # =================================================================
        section("Approval routing -- ordinary role")
        # =================================================================
        state = (await SC.get_scorecard(COMPANY, SCR))["approval_state"]
        check("an ordinary role needs the hiring manager only",
              state["required_roles"] == ["manager"] and not state["complete"])

        await expect_http(
            "approving without signing",
            SC.approve_scorecard(HOD, COMPANY, SCR, {"decision": "Pass"}),
            422, "Type your name")

        out = await SC.approve_scorecard(HOD, COMPANY, SCR,
                                         {"decision": "Pass", "signature": "HOD"})
        check("the hiring manager's signature completes it",
              out["status"] == M.ScorecardStatus.APPROVED.value)
        check("and the approval state says so", out["approval_state"]["complete"])
        check("approval is audited",
              any(a["action"] == M.AUDIT_SCORECARD_APPROVED for a in audit_log.docs))

        await expect_http("approving an already-approved scorecard",
                          SC.approve_scorecard(MD, COMPANY, SCR,
                                               {"decision": "Pass", "signature": "MD"}),
                          409, "already approved")
        await expect_http(
            "editing an APPROVED scorecard",
            SC.update_scorecard(HR, COMPANY, SCR, {"title": "Rewritten"}),
            409, "can no longer be edited")

        # =================================================================
        section("Approval routing -- managerial+ needs Management too")
        # =================================================================
        mgr_card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": "HR-REQ-2026-002", "criteria": CRITERIA, "managerial": True})
        MSCR = mgr_card["scr_no"]
        check("a managerial scorecard needs BOTH the manager and Management",
              mgr_card["approval_state"]["required_roles"] == ["manager", "md"])

        out = await SC.approve_scorecard(HOD, COMPANY, MSCR,
                                         {"decision": "Pass", "signature": "HOD"})
        check("the manager alone does NOT complete a managerial scorecard",
              out["status"] == M.ScorecardStatus.PENDING_APPROVAL.value)
        check("and Management is named as outstanding",
              out["approval_state"]["outstanding_roles"] == ["md"])

        out = await SC.approve_scorecard(MD, COMPANY, MSCR,
                                         {"decision": "Pass", "signature": "MD"})
        check("Management's signature completes it",
              out["status"] == M.ScorecardStatus.APPROVED.value)
        check("both signatures are on the record", len(out["approvals"]) == 2)
        check("they are two DIFFERENT people",
              len({a["user_id"] for a in out["approvals"]}) == 2)

        # =================================================================
        section("Sending one back, and re-approval after an edit")
        # =================================================================
        third = await SC.create_scorecard(HR, COMPANY, {
            "request_no": "HR-REQ-2026-004", "criteria": CRITERIA}) \
            if await reqs.find_one({"request_no": "HR-REQ-2026-004"}) else None
        # Requisition 004 does not exist, so build the case on a fresh internal one.
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-005", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Analyst",
            "created_by": U_HOD, "approval_status": M.ReqApproval.PENDING_SCORECARD.value,
            "closing_status": "Open", "vacancy": 1, "created_at": NOW})
        back = await SC.create_scorecard(HR, COMPANY, {
            "request_no": "HR-REQ-2026-005", "criteria": CRITERIA})
        BSCR = back["scr_no"]

        await expect_http(
            "sending a scorecard back with no reason",
            SC.approve_scorecard(HOD, COMPANY, BSCR,
                                 {"decision": "Fail", "signature": "HOD"}),
            422, "Say why")
        out = await SC.approve_scorecard(
            HOD, COMPANY, BSCR,
            {"decision": "Fail", "signature": "HOD", "remarks": "Weights favour tenure."})
        check("a rejected scorecard is marked Rejected",
              out["status"] == M.ScorecardStatus.REJECTED.value)
        check("and is editable again", out["status"] != M.ScorecardStatus.APPROVED.value)

        edited = await SC.update_scorecard(
            HR, COMPANY, BSCR,
            {"criteria": [{"label": "SQL", "weight": 1}, {"label": "Ownership",
                                                          "weight": 3}]})
        check("editing the criteria returns it to Pending Approval",
              edited["status"] == M.ScorecardStatus.PENDING_APPROVAL.value)

        # An edit to the CRITERIA must invalidate signatures already given.
        await SC.approve_scorecard(HOD, COMPANY, BSCR,
                                   {"decision": "Pass", "signature": "HOD"})
        signed = await SC.get_scorecard(COMPANY, BSCR)
        check("it approves again after the edit",
              signed["status"] == M.ScorecardStatus.APPROVED.value)

        # =================================================================
        section("The gate it puts on the requisition chain")
        # =================================================================
        approved = await SC.assert_scorecard_approved(COMPANY, "HR-REQ-2026-001")
        check("an approved scorecard satisfies the gate", approved["scr_no"] == SCR)

        await reqs.insert_one({
            "request_no": "HR-REQ-2026-006", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Coordinator",
            "created_by": U_HOD, "approval_status": M.ReqApproval.PENDING_SCORECARD.value,
            "closing_status": "Open", "vacancy": 1, "created_at": NOW})
        await expect_http(
            "the gate with NO scorecard at all",
            SC.assert_scorecard_approved(COMPANY, "HR-REQ-2026-006"),
            409, "has no position scorecard")

        pending = await SC.create_scorecard(HR, COMPANY, {
            "request_no": "HR-REQ-2026-006", "criteria": CRITERIA, "managerial": True})
        await SC.approve_scorecard(HOD, COMPANY, pending["scr_no"],
                                   {"decision": "Pass", "signature": "HOD"})
        await expect_http(
            "the gate with a HALF-approved managerial scorecard",
            SC.assert_scorecard_approved(COMPANY, "HR-REQ-2026-006"),
            409, "still waiting on: md")

        # =================================================================
        section("Evaluating a candidate -- and NOT moving them")
        # =================================================================
        before = await candidates.find_one({"uk": "CAN-001"})
        stage_before = before["application_status"]

        await expect_http(
            "evaluating without signing",
            SC.evaluate_candidate(HR, COMPANY, "CAN-001",
                                  {"scores": {"SQL": 5, "Years in role": 4,
                                              "Culture fit": 4}}),
            422, "Type your name")

        out = await SC.evaluate_candidate(HR, COMPANY, "CAN-001", {
            "scores": {"SQL": 5, "Years in role": 4, "Culture fit": 4},
            "signature": "HR", "remarks": "Strong on the core skill."})
        check("the weighted score is computed server-side",
              out["weighted_score"] == round((5 * 3 + 4 * 2 + 4 * 1) / 6, 2))
        check("its band is named", out["band"] == "Strong")
        check("the breakdown shows every criterion", len(out["breakdown"]) == 3)

        after = await candidates.find_one({"uk": "CAN-001"})
        check("THE CANDIDATE IS NOT MOVED -- a band is advice, not a decision",
              after["application_status"] == stage_before)
        check("and the response says so outright", out["stage_changed"] is False)
        check("the score is denormalised for reporting",
              after["scorecard_score"] == out["weighted_score"]
              and after["scorecard_band"] == "Strong")
        check("the evaluation is signed and attributable",
              after["scorecard_evaluation"]["signature"] == "HR"
              and after["scorecard_evaluation"]["evaluated_by"] == U_HR)
        check("evaluation is audited",
              any(a["action"] == M.AUDIT_SCORECARD_EVALUATED for a in audit_log.docs))

        # A below-bar score must be recorded exactly as readily as a strong one, and still
        # not move anybody -- this is the case an auto-reject would have swallowed.
        out = await SC.evaluate_candidate(HR, COMPANY, "CAN-001", {
            "scores": {"SQL": 2, "Years in role": 2, "Culture fit": 2},
            "signature": "HR"})
        after = await candidates.find_one({"uk": "CAN-001"})
        check("a REJECT-band score is recorded", out["band"] == "Reject")
        check("and still does not reject the candidate",
              after["application_status"] == stage_before)

        await expect_http(
            "evaluating a candidate attached to no requisition",
            SC.evaluate_candidate(HR, COMPANY, "CAN-002",
                                  {"scores": {"SQL": 4}, "signature": "HR"}),
            409, "not attached to a requisition")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
