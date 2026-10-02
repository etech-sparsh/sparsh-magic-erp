"""
TPMS ▸ escalation services.

⚠ THE APPS SCRIPT RUNS **TWO** INDEPENDENT ESCALATION ENGINES ON DIFFERENT TIMELINES.
Both are ported here because both run in production today, and the instruction is to
replicate the source exactly. They do not agree with each other:

  Engine A — runEscalationLadder (code.js:3755, daily 07:00) — the one that EMAILS.
      D+1  [Pending Action] → owners + HODs + HRs, cc SMOps      esc_stage 1
      D+2  [CRITICAL]       → MDs (fallback HOD+HR), cc SMOps    esc_stage 2
      D+3  [LAPSED]         → everyone; status becomes Lapsed    esc_stage 3

  Engine B — syncAutoFeed (code.js:2714, daily 06:00) — writes ROWS, sends NOTHING.
      overdue ≥1d  → open an Action_Item (follow-up tracker)
      overdue ≥5d  → open an Escalation, level HOD@5 / HR@7 / MD@10
      completed    → close the action, resolve the escalation

Net effect (unchanged from the source): an activity is force-lapsed on day 3 by Engine A,
while the Escalations table Engine B feeds doesn't open a row until day 5. The Escalation
Dashboard therefore shows a different progression from the one recipients experience.
A third ladder (T−2/T/T+2/T+4/T+5/T+7/T+10) is displayed in the UI as "system logic" and
is not implemented in the source — it is not implemented here either.

Both engines are idempotent and keyed by event id, so re-running is safe.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.tpms import (
    AUTO_ACTION_MIN_DAYS, AUTO_ESCALATION_MIN_DAYS,
    COLL_ACTION_ITEMS, COLL_ESCALATIONS, COLL_ESCALATION_SENDS,
    LADDER_CRITICAL_DAYS, LADDER_LAPSE_DAYS, LADDER_PENDING_DAYS,
    STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED, STATUS_SCHEDULED,
    TPMS_EVENT_KIND, TPMS_NOTIFICATIONS_ENABLED, erp_status_for, escalation_level,
)
from app.services.tpms_schedule_service import CAL_COLLECTIONS, update_tracker_status

logger = logging.getLogger(__name__)

# Statuses the sweeps skip entirely (code.js:3775 / 2751).
SKIP_STATUSES = {STATUS_COMPLETED, STATUS_CANCELLED, STATUS_LAPSED}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_between(a: str, b: str) -> int:
    try:
        return (datetime.fromisoformat(str(b)[:10]) - datetime.fromisoformat(str(a)[:10])).days
    except Exception:
        return 0


async def _open_tpms_events() -> List[tuple]:
    """Every TPMS activity across the calendar collections, as (doc, collection)."""
    out = []
    for coll in CAL_COLLECTIONS:
        for doc in await get_collection(coll).find({"kind": TPMS_EVENT_KIND}).to_list(5000):
            out.append((doc, coll))
    return out


# ─────────────────────────────────────────────────────────────
# Recipient resolution — port of escalationRecipients_ (code.js:3713)
#
# DEVIATION, documented: the sheet carried per-employee HOD_Email / HR_Email / MD_Email
# columns. ERP users have no such columns, so we resolve by DEPARTMENT within the
# company. This is precisely the Apps Script's own company-wide fallback path
# (code.js:3727-3733), which is what actually fires in their data — most of those
# columns are blank.
# ─────────────────────────────────────────────────────────────
async def escalation_recipients(event: dict) -> Dict[str, List[str]]:
    company_id = str(event.get("company_id") or "")
    member_ids = {str(m) for m in (event.get("assigned_member_ids") or [])}
    staff_ids = {str(s) for s in (event.get("coach_ids") or [])}

    owners, hods, hrs, mds, smops = [], [], [], [], []
    if company_id:
        users = await get_collection("learners").find(
            {"company_id": company_id, "is_active": {"$ne": False}}
        ).to_list(1000)
        for u in users:
            email = (u.get("email") or "").strip()
            if not email:
                continue
            # C8 — escalation routing keys on the governance ROLE. Prefer an explicit
            # `governance_role` (HOD/HR/MD) when present, so `department` can hold the real
            # org department (Sales, Ops…); falls back to `department` for un-migrated users.
            dept = (u.get("governance_role") or u.get("department") or "").strip().lower()
            if str(u["_id"]) in member_ids:
                owners.append(email)
            if dept == "hod":
                hods.append(email)
            elif dept == "hr":
                hrs.append(email)
            elif dept == "md":
                mds.append(email)

    if staff_ids:
        from bson import ObjectId
        oids = []
        for s in staff_ids:
            try:
                oids.append(ObjectId(s))
            except Exception:
                pass
        if oids:
            for u in await get_collection("staff").find({"_id": {"$in": oids}}).to_list(200):
                if (u.get("email") or "").strip():
                    smops.append(u["email"].strip())

    dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
    return {"owners": dedupe(owners), "hods": dedupe(hods), "hrs": dedupe(hrs),
            "mds": dedupe(mds), "smops": dedupe(smops)}


def _esc_body(event: dict, label: str, note: str) -> str:
    """Port of escBody_ (code.js:3740)."""
    start = str(event.get("start") or "")
    return (
        f'<div style="font-family:Arial,sans-serif;color:#1e293b">'
        f'<h3 style="color:#b91c1c">{label}: {event.get("title") or ""}</h3>'
        f"<p>{note}</p>"
        f'<table style="border-collapse:collapse;font-size:14px">'
        f'<tr><td style="padding:3px 10px;color:#64748b">Activity</td>'
        f'<td style="padding:3px 10px"><b>{event.get("activity") or ""}</b></td></tr>'
        f'<tr><td style="padding:3px 10px;color:#64748b">Company</td>'
        f'<td style="padding:3px 10px">{event.get("company_name") or ""}</td></tr>'
        f'<tr><td style="padding:3px 10px;color:#64748b">Scheduled</td>'
        f'<td style="padding:3px 10px">{start[:10]} {start[11:16]}</td></tr>'
        f"</table></div>"
    )


# ── Undelivered-escalation retry ─────────────────────────────────────────────
# WHY THE LEDGER RETRIES, AND NOT THE LADDER
#
# The obvious fix for "a failed escalation is lost" is to advance `esc_stage` only when the
# mail was delivered. That does not work, for two reasons:
#
#   1. The lapse stage also sets tpms_status = Lapsed, and a Lapsed event is skipped at the
#      top of the ladder (SKIP_STATUSES). So a failed lapse mail would never be retried
#      anyway — the ladder can no longer see the event.
#   2. Lapsing is a BUSINESS state: an activity is overdue on day 3 whether or not anyone
#      could be emailed. Gating it on SMTP would let a mail outage silently change what the
#      dashboards report.
#
# So the stage and the status still advance exactly as before, and the undelivered MAIL is
# kept in the ledger with its rendered body and retried by its own sweep. Every byte of new
# state lives in `tpms_escalation_sends` — no existing calendar-event document is written.
ESCALATION_MAIL_MAX_ATTEMPTS = 3
ESCALATION_MAIL_RETRY_MINUTES = 30
# Past this, an escalation is stale: the situation has moved on and mailing about it is
# noise. The row is closed as given-up rather than retried forever.
ESCALATION_MAIL_MAX_AGE_HOURS = 24


async def _claim_send(event_id: str, stage: str, recipient: str) -> bool:
    """Reserve the right to mail `recipient` for this (event, stage). False = already owned.

    The unique index on (event_id, stage, recipient) does the work: the insert either
    succeeds — this caller owns the send — or raises a duplicate-key error, meaning an
    earlier run already handled it. That is what makes the ladder safe to run twice.

    Claiming BEFORE the send is deliberate. Marking afterwards leaves a window where a crash
    between delivery and mark produces a duplicate on the next run.

    A duplicate key now means "some row already exists" — delivered, or awaiting retry. The
    retry sweep owns the pending ones, so the ladder must not re-send them itself.

    A ledger failure must never suppress an escalation: if the claim itself errors we return
    True and mail anyway, preferring a possible duplicate over a missed alert.
    """
    if not event_id or not recipient:
        return True  # nothing to key on — behave exactly as before
    try:
        await get_collection(COLL_ESCALATION_SENDS).insert_one({
            "event_id": str(event_id),
            "stage": stage,
            "recipient": recipient,
            "sent_on": _today(),
            "claimed_at": datetime.now(timezone.utc),
            "delivered": False,
            "attempts": 0,
        })
        return True
    except Exception as e:
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            logger.info("TPMS escalation: %s already handled for %s on event %s — skipping",
                        stage, recipient, event_id)
            return False
        logger.error("TPMS escalation ledger unavailable (%s) — sending without dedup", e)
        return True


async def _record_outcome(event_id: str, stage: str, recipient: str, *, delivered: bool,
                          subject: str = "", html: str = "", cc: Optional[List[str]] = None,
                          company_id: str = "", activity: str = "",
                          error: Optional[str] = None) -> None:
    """Stamp what happened onto the claim row.

    A FAILED send keeps its row (it used to be deleted) and stores the rendered message, so
    `retry_failed_escalation_mail` can re-send exactly what was meant to go out without
    re-deriving recipients or re-rendering anything.
    """
    if not event_id or not recipient:
        return
    now = datetime.now(timezone.utc)
    updates = {
        "delivered": delivered,
        "last_attempt_at": now,
        "error": None if delivered else (error or "Delivery failed"),
    }
    if delivered:
        updates.update({"delivered_at": now, "next_retry_at": None,
                        "subject": None, "html": None, "cc": None})
    else:
        # Payload retained ONLY while undelivered, so the ledger does not accumulate message
        # bodies for mail that already went out.
        updates.update({
            "subject": subject, "html": html, "cc": list(cc or []),
            "company_id": str(company_id or ""), "activity": activity or "",
            "next_retry_at": now + timedelta(minutes=ESCALATION_MAIL_RETRY_MINUTES),
        })
    try:
        await get_collection(COLL_ESCALATION_SENDS).update_one(
            {"event_id": str(event_id), "stage": stage, "recipient": recipient},
            {"$set": updates, "$inc": {"attempts": 1}},
        )
    except Exception as e:
        logger.error("TPMS escalation: could not record outcome for %s/%s: %s",
                     stage, recipient, e)


async def _send(recipients: List[str], subject: str, html: str, slug: str,
                cc: Optional[List[str]] = None, event: Optional[dict] = None) -> int:
    """Spec §6 — `recipients` are addressed on To, `cc` is copied. Each To recipient gets
    their own message with the same CC list, so nobody sees the full distribution.

    TPMS notifications globally disabled → suppress escalation mails only. The ladder's
    STATE transitions (esc_stage bumps, Lapsed status) still run; this silences the mail.

    Every send is now claimed in `tpms_escalation_sends` first, so a person is mailed once
    per (event, stage) no matter how many times the ladder runs. Recipients, CC, subject,
    body, stages and timings are all unchanged — only repeat delivery of an identical mail
    is suppressed. 6,796 escalation mails were attempted historically where 2,418 were
    distinct; the rest were replays of runs that had already happened.
    """
    if not TPMS_NOTIFICATIONS_ENABLED:
        return 0
    from app.services.notification_service import send_email_notification
    from app.services.tpms_notify_service import log_context
    # Spec §14 — carry the activity/company onto the delivery log so escalation sends show
    # the same context in the Logs Report as every other TPMS mail kind.
    meta = log_context(event) if event else None
    to_list = list(dict.fromkeys(e for e in recipients if e))
    cc_list = [e for e in dict.fromkeys(cc or []) if e and e not in to_list]
    event_id = str((event or {}).get("_id") or "")
    sent = 0
    skipped = 0
    company_id = str((event or {}).get("company_id") or "")
    activity = (event or {}).get("activity") or ""
    for email in to_list:
        if not await _claim_send(event_id, slug, email):
            skipped += 1
            continue
        try:
            ok = await send_email_notification(email, subject, html, slug=slug, cc=cc_list, meta=meta)
            if ok:
                sent += 1
                await _record_outcome(event_id, slug, email, delivered=True)
            else:
                # Delivery failed (throttled, refused, breaker open). The row is KEPT, with
                # the rendered message, so the retry sweep can send it later — the ladder
                # itself will not see this event again once its stage/status has advanced.
                await _record_outcome(event_id, slug, email, delivered=False,
                                      subject=subject, html=html, cc=cc_list,
                                      company_id=company_id, activity=activity)
        except Exception as e:
            logger.error(f"TPMS escalation mail to {email} failed: {e}")
            await _record_outcome(event_id, slug, email, delivered=False,
                                  subject=subject, html=html, cc=cc_list,
                                  company_id=company_id, activity=activity, error=str(e))
    if skipped:
        logger.info("TPMS escalation %s: %d sent, %d already handled earlier (event %s)",
                    slug, sent, skipped, event_id)
    return sent


async def retry_failed_escalation_mail() -> dict:
    """Re-send escalation mail that was claimed but never delivered.

    This is what closes Bug 6 without touching a single calendar-event document: the ladder
    advances its stage and status exactly as it always did, and the undelivered message is
    recovered from the ledger instead of being lost.

    Three guards keep it from becoming noise:
      • bounded — ESCALATION_MAIL_MAX_ATTEMPTS, spaced ESCALATION_MAIL_RETRY_MINUTES apart;
      • time-boxed — nothing older than ESCALATION_MAIL_MAX_AGE_HOURS is retried;
      • state-checked — if the activity has since been completed or cancelled, the mail is
        dropped rather than sent. Chasing someone about work they have already finished is
        worse than not chasing them at all.
    """
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"retried": 0, "delivered": 0, "given_up": 0, "dropped": 0}

    from app.services.notification_service import send_email_notification

    now = datetime.now(timezone.utc)
    col = get_collection(COLL_ESCALATION_SENDS)
    try:
        rows = await col.find({
            "delivered": False,
            "attempts": {"$lt": ESCALATION_MAIL_MAX_ATTEMPTS},
            "next_retry_at": {"$lte": now},
        }).to_list(500)
    except Exception as e:
        logger.error("TPMS escalation retry sweep could not read the ledger: %s", e)
        return {"retried": 0, "delivered": 0, "given_up": 0, "dropped": 0, "error": str(e)}

    retried = delivered = given_up = dropped = 0

    for row in rows:
        claimed_at = row.get("claimed_at")
        if claimed_at and claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        too_old = claimed_at and (now - claimed_at) > timedelta(hours=ESCALATION_MAIL_MAX_AGE_HOURS)

        if too_old:
            await col.update_one({"_id": row["_id"]},
                                 {"$set": {"delivered": False, "given_up": True,
                                           "next_retry_at": None, "subject": None, "html": None}})
            given_up += 1
            logger.error(
                "TPMS escalation mail GIVEN UP (stale) — %s to %s for event %s was never delivered.",
                row.get("stage"), row.get("recipient"), row.get("event_id"))
            continue

        # Has the activity moved on since the mail was queued?
        if await _event_is_closed(row.get("event_id")):
            await col.update_one({"_id": row["_id"]},
                                 {"$set": {"delivered": False, "dropped": True,
                                           "next_retry_at": None, "subject": None, "html": None}})
            dropped += 1
            continue

        subject, html = row.get("subject") or "", row.get("html") or ""
        if not subject or not html:
            # Nothing to re-send (a row from before the payload was retained).
            await col.update_one({"_id": row["_id"]},
                                 {"$set": {"given_up": True, "next_retry_at": None}})
            given_up += 1
            continue

        retried += 1
        try:
            ok = await send_email_notification(
                row["recipient"], subject, html, slug=row.get("stage"),
                cc=list(row.get("cc") or []),
                meta={"activity": row.get("activity"), "company_id": row.get("company_id")},
            )
        except Exception as e:
            ok = False
            logger.error("TPMS escalation retry to %s failed: %s", row.get("recipient"), e)

        if ok:
            delivered += 1
            await _record_outcome(row["event_id"], row["stage"], row["recipient"], delivered=True)
        else:
            await _record_outcome(
                row["event_id"], row["stage"], row["recipient"], delivered=False,
                subject=subject, html=html, cc=list(row.get("cc") or []),
                company_id=row.get("company_id", ""), activity=row.get("activity", ""))
            # attempts was just incremented; if that exhausts the budget, say so loudly.
            if int(row.get("attempts") or 0) + 1 >= ESCALATION_MAIL_MAX_ATTEMPTS:
                given_up += 1
                logger.error(
                    "TPMS escalation mail GIVEN UP after %d attempts — %s to %s for event %s "
                    "was never delivered.",
                    ESCALATION_MAIL_MAX_ATTEMPTS, row.get("stage"),
                    row.get("recipient"), row.get("event_id"))

    if retried or given_up or dropped:
        logger.info("TPMS escalation retry sweep: %d retried, %d delivered, %d given up, "
                    "%d dropped (activity closed)", retried, delivered, given_up, dropped)
    return {"retried": retried, "delivered": delivered,
            "given_up": given_up, "dropped": dropped}


async def _event_is_closed(event_id: str) -> bool:
    """True when the activity has been completed or cancelled since the mail was queued."""
    if not event_id:
        return False
    from bson import ObjectId
    try:
        oid = ObjectId(str(event_id))
    except Exception:
        return False
    for coll in CAL_COLLECTIONS:
        try:
            doc = await get_collection(coll).find_one({"_id": oid})
        except Exception:
            continue
        if doc:
            return str(doc.get("tpms_status") or "") in {STATUS_COMPLETED, STATUS_CANCELLED}
    return False


# ─────────────────────────────────────────────────────────────
# ENGINE A — runEscalationLadder (code.js:3755). Daily ~07:00.
# ─────────────────────────────────────────────────────────────
async def run_escalation_ladder() -> dict:
    """D+1 pending → D+2 critical → D+3 Lapsed. Calendar days; weekends counted.

    Skips rows where the doer has already marked done — waiting on staff confirmation
    is not "overdue" (code.js:3776).
    """
    today = _today()
    pending = critical = lapsed = 0

    # Recover anything a previous run queued but could not deliver. Done FIRST so a mail
    # held over from an outage goes out before today's new escalations compete for the
    # provider's rate budget.
    retry = await retry_failed_escalation_mail()

    for event, coll in await _open_tpms_events():
        status = event.get("tpms_status") or STATUS_SCHEDULED
        if status in SKIP_STATUSES:
            continue
        if event.get("learner_done"):
            continue
        event_day = str(event.get("start") or "")[:10]
        if not event_day or event_day >= today:
            continue

        overdue = _days_between(event_day, today)
        stage = int(event.get("esc_stage") or 0)
        recipients = await escalation_recipients(event)
        title = event.get("title") or ""
        activity = event.get("activity") or ""
        updates: dict = {}

        # Spec §6 recipient table — To: Owner, HOD, HR. CC: SMOps/OM.
        if overdue >= LADDER_PENDING_DAYS and stage < 1:
            to = recipients["owners"] + recipients["hods"] + recipients["hrs"]
            if to:
                await _send(
                    to,
                    f"[Pending Action] {title} – {activity} not updated",
                    _esc_body(event, "Pending Action Escalation",
                              f"This activity was scheduled on {event_day} and has not been "
                              "marked complete. Please update its status today."),
                    "tpms_escalation_pending",
                    cc=recipients["smops"], event=event,
                )
            updates["esc_stage"] = stage = 1
            pending += 1

        # To: MD (falling back to HOD+HR when no MD resolves). CC: SMOps, Owner.
        if overdue >= LADDER_CRITICAL_DAYS and stage < 2:
            to = recipients["mds"] or (recipients["hods"] + recipients["hrs"])
            if to:
                await _send(
                    to,
                    f"[CRITICAL] {title} – {activity} overdue",
                    _esc_body(event, "Critical Escalation",
                              f"This activity (scheduled {event_day}) is still not completed "
                              "after 2 days. Immediate attention required before it lapses."),
                    "tpms_escalation_critical",
                    cc=recipients["smops"] + recipients["owners"], event=event,
                )
            updates["esc_stage"] = stage = 2
            critical += 1

        # To: Owner, HOD, HR, MD. CC: SMOps.
        if overdue >= LADDER_LAPSE_DAYS and stage < 3:
            to = (recipients["owners"] + recipients["hods"]
                  + recipients["hrs"] + recipients["mds"])
            if to:
                await _send(
                    to,
                    f"[LAPSED] {title} – {activity}",
                    _esc_body(event, "Activity Lapsed",
                              f"This activity (scheduled {event_day}) was not completed within "
                              "the allowed window and has been automatically marked LAPSED."),
                    "tpms_escalation_lapsed",
                    cc=recipients["smops"], event=event,
                )
            updates.update({
                "esc_stage": 3,
                "tpms_status": STATUS_LAPSED,
                "status": erp_status_for(STATUS_LAPSED),
            })
            lapsed += 1
            await update_tracker_status(str(event["_id"]), STATUS_LAPSED)

        if updates:
            updates["updated_at"] = datetime.utcnow()
            await get_collection(coll).update_one({"_id": event["_id"]}, {"$set": updates})

    msg = (f"TPMS escalation ladder: {pending} pending, {critical} critical, {lapsed} lapsed, "
           f"{retry.get('delivered', 0)} recovered from earlier failures [{today}]")
    logger.info(msg)
    return {"pending": pending, "critical": critical, "lapsed": lapsed,
            "date": today, "retry": retry}


# ─────────────────────────────────────────────────────────────
# ENGINE B — syncAutoFeed (code.js:2714). Daily ~06:00.
# Writes Action_Items + Escalations. Sends no mail. Idempotent by event id.
# ─────────────────────────────────────────────────────────────
async def sync_auto_feed() -> dict:
    today = _today()
    now = datetime.utcnow()
    actions_created = actions_closed = esc_created = esc_resolved = 0

    companies: Dict[str, dict] = {}
    for c in await get_collection("companies").find({}).to_list(1000):
        companies[str(c["_id"])] = c

    for event, _coll in await _open_tpms_events():
        event_id = str(event["_id"])
        company_id = str(event.get("company_id") or "")
        company = companies.get(company_id) or {}
        company_name = event.get("company_name") or company.get("name") or company_id
        om = company.get("owner") or ""
        status = event.get("tpms_status") or STATUS_SCHEDULED
        event_day = str(event.get("start") or "")[:10]
        activity = event.get("activity") or ""
        overdue = _days_between(event_day, today) if event_day else 0

        # ── Closed activities: close the follow-up, resolve the escalation ──
        if status in (STATUS_COMPLETED, STATUS_CANCELLED):
            res = await get_collection(COLL_ACTION_ITEMS).update_one(
                {"event_id": event_id, "status": {"$ne": "Closed"}},
                {"$set": {"status": "Closed", "closed_at": now}},
            )
            actions_closed += res.modified_count

            completed_day = event.get("completed_at")
            completed_day = (completed_day.date().isoformat()
                             if isinstance(completed_day, datetime) else today)
            res = await get_collection(COLL_ESCALATIONS).update_one(
                {"event_id": event_id, "status": {"$ne": "Resolved"}},
                {"$set": {
                    "status": "Resolved",
                    "actual_date": completed_day,
                    "resolution_date": completed_day,
                    "resolution_method": "Auto: activity completed",
                    "resolved_by": om or "System",
                }},
            )
            esc_resolved += res.modified_count
            continue

        # ── Action item at overdue ≥ 1 day ──
        if overdue >= AUTO_ACTION_MIN_DAYS:
            existing = await get_collection(COLL_ACTION_ITEMS).find_one({"event_id": event_id})
            if existing:
                await get_collection(COLL_ACTION_ITEMS).update_one(
                    {"_id": existing["_id"]}, {"$set": {"delay_days": overdue}}
                )
            else:
                members = event.get("assigned_member_ids") or []
                owner_id = str(members[0]) if members else None
                # Spec §18 — the auto-created follow-up's Owner defaults to the first doer,
                # or literally "HOD" when the activity carries none, so the Action Items
                # table never shows a blank owner.
                owner_name, owner_email = ("HOD" if not owner_id else None), None
                if owner_id:
                    from app.utils.calendar_utils import find_user_by_id
                    u = await find_user_by_id(owner_id)
                    if u:
                        owner_name = (u.get("full_name")
                                      or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                                      or u.get("email"))
                        owner_email = u.get("email")
                await get_collection(COLL_ACTION_ITEMS).insert_one({
                    "event_id": event_id,
                    "company_id": company_id,
                    "company_name": company_name,
                    "activity": activity,
                    "action": f"Follow up: {activity or event.get('title') or ''}",
                    "owner_id": owner_id,
                    "owner_name": owner_name,
                    "owner_email": owner_email,
                    "target_date": event_day,
                    "status": "Pending",
                    "delay_days": overdue,
                    "created_at": now,
                })
                actions_created += 1

        # ── Escalation at overdue ≥ 5 days ──
        if overdue >= AUTO_ESCALATION_MIN_DAYS:
            level = escalation_level(overdue)
            existing = await get_collection(COLL_ESCALATIONS).find_one({"event_id": event_id})
            if existing:
                await get_collection(COLL_ESCALATIONS).update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"escalated_to": level["to"], "level": level["level"],
                              "last_reminder": today}},
                )
            else:
                await get_collection(COLL_ESCALATIONS).insert_one({
                    "event_id": event_id,
                    "company_id": company_id,
                    "company_name": company_name,
                    "om": om,
                    "activity": activity,
                    "target_date": event_day,
                    "status": "Active",
                    "level": level["level"],
                    "escalated_to": level["to"],
                    "escalation_date": today,
                    "last_reminder": today,
                    "recommended_action": (
                        f"Auto: {activity or 'activity'} overdue {overdue} days — "
                        f"escalate to {level['to']}"
                    ),
                })
                esc_created += 1

    logger.info(
        f"TPMS auto-feed: actions +{actions_created}/closed {actions_closed}, "
        f"escalations +{esc_created}/resolved {esc_resolved}"
    )
    return {"actions_created": actions_created, "actions_closed": actions_closed,
            "escalations_created": esc_created, "escalations_resolved": esc_resolved}
