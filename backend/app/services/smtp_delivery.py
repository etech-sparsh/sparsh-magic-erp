"""
SMTP delivery layer — connection reuse, rate limiting, retry/backoff, failure breaker.

WHY THIS EXISTS
---------------
Every email used to open its own SMTP session: connect → EHLO → STARTTLS → LOGIN → send →
QUIT. The TPMS escalation ladder addresses each recipient individually, so a single nightly
run produced ~130 complete authenticated handshakes per minute and 4,830 in one day. Gmail
throttled the account and began dropping sessions mid-conversation, which smtplib surfaces
as `SMTPServerDisconnected: Connection unexpectedly closed`. Six consecutive days of mail
failed that way, and the retry-free send loop kept the throttle alive by hammering straight
through the failures.

WHAT THIS CHANGES — AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------
Only the socket lifecycle changes. Server, port, STARTTLS, credentials, message bodies,
subjects, recipients and every caller's business logic are untouched: `send_message()` takes
an already-built MIME message and an already-resolved recipient list, exactly as
`smtplib.send_message` does.

Four mechanisms, matching the four things that went wrong:

  1. CONNECTION REUSE      One live session serves consecutive sends. A "batch" is simply a
                           run of sends with gaps shorter than SMTP_IDLE_TIMEOUT_SECONDS —
                           which is precisely the shape the escalation ladder produces, so
                           no caller had to be restructured to benefit.
  2. RATE LIMITING         A sliding window caps sends per minute, so a burst is paced
                           rather than delivered as fast as the loop can iterate.
  3. RETRY + BACKOFF       A lost socket or a 4xx "try again later" is transient: reconnect
                           and retry with exponential backoff. A 5xx is the server judging
                           the message — retrying only burns quota, so it is not retried.
  4. FAILURE BREAKER       After SMTP_MAX_CONSECUTIVE_FAILURES the circuit opens and further
                           sends fail fast without touching the network, so a bad night
                           costs one short burst instead of 4,600 attempts.

CONCURRENCY
-----------
`smtplib` is synchronous and its socket is not thread-safe. Each blocking call runs in a
worker thread via `asyncio.to_thread` so the event loop is never stalled, and an
`asyncio.Lock` serialises access so exactly one coroutine — and therefore one thread — owns
the socket at any moment. Backoff waits use `asyncio.sleep`, so a retry never blocks a
thread either.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import socket
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

from app.config.settings import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Error classification
#
# CAREFUL: smtplib.SMTPException subclasses OSError, so a bare `except OSError` would
# swallow permanent protocol errors as if they were network faults. Every predicate below
# therefore tests the SMTP types BEFORE falling back to the socket types.
# ─────────────────────────────────────────────────────────────
def is_retryable(exc: BaseException) -> bool:
    """Whether re-sending this message could plausibly succeed.

    RFC 5321: 4xx is transient, 5xx is permanent. A refused recipient or a rejected
    credential will be refused identically on the next attempt, so neither is retried.
    """
    if isinstance(exc, smtplib.SMTPResponseException):
        # Covers SMTPSenderRefused / SMTPDataError / SMTPHeloError / SMTPAuthenticationError,
        # all of which carry a real response code.
        return 400 <= int(exc.smtp_code or 0) < 500
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    if isinstance(exc, smtplib.SMTPException):
        # SMTPRecipientsRefused and friends — the socket is fine, the address is not.
        return False
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, OSError))


def is_connection_lost(exc: BaseException) -> bool:
    """Whether the socket itself is gone and must be rebuilt.

    This is what keeps "reconnect only when the connection is actually lost" honest: a 550
    refused recipient leaves a perfectly usable session, and tearing it down would put us
    back to a handshake per message.
    """
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    if isinstance(exc, smtplib.SMTPResponseException):
        # 421 = "service not available, closing transmission channel" — the one response
        # code that means the server is hanging up on us.
        return int(exc.smtp_code or 0) == 421
    if isinstance(exc, smtplib.SMTPException):
        return False
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, OSError))


# ─────────────────────────────────────────────────────────────
# Rate limiter — sliding window
# ─────────────────────────────────────────────────────────────
class RateLimiter:
    """At most `max_per_window` sends in any `window` seconds.

    A sliding window rather than a fixed one: a fixed window lets 2x the limit through at a
    boundary, which is exactly the burst shape being defended against.
    """

    def __init__(self, max_per_window: int, window: float = 60.0):
        self.max_per_window = max_per_window
        self.window = window
        self._stamps: Deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    def delay_for(self, now: Optional[float] = None) -> float:
        """Seconds to wait before the next send is allowed. 0 when there is headroom."""
        if self.max_per_window <= 0:
            return 0.0
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._stamps) < self.max_per_window:
            return 0.0
        return max(0.0, self._stamps[0] + self.window - now)

    def record(self, now: Optional[float] = None) -> None:
        if self.max_per_window <= 0:
            return
        self._stamps.append(time.monotonic() if now is None else now)

    async def acquire(self) -> float:
        """Wait until a send is permitted. Returns how long it waited (for logging)."""
        waited = 0.0
        while True:
            delay = self.delay_for()
            if delay <= 0:
                self.record()
                return waited
            waited += delay
            logger.info("SMTP rate limit: pausing %.2fs (cap %d/min)", delay, self.max_per_window)
            await asyncio.sleep(delay)

    def reset(self) -> None:
        self._stamps.clear()


# ─────────────────────────────────────────────────────────────
# Circuit breaker — consecutive failures
# ─────────────────────────────────────────────────────────────
class DailyBudget:
    """A hard ceiling on messages per UTC day.

    The per-minute limiter paces a burst but says nothing about the total: the outage day
    attempted 4,830 sends spread across hours, every one of them inside any sane per-minute
    cap. This is the backstop that makes exceeding the provider's daily allowance
    structurally impossible rather than merely unlikely.

    Counted in memory. A restart resets the count, which is the safe direction to be wrong:
    it can let a little extra mail through after a crash, but it can never silently block
    mail that should have gone out.
    """

    def __init__(self, max_per_day: int):
        self.max_per_day = max_per_day
        self.day: Optional[str] = None
        self.count = 0
        self._warned = False

    def _roll(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.day != today:
            if self.day is not None and self.count:
                logger.info("SMTP daily budget: %d sent on %s", self.count, self.day)
            self.day, self.count, self._warned = today, 0, False

    def allows(self) -> bool:
        if self.max_per_day <= 0:
            return True
        self._roll()
        if self.count < self.max_per_day:
            return True
        if not self._warned:
            logger.error(
                "SMTP daily budget EXHAUSTED: %d messages sent today (cap %d). Further email "
                "is suppressed until UTC midnight to stay inside the provider's daily limit.",
                self.count, self.max_per_day,
            )
            self._warned = True
        return False

    def record(self) -> None:
        if self.max_per_day <= 0:
            return
        self._roll()
        self.count += 1
        # One warning as the ceiling comes into view, so it is visible before it bites.
        if not self._warned and self.count == int(self.max_per_day * 0.8):
            logger.warning("SMTP daily budget: %d of %d used today", self.count, self.max_per_day)

    def remaining(self) -> Optional[int]:
        if self.max_per_day <= 0:
            return None
        self._roll()
        return max(0, self.max_per_day - self.count)

    def reset(self) -> None:
        self.day, self.count, self._warned = None, 0, False


class CircuitBreaker:
    """Opens after `threshold` consecutive failures and stays open for `cooldown` seconds.

    Counts CONSECUTIVE failures, not a rate: one success proves the server is talking to us
    again and resets the count. That distinguishes "the provider has cut us off" from
    "one address bounced".
    """

    def __init__(self, threshold: int, cooldown: float):
        self.threshold = threshold
        self.cooldown = cooldown
        self.consecutive_failures = 0
        self.opened_at: Optional[float] = None

    def is_open(self, now: Optional[float] = None) -> bool:
        if self.opened_at is None:
            return False
        now = time.monotonic() if now is None else now
        if now - self.opened_at >= self.cooldown:
            logger.info("SMTP breaker: cooldown elapsed, closing circuit and retrying sends")
            self.opened_at = None
            self.consecutive_failures = 0
            return False
        return True

    def retry_after(self, now: Optional[float] = None) -> float:
        if self.opened_at is None:
            return 0.0
        now = time.monotonic() if now is None else now
        return max(0.0, self.opened_at + self.cooldown - now)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> bool:
        """Returns True if this failure tripped the breaker."""
        self.consecutive_failures += 1
        if self.threshold > 0 and self.consecutive_failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic()
            logger.error(
                "SMTP breaker OPEN after %d consecutive failures — pausing all email for %ds "
                "to stop hammering the provider",
                self.consecutive_failures, int(self.cooldown),
            )
            return True
        return False

    def reset(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None


# ─────────────────────────────────────────────────────────────
# The pooled connection
# ─────────────────────────────────────────────────────────────
class SmtpConnection:
    """One live SMTP session, plus the counters that describe the batch it is serving.

    `connect_factory` exists so the validator can substitute a fake server; production always
    uses the real `smtplib.SMTP` against the configured host/port with STARTTLS, unchanged.
    """

    def __init__(self, client):
        self.client = client
        self.opened_at = time.monotonic()
        self.last_used = self.opened_at
        self.delivered = 0
        self.failed = 0

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used

    def age_seconds(self) -> float:
        return time.monotonic() - self.opened_at


def _default_connect() -> smtplib.SMTP:
    """Build a session exactly as the previous per-email code did — same host, port,
    STARTTLS handshake and login. The only addition is an explicit socket timeout, so a
    silently half-open connection fails fast instead of hanging the send."""
    client = smtplib.SMTP(
        settings.SMTP_SERVER, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS
    )
    client.starttls()
    client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
    return client


class SmtpDeliveryService:
    """Serialised, rate-limited, self-healing SMTP sender.

    One instance is shared process-wide (`delivery` below). Tests construct their own with a
    fake `connect_factory` so nothing touches the network.
    """

    def __init__(self, connect_factory=None, rate_limiter=None, breaker=None,
                 max_retries=None, backoff_base=None, backoff_max=None,
                 idle_timeout=None, reap_after=None, budget=None):
        self._connect_factory = connect_factory or _default_connect
        self._conn: Optional[SmtpConnection] = None
        self._lock: Optional[asyncio.Lock] = None
        self._reaper: Optional[asyncio.Task] = None

        self.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter(
            settings.SMTP_MAX_PER_MINUTE
        )
        self.budget = budget if budget is not None else DailyBudget(settings.SMTP_MAX_PER_DAY)
        self.breaker = breaker if breaker is not None else CircuitBreaker(
            settings.SMTP_MAX_CONSECUTIVE_FAILURES, settings.SMTP_FAILURE_COOLDOWN_SECONDS
        )
        self.max_retries = max_retries if max_retries is not None else settings.SMTP_MAX_RETRIES
        self.backoff_base = backoff_base if backoff_base is not None else settings.SMTP_BACKOFF_BASE_SECONDS
        self.backoff_max = backoff_max if backoff_max is not None else settings.SMTP_BACKOFF_MAX_SECONDS
        self.idle_timeout = idle_timeout if idle_timeout is not None else settings.SMTP_IDLE_TIMEOUT_SECONDS
        # Two distinct thresholds for the same idle condition, and they must not collapse
        # into one. `idle_timeout` is when a session stops being trusted, so the next send
        # probes it before reuse. `reap_after` is when an unused session is closed outright,
        # ending the batch. Reaping strictly later leaves a window where a batch can resume
        # on the existing connection after a pause — if the reaper fired first, the probe
        # would be unreachable and every pause would cost a fresh handshake.
        self.reap_after = reap_after if reap_after is not None else self.idle_timeout * 2

        # Lifetime counters, for observability and for the validator's assertions.
        self.connects = 0
        self.reuses = 0
        self.retries = 0
        self.total_delivered = 0
        self.total_failed = 0
        # Permanent rejections (5xx / refused recipient). Tracked separately because they are
        # a data problem, not a provider problem, and must not trip the breaker.
        self.permanent_failures = 0

    # ── lock is created lazily so the service can be constructed outside a running loop ──
    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ── connection lifecycle (all of these run inside a worker thread) ──
    def _open_sync(self) -> SmtpConnection:
        client = self._connect_factory()
        self.connects += 1
        logger.info("SMTP connect: new session to %s:%s (connection #%d)",
                    settings.SMTP_SERVER, settings.SMTP_PORT, self.connects)
        return SmtpConnection(client)

    def _close_sync(self, conn: Optional[SmtpConnection], reason: str) -> None:
        if conn is None:
            return
        # The batch summary belongs here: this is the moment one reused connection's work
        # is finished, whichever way it ended.
        logger.info(
            "SMTP batch complete (%s): %d delivered, %d failed over %.1fs on one connection",
            reason, conn.delivered, conn.failed, conn.age_seconds(),
        )
        try:
            conn.client.quit()
        except Exception:
            # A dead socket cannot be closed politely, and that is not worth reporting.
            try:
                conn.client.close()
            except Exception:
                pass

    def _usable_sync(self, conn: SmtpConnection) -> bool:
        """Probe an idle session with NOOP before trusting it.

        Only idle sessions are probed. A connection in active use has just proved itself by
        delivering, and an extra round-trip per message would give back part of what pooling
        was meant to save.
        """
        if conn.idle_seconds() < self.idle_timeout:
            return True
        try:
            code, _ = conn.client.noop()
            alive = 200 <= int(code) < 400
        except Exception as exc:
            logger.info("SMTP probe: idle session is dead (%s) — will reconnect", type(exc).__name__)
            return False
        if not alive:
            logger.info("SMTP probe: idle session returned %s — will reconnect", code)
        return alive

    def _send_sync(self, message, to_addrs: List[str]) -> bool:
        """One delivery attempt. Returns True if the existing connection was reused.

        Raises the underlying smtplib/socket error; classification and retry live in the
        async caller so backoff can yield the event loop.
        """
        reused = False
        if self._conn is not None:
            if self._usable_sync(self._conn):
                reused = True
            else:
                self._close_sync(self._conn, "idle probe failed")
                self._conn = None
        if self._conn is None:
            self._conn = self._open_sync()

        self._conn.client.send_message(message, to_addrs=to_addrs)
        self._conn.last_used = time.monotonic()
        return reused

    def _drop_sync(self, reason: str) -> None:
        self._close_sync(self._conn, reason)
        self._conn = None

    # ── idle reaper — ends a batch that has gone quiet ──
    def _schedule_reaper(self) -> None:
        if self.reap_after <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._reaper and not self._reaper.done():
            self._reaper.cancel()
        self._reaper = loop.create_task(self._reap_when_idle())

    async def _reap_when_idle(self) -> None:
        try:
            while True:
                async with self._get_lock():
                    if self._conn is None:
                        return
                    remaining = self.reap_after - self._conn.idle_seconds()
                    if remaining <= 0:
                        await asyncio.to_thread(self._drop_sync, "idle")
                        return
                await asyncio.sleep(min(remaining, 5.0))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("SMTP idle reaper stopped: %s", exc)

    # ── public API ──
    async def send_message(self, message, to_addrs: List[str]) -> Tuple[bool, Optional[str]]:
        """Deliver one already-built message. Returns (ok, error_message).

        Never raises: callers log the failure and carry on, exactly as they did when each
        send opened its own connection.
        """
        if self.breaker.is_open():
            wait = int(self.breaker.retry_after())
            error = (f"SMTP circuit open after {self.breaker.consecutive_failures} consecutive "
                     f"failures; retrying in {wait}s")
            logger.warning("SMTP send skipped: %s", error)
            return False, error

        # Checked before the rate limiter: once the day's budget is gone there is nothing to
        # pace, and a caller should learn that immediately rather than after a wait.
        if not self.budget.allows():
            return False, (f"SMTP daily budget exhausted ({self.budget.count}/"
                           f"{self.budget.max_per_day} sent today)")

        await self.rate_limiter.acquire()

        last_error: Optional[Exception] = None
        async with self._get_lock():
            for attempt in range(1, max(1, self.max_retries) + 1):
                try:
                    reused = await asyncio.to_thread(self._send_sync, message, to_addrs)
                except Exception as exc:  # classified below; never propagated to callers
                    last_error = exc
                    lost = is_connection_lost(exc)
                    retryable = is_retryable(exc)
                    if lost:
                        await asyncio.to_thread(self._drop_sync, f"connection lost: {type(exc).__name__}")
                    if not retryable or attempt >= max(1, self.max_retries):
                        break
                    self.retries += 1
                    delay = min(self.backoff_base * (2 ** (attempt - 1)), self.backoff_max)
                    logger.warning(
                        "SMTP send failed (attempt %d/%d): %s: %s — retrying in %.1fs",
                        attempt, self.max_retries, type(exc).__name__, exc, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Delivered.
                if reused:
                    self.reuses += 1
                    logger.debug("SMTP send: reused connection #%d (%d delivered on it)",
                                 self.connects, self._conn.delivered + 1 if self._conn else 0)
                if self._conn is not None:
                    self._conn.delivered += 1
                self.total_delivered += 1
                self.budget.record()   # only successful deliveries count against the day
                self.breaker.record_success()
                if attempt > 1:
                    logger.info("SMTP send succeeded on attempt %d", attempt)
                self._schedule_reaper()
                return True, None

            # Every attempt failed.
            if self._conn is not None:
                self._conn.failed += 1
            self.total_failed += 1

            # The breaker exists to detect the PROVIDER refusing to serve us — a throttle, a
            # dropped socket, a dead network. A permanent 5xx is the opposite: the server is
            # healthy and talking to us, and has judged one message (bad address, rejected
            # sender). Counting those would let a handful of stale addresses in a roster open
            # the circuit and block every module's mail for the cooldown, on a data problem.
            #
            # A permanent failure is not counted, and deliberately does not RESET the counter
            # either: a run of real transient failures interleaved with a bad address is still
            # a run, and must still be able to trip.
            transient = is_retryable(last_error) if last_error else True
            if transient:
                if self.breaker.record_failure():
                    await asyncio.to_thread(self._drop_sync, "breaker tripped")
            else:
                self.permanent_failures += 1
                logger.warning(
                    "SMTP permanent rejection (not counted toward the breaker): %s",
                    last_error,
                )
            self._schedule_reaper()

        error = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown SMTP error"
        logger.error("SMTP send failed permanently after %d attempt(s): %s", self.max_retries, error)
        return False, str(last_error) if last_error else error

    async def close(self, reason: str = "shutdown") -> None:
        """Close the pooled connection and log the batch summary. Safe to call at any time."""
        if self._reaper and not self._reaper.done():
            self._reaper.cancel()
            self._reaper = None
        async with self._get_lock():
            if self._conn is not None:
                await asyncio.to_thread(self._drop_sync, reason)

    def stats(self) -> dict:
        return {
            "connects": self.connects,
            "reuses": self.reuses,
            "retries": self.retries,
            "delivered": self.total_delivered,
            "failed": self.total_failed,
            "consecutive_failures": self.breaker.consecutive_failures,
            "circuit_open": self.breaker.opened_at is not None,
            "connection_open": self._conn is not None,
            "permanent_failures": self.permanent_failures,
            "sent_today": self.budget.count,
            "budget_remaining": self.budget.remaining(),
        }

    def reset(self) -> None:
        """Drop all counters and state WITHOUT touching the socket. Test-support only."""
        self.connects = self.reuses = self.retries = 0
        self.total_delivered = self.total_failed = self.permanent_failures = 0
        self.rate_limiter.reset()
        self.breaker.reset()
        self.budget.reset()
        self._conn = None


# Process-wide instance used by notification_service.
delivery = SmtpDeliveryService()


async def send_message(message, to_addrs: List[str]) -> Tuple[bool, Optional[str]]:
    return await delivery.send_message(message, to_addrs)


async def close(reason: str = "shutdown") -> None:
    await delivery.close(reason)


def stats() -> dict:
    return delivery.stats()
