"""Salary above the approved budget -- HR asks Finance, and the answer is a FIGURE.

SOP section 6 / the negotiation flow:

  * negotiated salary inside the approved budget -> proceed
  * above it -> HR raises a budget approval request to Finance, and the candidate may only
    be finalised at the higher salary AFTER Finance approves the additional budget
  * Finance refuses -> renegotiate inside the band, or reject the candidate

The machinery for this already existed: an Offer Outside Budget exception, raised by HR,
approved by Finance, checked by `assert_within_band`. What it did NOT do was carry a number.

That is the property this file exists for. An approval used to be a boolean, so the gate
returned the moment it found one -- which meant Finance approving thirteen lakh cleared an
offer of thirty. "Only after Finance approves the ADDITIONAL BUDGET" is a statement about an
amount, and a control that ignores the amount is not enforcing it.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_budget_approval_request   (from backend/)
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

BAND_MIN, BAND_MAX = 400000.0, 900000.0


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_FIN, U_MD = (str(ObjectId()) for _ in range(3))

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_FIN), "full_name": "Farid Finance", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "FINANCE"},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "company_id": COMPANY,
         "role": "clientadmin", "governance_role": "MD"},
    ])

    def cand(uk, name):
        return {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": "R1",
                "application_status": M.AppStatus.SELECTED.value}

    candidates = FakeCollection([cand("CAN-001", "Asha Ask"),
                                 cand("CAN-002", "Bela Bid")])
    reqs = FakeCollection([
        {"request_no": "R1", "company_id": COMPANY, "requisition_track": "internal",
         "designation_name": "Ops Executive", "approval_status": "Approved",
         "closing_status": "Open", "vacancy": 5,
         "approved_salary_band_min": BAND_MIN, "approved_salary_band_max": BAND_MAX,
         "sla_actuals": {}, "created_at": NOW},
    ])
    exceptions_coll = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, M.COLL_REQUISITIONS: reqs,
             M.COLL_EXCEPTIONS: exceptions_coll, M.COLL_OFFERS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": learners, "staff": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_exception_service as EX
    import app.services.hrms_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HACC
    for mod in (EX, OF, AUD, IDS, HACC):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    EX.notify_hrms_role = silent
    try:
        import app.services.hrms_notify_service as NS
        NS.notify_hrms_role = silent
        NS.notify_user = silent
    except Exception:
        pass

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": {"HR": "Hana HR", "FINANCE": "Farid Finance",
                              "MD": "Meera MD"}[governance]}

    HR = actor(U_HR, "HR")
    FIN = actor(U_FIN, "FINANCE")
    req = await reqs.find_one({"request_no": "R1"})

    async def band_check(ctc, uk="CAN-001"):
        c = await candidates.find_one({"uk": uk})
        await OF.assert_within_band(COMPANY, ctc, c, req)

    try:
        # =================================================================
        section("Inside the approved budget -- nothing to ask anybody")
        # =================================================================
        await band_check(850000)
        check("an offer inside the band passes with no exception at all", True)

        await expect_http(
            "an offer above the band is refused",
            band_check(1300000), 409, "above the approved salary band")

        # =================================================================
        section("The request to Finance has to name a figure")
        # =================================================================
        await expect_http(
            "asking for 'more budget' with no number",
            EX.raise_exception(HR, COMPANY, {
                "request_no": "R1", "uk": "CAN-001",
                "exception_type": "Offer Outside Budget",
                "reason": "She will not move below thirteen."}),
            422, "no number")

        await expect_http(
            "asking for a figure already inside the band",
            EX.raise_exception(HR, COMPANY, {
                "request_no": "R1", "uk": "CAN-001",
                "exception_type": "Offer Outside Budget", "requested_ctc": 700000,
                "reason": "Belt and braces."}),
            422, "already inside the approved band")

        # =================================================================
        section("HR asks, Finance decides -- and HR cannot decide it themselves")
        # =================================================================
        exc = await EX.raise_exception(HR, COMPANY, {
            "request_no": "R1", "uk": "CAN-001",
            "exception_type": "Offer Outside Budget", "requested_ctc": 1300000,
            "reason": "She will not move below thirteen and we have no second choice."})
        check("the request records what was asked for",
              exc["requested_ctc"] == 1300000)
        check("and the band it is a deviation from",
              exc["band_max_at_request"] == BAND_MAX)
        check("nothing is granted yet", exc["approved_ctc"] is None
              and exc["status"] == M.ExceptionStatus.PENDING.value)

        await expect_http(
            "a pending request does not lift the gate",
            band_check(1300000), 409, "above the approved salary band")

        await expect_http(
            "HR approving their own request",
            EX.decide_exception(HR, COMPANY, exc["exc_no"], {
                "decision": "Approved", "signature": "Hana HR"}),
            409, "cannot approve it")

        # =================================================================
        section("Finance may grant less than was asked -- and never more")
        # =================================================================
        await expect_http(
            "approving ABOVE the requested figure",
            EX.decide_exception(FIN, COMPANY, exc["exc_no"], {
                "decision": "Approved", "approved_ctc": 2000000,
                "signature": "Farid Finance"}),
            422, "more than the")

        decided = await EX.decide_exception(FIN, COMPANY, exc["exc_no"], {
            "decision": "Approved", "approved_ctc": 1100000,
            "remarks": "Eleven, not thirteen.", "signature": "Farid Finance"})
        check("Finance granted less than was requested",
              decided["approved_ctc"] == 1100000
              and decided["requested_ctc"] == 1300000)

        # =================================================================
        section("The offer is held to the figure Finance approved")
        # =================================================================
        await band_check(1100000)
        check("an offer AT the approved figure passes", True)
        await band_check(1050000)
        check("an offer below it passes too", True)

        await expect_http(
            "an offer above what Finance approved",
            band_check(1300000), 409, "more than the 1,100,000 finance approved")
        check("...the amount is enforced, not just the existence of an approval", True)

        await expect_http(
            "and a wildly higher one",
            band_check(3000000), 409, "finance approved")

        # =================================================================
        section("A waiver is as narrow as it was written")
        # =================================================================
        await expect_http(
            "another candidate on the same requisition is not covered",
            band_check(1100000, uk="CAN-002"), 409, "above the approved salary band")

        # =================================================================
        section("A refusal leaves the gate exactly where it was")
        # =================================================================
        exc2 = await EX.raise_exception(HR, COMPANY, {
            "request_no": "R1", "uk": "CAN-002",
            "exception_type": "Offer Outside Budget", "requested_ctc": 1500000,
            "reason": "He is asking fifteen."})
        await EX.decide_exception(FIN, COMPANY, exc2["exc_no"], {
            "decision": "Rejected", "remarks": "Not for this grade.",
            "signature": "Farid Finance"})
        await expect_http(
            "a REFUSED request grants nothing",
            band_check(1500000, uk="CAN-002"), 409, "above the approved salary band")
        await band_check(850000, uk="CAN-002")
        check("HR can still offer inside the band after a refusal", True)

        # =================================================================
        section("Legacy rows, written before the figure was recorded")
        # =================================================================
        await exceptions_coll.insert_one({
            "exc_no": "EXC-LEGACY", "company_id": COMPANY, "request_no": "R1",
            "uk": "CAN-002", "exception_type": "Offer Outside Budget",
            "gate": "salary_band", "status": M.ExceptionStatus.APPROVED.value,
            "created_at": NOW})
        await band_check(2500000, uk="CAN-002")
        check("an approval with no figure still lifts the gate, as it always did", True)
        check("salary_exception_ceiling reports it as unbounded",
              M.salary_exception_ceiling({"exception_type": "Offer Outside Budget"})
              is None)
        check("and reads the granted figure when there is one",
              M.salary_exception_ceiling({"approved_ctc": 1100000,
                                          "requested_ctc": 1300000}) == 1100000)
        check("falling back to the requested figure if a decision predates approved_ctc",
              M.salary_exception_ceiling({"requested_ctc": 1300000}) == 1300000)
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 62}\n  {passed}/{total} checks passed\n{'=' * 62}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
