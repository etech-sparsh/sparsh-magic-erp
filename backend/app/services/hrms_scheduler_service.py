"""HRMS ▸ the scheduled governance jobs (Phase INT-3, SOP §12).

Five sweeps — the SLA breach detector, probation reminders, pre-boarding reminders, the
policy review notice and the retention purge proposal — were each written to be *driven* by
a job runner, and until this phase nothing drove them. Every automated reminder and
escalation the SOP promises was therefore dead: the code was correct, tested, and never
called.

This module is the driver. It contains **no new governance logic** — each job calls the
service that already owns the decision — so the rules stay in one place and this file stays
a schedule.

## Why not a new scheduler

The ERP already runs one: `reminder_scheduler.start_reminder_scheduler()`, an asyncio task
on a 60-second tick with hour-gated daily jobs. A second runner would mean two things to
deploy, two things to watch and two places to look when a reminder does not arrive.
`run_due_jobs()` is called from that loop.

## Why the run ledger is in the database

The TPMS jobs beside this one remember their last run in a process-local dict, and that is
correct for them: they are idempotent syncs, so a restart that re-runs one costs nothing.
These are not. Re-running a reminder job **sends the reminder again**, and process memory
resets on every deploy. So the stamp lives in `hrms_job_runs` (see `COLL_JOB_RUNS`), with an
in-memory cache in front of it purely to keep the common "already ran today" tick from
hitting the database.

## Two independent guarantees, deliberately

1. **The run ledger** stops a job running twice in one period.
2. **Per-record guards** stop a *record* being notified twice even if the job does run
   twice — `sla_escalated` for breaches, `reminders_sent` for probation tiers, an existing
   Proposed batch for the purge.

The second is what makes the house convention safe here. The stamp is recorded **only on
success**, exactly as `reminder_scheduler._run_job` does it, so a failed run is retried on
the next tick rather than silently lost until tomorrow — and a retry is harmless precisely
because the per-record guards absorb it.

## What this module will not do

**The retention job proposes; it never executes.** Execution stays behind
`POST /purge-batches/{batch_no}/approve`, `Cap.RETENTION_PURGE` and a typed signature.
A purge that could begin because a clock struck three would make that approval decorative,
and the invariant is that nothing is redacted without an attributable human decision.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_DESIGNATIONS, COLL_JOB_RUNS, COLL_PROBATION_REVIEWS, COLL_PURGE_BATCHES,
    COLL_REQUISITIONS, JOB_CADENCE_WEEKLY, JOB_ORIENTATION, JOB_POLICY_ACK, JOB_POLICY_REVIEW,
    JOB_PREBOARDING,
    JOB_PROBATION, JOB_PULSE_SURVEY, JOB_RETENTION, JOB_SLA_SWEEP, MANAGERIAL_LEVELS,
    PROBATION_REMINDED_FIELD, ProbationOutcome,
    JOB_LWD, PurgeBatchStatus, SCHEDULED_JOBS,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now().date()


def _as_date(value) -> Optional[date]:
    """An ISO `YYYY-MM-DD` string as a date, or None. Never raises on bad data."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def stamp_for(cadence: str, now: datetime = None) -> str:
    """The period a run is remembered against.

    A weekly job stamped by date would run seven times a week. Stamping it by ISO year+week
    means it runs on the first tick after its hour in any week it has not yet run in — so a
    process that was down all Monday still sends Tuesday's notice, rather than skipping the
    week because it missed one named day.
    """
    moment = now or _now()
    if cadence == JOB_CADENCE_WEEKLY:
        iso = moment.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    return moment.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────
# The run ledger
# ─────────────────────────────────────────────────────────────
async def already_ran(company_id: str, job_key: str, stamp: str) -> bool:
    """Whether this job has already completed for this company in this period."""
    doc = await get_collection(COLL_JOB_RUNS).find_one(
        {"company_id": str(company_id), "job_key": job_key})
    return bool(doc) and doc.get("last_stamp") == stamp


async def record_run(company_id: str, job_key: str, stamp: str,
                     summary: dict = None) -> bool:
    """Remember a SUCCESSFUL run. Returns True if this call was the one that recorded it.

    Written as find-then-write rather than one upserting update, because `upsert=True`
    alongside `last_stamp: {"$ne": stamp}` is a trap: when the row already holds this stamp
    the query matches nothing, so Mongo INSERTS a second row for the same slot instead of
    doing nothing. Two rows for one job means `already_ran` can read the stale one and run
    the job again.

    The update path is still a single atomic conditional write, which is what resolves two
    workers racing for the same slot: the loser matches nothing and modifies nothing. The
    insert path is resolved by the unique index on (company_id, job_key) — the loser's
    insert raises, and a raise here means somebody else recorded it.
    """
    coll = get_collection(COLL_JOB_RUNS)
    cid = str(company_id)
    existing = await coll.find_one({"company_id": cid, "job_key": job_key})

    if existing is None:
        try:
            await coll.insert_one({"company_id": cid, "job_key": job_key,
                                   "last_stamp": stamp, "last_run_at": _now(),
                                   "last_summary": summary or {}})
            return True
        except Exception as e:
            # Another worker inserted first: the race resolving itself correctly. Never
            # worth failing a completed job over — the work is already done.
            print(f"[WARN] HRMS job ledger insert lost for {cid}/{job_key}: {e}")
            return False

    if existing.get("last_stamp") == stamp:
        return False

    result = await coll.update_one(
        {"company_id": cid, "job_key": job_key, "last_stamp": {"$ne": stamp}},
        {"$set": {"last_stamp": stamp, "last_run_at": _now(),
                  "last_summary": summary or {}}})
    return result.modified_count > 0


# ─────────────────────────────────────────────────────────────
# The jobs
# ─────────────────────────────────────────────────────────────
async def run_sla_sweep(company_id: str) -> dict:
    """Find internal requisitions sitting on an overdue, unrecorded milestone.

    Idempotent without help from the ledger: `escalate_if_breached` guards on
    `sla_escalated`, so a milestone already announced is never announced twice.
    """
    from app.services.hrms_config_service import config_for
    from app.services.hrms_sla_service import sweep_open_breaches

    # Resolved here and handed down, so one sweep judges every requisition against the same
    # targets even if somebody edits the settings while it runs.
    result = await sweep_open_breaches(None, company_id, notify=True,
                                       config=await config_for(company_id))
    return {"checked": result.get("checked", 0),
            "breaches": len(result.get("breaches") or []),
            "notified": result.get("notified", 0)}


async def _managerial_request_nos(company_id: str, request_nos: list) -> set:
    """Which of these requisitions are for a managerial-and-above role.

    Resolved in two queries for the whole batch rather than two per record: the seniority
    band lives on the designation, not the requisition, and walking that chain per row would
    turn a reminder sweep into a lookup storm on the one collection every screen reads.
    """
    if not request_nos:
        return set()
    levels = [lvl.value for lvl in MANAGERIAL_LEVELS]
    designations = await get_collection(COLL_DESIGNATIONS).find(
        {"company_id": str(company_id), "designation_level": {"$in": levels}},
        {"_id": 1}).to_list(2000)
    senior_ids = {str(d["_id"]) for d in designations}
    if not senior_ids:
        return set()

    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "request_no": {"$in": list(request_nos)}},
        {"request_no": 1, "designation_id": 1}).to_list(2000)
    return {r["request_no"] for r in reqs
            if str(r.get("designation_id") or "") in senior_ids}


async def run_probation_reminders(company_id: str) -> dict:
    """Remind the reviewer and HR that a probation review is coming due.

    Fires at each tier in this company's configured reminder table (Phase INT-5;
    `PROBATION_REMINDER_DAYS` is the default) that the end date has reached, once per
    tier per record. The tier is recorded on the probation row itself, so a job that runs
    twice — or is rewritten entirely — still cannot send the same reminder twice.

    Only the CLOSEST unfired tier is sent on any run. A record that has been invisible since
    day 45 owes one reminder saying "7 days", not four saying 30, 15, 7 and 1 in the same
    minute; the earlier tiers are marked fired because their moment has passed.

    Overdue reviews are deliberately absent. `probation_review_due` in SLA_MILESTONES already
    reports those and `sweep_open_breaches` already escalates them.
    """
    from app.services.hrms_config_service import probation_reminder_tiers
    from app.services.hrms_notify_service import notify_hrms_role, notify_user

    # ── Phase INT-5 ── this company's tiers. A company that wants a single 7-day nudge
    # instead of four reminders says so here rather than in a code change.
    tiers = await probation_reminder_tiers(company_id)

    coll = get_collection(COLL_PROBATION_REVIEWS)
    rows = await coll.find({"company_id": str(company_id),
                            "outcome": ProbationOutcome.PENDING.value}).to_list(1000)
    today = _today()

    due = []
    for row in rows:
        ends_on = _as_date(row.get("ends_on"))
        if ends_on is None:
            continue
        days_left = (ends_on - today).days
        if days_left < 0:
            continue                      # the SLA sweep owns overdue
        reached = [t for t in tiers if days_left <= t]
        if not reached:
            continue
        already = set(row.get(PROBATION_REMINDED_FIELD) or [])
        unfired = [t for t in reached if t not in already]
        if not unfired:
            continue
        due.append((row, min(unfired), sorted(reached, reverse=True), days_left))

    if not due:
        return {"pending": len(rows), "reminded": 0}

    senior = await _managerial_request_nos(
        company_id, [r.get("request_no") for r, _, _, _ in due if r.get("request_no")])

    reminded = 0
    for row, tier, reached, days_left in due:
        prb_no = row.get("prb_no")
        name = row.get("employee_name") or row.get("employee_code") or "An employee"
        title = f"Probation review due in {days_left} day(s): {name}"
        message = (f'{name} ({row.get("employee_code")}) completes probation on '
                   f'{row.get("ends_on")}. Review {prb_no} is still Pending — the '
                   f'confirmation decision is due before that date.')
        link = "/hrms/probation"

        if row.get("reviewer_id"):
            await notify_user(str(row["reviewer_id"]), title, message,
                              kind="warning", link=link, email=True)
        await notify_hrms_role(company_id, ["HR"], title, message,
                               kind="warning", link=link, email=True)
        # Management is INFORMED for managerial-and-above (Annexure B), not consulted --
        # so they are told, and told nothing extra.
        if row.get("request_no") in senior:
            await notify_hrms_role(company_id, ["MD"], title, message,
                                   kind="info", link=link, email=False)

        # Every tier the end date has already passed is marked fired, not just the one sent.
        # Without this a record found late would send the remaining tiers on consecutive
        # days, turning one missed sweep into a burst.
        # Conditioned on the end date and the Pending state the sweep computed FROM: an
        # extension (which moves ends_on and re-arms the tiers) or a decision landing
        # between this sweep's read and this write makes the burn match nothing, so the
        # re-armed field survives. The next sweep re-evaluates against the new date; a
        # duplicate send is impossible because the tier only burns with its notification.
        await coll.update_one(
            {"prb_no": prb_no, "company_id": str(company_id),
             "ends_on": row.get("ends_on"),
             "outcome": ProbationOutcome.PENDING.value},
            {"$addToSet": {PROBATION_REMINDED_FIELD: {"$each": reached}}})
        reminded += 1

    return {"pending": len(rows), "reminded": reminded}


async def run_preboarding_reminders(company_id: str) -> dict:
    """Nudge whoever owns a candidate who has accepted an offer and gone quiet.

    Routed to the assigned recruiter rather than broadcast to HR, because a list of other
    people's candidates is the kind of notification that teaches somebody to dismiss the
    bell. Candidates with no recruiter assigned have no such owner, so those — and only
    those — go to HR as a group.
    """
    from app.services.hrms_notify_service import notify_hrms_role, notify_user
    from app.services.hrms_preboarding_service import due_touchpoints

    due = await due_touchpoints(None, company_id)
    rows = (due.get("never_contacted") or []) + (due.get("gone_quiet") or [])
    if not rows:
        return {"due": 0, "notified": 0}

    owned: dict = {}
    unowned = []
    for row in rows:
        owner = str(row.get("assigned_recruiter_id") or "")
        (owned.setdefault(owner, []) if owner else unowned).append(row)

    def _describe(items: list) -> str:
        return "\n".join(
            f'{r.get("candidate_name") or r.get("uk")} — '
            f'{r.get("designation_name") or r.get("request_no") or "role unrecorded"}'
            + (" (never contacted)" if not r.get("last_contacted_at")
               else f' (last contacted {str(r["last_contacted_at"])[:10]})')
            for r in items)

    notified = 0
    for owner, items in owned.items():
        await notify_user(
            owner, f"{len(items)} pre-boarding candidate(s) need contact",
            _describe(items), kind="warning", link="/hrms/preboarding", email=True)
        notified += 1

    if unowned:
        await notify_hrms_role(
            company_id, ["HR"],
            f"{len(unowned)} pre-boarding candidate(s) have no recruiter assigned",
            _describe(unowned), kind="warning", link="/hrms/preboarding", email=True)
        notified += 1

    return {"due": len(rows), "notified": notified}


async def run_policy_review(company_id: str) -> dict:
    """Tell the MD and HR about recruitment policy reviews falling due (SOP §14)."""
    from app.services.hrms_policy_service import notify_due_reviews

    result = await notify_due_reviews(None, company_id)
    return {"notified": result.get("notified", 0), "total": result.get("total", 0)}


async def run_retention_proposal(company_id: str) -> dict:
    """Propose a retention purge when records have passed their retention floor (SOP §13).

    Three things this deliberately does NOT do:

    1. **It does not purge.** `propose` writes a proposal; redaction happens only when an MD
       approves it with a typed signature.
    2. **It does not propose an empty batch.** The dry run costs nothing and writes nothing,
       so the count is checked before anything is recorded — a register full of "0 records"
       proposals is a register nobody reads.
    3. **It does not stack proposals.** While one batch is still awaiting a decision, a
       second would ask the same person the same question about an overlapping set of ids,
       and approving both would be ambiguous about which one governed.
    """
    from app.services.hrms_notify_service import notify_hrms_role
    from app.services.hrms_purge_service import propose

    pending = await get_collection(COLL_PURGE_BATCHES).find_one(
        {"company_id": str(company_id), "status": PurgeBatchStatus.PROPOSED.value})
    if pending:
        return {"skipped": "a proposal is already awaiting approval",
                "batch_no": pending.get("batch_no")}

    preview = await propose(None, company_id, dry_run=True)
    if not preview.get("total_records"):
        return {"eligible": 0, "proposed": False}

    batch = await propose(None, company_id, dry_run=False)
    await notify_hrms_role(
        company_id, ["MD"],
        f'Retention purge {batch.get("batch_no")} awaiting approval',
        f'{batch.get("total_records")} record(s) have passed their retention floor. '
        f'{batch.get("summary") or ""} Nothing is redacted until this batch is approved.',
        kind="warning", link="/hrms/policies", email=True)
    return {"eligible": batch.get("total_records"), "proposed": True,
            "batch_no": batch.get("batch_no")}


async def run_orientation_escalation(company_id: str) -> dict:
    """§22.3 step 207 — escalate assignments with an open mandatory item past the
    company's escalation window. All the decision logic lives in
    hrms_orientation_service.run_escalation_sweep; this is purely the schedule."""
    from app.services.hrms_orientation_service import run_escalation_sweep
    return await run_escalation_sweep(company_id)


async def run_pulse_survey_issue(company_id: str) -> dict:
    """§22.4 steps 208-209 — issue 30/90-day pulse surveys to employees who just reached a
    milestone. All the decision logic lives in hrms_pulse_service.run_issue_sweep; this is
    purely the schedule."""
    from app.services.hrms_pulse_service import run_issue_sweep
    return await run_issue_sweep(company_id)


async def run_policy_acknowledgement_reminders(company_id: str) -> dict:
    """§22.6 — nudge employees who still owe a required policy acknowledgement. All the
    decision logic lives in hrms_policy_service.notify_pending_acknowledgements; this is
    purely the schedule."""
    from app.services.hrms_policy_service import notify_pending_acknowledgements
    return await notify_pending_acknowledgements(company_id)


async def run_last_working_day(company_id: str) -> dict:
    """Everything that should happen on somebody's last day (7.18 step 10).

    All the decision logic lives in hrms_exit_service.run_lwd_sweep; this is the
    registration shim, exactly as the pulse and orientation jobs are.
    """
    from app.services.hrms_exit_service import run_lwd_sweep
    return await run_lwd_sweep(company_id)


JOB_HANDLERS = {
    JOB_SLA_SWEEP:     run_sla_sweep,
    JOB_PROBATION:     run_probation_reminders,
    JOB_PREBOARDING:   run_preboarding_reminders,
    JOB_POLICY_REVIEW: run_policy_review,
    JOB_RETENTION:     run_retention_proposal,
    JOB_ORIENTATION:   run_orientation_escalation,
    JOB_PULSE_SURVEY:  run_pulse_survey_issue,
    JOB_POLICY_ACK:    run_policy_acknowledgement_reminders,
    JOB_LWD:           run_last_working_day,
}


# ─────────────────────────────────────────────────────────────
# The driver
# ─────────────────────────────────────────────────────────────
async def run_due_jobs(state: dict = None, now: datetime = None) -> dict:
    """Run every job that is due, for every company with HRMS switched on.

    `state` is an optional process-local cache of the ledger, passed in by the scheduler
    loop. It is an optimisation and nothing else: it saves a database read on the ticks
    after a job has already run today, and losing it (a restart) costs one extra read, never
    a duplicate run — the ledger is still consulted whenever the cache does not know.

    Never raises. A failing job is logged, leaves its stamp unrecorded so the next tick
    retries it, and cannot stop the jobs after it or the reminder loop around it.
    """
    from app.utils.hrms_access import hrms_enabled_company_ids

    moment = now or _now()
    cache = state if state is not None else {}
    ran = []

    try:
        company_ids = sorted(await hrms_enabled_company_ids())
    except Exception as e:
        print(f"[WARN] HRMS scheduler could not list enabled companies: {e}")
        return {"companies": 0, "ran": []}

    for company_id in company_ids:
        for job_key, label, cadence, hour in SCHEDULED_JOBS:
            if moment.hour < hour:
                continue
            stamp = stamp_for(cadence, moment)
            cache_key = (company_id, job_key)
            if cache.get(cache_key) == stamp:
                continue
            try:
                if await already_ran(company_id, job_key, stamp):
                    cache[cache_key] = stamp
                    continue
                summary = await JOB_HANDLERS[job_key](company_id)
                # Recorded only on success, so a failure is retried on the next tick. The
                # per-record guards inside each job are what make that retry safe.
                await record_run(company_id, job_key, stamp, summary)
                cache[cache_key] = stamp
                ran.append({"company_id": company_id, "job": job_key, "summary": summary})
                print(f"[INFO] HRMS {label} ({company_id}): {summary}")
            except Exception as e:
                print(f"[ERROR] HRMS {label} failed for company {company_id}: {e}")

    return {"companies": len(company_ids), "ran": ran}
