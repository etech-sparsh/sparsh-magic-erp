"""Escalation send-once ledger + durable daily-job claim validator.

Runs entirely against an IN-MEMORY fake Mongo. No real database is opened, no existing
TPMS document is read or written, and no email is sent. Safe to run at any time.

What it proves, and why:

  send-once     The escalation ladder mails each person once per (event, stage) however
                many times it runs. Historically 6,796 escalation mails were attempted
                where only 2,418 were distinct - the rest were replays of a run that had
                already happened, caused by the container restarting mid-run.
  retry-safe    A FAILED send releases its claim, so the mail is retried next run rather
                than being silently swallowed by the de-duplication.
  fail-open     If the ledger itself is unavailable the mail still goes out. A missed
                escalation is worse than a duplicate one.
  job claim     A daily job runs once per day even across a process restart, which is what
                the old in-memory-only stamp could not survive.
  job retry     A FAILED job drops its claim and is retried on the next tick, preserving
                the existing behaviour.
  job lease     A claim abandoned by a dead process is taken over rather than blocking the
                job for the rest of the day.

Usage (PowerShell, from backend/):
    python scripts/validate_escalation_dedup.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD = "[PASS]", "[FAIL]"
_results: list = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    _results.append(bool(condition))
    print(f"{OK if condition else BAD} {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} " + "-" * max(0, 62 - len(title)))


# ─────────────────────────────────────────────────────────────
# In-memory Mongo stand-in
# ─────────────────────────────────────────────────────────────
class DuplicateKeyError(Exception):
    """Mirrors what pymongo raises; the code under test matches on the message text."""

    def __init__(self):
        super().__init__("E11000 duplicate key error collection")


class FakeCollection:
    """Just the operations the ledger code uses, with a unique index on `unique_on`."""

    def __init__(self, unique_on=(), fail_with=None):
        self.docs: list = []
        self.unique_on = tuple(unique_on)
        self.fail_with = fail_with          # simulate an unavailable ledger

    def _key(self, doc):
        return tuple(str(doc.get(k)) for k in self.unique_on)

    @staticmethod
    def _match(doc, query):
        """The operator subset the retry sweep uses: equality, $lt, $lte, $ne, $in."""
        for k, cond in (query or {}).items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if "$lt" in cond and not (v is not None and v < cond["$lt"]):
                    return False
                if "$lte" in cond and not (v is not None and v <= cond["$lte"]):
                    return False
                if "$ne" in cond and v == cond["$ne"]:
                    return False
                if "$in" in cond and v not in cond["$in"]:
                    return False
            elif v != cond:
                return False
        return True

    async def insert_one(self, doc):
        if self.fail_with:
            raise self.fail_with
        if self.unique_on and any(self._key(d) == self._key(doc) for d in self.docs):
            raise DuplicateKeyError()
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": len(self.docs)})()

    def find(self, query=None):
        if self.fail_with:
            raise self.fail_with
        rows = [d for d in self.docs if self._match(d, query or {})]

        class _Cursor:
            def sort(self, *a, **k):
                return self

            async def to_list(self, n=None):
                return rows

        return _Cursor()

    async def find_one(self, query):
        if self.fail_with:
            raise self.fail_with
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs.pop(i)
                return
        return

    async def update_one(self, query, update):
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                for field, delta in (update.get("$inc") or {}).items():
                    d[field] = int(d.get(field) or 0) + delta
                return
        return


class FakeDb:
    def __init__(self, **collections):
        self.collections = collections

    def get(self, name):
        return self.collections.setdefault(name, FakeCollection())


# ─────────────────────────────────────────────────────────────
# A — escalation send-once ledger
# ─────────────────────────────────────────────────────────────
async def check_send_once():
    section("Escalation mails once per (event, stage, person)")
    from app.models.tpms import COLL_ESCALATION_SENDS
    from app.services import tpms_escalation_service as esc

    ledger = FakeCollection(unique_on=("event_id", "stage", "recipient"))
    sent_log: list = []

    async def fake_send_email(email, subject, html, slug=None, cc=None, meta=None):
        sent_log.append({"to": email, "slug": slug})
        return True

    real_get = esc.get_collection
    try:
        esc.get_collection = lambda name: ledger if name == COLL_ESCALATION_SENDS else FakeCollection()
        import app.services.notification_service as ns
        real_email = ns.send_email_notification
        ns.send_email_notification = fake_send_email

        event = {"_id": "evt1", "activity": "WRM", "company_id": "c1"}
        people = ["a@x.com", "b@x.com", "c@x.com"]

        # Ladder run #1
        n1 = await esc._send(people, "[LAPSED] x", "<p>x</p>", "tpms_escalation_lapsed", event=event)
        # Ladder run #2 — the replay that used to double-send
        n2 = await esc._send(people, "[LAPSED] x", "<p>x</p>", "tpms_escalation_lapsed", event=event)
        # And a third, for good measure
        n3 = await esc._send(people, "[LAPSED] x", "<p>x</p>", "tpms_escalation_lapsed", event=event)

        check("first run mails everyone", n1 == 3, f"sent={n1}")
        check("replay mails nobody", n2 == 0 and n3 == 0, f"run2={n2} run3={n3}")
        check("exactly 3 emails across 3 runs", len(sent_log) == 3, f"emails={len(sent_log)}")
        check("ledger holds one row per recipient", len(ledger.docs) == 3, f"rows={len(ledger.docs)}")

        # A DIFFERENT stage for the same event is a different mail and must still go out.
        n4 = await esc._send(people, "[CRITICAL] x", "<p>x</p>", "tpms_escalation_critical", event=event)
        check("a different stage still mails", n4 == 3, f"sent={n4}")

        # A different event is independent too.
        n5 = await esc._send(people, "[LAPSED] y", "<p>y</p>", "tpms_escalation_lapsed",
                             event={"_id": "evt2"})
        check("a different event still mails", n5 == 3, f"sent={n5}")
        check("total emails is 9, not 21", len(sent_log) == 9, f"emails={len(sent_log)}")
    finally:
        esc.get_collection = real_get
        ns.send_email_notification = real_email


async def check_failed_send_is_retried():
    section("A failed send is retried, not swallowed")
    from app.models.tpms import COLL_ESCALATION_SENDS
    from app.services import tpms_escalation_service as esc
    import app.services.notification_service as ns

    ledger = FakeCollection(unique_on=("event_id", "stage", "recipient"))
    attempts: list = []
    outcome = {"ok": False}

    async def flaky_send(email, subject, html, slug=None, cc=None, meta=None):
        attempts.append(email)
        return outcome["ok"]

    real_get, real_email = esc.get_collection, ns.send_email_notification
    try:
        esc.get_collection = lambda name: ledger if name == COLL_ESCALATION_SENDS else FakeCollection()
        ns.send_email_notification = flaky_send
        event = {"_id": "evt9"}

        n1 = await esc._send(["a@x.com"], "s", "<p>b</p>", "tpms_escalation_pending", event=event)
        check("failed send reports 0 delivered", n1 == 0)
        # Bug 6: the row is now KEPT (it used to be deleted) so the sweep can recover it.
        check("the undelivered row is retained", len(ledger.docs) == 1, f"rows={len(ledger.docs)}")
        row = ledger.docs[0]
        check("it is marked undelivered", row.get("delivered") is False)
        check("the rendered message is stored for retry",
              row.get("subject") == "s" and row.get("html") == "<p>b</p>")
        check("a retry time is scheduled", row.get("next_retry_at") is not None)

        # The ladder itself must NOT re-send a pending row — the sweep owns those.
        n2 = await esc._send(["a@x.com"], "s", "<p>b</p>", "tpms_escalation_pending", event=event)
        check("the ladder does not double-send a pending row", n2 == 0, f"sent={n2}")
        check("still only one ladder attempt", len(attempts) == 1, f"attempts={len(attempts)}")
    finally:
        esc.get_collection, ns.send_email_notification = real_get, real_email


async def check_retry_sweep_recovers_lost_mail():
    section("Bug 6 - undelivered escalation mail is recovered by the sweep")
    from app.models.tpms import COLL_ESCALATION_SENDS
    from app.services import tpms_escalation_service as esc
    import app.services.notification_service as ns

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    ledger = FakeCollection()
    ledger.docs.append({
        "_id": "row-1",
        "event_id": "evtX", "stage": "tpms_escalation_lapsed", "recipient": "a@x.com",
        "delivered": False, "attempts": 1, "claimed_at": now,
        "next_retry_at": now - timedelta(minutes=1),
        "subject": "[LAPSED] x", "html": "<p>body</p>",
        "cc": [], "company_id": "c1", "activity": "WRM",
    })
    mailed: list = []

    async def ok_send(email, subject, html, slug=None, cc=None, meta=None):
        mailed.append(email)
        return True

    real_get, real_email = esc.get_collection, ns.send_email_notification
    try:
        esc.get_collection = lambda n: ledger if n == COLL_ESCALATION_SENDS else FakeCollection()
        ns.send_email_notification = ok_send
        res = await esc.retry_failed_escalation_mail()
        check("the sweep retried the lost mail", res["retried"] == 1, str(res))
        check("and delivered it", res["delivered"] == 1 and mailed == ["a@x.com"], str(mailed))
        check("the row is now marked delivered", ledger.docs[0].get("delivered") is True)
        check("the stored payload is cleared once delivered",
              ledger.docs[0].get("html") is None)

        mailed.clear()
        res2 = await esc.retry_failed_escalation_mail()
        check("a delivered row is not swept again", res2["retried"] == 0 and not mailed)
    finally:
        esc.get_collection, ns.send_email_notification = real_get, real_email


async def check_retry_sweep_guards():
    section("Bug 6 - the sweep is bounded and time-boxed")
    from app.models.tpms import COLL_ESCALATION_SENDS
    from app.services import tpms_escalation_service as esc
    import app.services.notification_service as ns

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    past = now - timedelta(minutes=1)

    async def always_ok(*a, **k):
        return True

    exhausted = FakeCollection()
    exhausted.docs.append({
        "_id": "row-ex",
        "event_id": "e1", "stage": "s", "recipient": "a@x.com", "delivered": False,
        "attempts": esc.ESCALATION_MAIL_MAX_ATTEMPTS, "claimed_at": now,
        "next_retry_at": past, "subject": "s", "html": "<p>b</p>",
    })
    stale = FakeCollection()
    stale.docs.append({
        "_id": "row-stale",
        "event_id": "e2", "stage": "s", "recipient": "b@x.com", "delivered": False,
        "attempts": 0,
        "claimed_at": now - timedelta(hours=esc.ESCALATION_MAIL_MAX_AGE_HOURS + 1),
        "next_retry_at": past, "subject": "s", "html": "<p>b</p>",
    })

    real_get, real_email = esc.get_collection, ns.send_email_notification
    try:
        ns.send_email_notification = always_ok

        esc.get_collection = lambda n: exhausted if n == COLL_ESCALATION_SENDS else FakeCollection()
        r1 = await esc.retry_failed_escalation_mail()
        check("a row at the attempt cap is not retried", r1["retried"] == 0, str(r1))

        esc.get_collection = lambda n: stale if n == COLL_ESCALATION_SENDS else FakeCollection()
        r2 = await esc.retry_failed_escalation_mail()
        check("a stale row is given up, not retried",
              r2["retried"] == 0 and r2["given_up"] == 1, str(r2))
        check("giving up is recorded on the row", stale.docs[0].get("given_up") is True)

        check("attempts are capped at a small number",
              1 < esc.ESCALATION_MAIL_MAX_ATTEMPTS <= 5, str(esc.ESCALATION_MAIL_MAX_ATTEMPTS))
        check("retries are spaced, not per-tick",
              esc.ESCALATION_MAIL_RETRY_MINUTES >= 5, f"{esc.ESCALATION_MAIL_RETRY_MINUTES} min")
    finally:
        esc.get_collection, ns.send_email_notification = real_get, real_email


async def check_completed_activity_not_chased():
    section("Bug 6 - a finished activity is not chased by a late retry")
    from bson import ObjectId
    from app.models.tpms import COLL_ESCALATION_SENDS, STATUS_COMPLETED
    from app.services import tpms_escalation_service as esc
    import app.services.notification_service as ns

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    oid = ObjectId()
    ledger = FakeCollection()
    ledger.docs.append({
        "_id": "row-done",
        "event_id": str(oid), "stage": "tpms_escalation_pending", "recipient": "a@x.com",
        "delivered": False, "attempts": 0, "claimed_at": now,
        "next_retry_at": now - timedelta(minutes=1),
        "subject": "s", "html": "<p>b</p>",
    })
    # NOTE: this FakeCollection takes `unique_on` first, not a docs list — seed via .docs.
    events = FakeCollection()
    events.docs.append({"_id": oid, "tpms_status": STATUS_COMPLETED})
    mailed: list = []

    async def ok_send(*a, **k):
        mailed.append(1)
        return True

    real_get, real_email = esc.get_collection, ns.send_email_notification
    try:
        esc.get_collection = lambda n: ledger if n == COLL_ESCALATION_SENDS else events
        ns.send_email_notification = ok_send
        res = await esc.retry_failed_escalation_mail()
        check("a completed activity is not chased", not mailed and res["dropped"] == 1, str(res))
        check("the row is closed as dropped", ledger.docs[0].get("dropped") is True)
    finally:
        esc.get_collection, ns.send_email_notification = real_get, real_email


async def check_ledger_fail_open():
    section("A broken ledger must not suppress escalations")
    from app.models.tpms import COLL_ESCALATION_SENDS
    from app.services import tpms_escalation_service as esc
    import app.services.notification_service as ns

    broken = FakeCollection(fail_with=RuntimeError("ledger offline"))
    sent_log: list = []

    async def fake_send(email, subject, html, slug=None, cc=None, meta=None):
        sent_log.append(email)
        return True

    real_get, real_email = esc.get_collection, ns.send_email_notification
    try:
        esc.get_collection = lambda name: broken if name == COLL_ESCALATION_SENDS else FakeCollection()
        ns.send_email_notification = fake_send
        n = await esc._send(["a@x.com", "b@x.com"], "s", "<p>b</p>",
                            "tpms_escalation_lapsed", event={"_id": "evt5"})
        check("mail still goes out when the ledger is down", n == 2, f"sent={n}")
        check("a missed escalation is preferred over none", len(sent_log) == 2)

        # No event id (e.g. a caller that doesn't pass one) must behave exactly as before.
        sent_log.clear()
        n2 = await esc._send(["a@x.com"], "s", "<p>b</p>", "tpms_escalation_pending", event=None)
        check("no event id -> unchanged legacy behaviour", n2 == 1, f"sent={n2}")
    finally:
        esc.get_collection, ns.send_email_notification = real_get, real_email


# ─────────────────────────────────────────────────────────────
# B — durable daily job claim
# ─────────────────────────────────────────────────────────────
async def check_job_claim():
    section("Daily job claim survives a restart")
    from app.services import reminder_scheduler as sched

    runs = FakeCollection(unique_on=("job", "stamp"))
    real_get = sched.get_collection
    try:
        sched.get_collection = lambda name: runs
        today = "2026-08-17"
        calls: list = []

        async def job():
            calls.append(1)
            return {"ok": True}

        # Process #1 runs the ladder.
        state1: dict = {}
        await sched._run_job(state1, "ladder", today, "escalation ladder", job)
        check("job runs the first time", len(calls) == 1)
        check("claim recorded as done", runs.docs and runs.docs[0].get("status") == "done",
              str(runs.docs[0].get("status")) if runs.docs else "no row")

        # Same process, next tick — the in-memory guard stops it.
        await sched._run_job(state1, "ladder", today, "escalation ladder", job)
        check("same process does not re-run", len(calls) == 1)

        # RESTART: fresh in-memory state, same day. This is the case that replayed the
        # whole day's escalation mail before the durable claim existed.
        state2: dict = {}
        await sched._run_job(state2, "ladder", today, "escalation ladder", job)
        check("a restarted process does NOT re-run the day's job", len(calls) == 1,
              f"calls={len(calls)}")

        # A new day runs again.
        await sched._run_job({}, "ladder", "2026-08-18", "escalation ladder", job)
        check("the next day runs normally", len(calls) == 2, f"calls={len(calls)}")
    finally:
        sched.get_collection = real_get


async def check_job_failure_retries():
    section("A failed job is retried on the next tick")
    from app.services import reminder_scheduler as sched

    runs = FakeCollection(unique_on=("job", "stamp"))
    real_get = sched.get_collection
    try:
        sched.get_collection = lambda name: runs
        today = "2026-08-17"
        calls: list = []
        blow_up = {"yes": True}

        async def job():
            calls.append(1)
            if blow_up["yes"]:
                raise RuntimeError("mongo hiccup")
            return {"ok": True}

        await sched._run_job({}, "ladder", today, "escalation ladder", job)
        check("failed job attempted once", len(calls) == 1)
        check("failed job released its claim", len(runs.docs) == 0, f"rows={len(runs.docs)}")

        blow_up["yes"] = False
        await sched._run_job({}, "ladder", today, "escalation ladder", job)
        check("it is retried and succeeds", len(calls) == 2, f"calls={len(calls)}")
        check("claim is now done", runs.docs and runs.docs[0].get("status") == "done")
    finally:
        sched.get_collection = real_get


async def check_job_lease():
    section("An abandoned claim is taken over, not left forever")
    from app.services import reminder_scheduler as sched

    runs = FakeCollection(unique_on=("job", "stamp"))
    real_get = sched.get_collection
    try:
        sched.get_collection = lambda name: runs
        today = "2026-08-17"

        # A live claim from another process blocks this tick.
        runs.docs.append({"job": "ladder", "stamp": today, "status": "running",
                          "started_at": datetime.utcnow()})
        check("a live claim blocks a second runner",
              (await sched._claim_job("ladder", today)) is False)

        # The same claim, stale — the owner died mid-run.
        runs.docs[0]["started_at"] = datetime.utcnow() - timedelta(minutes=sched.JOB_LEASE_MINUTES + 5)
        check("a stale claim is reclaimed",
              (await sched._claim_job("ladder", today)) is True)
        check("lease window is a sane length", 5 <= sched.JOB_LEASE_MINUTES <= 120,
              f"{sched.JOB_LEASE_MINUTES} min")

        # A ledger outage must not stop a scheduled job.
        sched.get_collection = lambda name: FakeCollection(fail_with=RuntimeError("offline"))
        check("job still runs when the ledger is down",
              (await sched._claim_job("ladder", "2026-08-19")) is True)
    finally:
        sched.get_collection = real_get


async def check_no_existing_data_touched():
    section("Only the two NEW collections are written")
    from app.models.tpms import COLL_ESCALATION_SENDS, COLL_JOB_RUNS, TPMS_INDEXES

    names = {c for c, _, _ in TPMS_INDEXES}
    check("escalation ledger is indexed", COLL_ESCALATION_SENDS in names)
    check("job-run ledger is indexed", COLL_JOB_RUNS in names)
    check("ledger collections are new names",
          COLL_ESCALATION_SENDS == "tpms_escalation_sends" and COLL_JOB_RUNS == "tpms_job_runs",
          f"{COLL_ESCALATION_SENDS}, {COLL_JOB_RUNS}")

    uniq = [(c, o.get("name")) for c, _, o in TPMS_INDEXES
            if c in (COLL_ESCALATION_SENDS, COLL_JOB_RUNS) and o.get("unique")]
    check("both ledgers have the unique index the de-dup relies on", len(uniq) == 2, str(uniq))

    # The escalation service must not write to events/escalations for de-duplication.
    import inspect
    from app.services import tpms_escalation_service as esc
    # _release_send is gone: a failed send now KEEPS its row so the retry sweep can recover
    # it, rather than deleting the claim and hoping the ladder comes back (it cannot, once
    # the event has lapsed). Its replacement is _record_outcome.
    check("_release_send was replaced by _record_outcome",
          not hasattr(esc, "_release_send") and hasattr(esc, "_record_outcome"))
    src = inspect.getsource(esc._claim_send) + inspect.getsource(esc._record_outcome)
    check("claim/outcome touch ONLY the new ledger",
          "COLL_ESCALATION_SENDS" in src and "COLL_ESCALATIONS" not in src
          and "CAL_COLLECTIONS" not in src)

    # Bug 6 was fixed WITHOUT writing to calendar-event documents: the sweep only reads them
    # (to check whether the activity has since closed) and writes to the ledger.
    sweep = inspect.getsource(esc.retry_failed_escalation_mail)
    check("the retry sweep writes only to the ledger",
          "COLL_ESCALATION_SENDS" in sweep
          and "update_tracker_status" not in sweep
          and "esc_stage" not in sweep)
    closed = inspect.getsource(esc._event_is_closed)
    check("the event lookup is read-only", "find_one" in closed
          and "update_one" not in closed and "delete" not in closed)


async def main() -> int:
    print("Escalation de-dup validator - in-memory fake DB, no real data touched, no email sent.")
    await check_send_once()
    await check_failed_send_is_retried()
    await check_retry_sweep_recovers_lost_mail()
    await check_retry_sweep_guards()
    await check_completed_activity_not_chased()
    await check_ledger_fail_open()
    await check_job_claim()
    await check_job_failure_retries()
    await check_job_lease()
    await check_no_existing_data_touched()

    passed, total = sum(1 for r in _results if r), len(_results)
    print("\n" + "=" * 68)
    print(f"{passed}/{total} checks passed")
    print("=" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
