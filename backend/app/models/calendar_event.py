from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime

class Reminder(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    # task | event | todo. Descriptive only — it records what the reminder was authored on, and
    # is NOT what picks the reminder email template: send_reminder_email keys a todo off the
    # DOCUMENT type so a mislabelled reminder can never reach the Task template.
    parent_type: str
    reminder_type: str # email | whatsapp | both
    timing_type: str # before | after
    offset_minutes: int
    sent: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CalendarEventBase(BaseModel):
    title: str
    type: str = "event" # event, task
    start: str 
    end: Optional[str] = None
    all_day: bool = False
    
    # Event specific
    session_type: Optional[str] = None
    priority: Optional[str] = "Normal"
    # IRM ▸ how much this ONE task counts for inside the Task / Delegation parameter.
    # Optional and unset by default, so every task already stored — and every task created
    # from the ordinary Task form — keeps weighing exactly 1.0 (see irm_service.task_weight).
    irm_weight: Optional[float] = None
    session_template_id: Optional[str] = None
    batch_id: Optional[str] = None
    quarter_id: Optional[str] = None
    status: str = "schedule"
    assigned_departments: Optional[List[str]] = []
    assigned_member_ids: Optional[List[str]] = []
    coach_ids: Optional[List[str]] = []
    additional_details: Optional[str] = None
    status_remark: Optional[str] = None # Added for handover/reschedule notes
    meeting_link: Optional[str] = None
    gpt_project_id: Optional[str] = None
    gpt_project_name: Optional[str] = None
    gpt_projects: List[Dict] = []

    
    # Task specific
    category: Optional[str] = None
    description: Optional[str] = None
    
    # Repetition
    repeat: str = "Does not repeat" # Daily, Weekly, Monthly, Yearly, Periodically, Custom
    repeat_end_date: Optional[str] = None
    repeat_interval: Optional[int] = 1
    repeat_data: Optional[dict] = None
    
    # Delegation
    assigned_to: str = "myself" # myself, other
    target_staff_id: Optional[List[str]] = []
    # How a task with multiple assignees is materialised (task-typed docs only; events ignore it):
    #   "combined" (default) — one shared task doc for the whole group (existing behavior); any
    #       assignee completing it (verified, if verification is enabled) completes it for all.
    #   "separate" — one independent task doc per assignee, each with its own status/progress/
    #       evidence/verification/comments/deadline/completion, so users are tracked individually.
    assignment_mode: Optional[str] = "combined"  # combined | separate

    # Reminders
    reminders: List[Reminder] = []

    color: str = "var(--accent-indigo)"
    bg: str = "var(--accent-indigo-bg)"

    # ─── Task Management module additions (additive/optional; events are unaffected) ───
    # Richer workflow state for type=="task" docs only. The legacy `status` field
    # (schedule/completed/canceled/reschedule) stays authoritative for the Calendar page;
    # the Task Management dashboard/lists read `workflow_status`. A task starts In Progress —
    # it is live from the moment it is raised — and "pending" is kept in the accepted values
    # only so documents that already hold it still validate (tasks._resolve_workflow_status
    # reads those as In Progress).
    workflow_status: str = "in_progress" # accepted, in_progress, dependent_on_others, blocked, verification, completed
    watchers: Optional[List[str]] = [] # user ids "in the loop" / subscribed to this task
    tags: Optional[List[str]] = []
    group_id: Optional[str] = None # Task Group this task belongs to (Groups sub-module); None = ungrouped
    parent_task_id: Optional[str] = None # Parent task id for a subtask; None = top-level task
    deleted_at: Optional[str] = None # soft-delete timestamp (ISO string); None = not deleted

    # ─── Task Details additions (checklist/attachments/comments/history) ───
    evidence_required: bool = False
    verification_required: bool = False
    checklist: List[Dict] = [] # [{id, title, completed, completed_at}]
    attachments: List[Dict] = [] # [{id, name, key, url, uploaded_by, uploaded_at}] - assignment-time attachments
    remarks: List[Dict] = [] # [{id, author_id, author_name, text, created_at}] - task comment thread
    status_history: List[Dict] = [] # [{old_status, new_status, changed_by, changed_by_name, reason, changed_at}]

    # ─── Delegation-flow additions (additive/optional; existing tasks default to []) ───
    # Evidence uploaded while COMPLETING the task, kept separate from `attachments`
    # (the assignment-time files) so the two never mix in the UI.
    completion_attachments: List[Dict] = [] # [{id, name, key, url, uploaded_by, uploaded_at}]
    # Deadline (`end`) revision trail — only the assigner/delegator can revise.
    # Each entry may also carry kind ("revision" | "reopen") and, when it came from an
    # assignee's request, request_id / requested_by / requested_by_name / decision_remark.
    deadline_history: List[Dict] = [] # [{old_end, new_end, reason, revised_by, revised_by_name, revised_at}]
    # Deadline revision REQUESTS raised by an assignee. The assignee cannot move the deadline
    # themselves — they propose a new one and the assigner (or an admin / the reporting manager)
    # approves or rejects it. Only an APPROVED request moves `end` and writes into
    # `deadline_history` above, so the revised deadline "continues" only once it is signed off.
    # At most one entry is ever `pending`; raising another supersedes it.
    # [{id, old_end, new_end, reason, requested_by, requested_by_name, requested_at,
    #   status: pending|approved|rejected|superseded, decided_by, decided_by_name,
    #   decided_at, decision_remark}]
    deadline_requests: List[Dict] = []
    # Follow-Ups raised by In-Loop members (watchers) / participants — a nudge + remark.
    # The count is simply len(follow_ups). Additive/optional; existing tasks default to [].
    follow_ups: List[Dict] = [] # [{id, by, by_name, remark, created_at}]

    # ─── TPMS module additions (additive/optional; non-TPMS events are unaffected) ───
    # A TPMS "scheduled activity" IS a calendar event, tagged with this discriminator so
    # it reuses the recurrence engine, reminder scheduler and calendar UI. All other
    # events leave `kind` as None. See app/models/tpms.py:TPMS_EVENT_KIND.
    kind: Optional[str] = None                      # "tpms_activity" | None
    # TPMS's own status vocabulary (Scheduled/Rescheduled/Cancelled/Completed/Lapsed).
    # The legacy lowercase `status` above stays in sync via tpms.erp_status_for() so the
    # existing Calendar page and every other consumer keep working unchanged.
    tpms_status: Optional[str] = None
    # Groups one recurrence expansion (the Apps Script's Batch_ID). Deliberately NOT
    # `batch_id` — that name is already taken above by the LMS Batch.
    tpms_batch_id: Optional[str] = None
    # Escalation ladder progress: 0=none, 1=pending mailed, 2=critical mailed, 3=lapsed.
    # Reset to 0 when the doer marks done. (runEscalationLadder, code.js:3755)
    esc_stage: int = 0
    reschedule_count: int = 0
    # Two-step completion: the doer claims it, then internal staff confirm. `status`
    # only becomes "completed" on confirmation. (code.js:3888 / 3915)
    learner_done: bool = False
    learner_done_by: Optional[str] = None
    learner_done_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None

class CalendarEventCreate(CalendarEventBase):
    pass

class CalendarEventResponse(CalendarEventBase):
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
