"""HRMS ▸ 30/90-Day Pulse Survey (BA/Functional Design §22.4, screen SM-HR-058).

See the "Phase PULSE-1" header comment in models/hrms.py for why this is a deliberately
separate, IDENTIFIABLE module rather than an extension of the existing anonymous
hrms_survey_service.py (induction/probation feedback).

-- DOJ-anchored, survives early-closed onboarding tasks (BR-027) ---------------------------
The scheduler job scans every ACTIVE employee's `joined_on` directly, not anything onboarding-
task-shaped — so a plan/checklist/probation record closing early, or never existing at all,
has no effect on when the 30-day and 90-day surveys fire.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PULSE_CONFIG_SAVED, AUDIT_PULSE_FOLLOW_UP, AUDIT_PULSE_ISSUED, AUDIT_PULSE_SUBMITTED,
    COLL_EMPLOYEE_PROFILES, COLL_PULSE_RESPONSES, COLL_SETTINGS,
    DEFAULT_PULSE_LOW_SCORE_THRESHOLD, DEFAULT_PULSE_QUESTIONS, ENTITY_PULSE_RESPONSE,
    HrmsRole, PulseMilestone, PulseResponseStatus,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_access import hrms_role

MILESTONE_DAYS = {PulseMilestone.DAY_30.value: 30, PulseMilestone.DAY_90.value: 90}


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_id(actor: dict) -> str:
    return str((actor or {}).get("_id") or "")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": _actor_id(actor)})
    return (profile or {}).get("employee_code")


# =============================================================
# Config — adjustable default, not frozen policy
# =============================================================
async def get_questions(company_id: str) -> list:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("pulse_questions")
    return stored if stored else list(DEFAULT_PULSE_QUESTIONS)


async def save_questions(actor: dict, company_id: str, questions: list) -> list:
    questions = [q.strip() for q in (questions or []) if q and q.strip()]
    if not questions:
        raise HTTPException(status_code=422, detail="At least one question is required.")
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"pulse_questions": questions, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True)
    await audit(actor, AUDIT_PULSE_CONFIG_SAVED, ENTITY_PULSE_RESPONSE, "config",
               f"{len(questions)} question(s)", company_id)
    return questions


# =============================================================
# Responses
# =============================================================
async def _get_response(company_id: str, employee_code: str, milestone: str) -> Optional[dict]:
    return await get_collection(COLL_PULSE_RESPONSES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "milestone": milestone})


async def get_response(actor: dict, company_id: str, employee_code: str, milestone: str) -> dict:
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if own != employee_code:
            raise HTTPException(status_code=403, detail="You may only view your own survey.")
    doc = await _get_response(company_id, employee_code, milestone)
    if not doc:
        raise HTTPException(status_code=404, detail="No survey found for that milestone.")
    return _out(doc)


async def list_responses(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                         milestone: Optional[str] = None, status: Optional[str] = None,
                         follow_up_only: bool = False, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if milestone:
        query["milestone"] = milestone
    if status:
        query["status"] = status
    if follow_up_only:
        query["follow_up_required"] = True
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        # Overrides any employee_code the caller passed — an EMPLOYEE may only ever see
        # their own rows, the same fails-closed pattern hrms_pip_service establishes.
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    rows = await get_collection(COLL_PULSE_RESPONSES).find(query).sort(
        "issued_at", -1).to_list(min(limit, 500))
    return [_out(r) for r in rows]


async def submit_response(actor: dict, company_id: str, employee_code: str,
                          milestone: str, scores: dict, comment: Optional[str] = None) -> dict:
    """§22.4 step 210 — enforced ownership: only the survey's OWN employee may submit it,
    the same pattern hrms_pip_service.acknowledge_pip already establishes."""
    doc = await _get_response(company_id, employee_code, milestone)
    if not doc:
        raise HTTPException(status_code=404, detail="No survey found for that milestone.")
    own = await _own_employee_code(actor, company_id)
    if own != employee_code:
        raise HTTPException(status_code=403, detail="You may only submit your own survey.")
    if doc["status"] == PulseResponseStatus.SUBMITTED.value:
        raise HTTPException(status_code=409, detail="This survey has already been submitted.")

    questions = await get_questions(company_id)
    clean_scores = {q: float(scores[q]) for q in questions if q in (scores or {})}
    if not clean_scores:
        raise HTTPException(status_code=422, detail="At least one question must be answered.")
    average = sum(clean_scores.values()) / len(clean_scores)
    follow_up = average <= DEFAULT_PULSE_LOW_SCORE_THRESHOLD

    now = datetime.now(timezone.utc)
    await get_collection(COLL_PULSE_RESPONSES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": PulseResponseStatus.SUBMITTED.value, "submitted_at": now,
                  "scores": clean_scores, "average": round(average, 2), "comment": comment,
                  "follow_up_required": follow_up}})
    await audit(actor, AUDIT_PULSE_SUBMITTED, ENTITY_PULSE_RESPONSE,
               f"{employee_code}:{milestone}", f"average {round(average, 2)}", company_id)

    if follow_up:
        await _notify_follow_up(company_id, employee_code, milestone, average)

    return await get_response(actor, company_id, employee_code, milestone)


async def _notify_follow_up(company_id: str, employee_code: str, milestone: str, average: float) -> None:
    """§22.4 step 212 — one HR notification per response, guarded by `follow_up_notified`
    on the record so a retried write never sends it twice."""
    from app.services.hrms_notify_service import notify_hrms_role

    row = await get_collection(COLL_PULSE_RESPONSES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "milestone": milestone})
    if not row or row.get("follow_up_notified"):
        return
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code}, {"display_name": 1})
    name = (profile or {}).get("display_name") or employee_code
    await notify_hrms_role(
        company_id, ["HR"], f"Pulse survey follow-up: {name}",
        f'{name} ({employee_code}) scored {average:.1f}/5 on their {milestone}-day pulse '
        f'survey — at or below the follow-up threshold. A conversation is recommended.',
        kind="warning", link="/hrms/pulse-surveys", email=True)
    await get_collection(COLL_PULSE_RESPONSES).update_one(
        {"_id": row["_id"]}, {"$set": {"follow_up_notified": True}})
    await audit(None, AUDIT_PULSE_FOLLOW_UP, ENTITY_PULSE_RESPONSE,
               f"{employee_code}:{milestone}", f"average {average:.1f}", company_id)


# =============================================================
# HR summary (§22.4 step 213 — completion rate / average score)
# =============================================================
async def get_summary(company_id: str) -> dict:
    rows = await get_collection(COLL_PULSE_RESPONSES).find(
        {"company_id": str(company_id)}).to_list(5000)
    out = {}
    for milestone in (PulseMilestone.DAY_30.value, PulseMilestone.DAY_90.value):
        subset = [r for r in rows if r["milestone"] == milestone]
        submitted = [r for r in subset if r["status"] == PulseResponseStatus.SUBMITTED.value]
        averages = [r["average"] for r in submitted if r.get("average") is not None]
        out[milestone] = {
            "issued": len(subset),
            "submitted": len(submitted),
            "completion_rate": round(len(submitted) / len(subset), 2) if subset else None,
            "average_score": round(sum(averages) / len(averages), 2) if averages else None,
            "follow_ups_open": sum(1 for r in subset if r.get("follow_up_required")),
        }
    return out


# =============================================================
# Scheduler job (§22.4 steps 208-209) — driven by hrms_scheduler_service.run_due_jobs
# =============================================================
async def run_issue_sweep(company_id: str) -> dict:
    """Issue a pulse survey for every ACTIVE employee who has just reached a milestone.

    DOJ-anchored: reads `joined_on` off the employee profile directly, nothing derived from
    another module's task state (BR-027). Idempotent via the unique index on
    (company_id, employee_code, milestone) — a retried run's insert simply fails and is
    swallowed, never a duplicate issuance.
    """
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "employment_status": "Active"},
        {"employee_code": 1, "joined_on": 1, "display_name": 1}).to_list(5000)
    if not profiles:
        return {"checked": 0, "issued": 0}

    today = datetime.now(timezone.utc).date()
    issued = 0
    for profile in profiles:
        try:
            joined = date.fromisoformat(str(profile.get("joined_on"))[:10])
        except (ValueError, TypeError):
            continue
        elapsed = (today - joined).days
        for milestone, threshold_days in MILESTONE_DAYS.items():
            if elapsed < threshold_days:
                continue
            existing = await _get_response(company_id, profile["employee_code"], milestone)
            if existing:
                continue
            await _issue_one(company_id, profile["employee_code"],
                             profile.get("display_name"), milestone)
            issued += 1

    return {"checked": len(profiles), "issued": issued}


async def _issue_one(company_id: str, employee_code: str, employee_name: Optional[str],
                     milestone: str) -> None:
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code,
        "employee_name": employee_name, "milestone": milestone,
        "status": PulseResponseStatus.ISSUED.value,
        "issued_at": now, "submitted_at": None,
        "scores": {}, "average": None, "comment": None,
        "follow_up_required": False, "follow_up_notified": False,
        "created_at": now, "updated_at": now,
    }
    try:
        await get_collection(COLL_PULSE_RESPONSES).insert_one(doc)
    except Exception as e:
        # Unique index race — another run's insert already landed. Harmless to skip.
        print(f"[WARN] HRMS pulse survey issue skipped for {employee_code}/{milestone}: {e}")
        return

    await audit(None, AUDIT_PULSE_ISSUED, ENTITY_PULSE_RESPONSE,
               f"{employee_code}:{milestone}", employee_name, company_id)
    try:
        profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"company_id": str(company_id), "employee_code": employee_code}, {"user_id": 1})
        if profile and profile.get("user_id"):
            from app.services.hrms_notify_service import notify_user
            await notify_user(
                profile["user_id"], f"Your {milestone}-day check-in is ready",
                "A short pulse survey about your first weeks is ready — your honest "
                "feedback helps us support you better.",
                kind="info", link="/hrms/pulse-surveys", email=True)
    except Exception as e:
        print(f"[WARN] HRMS pulse survey notification failed for {employee_code}: {e}")
