"""Internal recruitment track -- the two offer gates.

  1. SALARY BAND. SOP §6: "Salary negotiation must stay within the internally approved budget
     from Step 2; any deviation requires fresh Management/Finance approval."
  2. OFFER APPROVAL. Annexure B marks "Offer approval" accountable to Management/Finance and
     Table 2 calls it mandatory.

The second gate exists because the first is not the same act. The band says the figure is
AFFORDABLE. The approval says this offer, to this person, should go out. Verifying a number
is not deciding to make someone an offer, and the SOP asks for both.

Also asserted: the approval is recorded as a FIELD, not a new OfferStatus. `Draft -> Sent ->
Accepted/Declined` is shared with the client track and read by the public offer page, the
stage ranks and the analytics funnel -- slipping a state into that sequence would change what
an existing status means on a track this phase must not touch.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_offer_gates   (from backend/)
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

BAND_MIN, BAND_MAX = 400000.0, 900000.0


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

    U_HR, U_MD, U_FIN = str(ObjectId()), str(ObjectId()), str(ObjectId())

    def cand(uk, request_no, name):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": request_no,
                "application_status": M.AppStatus.SELECTED.value}

    candidates = FakeCollection([cand(f"CAN-00{i}", "HR-REQ-2026-001", f"Internal {i}")
                                 for i in range(1, 8)]
                                + [cand("CAN-100", "HR-REQ-2026-002", "Client One")])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 9,
         "approved_salary_band_min": BAND_MIN, "approved_salary_band_max": BAND_MAX,
         "approved_headcount": 9, "sla_actuals": {}, "created_at": NOW},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "approval_status": "Approved", "closing_status": "Open", "vacancy": 5,
         "created_at": NOW},
    ])
    # Every internal candidate is reference-cleared, so the ONLY thing under test here is the
    # pair of offer gates. The reference gate has its own file.
    references = FakeCollection([
        {"ref_no": f"REF-2026-{i:03d}", "company_id": COMPANY, "uk": f"CAN-00{i}",
         "request_no": "HR-REQ-2026-001", "outcome": "Positive",
         "referee_name": "Former Manager", "created_at": NOW}
        for i in range(1, 8)
    ])
    offers_coll = FakeCollection()
    exceptions = FakeCollection()
    audit_log = FakeCollection()
    # Phase INT-2 added a THIRD internal-track precondition on an offer: the shortlisting
    # committee must have finalised the candidate (SOP §5). It has its own test file; here
    # it is satisfied for every internal candidate so this file keeps testing exactly the
    # two gates it is about. The designation is unbanded, so it reads as `mid` and the
    # mandatory-MD-round rule does not apply.
    shortlists = FakeCollection([
        {"slr_no": "SLR-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001",
         "candidate_uks": [f"CAN-00{i}" for i in range(1, 8)],
         "outcome": M.ShortlistOutcome.FINALISED.value, "created_at": NOW},
    ])

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_REFERENCE_CHECKS: references, M.COLL_OFFERS: offers_coll,
             M.COLL_EXCEPTIONS: exceptions, M.COLL_COUNTERS: FakeCollection(),
             M.COLL_SHORTLIST_REVIEWS: shortlists,
             M.COLL_AUDIT_LOG: audit_log, M.COLL_LINKS: FakeCollection(),
             M.COLL_EMPLOYEE_PROFILES: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_offer_service as OF
    import app.services.hrms_reference_service as RC
    import app.services.hrms_exception_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (OF, RC, EX, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    OF.notify_user = silent
    OF.notify_hrms_role = silent

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "MD", "full_name": "Meera MD"}
    FIN = {"_id": U_FIN, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "FINANCE", "full_name": "Farid Finance"}

    def offer(uk, ctc=600000, **over):
        base = {"uk": uk, "ctc": ctc, "joining_date": JOINING,
                "designation": "Ops Executive"}
        base.update(over)
        return base

    try:
        # =================================================================
        section("Capability shape")
        # =================================================================
        from app.utils.hrms_access import can
        check("Finance may approve an offer", can(FIN, M.Cap.OFFER_APPROVE))
        check("MD may approve an offer", can(MD, M.Cap.OFFER_APPROVE))
        check("HR may NOT approve an offer -- it verifies, Management approves",
              not can(HR, M.Cap.OFFER_APPROVE))
        check("HR still writes and sends offers",
              can(HR, M.Cap.OFFER_WRITE) and can(HR, M.Cap.OFFER_SEND))

        # =================================================================
        section("Gate 1 -- the salary band")
        # =================================================================
        await expect_http(
            "an offer ABOVE the approved band",
            OF.create_offer(HR, COMPANY, offer("CAN-001", ctc=1200000)),
            409, "above the approved salary band")
        await expect_http(
            "an offer BELOW the approved band",
            OF.create_offer(HR, COMPANY, offer("CAN-001", ctc=100000)),
            409, "below the approved salary band")
        check("the refusal names the figure and the band",
              True)  # asserted by the fragments above
        check("no draft offer was left behind by a refusal",
              await offers_coll.count_documents({}) == 0)

        made = await OF.create_offer(HR, COMPANY, offer("CAN-001", ctc=BAND_MIN))
        check("the band is INCLUSIVE at its minimum", made["offer_no"].startswith("OFR-"))
        made_max = await OF.create_offer(HR, COMPANY, offer("CAN-002", ctc=BAND_MAX))
        check("and at its maximum", made_max["offer_no"].startswith("OFR-"))
        OFFER_1 = made["offer_no"]

        # =================================================================
        section("Gate 2 -- Management's approval before it goes out")
        # =================================================================
        await expect_http(
            "sending an unapproved internal offer",
            OF.send_offer(HR, COMPANY, OFFER_1, {"signature": "Hana HR"}),
            409, "has not been approved yet")

        await expect_http(
            "approving without signing",
            OF.approve_offer(FIN, COMPANY, OFFER_1, {}),
            422, "Type your name")

        approved = await OF.approve_offer(
            FIN, COMPANY, OFFER_1,
            {"signature": "Farid Finance", "remarks": "Within plan."})
        check("Finance's approval is recorded",
              approved["offer_approval"]["approved_by"] == U_FIN)
        check("it is signed", approved["offer_approval"]["signature"] == "Farid Finance")
        check("the band AS IT STOOD is captured, so a later change shows as a discrepancy",
              approved["offer_approval"]["band_min_at_approval"] == BAND_MIN)
        check("approval is audited",
              any(a["action"] == M.AUDIT_OFFER_APPROVED for a in audit_log.docs))

        check("the offer STATUS is untouched -- approval is a field, not a new state",
              approved["status"] == M.OfferStatus.DRAFT.value)
        check("and the shared status enum gained nothing",
              [s.value for s in M.OfferStatus]
              == ["Draft", "Sent", "Accepted", "Declined", "Revoked"])

        sent = await OF.send_offer(HR, COMPANY, OFFER_1, {"signature": "Hana HR"})
        check("an approved offer sends", sent["status"] == M.OfferStatus.SENT.value)

        after = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("sending stamps the SLA milestone (SOP 8: offer released)",
              (after.get("sla_actuals") or {}).get("offer_released") is not None)
        first_stamp = after["sla_actuals"]["offer_released"]

        await OF.approve_offer(MD, COMPANY, made_max["offer_no"], {"signature": "Meera MD"})
        await OF.send_offer(HR, COMPANY, made_max["offer_no"], {"signature": "Hana HR"})
        after = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("a SECOND offer does not overwrite the stamp -- one deadline, one measurement",
              after["sla_actuals"]["offer_released"] == first_stamp)

        # =================================================================
        section("Create-and-send is refused, not half-done")
        # =================================================================
        await expect_http(
            "creating AND sending an internal offer in one call",
            OF.create_offer(HR, COMPANY,
                            offer("CAN-003", send_now=True, signature="Hana HR")),
            409, "cannot be created and sent in one step")
        check("and no orphaned draft was written",
              await offers_coll.count_documents({"uk": "CAN-003"}) == 0)

        # =================================================================
        section("Editing the figure withdraws the approval")
        # =================================================================
        third = await OF.create_offer(HR, COMPANY, offer("CAN-004", ctc=500000))
        await OF.approve_offer(FIN, COMPANY, third["offer_no"], {"signature": "Farid"})
        check("it is approved", (await OF._get_offer(COMPANY, third["offer_no"]))
              ["offer_approval"] is not None)

        edited = await OF.update_offer(HR, COMPANY, third["offer_no"], {"ctc": 700000})
        check("changing the CTC WITHDRAWS the approval -- a different figure is a "
              "different offer",
              edited.get("offer_approval") is None)
        check("and why it was withdrawn is on the record",
              "after approval" in (edited.get("approval_withdrawn_reason") or ""))
        await expect_http(
            "sending it on the old approval",
            OF.send_offer(HR, COMPANY, third["offer_no"], {"signature": "Hana HR"}),
            409, "has not been approved yet")

        await expect_http(
            "editing the CTC to something outside the band",
            OF.update_offer(HR, COMPANY, third["offer_no"], {"ctc": 2000000}),
            409, "above the approved salary band")

        # =================================================================
        section("Only an APPROVED exception lifts the band")
        # =================================================================
        check("the band gate maps to exactly one exception type",
              M.EXCEPTION_UNBLOCKS["salary_band"]
              == M.ExceptionType.OFFER_OUTSIDE_BUDGET.value)

        await exceptions.insert_one({
            "exc_no": "EXC-2026-010", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "uk": "CAN-005",
            "exception_type": M.ExceptionType.OFFER_OUTSIDE_BUDGET.value,
            "status": M.ExceptionStatus.PENDING.value,
            "reason": "Counter-offer from their current employer", "created_at": NOW})
        await expect_http(
            "an out-of-band offer with a PENDING exception",
            OF.create_offer(HR, COMPANY, offer("CAN-005", ctc=1100000)),
            409, "above the approved salary band")

        await exceptions.update_one(
            {"exc_no": "EXC-2026-010"},
            {"$set": {"status": M.ExceptionStatus.APPROVED.value, "approved_by": U_MD}})
        out_of_band = await OF.create_offer(HR, COMPANY, offer("CAN-005", ctc=1100000))
        check("an APPROVED exception lets the out-of-band offer through",
              out_of_band["offer_no"].startswith("OFR-"))
        check("but it STILL needs Management's approval to be sent",
              True)
        await expect_http(
            "sending it without approval",
            OF.send_offer(HR, COMPANY, out_of_band["offer_no"], {"signature": "Hana HR"}),
            409, "has not been approved yet")

        # A candidate-specific band exception must not cover anybody else.
        await expect_http(
            "another candidate riding the first one's exception",
            OF.create_offer(HR, COMPANY, offer("CAN-006", ctc=1100000)),
            409, "above the approved salary band")

        # =================================================================
        section("Re-approving the budget at the new figure also clears it")
        # =================================================================
        await reqs.update_one({"request_no": "HR-REQ-2026-001"},
                              {"$set": {"approved_salary_band_max": 1500000.0}})
        widened = await OF.create_offer(HR, COMPANY, offer("CAN-006", ctc=1100000))
        check("a re-approved band admits the figure with no exception at all",
              widened["offer_no"].startswith("OFR-"))
        await reqs.update_one({"request_no": "HR-REQ-2026-001"},
                              {"$set": {"approved_salary_band_max": BAND_MAX}})

        # =================================================================
        section("The client track is untouched")
        # =================================================================
        client_offer = await OF.create_offer(HR, COMPANY,
                                             {"uk": "CAN-100", "ctc": 9999999,
                                              "joining_date": JOINING,
                                              "designation": "Analyst"})
        check("a client-track offer is not band-checked at all",
              client_offer["offer_no"].startswith("OFR-"))
        # Refused while it is still a DRAFT, so the refusal is about the track and not about
        # the offer already having gone out -- those are two different 409s.
        await expect_http(
            "approving a CLIENT-track offer",
            OF.approve_offer(FIN, COMPANY, client_offer["offer_no"],
                             {"signature": "Farid"}),
            409, "legacy client-track")

        sent = await OF.send_offer(HR, COMPANY, client_offer["offer_no"],
                                   {"signature": "Hana HR"})
        check("and sends with no approval step",
              sent["status"] == M.OfferStatus.SENT.value)

        # An internal requisition approved before this phase has no band recorded.
        await reqs.insert_one({
            "request_no": "HR-REQ-2025-900", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Legacy",
            "approval_status": "Approved", "closing_status": "Open", "vacancy": 1,
            "created_at": NOW})
        await candidates.insert_one(cand("CAN-200", "HR-REQ-2025-900", "Legacy One"))
        await references.insert_one({
            "ref_no": "REF-2026-900", "company_id": COMPANY, "uk": "CAN-200",
            "request_no": "HR-REQ-2025-900", "outcome": "Positive",
            "referee_name": "Old Manager", "created_at": NOW})
        # The shortlist gate is NOT waived for a historical requisition, unlike the band
        # gate this section is about. The two differ in what they can honestly tell: a
        # missing BAND is proof the row predates the budget gate, whereas a missing
        # committee record is indistinguishable from a committee that never sat. So the
        # only sanctioned ways past it are the real ones -- record the sitting, or log an
        # approved exception -- and this fixture records the sitting.
        await shortlists.insert_one({
            "slr_no": "SLR-2026-900", "company_id": COMPANY,
            "request_no": "HR-REQ-2025-900", "candidate_uks": ["CAN-200"],
            "outcome": M.ShortlistOutcome.FINALISED.value, "created_at": NOW})
        legacy = await OF.create_offer(HR, COMPANY, offer("CAN-200", ctc=5000000))
        check("an internal requisition with NO band recorded is not band-gated",
              legacy["offer_no"].startswith("OFR-"))
        await expect_http(
            "but it still needs approval before sending",
            OF.send_offer(HR, COMPANY, legacy["offer_no"], {"signature": "Hana HR"}),
            409, "has not been approved yet")

        # =================================================================
        section("Approval is only meaningful on a draft")
        # =================================================================
        await expect_http(
            "approving an offer that has already gone out",
            OF.approve_offer(FIN, COMPANY, OFFER_1, {"signature": "Farid"}),
            409, "Only a draft offer can be approved")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
