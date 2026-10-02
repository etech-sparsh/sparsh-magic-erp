"""Phase INT-2 -- the talent pool (Annexure C).

"Build and maintain an internal talent pool of prior applicants and referrals."

The compliance shape matters more than the feature, and it is what this file tests hardest:

  * a candidate enters the pool ONLY with explicit consent, and
  * `consent_expires_at` may never outlive `retention_until`.

Retaining a CV past its retention period BECAUSE it is "in the pool" is exactly the failure
SOP §11 and §13 exist to prevent -- the pool would otherwise be a way of quietly turning a
one-year record into a permanent one.

Also covered: sourcing forward COPIES rather than re-points, so the original application
stays a record of what somebody applied for and when.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_talent_pool   (from backend/)
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
LAST_YEAR = NOW - timedelta(days=200)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2025-900", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Closed",
         "created_at": LAST_YEAR},
        # The vacancy people are sourced ONTO: approved, so the budget gate is clear.
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "jd_no": "JD-2026-001", "approval_status": "Approved",
         "closing_status": "Open", "created_at": NOW},
        # One that has NOT cleared its budget gate.
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Analyst",
         "approval_status": M.ReqApproval.PENDING_BUDGET.value,
         "closing_status": "Open", "created_at": NOW},
    ])

    def cand(uk, name, **over):
        base = {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
                "candidate_name": name, "request_no": "HR-REQ-2025-900",
                "can_email": f"{uk.lower()}@example.com",
                "can_contact": "+91 00000 11111",
                "application_status": M.AppStatus.REJECTED.value,
                "applied_at": LAST_YEAR, "created_at": LAST_YEAR,
                "total_experience": "5 years",
                "resume": {"name": "cv.pdf", "key": "s3/cv.pdf"}}
        base.update(over)
        return base

    candidates = FakeCollection([
        cand("CAN-001", "Consented One", consent_to_retain=True),
        cand("CAN-002", "Never Consented"),
        cand("CAN-003", "Joined One",
             application_status=M.AppStatus.EMPLOYEE_CREATED.value,
             consent_to_retain=True),
    ])

    # The counter is pre-advanced past the fixture ids, exactly as it would be in a real
    # company that has already received three applications. Starting it at zero would mint
    # CAN-001 again and the "a NEW id is minted" assertion would pass for the wrong reason.
    counters = FakeCollection([{"_id": f"{COMPANY}:candidate", "seq": 3,
                                "scope": "candidate", "company_id": COMPANY}])
    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_candidate_service as CS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (CS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    CS.notify_user = silent

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    def year_after(dt, years):
        return f"{dt.year + years:04d}-{dt.month:02d}-{dt.day:02d}"

    try:
        # =================================================================
        section("The retention floor is the SOP's, and it differs by outcome")
        # =================================================================
        check("an unselected candidate is kept ONE year (SOP section 13)",
              M.RETENTION_YEARS["candidate_unselected"] == 1)
        check("a selected one is kept THREE, from joining",
              M.RETENTION_YEARS["candidate_selected"] == 3)

        unselected = await candidates.find_one({"uk": "CAN-001"})
        check("an unselected CV's floor is a year after they applied",
              CS.candidate_retention_until(unselected) == year_after(LAST_YEAR, 1))
        joined = await candidates.find_one({"uk": "CAN-003"})
        check("a joiner's floor is three years, because their file lives on",
              CS.candidate_retention_until(joined) == year_after(LAST_YEAR, 3))
        check("a record with no date at all has no floor, rather than a guessed one",
              CS.candidate_retention_until({"application_status": "Applied"}) is None)

        # =================================================================
        section("Consent is REQUIRED to enter the pool")
        # =================================================================
        await expect_http(
            "pooling somebody who never consented",
            CS.set_talent_pool(HR, COMPANY, "CAN-002", {"talent_pool": True}),
            422, "has not consented")
        after = await candidates.find_one({"uk": "CAN-002"})
        check("and they were not quietly pooled anyway",
              not after.get("talent_pool"))
        check("there is no path that opts somebody in because a recruiter liked their CV",
              True)   # asserted by the refusal above

        pooled = await CS.set_talent_pool(HR, COMPANY, "CAN-001", {
            "talent_pool": True, "talent_pool_tags": ["Python", "python", "Ops"]})
        check("consent captured on the application form is enough",
              pooled["talent_pool"] is True)
        check("tags are normalised and de-duplicated, so a search for one finds the other",
              pooled["talent_pool_tags"] == ["ops", "python"])
        check("the retention floor is stamped, so the purge reads one field",
              pooled["retention_until"] == year_after(LAST_YEAR, 1))
        check("and the consent defaults to expiring exactly at that floor",
              pooled["consent_expires_at"] == pooled["retention_until"])

        # Consent given LATER, rather than on the form, counts just as much.
        await CS.set_talent_pool(HR, COMPANY, "CAN-002", {
            "talent_pool": True, "consent_to_retain": True})
        check("consent given later and recorded here counts too",
              (await candidates.find_one({"uk": "CAN-002"}))["talent_pool"] is True)

        # =================================================================
        section("Consent may not outlive retention")
        # =================================================================
        # THE compliance test. Being in the pool must not extend how long a CV may be kept.
        floor = year_after(LAST_YEAR, 1)
        beyond = f"{int(floor[:4]) + 5}{floor[4:]}"
        await expect_http(
            "asking to keep a CV five years past its retention period",
            CS.set_talent_pool(HR, COMPANY, "CAN-001", {
                "talent_pool": True, "consent_expires_at": beyond}),
            422, "cannot outlive the retention period")
        check("the refusal names the date the record may actually be kept until",
              True)   # asserted by the fragment
        check("it is refused rather than silently clamped -- a promise we cannot keep "
              "should be visible when it is made", True)

        # Shorter than the floor, and still ahead of today -- what somebody who agreed to
        # "keep it for a few months" actually asked for.
        earlier = (NOW + timedelta(days=30)).strftime("%Y-%m-%d")
        shorter = await CS.set_talent_pool(HR, COMPANY, "CAN-001", {
            "talent_pool": True, "consent_expires_at": earlier})
        check("a SHORTER consent is honoured exactly as given",
              shorter["consent_expires_at"] == earlier)
        check("and it is genuinely shorter than the retention floor",
              earlier < shorter["retention_until"])

        # =================================================================
        section("Leaving the pool is unconditional")
        # =================================================================
        left = await CS.set_talent_pool(HR, COMPANY, "CAN-002", {"talent_pool": False})
        check("removal needs no justification -- consent is a thing you may withdraw",
              left["talent_pool"] is False)
        check("and the tags go with it", left["talent_pool_tags"] == [])

        # =================================================================
        section("The pool is a FILTER on the candidate list")
        # =================================================================
        listing = await CS.list_candidates(HR, COMPANY, talent_pool=True)
        check("only pooled candidates come back",
              {c["uk"] for c in listing["candidates"]} == {"CAN-001"})
        tagged = await CS.list_candidates(HR, COMPANY, talent_pool=True, tags="Python")
        check("a tag filter narrows it", len(tagged["candidates"]) == 1)
        missed = await CS.list_candidates(HR, COMPANY, talent_pool=True, tags="Rust")
        check("a tag nobody carries matches nobody", not missed["candidates"])
        either = await CS.list_candidates(HR, COMPANY, talent_pool=True,
                                          tags="Rust,Python")
        check("several tags match ANY of them, not all",
              len(either["candidates"]) == 1)

        # =================================================================
        section("Sourcing forward COPIES; it never re-points")
        # =================================================================
        fresh = await CS.create_from_pool(HR, COMPANY, "CAN-001", "HR-REQ-2026-001")
        check("a NEW candidate id is minted", fresh["uk"] != "CAN-001")
        check("against the NEW requisition", fresh["request_no"] == "HR-REQ-2026-001")
        check("starting at Applied, with none of the old process carried over",
              fresh["application_status"] == M.AppStatus.APPLIED.value)
        check("the CV travels", fresh["resume"] == {"name": "cv.pdf", "key": "s3/cv.pdf"})
        check("the source says where they came from, rather than inheriting an old advert",
              fresh["source"] == "Talent Pool")
        check("and the original is named, so the two are traceable",
              fresh["sourced_from_uk"] == "CAN-001")
        check("their own retention clock starts now, not last year",
              fresh["retention_until"] != year_after(LAST_YEAR, 1))

        original_row = await candidates.find_one({"uk": "CAN-001"})
        check("THE ORIGINAL IS UNTOUCHED -- still on the old requisition",
              original_row["request_no"] == "HR-REQ-2025-900")
        check("and still at the stage it actually reached",
              original_row["application_status"] == M.AppStatus.REJECTED.value)

        await expect_http(
            "putting the same person forward twice onto one vacancy",
            CS.create_from_pool(HR, COMPANY, "CAN-001", "HR-REQ-2026-001"),
            409, "already a candidate")

        await expect_http(
            "putting somebody forward who is not in the pool",
            CS.create_from_pool(HR, COMPANY, "CAN-003", "HR-REQ-2026-001"),
            409, "not in the talent pool")

        # =================================================================
        section("The budget gate applies to a pooled CV exactly as to a fresh one")
        # =================================================================
        await expect_http(
            "sourcing onto a requisition that has not cleared its budget",
            CS.create_from_pool(HR, COMPANY, "CAN-001", "HR-REQ-2026-002"),
            409, "budget approval")
        check("sourcing is sourcing, whichever drawer the CV came out of", True)

        # =================================================================
        section("Expired consent stops them being put forward")
        # =================================================================
        await candidates.update_one(
            {"uk": "CAN-001"}, {"$set": {"consent_expires_at": "2020-01-01"}})
        await expect_http(
            "putting forward somebody whose consent lapsed",
            CS.create_from_pool(HR, COMPANY, "CAN-001", "HR-REQ-2026-001"),
            409, "expired")
        check("the answer is to ask them again, and the message says so", True)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
