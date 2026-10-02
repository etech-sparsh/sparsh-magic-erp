"""Phase INT-3 -- the scheduled governance jobs (SOP §12).

Five sweeps existed, were tested, and were called by nothing. This covers the driver that
now calls them, and the guarantees that make an automated reminder safe to run on a loop.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. THE RUN LEDGER IS DURABLE. It lives in a collection, not in process memory, because a
     deploy resets memory and re-running a reminder job sends the reminder again.
  2. PER-RECORD GUARDS ARE INDEPENDENT OF THE LEDGER. Bypass the ledger entirely and run a
     job twice in one day, and no record is notified twice. That is what makes "record the
     stamp only on success, retry on failure" a safe convention here.
  3. THE RETENTION JOB PROPOSES AND NEVER EXECUTES. A clock striking three must not be able
     to begin redacting employment records.
  4. A FAILING JOB CONSUMES NOBODY ELSE'S SLOT, and leaves its own stamp unrecorded so the
     next tick retries it.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int3_scheduler   (from backend/)
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

C1 = "COMPANY-1"
C2 = "COMPANY-2"
NOW = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)      # a Friday, past every job hour


def in_days(n: int) -> str:
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    store: dict = {}
    original_get = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_scheduler_service as SCH
    SCH.get_collection = mongo.get_collection
    # Phase INT-5: the jobs resolve this company's rule set before they run, so the config
    # service reads through the same fake store. With no settings row it returns the module
    # defaults, which is what every assertion below is written against.
    import app.services.hrms_config_service as CFG
    CFG.get_collection = mongo.get_collection
    # Freeze the clock. Every tier boundary in this file is stated relative to NOW, so a run
    # at midnight on a real machine must not shift them by a day.
    SCH._now = lambda: NOW

    # ── Notification capture ─────────────────────────────────────────────────
    sent: list = []

    async def fake_user(user_id, title, message, **kw):
        sent.append(("user", str(user_id), title, message))

    async def fake_role(company_id, roles, title, message, **kw):
        sent.append(("role", ",".join(roles), title, message))

    import app.services.hrms_notify_service as NOTIFY
    NOTIFY.notify_user = fake_user
    NOTIFY.notify_hrms_role = fake_role

    # ── Companies ────────────────────────────────────────────────────────────
    import app.utils.hrms_access as ACCESS

    async def fake_enabled():
        return {C1}                       # C2 exists but HRMS is switched OFF

    ACCESS.hrms_enabled_company_ids = fake_enabled

    # =========================================================================
    section("1. Run stamps -- a weekly job is not remembered by date")
    # =========================================================================
    daily = SCH.stamp_for(M.JOB_CADENCE_DAILY, NOW)
    weekly = SCH.stamp_for(M.JOB_CADENCE_WEEKLY, NOW)
    check("a daily stamp is the date", daily == "2026-08-14")
    check("a weekly stamp is ISO year+week", weekly == "2026-W33")
    check("the next day is a new daily stamp",
          SCH.stamp_for(M.JOB_CADENCE_DAILY, NOW + timedelta(days=1)) != daily)
    check("the next day is the SAME weekly stamp -- a weekly job does not run seven times",
          SCH.stamp_for(M.JOB_CADENCE_WEEKLY, NOW + timedelta(days=1)) == weekly)
    check("the next week is a new weekly stamp",
          SCH.stamp_for(M.JOB_CADENCE_WEEKLY, NOW + timedelta(days=7)) != weekly)

    # =========================================================================
    section("2. The ledger is durable, and one row per (company, job)")
    # =========================================================================
    check("nothing has run yet", not await SCH.already_ran(C1, M.JOB_SLA_SWEEP, daily))
    check("recording a run returns True",
          await SCH.record_run(C1, M.JOB_SLA_SWEEP, daily, {"ok": 1}))
    check("the run is remembered", await SCH.already_ran(C1, M.JOB_SLA_SWEEP, daily))
    check("recording the same stamp again returns False (the race loser)",
          not await SCH.record_run(C1, M.JOB_SLA_SWEEP, daily))
    check("ONE ledger row, not two -- upsert with $ne would have written a second",
          len(store[M.COLL_JOB_RUNS].docs) == 1)
    check("another company's slot is untouched",
          not await SCH.already_ran(C2, M.JOB_SLA_SWEEP, daily))
    check("another job's slot is untouched",
          not await SCH.already_ran(C1, M.JOB_PROBATION, daily))
    check("tomorrow's stamp is due again",
          not await SCH.already_ran(C1, M.JOB_SLA_SWEEP, "2026-08-15"))
    check("rolling to tomorrow updates the same row",
          await SCH.record_run(C1, M.JOB_SLA_SWEEP, "2026-08-15")
          and len(store[M.COLL_JOB_RUNS].docs) == 1)

    # =========================================================================
    section("3. Probation reminders -- tiers fire once, and only the closest one")
    # =========================================================================
    prb = store.setdefault(M.COLL_PROBATION_REVIEWS, FakeCollection())
    REVIEWER = str(ObjectId())
    PENDING = M.ProbationOutcome.PENDING.value

    prb.docs.extend([
        # Far out -- no tier reached.
        {"prb_no": "PRB-001", "company_id": C1, "employee_code": "E1",
         "employee_name": "Far Off", "outcome": PENDING, "ends_on": in_days(60),
         "reviewer_id": REVIEWER, "request_no": "R-JUNIOR"},
        # 25 days out -- the 30 tier is reached.
        {"prb_no": "PRB-002", "company_id": C1, "employee_code": "E2",
         "employee_name": "Due Soon", "outcome": PENDING, "ends_on": in_days(25),
         "reviewer_id": REVIEWER, "request_no": "R-JUNIOR"},
        # 5 days out and never reminded -- 30, 15 and 7 are all reached.
        {"prb_no": "PRB-003", "company_id": C1, "employee_code": "E3",
         "employee_name": "Found Late", "outcome": PENDING, "ends_on": in_days(5),
         "reviewer_id": REVIEWER, "request_no": "R-SENIOR"},
        # Already overdue -- the SLA sweep owns this one.
        {"prb_no": "PRB-004", "company_id": C1, "employee_code": "E4",
         "employee_name": "Overdue", "outcome": PENDING, "ends_on": in_days(-3),
         "reviewer_id": REVIEWER, "request_no": "R-JUNIOR"},
        # Already confirmed -- not pending, so not a reminder.
        {"prb_no": "PRB-005", "company_id": C1, "employee_code": "E5",
         "employee_name": "Confirmed", "outcome": M.ProbationOutcome.CONFIRMED.value,
         "ends_on": in_days(2), "reviewer_id": REVIEWER, "request_no": "R-JUNIOR"},
        # Another company entirely.
        {"prb_no": "PRB-006", "company_id": C2, "employee_code": "E6",
         "employee_name": "Elsewhere", "outcome": PENDING, "ends_on": in_days(3),
         "reviewer_id": REVIEWER, "request_no": "R-OTHER"},
    ])

    # R-SENIOR is a managerial role; R-JUNIOR is not.
    senior_id, junior_id = ObjectId(), ObjectId()
    store.setdefault(M.COLL_DESIGNATIONS, FakeCollection()).docs.extend([
        {"_id": senior_id, "company_id": C1, "name": "Head of Ops",
         "designation_level": M.DesignationLevel.MANAGERIAL.value},
        {"_id": junior_id, "company_id": C1, "name": "Executive",
         "designation_level": M.DesignationLevel.JUNIOR.value},
    ])
    store.setdefault(M.COLL_REQUISITIONS, FakeCollection()).docs.extend([
        {"request_no": "R-SENIOR", "company_id": C1, "designation_id": str(senior_id)},
        {"request_no": "R-JUNIOR", "company_id": C1, "designation_id": str(junior_id)},
    ])

    sent.clear()
    out = await SCH.run_probation_reminders(C1)
    check("only this company's pending reviews are considered (4 of 6)",
          out["pending"] == 4)
    check("two records were reminded -- PRB-002 and PRB-003", out["reminded"] == 2)

    titles = " | ".join(t for _, _, t, _ in sent)
    check("the 25-day record was reminded", "Due Soon" in titles)
    check("the 5-day record was reminded", "Found Late" in titles)
    check("the 60-day record was NOT reminded", "Far Off" not in titles)
    check("the OVERDUE record was NOT reminded -- the SLA sweep owns overdue",
          "Overdue" not in titles)
    check("a confirmed review is not reminded", "Confirmed" not in titles)
    check("the other company's record was not touched", "Elsewhere" not in titles)

    check("the reviewer was notified directly",
          any(kind == "user" and who == REVIEWER for kind, who, _, _ in sent))
    check("HR was notified", any(kind == "role" and "HR" in who for kind, who, _, _ in sent))
    md_titles = [t for kind, who, t, _ in sent if kind == "role" and "MD" in who]
    check("Management was INFORMED for the managerial role",
          any("Found Late" in t for t in md_titles))
    check("Management was NOT told about the non-managerial role",
          not any("Due Soon" in t for t in md_titles))

    fired_002 = set((await prb.find_one({"prb_no": "PRB-002"})).get(
        M.PROBATION_REMINDED_FIELD) or [])
    fired_003 = set((await prb.find_one({"prb_no": "PRB-003"})).get(
        M.PROBATION_REMINDED_FIELD) or [])
    check("the 25-day record recorded only the 30 tier", fired_002 == {30})
    check("the 5-day record recorded 30, 15 AND 7 -- so the passed tiers cannot "
          "fire on consecutive days as a burst", fired_003 == {30, 15, 7})
    check("the 1-day tier is still unfired on the 5-day record", 1 not in fired_003)

    # -- The guarantee that matters: run it again, same day, ledger bypassed --
    sent.clear()
    again = await SCH.run_probation_reminders(C1)
    check("a SECOND run on the same day sends nothing -- the per-record guard holds "
          "without any help from the ledger", again["reminded"] == 0 and not sent)

    # -- The last tier still fires when its day arrives --
    await prb.update_one({"prb_no": "PRB-003"}, {"$set": {"ends_on": in_days(1)}})
    sent.clear()
    final = await SCH.run_probation_reminders(C1)
    check("the 1-day tier fires when the date reaches it", final["reminded"] == 1)
    fired_003 = set((await prb.find_one({"prb_no": "PRB-003"})).get(
        M.PROBATION_REMINDED_FIELD) or [])
    check("every tier is now recorded", fired_003 == {30, 15, 7, 1})

    # =========================================================================
    section("4. Pre-boarding -- routed to the owner, not broadcast")
    # =========================================================================
    RECRUITER = str(ObjectId())
    import app.services.hrms_preboarding_service as PRE

    async def fake_due(actor, company_id, **kw):
        return {"never_contacted": [
                    {"uk": "CAN-1", "candidate_name": "Owned One",
                     "assigned_recruiter_id": RECRUITER, "designation_name": "Analyst",
                     "last_contacted_at": None}],
                "gone_quiet": [
                    {"uk": "CAN-2", "candidate_name": "Owned Two",
                     "assigned_recruiter_id": RECRUITER, "designation_name": "Analyst",
                     "last_contacted_at": "2026-07-01T00:00:00"},
                    {"uk": "CAN-3", "candidate_name": "Orphan",
                     "assigned_recruiter_id": None, "designation_name": "Clerk",
                     "last_contacted_at": "2026-07-02T00:00:00"}],
                "total": 3}

    PRE.due_touchpoints = fake_due
    sent.clear()
    out = await SCH.run_preboarding_reminders(C1)
    check("all three due candidates were counted", out["due"] == 3)
    check("two notifications went out, not three -- the recruiter gets ONE digest",
          out["notified"] == 2)
    to_recruiter = [m for kind, who, _, m in sent if kind == "user" and who == RECRUITER]
    check("the recruiter got exactly one message", len(to_recruiter) == 1)
    check("it names both of their candidates",
          "Owned One" in to_recruiter[0] and "Owned Two" in to_recruiter[0])
    check("it does NOT name somebody else's candidate", "Orphan" not in to_recruiter[0])
    to_hr = [m for kind, who, _, m in sent if kind == "role" and "HR" in who]
    check("the unassigned candidate went to HR", to_hr and "Orphan" in to_hr[0])

    async def fake_due_empty(actor, company_id, **kw):
        return {"never_contacted": [], "gone_quiet": [], "total": 0}

    PRE.due_touchpoints = fake_due_empty
    sent.clear()
    out = await SCH.run_preboarding_reminders(C1)
    check("nothing due sends nothing", out["notified"] == 0 and not sent)

    # =========================================================================
    section("5. Retention -- proposes, and never executes")
    # =========================================================================
    import app.services.hrms_purge_service as PURGE
    purge_calls: list = []

    async def fake_propose(actor, company_id, *, as_of=None, dry_run=True):
        purge_calls.append(dry_run)
        payload = {"company_id": company_id, "total_records": 7, "dry_run": dry_run,
                   "summary": "7 records", "status": M.PurgeBatchStatus.PROPOSED.value}
        if not dry_run:
            payload["batch_no"] = "PRG-2026-001"
            await mongo.get_collection(M.COLL_PURGE_BATCHES).insert_one(dict(payload))
        return payload

    PURGE.propose = fake_propose
    sent.clear()
    out = await SCH.run_retention_proposal(C1)
    check("the dry run ran first, then the real proposal",
          purge_calls == [True, False])
    check("a batch was proposed", out["proposed"] and out["batch_no"] == "PRG-2026-001")
    check("the MD was told it is AWAITING APPROVAL",
          any(kind == "role" and "MD" in who and "awaiting approval" in t.lower()
              for kind, who, t, _ in sent))
    batch = await store[M.COLL_PURGE_BATCHES].find_one({"batch_no": "PRG-2026-001"})
    check("the batch is Proposed, NOT Approved or Executed -- a clock cannot redact "
          "an employment record", batch["status"] == M.PurgeBatchStatus.PROPOSED.value)

    # -- A pending proposal blocks a second one --
    purge_calls.clear()
    sent.clear()
    out = await SCH.run_retention_proposal(C1)
    check("a second proposal is refused while one awaits a decision", "skipped" in out)
    check("propose was not called at all", purge_calls == [])
    check("no second notification", not sent)

    # -- Nothing eligible writes nothing --
    store[M.COLL_PURGE_BATCHES].docs.clear()

    async def fake_propose_empty(actor, company_id, *, as_of=None, dry_run=True):
        purge_calls.append(dry_run)
        return {"total_records": 0, "dry_run": dry_run}

    PURGE.propose = fake_propose_empty
    purge_calls.clear()
    sent.clear()
    out = await SCH.run_retention_proposal(C1)
    check("nothing eligible -> no proposal", out["proposed"] is False)
    check("only the DRY RUN was called, which writes nothing", purge_calls == [True])
    check("no empty batch was recorded", not store[M.COLL_PURGE_BATCHES].docs)
    check("nobody was notified about nothing", not sent)

    # -- Structural: this module cannot execute a purge --
    import inspect
    source = inspect.getsource(SCH)
    check("the scheduler never calls approve_batch or execute",
          "approve_batch" not in source and "execute_batch" not in source)

    # =========================================================================
    section("6. The driver -- hour gates, one run per period, isolated failures")
    # =========================================================================
    import app.services.hrms_sla_service as SLA
    import app.services.hrms_policy_service as POL

    calls: list = []

    async def fake_sweep(actor, company_id, *, notify=True, config=None):
        # `config` is accepted and asserted on below: the job is supposed to resolve the
        # rule set ONCE and hand it down, not let the sweep read it per requisition.
        calls.append(("sla", company_id, config))
        return {"checked": 2, "breaches": [], "notified": 0}

    async def fake_policy(actor, company_id):
        calls.append(("policy", company_id))
        return {"notified": 1, "total": 1}

    SLA.sweep_open_breaches = fake_sweep
    POL.notify_due_reviews = fake_policy
    PURGE.propose = fake_propose_empty
    PRE.due_touchpoints = fake_due_empty

    store[M.COLL_JOB_RUNS].docs.clear()

    # -- Before any job's hour, nothing runs --
    calls.clear()
    early = await SCH.run_due_jobs({}, now=NOW.replace(hour=2))
    check("at 02:00 no job has reached its hour", not early["ran"] and not calls)

    # -- At 09:00 every job is due --
    calls.clear()
    cache: dict = {}
    first = await SCH.run_due_jobs(cache, now=NOW)
    ran_jobs = {r["job"] for r in first["ran"]}
    # Read from the job table rather than a hardcoded set: later phases legitimately add
    # sweeps (orientation escalation, pulse issuance, policy acknowledgement), and this
    # line is about "every registered job got its slot", not about how many there are.
    check("every registered job ran",
          ran_jobs == {key for key, _label, _cadence, _hour in M.SCHEDULED_JOBS})
    check("only the HRMS-enabled company was swept",
          all(r["company_id"] == C1 for r in first["ran"]))
    check("the disabled company was never touched",
          not any(call[1] == C2 for call in calls))
    sla_call = next(c for c in calls if c[0] == "sla")
    check("the SLA job resolved the rule set ONCE and passed it down, rather than letting "
          "the sweep read the settings row per requisition",
          isinstance(sla_call[2], dict)
          and M.CONFIG_SLA_TARGET_DAYS in sla_call[2])

    # -- The next tick, one minute later, repeats nothing --
    calls.clear()
    second = await SCH.run_due_jobs(cache, now=NOW + timedelta(minutes=1))
    check("the next tick runs nothing", not second["ran"] and not calls)

    # -- A restart empties the cache; the LEDGER still holds --
    calls.clear()
    third = await SCH.run_due_jobs({}, now=NOW + timedelta(minutes=2))
    check("after a restart the durable ledger still suppresses the run -- this is why "
          "it is not a process-local dict", not third["ran"] and not calls)

    # -- Tomorrow the daily jobs return; the weekly ones do not --
    calls.clear()
    tomorrow = await SCH.run_due_jobs({}, now=NOW + timedelta(days=1))
    ran_jobs = {r["job"] for r in tomorrow["ran"]}
    check("the daily jobs run again tomorrow",
          ran_jobs == {key for key, _l, cadence, _h in M.SCHEDULED_JOBS
                       if cadence == M.JOB_CADENCE_DAILY})
    check("the weekly jobs do not", M.JOB_POLICY_REVIEW not in ran_jobs
          and M.JOB_RETENTION not in ran_jobs)

    # -- Next week the weekly jobs return --
    calls.clear()
    next_week = await SCH.run_due_jobs({}, now=NOW + timedelta(days=7))
    ran_jobs = {r["job"] for r in next_week["ran"]}
    check("the weekly jobs run again next week",
          M.JOB_POLICY_REVIEW in ran_jobs and M.JOB_RETENTION in ran_jobs)

    # -- A failing job is isolated and retried --
    store[M.COLL_JOB_RUNS].docs.clear()
    boom_calls: list = []

    async def boom(actor, company_id, *, notify=True, config=None):
        boom_calls.append(company_id)
        raise RuntimeError("the SLA sweep exploded")

    SLA.sweep_open_breaches = boom
    calls.clear()
    failed = await SCH.run_due_jobs({}, now=NOW)
    ran_jobs = {r["job"] for r in failed["ran"]}
    check("the driver did not raise", isinstance(failed, dict))
    check("the failing job is not reported as run", M.JOB_SLA_SWEEP not in ran_jobs)
    check("every OTHER job still ran -- one failure consumes nobody else's slot",
          ran_jobs == {key for key, _l, _c, _h in M.SCHEDULED_JOBS}
          - {M.JOB_SLA_SWEEP})
    check("the failed job left NO ledger stamp",
          not await SCH.already_ran(C1, M.JOB_SLA_SWEEP, daily))
    check("a successful job DID leave one",
          await SCH.already_ran(C1, M.JOB_PROBATION, daily))

    # The next tick retries the failure and nothing else.
    calls.clear()
    boom_calls.clear()
    retry = await SCH.run_due_jobs({}, now=NOW + timedelta(minutes=1))
    check("the next tick retries the failed job", len(boom_calls) == 1)
    check("and repeats none of the successful ones", not retry["ran"] and not calls)

    # Once it recovers, it records.
    SLA.sweep_open_breaches = fake_sweep
    recovered = await SCH.run_due_jobs({}, now=NOW + timedelta(minutes=2))
    check("a recovered job runs and is recorded",
          {r["job"] for r in recovered["ran"]} == {M.JOB_SLA_SWEEP}
          and await SCH.already_ran(C1, M.JOB_SLA_SWEEP, daily))

    # -- The driver survives a company listing that fails outright --
    async def broken_companies():
        raise RuntimeError("mongo is down")

    ACCESS.hrms_enabled_company_ids = broken_companies
    safe = await SCH.run_due_jobs({}, now=NOW)
    check("an unavailable company list returns empty rather than raising into the loop",
          safe == {"companies": 0, "ran": []})
    ACCESS.hrms_enabled_company_ids = fake_enabled

    # =========================================================================
    section("7. The job table is the specification")
    # =========================================================================
    check("every declared job has a handler",
          {j[0] for j in M.SCHEDULED_JOBS} == set(SCH.JOB_HANDLERS))
    check("every job names a known cadence",
          all(j[2] in (M.JOB_CADENCE_DAILY, M.JOB_CADENCE_WEEKLY)
              for j in M.SCHEDULED_JOBS))
    check("every job hour is a real UTC hour",
          all(0 <= j[3] <= 23 for j in M.SCHEDULED_JOBS))
    check("job keys are unique",
          len({j[0] for j in M.SCHEDULED_JOBS}) == len(M.SCHEDULED_JOBS))
    check("scheduled_job() finds a row", M.scheduled_job(M.JOB_RETENTION) is not None)
    check("scheduled_job() returns None for a stranger",
          M.scheduled_job("not_a_job") is None)
    check("the probation tiers descend", M.PROBATION_REMINDER_DAYS
          == sorted(M.PROBATION_REMINDER_DAYS, reverse=True))

    # The ledger's whole guarantee rests on one row per (company, job). Declared, not
    # hoped for -- without the unique index the insert race leaves two rows and the job
    # can fire twice.
    ledger_indexes = [(keys, opts) for coll, keys, opts in M.HRMS_INDEXES
                      if coll == M.COLL_JOB_RUNS]
    check("the ledger declares a UNIQUE (company_id, job_key) index",
          any(keys == [("company_id", 1), ("job_key", 1)] and opts.get("unique")
              for keys, opts in ledger_indexes))

    # -- The loop actually calls this module --
    import inspect as _inspect
    import app.services.reminder_scheduler as RS
    loop_source = _inspect.getsource(RS.start_reminder_scheduler)
    check("start_reminder_scheduler calls run_due_jobs -- without this the whole phase "
          "is dead code again", "run_due_jobs" in loop_source)

    mongo.get_collection = original_get

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
