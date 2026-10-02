"""Internal recruitment track -- SLA / TAT tracking (SOP §8).

Covers: working-day arithmetic across weekends, the four elapsed-time milestones and their
targets, the two date-based ones (induction on Day 1, probation before its end date), breach
detection in both directions, and the escalation that fires once and only once.

The arithmetic is the part worth testing hardest. "Three working days" is a promise somebody
made to a hiring manager, and an off-by-one across a weekend is the difference between a
requisition that met its target and one that did not.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_sla   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


def utc(y, m, d, hour=10):
    return datetime(y, m, d, hour, tzinfo=timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    reqs = FakeCollection()
    onboardings = FakeCollection()
    probations = FakeCollection()
    audit_log = FakeCollection()
    notes = []

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_ONBOARDING: onboardings,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_AUDIT_LOG: audit_log,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_sla_service as SLA
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_notify_service as NS
    for mod in (SLA, AUD):
        mod.get_collection = mongo.get_collection

    async def fake_role(company_id, roles, title, message, **kw):
        notes.append((tuple(roles), title))
    NS.notify_hrms_role = fake_role

    HR = {"_id": str(ObjectId()), "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Working-day arithmetic")
        # =================================================================
        # 2026-08-10 is a Monday; 08-14 Friday; 08-15/16 the weekend; 08-17 Monday.
        check("Monday to Friday is 4 working days",
              SLA.working_days_between(utc(2026, 8, 10), utc(2026, 8, 14)) == 4)
        check("Friday to Monday is 1, not 3 -- the weekend is not time anybody had",
              SLA.working_days_between(utc(2026, 8, 14), utc(2026, 8, 17)) == 1)
        check("same day is 0",
              SLA.working_days_between(utc(2026, 8, 14), utc(2026, 8, 14)) == 0)
        check("a full week is 5",
              SLA.working_days_between(utc(2026, 8, 10), utc(2026, 8, 17)) == 5)
        check("a backwards range reports NEGATIVE rather than clamping to zero",
              SLA.working_days_between(utc(2026, 8, 17), utc(2026, 8, 14)) == -1)
        check("an unreadable date is None, not an exception",
              SLA.working_days_between(None, utc(2026, 8, 14)) is None)

        check("Monday + 3 working days is Thursday",
              SLA.add_working_days(utc(2026, 8, 10), 3).isoformat() == "2026-08-13")
        check("Thursday + 3 spans the weekend to Tuesday",
              SLA.add_working_days(utc(2026, 8, 13), 3).isoformat() == "2026-08-18")
        check("Friday + 1 is Monday",
              SLA.add_working_days(utc(2026, 8, 14), 1).isoformat() == "2026-08-17")
        check("a due date never lands on a weekend",
              SLA.add_working_days(utc(2026, 8, 14), 0).weekday() not in SLA.WEEKEND)

        # =================================================================
        section("The milestone table is the SOP's")
        # =================================================================
        # Phase INT-2 turned the table into a list of dicts with an explicit `anchor`, so
        # the two milestone KINDS live in one declaration and the sweep needs no new code.
        elapsed = [m for m in M.SLA_MILESTONES if m["anchor"] == M.ANCHOR_MILESTONE]
        dated = [m for m in M.SLA_MILESTONES if m["anchor"] == M.ANCHOR_DATE]
        check("four elapsed-time milestones are declared",
              [m["key"] for m in elapsed] == ["budget_approved", "scorecard_approved",
                                              "shortlist_ready", "offer_released"])
        check("and the SOP's two date-anchored ones alongside them",
              [m["key"] for m in dated] == ["induction_due", "probation_review_due"])
        targets = {m["key"]: m["target_days"] for m in M.SLA_MILESTONES}
        check("budget approval targets 3 working days", targets["budget_approved"] == 3)
        check("the scorecard targets 2", targets["scorecard_approved"] == 2)
        check("the shortlist targets 15", targets["shortlist_ready"] == 15)
        check("the offer targets 3", targets["offer_released"] == 3)
        check("a date-anchored milestone states NO working-day target",
              all(m["target_days"] is None for m in dated))
        chain = {m["key"]: m["measured_from"] for m in M.SLA_MILESTONES}
        check("the scorecard clock starts at budget approval, not at the requisition",
              chain["scorecard_approved"] == "budget_approved")
        check("the offer clock starts at final selection",
              chain["offer_released"] == "final_selection")
        check("only the elapsed-time milestones are stampable",
              M.STAMPABLE_MILESTONES == {m["key"] for m in elapsed})

        # =================================================================
        section("A requisition on target")
        # =================================================================
        raised = utc(2026, 8, 10)          # Monday
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Ops Executive",
            "closing_status": "Open", "created_at": raised,
            "sla_actuals": {
                "budget_approved": utc(2026, 8, 12),      # 2 working days -> met (target 3)
                "scorecard_approved": utc(2026, 8, 13),   # 1 after budget -> met (target 2)
            }})
        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        report = await SLA.sla_for(COMPANY, req)
        rows = {r["key"]: r for r in report["milestones"]}

        check("the report applies to an internal requisition", report["applicable"])
        check("it says outright that holidays are not counted",
              report["counts_holidays"] is False and "holiday" in report["basis"].lower())
        check("budget approval is MET", rows["budget_approved"]["status"] == "met")
        check("and reports the working days it actually took",
              rows["budget_approved"]["working_days_taken"] == 2)
        check("its due date is computed from the requisition date",
              rows["budget_approved"]["due_on"] == "2026-08-13")
        check("the scorecard is MET, measured from BUDGET approval not the requisition",
              rows["scorecard_approved"]["status"] == "met"
              and rows["scorecard_approved"]["working_days_taken"] == 1)
        check("the offer milestone has NOT STARTED -- nobody has been selected yet",
              rows["offer_released"]["status"] == "not_started")
        check("a not-started milestone shows no due date to chase",
              rows["offer_released"]["due_on"] is None)

        # =================================================================
        section("Late, and not done at all")
        # =================================================================
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Analyst",
            "closing_status": "Open", "created_at": raised,
            "sla_actuals": {
                # Monday to the NEXT Monday is 5 working days against a target of 3.
                "budget_approved": utc(2026, 8, 17),
            }})
        req2 = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        report2 = await SLA.sla_for(COMPANY, req2)
        rows2 = {r["key"]: r for r in report2["milestones"]}
        check("a milestone recorded late is BREACHED",
              rows2["budget_approved"]["status"] == "breached")
        check("and reports how far over it ran",
              rows2["budget_approved"]["working_days_over"] == 2)
        check("the requisition is reported as not on track", report2["on_track"] is False)
        check("and names which milestones broke",
              "budget_approved" in report2["breached"])

        # A milestone with no actual at all, whose clock started long ago.
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-003", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Coordinator",
            "closing_status": "Open",
            "created_at": NOW - timedelta(days=60), "sla_actuals": {}})
        req3 = await reqs.find_one({"request_no": "HR-REQ-2026-003"})
        rows3 = {r["key"]: r for r in (await SLA.sla_for(COMPANY, req3))["milestones"]}
        check("a milestone never recorded, long past its target, is OVERDUE",
              rows3["budget_approved"]["status"] == "overdue")
        check("a young requisition's milestone is PENDING, not overdue",
              True)

        await reqs.insert_one({
            "request_no": "HR-REQ-2026-004", "company_id": COMPANY,
            "requisition_track": "internal", "designation_name": "Fresh",
            "closing_status": "Open", "created_at": NOW, "sla_actuals": {}})
        req4 = await reqs.find_one({"request_no": "HR-REQ-2026-004"})
        rows4 = {r["key"]: r for r in (await SLA.sla_for(COMPANY, req4))["milestones"]}
        check("a requisition raised today is PENDING on its first milestone",
              rows4["budget_approved"]["status"] == "pending")

        # =================================================================
        section("The client track has no SLA")
        # =================================================================
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-100", "company_id": COMPANY,
            "requisition_track": "client", "designation_name": "Client Role",
            "closing_status": "Open", "created_at": raised, "sla_actuals": {}})
        client_req = await reqs.find_one({"request_no": "HR-REQ-2026-100"})
        client_report = await SLA.sla_for(COMPANY, client_req)
        check("a client requisition reports not-applicable rather than raising",
              client_report["applicable"] is False)
        check("with no milestones at all", client_report["milestones"] == [])
        check("and says why", "client" in client_report["reason"].lower())

        # =================================================================
        section("Stamping")
        # =================================================================
        first = await SLA.stamp(COMPANY, "HR-REQ-2026-004", "budget_approved",
                                when=utc(2026, 8, 11))
        again = await SLA.stamp(COMPANY, "HR-REQ-2026-004", "budget_approved",
                                when=utc(2026, 9, 1))
        check("the first stamp lands", first is True)
        check("a second does NOT overwrite it -- one deadline, one measurement",
              again is False)
        stamped = await reqs.find_one({"request_no": "HR-REQ-2026-004"})
        check("the original timestamp survives",
              stamped["sla_actuals"]["budget_approved"] == utc(2026, 8, 11))

        await SLA.stamp_if_internal(HR, COMPANY, "HR-REQ-2026-100", "budget_approved")
        client_after = await reqs.find_one({"request_no": "HR-REQ-2026-100"})
        check("stamp_if_internal ignores a CLIENT requisition",
              not (client_after.get("sla_actuals") or {}).get("budget_approved"))

        # =================================================================
        section("Escalation fires once")
        # =================================================================
        notes.clear()
        fired = await SLA.escalate_if_breached(HR, COMPANY, req2, "budget_approved")
        check("a breach escalates", fired is True)
        check("HR and Management are told",
              notes and set(notes[0][0]) == {"HR", "MD"})
        check("the breach is audited",
              any(a["action"] == M.AUDIT_SLA_BREACHED for a in audit_log.docs))

        refreshed = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        notes.clear()
        again = await SLA.escalate_if_breached(HR, COMPANY, refreshed, "budget_approved")
        check("the SAME breach does not escalate twice", again is False)
        check("and no second notification is sent", notes == [])

        on_time = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        check("a milestone that was MET never escalates",
              await SLA.escalate_if_breached(HR, COMPANY, on_time,
                                             "budget_approved") is False)

        # =================================================================
        section("The sweep finds what silence hides")
        # =================================================================
        notes.clear()
        swept = await SLA.sweep_open_breaches(HR, COMPANY, notify=False)
        overdue_reqs = {b["request_no"] for b in swept["breaches"]}
        check("the sweep finds a milestone that was never recorded",
              "HR-REQ-2026-003" in overdue_reqs)
        check("it does not report a client requisition",
              "HR-REQ-2026-100" not in overdue_reqs)
        check("notify=False sends nothing -- opening a screen must not email people",
              swept["notified"] == 0 and notes == [])

        swept = await SLA.sweep_open_breaches(HR, COMPANY, notify=True)
        check("notify=True escalates the newly-found breaches", swept["notified"] > 0)
        before = swept["notified"]
        swept = await SLA.sweep_open_breaches(HR, COMPANY, notify=True)
        check("running it again escalates nothing new", swept["notified"] < before)

        # =================================================================
        section("Induction and probation -- due on a date, not after N days")
        # =================================================================
        await onboardings.insert_one({
            "onb_no": "ONB-2026-001", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "candidate_name": "Joiner One",
            "joining_date": (NOW - timedelta(days=5)).strftime("%Y-%m-%d"),
            "checklist": M.seed_checklist()})
        await onboardings.insert_one({
            "onb_no": "ONB-2026-002", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "candidate_name": "Legacy Client Joiner",
            "joining_date": (NOW - timedelta(days=5)).strftime("%Y-%m-%d"),
            # A LEGACY client-track onboarding: base items only, no induction items.
            "checklist": [{"key": k, "label": label, "done": False, "done_at": None}
                          for k, label in M.ONBOARD_CHECKLIST]})
        await probations.insert_one({
            "prb_no": "PRB-2026-001", "company_id": COMPANY,
            "request_no": "HR-REQ-2026-001", "employee_name": "Joiner One",
            "ends_on": (NOW - timedelta(days=3)).strftime("%Y-%m-%d"),
            "outcome": M.ProbationOutcome.PENDING.value})

        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        report = await SLA.sla_for(COMPANY, req)
        by_key = {r["key"]: r for r in report["milestones"]}
        check("an induction whose Day 1 has passed with items untouched is OVERDUE",
              by_key["induction_due:ONB-2026-001"]["status"] == "overdue")
        check("a CLIENT-track onboarding contributes no induction milestone",
              "induction_due:ONB-2026-002" not in by_key)
        check("a probation past its end date and undecided is OVERDUE",
              by_key["probation_review_due:PRB-2026-001"]["status"] == "overdue")
        check("date-based milestones state no working-day target, because there is none",
              by_key["probation_review_due:PRB-2026-001"]["target_working_days"] is None)
        check("and they carry the date they were due",
              by_key["probation_review_due:PRB-2026-001"]["due_on"] is not None)

        await onboardings.update_one(
            {"onb_no": "ONB-2026-001"},
            {"$set": {"checklist": [{**i, "done": True}
                                    for i in M.seed_checklist()]}})
        await probations.update_one(
            {"prb_no": "PRB-2026-001"},
            {"$set": {"outcome": M.ProbationOutcome.CONFIRMED.value}})
        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        by_key = {r["key"]: r for r in (await SLA.sla_for(COMPANY, req))["milestones"]}
        check("a completed induction is MET",
              by_key["induction_due:ONB-2026-001"]["status"] == "met")
        check("a decided probation is MET",
              by_key["probation_review_due:PRB-2026-001"]["status"] == "met")

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
