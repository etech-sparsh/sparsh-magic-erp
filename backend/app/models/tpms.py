"""
TPMS ▸ core domain models + collection registry.

Ported 1:1 from the Apps Script implementation (`copy_of calender/code.js`, 4207 lines).
Where a constant here looks arbitrary, it mirrors the sheet/script exactly — the source
line is cited so behaviour can be diffed against the original.

The *forms* sub-module (rating matrices + Yes/No checklist) lives in `app.models.forms`
and is unchanged by this file. This module covers everything else: the activity
catalogue, scheduling lifecycle, reminders, escalations, action items, uploads and the
Success-Measure engine's storage.

Scheduled TPMS activities are NOT stored here — they are calendar events carrying
`kind == TPMS_EVENT_KIND` (see app/models/calendar_event.py), so they reuse the ERP's
recurrence engine, reminder scheduler and calendar UI.
"""
import re
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections
# ─────────────────────────────────────────────────────────────
COLL_ACTIVITIES          = "tpms_activities"
COLL_REMINDER_RULES      = "tpms_reminder_rules"
COLL_RESCHEDULE_REQUESTS = "tpms_reschedule_requests"
COLL_TASK_UPLOADS        = "tpms_task_uploads"
COLL_ACTIVITY_TRACKER    = "tpms_activity_tracker"
COLL_ESCALATIONS         = "tpms_escalations"
COLL_ACTION_ITEMS        = "tpms_action_items"
COLL_SUCCESS_MEASURES    = "tpms_success_measures"
COLL_MAIL_TEMPLATES      = "tpms_mail_templates"
COLL_MIGRATION_MAP       = "tpms_migration_map"   # sheet id → Mongo _id, for re-runnable migration
COLL_DEPARTMENTS         = "tpms_departments"     # H5 — department master (governance roles + custom)
COLL_REMINDER_LOGS       = "tpms_reminder_logs"   # H10 — per-reminder send ledger
COLL_WHATSAPP_TEMPLATES  = "tpms_whatsapp_templates"  # H1 — Meta WhatsApp template config
COLL_META_TEMPLATES      = "tpms_meta_whatsapp_templates"  # H1b — templates authored in TPMS
                                                           #       and submitted to Meta for approval
# Delivery-idempotency ledger: one row per (event, escalation stage, recipient) that has
# been mailed. The ladder claims a row BEFORE sending, so however many times it runs — a
# restart mid-run, two overlapping runs — each person is mailed once per stage. Purely
# additive: it is written only by new code and never rewrites an event or a notification.
COLL_ESCALATION_SENDS    = "tpms_escalation_sends"
# Durable "this daily job already ran" claim. The scheduler previously held this in memory,
# so any container restart replayed the whole day's escalation ladder from scratch.
COLL_JOB_RUNS            = "tpms_job_runs"

# Discriminator marking a calendar event as a TPMS activity.
TPMS_EVENT_KIND = "tpms_activity"


# ─────────────────────────────────────────────────────────────
# Enumerations (string constants — values match the sheet verbatim)
# ─────────────────────────────────────────────────────────────
STATUS_SCHEDULED   = "Scheduled"
STATUS_RESCHEDULED = "Rescheduled"
STATUS_CANCELLED   = "Cancelled"
STATUS_COMPLETED   = "Completed"
STATUS_LAPSED      = "Lapsed"
SCHEDULE_STATUSES = [STATUS_SCHEDULED, STATUS_RESCHEDULED, STATUS_CANCELLED,
                     STATUS_COMPLETED, STATUS_LAPSED]

# Statuses the escalation ladder and the auto-feed treat as "closed".
CLOSED_STATUSES = {STATUS_COMPLETED, STATUS_CANCELLED}

# The ERP calendar's own `status` vocabulary is lowercase and has no "Lapsed". TPMS keeps
# its five statuses in `tpms_status` and mirrors the closest ERP value into `status`, so the
# existing Calendar page keeps rendering TPMS events correctly and nothing downstream breaks.
TPMS_TO_ERP_STATUS = {
    STATUS_SCHEDULED:   "schedule",
    STATUS_RESCHEDULED: "reschedule",
    STATUS_CANCELLED:   "canceled",
    STATUS_COMPLETED:   "completed",
    STATUS_LAPSED:      "schedule",   # no ERP equivalent — stays visible as scheduled
}


def erp_status_for(tpms_status: str) -> str:
    return TPMS_TO_ERP_STATUS.get(tpms_status, "schedule")


SCOPE_COMPANY = "company"
SCOPE_HOD     = "hod"

SCORE_MODE_MANUAL = "manual"   # OM types the number in (Success_Manual)
SCORE_MODE_FORM   = "form"     # derived from TPMS form submissions
SCORE_MODE_AUTO   = "auto"     # completed ÷ total

CHANNEL_EMAIL    = "Email"
CHANNEL_WHATSAPP = "WhatsApp"
CHANNEL_BOTH     = "Both"

RECURRENCE_ONE_TIME     = "One-time"
RECURRENCE_DAILY        = "Daily"
RECURRENCE_MONTHLY      = "Monthly"
RECURRENCE_WEEKLY       = "Weekly"
RECURRENCE_PERIODICALLY = "Periodically"
# "Daily" is now implemented (one occurrence per day from plan_start..plan_end). The Apps
# Script offered it in the filter UI but buildOccurrences_ never implemented it (code.js:1304);
# the ERP closes that gap.
RECURRENCES = [RECURRENCE_ONE_TIME, RECURRENCE_DAILY, RECURRENCE_MONTHLY, RECURRENCE_WEEKLY, RECURRENCE_PERIODICALLY]

REQUEST_PENDING  = "Pending"
REQUEST_APPROVED = "Approved"
REQUEST_REJECTED = "Rejected"

# Client-side departments the doers are grouped by. Matches the `Department` sheet and
# the hardcoded list in frontend ScheduleCalendarModal.jsx. Retained as the built-in
# fallback; the authoritative list now lives in the tpms_departments master (H5).
#
# FINANCE was added for the HRMS internal recruitment track, where Management/Finance is the
# mandatory budget approver (Internal Recruitment SOP, Annexure B). It is a governance role
# like the other four: a user carries it in `governance_role`, auth_controller.CLIENT_RANK
# ranks it with HR, and hrms_access maps it to HrmsRole.FINANCE. TPMS itself does not treat
# it specially — it is simply another governance department to the escalation logic.
TPMS_DEPARTMENTS = ["HOD", "MD", "HR", "FINANCE", "CLIENT", "IMPLEMENTOR"]

# H5 — department master seed. The governance roles are flagged `is_governance_role` so
# escalation/form logic can tell them apart from custom client departments (Sales, Ops…),
# which admins add via the API. Seed is insert-only; company_id=None means global/default.
DEPARTMENT_SEED = [
    {"name": d, "code": d.lower(), "is_governance_role": True, "company_id": None, "active": True}
    for d in TPMS_DEPARTMENTS
]


# ─────────────────────────────────────────────────────────────
# Tunables — every value mirrors the Apps Script
# ─────────────────────────────────────────────────────────────
# Engine B — syncAutoFeed (code.js:2711-2712), daily ~06:00
AUTO_ACTION_MIN_DAYS      = 1    # overdue ≥1d → open an Action_Item
AUTO_ESCALATION_MIN_DAYS  = 5    # overdue ≥5d → open an Escalation

# Engine B — escLevel_ (code.js:2855)
ESCALATION_LEVELS = [(10, 3, "MD"), (7, 2, "HR"), (5, 1, "HOD")]  # (min_days, level, escalate_to)

# Engine A — runEscalationLadder (code.js:3755), daily ~07:00
LADDER_PENDING_DAYS  = 1   # → [Pending Action] mail, Esc_Stage 1
LADDER_CRITICAL_DAYS = 2   # → [CRITICAL] mail, Esc_Stage 2
LADDER_LAPSE_DAYS    = 3   # → Status = Lapsed, Esc_Stage 3

RESCHEDULE_MIN_HOURS = 12          # requestReschedule (code.js:3834)
UPLOAD_MAX_BYTES     = 25 * 1024 * 1024
DEFAULT_REMIND_TIME  = "09:00"     # CFG.DEFAULT_REMIND_TIME
REVIEW_MAX_RATING    = 5           # REVIEW_MAX_RATING (code.js:2016)

# ─── TPMS notification master switch ───────────────────────────────────────────
# When False, the TPMS module sends NO email or WhatsApp notifications of any kind —
# schedule / reschedule / cancel / completion mails, the "marked done → please confirm"
# nudge, the escalation-ladder mails, AND the TPMS activity reminders fired by the shared
# reminder scheduler are all suppressed. TPMS state changes (status, esc_stage, Lapsed,
# tracker, scores) are UNAFFECTED — only the outbound messages are silenced.
# This flag is TPMS-only: every other module's email/WhatsApp/reminder behaviour is
# untouched because those paths never consult it. Flip to False to silence TPMS messaging.
#
# ENABLED. Two things make this safe to leave on:
#   • Reminders older than TPMS_REMINDER_MAX_AGE_HOURS (reminder_scheduler) are consumed
#     without sending, so the backlog that accumulated while this was off cannot flood out.
#   • Each template carries its own Active switch (tpms_mail_templates /
#     tpms_whatsapp_templates), checked at send time — individual notifications can be
#     silenced from the admin UI without touching this master switch.
TPMS_NOTIFICATIONS_ENABLED = True

# Calendar Discipline is a pseudo-activity: its score is the completion rate across all
# OTHER activities that month, excluding itself and Action Closure Review (code.js:1924).
CAL_DISCIPLINE_ACTIVITY = "Calendar Discipline"
CAL_DISCIPLINE_EXCLUDE  = "Action Closure Review"

# Offset units → seconds (writeReminders_ UNIT map, code.js:1209)
OFFSET_UNIT_SECONDS = {"MINS": 60, "HRS": 3600, "DAYS": 86400}


def escalation_level(days_overdue: int) -> Dict:
    """Port of escLevel_ (code.js:2855). Returns {level, to}; level 0 = not escalated."""
    for min_days, level, to in ESCALATION_LEVELS:
        if days_overdue >= min_days:
            return {"level": level, "to": to}
    return {"level": 0, "to": ""}


# ─────────────────────────────────────────────────────────────
# Success-measure achievement band (spec §7)
#     ≥100% → Met · 50–99% → Partial · <50% → Not Met
# Anything below half of target is NOT a partial success — it reads as Not Met. Defined
# once here because the band is applied on three surfaces (client dashboard, implementation
# tracker cards, per-activity scorecard) and they must never disagree.
# ─────────────────────────────────────────────────────────────
ACHIEVEMENT_MET_MIN = 100
ACHIEVEMENT_PARTIAL_MIN = 50

STATUS_MET = "Met"
STATUS_PARTIAL = "Partial"
STATUS_NOT_MET = "Not Met"


# ─────────────────────────────────────────────────────────────
# Governance-role detection (spec §2 / §3)
#
# The source matched a free-text `Role` column against
#     /\bmd\b|managing director|client|owner|founder|ceo/i
# to decide who oversees a whole company. The ERP prefers the controlled
# `governance_role` (HOD/MD/HR), falling back to `department` for un-migrated users — and
# keeps the source's synonyms so a user still carrying "Owner"/"CEO"/"Founder" is read as
# MD rather than silently losing company-wide visibility.
#
# Defined once here because MD detection gates three separate surfaces (calendar scope,
# review-report self-lock, HOD-dashboard self-lock) that must agree.
# ─────────────────────────────────────────────────────────────
_MD_ROLE_PATTERN = re.compile(r"\bmd\b|managing director|client|owner|founder|ceo", re.I)


def governance_role_of(user: dict) -> str:
    """The user's governance role, lower-cased. Prefers the controlled field."""
    return (user.get("governance_role") or user.get("department") or "").strip().lower()


def is_md_like(user: dict) -> bool:
    """Does this user oversee their entire company? (spec §3 "Learner (MD)")"""
    return bool(_MD_ROLE_PATTERN.search(governance_role_of(user)))


def is_hod_like(user: dict) -> bool:
    return governance_role_of(user) == "hod"


def achievement_status(achievement, has_data: bool = True) -> str:
    """Band an Achievement_% figure. No data / no score reads as Not Met, matching the
    source (a blank actual scores 0, which falls below the partial floor anyway)."""
    if not has_data or achievement is None:
        return STATUS_NOT_MET
    try:
        value = float(achievement)
    except (TypeError, ValueError):
        return STATUS_NOT_MET
    if value >= ACHIEVEMENT_MET_MIN:
        return STATUS_MET
    if value >= ACHIEVEMENT_PARTIAL_MIN:
        return STATUS_PARTIAL
    return STATUS_NOT_MET


# ─────────────────────────────────────────────────────────────
# Period helpers — canonical "YYYY-MM"
#
# The sheet stores months three different ways ("jul26", "July26", a real Date) and the
# Apps Script normalises them with succMonthNorm_ (code.js:1903). We store the canonical
# ISO form and generate the legacy tokens when reading migrated data.
# ─────────────────────────────────────────────────────────────
_MON_SHORT = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]
_MON_FULL = ["january", "february", "march", "april", "may", "june",
             "july", "august", "september", "october", "november", "december"]


def period_parts(period: str):
    """Canonical 'YYYY-MM' OR a legacy token ('jul26', 'july26', 'jul-26') → (year, month).
    Form submissions store the token spelling the client sends, so this must parse both."""
    s = str(period or "").strip()
    # Canonical ISO 'YYYY-MM'
    if len(s) >= 7 and s[4] == "-" and s[:4].isdigit():
        year, month = int(s[:4]), int(s[5:7])
        if not 1 <= month <= 12:
            raise ValueError(f"invalid month in period {period!r}")
        return year, month
    # Legacy token: <month-name><yy> with an optional '-' (e.g. 'jul26', 'july26', 'jul-26').
    t = s.lower().replace("-", "")
    for i in range(12):
        full, short = _MON_FULL[i], _MON_SHORT[i]
        if t.startswith(full):
            yy = t[len(full):]
        elif t.startswith(short):
            yy = t[len(short):]
        else:
            continue
        if len(yy) == 2 and yy.isdigit():
            return 2000 + int(yy), i + 1
        break
    raise ValueError(f"unrecognised period {period!r}")


def period_tokens(period: str) -> List[str]:
    """Every spelling of a period that may appear in migrated rows, for `$in` queries.
    '2026-07' → ['2026-07', 'jul26', 'july26', 'jul-26']"""
    year, month = period_parts(period)
    yy = str(year)[-2:]
    short, full = _MON_SHORT[month - 1], _MON_FULL[month - 1]
    return list({period, f"{short}{yy}", f"{full}{yy}", f"{short}-{yy}"})


def period_from_date(value) -> str:
    """A date (or ISO string) → canonical 'YYYY-MM'. Port of midFromDate_ (code.js:1133),
    except it yields the ISO form rather than 'jul26'."""
    if isinstance(value, datetime):
        return f"{value.year:04d}-{value.month:02d}"
    s = str(value or "").strip()
    if not s:
        return ""
    return s[:7] if len(s) >= 7 and s[4] == "-" else ""


def period_display(period: str) -> str:
    """'2026-07' or 'jul26' → 'July26' (succMonthDisplay_, code.js:1914). Never raises —
    an unrecognised period is echoed back so a report can't crash on odd stored data."""
    try:
        year, month = period_parts(period)
    except (ValueError, TypeError):
        return str(period or "")
    return _MON_FULL[month - 1].capitalize() + str(year)[-2:]


# ─────────────────────────────────────────────────────────────
# Activity catalogue — the 14 rows of the `Activity` sheet.
# Seed data; `tpms_activities` is the runtime source of truth once migrated.
# ─────────────────────────────────────────────────────────────
class Activity(BaseModel):
    name: str
    short: str
    frequency: str                       # verbatim sheet text — drives the conflict rule
    scope: str = SCOPE_COMPANY           # company | hod  (sheet: "Responsive")
    upload_required: bool = False
    score_mode: str = SCORE_MODE_AUTO    # manual | form | auto
    doc_link: Optional[str] = None
    active: bool = True


ACTIVITY_SEED: List[dict] = [
    {"name": "Org Structure Update",               "short": "Org Str",        "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "DRM & KPI data available",           "short": "DRM/KPI",        "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Calendar Discipline",                "short": "Cal Disc",       "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_AUTO},
    {"name": "WRM",                                "short": "WRM",            "frequency": "3-4 in month",    "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_MANUAL},
    {"name": "Monthly Management Review (MMR)",    "short": "MMR",            "frequency": "once",            "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "One pager Memo",                     "short": "1-Pager",        "frequency": "multiple times",  "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Action Closure Review",              "short": "Action Closure", "frequency": "multiple times",  "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Accountability & Ownership Rating",  "short": "A&O Rtg",        "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "Culture Rating",                     "short": "Cult Rtg",       "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "RRO",                                "short": "RRO",            "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_MANUAL},
    {"name": "Implementation Update Feedback",     "short": "Imp Stats",      "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "Team Engagement Index",              "short": "TEI",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Customer Satisfaction Index",        "short": "CSI",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Organization Result Matrix",         "short": "ORM",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
]


def is_once_per_month(frequency: str) -> bool:
    """Port of the conflict gate in checkScheduleConflict (code.js:758-760).
    Only "once"-type activities are duplicate-checked; "3-4 in month" and
    "multiple times" are exempt."""
    f = (frequency or "").strip().lower()
    is_once = "once" in f or f.startswith("1 ") or f == "1"
    is_multi = "multiple" in f or bool(__import__("re").search(r"\d\s*-\s*\d", f))
    return is_once and not is_multi


# ─────────────────────────────────────────────────────────────
# Reminder rules — defaults applied to every schedule on save
# (autoRemindersFromRules_, code.js:3690; seeds from ensureReminderRulesSheet_:3673)
# ─────────────────────────────────────────────────────────────
class ReminderRule(BaseModel):
    activity: str = "*"                  # "*" = applies to every activity
    stage: str
    offset_value: int
    offset_unit: str = "DAYS"            # MINS | HRS | DAYS
    offset_dir: str = "before"           # before | after
    channel: str = CHANNEL_EMAIL
    active: bool = True


REMINDER_RULE_SEED: List[dict] = [
    {"activity": "*", "stage": "Initiate (Day-2)",     "offset_value": 2, "offset_unit": "DAYS", "offset_dir": "before", "channel": CHANNEL_EMAIL, "active": True},
    {"activity": "*", "stage": "Pre-Reminder (Day-1)", "offset_value": 1, "offset_unit": "DAYS", "offset_dir": "before", "channel": CHANNEL_EMAIL, "active": True},
    {"activity": "*", "stage": "Same-day 2h before",   "offset_value": 2, "offset_unit": "HRS",  "offset_dir": "before", "channel": CHANNEL_BOTH,  "active": True},
]


# ─────────────────────────────────────────────────────────────
# Lifecycle documents
# ─────────────────────────────────────────────────────────────
class RescheduleRequest(BaseModel):
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    title: Optional[str] = None
    old_date: Optional[str] = None
    old_time: Optional[str] = None
    new_date: str
    new_time: Optional[str] = None
    reason: Optional[str] = ""
    requested_by: str
    requested_by_name: Optional[str] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = REQUEST_PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = ""


class TaskUpload(BaseModel):
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    scope: Optional[str] = None          # company | hod, from the activity catalogue
    period: Optional[str] = None         # YYYY-MM
    member_id: Optional[str] = None
    member_name: Optional[str] = None
    file_name: str
    s3_key: str
    file_url: Optional[str] = None
    uploaded_by: str
    uploaded_by_name: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class ActivityTrackerRow(BaseModel):
    """One row per (company, member, activity, occurrence). Feeds the Success-Measure
    engine and the Employee Activity dashboard. Port of writeTrackerRows_ (code.js:884)."""
    company_id: str
    member_id: Optional[str] = None
    member_name: Optional[str] = None
    period: str                          # YYYY-MM
    date: str                            # YYYY-MM-DD
    activity: str
    status: str = STATUS_SCHEDULED
    event_id: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Escalation(BaseModel):
    """Written by Engine B (syncAutoFeed). One row per event, idempotent."""
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    om: Optional[str] = None
    activity: Optional[str] = None
    target_date: Optional[str] = None
    actual_date: Optional[str] = None
    status: str = "Active"               # Active | Resolved
    level: int = 0
    escalated_to: Optional[str] = None   # HOD | HR | MD
    escalation_date: Optional[str] = None
    last_reminder: Optional[str] = None
    resolution_date: Optional[str] = None
    resolution_method: Optional[str] = None
    resolved_by: Optional[str] = None
    recommended_action: Optional[str] = None


class ActionItem(BaseModel):
    """Written by Engine B at overdue ≥1 day; closed when the activity completes.
    The delay split (learner vs staff) comes from the two-step completion."""
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    action: Optional[str] = None         # "Follow up: <Activity>"
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    target_date: Optional[str] = None
    status: str = "Pending"              # Pending | Closed
    delay_days: int = 0
    learner_delay_days: Optional[int] = None
    staff_delay_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SuccessMeasure(BaseModel):
    """One row per (company, activity, period). Merges the sheet's Success_Measures and
    Success_Manual: `scope`/`hod_id` are set only for per-HOD manual entries."""
    company_id: str
    activity: str
    period: str                          # YYYY-MM
    impl_target: Optional[int] = 100
    impl_actual: Optional[int] = None    # binary 100/0 — mirrors the Apps Script
    score_target: Optional[int] = 100
    score_actual: Optional[int] = None
    achievement: Optional[int] = None
    scope: str = SCOPE_COMPANY
    hod_id: Optional[str] = None
    hod_name: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MailTemplate(BaseModel):
    """Per activity × side × event body. Merges the sheet's `Templates` (11 columns per
    activity) and `HOD_Form_mail_templates` (6 form-specific columns)."""
    activity: str                        # activity name, form_type, or "*"
    side: str                            # staff | company | employee | admin
    event: str                           # schedule | reminder | reschedule | cancel | completed | form_summary | form_scorecard
    subject: Optional[str] = None
    body_html: str
    active: bool = True


# ─────────────────────────────────────────────────────────────
# H1b — Meta WhatsApp template library (authored in TPMS, approved by Meta)
#
# A row here is a *template definition* that lives on the WhatsApp Business Account, not a
# per-event notification. The activity × side × event rows in COLL_WHATSAPP_TEMPLATES point
# at one of these by name, and may only point at an APPROVED one.
#
# Vocabulary matches the Cloud API verbatim so a document can be turned into a
# POST /{waba_id}/message_templates payload without translation.
# ─────────────────────────────────────────────────────────────
META_CATEGORY_MARKETING      = "MARKETING"
META_CATEGORY_UTILITY        = "UTILITY"
META_CATEGORY_AUTHENTICATION = "AUTHENTICATION"
META_CATEGORIES = [META_CATEGORY_MARKETING, META_CATEGORY_UTILITY, META_CATEGORY_AUTHENTICATION]

META_HEADER_NONE     = "NONE"
META_HEADER_TEXT     = "TEXT"
META_HEADER_IMAGE    = "IMAGE"
META_HEADER_VIDEO    = "VIDEO"
META_HEADER_DOCUMENT = "DOCUMENT"
META_HEADER_FORMATS = [META_HEADER_NONE, META_HEADER_TEXT, META_HEADER_IMAGE,
                       META_HEADER_VIDEO, META_HEADER_DOCUMENT]
# The three formats whose example is a media handle rather than text.
META_MEDIA_HEADERS = {META_HEADER_IMAGE, META_HEADER_VIDEO, META_HEADER_DOCUMENT}

META_BUTTON_QUICK_REPLY  = "QUICK_REPLY"
META_BUTTON_URL          = "URL"
META_BUTTON_PHONE_NUMBER = "PHONE_NUMBER"
META_BUTTON_TYPES = [META_BUTTON_QUICK_REPLY, META_BUTTON_URL, META_BUTTON_PHONE_NUMBER]

# "Type of variable" — one style per template; Meta rejects a mix.
META_VAR_NUMBERED = "numbered"   # {{1}}, {{2}}, …
META_VAR_NAMED    = "named"      # {{customer_name}}
META_VAR_STYLES = [META_VAR_NUMBERED, META_VAR_NAMED]

# Lifecycle. DRAFT is ours (never submitted); the rest mirror Meta's `status` field, which is
# authoritative from the moment the template is created on the WABA.
META_STATUS_DRAFT    = "DRAFT"
META_STATUS_PENDING  = "PENDING"
META_STATUS_APPROVED = "APPROVED"
META_STATUS_REJECTED = "REJECTED"
# Statuses Meta can additionally report and we store verbatim: PAUSED, DISABLED, IN_APPEAL,
# PENDING_DELETION, DELETED. Only APPROVED is usable for sending.
META_STATUSES = [META_STATUS_DRAFT, META_STATUS_PENDING, META_STATUS_APPROVED, META_STATUS_REJECTED]

# A template may be edited/resubmitted only from these states. Once PENDING or APPROVED the
# definition is Meta's, and editing it locally would silently diverge from what is being sent.
META_EDITABLE_STATUSES = {META_STATUS_DRAFT, META_STATUS_REJECTED}

# Meta's published field limits (Cloud API v21.0).
META_LIMIT_NAME   = 512
META_LIMIT_BODY   = 1024
META_LIMIT_HEADER = 60
META_LIMIT_FOOTER = 60
META_LIMIT_BUTTON_TEXT = 25
META_MAX_BUTTONS = 10
META_MAX_URL_BUTTONS = 2
META_MAX_PHONE_BUTTONS = 1


class MetaTemplateButton(BaseModel):
    """One call-to-action / quick-reply button."""
    type: str = META_BUTTON_QUICK_REPLY
    text: str = ""
    url: Optional[str] = None            # URL buttons; may carry a single trailing variable
    url_example: Optional[str] = None    # required by Meta when `url` is variable
    phone_number: Optional[str] = None   # PHONE_NUMBER buttons, E.164


class MetaWhatsappTemplate(BaseModel):
    """A WhatsApp template authored in TPMS and submitted to Meta for approval.

    `meta_template_id` + `status` are what Meta returned; everything else is the authored
    definition kept so a REJECTED template can be corrected and resubmitted without
    retyping it."""
    name: str                            # ^[a-z0-9_]+$ — Meta rejects anything else
    language: str = "en"
    category: str = META_CATEGORY_UTILITY
    variable_style: str = META_VAR_NUMBERED

    header_format: str = META_HEADER_NONE
    header_text: Optional[str] = None
    header_examples: List[str] = []      # sample value per header variable (max 1)
    header_handle: Optional[str] = None  # media headers — from Meta's resumable upload API
    header_media_url: Optional[str] = None  # sample media we upload to obtain the handle

    body: str = ""
    body_examples: List[str] = []        # sample value per body variable, in order
    footer: Optional[str] = None
    buttons: List[MetaTemplateButton] = []

    # AUTHENTICATION templates have no free-form copy — Meta generates it.
    add_security_recommendation: bool = True
    code_expiration_minutes: Optional[int] = None

    status: str = META_STATUS_DRAFT
    meta_template_id: Optional[str] = None
    meta_category: Optional[str] = None  # the category Meta actually assigned (it can override)
    rejected_reason: Optional[str] = None
    quality_score: Optional[str] = None

    submitted_at: Optional[datetime] = None
    submitted_by: Optional[str] = None
    synced_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# Index specification — consumed by app/db/mongodb.py at startup
# (collection, keys, {options})
# ─────────────────────────────────────────────────────────────
TPMS_INDEXES = [
    (COLL_ACTIVITIES,          [("name", 1)],                                        {"unique": True, "name": "uniq_name"}),
    (COLL_REMINDER_RULES,      [("activity", 1), ("active", 1)],                     {"name": "by_activity_active"}),
    (COLL_RESCHEDULE_REQUESTS, [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_RESCHEDULE_REQUESTS, [("event_id", 1)],                                    {"name": "by_event"}),
    (COLL_TASK_UPLOADS,        [("event_id", 1)],                                    {"name": "by_event"}),
    (COLL_TASK_UPLOADS,        [("company_id", 1), ("period", 1)],                   {"name": "by_company_period"}),
    (COLL_ACTIVITY_TRACKER,    [("company_id", 1), ("period", 1), ("activity", 1)],  {"name": "by_company_period_activity"}),
    (COLL_ACTIVITY_TRACKER,    [("event_id", 1), ("member_id", 1)],                  {"unique": True, "name": "uniq_event_member"}),
    (COLL_ESCALATIONS,         [("event_id", 1)],                                    {"unique": True, "name": "uniq_event"}),
    (COLL_ESCALATIONS,         [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_ACTION_ITEMS,        [("event_id", 1)],                                    {"unique": True, "name": "uniq_event"}),
    (COLL_ACTION_ITEMS,        [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_SUCCESS_MEASURES,    [("company_id", 1), ("activity", 1), ("period", 1),
                                ("scope", 1), ("hod_id", 1)],                        {"unique": True, "name": "uniq_company_activity_period_scope"}),
    (COLL_SUCCESS_MEASURES,    [("company_id", 1), ("period", 1)],                   {"name": "by_company_period"}),
    (COLL_MAIL_TEMPLATES,      [("activity", 1), ("side", 1), ("event", 1)],         {"unique": True, "name": "uniq_activity_side_event"}),
    (COLL_DEPARTMENTS,         [("name", 1), ("company_id", 1)],                     {"unique": True, "name": "uniq_name_company"}),
    (COLL_REMINDER_LOGS,       [("event_id", 1)],                                    {"name": "by_event"}),
    (COLL_REMINDER_LOGS,       [("sent_at", -1)],                                    {"name": "by_sent_at"}),
    (COLL_WHATSAPP_TEMPLATES,  [("activity", 1), ("side", 1), ("event", 1)],         {"unique": True, "name": "uniq_activity_side_event"}),
    # A WhatsApp template is identified on the WABA by (name, language) — the same name in two
    # languages is two templates, so the pair is what must be unique.
    (COLL_META_TEMPLATES,      [("name", 1), ("language", 1)],                       {"unique": True, "name": "uniq_name_language"}),
    (COLL_META_TEMPLATES,      [("status", 1)],                                      {"name": "by_status"}),
    # The unique index IS the de-duplication: the claim is an insert, and a duplicate key
    # error is what tells the ladder this person was already mailed for this stage.
    (COLL_ESCALATION_SENDS,    [("event_id", 1), ("stage", 1), ("recipient", 1)],    {"unique": True, "name": "uniq_event_stage_recipient"}),
    (COLL_ESCALATION_SENDS,    [("sent_on", 1)],                                     {"name": "by_sent_on"}),
    # Drives the undelivered-mail retry sweep (tpms_escalation_service.retry_failed_escalation_mail).
    (COLL_ESCALATION_SENDS,    [("delivered", 1), ("next_retry_at", 1)],             {"name": "by_delivered_retry"}),
    (COLL_JOB_RUNS,            [("job", 1), ("stamp", 1)],                           {"unique": True, "name": "uniq_job_stamp"}),
]
