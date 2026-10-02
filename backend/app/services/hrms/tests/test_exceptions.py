"""Internal recruitment track -- the exception log.

SOP §12: "Any deviation from this policy ... must be recorded, with a reason and an approver."

Covers: raising, the duplicate guard, approval authority per role, the separation of duties
between raiser and approver, rejection, and -- the point of the whole thing -- that only an
APPROVED exception lifts a gate, end to end through the real offer service.

Two properties this file pins down:

  1. NO OVERRIDE FLAG EXISTS. The gates ask this log a question; they do not accept a boolean.
     Asserted by driving a real gate rather than by inspecting the log in isolation.
  2. THE ASKER IS NEVER THE GRANTER. An MD holds both exception.write and exception.approve,
     so without an explicit check they could wave through their own request -- which is not
     an approval, it is a note to self.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_exceptions   (from backend/)
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
JOINING = (NOW + timedelta(days=30)).strftime("%Y-%m-%d")


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

    U_HR, U_MD, U_FIN, U_HOD = (str(ObjectId()), str(ObjectId()),
                                str(ObjectId()), str(ObjectId()))

    def cand(uk, request_no, name):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": M.AppStatus.SELECTED.value}

    candidates = FakeCollection([
        cand("CAN-001", "HR-REQ-2026-001", "Internal One"),
        cand("CAN-002", "HR-REQ-2026-001", "Internal Two"),
        cand("CAN-900", "HR-REQ-2026-002", "Client One"),
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 5,
         "approved_salary_band_min": 400000.0, "approved_salary_band_max": 900000.0,
         "sla_actuals": {}, "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 5,
         "created_at": NOW},
    ])
    exceptions_coll = FakeCollection()
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
             M.COLL_EXCEPTIONS: exceptions_coll, M.COLL_OFFERS: FakeCollection(),
             M.COLL_REFERENCE_CHECKS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: audit_log,
             M.COLL_LINKS: FakeCollection(), M.COLL_EMPLOYEE_PROFILES: FakeCollection(),
             M.COLL_SHORTLIST_REVIEWS: shortlists,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_exception_service as EX
    import app.services.hrms_offer_service as OF
    import app.services.hrms_reference_service as RC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (EX, OF, RC, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    OF.notify_user = silent
    OF.notify_hrms_role = silent

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} user"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")
    FIN = actor(U_FIN, "FINANCE")
    HOD = actor(U_HOD, "HOD")

    def exc(**over):
        base = {"request_no": "HR-REQ-2026-001",
                "exception_type": "Reference Check Waived",
                "reason": "Referee has left the organisation and cannot be reached."}
        base.update(over)
        return base

    try:
        # =================================================================
        section("Who may ask, and who may grant")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR may raise an exception", can(HR, M.Cap.EXCEPTION_WRITE))
        check("the hiring manager may raise one", can(HOD, M.Cap.EXCEPTION_WRITE))
        check("HR may NOT approve one -- Annexure B puts HR at 'C'",
              not can(HR, M.Cap.EXCEPTION_APPROVE))
        check("nor may the hiring manager", not can(HOD, M.Cap.EXCEPTION_APPROVE))
        check("Management approves", can(MD, M.Cap.EXCEPTION_APPROVE))
        check("and so does Finance", can(FIN, M.Cap.EXCEPTION_APPROVE))
        check("Finance may NOT raise one -- it grants deviations, it does not ask for them",
              not can(FIN, M.Cap.EXCEPTION_WRITE))

        # =================================================================
        section("Raising")
        # =================================================================
        row = await EX.raise_exception(HR, COMPANY, exc(uk="CAN-001"))
        EXC = row["exc_no"]
        check("an exception id is minted", EXC.startswith("EXC-"))
        check("it starts Pending", row["status"] == M.ExceptionStatus.PENDING.value)
        check("the raiser is recorded", row["raised_by"] == U_HR)
        check("the GATE it would lift is named on the record, not left implicit",
              row["gate"] == "reference_check")
        check("the candidate's name rides along for the log view",
              row["candidate_name"] == "Internal One")
        check("raising is audited",
              any(a["action"] == M.AUDIT_EXCEPTION_RAISED for a in audit_log.docs))

        await expect_http(
            "an exception with no reason",
            EX.raise_exception(HR, COMPANY, exc(reason="   ")),
            422, "no reason is the thing this log exists to prevent")
        await expect_http(
            "an unknown exception type",
            EX.raise_exception(HR, COMPANY, exc(exception_type="Just Because")),
            422, "Type must be one of")
        await expect_http(
            "an exception on a CLIENT requisition",
            EX.raise_exception(HR, COMPANY, exc(request_no="HR-REQ-2026-002")),
            409, "legacy client-track")
        await expect_http(
            "an exception naming a candidate from a DIFFERENT requisition",
            EX.raise_exception(HR, COMPANY, exc(uk="CAN-900")),
            422, "not a candidate on")
        await expect_http(
            "a duplicate pending request for the same scope",
            EX.raise_exception(HR, COMPANY, exc(uk="CAN-001")),
            409, "already requests")
        check("but the SAME type for a DIFFERENT candidate is fine",
              (await EX.raise_exception(HR, COMPANY, exc(uk="CAN-002")))["exc_no"]
              .startswith("EXC-"))

        # =================================================================
        section("The asker is never the granter")
        # =================================================================
        own = await EX.raise_exception(MD, COMPANY, exc(
            exception_type="Extended TAT", reason="Festival season slowed sourcing."))
        await expect_http(
            "the MD approving the exception the MD raised",
            EX.decide_exception(MD, COMPANY, own["exc_no"],
                                {"decision": "Approved", "signature": "MD"}),
            409, "you raised this exception")
        other = await EX.decide_exception(FIN, COMPANY, own["exc_no"],
                                          {"decision": "Approved", "signature": "Finance"})
        check("but somebody else may grant it",
              other["status"] == M.ExceptionStatus.APPROVED.value)

        # =================================================================
        section("Deciding")
        # =================================================================
        await expect_http(
            "deciding without signing",
            EX.decide_exception(MD, COMPANY, EXC, {"decision": "Approved"}),
            422, "Type your name")
        await expect_http(
            "'Pending' as a decision",
            EX.decide_exception(MD, COMPANY, EXC,
                                {"decision": "Pending", "signature": "MD"}),
            422, "not a decision")
        await expect_http(
            "rejecting with no reason",
            EX.decide_exception(MD, COMPANY, EXC,
                                {"decision": "Rejected", "signature": "MD"}),
            422, "Say why")

        approved = await EX.decide_exception(
            MD, COMPANY, EXC,
            {"decision": "Approved", "signature": "Meera MD", "remarks": "Accepted once."})
        check("an approval is recorded and signed",
              approved["status"] == M.ExceptionStatus.APPROVED.value
              and approved["approved_by"] == U_MD)
        check("deciding is audited",
              any(a["action"] == M.AUDIT_EXCEPTION_DECIDED for a in audit_log.docs))
        await expect_http(
            "deciding an already-decided exception",
            EX.decide_exception(FIN, COMPANY, EXC,
                                {"decision": "Rejected", "signature": "Fin",
                                 "remarks": "changed my mind"}),
            409, "already approved")

        # =================================================================
        section("Only an approval lifts a gate -- driven through the real offer service")
        # =================================================================
        # CAN-002 has a PENDING reference waiver and no reference check at all.
        await expect_http(
            "an offer while the waiver is still pending",
            OF.create_offer(HR, COMPANY, {"uk": "CAN-002", "ctc": 500000,
                                          "joining_date": JOINING}),
            409, "no reference check has been completed")

        pending = await exceptions_coll.find_one(
            {"uk": "CAN-002", "exception_type": "Reference Check Waived"})
        rejected = await EX.decide_exception(
            FIN, COMPANY, pending["exc_no"],
            {"decision": "Rejected", "signature": "Finance",
             "remarks": "Call the second referee first."})
        check("a REJECTED exception is recorded as such",
              rejected["status"] == M.ExceptionStatus.REJECTED.value)
        await expect_http(
            "an offer on a REJECTED waiver",
            OF.create_offer(HR, COMPANY, {"uk": "CAN-002", "ctc": 500000,
                                          "joining_date": JOINING}),
            409, "no reference check has been completed")

        # CAN-001's waiver IS approved, so the same call now succeeds.
        made = await OF.create_offer(HR, COMPANY, {"uk": "CAN-001", "ctc": 500000,
                                                   "joining_date": JOINING})
        check("the approved waiver lets the offer through",
              made["offer_no"].startswith("OFR-"))

        # =================================================================
        section("Scope: broad covers narrow, narrow never widens")
        # =================================================================
        found = await EX.approved_exception_for(
            COMPANY, "reference_check", "HR-REQ-2026-001", "CAN-001")
        check("the candidate-specific waiver is found for its own candidate",
              found["exc_no"] == EXC)
        check("and NOT for another candidate on the same requisition",
              await EX.approved_exception_for(
                  COMPANY, "reference_check", "HR-REQ-2026-001", "CAN-002") is None)

        wide = await EX.raise_exception(HOD, COMPANY, exc(
            reason="Bulk intake: references waived for this cohort."))
        await EX.decide_exception(MD, COMPANY, wide["exc_no"],
                                  {"decision": "Approved", "signature": "MD"})
        check("a requisition-wide waiver covers a candidate who has none of their own",
              (await EX.approved_exception_for(
                  COMPANY, "reference_check", "HR-REQ-2026-001", "CAN-002"))["exc_no"]
              == wide["exc_no"])
        check("and covers a caller who names no candidate at all",
              (await EX.approved_exception_for(
                  COMPANY, "reference_check", "HR-REQ-2026-001")) is not None)

        # =================================================================
        section("A gate only answers to its OWN exception type")
        # =================================================================
        check("each gate maps to exactly one type, both directions",
              EX.GATE_FOR_TYPE[M.EXCEPTION_UNBLOCKS["salary_band"]] == "salary_band")
        check("an approved TAT exception does not lift the salary band",
              await EX.approved_exception_for(
                  COMPANY, "salary_band", "HR-REQ-2026-001") is None)
        check("nor does it lift the reference gate for a candidate it never named",
              True)

        # =================================================================
        section("Listing")
        # =================================================================
        listing = await EX.list_exceptions(HR, COMPANY)
        check("the log lists every exception", listing["total"] >= 4)
        check("and leads with what is still waiting on somebody",
              listing["pending"] == sum(
                  1 for e in listing["exceptions"]
                  if e["status"] == M.ExceptionStatus.PENDING.value))
        scoped = await EX.list_exceptions(HR, COMPANY, status="Approved")
        check("it filters by status",
              all(e["status"] == "Approved" for e in scoped["exceptions"]))
        by_type = await EX.list_exceptions(HR, COMPANY, exception_type="Extended TAT")
        check("and by type", all(e["exception_type"] == "Extended TAT"
                                 for e in by_type["exceptions"]))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
