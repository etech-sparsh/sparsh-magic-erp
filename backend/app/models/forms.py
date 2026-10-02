"""
TPMS ▸ Forms sub-module — models + form-type registry.

Two form KINDS are supported:

  • "rating_matrix"   — an HOD scores every team member on fixed criteria using a
                        0–5 scale (Ownership, Accountability, [Culture]).
  • "yesno_checklist" — the MD answers a flat list of questions with Yes/No + an
                        optional remark, with partial (slot-by-slot) submission
                        (Implementation Feedback).

Storage granularity is deliberately atomic so downstream Success Measure
calculations can aggregate freely without re-parsing:
  • rating_matrix   → one score per (company_id, period, hod_id, member_id, criterion_code)
  • yesno_checklist → one answer per (company_id, period, md_id, question_id)
Success Measure computation itself is intentionally NOT implemented here.
"""
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime


SCALE_MIN = 0
SCALE_MAX = 5

KIND_RATING_MATRIX = "rating_matrix"
KIND_YESNO_CHECKLIST = "yesno_checklist"


# ─────────────────────────────────────────────────────────────
# Form-type registry (source of truth for questions/criteria).
# The frontend fetches these so the UI never hardcodes anything.
# Activate a form by filling its criteria/questions and available:True.
# ─────────────────────────────────────────────────────────────
FORM_DEFINITIONS: Dict[str, dict] = {
    "accountability": {
        "form_type": "accountability",
        "kind": KIND_RATING_MATRIX,
        "title": "Accountability Rating",
        "description": "Monthly HOD accountability rating for each team member.",
        "available": True,
        # audience — who fills this on the client side:
        #   "hod" → each HOD rates their own team members
        #   "all" → every client-side user submits their own response
        "audience": "hod",
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "A1", "title": "Timely Task Completion",
             "prompt": "Is he/she ensure adherence to Position Score Card (PSC)?"},
            {"code": "A2", "title": "Departmental result Adherence",
             "prompt": "Is he/she ensuring departmental processes are adhered?"},
            {"code": "A3", "title": "Task Completion Without Follow-up",
             "prompt": "Is he/she ensuring task completion without followup?"},
            {"code": "A4", "title": "Initiative for Better DRM Score",
             "prompt": "Is he/she ensuring to take initiatives to achieve an excellent DRM Score?"},
        ],
    },
    "ownership": {
        "form_type": "ownership",
        "kind": KIND_RATING_MATRIX,
        "title": "Ownership Rating",
        "description": "Monthly HOD ownership rating for each team member.",
        "available": True,
        "audience": "hod",
        # Ownership is only rated for senior members: L4 and above on the client's L1–L12
        # hierarchy (L1 = lower level … L12 = MD), so L3 and below never appear on this form.
        # This is the ONE place the rule lives — the roster endpoints, the assigned-link
        # payload, the submit validation and the client UI all read it from here, so
        # changing the number here changes the form everywhere.
        "min_level": 4,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "O1", "title": "Active Departmental Participation",
             "prompt": "Is he/she getting involved and actively participating in departmental activity?"},
            {"code": "O2", "title": "Departmental Problem Solving",
             "prompt": "Is he/she contributing towards solving departmental problems?"},
            {"code": "O3", "title": "Process Involvement",
             "prompt": "Is he/she interested or involved to follow the process?"},
            {"code": "O4", "title": "Organisational Result Alignment",
             "prompt": "Is he/she aligned with the organisational result Matrix?"},
        ],
    },
    # Culture — an HOD rates each of their team members, exactly like Accountability and
    # Ownership. (Source of truth: HOD_Culture/code.js, which is byte-identical to the
    # Accountability form apart from sheet names + template columns. It builds the team
    # from HOD_IDs and writes one row per question × employee. The 261 rows in
    # HOD_Culture_Responses match that shape.)
    # NOTE: the Activity sheet marks "Culture Rating" as Company-wise — that governs
    # scheduling/upload scope only, NOT who fills the form.
    "culture": {
        "form_type": "culture",
        "kind": KIND_RATING_MATRIX,
        "title": "Culture Rating",
        "description": "Monthly HOD culture rating for each team member.",
        "available": True,
        "audience": "hod",
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "C1", "title": "Works in the Team",
             "prompt": "Supportive and works as a team"},
            {"code": "C2", "title": "Problem Solving Approach",
             "prompt": "Acts as a problem solver in day-to-day work situations and approches with multiple solutions."},
            {"code": "C3", "title": "Carrying Pocket Diary",
             "prompt": "Carries the Pocket Diary at all times as required"},
            {"code": "C4", "title": "Understanding the Core Ideology",
             "prompt": "Is aware of company core values and actively practices them"},
            {"code": "C5", "title": "Customer First Attitude",
             "prompt": "Exhibits a customer-first attitude for internal and external customers"},
        ],
    },
    # Yes/No checklist answered by the company's MD only — not every client-side user.
    # (Source of truth: Implementation_Update_Feedback/code.js, which resolves the
    # respondent as the MD and writes MD_ID / MD_Name columns.)
    # NOTE: Q6 asks for a list of departments — it is a free-text question living in a
    # Yes/No form. The AppScript stores it as Yes/No with the real answer in `remark`;
    # that behaviour is reproduced here deliberately.
    "implementation_feedback": {
        "form_type": "implementation_feedback",
        "kind": KIND_YESNO_CHECKLIST,
        "title": "Implementation Update Feedback",
        "description": "Monthly implementation update feedback submitted by the MD (Yes/No + remark).",
        "available": True,
        "audience": "md",
        "respondent": "md",
        "questions": [
            {"id": "Q1",  "title": "Are you receiving ORM score?", "desc": ""},
            {"id": "Q2",  "title": "Are you receiving process audit scores for all departments?", "desc": ""},
            {"id": "Q3",  "title": "Are CSI (Customer Satisfaction Index) scores being reviewed to identify improvement areas?", "desc": ""},
            {"id": "Q4",  "title": "Were actions taken on TEI (Team Engagement Index) areas to improve team engagement?", "desc": ""},
            {"id": "Q5",  "title": "Is the OHL moving towards the desired pyramid structure month on month through hiring, promotions, and structure corrections?", "desc": ""},
            {"id": "Q6",  "title": "Please mention for which departments you are receiving DRM scores?", "desc": ""},
            {"id": "Q7",  "title": "Is your implementation team making schedules and getting RRO done for IRM (Individual Result Matrix)?", "desc": ""},
            {"id": "Q8",  "title": "Are Weekly Review Meetings (WRM) happening?", "desc": ""},
            {"id": "Q9",  "title": "Are Monthly Management Reviews (MMR) being conducted?", "desc": ""},
            {"id": "Q10", "title": "Are A&O ratings happening?", "desc": ""},
            {"id": "Q11", "title": "Are culture ratings happening?", "desc": ""},
            {"id": "Q12", "title": "Are leadership scoring happening?", "desc": ""},
            {"id": "Q13", "title": "Are you receiving calendars for leaders?", "desc": ""},
            {"id": "Q14", "title": "Do you feel the implementation is moving forward with the expected speed?", "desc": ""},
            {"id": "Q15", "title": "Do teams have sufficient leadership support and decision-making speed to implement the framework?", "desc": ""},
        ],
    },
}


# ─────────────────────────────────────────────────────────────
# Physical storage — one dedicated collection ("table") per form.
# submission_collection(form_type) is the single source of truth used by the
# routes and by the DB provisioning (startup hook + scripts/setup_form_collections.py).
# ─────────────────────────────────────────────────────────────
FORM_COLLECTIONS: Dict[str, str] = {
    "accountability":         "tpms_accountability",
    "ownership":              "tpms_ownership",
    "culture":                "tpms_culture",
    "implementation_feedback": "tpms_implementation_feedback",
}


def submission_collection(form_type: str) -> Optional[str]:
    """The collection a form's submissions are stored in (one table per form)."""
    return FORM_COLLECTIONS.get(form_type)


# M10 — question master. Stores the editable TEXT of each form's criteria/questions, keyed by
# the immutable item id (criterion code / question id). Business can reword prompts; item ids
# are never changed here, so scoring and cell-level validation stay intact.
QUESTION_COLLECTION = "tpms_form_questions"


def definition_items(form_type: str, definition: dict) -> List[dict]:
    """Flatten a form definition's criteria/questions into master rows (for seeding)."""
    kind = definition.get("kind")
    if kind == KIND_RATING_MATRIX:
        return [{"form_type": form_type, "kind": kind, "item_id": c["code"],
                 "title": c.get("title", ""), "prompt": c.get("prompt", ""),
                 "order": i, "active": True}
                for i, c in enumerate(definition.get("criteria", []))]
    return [{"form_type": form_type, "kind": kind, "item_id": str(q["id"]),
             "title": q.get("title", ""), "desc": q.get("desc", ""),
             "order": i, "active": True}
            for i, q in enumerate(definition.get("questions", []))]


# ─────────────────────────────────────────────────────────────
# Activity catalogue — the Success-Measure activities scheduled on the calendar and
# scored on the client dashboard. Keep in sync with the frontend Schedule Calendar list.
# ─────────────────────────────────────────────────────────────
ACTIVITY_CATALOGUE = [
    "Org Structure Update",
    "DRM & KPI data available",
    "Calendar Discipline",
    "WRM",
    "Monthly Management Review (MMR)",
    "One pager Memo",
    "Action Closure Review",
    "Accountability & Ownership Rating",
    "Culture Rating",
    "RRO",
    "Implementation Update Feedback",
    "Team Engagement Index",
    "Customer Satisfaction Index",
    "Organization Result Matrix",
]

# Activities whose "Actual Score %" is derived from a TPMS form submission.
# The value is the list of form_types averaged for that activity's score.
ACTIVITY_FORM_MAP = {
    "Accountability & Ownership Rating": ["accountability", "ownership"],
    "Culture Rating": ["culture"],
    "Implementation Update Feedback": ["implementation_feedback"],
}


# ─────────────────────────────────────────────────────────────
# Hierarchy-level eligibility (`min_level` on a form definition).
#
# A member's hierarchy level is free text — "L1" … "L12" in practice (L1 = lower level …
# L12 = MD), occasionally written "Level 4" or as a bare number. It is parsed rather than
# compared as a string so "L10"/"L12" rank above "L4" instead of sorting before them.
#
# TWO fields carry it. `leadership_level` is the one the org-structure tooling writes and it
# WINS wherever it is set; `level` is the original field and remains the fallback for users
# that tooling has not touched. Reading only `level` made recently-levelled members
# (leadership_level set, level still empty) invisible to a level-gated form, and disagreed
# with the newer value for members who have both.
#
# Membership is resolved at READ time (every time the form is opened), never snapshotted onto
# the assignment — so correcting someone's level is reflected on the already-generated form
# the next time it is opened, with no need to re-issue the link.
# ─────────────────────────────────────────────────────────────
LEVEL_FIELDS = ("leadership_level", "level")


def user_level(user: dict):
    """The level to judge a member by: `leadership_level` when set, otherwise `level`.

    Blank strings count as unset — a cleared field falls through to the next one rather than
    reading as level 0.
    """
    for field in LEVEL_FIELDS:
        value = (user or {}).get(field)
        if value is not None and str(value).strip() != "":
            return value
    return None


def member_level_number(value) -> int:
    """Numeric hierarchy level of a user's `level` field. 0 = unset or unparseable.

    0 sorts below every real level, so a member with no level set does not appear on a
    level-restricted form until their level is filled in.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else 0


def form_min_level(form_type: str) -> int:
    """Lowest hierarchy level that appears on this form's roster. 0 = no restriction."""
    try:
        return int((FORM_DEFINITIONS.get(form_type) or {}).get("min_level") or 0)
    except (TypeError, ValueError):
        return 0


def user_level_number(user: dict) -> int:
    """A member's effective numeric hierarchy level across both level fields."""
    return member_level_number(user_level(user))


def eligible_by_level(users: List[dict], form_type: str) -> List[dict]:
    """`users` narrowed to those meeting the form's `min_level`. Unrestricted forms pass through."""
    min_level = form_min_level(form_type)
    if not min_level:
        return list(users)
    return [u for u in users if user_level_number(u) >= min_level]


def get_definition(form_type: str) -> Optional[dict]:
    return FORM_DEFINITIONS.get(form_type)


def form_kind(form_type: str) -> Optional[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return d.get("kind")


def form_audience(form_type: str) -> str:
    """Who fills this form on the client side:
      'hod' — each HOD rates their own team members (Accountability/Ownership/Culture)
      'md'  — only the company's MD responds (Implementation Feedback)
      'all' — every client-side user submits their own response
    Defaults to 'hod'."""
    d = FORM_DEFINITIONS.get(form_type) or {}
    return d.get("audience", "hod")


# audience → the client-side `department` value required to submit. 'all' imposes none.
AUDIENCE_DEPARTMENT = {"hod": "hod", "md": "md"}


def criteria_codes(form_type: str) -> List[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return [c["code"] for c in d.get("criteria", [])]


def question_map(form_type: str) -> Dict[str, dict]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return {str(q["id"]): q for q in d.get("questions", [])}


# ─────────────────────────────────────────────────────────────
# rating_matrix submission models (cell-level, partial submission)
# One "cell" = one team member rated on one criterion.
# ─────────────────────────────────────────────────────────────
class RatingCell(BaseModel):
    criterion_code: str
    member_id: str
    member_name: str
    designation: Optional[str] = None
    employee_id: Optional[str] = None
    rating: int

    @field_validator("criterion_code", "member_id", "member_name")
    @classmethod
    def _required(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("criterion_code, member_id and member_name are required")
        return str(v).strip()

    @field_validator("rating")
    @classmethod
    def _rating_in_range(cls, v: int) -> int:
        if not isinstance(v, int) or v < SCALE_MIN or v > SCALE_MAX:
            raise ValueError(f"rating must be an integer between {SCALE_MIN} and {SCALE_MAX}")
        return v


class RatingSubmissionCreate(BaseModel):
    company_id: str
    period: str
    hod_id: str
    hod_name: Optional[str] = None
    ratings: List[RatingCell]

    @field_validator("company_id", "period", "hod_id")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("company_id, period and hod_id are required")
        return str(v).strip()

    @field_validator("ratings")
    @classmethod
    def _ratings_non_empty(cls, v: List[RatingCell]) -> List[RatingCell]:
        if not v:
            raise ValueError("At least one rating is required")
        return v


# ─────────────────────────────────────────────────────────────
# yesno_checklist submission models
# ─────────────────────────────────────────────────────────────
class FeedbackAnswer(BaseModel):
    question_id: str
    question: Optional[str] = ""       # snapshot of the question text at answer time
    checked: bool = False              # True = Yes, False = No
    remark: Optional[str] = ""

    @field_validator("question_id")
    @classmethod
    def _qid_required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("question_id is required")
        return str(v).strip()


class FeedbackSubmissionCreate(BaseModel):
    company_id: str
    period: str
    md_id: str
    md_name: Optional[str] = None
    answers: List[FeedbackAnswer]

    @field_validator("company_id", "period", "md_id")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("company_id, period and md_id are required")
        return str(v).strip()

    @field_validator("answers")
    @classmethod
    def _answers_non_empty(cls, v: List[FeedbackAnswer]) -> List[FeedbackAnswer]:
        if not v:
            raise ValueError("At least one answer is required")
        return v
