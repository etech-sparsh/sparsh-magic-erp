"""Phase INT-2 -- the four-band scoring decision guide (SOP §5, Part A §13).

The scorecard banded into THREE (>=4.0 Strong, <3.0 Below bar, else Consider). Both SOPs
define FOUR: >=4.0 Strong, 3.5-3.9 Consider, 3.0-3.4 Hold, <3.0 Reject.

This file walks every boundary. Boundaries are where a banding function goes wrong, and the
difference between Hold and Reject at exactly 3.0 is the difference between parking somebody
and turning them down.

It also re-asserts the property the previous phase established and this one must not lose:
THE BAND IS ADVICE. Scoring a candidate must never move them.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_score_bands   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR = str(ObjectId())

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": COMPANY,
         "candidate_name": "Test One", "request_no": "HR-REQ-2026-001",
         "application_status": M.AppStatus.SHORTLISTED.value},
    ])
    scorecards = FakeCollection([
        {"scr_no": "SCR-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "status": "Approved",
         "criteria": [{"label": "Skill", "category": "skill", "weight": 1,
                       "max_score": 5}]},
    ])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_POSITION_SCORECARDS: scorecards,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_audit_service as AUD
    for mod in (SC, AUD):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Four bands, not three")
        # =================================================================
        check("the table declares three floors plus a fallback",
              len(M.SCORE_BANDS) == 3 and M.SCORE_BAND_REJECT == "Reject")
        check("and runs highest floor first, so the first match wins",
              [floor for floor, _ in M.SCORE_BANDS] == sorted(
                  (floor for floor, _ in M.SCORE_BANDS), reverse=True))
        check("the four labels are the SOP's",
              [label for _, label in M.SCORE_BANDS] + [M.SCORE_BAND_REJECT]
              == ["Strong", "Consider", "Hold", "Reject"])

        # =================================================================
        section("Every boundary the brief names")
        # =================================================================
        boundaries = [
            (4.0,  "Strong",   "4.0 is Strong -- the floor is inclusive"),
            (3.9,  "Consider", "3.9 is Consider, one hundredth below Strong"),
            (3.5,  "Consider", "3.5 is Consider -- its floor is inclusive too"),
            (3.4,  "Hold",     "3.4 is Hold, one hundredth below Consider"),
            (3.0,  "Hold",     "3.0 is Hold, NOT Reject -- the SOP rejects BELOW 3.0"),
            (2.99, "Reject",   "2.99 is Reject"),
        ]
        for value, expected, label in boundaries:
            check(label, M.score_band(value) == expected)

        # =================================================================
        section("The edges of the scale, and non-numbers")
        # =================================================================
        check("the top of the scale is Strong", M.score_band(5.0) == "Strong")
        check("the bottom of the scale is Reject", M.score_band(1.0) == "Reject")
        check("an unscored candidate has NO band -- not a bad one",
              M.score_band(None) is None)
        check("an unreadable value is None rather than an exception",
              M.score_band("not a number") is None)
        check("an integer bands the same as its float",
              M.score_band(4) == M.score_band(4.0) == "Strong")

        # =================================================================
        section("The guide the UI renders cannot drift from the function")
        # =================================================================
        check("the guide names the same four bands, in descending order",
              [row["band"] for row in M.SCORE_BAND_GUIDE]
              == ["Strong", "Consider", "Hold", "Reject"])
        check("every band in the guide is one the function can actually return",
              all(row["band"] in {"Strong", "Consider", "Hold", "Reject"}
                  for row in M.SCORE_BAND_GUIDE))
        check("and every guide row carries advice a reader can act on",
              all(row.get("advice") for row in M.SCORE_BAND_GUIDE))

        # =================================================================
        section("Scoring returns BOTH the number and the band")
        # =================================================================
        for score, expected in ((5, "Strong"), (4, "Strong"), (3, "Hold"), (2, "Reject")):
            result = SC.compute_weighted(
                [{"label": "Skill", "weight": 1, "max_score": 5}], {"Skill": score})
            check(f"a raw {score} scores {float(score)} and bands as {expected}",
                  result["weighted_score"] == float(score)
                  and result["band"] == expected)

        # =================================================================
        section("The band is ADVICE -- it still moves nobody")
        # =================================================================
        before = (await candidates.find_one({"uk": "CAN-001"}))["application_status"]
        out = await SC.evaluate_candidate(HR, COMPANY, "CAN-001", {
            "scores": {"Skill": 2}, "signature": "Hana HR"})
        after = await candidates.find_one({"uk": "CAN-001"})
        check("a Reject-band score is recorded", out["band"] == "Reject")
        check("the candidate did NOT move", after["application_status"] == before)
        check("and the response says so outright", out["stage_changed"] is False)
        check("the flat reporting fields carry the new band",
              after["scorecard_band"] == "Reject" and after["scorecard_score"] == 2.0)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
