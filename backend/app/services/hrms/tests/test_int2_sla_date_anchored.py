"""Phase INT-2 -- the two date-anchored SLA milestones (SOP §8).

`hrms_sla_service` implemented the four milestone-to-milestone targets. The two measured
against a stored DATE -- induction due on the joining date, the probation review before the
probation end date -- were deliberately deferred. This phase brings them into the SAME table
with an explicit `anchor` discriminator.

The property that matters: `sweep_open_breaches()` picks them up with NO NEW SWEEP CODE.
That is the whole reason for the discriminator, and it is asserted here directly rather than
inferred from the fact that the report contains the rows.

Also covered: one row PER RECORD (a requisition that hired three people owes three
inductions), a date row honestly reporting NO working-day target, and "met late" counting as
a breach -- the point of a Day 1 milestone is that Day 1 was Day 1.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_sla_date_anchored   (from backend/)
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


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


def ahead(days):
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "closing_status": "Open", "created_at": NOW - timedelta(days=60),
         "sla_actuals": {"budget_approved": NOW - timedelta(days=58),
                         "scorecard_approved": NOW - timedelta(days=57),
                         "shortlist_ready": NOW - timedelta(days=50),
                         "final_selection": NOW - timedelta(days=40),
                         "offer_released": NOW - timedelta(days=39)}},
        {"request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "requisition_track": "client", "designation_name": "Analyst",
         "closing_status": "Open", "created_at": NOW},
    ])

    def induction_items(done=False, done_at=None):
        return [{"key": k, "label": label, "done": done, "done_at": done_at,
                 "induction": True} for k, label in M.INDUCTION_CHECKLIST]

    onboardings = FakeCollection([
        # Day 1 has passed and the induction is untouched.
        {"onb_no": "ONB-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "candidate_name": "Joiner One",
         "joining_date": ago(10), "checklist": induction_items()},
        # Day 1 is still ahead.
        {"onb_no": "ONB-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "candidate_name": "Joiner Two",
         "joining_date": ahead(10), "checklist": induction_items()},
        # Done, and done ON TIME.
        {"onb_no": "ONB-2026-003", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "candidate_name": "Joiner Three",
         "joining_date": ago(20),
         "checklist": induction_items(True, NOW - timedelta(days=20))},
        # Done, but LATE -- Day 1 was Day 1.
        {"onb_no": "ONB-2026-004", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "candidate_name": "Joiner Four",
         "joining_date": ago(30),
         "checklist": induction_items(True, NOW - timedelta(days=5))},
        # A LEGACY client-track onboarding: twelve base items, no induction items at all.
        {"onb_no": "ONB-2026-005", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "candidate_name": "Client Joiner",
         "joining_date": ago(10),
         "checklist": [{"key": k, "label": label, "done": False, "done_at": None}
                       for k, label in M.ONBOARD_CHECKLIST]},
    ])
    probations = FakeCollection([
        {"prb_no": "PRB-2026-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_name": "Joiner One",
         "ends_on": ago(5), "outcome": M.ProbationOutcome.PENDING.value},
        {"prb_no": "PRB-2026-002", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_name": "Joiner Two",
         "ends_on": ahead(30), "outcome": M.ProbationOutcome.PENDING.value},
        {"prb_no": "PRB-2026-003", "company_id": COMPANY,
         "request_no": "HR-REQ-2026-001", "employee_name": "Joiner Three",
         "ends_on": ago(40), "outcome": M.ProbationOutcome.CONFIRMED.value,
         "confirmed_at": NOW - timedelta(days=41)},
    ])

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_ONBOARDING: onboardings,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_AUDIT_LOG: FakeCollection(),
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_sla_service as SLA
    import app.services.hrms_audit_service as AUD
    for mod in (SLA, AUD):
        mod.get_collection = mongo.get_collection

    notes = []

    async def fake_role(company_id, roles, title, message, **kw):
        notes.append(title)
    import app.services.hrms_notify_service as NS
    NS.notify_hrms_role = fake_role

    try:
        # =================================================================
        section("One table, two evaluators")
        # =================================================================
        dated = [m for m in M.SLA_MILESTONES if m["anchor"] == M.ANCHOR_DATE]
        check("both SOP date-anchored milestones are in the SAME table",
              [m["key"] for m in dated] == ["induction_due", "probation_review_due"])
        check("each names WHERE its due date lives, so the evaluator stays declarative",
              all(m.get("collection") and m.get("due_field") and m.get("id_field")
                  for m in dated))
        check("neither states a working-day target, because there is none to state",
              all(m["target_days"] is None for m in dated))
        check("and neither is stampable -- there is nothing to stamp",
              not (M.STAMPABLE_MILESTONES & {m["key"] for m in dated}))
        check("sla_milestone() finds a row by key",
              M.sla_milestone("induction_due")["anchor"] == M.ANCHOR_DATE)
        check("and returns None for one that does not exist",
              M.sla_milestone("nonsense") is None)

        # =================================================================
        section("Stamping a date-anchored milestone is a loud programming error")
        # =================================================================
        try:
            await SLA.stamp(COMPANY, "HR-REQ-2026-001", "induction_due")
            check("stamping a date-anchored milestone raises", False)
        except ValueError as e:
            check("stamping a date-anchored milestone raises ValueError",
                  "not a stampable" in str(e))
        # The four real ones still stamp exactly as they always did.
        ok = await SLA.stamp(COMPANY, "HR-REQ-2026-002", "budget_approved")
        check("a milestone-anchored key still stamps", ok is True)

        # =================================================================
        section("One row PER RECORD, not one per requisition")
        # =================================================================
        req = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        report = await SLA.sla_for(COMPANY, req)
        rows = {r["key"]: r for r in report["milestones"]}

        induction_rows = [k for k in rows if k.startswith("induction_due:")]
        check("four internal onboardings produce FOUR induction rows",
              len(induction_rows) == 4)
        check("a client-track onboarding contributes none",
              "induction_due:ONB-2026-005" not in rows)
        check("an aggregate would hide the one person nobody inducted -- it does not",
              rows["induction_due:ONB-2026-001"]["status"] == "overdue")

        probation_rows = [k for k in rows if k.startswith("probation_review_due:")]
        check("three probations produce THREE rows", len(probation_rows) == 3)

        # =================================================================
        section("Induction -- due on Day 1")
        # =================================================================
        check("Day 1 passed with the items untouched is OVERDUE",
              rows["induction_due:ONB-2026-001"]["status"] == "overdue")
        check("Day 1 still ahead is PENDING",
              rows["induction_due:ONB-2026-002"]["status"] == "pending")
        check("completed on the day is MET",
              rows["induction_due:ONB-2026-003"]["status"] == "met")
        check("completed twenty-five days LATE is BREACHED, not met",
              rows["induction_due:ONB-2026-004"]["status"] == "breached")
        check("the due date is the joining date itself",
              rows["induction_due:ONB-2026-001"]["due_on"] == ago(10))
        check("it names what it is measured from, in words",
              "day 1" in rows["induction_due:ONB-2026-001"]["measured_from"].lower())
        check("and it reports NO elapsed-time figure, because there is none",
              rows["induction_due:ONB-2026-001"]["target_working_days"] is None
              and rows["induction_due:ONB-2026-001"]["working_days_taken"] is None)
        check("the row carries the candidate's name, so a reader knows who",
              "Joiner One" in rows["induction_due:ONB-2026-001"]["label"])

        # =================================================================
        section("Probation -- due before the end date")
        # =================================================================
        check("past its end date and undecided is OVERDUE",
              rows["probation_review_due:PRB-2026-001"]["status"] == "overdue")
        check("end date still ahead is PENDING",
              rows["probation_review_due:PRB-2026-002"]["status"] == "pending")
        check("decided before the end date is MET",
              rows["probation_review_due:PRB-2026-003"]["status"] == "met")
        check("and the decision timestamp is reported as the actual",
              rows["probation_review_due:PRB-2026-003"]["actual_at"] is not None)

        # =================================================================
        section("The sweep picks them up with no new sweep code")
        # =================================================================
        # THE point of the discriminator. `sweep_open_breaches` iterates whatever `sla_for`
        # returns; if the date rows were assembled outside the table it would miss them.
        sweep = await SLA.sweep_open_breaches(None, COMPANY, notify=False)
        found = {b["milestone"] for b in sweep["breaches"]}
        check("the sweep reports the overdue induction",
              "induction_due:ONB-2026-001" in found)
        check("and the overdue probation review",
              "probation_review_due:PRB-2026-001" in found)
        check("it does not report the ones that are met or still pending",
              "induction_due:ONB-2026-003" not in found
              and "probation_review_due:PRB-2026-002" not in found)
        check("notify=False sent nothing -- running a report must not email people",
              not notes)

        # =================================================================
        section("Escalation says something a human can act on")
        # =================================================================
        fired = await SLA.escalate_if_breached(
            None, COMPANY, req, "induction_due:ONB-2026-001")
        check("a date-anchored breach escalates", fired is True)
        check("HR and Management were told", len(notes) == 1)
        audits = await store[M.COLL_AUDIT_LOG].find({}).to_list(50)
        detail = " ".join(str(a.get("detail") or "") for a in audits)
        check("and the audit line names the DUE DATE rather than 'None working days'",
              ago(10) in detail and "None working day" not in detail)

        fresh = await reqs.find_one({"request_no": "HR-REQ-2026-001"})
        again = await SLA.escalate_if_breached(
            None, COMPANY, fresh, "induction_due:ONB-2026-001")
        check("the SAME breach does not escalate twice", again is False)
        check("and no second notification was sent", len(notes) == 1)

        # =================================================================
        section("The client track still has no SLA at all")
        # =================================================================
        client_req = await reqs.find_one({"request_no": "HR-REQ-2026-002"})
        client_report = await SLA.sla_for(COMPANY, client_req)
        check("a client requisition reports not-applicable",
              client_report["applicable"] is False)
        check("with no milestones of either kind", client_report["milestones"] == [])

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
