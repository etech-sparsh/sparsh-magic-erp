import asyncio
from datetime import datetime, timedelta, timezone
from app.db.mongodb import get_collection
from app.services.notification_service import send_reminder_email
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

from app.utils.calendar_utils import CALENDAR_COLLECTIONS, find_user_by_id
from app.models.tpms import (
    TPMS_EVENT_KIND, TPMS_NOTIFICATIONS_ENABLED,
    STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED,
)

# A TPMS activity in one of these states no longer occupies the calendar, so its still-pending
# reminders are consumed without firing (covers manual cancel, staff confirm, escalation lapse).
_TPMS_TERMINAL = {STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED}

# How far past its trigger a TPMS reminder may be and still be worth sending. Anything older
# is marked sent and skipped — see the note at the send site in check_and_trigger_reminders.
TPMS_REMINDER_MAX_AGE_HOURS = 48

# How long after its trigger time a task/todo reminder is still worth sending.
#
# The recurring engine backfills every missed occurrence after downtime, each with its
# reminders re-armed (sent=False) and a due date already in the past — so every one of them
# qualifies to fire on the very next 60s tick. Without this window, a week of downtime meant a
# week of reminders delivered at once, for deadlines that had already passed.
#
# Anything still inside the window fires normally, so a reminder the scheduler was merely a
# few minutes late for is never lost. Older ones are consumed silently (marked sent, not
# delivered) — the deadline has passed and the task itself already shows as overdue.
REMINDER_MAX_AGE_HOURS = 12

# How long a daily-job claim stays valid before another process may take it over. Long
# enough that a genuinely slow escalation run is never double-started, short enough that a
# process killed mid-run doesn't block the job for the rest of the day.
JOB_LEASE_MINUTES = 30

# ── Reminder delivery retry ──────────────────────────────────────────────────
# A reminder whose email failed is retried rather than being marked delivered, but only a
# few times and never on consecutive ticks: the scheduler runs every 60 seconds, and
# retrying that fast during a provider outage is exactly the behaviour that got the mail
# account throttled. Three attempts, 15 minutes apart, then the reminder is consumed with a
# loud error rather than looping until its stale window closes.
REMINDER_RETRY_BACKOFF_MINUTES = 15
REMINDER_MAX_SEND_ATTEMPTS = 3


def _delivery_succeeded(result) -> bool:
    """Interpret what the non-TPMS reminder senders return.

    `send_reminder_email` -> `send_notification_from_template` returns a dict of per-channel
    booleans, e.g. {"email": True}. Three cases, and only one of them is a failure:

      {}                 nothing was attempted — no active template, or notifications are
                         globally off. A deliberate skip, NOT a delivery failure, so the
                         reminder is consumed rather than retried forever.
      {"email": False}   the send was attempted and failed  -> retry
      {"email": True}    delivered                          -> done

    Treating the dict as a plain boolean would be wrong: {"email": False} is truthy.
    """
    if isinstance(result, dict):
        if not result:
            return True            # nothing attempted; nothing to retry
        return any(bool(v) for v in result.values())
    return bool(result)


def _parse_attempt_time(value):
    """`last_attempt_at` as a naive-UTC datetime. Tolerates the ISO string it is stored as,
    a real datetime, or nothing at all (a reminder written before this field existed)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except Exception:
        return None

# ── Spec §16 trigger schedule ─────────────────────────────────────────────────
# The source installed one time-driven trigger per job. There is a single loop here, so the
# clock times are enforced by gating on the hour and remembering the last run.
#
# Gates use `hour >= N`, not `== N`: if the process is restarted or busy at the scheduled
# minute, the job still runs on the next tick that day rather than being skipped entirely.
# Each job is remembered separately, so a failure in one never consumes another's slot.
#
# Times are UTC — the source's triggers were in the sheet's local zone. Set these to the
# UTC equivalents of your 06:00/07:00 if the business cares about local time of day.
TPMS_AUTOFEED_HOUR = 6      # syncAutoFeed            — daily @ 06:00
TPMS_SCORE_SYNC_HOUR = 6    # syncSuccessMeasures     — daily @ 06:00
TPMS_LADDER_HOUR = 7        # runEscalationLadder     — daily @ 07:00
TPMS_SEED_HOUR = 6          # seedSuccessMeasures     — monthly, 1st @ 06:00


# Which field a reminder's offset is measured from.
# An event happens at `start`, so its reminders anchor there. A task and a todo do NOT:
# both carry the moment that matters — the deadline / due date — in `end`. A task's `start`
# is its recurrence anchor and a todo's `start` is merely its creation timestamp, which is
# why the calendar grid also places both under `end` (see CalendarPage: displayStart).
# Anchoring these to `start` made every "before" reminder resolve to a past trigger time and
# fire on the next 60s tick — a todo's reminder went out seconds after it was created.
DUE_ANCHORED_TYPES = {"task", "todo"}

# TPMS schedule starts are stored as a NAIVE IST wall-clock string (see
# tpms_schedule_service._start_iso → "2026-08-11T15:56:00", no zone marker), unlike every
# other calendar start, which the ERP writes as a UTC-marked ISO string. This offset converts
# that naive IST value to UTC so its reminder trigger lines up with datetime.utcnow(); without
# it, a "5 min before" reminder for a 15:56 IST activity resolved to 15:51 UTC (21:21 IST) and
# never arrived while the user was watching.
IST_OFFSET = timedelta(hours=5, minutes=30)


def get_reminder_anchor(event: dict):
    """The ISO datetime string a reminder's offset is measured against."""
    if event.get("type") in DUE_ANCHORED_TYPES:
        # Fall back to `start` for older docs saved without an `end`.
        return event.get("end") or event.get("start")
    return event.get("start")


async def start_reminder_scheduler():
    logger.info("Starting reminder scheduler background worker...")
    last_recurring_day = None
    last_nudge_day = None
    nudge_state: dict = {}
    tpms_last_run: dict = {}
    # HRMS keeps its run ledger in the database (see hrms_scheduler_service), because
    # re-running a reminder job SENDS THE REMINDER AGAIN and process memory resets on every
    # deploy. This dict is only a cache in front of that ledger, so the ticks after a job
    # has already run today cost no database read.
    hrms_last_run: dict = {}
    while True:
        try:
            await check_and_trigger_reminders()

            # Every tick: move personal todos whose due date/time has passed from Pending to
            # Overdue. Runs at the 60s cadence rather than with the daily job below so the
            # status flips within a minute of the deadline, not at the next midnight. Isolated
            # so a sweep failure can never stop the reminders the rest of the ERP depends on.
            try:
                from app.services.todo_status_service import mark_overdue_todos
                await mark_overdue_todos()
            except Exception as e:
                logger.error(f"Error marking overdue todos: {e}")

            # Once per day (first tick after midnight, and at startup), roll recurring
            # task series forward — creating each day's/week's/month's next occurrence.
            # The day boundary is IST (UTC+5:30), so the next occurrence is created at
            # 12:00 AM IST, not 00:00 UTC (= 5:30 AM IST). The generator applies the same
            # IST boundary internally, so trigger and generation agree.
            today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
            if today != last_recurring_day:
                try:
                    from app.services.recurring_task_service import generate_due_recurring_tasks
                    await generate_due_recurring_tasks()
                    last_recurring_day = today
                except Exception as e:
                    logger.error(f"Error generating recurring tasks: {e}")

            # Once per day, at the configured IST send time (10:00 by default): the
            # time-driven Task & Delegation nudges — daily/weekly due reminders, the overdue
            # alert, and the alternate-day chase on a task waiting for the assigner to close
            # it. Deliberately NOT at the IST midnight boundary the recurrence rollover uses:
            # a reminder that arrives at 3 AM has been dismissed before the working day
            # starts. The day stamp is set only on success, so a failed run retries on the
            # next tick rather than being lost until tomorrow, and can never send twice.
            # Isolated for the same reason as everything else in this loop: a nudge failure
            # must not stop the reminders.
            if today != last_nudge_day:
                try:
                    from app.services.task_nudge_service import is_send_time, sweep_task_nudges
                    if await is_send_time():
                        # Claimed through the same durable ledger the TPMS jobs use. The
                        # in-memory day flag alone has the failure this container's
                        # `restart: always` makes routine: a restart clears it, and the sweep
                        # re-runs. Per-task date stamps mean nothing would be re-sent, but a
                        # restart loop would still re-scan every open task on every tick.
                        await _run_job(nudge_state, "task_nudges", today,
                                       "task nudge sweep", sweep_task_nudges)
                        last_nudge_day = today
                except Exception as e:
                    logger.error(f"Error sweeping task nudges: {e}")

            # TPMS scheduled sweeps, each at its own hour. Isolated so a TPMS failure can
            # never stop the reminder loop the rest of the ERP depends on.
            await run_tpms_scheduled_jobs(tpms_last_run)

            # HRMS governance sweeps — the SLA breach detector, probation and pre-boarding
            # reminders, the policy review notice and the retention purge PROPOSAL. Each
            # gates itself on its own hour and its own ledger entry; `run_due_jobs` never
            # raises, and is wrapped anyway so a change there can never reach this loop.
            #
            # The retention job proposes and never executes: redaction still requires an MD
            # to approve the batch with a typed signature.
            try:
                from app.services.hrms_scheduler_service import run_due_jobs
                await run_due_jobs(hrms_last_run)
            except Exception as e:
                logger.error(f"Error in HRMS scheduled jobs: {e}")
        except Exception as e:
            logger.error(f"Error in reminder scheduler: {e}")
        await asyncio.sleep(60)  # tick every minute; each job gates itself on the clock


async def _claim_job(key, stamp) -> bool:
    """Claim `(job, stamp)` in Mongo. False = someone already ran (or is running) it.

    The in-memory `state` dict alone was not enough. The container runs `restart: always`,
    and the stamp was only written AFTER the job returned — so any restart during a long
    escalation run lost the record entirely and replayed the whole day's mail. A durable
    claim survives that.

    A claim older than the lease is treated as abandoned and taken over, so a process that
    died mid-run doesn't block the job forever.
    """
    from app.models.tpms import COLL_JOB_RUNS
    now = datetime.utcnow()
    lease_cutoff = now - timedelta(minutes=JOB_LEASE_MINUTES)
    col = get_collection(COLL_JOB_RUNS)
    doc = {"job": str(key), "stamp": str(stamp)}
    try:
        existing = await col.find_one(doc)
        if existing:
            if existing.get("status") == "done":
                return False
            started = existing.get("started_at")
            if started and started > lease_cutoff:
                logger.info("TPMS job %s already running elsewhere (since %s) — skipping tick",
                            key, started)
                return False
            # Stale lease: a previous process died mid-run. Take it over.
            logger.warning("TPMS job %s lease expired — reclaiming", key)
            await col.update_one({"_id": existing["_id"]},
                                 {"$set": {"status": "running", "started_at": now}})
            return True
        await col.insert_one({**doc, "status": "running", "started_at": now})
        return True
    except Exception as e:
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            return False  # claimed concurrently
        # Never let the ledger stop a scheduled job — fall back to the in-memory guard.
        logger.error("TPMS job ledger unavailable (%s) — relying on in-memory guard", e)
        return True


async def _finish_job(key, stamp, ok: bool, result=None) -> None:
    """Mark the claim done, or drop it so a failed run retries on the next tick."""
    from app.models.tpms import COLL_JOB_RUNS
    col = get_collection(COLL_JOB_RUNS)
    doc = {"job": str(key), "stamp": str(stamp)}
    try:
        if ok:
            await col.update_one(doc, {"$set": {"status": "done",
                                                "finished_at": datetime.utcnow(),
                                                "result": str(result)[:500]}})
        else:
            await col.delete_one(doc)
    except Exception as e:
        logger.error("TPMS job ledger update failed for %s: %s", key, e)


async def _run_job(state: dict, key, stamp, label: str, fn):
    """Run `fn` once per `stamp` (a date, or a (year, month) tuple for monthly jobs).

    Two guards, in order of cost: the in-memory `state` short-circuits repeat ticks inside
    one process, and the Mongo claim stops a restarted or concurrent process replaying a
    job that already ran today.

    The stamp is still recorded only on success, so a failed run is retried on the next
    tick instead of being silently lost until tomorrow — the claim is dropped on failure
    for exactly that reason.
    """
    if state.get(key) == stamp:
        return
    if not await _claim_job(key, stamp):
        state[key] = stamp  # someone else owns it; stop re-checking this process
        return
    try:
        result = await fn()
        state[key] = stamp
        await _finish_job(key, stamp, True, result)
        logger.info(f"TPMS {label}: {result}")
    except Exception as e:
        await _finish_job(key, stamp, False)
        logger.error(f"TPMS {label} failed: {e}")


async def run_tpms_scheduled_jobs(state: dict):
    """Spec §16 — the four time-driven TPMS jobs, at their specified times.

    Order matters at 06:00: the auto-feed runs before the score sync so the sync sees the
    statuses the feed has just settled. The ladder deliberately runs an hour later, as in
    the source, so it never lapses an activity the feed has not yet accounted for.
    """
    now = datetime.utcnow()
    today = now.date()

    # ── Monthly, 1st @ 06:00 — seed the new month's success-measure rows (insert-only) ──
    if today.day == 1 and now.hour >= TPMS_SEED_HOUR:
        from app.services.tpms_score_service import seed_success_measures
        period = f"{today.year:04d}-{today.month:02d}"
        await _run_job(state, "seed", (today.year, today.month), "success-measure seed",
                       lambda: seed_success_measures(period))

    # ── Daily @ 06:00 — auto-feed, then the score sync ──
    if now.hour >= TPMS_AUTOFEED_HOUR:
        from app.services.tpms_escalation_service import sync_auto_feed
        await _run_job(state, "autofeed", today, "auto-feed", sync_auto_feed)

    if now.hour >= TPMS_SCORE_SYNC_HOUR:
        from app.services.tpms_score_service import sync_success_measures
        await _run_job(state, "score_sync", today, "success-measure sync",
                       lambda: sync_success_measures())

    # ── Daily @ 07:00 — the escalation ladder ──
    if now.hour >= TPMS_LADDER_HOUR:
        from app.services.tpms_escalation_service import run_escalation_ladder
        await _run_job(state, "ladder", today, "escalation ladder", run_escalation_ladder)

    # ── Daily @ 07:00 — Leadership Score: the reminder ladder and cycle notices ──
    #
    # Runs alongside the TPMS ladder and gates itself on the clock the same way, so it
    # needs no scheduler of its own. Every job reads the ASSIGNMENT's status, never a
    # response — nothing here can walk from an answer back to the person who gave it.
    if now.hour >= TPMS_LADDER_HOUR:
        from app.services.leadership_notify_service import run_leadership_jobs
        await _run_job(state, "leadership", today, "leadership reminder ladder",
                       run_leadership_jobs)


async def check_and_trigger_reminders():
    now = datetime.utcnow()
    collections_to_search = CALENDAR_COLLECTIONS + ["calendar_events"]
    
    for col_name in collections_to_search:
        col = get_collection(col_name)
        # We find events that have reminders that are not sent
        query = {"reminders": {"$elemMatch": {"sent": False}}}
        events = await col.find(query).to_list(1000)
        
        for event in events:
            # TPMS activity reminders are suppressed while TPMS notifications are disabled.
            # This gate is TPMS-only (keyed on the `tpms_activity` discriminator) — reminders
            # for every other event/task fire exactly as before. Leaving them unsent (rather
            # than marking them sent) means re-enabling the flag restores them intact.
            is_tpms_event = event.get("kind") == TPMS_EVENT_KIND
            if is_tpms_event and not TPMS_NOTIFICATIONS_ENABLED:
                continue
            reminders = event.get("reminders", [])
            # ── STRICT RULE ──────────────────────────────────────────────────────────
            # A reminder is triggered ONLY when the task/event has one explicitly
            # configured. If the task carries no reminders (empty or missing array),
            # nothing is ever sent — full stop. The $elemMatch query above already
            # selects only events with an unsent reminder; this explicit guard makes the
            # "no reminder configured → no reminder fires" guarantee impossible to break.
            if not reminders:
                continue

            # Personal Todo: once it is completed, its still-pending reminders must NOT fire —
            # mark them consumed (sent) without sending, so a finished todo never nags. Todos
            # only; tasks and sessions keep firing regardless of status (unchanged).
            if event.get("type") == "todo" and (
                event.get("status") == "completed" or event.get("completed_at")
            ):
                if any(not r.get("sent") for r in reminders):
                    for r in reminders:
                        r["sent"] = True
                    await col.update_one({"_id": event["_id"]}, {"$set": {"reminders": reminders}})
                continue

            # A TPMS activity in a terminal state (Cancelled / Completed / Lapsed) must stop
            # nagging — consume its pending reminders without sending. Covers manual cancel,
            # staff confirmation, and the escalation lapse, whichever set the status.
            if is_tpms_event and str(event.get("tpms_status") or "") in _TPMS_TERMINAL:
                if any(not r.get("sent") for r in reminders):
                    for r in reminders:
                        r["sent"] = True
                    await col.update_one({"_id": event["_id"]}, {"$set": {"reminders": reminders}})
                continue

            # A task's/todo's offset is measured from its DUE date (`end`), an event's from
            # when it starts (`start`) — see get_reminder_anchor. Reading `start` directly here
            # meant a task's "1 hour before" resolved against its recurrence anchor, which is
            # normally already in the past, so the reminder fired on the next 60s tick instead
            # of an hour before the deadline.
            event_time_str = get_reminder_anchor(event)
            if not event_time_str: continue

            try:
                # Robust ISO parsing → naive UTC, so it compares directly against utcnow().
                clean_time = event_time_str.replace("Z", "+00:00").replace(" ", "T")
                parsed = datetime.fromisoformat(clean_time)
                if parsed.tzinfo is not None:
                    # Zone-marked (every non-TPMS start; the ERP writes UTC-marked ISO).
                    event_time = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                elif is_tpms_event:
                    # TPMS's one exception: a naive IST wall-clock string. Convert IST→UTC.
                    event_time = parsed - IST_OFFSET
                else:
                    event_time = parsed  # legacy naive value → treat as UTC (unchanged)
            except Exception as e:
                logger.error(f"Date Parse Error for event {event.get('_id')}: {e}")
                continue

            updated = False
            for reminder in reminders:
                if reminder.get("sent"): continue
                
                offset = int(reminder.get("offset_minutes", 0))
                timing = reminder.get("timing_type", "before")
                
                if timing == "before":
                    trigger_time = event_time - timedelta(minutes=offset)
                else:
                    trigger_time = event_time + timedelta(minutes=offset)
                
                # If trigger time reached or passed
                if trigger_time <= now:
                    # A TPMS reminder that is long overdue is consumed WITHOUT sending.
                    # While notifications are disabled these accumulate unsent (see the gate
                    # above), so without this window the first tick after enabling the flag
                    # would deliver every historical reminder at once — three per activity,
                    # to every doer and coach. Recent ones still fire normally.
                    # Scoped to TPMS: other modules have been sending all along and have no
                    # backlog, so their behaviour is unchanged.
                    # Tasks/todos get the same treatment, on a tighter window: the recurring
                    # engine backfills missed occurrences with their reminders re-armed and
                    # their due dates already past, so without this a downtime backlog was
                    # delivered in one burst. See REMINDER_MAX_AGE_HOURS.
                    max_age = (TPMS_REMINDER_MAX_AGE_HOURS if is_tpms_event
                               else REMINDER_MAX_AGE_HOURS)
                    stale = (now - trigger_time) > timedelta(hours=max_age)
                    if stale:
                        logger.info(
                            f"Reminder skipped as stale ({trigger_time.isoformat()}, "
                            f"{'tpms' if is_tpms_event else event.get('type')}) "
                            f"for event {event.get('_id')}"
                        )
                        reminder["sent"] = True   # consumed without sending, as before
                        updated = True
                        continue

                    # A reminder that failed to send is NOT marked sent — it used to be, so
                    # every reminder lost to an SMTP outage was permanently recorded as
                    # delivered. It is retried on a later tick instead.
                    #
                    # Bounded deliberately. Retrying on every 60s tick until the stale window
                    # closes would mean hundreds of attempts per reminder during an outage —
                    # which is the hammering that got the mail account throttled in the first
                    # place. So: wait REMINDER_RETRY_BACKOFF_MINUTES between attempts, and give
                    # up after REMINDER_MAX_SEND_ATTEMPTS.
                    attempts = int(reminder.get("send_attempts") or 0)
                    last_try = _parse_attempt_time(reminder.get("last_attempt_at"))
                    if last_try and (now - last_try) < timedelta(minutes=REMINDER_RETRY_BACKOFF_MINUTES):
                        continue  # still backing off; try again on a later tick

                    delivered = await trigger_reminder_notification(event, reminder)
                    attempts += 1
                    reminder["send_attempts"] = attempts
                    reminder["last_attempt_at"] = now.isoformat()

                    if delivered:
                        reminder["sent"] = True
                    elif attempts >= REMINDER_MAX_SEND_ATTEMPTS:
                        # Out of attempts. Consume it so it cannot loop forever, but say so
                        # loudly — this reminder genuinely never reached anyone.
                        reminder["sent"] = True
                        logger.error(
                            "Reminder GIVEN UP after %d failed attempts for event %s "
                            "(trigger %s) — it was never delivered.",
                            attempts, event.get("_id"), trigger_time.isoformat(),
                        )
                    else:
                        logger.warning(
                            "Reminder not delivered for event %s (attempt %d/%d) — will retry "
                            "in %d minutes.",
                            event.get("_id"), attempts, REMINDER_MAX_SEND_ATTEMPTS,
                            REMINDER_RETRY_BACKOFF_MINUTES,
                        )
                    updated = True
            
            if updated:
                await col.update_one({"_id": event["_id"]}, {"$set": {"reminders": reminders}})


async def _send_tpms_reminder_email(user_data, event) -> bool:
    """Render a TPMS activity reminder through the module's own template layer.

    Side is decided by which collection the recipient came from: a learner is the company
    side, internal staff are the staff side. Strictly respects the template's Active/Inactive
    status — if there is no Active reminder template (with a body) for this activity/side,
    NOTHING is sent (no _default_body fallback). Returns True only when an email was sent.
    """
    from app.services.tpms_notify_service import (
        EVENT_REMINDER, SIDE_COMPANY, SIDE_STAFF, SEND_FORM_LINKS,
        build_map, fill, get_template, log_context, _default_body,
        _link_block, _strip_bare_form_urls, _strip_form_links,
        _ensure_links_delivered, _template_wires_own_button,
    )
    from app.services.tpms_form_link_service import existing_links_for
    from app.services.notification_service import send_email_notification

    side = SIDE_COMPANY if user_data.get("company_id") else SIDE_STAFF
    tpl = await get_template(event.get("activity") or "", EVENT_REMINDER, side)
    mapping = await build_map(event)

    # The reminder for a form-scored activity is the natural place to re-send the link, and
    # reminder templates are written expecting one ({{Form_Links}} / {{Form_Link}}). These are
    # LOOKED UP, never created — see existing_links_for — so the recipient keeps the single URL
    # the schedule mail issued and the log is not double-counted.
    my_links = await existing_links_for(event, str(user_data.get("_id") or ""))
    mapping["Recipient_Name"] = (user_data.get("full_name")
                                 or " ".join(filter(None, [user_data.get("first_name"),
                                                           user_data.get("last_name")])).strip()
                                 or user_data.get("email") or "")
    # Spec parity — when no Active reminder template is configured, send a branded default body
    # rather than silently dropping the reminder (matches the schedule/status mail fallback).
    body_tpl = (tpl or {}).get("body_html")
    if my_links and SEND_FORM_LINKS:
        # A template that builds its own button keeps the raw URL; one that drops a bare
        # placeholder in gets the labelled block, placed where the placeholder already sits.
        mapping["Form_Link"] = (my_links[0]["link"] if _template_wires_own_button(body_tpl or "")
                                else _link_block(my_links))
        mapping["Form_Link_2"] = my_links[1]["link"] if len(my_links) > 1 else ""
        mapping["Form_Links"] = _link_block(my_links)

    if body_tpl:
        subject_tpl = tpl.get("subject") or "[Reminder] {{Title}} – {{Activity}}"
        html = fill(body_tpl, mapping)
    else:
        subject_tpl = "[Reminder] {{Title}} – {{Activity}}"
        html = _default_body(mapping, "Reminder")

    if my_links and SEND_FORM_LINKS:
        html = _strip_bare_form_urls(html)
        html = _ensure_links_delivered(html, my_links)
    # Same scrub the schedule mail gets: no legacy Google-Form URL, no dead empty-href button.
    html = _strip_form_links(html)
    # send_email_notification returns False on failure and never raises. This used to
    # discard the result and `return True` unconditionally, so a reminder that failed was
    # logged "sent" and marked consumed. Return what actually happened.
    return bool(await send_email_notification(
        user_data.get("email"), fill(subject_tpl, mapping), html,
        user_id=str(user_data.get("_id")), slug=f"tpms_reminder_{side}",
        meta=log_context(event),
    ))


async def trigger_reminder_notification(event, reminder) -> bool:
    """Notify every recipient of one reminder.

    Returns True only when EVERY resolved recipient was actually mailed. The caller uses
    that to decide whether the reminder may be marked sent, so a partial failure keeps the
    reminder retryable rather than silently dropping the people who missed out.
    """
    delivered_all = True
    attempted = 0
    user_ids = set()
    user_ids.add(event.get("user_id")) # Always notify the creator
    
    if event.get("type") == "task":
        target = event.get("target_staff_id", [])
        if isinstance(target, list):
            for tid in target: 
                if tid: user_ids.add(tid)
        elif target: user_ids.add(target)
    else:
        for mid in event.get("assigned_member_ids", []) or []:
            if mid: user_ids.add(mid)
        for cid in event.get("coach_ids", []) or []:
            if cid: user_ids.add(cid)
    
    # H2 — honour the reminder's Channel (email / whatsapp / both). Only applied to TPMS
    # activities; every other event/task keeps the original email-always behaviour.
    is_tpms = event.get("kind") == TPMS_EVENT_KIND
    channel = ((reminder or {}).get("reminder_type") or "both").lower()
    send_email_flag = (not is_tpms) or channel in ("email", "both")

    for uid in user_ids:
        if not uid or uid == "null": continue
        try:
            # Fallback search across collections
            user_data = None
            try:
                oid = ObjectId(uid) if isinstance(uid, str) and len(uid) == 24 else uid
                for col_name in ["staff", "learners"]:
                    user_data = await get_collection(col_name).find_one({"_id": oid})
                    if user_data: break
            except:
                pass # Continue search to other users

            if user_data and send_email_flag:
                # Spec §11 — a TPMS activity reminder uses the per-activity `reminder`
                # template (activity × reminder × side) so a configured body is actually
                # applied. Anything else keeps the generic ERP reminder mail.
                if is_tpms:
                    # Respects Active/Inactive: returns False (nothing sent) when the reminder
                    # template is Inactive/unconfigured. Log accurately so the Logs Report never
                    # shows a "sent" reminder that was actually suppressed.
                    attempted += 1
                    did_send = await _send_tpms_reminder_email(user_data, event)
                    if not did_send:
                        delivered_all = False
                    await _log_tpms_reminder(event, reminder, user_data,
                                             "sent" if did_send else "failed", None)
                else:
                    # Pass the specific reminder so the template can be chosen by its
                    # parent_type — a parent_type=="task" reminder always uses the Task
                    # Reminder template, never the Session one.
                    attempted += 1
                    ok = _delivery_succeeded(
                        await send_reminder_email(user_data, event, reminder))
                    if not ok:
                        delivered_all = False
                    await _log_tpms_reminder(event, reminder, user_data,
                                             "sent" if ok else "failed", None)
        except Exception as e:
            delivered_all = False
            logger.error(f"Error notifying user {uid} for reminder: {e}")
            await _log_tpms_reminder(event, reminder, locals().get("user_data"), "failed", str(e))

    # H1/H2 — WhatsApp reminder for TPMS activities when the channel includes it (gated OFF).
    if is_tpms and channel in ("whatsapp", "both"):
        try:
            from app.services.tpms_notify_service import send_whatsapp
            for side in ("company", "staff"):
                await send_whatsapp(event, "reminder", side)
        except Exception as e:
            logger.error(f"TPMS WhatsApp reminder failed: {e}")

    # No recipient resolved at all (deleted users, or the email channel switched off): there
    # is nothing to retry, so report success and let the reminder be consumed.
    return delivered_all if attempted else True


async def _log_tpms_reminder(event, reminder, user_data, status, error):
    """H10 — per-reminder send ledger (TPMS activities only): who, which channel, and any
    error. Best-effort; a logging failure must never affect the reminder itself."""
    if event.get("kind") != TPMS_EVENT_KIND:
        return
    try:
        from app.models.tpms import COLL_REMINDER_LOGS
        await get_collection(COLL_REMINDER_LOGS).insert_one({
            "event_id": str(event.get("_id") or ""),
            "activity": event.get("activity") or "",
            "company_id": event.get("company_id") or "",
            "recipient": (user_data or {}).get("email") or "",
            "recipient_name": (user_data or {}).get("full_name") or (user_data or {}).get("name") or "",
            "channel": (reminder or {}).get("reminder_type") or "email",
            "offset_minutes": (reminder or {}).get("offset_minutes"),
            "timing_type": (reminder or {}).get("timing_type"),
            "status": status,
            "error": error,
            "sent_at": datetime.utcnow(),
        })
    except Exception as le:
        logger.error(f"TPMS reminder-log write failed: {le}")