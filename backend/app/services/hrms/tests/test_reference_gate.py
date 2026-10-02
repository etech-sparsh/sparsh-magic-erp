"""Internal recruitment track -- reference checks and the offer gate.

SOP §6: "Reference check completed before offer for all roles (not limited to managerial+,
since Sparsh Magic bears the direct employment risk internally)."

Covers: recording a reference, the several-referees case, what counts as a CLEARANCE as
opposed to completed work, the 409 on `POST /offers` without one, the fact that ONLY an
approved exception lifts it, and -- the negative that matters most -- that the client track
is entirely unaffected.

The distinction this file exists to pin down: "Unable to Verify" is finished WORK but not a
clearance. Nobody vouched for the candidate. Treating it as good enough would turn the
control into paperwork.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_reference_gate   (from backend/)
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
TODAY = NOW.strftime("%Y-%m-%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")


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

    U_HR, U_MD = str(ObjectId()), str(ObjectId())

    def cand(uk, request_no, name):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": M.AppStatus.SELECTED.value}

    candidates = FakeCollection([
        cand("CAN-001", "HR-REQ-2026-001", "Internal One"),     # internal, no reference
        cand("CAN-002", "HR-REQ-2026-001", "Internal Two"),     # internal, will clear
        cand("CAN-003", "HR-REQ-2026-001", "Internal Three"),   # internal, unverifiable
        cand("CAN-004", "HR-REQ-2026-002", "Client One"),       # client track
        cand("CAN-005", "HR-REQ-2026-001", "Internal Four"),    # waived by exception
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 5,
         "approved_salary_band_min": 100000, "approved_salary_band_max": 900000,
         "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 5,
         "created_at": NOW},
    ])
    references_coll = FakeCollection()
    exceptions = FakeCollection()
    audit_log = FakeCollection()

    # Phase INT-2 added a shortlisting-committee gate on `Selected` (SOP §5). It has its
    # own test file; here it is satisfied for every internal candidate so this file keeps
    # testing exactly the gate it is about.
    shortlists = FakeCollection([
        {"slr_no": "SLR-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001",
         "candidate_uks": [f"CAN-{i:03d}" for i in range(1, 30)],
         "outcome": M.ShortlistOutcome.FINALISED.value, "created_at": NOW},
    ])

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_REFERENCE_CHECKS: references_coll, M.COLL_EXCEPTIONS: exceptions,
             M.COLL_OFFERS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: audit_log, M.COLL_LINKS: FakeCollection(),
             M.COLL_EMPLOYEE_PROFILES: FakeCollection(),
             M.COLL_SHORTLIST_REVIEWS: shortlists,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_reference_service as RC
    import app.services.hrms_exception_service as EX
    import app.services.hrms_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (RC, EX, OF, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in (OF,):
        if hasattr(mod, "notify_user"):
            mod.notify_user = silent
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = silent

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "MD", "full_name": "Meera MD"}

    def reference(uk, outcome="Positive", **over):
        base = {"uk": uk, "referee_name": "Former Manager",
                "referee_designation": "Delivery Head",
                "referee_organisation": "Northwind Systems",
                "relationship": "Reporting manager", "referee_contact": "+91 00000 00001",
                "mode": "Phone", "checked_on": TODAY, "outcome": outcome,
                "responses": "Confirmed dates and scope of work."}
        if outcome != "Positive":
            base["remarks"] = "Referee would not comment on performance."
        base.update(over)
        return base

    def offer(uk, ctc=500000):
        return {"uk": uk, "ctc": ctc, "joining_date": (NOW + timedelta(days=30))
                .strftime("%Y-%m-%d"), "designation": "Ops Executive"}

    try:
        # =================================================================
        section("Recording a reference")
        # =================================================================
        row = await RC.create_reference_check(HR, COMPANY, reference("CAN-002"))
        REF = row["ref_no"]
        check("a reference id is minted", REF.startswith("REF-"))
        check("it carries the candidate", row["uk"] == "CAN-002")
        check("and the requisition, so analytics scoping still reaches it",
              row["request_no"] == "HR-REQ-2026-001")
        check("who conducted it is attributable", row["conducted_by"] == U_HR)
        check("a retention date is computed and stored (SOP 13)",
              row["retention_until"].startswith(str(NOW.year + 3)))
        check("recording is audited",
              any(a["action"] == M.AUDIT_REFERENCE_RECORDED for a in audit_log.docs))

        await expect_http(
            "a reference with no referee named",
            RC.create_reference_check(HR, COMPANY, reference("CAN-001", referee_name="")),
            422, "anonymous reference check is not a check")
        await expect_http(
            "a reference dated in the future",
            RC.create_reference_check(HR, COMPANY,
                                      reference("CAN-001", checked_on=TOMORROW)),
            422, "cannot be dated in the future")
        await expect_http(
            "a NEGATIVE reference with no note",
            RC.create_reference_check(HR, COMPANY,
                                      dict(reference("CAN-001", outcome="Negative"),
                                           remarks=None)),
            422, "cannot be acted on")
        await expect_http(
            "an unknown outcome",
            RC.create_reference_check(HR, COMPANY, reference("CAN-001", outcome="Vibes")),
            422, "Outcome must be one of")

        # =================================================================
        section("Completed work is not the same as a clearance")
        # =================================================================
        await RC.create_reference_check(HR, COMPANY,
                                        reference("CAN-003", outcome="Unable to Verify"))
        check("an 'Unable to Verify' reference IS recorded",
              (await RC.list_reference_checks(HR, COMPANY, uk="CAN-003"))["total"] == 1)
        check("but it does NOT clear the candidate -- nobody vouched for them",
              await RC.clearing_reference(COMPANY, "CAN-003") is None)
        check("a Positive one does",
              (await RC.clearing_reference(COMPANY, "CAN-002"))["ref_no"] == REF)
        check("the clearing set is read from the model, not hard-coded in the service",
              M.REFERENCE_CLEARS_OFFER == {M.ReferenceOutcome.POSITIVE.value})

        # Several referees: a negative first call followed by a positive second still clears.
        await RC.create_reference_check(HR, COMPANY,
                                        reference("CAN-001", outcome="Negative",
                                                  referee_name="First Referee"))
        check("a candidate may have several referees",
              (await RC.list_reference_checks(HR, COMPANY, uk="CAN-001"))["total"] == 1)
        check("one negative reference alone does not clear them",
              await RC.clearing_reference(COMPANY, "CAN-001") is None)

        # =================================================================
        section("The offer gate -- internal track")
        # =================================================================
        await expect_http(
            "an offer for a candidate with NO reference at all",
            OF.create_offer(HR, COMPANY, offer("CAN-005")),
            409, "no reference check has been completed")
        await expect_http(
            "an offer for a candidate whose only reference is Negative",
            OF.create_offer(HR, COMPANY, offer("CAN-001")),
            409, "none of which is a clearance")
        await expect_http(
            "an offer for a candidate who could not be verified",
            OF.create_offer(HR, COMPANY, offer("CAN-003")),
            409, "none of which is a clearance")
        check("no draft offer was left behind by any refusal",
              await store[M.COLL_OFFERS].count_documents({}) == 0)

        made = await OF.create_offer(HR, COMPANY, offer("CAN-002"))
        check("a cleared candidate gets their offer", made["offer_no"].startswith("OFR-"))

        # A second referee turning positive unblocks the first candidate.
        await RC.create_reference_check(HR, COMPANY,
                                        reference("CAN-001", referee_name="Second Referee"))
        check("a later POSITIVE reference clears a candidate an earlier one did not",
              (await RC.clearing_reference(COMPANY, "CAN-001")) is not None)
        made = await OF.create_offer(HR, COMPANY, offer("CAN-001"))
        check("and the offer now goes through", made["offer_no"].startswith("OFR-"))

        # =================================================================
        section("Only an APPROVED exception lifts it")
        # =================================================================
        check("the gate maps to exactly one exception type",
              M.EXCEPTION_UNBLOCKS["reference_check"]
              == M.ExceptionType.REFERENCE_WAIVED.value)

        # A PENDING waiver must not open the gate.
        await exceptions.insert_one({
            "exc_no": "EXC-2026-001", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "uk": "CAN-005",
            "exception_type": M.ExceptionType.REFERENCE_WAIVED.value,
            "status": M.ExceptionStatus.PENDING.value, "reason": "Referee unreachable",
            "created_at": NOW})
        await expect_http(
            "an offer with a PENDING waiver",
            OF.create_offer(HR, COMPANY, offer("CAN-005")),
            409, "no reference check has been completed")

        # The WRONG type of approved exception must not open it either.
        await exceptions.insert_one({
            "exc_no": "EXC-2026-002", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "uk": "CAN-005",
            "exception_type": M.ExceptionType.EXTENDED_TAT.value,
            "status": M.ExceptionStatus.APPROVED.value, "reason": "Slow month",
            "created_at": NOW})
        await expect_http(
            "an offer with an approved exception of the WRONG type",
            OF.create_offer(HR, COMPANY, offer("CAN-005")),
            409, "no reference check has been completed")

        await exceptions.update_one(
            {"exc_no": "EXC-2026-001"},
            {"$set": {"status": M.ExceptionStatus.APPROVED.value,
                      "approved_by": U_MD, "approved_at": NOW}})
        waiver = await EX.approved_exception_for(
            COMPANY, "reference_check", "HR-REQ-2026-001", "CAN-005")
        check("the approved waiver is found", waiver["exc_no"] == "EXC-2026-001")
        made = await OF.create_offer(HR, COMPANY, offer("CAN-005"))
        check("and the offer is allowed through on the waiver",
              made["offer_no"].startswith("OFR-"))

        # A candidate-specific waiver must not cover anybody else.
        await candidates.insert_one(cand("CAN-006", "HR-REQ-2026-001", "Internal Five"))
        await expect_http(
            "a candidate-specific waiver covering a DIFFERENT candidate",
            OF.create_offer(HR, COMPANY, offer("CAN-006")),
            409, "no reference check has been completed")

        # A requisition-wide waiver does cover everybody on it.
        await exceptions.insert_one({
            "exc_no": "EXC-2026-003", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "uk": None,
            "exception_type": M.ExceptionType.REFERENCE_WAIVED.value,
            "status": M.ExceptionStatus.APPROVED.value,
            "reason": "Bulk intake, references waived by Management", "created_at": NOW})
        made = await OF.create_offer(HR, COMPANY, offer("CAN-006"))
        check("a requisition-wide waiver covers everyone on that requisition",
              made["offer_no"].startswith("OFR-"))

        # =================================================================
        section("The client track is untouched")
        # =================================================================
        check("no reference exists for the client-track candidate",
              await RC.clearing_reference(COMPANY, "CAN-004") is None)
        made = await OF.create_offer(HR, COMPANY, offer("CAN-004"))
        check("and their offer is raised with no reference check at all",
              made["offer_no"].startswith("OFR-"))

        # A requisition raised before this phase carries no track field.
        await reqs.insert_one({
            "request_no": "HR-REQ-2025-900", "company_id": COMPANY,
            "designation_name": "Legacy", "approval_status": "Approved",
            "closing_status": "Open", "vacancy": 1, "created_at": NOW})
        await candidates.insert_one(cand("CAN-007", "HR-REQ-2025-900", "Legacy One"))
        made = await OF.create_offer(HR, COMPANY, offer("CAN-007"))
        check("a legacy requisition with no track field is not gated either",
              made["offer_no"].startswith("OFR-"))

        # =================================================================
        section("Editing a reference")
        # =================================================================
        updated = await RC.update_reference_check(
            HR, COMPANY, REF, {"responses": "Also confirmed the notice period."})
        check("a reference can be corrected", "notice period" in updated["responses"])
        check("editing is audited",
              any(a["action"] == M.AUDIT_REFERENCE_UPDATED for a in audit_log.docs))
        await expect_http(
            "flipping an outcome to Negative without a note",
            RC.update_reference_check(HR, COMPANY, REF,
                                      {"outcome": "Negative", "remarks": ""}),
            422, "cannot be acted on")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
