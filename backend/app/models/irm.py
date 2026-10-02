"""
IRM — Individual Result Matrix.

A per-PERSON score out of 100, built from four evaluation parameters. Each parameter
first produces its own achievement %, that % is then scaled by the parameter's
configured weightage, and the weighted scores are summed:

    Achievement %  = (achieved ÷ total assigned) × 100      [task-type parameters]
                   = (rating sum ÷ (rating count × 5)) × 100 [form-type parameters]
    Weighted Score = (Achievement % × Weightage) ÷ 100
    Final IRM      = Σ Weighted Score                        (out of 100)

WEIGHTAGES ARE DATA, NOT CODE
-----------------------------
The numbers below are SEED values used only the first time a company opens the module
(and as the fallback when no row exists yet). Every calculation reads the weightage
from `irm_configs`, so an admin edit takes effect on the next read — there is no
recalculation job to wait for and no weightage literal anywhere in the maths. See
app/services/irm_service.py.

The four parameters map onto data the ERP already captures:
  task           → RECURRING tasks/checklists, however they were assigned — see
                   irm_service._irm_bucket
  delegation     → a ONE-TIME task someone else hand-assigned to the person
                   (a one-time task a person set for themselves scores in NEITHER)
  culture        → TPMS `culture` rating matrix (their HOD's 0-5 ratings of them)
  accountability → TPMS `accountability` rating matrix (same shape)
"""
import re

from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections
# ─────────────────────────────────────────────────────────────
COLL_IRM_CONFIG = "irm_configs"   # one row per company — the DEFAULT weightages
COLL_IRM_SCORES = "irm_scores"    # optional per (company, period, person) snapshot
# One row per (company, person) — an override for people whose mix differs from the
# company default. Deliberately a SEPARATE collection rather than a field on irm_configs:
# the company row keeps its exact meaning and existing documents are never rewritten, so a
# company that never sets an override behaves precisely as it did before.
COLL_IRM_PERSON_CONFIG = "irm_person_configs"
# Custom KPIs — company-defined parameters that sit alongside the five built-in ones.
#
# A SHARED definition with a list of the people it applies to, rather than a copy on each
# person's config row: a KPI given to six people is one row, so renaming it or changing its
# description is one edit and cannot drift between them. Which people carry it is the
# `person_ids` list — a custom KPI is deliberately NOT company-wide, so it never lands on the
# sheet of someone it was never meant for.
COLL_IRM_CUSTOM_KPIS = "irm_custom_kpis"
# The self-reported number behind a manual KPI — one row per (company, person, code, period).
# Separate from the definition because it is a different thing with a different lifetime: the
# KPI lasts, the score is per month and is written by the person being scored.
COLL_IRM_KPI_SCORES = "irm_kpi_scores"
# Imported attendance — one row per (company, person, date) carrying the day's punches.
# Import is the ONLY writer: there is deliberately no endpoint that marks a day by hand,
# so the punch times always trace back to whatever the biometric/HR export said.
COLL_IRM_ATTENDANCE = "irm_attendance"

# Parameter source kinds — decides how the achievement % is derived.
SOURCE_TASK = "task"   # counted:  achieved ÷ assigned
SOURCE_FORM = "form"   # rated:    rating sum ÷ max possible
SOURCE_ATTENDANCE = "attendance"   # punched: punctual days ÷ days present
# Self-reported: the person being scored enters their own achievement for the period. The
# four sources above read data the ERP already holds; a custom KPI measures something it does
# not, so the number has to come from a human. Who may type it is gated in the routes — the
# assignee for their own row, an admin for anyone's.
SOURCE_MANUAL = "manual"

# Custom KPI codes are namespaced so they can never collide with a built-in parameter code,
# and so any code can be classified as built-in or custom without a database lookup — which
# is what lets the Pydantic validators below stay synchronous.
CUSTOM_CODE_PREFIX = "kpi_"


def is_custom_code(code: str) -> bool:
    return str(code or "").startswith(CUSTOM_CODE_PREFIX)


def make_custom_code(name: str) -> str:
    """A stable, readable code for a KPI name: "Client Calls" → "kpi_client_calls"."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    return f"{CUSTOM_CODE_PREFIX}{slug or 'custom'}"

# ─────────────────────────────────────────────────────────────
# Shift rule — what "punctual" means for a company.
#
# Punctuality cannot be derived from punch times alone: 09:41 is early for one company and
# late for another. The shift is therefore configuration, stored on the company's own
# irm_configs row (additive — a company that never sets one uses these values), and the
# grace period is separate from the shift so "we start at 9:30, 10 minutes is fine" can be
# said directly instead of being smuggled into the start time.
# ─────────────────────────────────────────────────────────────
SHIFT_START_DEFAULT = "09:30"
SHIFT_END_DEFAULT = "18:30"
SHIFT_GRACE_DEFAULT = 10        # minutes


def default_shift() -> Dict[str, object]:
    return {"start": SHIFT_START_DEFAULT, "end": SHIFT_END_DEFAULT,
            "grace_minutes": SHIFT_GRACE_DEFAULT}


# ─────────────────────────────────────────────────────────────
# Per-task weight — how much ONE task counts for inside the Task / Delegation parameters.
#
# Distinct from the parameter weightages above, which decide how the five parameters trade
# off against each other. This decides how two tasks trade off against each other INSIDE
# one of them. 1.0 is the neutral value and the default, so every task already in the
# database keeps counting exactly as it always did.
# ─────────────────────────────────────────────────────────────
TASK_WEIGHT_DEFAULT = 1.0
TASK_WEIGHT_MIN = 0.1
TASK_WEIGHT_MAX = 10.0

# The weightages must add up to exactly this.
TOTAL_WEIGHTAGE = 100.0
# Float tolerance for that equality check (0.01 == one hundredth of a percentage point).
WEIGHTAGE_EPSILON = 0.01


# ─────────────────────────────────────────────────────────────
# Parameter registry — the rows of the IRM evaluation sheet.
# `default_weightage` seeds a company's first config and nothing else.
# ─────────────────────────────────────────────────────────────
IRM_PARAMETERS: List[dict] = [
    {
        "code": "task",
        "name": "Task",
        "default_weightage": 25.0,
        "source": SOURCE_TASK,
        "delegated": False,
        "description": "Target achievement on the person's own tasks and recurring checklists.",
    },
    {
        "code": "delegation",
        "name": "Delegation Score",
        "default_weightage": 30.0,
        "source": SOURCE_TASK,
        "delegated": True,
        "description": "Completion of one-time tasks delegated to the person by someone else.",
    },
    {
        "code": "culture",
        "name": "Culture Form",
        "default_weightage": 25.0,
        "source": SOURCE_FORM,
        "form_type": "culture",
        "description": "Monthly Culture rating submitted by the person's HOD.",
    },
    {
        "code": "accountability",
        "name": "Accountability Form",
        "default_weightage": 20.0,
        "source": SOURCE_FORM,
        "form_type": "accountability",
        "description": "Monthly Accountability rating submitted by the person's HOD.",
    },
    {
        "code": "punctuality",
        "name": "Punctuality",
        # Seeded at ZERO on purpose. The four parameters above already total 100, and every
        # company that has saved a column saved those four. A non-zero seed would push each
        # of those existing columns to more than 100 the moment this parameter shipped,
        # which IRMConfigUpdate would then refuse to re-save. At zero the arithmetic is
        # unchanged for everyone, and a company opts in by taking weightage from the others.
        "default_weightage": 0.0,
        "source": SOURCE_ATTENDANCE,
        "description": "On-time arrival and full-shift departure, from imported punch times.",
    },
]

PARAMETER_CODES: List[str] = [p["code"] for p in IRM_PARAMETERS]
PARAMETER_BY_CODE: Dict[str, dict] = {p["code"]: p for p in IRM_PARAMETERS}


def default_weightages() -> Dict[str, float]:
    """Seed weightages, as a fresh dict (callers mutate their copy)."""
    return {p["code"]: float(p["default_weightage"]) for p in IRM_PARAMETERS}


def parameter_name(code: str) -> str:
    return (PARAMETER_BY_CODE.get(code) or {}).get("name", code)


# ─────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────
class IRMWeightageItem(BaseModel):
    """One editable weightage cell from the sheet."""
    code: str
    weightage: float

    @field_validator("code")
    @classmethod
    def _known_code(cls, v: str) -> str:
        """A built-in parameter, or a custom KPI code.

        Whether a custom code actually exists — and belongs to the person whose column this
        is — cannot be answered here: it needs the database, and a Pydantic validator is
        synchronous. The namespaced prefix is enough to accept the SHAPE; the service checks
        the substance (irm_service.save_weightages), which is also the only layer that knows
        which person the column is for.
        """
        code = str(v or "").strip()
        if code not in PARAMETER_BY_CODE and not is_custom_code(code):
            raise ValueError(f"Unknown IRM parameter '{v}'")
        return code

    @field_validator("weightage")
    @classmethod
    def _in_range(cls, v: float) -> float:
        try:
            w = round(float(v), 2)
        except (TypeError, ValueError):
            raise ValueError("weightage must be a number")
        if w < 0 or w > TOTAL_WEIGHTAGE:
            raise ValueError(f"weightage must be between 0 and {TOTAL_WEIGHTAGE:g}")
        return w


class IRMConfigUpdate(BaseModel):
    """Save the weightage column. Every parameter must be present exactly once and the
    column must total 100 — the sheet's GRAND TOTAL row is a hard rule, not a hint."""
    weightages: List[IRMWeightageItem]

    @field_validator("weightages")
    @classmethod
    def _complete_and_totals_100(cls, items: List[IRMWeightageItem]) -> List[IRMWeightageItem]:
        codes = [i.code for i in items]
        if len(codes) != len(set(codes)):
            raise ValueError("Each IRM parameter may appear only once")
        # Every BUILT-IN parameter must still be present — they are the sheet's fixed rows and
        # a column missing one is not a column. Custom KPIs are the opposite: which of them
        # belong depends on the person, so extra codes are allowed through here and checked
        # against that person's own set in the service.
        missing = [c for c in PARAMETER_CODES if c not in codes]
        if missing:
            names = ", ".join(parameter_name(c) for c in missing)
            raise ValueError(f"Missing weightage for: {names}")

        total = round(sum(i.weightage for i in items), 2)
        if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
            raise ValueError(
                f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
            )
        return items

    def as_map(self) -> Dict[str, float]:
        return {i.code: i.weightage for i in self.weightages}


# Where a resolved weightage map came from. Reported alongside every score so the screen
# can say whether a person is on their own mix or the company's.
SCOPE_PERSON = "person"
SCOPE_COMPANY = "company"
SCOPE_DEFAULT = "default"   # neither row exists — the registry seeds are in force


def _hhmm(value, field: str) -> str:
    """'9:5' → '09:05'. Raises on anything that is not a 24-hour clock time."""
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    return f"{hh:02d}:{mm:02d}"


class IRMShiftUpdate(BaseModel):
    """The company's shift rule. Saved from IRM Setup, read by the punctuality parameter."""
    start: str = SHIFT_START_DEFAULT
    end: str = SHIFT_END_DEFAULT
    grace_minutes: int = SHIFT_GRACE_DEFAULT

    @field_validator("start")
    @classmethod
    def _start(cls, v):
        return _hhmm(v, "Shift start")

    @field_validator("end")
    @classmethod
    def _end(cls, v):
        return _hhmm(v, "Shift end")

    @field_validator("grace_minutes")
    @classmethod
    def _grace(cls, v):
        try:
            g = int(v)
        except (TypeError, ValueError):
            raise ValueError("Grace must be a whole number of minutes")
        if g < 0 or g > 240:
            raise ValueError("Grace must be between 0 and 240 minutes")
        return g

    def as_map(self) -> Dict[str, object]:
        return {"start": self.start, "end": self.end, "grace_minutes": self.grace_minutes}


class IRMConfig(BaseModel):
    company_id: str
    weightages: Dict[str, float] = Field(default_factory=default_weightages)
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Indexes provisioned at startup (mirrors TPMS_INDEXES in app/models/tpms.py).
# ─────────────────────────────────────────────────────────────
# Custom KPI request models
# ─────────────────────────────────────────────────────────────
KPI_NAME_MAX = 60
KPI_DESCRIPTION_MAX = 300
# A manual score is an achievement PERCENTAGE, the same unit every built-in parameter
# produces — so one custom KPI drops into the sheet's arithmetic unchanged.
ACHIEVEMENT_MIN = 0.0
ACHIEVEMENT_MAX = 100.0


# How a KPI's weightage is found inside an assignee's column. The column must total 100, so
# giving somebody a 12% KPI always costs 12% somewhere - the only question is where, and that
# is a judgement about what matters, not arithmetic. So it is asked rather than assumed.
BALANCE_SPREAD = "spread"    # take it from every other parameter, in proportion
BALANCE_FROM = "from"        # take it all out of one named parameter
BALANCE_MANUAL = "manual"    # touch nobody's column; the admin sets each one by hand
BALANCE_MODES = [BALANCE_SPREAD, BALANCE_FROM, BALANCE_MANUAL]


class IRMCustomKpiCreate(BaseModel):
    """A new company KPI, the people it applies to, and where its weightage comes from."""
    name: str
    description: Optional[str] = ""
    weightage: float = 0.0
    person_ids: List[str] = Field(default_factory=list)
    # Defaults to MANUAL: rewriting somebody's weightages is a decision, and a default that
    # quietly re-cuts every assignee's column is the kind of helpfulness you only notice after
    # it has changed a number you cared about.
    balance: str = BALANCE_MANUAL
    balance_from: Optional[str] = None

    @field_validator("balance")
    @classmethod
    def _known_mode(cls, v: str) -> str:
        mode = str(v or BALANCE_MANUAL).strip().lower()
        if mode not in BALANCE_MODES:
            raise ValueError(f"balance must be one of {', '.join(BALANCE_MODES)}")
        return mode

    @field_validator("balance_from")
    @classmethod
    def _known_source(cls, v: Optional[str]) -> Optional[str]:
        code = str(v or "").strip()
        if not code:
            return None
        # Only a BUILT-IN parameter can fund a KPI: taking it from another custom KPI would
        # make two of this company's own rows quietly depend on each other's order.
        if code not in PARAMETER_BY_CODE:
            raise ValueError(f"'{v}' is not a standard parameter")
        return code

    @field_validator("name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        name = str(v or "").strip()
        if not name:
            raise ValueError("Give the KPI a name")
        if len(name) > KPI_NAME_MAX:
            raise ValueError(f"Name must be {KPI_NAME_MAX} characters or fewer")
        return name

    @field_validator("description")
    @classmethod
    def _description_length(cls, v: Optional[str]) -> str:
        text = str(v or "").strip()
        if len(text) > KPI_DESCRIPTION_MAX:
            raise ValueError(f"Description must be {KPI_DESCRIPTION_MAX} characters or fewer")
        return text

    @field_validator("weightage")
    @classmethod
    def _weightage_in_range(cls, v: float) -> float:
        try:
            w = round(float(v), 2)
        except (TypeError, ValueError):
            raise ValueError("weightage must be a number")
        # 100 is refused, not just >100: a KPI taking the whole column would leave every
        # built-in parameter at zero, which is never what someone means to do.
        if w < 0 or w >= TOTAL_WEIGHTAGE:
            raise ValueError(f"weightage must be between 0 and {TOTAL_WEIGHTAGE:g}")
        return w

    @field_validator("person_ids")
    @classmethod
    def _unique_people(cls, v: List[str]) -> List[str]:
        ids = [str(p).strip() for p in (v or []) if str(p).strip()]
        return list(dict.fromkeys(ids))          # de-duplicated, order kept


class IRMCustomKpiUpdate(IRMCustomKpiCreate):
    """Same shape as create — the code is immutable and comes from the URL, so a rename
    never orphans the scores or weightages already filed against it."""


class IRMKpiScoreUpdate(BaseModel):
    """One person's self-reported achievement for one KPI in one period."""
    achievement: float
    note: Optional[str] = ""

    @field_validator("achievement")
    @classmethod
    def _percentage(cls, v: float) -> float:
        try:
            a = round(float(v), 2)
        except (TypeError, ValueError):
            raise ValueError("Score must be a number")
        if a < ACHIEVEMENT_MIN or a > ACHIEVEMENT_MAX:
            raise ValueError(f"Score must be between {ACHIEVEMENT_MIN:g} and {ACHIEVEMENT_MAX:g}")
        return a

    @field_validator("note")
    @classmethod
    def _note_length(cls, v: Optional[str]) -> str:
        return str(v or "").strip()[:KPI_DESCRIPTION_MAX]


IRM_INDEXES = [
    (COLL_IRM_CONFIG, [("company_id", 1)], {"unique": True, "name": "uniq_company"}),
    (COLL_IRM_PERSON_CONFIG, [("company_id", 1), ("person_id", 1)],
     {"unique": True, "name": "uniq_company_person"}),
    (COLL_IRM_PERSON_CONFIG, [("company_id", 1)], {"name": "by_company"}),
    # One row per person per day: a re-import of the same day updates rather than
    # duplicating, which is what makes re-importing a corrected file safe.
    (COLL_IRM_ATTENDANCE, [("company_id", 1), ("person_id", 1), ("date", 1)],
     {"unique": True, "name": "uniq_company_person_date"}),
    (COLL_IRM_ATTENDANCE, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1), ("person_id", 1)],
     {"unique": True, "name": "uniq_company_period_person"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
    # One definition per (company, code) — a second KPI by the same name updates rather than
    # quietly creating a duplicate that would both appear on the sheet.
    (COLL_IRM_CUSTOM_KPIS, [("company_id", 1), ("code", 1)],
     {"unique": True, "name": "uniq_company_code"}),
    (COLL_IRM_CUSTOM_KPIS, [("company_id", 1)], {"name": "by_company"}),
    # One score per person per KPI per month, so re-saving corrects rather than appends.
    (COLL_IRM_KPI_SCORES, [("company_id", 1), ("person_id", 1), ("code", 1), ("period", 1)],
     {"unique": True, "name": "uniq_company_person_code_period"}),
    (COLL_IRM_KPI_SCORES, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
]
