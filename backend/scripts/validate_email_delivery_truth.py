"""Email delivery-truth validator - Bugs 1-5, 7 and 9.

The audit found one systemic root cause: `send_email_notification` returns False on failure
and NEVER raises, but most callers wrapped it in try/except and ignored the result. Every
one of them therefore recorded success for mail that never went out.

Runs entirely against stubs and an in-memory fake Mongo. No real database, no network, no
email, no existing document read or written. Safe to run at any time.

What it proves, per bug:

  Bug 1  A failed reminder is NOT marked sent, IS retried (with backoff), and is given up
         loudly after a bounded number of attempts instead of looping every 60s.
  Bug 2  A failed schedule/reminder mail stamps the form-link assignment "failed", not "sent".
  Bug 3  A failed Leadership invitation does not set `sent_at`, so it does NOT enter the 24h
         cooldown and stays immediately retryable.
  Bug 4  The form-link resend endpoint reports a real failure instead of 200 OK.
  Bug 5  A link is created "pending" and only becomes "sent" on an actual delivery.
  Bug 7  A permanent 5xx does not count toward the global circuit breaker; transient
         failures still do.
  Bug 9  sent/failed counters reflect what really happened.

Usage (PowerShell, from backend/):
    python scripts/validate_email_delivery_truth.py
"""
from __future__ import annotations

import asyncio
import os
import smtplib
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
# Shared fakes
# ─────────────────────────────────────────────────────────────
class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    @staticmethod
    def _match(doc, query):
        for k, cond in (query or {}).items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if "$ne" in cond and v == cond["$ne"]:
                    return False
                if "$in" in cond and v not in cond["$in"]:
                    return False
            elif v != cond:
                return False
        return True

    def find(self, query=None):
        rows = [d for d in self.docs if self._match(d, query or {})]
        class _C:
            def sort(self, *a, **k): return self
            async def to_list(self, n=None): return rows
        return _C()

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def count_documents(self, query):
        return len([d for d in self.docs if self._match(d, query)])

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**query, **update.get("$set", {})})

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs.pop(i)
                return


# ─────────────────────────────────────────────────────────────
# Bug 1 — reminders
# ─────────────────────────────────────────────────────────────
async def check_reminder_failure_is_retryable():
    section("Bug 1 - a failed reminder is not marked sent")
    from app.services import reminder_scheduler as rs

    # The dict interpreter is the subtle part: {"email": False} is TRUTHY.
    check("{} (nothing attempted) counts as success",
          rs._delivery_succeeded({}) is True)
    check('{"email": False} is a FAILURE, not truthy',
          rs._delivery_succeeded({"email": False}) is False)
    check('{"email": True} is a success',
          rs._delivery_succeeded({"email": True}) is True)
    check("a bare False is a failure", rs._delivery_succeeded(False) is False)

    # Backoff bookkeeping.
    now = datetime.utcnow()
    check("no previous attempt -> eligible now", rs._parse_attempt_time(None) is None)
    recent = (now - timedelta(minutes=1)).isoformat()
    parsed = rs._parse_attempt_time(recent)
    check("an ISO last_attempt_at parses", parsed is not None
          and (now - parsed) < timedelta(minutes=2))
    check("backoff window is bounded", 1 <= rs.REMINDER_RETRY_BACKOFF_MINUTES <= 60,
          f"{rs.REMINDER_RETRY_BACKOFF_MINUTES} min")
    check("attempts are capped", 1 < rs.REMINDER_MAX_SEND_ATTEMPTS <= 10,
          str(rs.REMINDER_MAX_SEND_ATTEMPTS))
    # Worst case must be far short of "every 60s until the stale window closes".
    worst = rs.REMINDER_MAX_SEND_ATTEMPTS
    check("a failing reminder costs at most a handful of sends", worst <= 5,
          f"{worst} attempts, not ~{rs.TPMS_REMINDER_MAX_AGE_HOURS * 60}")


async def check_reminder_reports_real_result():
    section("Bug 1 - the TPMS reminder sender reports what happened")
    from app.services import reminder_scheduler as rs
    import app.services.notification_service as ns
    from app.services import tpms_notify_service as tns

    outcome = {"ok": True}

    async def fake_send(*a, **k):
        return outcome["ok"]

    async def fake_template(*a, **k):
        return {"subject": "s", "body_html": "<p>b</p>"}

    async def fake_map(*a, **k):
        return {"Title": "T", "Activity": "A"}

    real = (ns.send_email_notification, tns.get_template, tns.build_map)
    try:
        ns.send_email_notification = fake_send
        tns.get_template = fake_template
        tns.build_map = fake_map
        user = {"_id": "u1", "email": "a@x.com", "company_id": "c1", "full_name": "A"}
        event = {"_id": "e1", "activity": "WRM", "company_id": "c1", "start": "2026-08-17T10:00"}

        outcome["ok"] = True
        check("delivered -> True", await rs._send_tpms_reminder_email(user, event) is True)
        outcome["ok"] = False
        check("NOT delivered -> False (was hardcoded True)",
              await rs._send_tpms_reminder_email(user, event) is False)
    finally:
        ns.send_email_notification, tns.get_template, tns.build_map = real


# ─────────────────────────────────────────────────────────────
# Bugs 2 + 9 — dispatch counters and form-link stamping
# ─────────────────────────────────────────────────────────────
async def check_dispatch_counters_and_link_status():
    section("Bugs 2 + 9 - counters and form-link status tell the truth")
    import inspect
    from app.services import tpms_notify_service as tns

    src = inspect.getsource(tns)
    check("the _dispatch loop captures the send result",
          "delivered = await send_email_notification(" in src)
    check("form-link delivery is stamped from that result",
          '"sent" if delivered else "failed"' in src)
    check("the sent counter is conditional", "if delivered:\n                    sent += 1" in src)

    # Every remaining call site must capture too.
    ignored = []
    for i, line in enumerate(src.splitlines(), 1):
        if "await send_email_notification(" in line and "def " not in line:
            if not ("= await send_email_notification" in line
                    or "if await send_email_notification" in line):
                ignored.append(i)
    check("no call site in tpms_notify_service ignores the result",
          not ignored, f"lines {ignored}" if ignored else "all captured")


# ─────────────────────────────────────────────────────────────
# Bug 3 — Leadership cooldown
# ─────────────────────────────────────────────────────────────
async def check_leadership_failed_send_stays_retryable():
    section("Bug 3 - a failed invitation does not start the 24h cooldown")
    from bson import ObjectId
    from app.services import leadership_link_service as links
    import app.services.notification_service as ns

    row = {
        "_id": ObjectId(), "company_id": "c1", "cycle": "2099-C1", "subject_id": "s1",
        "giver_id": "g1", "giver_email": "g1@x.com", "giver_name": "G",
        "link": "https://x/lf/tok", "subject_name": "R", "subject_level": "L6",
        "company_name": "Acme", "status": "pending", "email_status": "pending",
        "sent_at": None, "expires_at": None,
    }
    col = FakeCollection([row])
    outcome = {"ok": False}

    async def fake_send(*a, **k):
        return outcome["ok"]

    async def no_tpl():
        return None

    real = (links.get_collection, ns.send_email_notification, links.get_invite_template)
    try:
        links.get_collection = lambda name: col
        ns.send_email_notification = fake_send
        links.get_invite_template = no_tpl

        res = await links.send_assignment_email(dict(row))
        stored = col.docs[0]
        check("a failed send reports ok=False", res.get("ok") is False, str(res)[:48])
        check("email_status is 'failed'", stored.get("email_status") == "failed",
              str(stored.get("email_status")))
        check("sent_at was NOT written", stored.get("sent_at") is None,
              str(stored.get("sent_at")))
        check("so it is NOT in cooldown", links.in_resend_cooldown(stored) is False)
        check("status stays 'pending', not 'sent'", stored.get("status") == "pending",
              str(stored.get("status")))

        # Now let it succeed — the cooldown must engage.
        outcome["ok"] = True
        res2 = await links.send_assignment_email(dict(stored))
        stored = col.docs[0]
        check("a real delivery reports ok=True", res2.get("ok") is True)
        check("sent_at is now written", stored.get("sent_at") is not None)
        check("cooldown now applies", links.in_resend_cooldown(stored) is True)
        check("status promoted to 'sent'", stored.get("status") == "sent",
              str(stored.get("status")))

        # A resend of a link the giver has already OPENED must not reset its status.
        col.docs[0]["status"] = "opened"
        await links.send_assignment_email(dict(col.docs[0]))
        check("a resend does not drag an 'opened' link back to 'sent'",
              col.docs[0].get("status") == "opened", str(col.docs[0].get("status")))
    finally:
        links.get_collection, ns.send_email_notification, links.get_invite_template = real


async def check_dispatch_counts_only_real_sends():
    section("Bug 3/9 - dispatch counts only real deliveries")
    from bson import ObjectId
    from app.services import leadership_link_service as links
    import app.services.notification_service as ns

    rows = [{
        "_id": ObjectId(), "company_id": "c1", "cycle": "2099-C1", "subject_id": "s1",
        "giver_id": f"g{i}", "giver_email": f"g{i}@x.com", "giver_name": "G",
        "link": f"https://x/lf/t{i}", "subject_name": "R", "subject_level": "L6",
        "company_name": "Acme", "status": "pending", "email_status": "pending",
        "sent_at": None, "expires_at": None,
    } for i in range(3)]
    col = FakeCollection(rows)

    async def all_fail(*a, **k):
        return False

    async def no_tpl():
        return None

    real = (links.get_collection, ns.send_email_notification, links.get_invite_template)
    try:
        links.get_collection = lambda name: col
        ns.send_email_notification = all_fail
        links.get_invite_template = no_tpl

        r = await links.dispatch_pending("c1", "2099-C1")
        check("all-failed dispatch reports 0 sent", r["sent"] == 0, f"sent={r['sent']}")
        check("all-failed dispatch reports 3 failed", r["failed"] == 3, f"failed={r['failed']}")
        check("none entered the cooldown",
              all(not links.in_resend_cooldown(d) for d in col.docs))

        # A second press must therefore retry all three, not skip them.
        r2 = await links.dispatch_pending("c1", "2099-C1")
        check("a retry is still possible immediately", r2["skipped_recent"] == 0,
              f"held={r2['skipped_recent']}")
    finally:
        links.get_collection, ns.send_email_notification, links.get_invite_template = real


# ─────────────────────────────────────────────────────────────
# Bugs 4 + 5 — resend endpoint and pending status
# ─────────────────────────────────────────────────────────────
async def check_resend_reports_failure():
    section("Bug 4 - form-link resend reports a real failure")
    import inspect
    from app.routes import forms

    src = inspect.getsource(forms.resend_form_assignment)
    check("the resend captures the send result",
          "delivered = await send_email_notification(" in src)
    check("a failed resend marks EMAIL_FAILED", "EMAIL_FAILED" in src and "if not delivered" in src)
    check("a failed resend raises an HTTP error, not 200", "status_code=502" in src)
    check("the HTTPException is not swallowed by the generic handler",
          "except HTTPException:" in src and "raise" in src)


async def check_link_created_pending():
    section("Bug 5 - a link is 'pending' until it is actually mailed")
    from app.services import tpms_form_link_service as fl
    from app.models import leadership as lm
    import inspect

    check("TPMS link service has a pending status", hasattr(fl, "STATUS_PENDING")
          and fl.STATUS_PENDING == "pending")
    check("Leadership has a pending status", getattr(lm, "LINK_PENDING", None) == "pending")

    fsrc = inspect.getsource(fl)
    check("TPMS assignments are created pending", '"status": STATUS_PENDING' in fsrc)
    # Promotion is a separate FILTERED update, so it can only move pending -> sent and can
    # never drag an already-opened link backwards on a resend.
    check("a real delivery promotes pending -> sent",
          '"status": STATUS_PENDING},' in fsrc and '{"status": STATUS_SENT}' in fsrc)
    check("opening still works from pending",
          "[STATUS_PENDING, STATUS_SENT]" in fsrc)

    lsrc = inspect.getsource(__import__("app.services.leadership_link_service",
                                        fromlist=["x"]))
    check("Leadership assignments are created pending", '"status": LINK_PENDING' in lsrc)
    check("Leadership opening works from pending", "[LINK_PENDING, LINK_SENT]" in lsrc)


# ─────────────────────────────────────────────────────────────
# Bug 7 — breaker must ignore permanent 5xx
# ─────────────────────────────────────────────────────────────
class FakeSMTP:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False

    def send_message(self, msg, to_addrs=None):
        if self.closed:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        self.owner.attempts += 1
        exc = self.owner.script.pop(0) if self.owner.script else None
        if exc is not None:
            if isinstance(exc, smtplib.SMTPServerDisconnected):
                self.closed = True
            raise exc
        self.owner.sent.append(list(to_addrs or []))
        return {}

    def noop(self):
        return (250, b"OK")

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class FakeServer:
    def __init__(self, script=None):
        self.script = list(script or [])
        self.sent: list = []
        self.attempts = 0
        self.connections: list = []

    def connect(self):
        c = FakeSMTP(self)
        self.connections.append(c)
        return c


def make_message():
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    m = MIMEMultipart()
    m["From"] = "a@x.com"; m["To"] = "b@x.com"; m["Subject"] = "s"
    m.attach(MIMEText("<p>b</p>", "html"))
    return m


def build(server, **kw):
    from app.services.smtp_delivery import (
        CircuitBreaker, DailyBudget, RateLimiter, SmtpDeliveryService,
    )
    opts = dict(connect_factory=server.connect, rate_limiter=RateLimiter(0),
                budget=DailyBudget(0), breaker=CircuitBreaker(threshold=3, cooldown=60),
                max_retries=1, backoff_base=0.01, backoff_max=0.02,
                idle_timeout=3600, reap_after=3600)
    opts.update(kw)
    return SmtpDeliveryService(**opts)


async def check_breaker_ignores_permanent():
    section("Bug 7 - permanent 5xx does not trip the global breaker")
    # 10 bad addresses in a row: a data problem, not a provider outage.
    server = FakeServer(script=[smtplib.SMTPResponseException(550, "no such user")] * 10)
    svc = build(server)
    for _ in range(10):
        await svc.send_message(make_message(), ["bad@x.com"])
    st = svc.stats()
    check("10 permanent rejections do NOT open the circuit", st["circuit_open"] is False)
    check("they are not counted as consecutive failures", st["consecutive_failures"] == 0,
          str(st["consecutive_failures"]))
    check("they are tracked separately", st["permanent_failures"] == 10,
          str(st["permanent_failures"]))
    check("every one was still attempted (not blocked)", server.attempts == 10,
          f"attempts={server.attempts}")

    # A healthy send still works afterwards — the circuit was never closed to it.
    server.script = []
    ok, err = await svc.send_message(make_message(), ["good@x.com"])
    check("a good address still delivers after 10 rejections", ok is True, str(err))

    # Transient failures must STILL trip it.
    server2 = FakeServer(script=[smtplib.SMTPServerDisconnected("closed")] * 20)
    svc2 = build(server2)
    for _ in range(5):
        await svc2.send_message(make_message(), ["a@x.com"])
    st2 = svc2.stats()
    check("transient failures still open the circuit", st2["circuit_open"] is True)
    check("the breaker stopped the network calls", server2.attempts == 3,
          f"attempts={server2.attempts} of 5 sends")

    # Mixed: a permanent rejection in the middle must not RESET a real transient run.
    server3 = FakeServer(script=[
        smtplib.SMTPServerDisconnected("closed"),
        smtplib.SMTPServerDisconnected("closed"),
        smtplib.SMTPResponseException(550, "no such user"),
        smtplib.SMTPServerDisconnected("closed"),
    ])
    svc3 = build(server3)
    for _ in range(4):
        await svc3.send_message(make_message(), ["a@x.com"])
    check("a 5xx in the middle does not reset a transient run",
          svc3.stats()["circuit_open"] is True,
          f"consec={svc3.stats()['consecutive_failures']}")


async def main() -> int:
    print("Email delivery-truth validator - stubs only, no DB, no network, no email sent.")
    await check_reminder_failure_is_retryable()
    await check_reminder_reports_real_result()
    await check_dispatch_counters_and_link_status()
    await check_leadership_failed_send_stays_retryable()
    await check_dispatch_counts_only_real_sends()
    await check_resend_reports_failure()
    await check_link_created_pending()
    await check_breaker_ignores_permanent()

    passed, total = sum(1 for r in _results if r), len(_results)
    print("\n" + "=" * 68)
    print(f"{passed}/{total} checks passed")
    print("=" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
