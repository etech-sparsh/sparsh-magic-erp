"""
TPMS ▸ Leadership Score — domain model, question master seed and payloads.

Leadership Score is one of the four matrices of the OD Matrix. It is a purely
feedback-derived score: 8 anonymous givers (2 superiors, 2 peers, 2 other-department
peers, 2 direct reports) rate one leader against level-specific expectations, once
every 2 months, and the weighted result is discussed at RRO.

ISOLATION
---------
This module owns its own collections exclusively (every name below is new). It does
not read, write, migrate or restructure any existing TPMS collection — the four
existing forms (Accountability / Ownership / Culture / Implementation Feedback), their
submissions, their assignments and their scoring are untouched by design. Where TPMS
infrastructure is reused it is reused as *pure functions* (token minting, period
arithmetic), never as shared storage.

WHY A SEPARATE QUESTION MASTER
------------------------------
`tpms_form_questions` is keyed (form_type, item_id) and its rows carry no level,
options or weightage. Leadership questions are keyed (level, item_id) and each carries
four scored options plus a weightage. Rather than widen the existing master — which
would touch rows the other four forms depend on — Leadership Score keeps its own.

SOURCE FIDELITY
---------------
LEADERSHIP_QUESTION_SEED below is transcribed VERBATIM from "Key insights of Leadership
Score", including its option scores (1 / 2 / 4 / 5 — note that 3 is never awarded) and
its original wording and typography. The document is the single source of truth and is
used exactly as it stands: nothing here "fixes" it, and — by instruction — nothing
flags, questions or withholds a question for confirmation either. Titles, option
wording and option scores are seeded and scored as printed. All question text, option
text, option scores and weightages remain editable at runtime through the admin API for
whoever chooses to change them.
"""
import hashlib
import json

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, List, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections — ALL NEW. None of these exist in TPMS today.
# ─────────────────────────────────────────────────────────────
COLL_LS_CYCLES      = "tpms_leadership_cycles"       # one per (company, cycle)
COLL_LS_SUBJECTS    = "tpms_leadership_subjects"     # leaders enrolled into a cycle
COLL_LS_ASSIGNMENTS = "tpms_leadership_assignments"  # one link per (subject, giver)
# ─────────────────────────────────────────────────────────────
# Leadership owns its WhatsApp stack outright — template, delivery log and all.
#
# Deliberately NOT the TPMS tables. TPMS keys its templates on (activity, event kind, side)
# and its log on an activity id; a Leadership invitation has none of those, and squeezing it
# in would have meant either inventing fake activity codes or widening TPMS's schema for a
# module that is not TPMS. Separate collections also mean a TPMS retention sweep can never
# reach feedback-invitation records, which carry panel identity.
# ─────────────────────────────────────────────────────────────
COLL_LS_WA_TEMPLATE  = "tpms_leadership_wa_template"    # THE invitation: exactly one row, all companies
# Superseded by the single shared template above. Read-only now, and only as a fallback
# while the shared one is not yet approved — see leadership_wa_service.send_invitation.
COLL_LS_WA_TEMPLATES = "tpms_leadership_wa_templates"   # legacy: one row per company
COLL_LS_WA_LOG       = "tpms_leadership_wa_log"         # one row per send attempt
COLL_LS_DOCUMENTS    = "tpms_leadership_documents"      # module file store
COLL_LS_RESPONSES   = "tpms_leadership_responses"    # one submitted feedback form
COLL_LS_QUESTIONS   = "tpms_leadership_questions"    # level-specific question master
COLL_LS_SCORES      = "tpms_leadership_scores"       # snapshot taken when a cycle closes
COLL_LS_DISCUSSIONS = "tpms_leadership_discussions"   # the RRO conversation + action plan
COLL_LS_BRIEFINGS   = "tpms_leadership_briefings"     # pre/post briefing tracker


# ─────────────────────────────────────────────────────────────
# Leadership levels — "Applicable from L4 (Asst Managers) and above".
# "Feedback parameters will differ from designation to designation."
# ─────────────────────────────────────────────────────────────
LEVEL_L4 = "L4"
LEVEL_L5 = "L5"
LEVEL_L6 = "L6"
LEVEL_L7 = "L7"          # "L7 & ABOVE"

LEVELS: List[str] = [LEVEL_L4, LEVEL_L5, LEVEL_L6, LEVEL_L7]

LEVEL_LABELS: Dict[str, str] = {
    LEVEL_L4: "L-4 (Asst. Manager)",
    LEVEL_L5: "L-5 (Manager)",
    LEVEL_L6: "L-6 (Senior Manager)",
    LEVEL_L7: "L7 & Above",
}

LEVEL_THEMES: Dict[str, str] = {
    LEVEL_L4: "Self-Management + Managing Other",
    LEVEL_L5: "Managing self and other managers",
    LEVEL_L6: "Managers' productivity, measurement, innovation",
    LEVEL_L7: "Strategy, business acumen, alignment",
}


# ─────────────────────────────────────────────────────────────
# Feedback givers — "hum aapke 8 logon se feedback lenge:
# 2 superiors, 2 peers, 2 other departments, aur 2 direct reports".
# ─────────────────────────────────────────────────────────────
REL_SUPERIOR     = "superior"
REL_PEER         = "peer"              # peer of the same department
REL_OTHER_DEPT   = "other_department"  # peer of another department
REL_DIRECT_REPORT = "direct_report"    # junior

RELATIONS: List[str] = [REL_SUPERIOR, REL_PEER, REL_OTHER_DEPT, REL_DIRECT_REPORT]

RELATION_LABELS: Dict[str, str] = {
    REL_SUPERIOR: "Supervisor",
    REL_PEER: "Peer (same department)",
    REL_OTHER_DEPT: "Peer (other department)",
    REL_DIRECT_REPORT: "Junior / Direct report",
}

# The document's recommended panel: 2 of each relation = 8 givers.
RECOMMENDED_PER_RELATION = 2
RECOMMENDED_PANEL_SIZE = RECOMMENDED_PER_RELATION * len(RELATIONS)

# Fewest responses a score may ever be computed from.
#
# The whole module rests on "ye feedback completely confidential hoga". A score built from
# one or two responses breaks that promise arithmetically: HR knows the panel, the result
# carries a per-relation breakdown, and with a single response in a relation the rating IS
# that person's rating, named. Three is the smallest number that keeps an individual answer
# inside an average. It is a floor, not a default — HR can still require more.
MIN_RESPONSES_FLOOR = 3

# COLLECTION IS DIGITAL ONLY.
#
# The source document prefers hard copy — "HR just approach each persons (feedback givers)
# for their score in hard copies, preferably, otherwise through digital form" — but the
# business has decided otherwise: every giver is emailed a personal link and submits
# online, and there is no paper intake at all.
#
# This is a deliberate departure from the document, recorded here so nobody reinstates a
# paper path by reading §5 of the source and assuming it was overlooked. It also removes
# the weakest point in the chain: a folder of completed forms in an HR drawer, and an
# administrator able to key in or delete feedback nobody can trace.

# Fewest responses a subject needs before a score may be FROZEN and released.
#
# Distinct from MIN_RESPONSES_FLOOR, which is the anonymity floor for showing a number at
# all. This is the confidence floor: the document's panel is 8, and a result built from
# three of them is not the 360° view its label claims. HR may raise or lower it per cycle
# but never below the anonymity floor.
DEFAULT_QUORUM = 5

# Relation groups are averaged first, then weighted against each other. Equal by default:
# the document does not say whether a direct report's view should outweigh a superior's,
# so the neutral split is the only defensible starting point and the screen says so.
DEFAULT_GROUP_WEIGHT = "equal"

# 180° collects from superiors and same-department peers; 360° from everyone.
# ("The feedback may be 180 degree or 360 degree.")
DEGREE_180 = "180"
DEGREE_360 = "360"
DEGREES: List[str] = [DEGREE_180, DEGREE_360]

DEGREE_RELATIONS: Dict[str, List[str]] = {
    DEGREE_180: [REL_SUPERIOR, REL_PEER],
    DEGREE_360: list(RELATIONS),
}


def panel_size_for(degree) -> int:
    """How many givers a degree actually collects from: 4 at 180 degrees, 8 at 360.

    RECOMMENDED_PANEL_SIZE is the 360 figure, and it was read as though it were universal.
    It is not: 180 collects from superiors and same-department peers only, so its panel is
    two relations x RECOMMENDED_PER_RELATION = four people. Treating it as eight let a 180
    cycle be created needing more replies than it has givers, and left DEFAULT_QUORUM (5)
    permanently out of reach of a four-person panel.
    """
    rels = DEGREE_RELATIONS.get(str(degree or DEGREE_360), RELATIONS)
    return RECOMMENDED_PER_RELATION * len(rels)


# ─────────────────────────────────────────────────────────────
# Cycle lifecycle
# ─────────────────────────────────────────────────────────────
CYCLE_DRAFT     = "draft"      # being set up; no links issued
CYCLE_OPEN      = "open"       # links issued, feedback being collected
CYCLE_CLOSED    = "closed"     # window shut; no further feedback accepted
CYCLE_COMPUTED  = "computed"   # scores frozen into COLL_LS_SCORES, HR reviewing
CYCLE_PUBLISHED = "published"  # released to leaders and their reporting managers

CYCLE_STATUSES: List[str] = [CYCLE_DRAFT, CYCLE_OPEN, CYCLE_CLOSED,
                             CYCLE_COMPUTED, CYCLE_PUBLISHED]

# Which states a cycle may move to from where.
#
# The important edge is that a leader sees NOTHING until `published`. Without that step a
# subject could read their own score while collection was still open, refresh after each
# submission and difference the average — which is one named person's rating, arrived at
# arithmetically. Group suppression does not stop that; only withholding the number does.
#
# Re-opening a closed cycle is allowed (HR extends a window for a late responder) and
# recomputing is allowed, but `published` is terminal for collection: once leaders have
# seen a number, changing the inputs behind it would rewrite a conversation that already
# happened.
CYCLE_TRANSITIONS: Dict[str, List[str]] = {
    CYCLE_DRAFT:     [CYCLE_OPEN],
    CYCLE_OPEN:      [CYCLE_CLOSED, CYCLE_DRAFT],
    CYCLE_CLOSED:    [CYCLE_OPEN, CYCLE_COMPUTED],
    CYCLE_COMPUTED:  [CYCLE_CLOSED, CYCLE_PUBLISHED],
    CYCLE_PUBLISHED: [],
}

# Feedback may still arrive in these states only.
CYCLE_COLLECTING: List[str] = [CYCLE_DRAFT, CYCLE_OPEN]


def can_transition(current: str, target: str) -> bool:
    return target in CYCLE_TRANSITIONS.get(str(current or CYCLE_DRAFT), [])

# Assignment (link) lifecycle — mirrors the vocabulary of tpms_form_link_service so the
# admin log reads identically, without sharing its storage.
# A link exists but has NOT been mailed yet. Rows used to be created as "sent", so a link
# that was minted and never delivered still read as Sent in the admin log. The real send is
# what promotes pending -> sent.
LINK_PENDING   = "pending"
LINK_SENT      = "sent"
LINK_OPENED    = "opened"
LINK_SUBMITTED = "submitted"
LINK_EXPIRED   = "expired"      # derived from the cycle window, never written

# ─────────────────────────────────────────────────────────────
# WhatsApp delivery states, in the order a message moves through them.
#
# PENDING is a real state, not a placeholder: a row is written before the send is attempted,
# so a crash mid-dispatch leaves evidence that the attempt happened rather than nothing at
# all. UNREACHABLE is kept apart from FAILED because they need different fixes — one is a
# missing number on a user record, the other is Meta rejecting a message we did send.
# ─────────────────────────────────────────────────────────────
WA_PENDING     = "pending"
WA_SENT        = "sent"
WA_DELIVERED   = "delivered"
WA_READ        = "read"
WA_FAILED      = "failed"
WA_UNREACHABLE = "unreachable"

WA_STATUSES: List[str] = [WA_PENDING, WA_SENT, WA_DELIVERED, WA_READ, WA_FAILED, WA_UNREACHABLE]

# Only ever move forward. Meta's webhooks arrive out of order often enough that a late
# "sent" callback would otherwise drag a message that is already "read" backwards.
WA_RANK: Dict[str, int] = {s: i for i, s in enumerate(
    [WA_PENDING, WA_SENT, WA_DELIVERED, WA_READ])}


def wa_is_forward(current: str, target: str) -> bool:
    """Whether `target` is a later state than `current`.

    Terminal failures always apply — a message can fail after being sent — but a progress
    state never regresses.
    """
    if target in (WA_FAILED, WA_UNREACHABLE):
        return True
    if current in (WA_FAILED, WA_UNREACHABLE):
        return False
    return WA_RANK.get(target, -1) > WA_RANK.get(current, -1)

# How long after a successful send the same pending invitation is left alone.
#
# "Mail All Pending" is a chase button, so its natural use is to press it again a few days
# later — but nothing stopped it being pressed three times in a minute, which mailed every
# outstanding giver three times. A cooldown makes the button safe to re-press without
# making it useless: anyone mailed longer ago than this is still chased on the next click.
# A never-sent or previously-FAILED invitation is never held back.
RESEND_COOLDOWN_HOURS = 24

# ─────────────────────────────────────────────────────────────
# Invitation link expiry
#
# Stored in the EXISTING `tpms_mail_templates` collection, so Leadership reuses the mail
# system the rest of TPMS already uses instead of growing a second one. The collection is
# keyed (activity, side, event) and this triple is new on all three counts, so it cannot
# collide with — or be picked up by — any template that exists today:
#
#   activity  "Leadership Score"   not in ACTIVITY_SEED; no scheduled activity uses it
#   side      "company"            givers are company-side people
#   event     "leadership_invite"  a brand-new event kind, used by nothing else
#
# `get_template()` falls back to the "*" catch-all only within the SAME event, so an
# existing "*" row for schedule/reminder events can never be served as a leadership
# invitation either.
# ─────────────────────────────────────────────────────────────
# Rating ceiling. The document scores every option 1, 2, 4 or 5 on a 1-5 scale.
SCALE_MIN = 1
SCALE_MAX = 5

# The weightage column must total this per level, exactly.
TOTAL_WEIGHTAGE = 100.0
WEIGHTAGE_EPSILON = 0.01


# ─────────────────────────────────────────────────────────────
# Cycle helpers — a Leadership cycle spans TWO calendar months.
#
# `cycle` is the canonical key ("2026-C3" = the 3rd two-month window of 2026,
# i.e. May-June). `period` carries the cycle's CLOSING month as "YYYY-MM" so the
# familiar TPMS period vocabulary still identifies a cycle in logs and filters.
# ─────────────────────────────────────────────────────────────
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def cycle_code(year: int, start_month: int) -> str:
    """(2026, 5) → '2026-C3'. Windows are Jan-Feb, Mar-Apr, … Nov-Dec."""
    return f"{year:04d}-C{((int(start_month) - 1) // 2) + 1}"


def cycle_months(cycle: str) -> tuple:
    """'2026-C3' → (2026, 5, 6) — year, first month, second month."""
    year_s, _, idx_s = str(cycle or "").partition("-C")
    year, idx = int(year_s), int(idx_s)
    if idx < 1 or idx > 6:
        raise ValueError(f"Invalid cycle '{cycle}'")
    first = (idx - 1) * 2 + 1
    return year, first, first + 1


def cycle_label(cycle: str) -> str:
    """'2026-C3' → 'May–Jun 2026'."""
    try:
        year, first, second = cycle_months(cycle)
    except (ValueError, TypeError):
        return str(cycle or "")
    return f"{_MONTH_ABBR[first - 1]}–{_MONTH_ABBR[second - 1]} {year}"


def cycle_period(cycle: str) -> str:
    """The cycle's CLOSING month as 'YYYY-MM' — '2026-C3' → '2026-06'."""
    year, _, second = cycle_months(cycle)
    return f"{year:04d}-{second:02d}"


def current_cycle(now: Optional[datetime] = None) -> str:
    now = now or datetime.utcnow()
    return cycle_code(now.year, now.month)


def recent_cycles(count: int = 6, now: Optional[datetime] = None) -> List[str]:
    """The current cycle and the ones before it, newest first."""
    now = now or datetime.utcnow()
    year, first, _ = cycle_months(current_cycle(now))
    out = []
    for _ in range(max(1, count)):
        out.append(cycle_code(year, first))
        first -= 2
        if first < 1:
            first, year = 11, year - 1
    return out


def upcoming_cycles(count: int = 3, now: Optional[datetime] = None) -> List[str]:
    """The cycles AFTER the current one, soonest first.

    A cycle's feedback links live for exactly its own two-month window, so a cycle whose
    window has already passed can be created but never dispatched — every link is born
    expired. Offering only past windows therefore left HR unable to open a usable cycle
    once the current one was taken: every remaining choice was dead on arrival.
    """
    now = now or datetime.utcnow()
    year, first, _ = cycle_months(current_cycle(now))
    out = []
    for _ in range(max(0, count)):
        first += 2
        if first > 11:
            first, year = 1, year + 1
        out.append(cycle_code(year, first))
    return out


def selectable_cycles(back: int = 6, ahead: int = 3,
                      now: Optional[datetime] = None) -> List[str]:
    """What the "open a cycle" picker should offer: soonest upcoming first, then the
    current window, then recent ones — so the default choice is a cycle that can actually
    collect feedback."""
    return list(reversed(upcoming_cycles(ahead, now))) + recent_cycles(back, now)


# ─────────────────────────────────────────────────────────────
# Question master seed — VERBATIM from the source document.
#
# Every option carries the exact score printed in the document. The set {1, 2, 4, 5}
# is intentional: the source awards no 3 anywhere.
#
# `weightage` is NOT specified anywhere in the document — it only states that
# "All parameters should have weightages to create scoring - HR and MD". The seed
# therefore distributes weight EQUALLY across a level's questions (summing to exactly
# 100), which is a neutral starting point, and HR/MD set the real values through
# PUT /api/leadership/questions/weightages. No weightage is invented per question.
# ─────────────────────────────────────────────────────────────
def _opts(*pairs) -> List[dict]:
    """(('A', 'text', 1), …) → option rows."""
    return [{"option_id": oid, "label": label, "score": score} for oid, label, score in pairs]


LEADERSHIP_QUESTION_SEED: Dict[str, List[dict]] = {
    # ── L-4 (Asst. Manager) — Self-Management + Managing Other ──
    LEVEL_L4: [
        {
            "item_id": "L4Q1",
            "title": "Managing himself/herself",
            "prompt": "How does he/she manage himself?",
            "options": _opts(
                ("A", "Need frequent reminder, priorities change daily.", 1),
                ("B", "Manages own work but struggles under pressure.", 2),
                ("C", "Plan work, meets commitments, handles pressure well.", 4),
                ("D", "Fully delf-driven, anticipates issues before they arise.", 5),
            ),
        },
        {
            "item_id": "L4Q2",
            "title": "Managing others",
            "prompt": "How do you rate him/her towards managing others?",
            "options": _opts(
                ("A", "Avoids correcting team; issues escalate.", 1),
                ("B", "Gives instructions but follow-up is inconsistent.", 2),
                ("C", "Regular follow-up; team usually completes work.", 4),
                ("D", "Team performs well even in leader's absence.", 5),
            ),
        },
        {
            "item_id": "L4Q3",
            "title": "Getting things done",
            "prompt": "How do you rate him/her towards getting things done?",
            "options": _opts(
                ("A", "Tasks often spill over deadlines.", 1),
                ("B", "Deadlines met only with intervention.", 2),
                ("C", "Work gets completed as planned.", 4),
                ("D", "Work completes early bottlenecks resolved proactively.", 5),
            ),
        },
        {
            "item_id": "L4Q4",
            "title": "Communication skill",
            "prompt": "How do you rate him/her communication skill?",
            "options": _opts(
                ("A", "Instructions are unclear or incomplete.", 1),
                ("B", "Communicates but assumptions remain.", 2),
                ("C", "Clear instructions with expected outcomes.", 4),
                ("D", "Communication prevents rework and confusion entirely.", 5),
            ),
        },
        {
            "item_id": "L4Q5",
            "title": "Making team accountable",
            "prompt": "How do you rate him/her towards making team accountable?",
            "options": _opts(
                # Source option A is printed truncated ("Loses accountability under scale").
                # Preserved verbatim — see the reported issue list.
                ("A", "Loses accountability under scale", 1),
                ("B", "Accountability exists only through constant intervention", 2),
                ("C", "Accountability is structured across teams/projects", 4),
                ("D", "Accountable for Teams self-track", 5),
            ),
        },
    ],

    # ── L-5 (Manager) ──
    LEVEL_L5: [
        {
            "item_id": "L5Q1",
            "title": "Managing self and other managers",
            "prompt": "How do you rate him/her towards managing self and other managers?",
            "options": _opts(
                ("A", "Manages self but struggles to manage team.", 1),
                ("B", "Manages team but firefighting is common.", 2),
                ("C", "Balances self, team, and deliverables well.", 4),
                ("D", "Team operates smoothly with minimal escalation.", 5),
            ),
        },
        {
            "item_id": "L5Q2",
            "title": "Getting things done",
            "prompt": "How do you rate him/her towards getting things done?",
            "options": _opts(
                ("A", "Delegates tasks but redoes work later.", 1),
                ("B", "Delegates but follow-up is weak.", 2),
                ("C", "Delegates with clarity and accountability.", 4),
                ("D", "Delegation builds ownership and capability.", 5),
            ),
        },
        {
            # NOTE: in the source this question's heading asks about communication skill
            # while its options describe priority-setting. Preserved exactly as printed.
            "item_id": "L5Q3",
            "title": "Communication skill",
            "prompt": "How do you rate his/her communication skill?",
            "options": _opts(
                ("A", "Everything feels urgent.", 1),
                ("B", "Priorities change frequently.", 2),
                ("C", "Clear priorities aligned to goals.", 4),
                ("D", "Priorities are clear, stable, and well-communicated.", 5),
            ),
        },
        {
            # NOTE: heading asks about team accountability while the options describe
            # communication. Preserved exactly as printed.
            "item_id": "L5Q4",
            "title": "Making the team accountable",
            "prompt": "How do you rate his/her skill towards making the team accountable?",
            "options": _opts(
                ("A", "Causes confusion or mixed messages.", 1),
                ("B", "Adequate but reactive communication.", 2),
                ("C", "Clear, timely, and structured communication.", 4),
                ("D", "Communication aligns teams and prevents issues.", 5),
            ),
        },
        {
            # NOTE: heading asks about setting priorities while the options describe
            # accountability. Preserved exactly as printed.
            "item_id": "L5Q5",
            "title": "Setting priorities",
            "prompt": "How does he set priorities? Rate him on a 1–5 scale.",
            "options": _opts(
                ("A", "Avoids tough conversations.", 1),
                ("B", "Accountability only after escalation.", 2),
                ("C", "Regular review and correction.", 4),
                ("D", "Accountability culture exists within the team.", 5),
            ),
        },
    ],

    # ── L-6 (Senior Manager) — Managers' productivity, measurement, innovation ──
    LEVEL_L6: [
        {
            "item_id": "L6Q1",
            "title": "Making managers / team productive",
            "prompt": "How is he Making Manager or Team Productive? Please rate.",
            "options": _opts(
                ("A", "Productivity depends on individuals.", 1),
                ("B", "Some teams perform, some don't.", 2),
                ("C", "Most teams perform consistently.", 4),
                ("D", "Systems drive productivity across teams.", 5),
            ),
        },
        {
            "item_id": "L6Q2",
            "title": "Self accountability",
            "prompt": "How do you rate him towards his self accountability?",
            "options": _opts(
                ("A", "Deflects responsibility", 1),
                ("B", "Accepts responsibility when pushed", 2),
                ("C", "Owns outcomes openly", 4),
                ("D", "Sets accountability standards for others", 5),
            ),
        },
        {
            "item_id": "L6Q3",
            "title": "Delegation",
            "prompt": "How do you rate him towards delegation, means whether his team is able to complete the delegation?",
            "options": _opts(
                ("A", "Micromanages managers", 1),
                ("B", "Delegates but interferes often", 2),
                ("C", "Delegates with trust and checkpoints", 4),
                ("D", "Builds leaders who independently deliver", 5),
            ),
        },
        {
            "item_id": "L6Q4",
            "title": "Measuring progress and counselling",
            "prompt": "Rate him towards Measuring the Progress of team members and subsequent counselling?",
            "options": _opts(
                ("A", "Reviews are irregular or absent", 1),
                ("B", "Reviews focus on problems only", 2),
                ("C", "Reviews track progress and corrective actions", 4),
                ("D", "Reviews lead to visible performance improvement", 5),
            ),
        },
        {
            "item_id": "L6Q5",
            "title": "Inspiring the team to achieve results",
            "prompt": "Rate him towards the methods he/she use to inspire the team to achieve results?",
            "options": _opts(
                ("A", "Repeats old methods.", 1),
                ("B", "Minor process improvements.", 2),
                ("C", "Improves workflows for efficiency.", 4),
                ("D", "Redesigns jobs to improve outcomes.", 5),
            ),
        },
        {
            "item_id": "L6Q6",
            "title": "Job design / innovation skills",
            "prompt": "Rate him towards designing the job to ensure result achievement (Rate his innovation skills)?",
            "options": _opts(
                ("a", "Job design is task-based and rigid", 1),
                ("b", "Minor improvements, but structure limits results", 2),
                ("c", "Job design supports consistent result delivery", 4),
                ("d", "Job design enables scalable and predictable results", 5),
            ),
        },
    ],

    # ── L7 & ABOVE — Strategy, business acumen, alignment ──
    LEVEL_L7: [
        {
            # NOTE: heading asks about measuring progress/counselling while the options
            # describe team structure. Preserved exactly as printed.
            "item_id": "L7Q1",
            "title": "Measuring progress and counselling",
            "prompt": "Rate him towards measuring the progress of team member and subsequent counselling?",
            "options": _opts(
                ("A", "Team depends heavily on leader", 1),
                ("B", "Some strong individuals, weak structure", 2),
                ("C", "Structured teams with clear roles", 4),
                ("D", "Self-driven leadership teams exist", 5),
            ),
        },
        {
            # NOTE: heading asks about building a strong team while the options describe
            # business impact. Preserved exactly as printed.
            "item_id": "L7Q2",
            "title": "Building a strong team",
            "prompt": "How rate him towards building a strong team?",
            "options": _opts(
                ("A", "Limited understanding of business impact", 1),
                ("B", "Understands own function only", 2),
                ("C", "Understands cross-functional business impact", 4),
                ("D", "Drives decisions based on business outcomes", 5),
            ),
        },
        {
            "item_id": "L7Q3",
            "title": "Business acumen",
            "prompt": "How do you rate his/her business acumen?",
            "options": _opts(
                ("A", "Avoids financial discussions", 1),
                ("B", "Understands budgets but not drivers", 2),
                ("C", "Understands cost, margins, profitability", 4),
                ("D", "Uses finance to drive strategy", 5),
            ),
        },
        {
            # NOTE: heading asks about business finance understanding while the options
            # describe managing scale. Preserved exactly as printed.
            "item_id": "L7Q4",
            "title": "Business finance understanding",
            "prompt": "How do you rate his/her business finance understanding?",
            "options": _opts(
                ("A", "Loses control under scale", 1),
                ("B", "Manages with stress and firefighting", 2),
                ("C", "Structured control across teams/projects", 4),
                ("D", "Scale handled through systems and leaders", 5),
            ),
        },
        {
            # NOTE: heading asks about managing multiple projects while the options
            # describe strategy. Preserved exactly as printed.
            "item_id": "L7Q5",
            "title": "Managing multiple / diversified projects",
            "prompt": "How do you rate him towards managing multiple project/diversified?",
            "options": _opts(
                ("A", "Strategy unclear to teams", 1),
                ("B", "Strategy exists but execution weak", 2),
                ("C", "Strategy understood and mostly executed", 4),
                ("D", "Strategy translates into measurable results", 5),
            ),
        },
        {
            # SEEDED VERBATIM, INCLUDING THE PRINTED SCORE ORDER.
            #
            # The document prints "Goals are aligned and largely executed" at 1 and "Goals
            # are unclear and execution is inconsistent" at 4. Reproduced exactly — option
            # order, letters and scores — and scored that way, per the instruction that the
            # document is the single source of truth and is used as it stands. Not
            # corrected, not flagged, and it holds nothing up.
            "item_id": "L7Q6",
            "title": "Goal alignment and strategy execution",
            "prompt": "How do you rate him towards goal alignment and strategy execution?",
            "options": _opts(
                ("a", "Goals are aligned and largely executed", 1),
                ("b", "Goals are embedded and strategy drives action", 2),
                ("c", "Goals are unclear and execution is inconsistent", 4),
                ("d", "Goals are communicated, execution is uneven", 5),
            ),
        },
    ],
}


# ─────────────────────────────────────────────────────────────
# NO REVIEW REGISTER, BY INSTRUCTION
#
# An earlier build carried a register of the source document's internal inconsistencies
# (titles naming a different parameter than their options measure, L7 Q6's inverted
# option scores, two L7 parameters with no option set, the missing rating midpoint) and
# used it to flag questions on screen and to require an HR + MD sign-off of each level
# before a cycle could be computed.
#
# That is removed. The instruction is that the document/seed is the single source of
# truth and is to be used exactly as it stands: no question or option is flagged, queried
# or held back for confirmation, and no approval is required from HR, MD or anyone else
# before a level is scored. Anything that reads oddly in the seed is intended to be
# scored as printed.
#
# The seed above is unchanged and remains verbatim; what went away is the machinery that
# asked about it. Question text, option wording, option scores and weightages all stay
# editable at runtime through the admin API for whoever wants to change them.
# ─────────────────────────────────────────────────────────────

def rubric_fingerprint(questions: List[dict]) -> str:
    """A stable digest of the rubric a level is actually scoring on.

    Stamped onto each subject when they are enrolled, so a published score can always be
    traced to the exact rubric that produced it even after a later edit.

    Covers exactly the fields that change what a leader is scored on — text, option
    scores and weightage. `order` is excluded: reordering the form changes no score.
    """
    payload = sorted(
        [{
            "item_id": str(q.get("item_id") or ""),
            "title": (q.get("title") or "").strip(),
            "prompt": (q.get("prompt") or "").strip(),
            "weightage": round(float(q.get("weightage") or 0), 2),
            "options": sorted(
                [{"option_id": str(o.get("option_id") or ""),
                  "label": (o.get("label") or "").strip(),
                  "score": float(o.get("score") or 0)}
                 for o in (q.get("options") or [])],
                key=lambda o: o["option_id"]),
        } for q in questions if q.get("active", True) is not False],
        key=lambda q: q["item_id"],
    )
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def seed_rows_for_level(level: str) -> List[dict]:
    """Question-master rows for one level, with weight distributed equally to total 100.

    The remainder is spread over the first questions so the column sums to exactly
    100.00 rather than 99.98 or 100.02 — the validator rejects anything else.
    """
    questions = LEADERSHIP_QUESTION_SEED.get(level) or []
    n = len(questions)
    if not n:
        return []
    base = round(TOTAL_WEIGHTAGE / n, 2)
    weights = [base] * n
    drift = round(TOTAL_WEIGHTAGE - sum(weights), 2)
    steps = int(round(abs(drift) * 100))
    step = 0.01 if drift > 0 else -0.01
    for i in range(steps):
        weights[i % n] = round(weights[i % n] + step, 2)

    rows = []
    for i, q in enumerate(questions):
        rows.append({
            "level": level,
            "item_id": q["item_id"],
            "title": q["title"],
            "prompt": q["prompt"],
            "options": [dict(o) for o in q["options"]],
            "weightage": weights[i],
            "order": i,
            "active": True,
        })
    return rows


def all_seed_rows() -> List[dict]:
    rows = []
    for level in LEVELS:
        rows.extend(seed_rows_for_level(level))
    return rows


# ─────────────────────────────────────────────────────────────
# Request payloads
# ─────────────────────────────────────────────────────────────
def _validate_threshold(v) -> int:
    """Shared by CycleCreate and CycleUpdate.

    CycleUpdate used to declare `min_responses` with no validator at all, so PATCH could set
    any integer a caller liked — including 0 or a negative, which would have shown a score
    computed from nothing. Both paths now run the same check.
    """
    # NB: `int(v or FLOOR)` would quietly turn an explicit 0 into the floor instead of
    # refusing it. The None case belongs to the caller (CycleUpdate), not here.
    n = int(v)
    if n < MIN_RESPONSES_FLOOR:
        raise ValueError(
            f"min_responses cannot be below {MIN_RESPONSES_FLOOR}: a score built from fewer "
            "responses can be traced back to an individual giver, which this module promises "
            "it never will be.")
    if n > RECOMMENDED_PANEL_SIZE:
        raise ValueError(f"min_responses cannot exceed the panel size ({RECOMMENDED_PANEL_SIZE})")
    return n


# Meta's own template categories. UTILITY is the right one for a feedback invitation —
# it is a transactional message the recipient is expected to act on, not marketing — but the
# client owns the choice at approval time, so it is stored rather than assumed.
WA_CATEGORIES: List[str] = ["UTILITY", "MARKETING", "AUTHENTICATION"]

# ─────────────────────────────────────────────────────────────
# Template approval lifecycle.
#
# DRAFT is ours — the template exists here and Meta has never seen it. The other three are
# Meta's verdict, mirrored locally so the screen can answer "where is it up to?" without a
# round trip on every page load.
#
# REJECTED is editable on purpose: a rejected template still OCCUPIES its name on the WABA,
# so the only way to act on a rejection is to correct the one Meta already holds and put it
# back into review. Deleting and recreating gets "Content in this language already exists".
# ─────────────────────────────────────────────────────────────
WA_TPL_DRAFT    = "DRAFT"
WA_TPL_PENDING  = "PENDING"
WA_TPL_APPROVED = "APPROVED"
WA_TPL_REJECTED = "REJECTED"

WA_TPL_STATUSES: List[str] = [WA_TPL_DRAFT, WA_TPL_PENDING, WA_TPL_APPROVED, WA_TPL_REJECTED]
# Only these may be (re)submitted. PENDING is with Meta; APPROVED needs no resubmission.
WA_TPL_EDITABLE = {WA_TPL_DRAFT, WA_TPL_REJECTED}

# The data fields a Leadership template's parameters may map to. Exactly what
# leadership_wa_service builds at send time, so a mapped field always resolves — Leadership's
# own list, deliberately not TPMS's (an invitation has no activity, status or event date).
WA_VARIABLE_FIELDS: List[str] = [
    "giver_name", "subject_name", "link", "company_name", "cycle", "cycle_label",
]


class LeadershipWhatsAppTemplate(BaseModel):
    """Leadership's own WIRING for a company's template — not the template itself.

    The message (name, language, category, header, body, footer, buttons) is authored and
    stored through the composer endpoints, which own the Meta definition. All that is left
    here is what Meta cannot know: which Leadership data fills each placeholder, and whether
    the wiring is switched on.

    Parameter ORDER is the contract — Meta addresses body parameters positionally, so
    `params[0]` fills {{1}}.
    """
    params: List[str] = Field(default_factory=lambda: ["giver_name", "subject_name", "link"])
    active: bool = True

    @field_validator("params")
    @classmethod
    def _known_fields(cls, values):
        for name in values or []:
            if str(name).strip() not in WA_VARIABLE_FIELDS:
                raise ValueError(
                    f"'{name}' is not a Leadership field. Available: "
                    + ", ".join(WA_VARIABLE_FIELDS))
        return [str(v).strip() for v in (values or []) if str(v).strip()]


class CycleCreate(BaseModel):
    company_id: Optional[str] = None
    cycle: Optional[str] = None                 # defaults to the current 2-month window
    degree: str = DEGREE_360
    # Fewest responses before a score may be FROZEN and released. Distinct from
    # min_responses, which is the anonymity floor for showing a number at all.
    quorum: int = DEFAULT_QUORUM
    # Empty = equal across the groups in play. Left empty rather than filled in, so the
    # screen can say "default" instead of showing numbers nobody chose.
    group_weightages: Optional[Dict[str, float]] = None
    # HR's collection window, independent of the cycle's calendar months — which is what
    # makes "extend the window" possible when quorum is not met.
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    # How many responses a subject needs before a score is shown. The document sets no
    # threshold, so this defaults to the anonymity floor rather than to 1 — see
    # MIN_RESPONSES_FLOOR. HR may raise it per cycle, never lower it.
    min_responses: int = MIN_RESPONSES_FLOOR
    notes: Optional[str] = ""

    @field_validator("degree")
    @classmethod
    def _known_degree(cls, v: str) -> str:
        d = str(v or "").strip()
        if d not in DEGREES:
            raise ValueError(f"degree must be one of {', '.join(DEGREES)}")
        return d

    @model_validator(mode="after")
    def _fits_the_panel(self):
        """Both thresholds count REPLIES, so neither can exceed the panel the degree
        collects from. A field validator cannot see `degree`, which is how a 180 cycle came
        to be creatable needing eight responses from four givers.

        An explicitly chosen value over the cap is refused. The DEFAULT quorum is clamped
        instead: DEFAULT_QUORUM is 5, which already exceeds a 180 panel, so refusing it
        would make every 180 cycle impossible to create.
        """
        panel = panel_size_for(self.degree)
        if self.min_responses > panel:
            raise ValueError(
                f"A {self.degree} degree cycle collects from {panel} givers "
                f"({RECOMMENDED_PER_RELATION} per relation), so min_responses cannot be "
                f"{self.min_responses}.")
        if self.quorum > panel:
            if "quorum" in self.model_fields_set:
                raise ValueError(
                    f"A {self.degree} degree cycle collects from {panel} givers, so quorum "
                    f"cannot be {self.quorum}.")
            self.quorum = panel
        return self

    @field_validator("min_responses")
    @classmethod
    def _sane_threshold(cls, v: int) -> int:
        return _validate_threshold(v)


class CycleUpdate(BaseModel):
    degree: Optional[str] = None
    min_responses: Optional[int] = None
    quorum: Optional[int] = None
    group_weightages: Optional[Dict[str, float]] = None
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("group_weightages")
    @classmethod
    def _weights(cls, v):
        return _validate_group_weightages(v)

    @field_validator("quorum")
    @classmethod
    def _quorum(cls, v):
        if v is None:
            return None
        if int(v) < MIN_RESPONSES_FLOOR:
            raise ValueError(
                f"quorum cannot be below the anonymity floor of {MIN_RESPONSES_FLOOR}")
        return int(v)

    @field_validator("min_responses")
    @classmethod
    def _sane_threshold(cls, v):
        return None if v is None else _validate_threshold(v)

    @field_validator("degree")
    @classmethod
    def _known_degree(cls, v):
        if v is None:
            return v
        if str(v) not in DEGREES:
            raise ValueError(f"degree must be one of {', '.join(DEGREES)}")
        return str(v)

    @field_validator("status")
    @classmethod
    def _known_status(cls, v):
        if v is None:
            return v
        if str(v) not in CYCLE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(CYCLE_STATUSES)}")
        return str(v)


class SubjectCreate(BaseModel):
    """Enrol one leader into a cycle at a level."""
    subject_id: str
    level: str
    # A leader with no direct reports cannot be a 360° subject.
    mode_override: Optional[str] = None

    @field_validator("subject_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("subject_id is required")
        return s

    @field_validator("level")
    @classmethod
    def _known_level(cls, v: str) -> str:
        lv = str(v or "").strip().upper()
        if lv not in LEVELS:
            raise ValueError(f"level must be one of {', '.join(LEVELS)}")
        return lv


class GiverItem(BaseModel):
    giver_id: str
    relation: str

    @field_validator("giver_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("giver_id is required")
        return s

    @field_validator("relation")
    @classmethod
    def _known_relation(cls, v: str) -> str:
        r = str(v or "").strip().lower()
        if r not in RELATIONS:
            raise ValueError(f"relation must be one of {', '.join(RELATIONS)}")
        return r


class GiverAssignment(BaseModel):
    """The feedback panel for one subject. Identified by HR and known only to HR."""
    givers: List[GiverItem]

    @field_validator("givers")
    @classmethod
    def _no_duplicates(cls, items: List[GiverItem]) -> List[GiverItem]:
        ids = [i.giver_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("The same person cannot be added to a panel twice")
        return items


class AnswerItem(BaseModel):
    question_id: str
    option_id: str

    @field_validator("question_id", "option_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("question_id and option_id are required")
        return s


class ResponseSubmit(BaseModel):
    answers: List[AnswerItem]

    @field_validator("answers")
    @classmethod
    def _non_empty(cls, v: List[AnswerItem]) -> List[AnswerItem]:
        if not v:
            raise ValueError("At least one answer is required")
        return v


class QuestionUpdate(BaseModel):
    """Reword a question or restate its options. `item_id` and `level` are immutable —
    they key the stored responses."""
    title: Optional[str] = None
    prompt: Optional[str] = None
    options: Optional[List[dict]] = None
    active: Optional[bool] = None

    @field_validator("options")
    @classmethod
    def _valid_options(cls, v):
        if v is None:
            return v
        if not v:
            raise ValueError("A question needs at least one option")
        seen = set()
        for o in v:
            oid = str((o or {}).get("option_id") or "").strip()
            if not oid:
                raise ValueError("Every option needs an option_id")
            if oid in seen:
                raise ValueError(f"Duplicate option_id '{oid}'")
            seen.add(oid)
            try:
                score = float((o or {}).get("score"))
            except (TypeError, ValueError):
                raise ValueError(f"Option '{oid}' needs a numeric score")
            if score < SCALE_MIN or score > SCALE_MAX:
                raise ValueError(f"Option '{oid}' score must be between {SCALE_MIN} and {SCALE_MAX}")
        return v


class WeightageItem(BaseModel):
    item_id: str
    weightage: float

    @field_validator("weightage")
    @classmethod
    def _in_range(cls, v: float) -> float:
        w = round(float(v), 2)
        if w < 0 or w > TOTAL_WEIGHTAGE:
            raise ValueError(f"weightage must be between 0 and {TOTAL_WEIGHTAGE:g}")
        return w


class WeightageUpdate(BaseModel):
    """Set a level's weightage column. It must total exactly 100 — a partially
    configured level would otherwise produce a plausible-looking wrong score."""
    level: str
    weightages: List[WeightageItem]

    @field_validator("level")
    @classmethod
    def _known_level(cls, v: str) -> str:
        lv = str(v or "").strip().upper()
        if lv not in LEVELS:
            raise ValueError(f"level must be one of {', '.join(LEVELS)}")
        return lv

    @field_validator("weightages")
    @classmethod
    def _totals_100(cls, items: List[WeightageItem]) -> List[WeightageItem]:
        if not items:
            raise ValueError("No weightages supplied")
        ids = [i.item_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each question may appear only once")
        total = round(sum(i.weightage for i in items), 2)
        if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
            raise ValueError(
                f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
            )
        return items


class ActionItem(BaseModel):
    text: str
    owner: Optional[str] = ""
    due_date: Optional[datetime] = None
    done: bool = False


class DiscussionCreate(BaseModel):
    """The RRO conversation, logged by the reporting manager.

    `parameters_discussed` holds item ids. "Agar zarurat ho toh parameter-wise discuss
    karo" — recording WHICH parameters were covered is what makes the next cycle's
    conversation able to start where this one finished.
    """
    notes: Optional[str] = ""
    parameters_discussed: Optional[List[str]] = None
    action_items: Optional[List[ActionItem]] = None
    discussed_at: Optional[datetime] = None


class DiscussionAck(BaseModel):
    comment: Optional[str] = ""


class BriefingCreate(BaseModel):
    user_id: str
    type: str = "pre"
    conducted_by: Optional[str] = ""
    notes: Optional[str] = ""

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        t = str(v or "").strip().lower()
        if t not in ("pre", "post"):
            raise ValueError("type must be 'pre' or 'post'")
        return t


class SubjectMode(BaseModel):
    """Put one leader on a different degree from the rest of their cycle."""
    mode_override: Optional[str] = None

    @field_validator("mode_override")
    @classmethod
    def _known(cls, v):
        if v in (None, ""):
            return None
        d = str(v).strip()
        if d not in DEGREES:
            raise ValueError(f"mode_override must be one of {', '.join(DEGREES)}")
        return d


def _validate_group_weightages(v):
    """Group weights must name known relations and be non-negative.

    They are NOT required to total 100: the scorer renormalises over whichever groups
    actually responded, so a fixed total would be a false promise the moment one group
    stays silent.
    """
    if v in (None, {}):
        return v
    unknown = [k for k in v if k not in RELATIONS]
    if unknown:
        raise ValueError(f"Unknown relation(s): {', '.join(unknown)}")
    if any(float(x) < 0 for x in v.values()):
        raise ValueError("A group weightage cannot be negative")
    if sum(float(x) for x in v.values()) <= 0:
        raise ValueError("At least one group must carry weight")
    return {k: float(x) for k, x in v.items()}


# ─────────────────────────────────────────────────────────────
# Index specification — consumed by app/db/mongodb.py at startup.
# Every collection here is new, so no existing index is touched.
# ─────────────────────────────────────────────────────────────
LEADERSHIP_INDEXES = [
    # THE invitation, shared by every company. The unique index on `scope` is what keeps
    # "exactly one row" true even if two administrators save at the same moment — both
    # upserts then resolve to the same document instead of racing a second one into being.
    (COLL_LS_WA_TEMPLATE, [("scope", 1)], {"unique": True, "name": "uniq_wa_shared"}),
    # Legacy per-company templates. Kept indexed because they are still read as a fallback
    # while the shared template waits on Meta; nothing writes here any more.
    (COLL_LS_WA_TEMPLATES, [("company_id", 1)], {"unique": True, "name": "uniq_wa_company"}),
    # And a Meta template name belongs to exactly one company. Those names are global to the
    # WhatsApp Business Account, so this is the backstop behind the check in
    # save_authored_template. PARTIAL rather than sparse: a draft saved without a name
    # stores "" rather than omitting the field, and a plain unique index would then permit
    # only one unnamed draft across every company.
    (COLL_LS_WA_TEMPLATES, [("meta_template_name", 1)],
     {"unique": True, "name": "uniq_wa_meta_name",
      "partialFilterExpression": {"meta_template_name": {"$gt": ""}}}),
    # The delivery log is read per cycle and per assignment, and written once per attempt.
    (COLL_LS_WA_LOG, [("company_id", 1), ("cycle", 1)], {"name": "wa_by_company_cycle"}),
    (COLL_LS_WA_LOG, [("assignment_id", 1)], {"name": "wa_by_assignment"}),
    (COLL_LS_WA_LOG, [("message_id", 1)], {"name": "wa_by_message"}),
    (COLL_LS_DOCUMENTS, [("company_id", 1), ("cycle", 1)], {"name": "docs_by_company_cycle"}),
    (COLL_LS_CYCLES,      [("company_id", 1), ("cycle", 1)],
     {"unique": True, "name": "uniq_company_cycle"}),
    (COLL_LS_SUBJECTS,    [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"unique": True, "name": "uniq_company_cycle_subject"}),
    (COLL_LS_SUBJECTS,    [("company_id", 1), ("cycle", 1)],
     {"name": "by_company_cycle"}),
    (COLL_LS_ASSIGNMENTS, [("company_id", 1), ("cycle", 1), ("subject_id", 1), ("giver_id", 1)],
     {"unique": True, "name": "uniq_cycle_subject_giver"}),
    (COLL_LS_ASSIGNMENTS, [("token_hash", 1)],
     {"unique": True, "sparse": True, "name": "uniq_token_hash"}),
    # Legacy plaintext tokens issued before hashing. Sparse, so rows without one are
    # ignored; kept only so links already in someone's inbox keep working.
    (COLL_LS_ASSIGNMENTS, [("token", 1)],
     {"unique": True, "sparse": True, "name": "uniq_token"}),
    # Retired credentials, so a giver resubmitting their own spent link is answered
    # "already submitted" without a collection scan. Sparse — only submitted rows carry
    # one — and NOT unique: uniqueness is already guaranteed by the live token index that
    # issued the value, and a write failure here would block a legitimate submission.
    (COLL_LS_ASSIGNMENTS, [("spent_token_hash", 1)],
     {"sparse": True, "name": "by_spent_token_hash"}),
    (COLL_LS_ASSIGNMENTS, [("company_id", 1), ("cycle", 1)],
     {"name": "by_company_cycle"}),
    # NOT unique, and NOT keyed on any giver. A response carries no rater identity, so
    # there is nothing per-person to be unique on; duplicate submission is prevented on
    # the assignment row instead (see leadership_link_service.claim_for_submission).
    (COLL_LS_RESPONSES,   [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"name": "by_subject"}),
    (COLL_LS_RESPONSES,   [("company_id", 1), ("cycle", 1), ("subject_id", 1), ("relation", 1)],
     {"name": "by_subject_relation"}),
    (COLL_LS_QUESTIONS,   [("level", 1), ("item_id", 1)],
     {"name": "by_level_item"}),
    (COLL_LS_QUESTIONS,   [("level", 1), ("order", 1)],
     {"name": "by_level_order"}),
    (COLL_LS_SCORES,      [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"unique": True, "name": "uniq_company_cycle_subject"}),
    (COLL_LS_DISCUSSIONS, [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"unique": True, "name": "uniq_company_cycle_subject"}),
    (COLL_LS_BRIEFINGS,   [("company_id", 1), ("cycle", 1), ("user_id", 1), ("type", 1)],
     {"unique": True, "name": "uniq_company_cycle_user_type"}),
    # Company-scoped question master (see get_questions). Rows with company_id=None are the
    # shared default; a company gets its own copy the first time it edits one.
    (COLL_LS_QUESTIONS,   [("company_id", 1), ("level", 1), ("item_id", 1)],
     {"name": "by_company_level_item"}),
]

# Indexes an EARLIER build created that are now wrong, dropped at startup if present.
#
# `uniq_cycle_subject_giver` on responses was unique across (company, cycle, subject,
# giver_id). Responses no longer store a giver, so every row would key on the same
# (company, cycle, subject, null) and the SECOND response for a leader would be rejected
# as a duplicate. Dropping it is required for correctness; it removes an index, never a
# document.
LEADERSHIP_OBSOLETE_INDEXES = [
    (COLL_LS_RESPONSES, "uniq_cycle_subject_giver"),
    (COLL_LS_QUESTIONS, "uniq_level_item"),   # replaced by the company-scoped index
    # `uniq_token` was unique but NOT sparse, from when every assignment stored a raw
    # token. Assignments now store only `token_hash`, and a submitted one has even that
    # unset — so `token` is absent on every new row. A non-sparse unique index treats a
    # missing field as null, which means the FIRST new assignment indexes null and the
    # SECOND is rejected as a duplicate key. It is dropped and recreated sparse below.
    #
    # MongoDB will not change an existing index's options in place: createIndex with the
    # same name and different options raises IndexKeySpecsConflict (code 86) and the new
    # options are silently never applied. Dropping first is the only way.
    (COLL_LS_ASSIGNMENTS, "uniq_token"),
]
