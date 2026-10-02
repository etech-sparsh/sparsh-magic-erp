"""Leadership Score — the reminder ladder and the notices around a cycle.

Every job here is driven by the ASSIGNMENT row's status, never by a response. That is not
an implementation detail: it is what lets reminders exist at all without breaking
anonymity. `status == submitted` says a giver is done; nothing here can reach the answers
they gave, because a response carries no rater identity to join on.

The ladder the plan calls for:

    day 3 · day 7 · the day before close      → non-submitters, over WhatsApp
    window closing today                      → HR
    quorum not met at close                   → HR, so the window can be extended
    score published                           → the leader and their reporting manager
    RRO discussion still pending after 7 days → the reporting manager, cc HR

Jobs hook into `reminder_scheduler`'s existing 60-second tick and gate themselves on the
clock, exactly like the TPMS daily jobs, so nothing new has to be scheduled or supervised.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS, COLL_LS_CYCLES, COLL_LS_DISCUSSIONS, COLL_LS_SUBJECTS,
    CYCLE_CLOSED, CYCLE_OPEN, CYCLE_PUBLISHED, LINK_SUBMITTED,
    cycle_label,
)

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Days after a cycle opens on which a non-submitter is chased, plus the day before close.
REMINDER_DAYS = (3, 7)

# How long a reporting manager has to log the RRO conversation before they are nudged.
RRO_GRACE_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt) -> Optional[datetime]:
    if not dt:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days_since(dt) -> Optional[int]:
    dt = _aware(dt)
    return None if not dt else (_now() - dt).days


async def _send(user_id: str, phone: str, text: str, slug: str) -> None:
    """Send one WhatsApp message. Leadership has no other channel.

    A feedback invitation or chase names the leader being rated. An inbox is shared,
    forwarded and auto-archived in ways a phone is not, so the module that promises "ye
    feedback completely confidential hoga" does not put that name in one.

    Best-effort and never raises. A chase that fails is a chase that fails — it must not
    take down the tick that also closes windows and freezes scores.
    """
    from app.services.notification_service import send_whatsapp_notification
    if not phone:
        # Said out loud rather than returning in silence: with email gone, no number on
        # file means this person is now genuinely unreachable, which is a data problem
        # somebody has to fix on their user record.
        logger.info("Leadership %s not sent: no mobile number for user %s", slug, user_id)
        return
    try:
        await send_whatsapp_notification(phone, text, user_id=user_id, slug=slug)
    except Exception as e:                                       # pragma: no cover
        logger.warning("Leadership %s WhatsApp to %s failed: %s", slug, phone, e)


# ─────────────────────────────────────────────────────────────
# The reminder ladder
# ─────────────────────────────────────────────────────────────
async def chase_non_submitters() -> dict:
    """Remind everyone who still owes a form, on day 3, day 7 and the day before close.

    Reads `status` on the invitation. A submitted invitation is never chased, and no job
    here ever touches a response — which is the whole reason reminders are safe to send.
    """
    sent = 0
    cycles = await get_collection(COLL_LS_CYCLES).find({"status": CYCLE_OPEN}).to_list(200)

    for cyc in cycles:
        opened = _aware(cyc.get("opens_at")) or _aware(cyc.get("updated_at"))
        closes = _aware(cyc.get("closes_at"))
        age = _days_since(opened)
        days_left = (closes - _now()).days if closes else None

        due = (age in REMINDER_DAYS) or (days_left == 1)
        if not due:
            continue

        stage = f"day{age}" if age in REMINDER_DAYS else "final"
        rows = await get_collection(COLL_LS_ASSIGNMENTS).find({
            "company_id": str(cyc.get("company_id")),
            "cycle": cyc.get("cycle"),
            "status": {"$ne": LINK_SUBMITTED},
        }).to_list(2000)

        for row in rows:
            # One reminder per stage per invitation — a scheduler that ticks every 60
            # seconds would otherwise mail the same person all day.
            if stage in (row.get("reminded_stages") or []):
                continue

            label = cycle_label(cyc.get("cycle") or "")
            text = (f"Reminder: your confidential leadership feedback for "
                    f"{row.get('subject_name') or 'a colleague'} ({label}) is still "
                    f"pending. Your invitation message has the link.")

            # Rows minted before `giver_phone` existed carry no number, so fall back to
            # the roster. Without this the WhatsApp half of the ladder is silently dead
            # for every panel already in flight.
            phone = row.get("giver_phone")
            if phone is None:
                person = await _person(row.get("giver_id"), cyc.get("company_id"))
                phone = (person or {}).get("mobile") or ""

            await _send(row.get("giver_id"), phone, text, "tpms_leadership_reminder")
            await get_collection(COLL_LS_ASSIGNMENTS).update_one(
                {"_id": row["_id"]},
                {"$addToSet": {"reminded_stages": stage},
                 "$push": {"reminded_at": _now()},
                 "$set": {"updated_at": _now()}})
            sent += 1

    if sent:
        logger.info("Leadership reminders sent: %d", sent)
    return {"reminded": sent}


async def notify_window_closing() -> dict:
    """Tell HR on the day a window closes, while they can still act on it."""
    notified = 0
    for cyc in await get_collection(COLL_LS_CYCLES).find({"status": CYCLE_OPEN}).to_list(200):
        closes = _aware(cyc.get("closes_at"))
        if not closes or (closes - _now()).days != 0:
            continue
        if cyc.get("closing_notice_sent"):
            continue
        label = cycle_label(cyc.get("cycle") or "")
        await _notify_hr(
            cyc.get("company_id"),
            f"Leadership Score {label} closes today. Check the quorum report.",
            "tpms_leadership_closing")
        await get_collection(COLL_LS_CYCLES).update_one(
            {"_id": cyc["_id"]}, {"$set": {"closing_notice_sent": True}})
        notified += 1
    return {"notified": notified}


async def notify_quorum_shortfall() -> dict:
    """Tell HR which leaders are short of quorum on a closed cycle.

    Names leaders and counts only — never which raters replied.
    """
    from app.services.leadership_service import quorum_report

    notified = 0
    for cyc in await get_collection(COLL_LS_CYCLES).find({"status": CYCLE_CLOSED}).to_list(200):
        if cyc.get("quorum_notice_sent"):
            continue
        report = await quorum_report(cyc.get("company_id"), cyc.get("cycle"))
        if report["all_met"]:
            continue
        label = cycle_label(cyc.get("cycle") or "")
        await _notify_hr(
            cyc.get("company_id"),
            f"Leadership Score {label}: {len(report['below_quorum'])} leader(s) below quorum.",
            "tpms_leadership_quorum")
        await get_collection(COLL_LS_CYCLES).update_one(
            {"_id": cyc["_id"]}, {"$set": {"quorum_notice_sent": True}})
        notified += 1
    return {"notified": notified}


async def notify_published(company_id: str, cycle: str) -> dict:
    """Tell each leader and their reporting manager that a score is available."""
    subjects = await get_collection(COLL_LS_SUBJECTS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(500)
    label = cycle_label(cycle)
    sent = 0

    for s in subjects:
        for uid, who in ((s.get("subject_id"), "leader"),
                         (s.get("reporting_manager"), "manager")):
            person = await _person(uid, company_id)
            if not person:
                continue
            if who == "leader":
                title = f"Your Leadership Score for {label} is ready"
            else:
                title = f"Leadership Scores for {label} are ready"
            await _send(str(uid), person.get("mobile"), title,
                        "tpms_leadership_published")
            sent += 1
    logger.info("Leadership publish notices sent: %d [%s/%s]", sent, company_id, cycle)
    return {"notified": sent}


async def chase_rro_discussions() -> dict:
    """Nudge managers whose RRO conversation is still unlogged a week after publication."""
    nudged = 0
    for cyc in await get_collection(COLL_LS_CYCLES).find(
            {"status": CYCLE_PUBLISHED}).to_list(200):
        age = _days_since(cyc.get("published_at"))
        if age is None or age < RRO_GRACE_DAYS or cyc.get("rro_notice_sent"):
            continue

        company_id, cycle = str(cyc.get("company_id")), cyc.get("cycle")
        logged = {str(d.get("subject_id")) for d in
                  await get_collection(COLL_LS_DISCUSSIONS).find(
                      {"company_id": company_id, "cycle": cycle}).to_list(500)}
        pending = [s for s in await get_collection(COLL_LS_SUBJECTS).find(
            {"company_id": company_id, "cycle": cycle}).to_list(500)
            if str(s.get("subject_id")) not in logged]

        by_manager: dict = {}
        for s in pending:
            by_manager.setdefault(str(s.get("reporting_manager") or ""), []).append(s)

        label = cycle_label(cycle or "")
        for manager_id, rows in by_manager.items():
            person = await _person(manager_id, company_id)
            if not person:
                continue
            await _send(manager_id, person.get("mobile"),
                        f"RRO discussion pending for {len(rows)} leader(s) — {label}.",
                        "tpms_leadership_rro_pending")
            nudged += 1

        if pending:
            await _notify_hr(company_id,
                             f"{len(pending)} RRO discussion(s) pending for {label}.",
                             "tpms_leadership_rro_pending")
        await get_collection(COLL_LS_CYCLES).update_one(
            {"_id": cyc["_id"]}, {"$set": {"rro_notice_sent": True}})
    return {"nudged": nudged}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
async def _person(user_id, company_id) -> Optional[dict]:
    from bson import ObjectId
    if not user_id:
        return None
    try:
        oid = ObjectId(str(user_id))
    except Exception:
        return None
    for coll in ("staff", "learners"):
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc and str(doc.get("company_id") or "") == str(company_id):
            return doc
    return None


async def _notify_hr(company_id, text: str, slug: str) -> None:
    """Reach the company's HR users — the people the document puts in charge of a cycle."""
    rows = await get_collection("learners").find({
        "company_id": str(company_id), "is_active": {"$ne": False},
    }).to_list(500)
    hr = [u for u in rows
          if str(u.get("governance_role") or u.get("department") or "").strip().lower() == "hr"]
    for u in hr:
        await _send(str(u.get("_id")), u.get("mobile"), text, slug)


async def run_leadership_jobs() -> dict:
    """Every Leadership job for one tick. Never raises — the scheduler must keep ticking."""
    out = {}
    # Statuses first. Every job below queries Mongo by status, so a cycle that opened or
    # closed since the last tick has to be reconciled before they run or it is skipped for
    # a whole day — on the one day it mattered most.
    from app.services.leadership_service import sync_all_cycle_statuses
    try:
        out["status_sweep"] = await sync_all_cycle_statuses()
    except Exception as e:                                        # pragma: no cover
        # Every job below selects cycles BY STATUS. Running them on statuses the sweep
        # failed to reconcile is worse than not running them: they would chase people in a
        # cycle that has closed, or stay silent on one that opened, and leave a run that
        # looks successful. Skipped loudly instead, and picked up on the next tick.
        logger.error(
            "Leadership status sweep FAILED (%s) — skipping the reminder, closing, quorum "
            "and RRO jobs this run rather than acting on stale cycle statuses.", e)
        out["status_sweep"] = {"error": str(e)}
        for skipped in ("reminders", "closing", "quorum", "rro"):
            out[skipped] = {"skipped": "cycle statuses could not be reconciled"}
        return out

    for name, fn in (("reminders", chase_non_submitters),
                     ("closing", notify_window_closing),
                     ("quorum", notify_quorum_shortfall),
                     ("rro", chase_rro_discussions)):
        try:
            out[name] = await fn()
        except Exception as e:                                    # pragma: no cover
            logger.error("Leadership job %s failed: %s", name, e)
            out[name] = {"error": str(e)}
    return out
