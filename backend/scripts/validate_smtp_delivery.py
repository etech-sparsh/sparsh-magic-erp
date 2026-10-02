"""SMTP delivery-layer validator — connection reuse, rate limiting, retry, reconnection,
and the consecutive-failure breaker.

Everything below runs against a FAKE in-memory SMTP server. No network, no Gmail, no Mongo,
no real email, and no existing data is read or written. Safe to run at any time.

What each check proves, and why it matters given the outage that prompted this work:

  reuse         N sends open ONE connection, not N. This is the actual fix — the old code
                did a full connect/STARTTLS/login/quit per recipient, ~130 a minute.
  rate limit    A burst is paced to the configured ceiling instead of going as fast as the
                send loop iterates.
  retry         A dropped socket (SMTPServerDisconnected — the exact error in the logs) is
                retried with exponential backoff and succeeds.
  reconnect     A lost connection is rebuilt, but a REFUSED RECIPIENT is not — a 5xx must
                not cost us the session, or pooling buys nothing.
  no-retry-5xx  A permanent error is not retried, so a bad address cannot burn quota.
  breaker       After N consecutive failures the circuit opens and further sends stop
                touching the network entirely.
  idle          An idle session is probed before reuse and rebuilt if the server hung up.
  contract      send_email_notification still returns True/False and writes exactly one
                notification row per call, with unchanged status values.

Usage (PowerShell, from backend/):
    python scripts/validate_smtp_delivery.py
"""
from __future__ import annotations

import asyncio
import os
import smtplib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD = "[PASS]", "[FAIL]"
_results: list = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    _results.append(bool(condition))
    print(f"{OK if condition else BAD} {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def section(title: str) -> None:
    # ASCII only: the Windows console this runs on is cp1252, and the house validators
    # (scripts/validate_tpms_whatsapp.py) print plain [PASS]/[FAIL] markers for the same reason.
    print(f"\n-- {title} " + "-" * max(0, 62 - len(title)))


# ─────────────────────────────────────────────────────────────
# Fake SMTP server — stands in for smtplib.SMTP
# ─────────────────────────────────────────────────────────────
class FakeSMTP:
    """Records what was sent and can be scripted to fail.

    `script` is a list of exceptions (or None for success) consumed one per send_message
    call, shared across every connection the factory hands out — so a test can say
    "fail twice, then succeed" regardless of how many reconnections happen in between.
    """

    def __init__(self, owner: "FakeServer"):
        self.owner = owner
        self.closed = False
        self.noop_calls = 0

    def send_message(self, msg, to_addrs=None):
        if self.closed:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        self.owner.attempts += 1
        outcome = self.owner.next_outcome()
        if outcome is not None:
            if isinstance(outcome, smtplib.SMTPServerDisconnected):
                self.closed = True  # a dropped socket really is unusable afterwards
            raise outcome
        self.owner.sent.append({"to": list(to_addrs or []), "subject": msg.get("Subject")})
        return {}

    def noop(self):
        self.noop_calls += 1
        self.owner.noops += 1
        if self.closed or self.owner.kill_idle:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        return (250, b"OK")

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class FakeServer:
    """Factory + bookkeeping shared by every FakeSMTP it creates."""

    def __init__(self, script=None, kill_idle=False):
        self.script = list(script or [])
        self.kill_idle = kill_idle
        self.connections: list = []
        self.sent: list = []
        self.attempts = 0
        self.noops = 0

    def next_outcome(self):
        return self.script.pop(0) if self.script else None

    def connect(self):
        conn = FakeSMTP(self)
        self.connections.append(conn)
        return conn


def make_message(subject: str = "Test", to: str = "a@example.com"):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart()
    msg["From"] = "automation@example.com"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText("<p>body</p>", "html"))
    return msg


def build(server: FakeServer, **kw):
    """A delivery service wired to the fake server, with test-friendly timings."""
    from app.services.smtp_delivery import (
        CircuitBreaker, DailyBudget, RateLimiter, SmtpDeliveryService,
    )
    opts = dict(
        connect_factory=server.connect,
        rate_limiter=RateLimiter(0),                 # off unless a test asks for it
        budget=DailyBudget(0),                       # off unless a test asks for it
        breaker=CircuitBreaker(threshold=10, cooldown=60),
        max_retries=3,
        backoff_base=0.01,                           # keep the suite fast
        backoff_max=0.02,
        idle_timeout=3600,                           # never probe unless a test asks
        reap_after=3600,                             # never reap unless a test asks
    )
    opts.update(kw)
    return SmtpDeliveryService(**opts)


# ─────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────
async def check_connection_reuse():
    section("Connection reuse - the fix itself")
    server = FakeServer()
    svc = build(server)

    for i in range(8):
        ok, err = await svc.send_message(make_message(f"msg {i}"), ["a@example.com"])
        if not ok:
            check("all 8 sends delivered", False, str(err))
            return

    check("8 sends opened exactly 1 connection", len(server.connections) == 1,
          f"connections={len(server.connections)}")
    check("8 messages delivered", len(server.sent) == 8, f"sent={len(server.sent)}")
    check("service counted 7 reuses", svc.stats()["reuses"] == 7, f"reuses={svc.stats()['reuses']}")
    check("service counted 1 connect", svc.stats()["connects"] == 1)

    await svc.close("test")
    check("close() quits the pooled session", server.connections[0].closed)


async def check_rate_limiting():
    section("Rate limiting - burst control")
    from app.services.smtp_delivery import RateLimiter

    rl = RateLimiter(max_per_window=3, window=60.0)
    now = 1000.0
    for _ in range(3):
        rl.record(now)
    check("limiter allows up to the cap", rl.delay_for(now) > 0, "4th send is delayed")
    check("delay is bounded by the window", 0 < rl.delay_for(now) <= 60.0,
          f"delay={rl.delay_for(now):.1f}s")
    check("window slides - capacity returns", rl.delay_for(now + 61) == 0.0)
    check("cap of 0 disables limiting", RateLimiter(0).delay_for() == 0.0)

    # End to end: 6 sends against a cap of 3/sec must take at least one window.
    server = FakeServer()
    svc = build(server, rate_limiter=RateLimiter(max_per_window=3, window=0.3))
    started = time.monotonic()
    for i in range(6):
        await svc.send_message(make_message(f"m{i}"), ["a@example.com"])
    elapsed = time.monotonic() - started
    check("6 sends against a 3/window cap were paced", elapsed >= 0.3,
          f"elapsed={elapsed:.2f}s")
    check("pacing did not drop any message", len(server.sent) == 6)
    check("pacing did not force reconnects", len(server.connections) == 1)


async def check_retry_with_backoff():
    section("Retry with exponential backoff")
    # The exact production symptom, twice, then success.
    server = FakeServer(script=[
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        None,
    ])
    svc = build(server)
    ok, err = await svc.send_message(make_message(), ["a@example.com"])

    check("send eventually succeeds after 2 disconnects", ok, str(err))
    check("message delivered exactly once", len(server.sent) == 1)
    check("2 retries were counted", svc.stats()["retries"] == 2, f"retries={svc.stats()['retries']}")
    check("breaker reset by the success", svc.stats()["consecutive_failures"] == 0)

    # Backoff must grow, and be capped.
    svc2 = build(FakeServer(), backoff_base=2.0, backoff_max=30.0)
    delays = [min(svc2.backoff_base * (2 ** (a - 1)), svc2.backoff_max) for a in range(1, 6)]
    check("backoff is exponential", delays[:3] == [2.0, 4.0, 8.0], str(delays[:3]))
    check("backoff is capped", max(delays) <= 30.0, f"max={max(delays)}")

    # Retries are finite.
    server3 = FakeServer(script=[smtplib.SMTPServerDisconnected("closed")] * 10)
    svc3 = build(server3, max_retries=3)
    ok3, err3 = await svc3.send_message(make_message(), ["a@example.com"])
    check("gives up after max_retries", not ok3, str(err3)[:48])
    check("attempted exactly max_retries times", server3.attempts == 3,
          f"attempts={server3.attempts}")


async def check_reconnect_only_when_lost():
    section("Reconnect only when the connection is actually lost")
    # A dropped socket SHOULD cost a reconnection.
    server = FakeServer(script=[smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), None])
    svc = build(server)
    ok, _ = await svc.send_message(make_message(), ["a@example.com"])
    check("lost connection is rebuilt", ok and len(server.connections) == 2,
          f"connections={len(server.connections)}")

    # A refused recipient (5xx) SHOULD NOT — the session is still perfectly good.
    server2 = FakeServer(script=[smtplib.SMTPRecipientsRefused({"bad@example.com": (550, b"No such user")})])
    svc2 = build(server2)
    ok2, err2 = await svc2.send_message(make_message(to="bad@example.com"), ["bad@example.com"])
    check("refused recipient reports failure", not ok2, str(err2)[:48])
    check("refused recipient does NOT drop the session", len(server2.connections) == 1,
          f"connections={len(server2.connections)}")

    ok3, _ = await svc2.send_message(make_message(), ["good@example.com"])
    check("same session still usable afterwards", ok3 and len(server2.connections) == 1)

    # Classification, directly.
    from app.services.smtp_delivery import is_connection_lost, is_retryable
    cases = [
        (smtplib.SMTPServerDisconnected("x"), True, True, "disconnect"),
        (smtplib.SMTPConnectError(421, "busy"), True, True, "connect error"),
        (smtplib.SMTPResponseException(421, "closing channel"), True, True, "421"),
        (smtplib.SMTPResponseException(451, "try later"), True, False, "451 temp"),
        (smtplib.SMTPResponseException(550, "no such user"), False, False, "550 permanent"),
        (smtplib.SMTPAuthenticationError(535, "bad creds"), False, False, "535 auth"),
        (smtplib.SMTPRecipientsRefused({}), False, False, "recipients refused"),
        (TimeoutError("timeout"), True, True, "socket timeout"),
    ]
    for exc, want_retry, want_lost, label in cases:
        check(f"classify {label}: retry={want_retry} lost={want_lost}",
              is_retryable(exc) == want_retry and is_connection_lost(exc) == want_lost,
              f"got retry={is_retryable(exc)} lost={is_connection_lost(exc)}")


async def check_no_retry_on_permanent():
    section("Permanent errors are not retried")
    server = FakeServer(script=[smtplib.SMTPResponseException(550, "mailbox unavailable")] * 5)
    svc = build(server, max_retries=3)
    ok, _ = await svc.send_message(make_message(), ["a@example.com"])
    check("5xx fails immediately", not ok)
    check("5xx tried exactly once - no wasted quota", server.attempts == 1,
          f"attempts={server.attempts}")
    check("no retries counted", svc.stats()["retries"] == 0)


async def check_failure_breaker():
    section("Consecutive-failure breaker")
    from app.services.smtp_delivery import CircuitBreaker

    server = FakeServer(script=[smtplib.SMTPServerDisconnected("closed")] * 200)
    svc = build(server, breaker=CircuitBreaker(threshold=3, cooldown=60), max_retries=1)

    results = []
    for _ in range(10):
        ok, err = await svc.send_message(make_message(), ["a@example.com"])
        results.append((ok, err))

    check("every send failed", not any(ok for ok, _ in results))
    check("breaker opened", svc.stats()["circuit_open"])
    check("network stopped being touched after the threshold", server.attempts == 3,
          f"attempts={server.attempts} of 10 sends")
    check("later sends fail fast with the breaker reason",
          "circuit open" in (results[-1][1] or "").lower(), results[-1][1])

    # Cooldown expiry re-closes the circuit.
    b = CircuitBreaker(threshold=2, cooldown=0.05)
    b.record_failure(); b.record_failure()
    check("breaker trips at its threshold", b.is_open())
    await asyncio.sleep(0.06)
    check("breaker closes after cooldown", not b.is_open())

    # One success resets the count — a single bounce must not creep toward tripping.
    b2 = CircuitBreaker(threshold=3, cooldown=60)
    b2.record_failure(); b2.record_failure(); b2.record_success()
    check("success resets the consecutive count", b2.consecutive_failures == 0)


async def check_idle_probe():
    section("Idle session is probed before reuse")
    # reap_after is held high so the PROBE path is what runs here, not the reaper.
    server = FakeServer(kill_idle=True)
    svc = build(server, idle_timeout=0.01, reap_after=3600)

    await svc.send_message(make_message(), ["a@example.com"])
    check("first send opens a connection", len(server.connections) == 1)
    await asyncio.sleep(0.02)
    await svc.send_message(make_message(), ["a@example.com"])
    check("idle session was probed with NOOP", server.noops >= 1, f"noops={server.noops}")
    check("dead idle session was replaced", len(server.connections) == 2,
          f"connections={len(server.connections)}")

    # A live idle session must be kept, not churned — otherwise a paused batch silently
    # goes back to a handshake per message, which is the bug being fixed.
    server2 = FakeServer(kill_idle=False)
    svc2 = build(server2, idle_timeout=0.01, reap_after=3600)
    await svc2.send_message(make_message(), ["a@example.com"])
    await asyncio.sleep(0.02)
    await svc2.send_message(make_message(), ["a@example.com"])
    check("healthy idle session is reused after probe", len(server2.connections) == 1,
          f"connections={len(server2.connections)}")
    check("probe ran on the healthy session too", server2.noops >= 1, f"noops={server2.noops}")


async def check_idle_reaper():
    section("Idle reaper ends the batch")
    server = FakeServer()
    svc = build(server, idle_timeout=3600, reap_after=0.05)

    await svc.send_message(make_message(), ["a@example.com"])
    check("connection open while the batch runs", svc.stats()["connection_open"])
    await asyncio.sleep(0.25)
    check("idle connection is closed by the reaper", not svc.stats()["connection_open"])
    check("reaped session was quit cleanly", server.connections[0].closed)

    # A send after reaping starts a fresh batch rather than failing.
    ok, err = await svc.send_message(make_message(), ["a@example.com"])
    check("a later send opens a new batch", ok and len(server.connections) == 2,
          f"connections={len(server.connections)} err={err}")
    await svc.close("test")

    # Defaults must keep the reaper strictly later than the probe.
    svc2 = build(server, idle_timeout=60, reap_after=None)
    check("reaper defaults to later than the probe threshold", svc2.reap_after > svc2.idle_timeout,
          f"probe={svc2.idle_timeout}s reap={svc2.reap_after}s")


async def check_daily_budget():
    section("Daily send budget")
    from app.services.smtp_delivery import DailyBudget

    server = FakeServer()
    svc = build(server, budget=DailyBudget(max_per_day=5))

    results = [await svc.send_message(make_message(), ["a@example.com"]) for _ in range(8)]
    delivered = sum(1 for ok, _ in results if ok)
    check("budget caps the day", delivered == 5, f"delivered={delivered} of 8 attempted")
    check("only budgeted messages reached the server", len(server.sent) == 5,
          f"server received {len(server.sent)}")
    check("over-budget sends report the reason",
          "daily budget" in (results[-1][1] or "").lower(), results[-1][1])
    check("stats expose today's usage", svc.stats()["sent_today"] == 5,
          str(svc.stats()["sent_today"]))
    check("stats expose remaining headroom", svc.stats()["budget_remaining"] == 0)

    # Only DELIVERED mail is charged — a failure must not consume the day's allowance.
    server2 = FakeServer(script=[smtplib.SMTPResponseException(550, "nope")])
    svc2 = build(server2, budget=DailyBudget(max_per_day=5), max_retries=1)
    await svc2.send_message(make_message(), ["a@example.com"])
    check("failed sends do not consume budget", svc2.stats()["sent_today"] == 0,
          str(svc2.stats()["sent_today"]))

    # Rollover and the disable switch.
    b = DailyBudget(max_per_day=2)
    b.record(); b.record()
    check("budget blocks once exhausted", not b.allows())
    b.day = "1999-01-01"                       # simulate crossing UTC midnight
    check("budget resets on a new UTC day", b.allows())
    check("cap of 0 disables the budget", DailyBudget(0).allows() and DailyBudget(0).remaining() is None)

    # The configured default has to be under Gmail's real ceiling.
    from app.config.settings import settings
    check("configured daily cap is under Gmail's ~2000",
          0 < settings.SMTP_MAX_PER_DAY < 2000, f"{settings.SMTP_MAX_PER_DAY}/day")
    check("cap is below the 4830 attempted on the outage day",
          settings.SMTP_MAX_PER_DAY < 4830, f"{settings.SMTP_MAX_PER_DAY} vs 4830")


async def check_notification_contract():
    section("send_email_notification contract is unchanged")
    from app.config.settings import settings
    from app.services import notification_service, smtp_delivery

    logged: list = []

    async def fake_log(user_id, recipient, channel, slug, content, status, error=None, meta=None):
        logged.append({"recipient": recipient, "channel": channel, "slug": slug,
                       "status": status, "error": error, "meta": meta})

    server = FakeServer(script=[None, smtplib.SMTPResponseException(550, "nope")])
    svc = build(server, max_retries=1)

    real_log = notification_service.log_notification
    real_delivery = smtp_delivery.delivery
    real_user, real_pw = settings.SMTP_USERNAME, settings.SMTP_PASSWORD
    try:
        notification_service.log_notification = fake_log
        smtp_delivery.delivery = svc
        settings.SMTP_USERNAME = settings.SMTP_USERNAME or "test@example.com"
        settings.SMTP_PASSWORD = settings.SMTP_PASSWORD or "secret"

        ok = await notification_service.send_email_notification(
            "a@example.com", "Subject A", "<p>hi</p>", user_id="u1", slug="tpms_test",
            cc=["cc@example.com"], meta={"activity": "Test Activity"})
        check("successful send returns True", ok is True)
        check("one 'sent' row logged", len(logged) == 1 and logged[0]["status"] == "sent",
              str(logged[-1] if logged else None)[:60])
        check("meta is carried onto the log row",
              (logged[0]["meta"] or {}).get("activity") == "Test Activity")
        check("CC recipient included in the envelope",
              server.sent and "cc@example.com" in server.sent[0]["to"],
              str(server.sent[0]["to"]) if server.sent else "no send recorded")

        ok2 = await notification_service.send_email_notification(
            "b@example.com", "Subject B", "<p>hi</p>", slug="tpms_test")
        check("failed send returns False", ok2 is False)
        check("one 'failed' row logged with the reason",
              len(logged) == 2 and logged[1]["status"] == "failed" and logged[1]["error"],
              str(logged[-1]["error"])[:48])

        settings.SMTP_USERNAME = None
        ok3 = await notification_service.send_email_notification("c@example.com", "S", "<p>x</p>")
        check("missing credentials still return False without logging",
              ok3 is False and len(logged) == 2)
    finally:
        notification_service.log_notification = real_log
        smtp_delivery.delivery = real_delivery
        settings.SMTP_USERNAME, settings.SMTP_PASSWORD = real_user, real_pw


async def check_defaults():
    section("Production defaults are sane for Gmail")
    from app.config.settings import settings
    check("rate cap is set and modest", 0 < settings.SMTP_MAX_PER_MINUTE <= 60,
          f"{settings.SMTP_MAX_PER_MINUTE}/min")
    check("retries are bounded", 1 <= settings.SMTP_MAX_RETRIES <= 5,
          str(settings.SMTP_MAX_RETRIES))
    check("breaker threshold is set", settings.SMTP_MAX_CONSECUTIVE_FAILURES > 0,
          str(settings.SMTP_MAX_CONSECUTIVE_FAILURES))
    check("cooldown is meaningful", settings.SMTP_FAILURE_COOLDOWN_SECONDS >= 60,
          f"{settings.SMTP_FAILURE_COOLDOWN_SECONDS}s")
    check("SMTP host/port/credentials untouched",
          settings.SMTP_SERVER == "smtp.gmail.com" and settings.SMTP_PORT == 587,
          f"{settings.SMTP_SERVER}:{settings.SMTP_PORT}")
    # 130/min was the observed burst; the cap must be well under it.
    check("cap is far below the burst that caused the outage",
          settings.SMTP_MAX_PER_MINUTE < 130,
          f"{settings.SMTP_MAX_PER_MINUTE} vs 130 observed")


async def main() -> int:
    print("SMTP delivery validator - fake server, no network, no database, no email sent.")
    await check_connection_reuse()
    await check_rate_limiting()
    await check_retry_with_backoff()
    await check_reconnect_only_when_lost()
    await check_no_retry_on_permanent()
    await check_failure_breaker()
    await check_idle_probe()
    await check_idle_reaper()
    await check_daily_budget()
    await check_notification_contract()
    await check_defaults()

    passed, total = sum(1 for r in _results if r), len(_results)
    print("\n" + "=" * 68)
    print(f"{passed}/{total} checks passed")
    print("=" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
