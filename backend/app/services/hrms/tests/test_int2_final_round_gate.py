"""Phase INT-2 -- the mandatory Management final round (SOP §5).

"Final interview with Management for managerial and above roles before offer stage."

Covers: the table assertion that keeps the gate honest, the 409 a managerial candidate hits
without a passed MD round, the fact that a HOLD is not a pass, and -- the part that makes it
a control rather than a suggestion -- that the OFFER asks again, so a hand-set `Selected`
routes around nothing.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_final_round_gate   (from backend/)
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
NOW = datetime.now(timezone.utc)
JOINING = (NOW + timedelta(days=45)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere -- each has its own test
    # file (test_int12_client_track), and a failure here should name THIS file's control
    # rather than a precondition it never set up.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())
    DESIG_MID, DESIG_MANAGERIAL = ObjectId(), ObjectId()

    designations = FakeCollection([
        {"_id": DESIG_MID, "company_id": COMPANY, "name": "Ops Executive",
         "designation_level": "mid"},
        {"_id": DESIG_MANAGERIAL, "company_id": COMPANY, "name": "Ops Manager",
         "designation_level": "managerial"},
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Manager",
         "designation_id": str(DESIG_MANAGERIAL), "approval_status": "Approved",
         "closing_status": "Open", "vacancy": 3, "created_at": NOW,
         "approved_salary_band_min": 100000, "approved_salary_band_max": 2000000},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "designation_id": str(DESIG_MID), "approval_status": "Approved",
         "closing_status": "Open", "vacancy": 3, "created_at": NOW,
         "approved_salary_band_min": 100000, "approved_salary_band_max": 2000000},
        {"request_no": "HR-REQ-2026-003", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Senior Analyst",
         "designation_id": str(DESIG_MANAGERIAL), "approval_status": "Approved",
         "closing_status": "Open", "vacancy": 3, "created_at": NOW},
    ])

    def cand(uk, request_no, name, status=M.AppStatus.SELECTED.value):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": status}

    candidates = FakeCollection([
        cand("CAN-001", "HR-REQ-2026-001", "Manager NoRound"),
        cand("CAN-002", "HR-REQ-2026-001", "Manager Held"),
        cand("CAN-003", "HR-REQ-2026-001", "Manager Passed"),
        cand("CAN-004", "HR-REQ-2026-002", "Mid One"),
        cand("CAN-005", "HR-REQ-2026-003", "Client Senior"),
    ])
    interviews = FakeCollection([
        # A round that HAPPENED but was held -- completed work, not a clearance.
        {"interview_no": "INT-2026-002", "company_id": COMPANY, "uk": "CAN-002",
         "round": M.InterviewRound.MD.value, "outcome": M.Outcome.HOLD.value,
         "status": "Completed", "request_no": "HR-REQ-2026-001"},
        {"interview_no": "INT-2026-003", "company_id": COMPANY, "uk": "CAN-003",
         "round": M.InterviewRound.MD.value, "outcome": M.Outcome.PASS.value,
         "status": "Completed", "request_no": "HR-REQ-2026-001"},
    ])
    # Every internal candidate is committee-finalised, so the ONLY gate under test here is
    # the final round. The shortlisting committee has its own file.
    shortlists = FakeCollection([
        {"slr_no": "SLR-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001",
         "candidate_uks": ["CAN-001", "CAN-002", "CAN-003"],
         "outcome": M.ShortlistOutcome.FINALISED.value, "created_at": NOW},
        {"slr_no": "SLR-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-002", "candidate_uks": ["CAN-004"],
         "outcome": M.ShortlistOutcome.FINALISED.value, "created_at": NOW},
    ])
    references = FakeCollection([
        {"ref_no": f"REF-2026-{i:03d}", "company_id": COMPANY, "uk": f"CAN-00{i}",
         "outcome": "Positive", "created_at": NOW} for i in range(1, 6)
    ])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_INTERVIEWS: interviews, M.COLL_DESIGNATIONS: designations,
             M.COLL_SHORTLIST_REVIEWS: shortlists, M.COLL_REFERENCE_CHECKS: references,
             M.COLL_OFFERS: FakeCollection(), M.COLL_EXCEPTIONS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             M.COLL_LINKS: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_interview_service as IV
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_offer_service as OF
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (IV, CS, OF, SL, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in (IV, CS, OF):
        if hasattr(mod, "notify_user"):
            mod.notify_user = silent
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = silent

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    def offer(uk, **over):
        base = {"uk": uk, "ctc": 900000, "joining_date": JOINING,
                "designation": "Ops Manager"}
        base.update(over)
        return base

    try:
        # =================================================================
        section("The rule is asserted from the table, not trusted")
        # =================================================================
        # In the spirit of budget_approval_is_mandatory(): if somebody later made the MD
        # round optional for managerial roles, or renamed the final round, these fail loudly
        # rather than the gate quietly disappearing.
        check("the final round IS the MD round", M.FINAL_ROUND is M.InterviewRound.MD)
        check("only a Pass clears it -- a Hold is a decision deferred, not a clearance",
              M.FINAL_ROUND_PASSING == {M.Outcome.PASS.value})
        check("it applies to exactly the managerial-and-above bands",
              {level for level in M.DesignationLevel
               if M.final_round_is_mandatory(level)} == M.MANAGERIAL_LEVELS)
        check("and NOT to junior or mid",
              not M.final_round_is_mandatory("junior")
              and not M.final_round_is_mandatory("mid"))
        check("the MD round is the only road to Selected in the pass chain",
              M.PASS_NEXT[M.InterviewRound.MD] is M.AppStatus.SELECTED)

        # =================================================================
        section("A managerial candidate with no MD round")
        # =================================================================
        req_managerial = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        await expect_http(
            "no MD round on record",
            IV.assert_final_round_complete(
                COMPANY, await candidates.find_one({"uk": "CAN-001"}), req_managerial),
            409, "has not sat the md round")

        await expect_http(
            "an MD round that was HELD rather than passed",
            IV.assert_final_round_complete(
                COMPANY, await candidates.find_one({"uk": "CAN-002"}), req_managerial),
            409, "not been passed")

        # A pass raises nothing.
        await IV.assert_final_round_complete(
            COMPANY, await candidates.find_one({"uk": "CAN-003"}), req_managerial)
        check("a PASSED MD round clears the gate", True)

        # =================================================================
        section("A mid-level role is not gated at all")
        # =================================================================
        req_mid = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        await IV.assert_final_round_complete(
            COMPANY, await candidates.find_one({"uk": "CAN-004"}), req_mid)
        check("a mid role with no MD round passes -- the SOP asks for one above mid only",
              True)

        # =================================================================
        section("The client track is untouched")
        # =================================================================
        req_client = await reqs.find_one({"request_no": "HR-REQ-2026-003"})
        await IV.assert_final_round_complete(
            COMPANY, await candidates.find_one({"uk": "CAN-005"}), req_client)
        check("a CLIENT-track senior role with no MD round is not gated", True)

        # =================================================================
        section("The offer asks again -- a hand-set status routes around nothing")
        # =================================================================
        # CAN-001 is sitting at `Selected` with no MD round: exactly the state somebody
        # reaches by typing the status in. The offer refuses it anyway.
        await expect_http(
            "raising an offer for a managerial candidate who never sat the MD round",
            OF.create_offer(HR, COMPANY, offer("CAN-001")),
            409, "has not sat the md round")
        check("and no draft offer was left behind",
              await store[M.COLL_OFFERS].count_documents({}) == 0)

        made = await OF.create_offer(HR, COMPANY, offer("CAN-003"))
        check("the candidate who passed the MD round CAN be offered",
              made["offer_no"].startswith("OFR-"))

        # =================================================================
        section("The hand-set stage move is gated too")
        # =================================================================
        await candidates.update_one(
            {"uk": "CAN-001"},
            {"$set": {"application_status": M.AppStatus.MD_ROUND.value}})
        await expect_http(
            "moving a managerial candidate to Selected by hand",
            CS.update_candidate(HR, COMPANY, "CAN-001",
                                {"application_status": "Selected"}),
            409, "has not sat the md round")
        after = await candidates.find_one({"uk": "CAN-001"})
        check("and they were left exactly where they were",
              after["application_status"] == M.AppStatus.MD_ROUND.value)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
