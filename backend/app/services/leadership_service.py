"""
TPMS ▸ Leadership Score — cycles, subjects, question master and scoring.

    "All leaders should get the score as per parameters they have."

SCORING
-------
For a subject with R submitted responses:

    question mean   avg(q) = mean over responses of the chosen option's score   -> 1..5
    achievement     ach(q) = avg(q) / 5 * 100                                   -> 0..100
    weighted        w(q)   = ach(q) * weightage(q) / 100
    Leadership Score       = sum of w(q)                                        -> 0..100

A question nobody answered is excluded from the total and its weightage reported as
unearned, rather than counted as zero — a giver's omission must not read as a leader's
failure. Weightages are read from the question master on every calculation, so an HR/MD
change takes effect on the next read with no recompute step.

CONFIDENTIALITY
---------------
    "Ye feedback completely confidential hoga."
    "HR should identify feedback givers and it should be only known to HR."

`giver_id` is stored on responses for authorization and duplicate prevention. It is never
returned to a leader or a reporting manager: every score payload is built by
`subject_score()`, which aggregates and never carries an identity, an individual response,
or a per-giver rating. The relation breakdown is computed for HR only and suppresses any
group with fewer than MIN_GROUP_FOR_BREAKDOWN responses, since a group of one would name
the person who filled it.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS, COLL_LS_BRIEFINGS, COLL_LS_CYCLES, COLL_LS_DISCUSSIONS,
    COLL_LS_QUESTIONS, COLL_LS_RESPONSES, COLL_LS_SCORES, COLL_LS_SUBJECTS,
    CYCLE_CLOSED, CYCLE_COLLECTING, CYCLE_COMPUTED, CYCLE_DRAFT, CYCLE_OPEN,
    CYCLE_PUBLISHED, CYCLE_STATUSES, CYCLE_TRANSITIONS, can_transition,
    DEFAULT_QUORUM, DEGREE_180, DEGREE_360, DEGREE_RELATIONS,
    LINK_SUBMITTED, WA_FAILED, WA_SENT, WA_UNREACHABLE,
    LEVEL_L4, LEVELS, LEVEL_LABELS, LEVEL_THEMES, MIN_RESPONSES_FLOOR,
    panel_size_for,
    RECOMMENDED_PER_RELATION, REL_DIRECT_REPORT, REL_OTHER_DEPT, REL_PEER,
    REL_SUPERIOR, RELATIONS, RELATION_LABELS,
    SCALE_MAX, TOTAL_WEIGHTAGE, WEIGHTAGE_EPSILON,
    all_seed_rows, cycle_label, cycle_period, current_cycle,
    rubric_fingerprint, seed_rows_for_level,
)

logger = logging.getLogger(__name__)

# A relation group smaller than this is folded into the total but not broken out, so a
# single response can never be attributed to the one person who gave it.
MIN_GROUP_FOR_BREAKDOWN = 2

PERSON_COLLECTIONS = ("staff", "learners")


def _display_name(u: dict) -> str:
    return (u.get("full_name")
            or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
            or u.get("email") or "Unknown")


def _round(v, nd=2):
    return None if v is None else round(float(v), nd)


# ─────────────────────────────────────────────────────────────
# Question master
# ─────────────────────────────────────────────────────────────
async def seed_questions_if_empty() -> int:
    """Insert-only seed of the level question master. Skipped entirely once any row
    exists, so an admin's edits are never overwritten."""
    col = get_collection(COLL_LS_QUESTIONS)
    if await col.count_documents({}) > 0:
        return 0
    rows = all_seed_rows()
    if not rows:
        return 0
    now = datetime.utcnow()
    for r in rows:
        # None = the shared default every company reads until it edits a level of its own.
        r["company_id"] = None
        r["created_at"] = now
        r["updated_at"] = now
    try:
        await col.insert_many(rows, ordered=False)
    except Exception as e:
        logger.warning("Leadership question seed: %s", e)
        return 0
    logger.info("Seeded %s leadership questions", len(rows))
    return len(rows)


async def get_questions(level: Optional[str] = None, include_inactive: bool = False,
                        company_id: Optional[str] = None) -> List[dict]:
    """The question master a company is actually scored on.

    COMPANY SCOPING (copy-on-write)
    -------------------------------
    Rows with `company_id = None` are the shared default seeded from the HR document.
    A company that edits a level gets its OWN copy of that level's rows first, and from
    then on reads and writes only its copy.

    Before this, one master served every client: an admin retitling a question or moving a
    weightage for one company silently rewrote the rubric — and therefore the scores — for
    every other company on the platform. Copy-on-write fixes that without migrating
    anything: existing rows keep `company_id` absent and go on serving as the default.

    `company_id=None` here means "the shared default", which is what the internal template
    editor asks for. It is not a wildcard.
    """
    await seed_questions_if_empty()
    col = get_collection(COLL_LS_QUESTIONS)

    base: dict = {}
    if level:
        base["level"] = str(level).upper()
    if not include_inactive:
        base["active"] = {"$ne": False}

    docs: List[dict] = []
    if company_id:
        docs = await col.find({**base, "company_id": str(company_id)}).to_list(500)
        if not docs:
            # No override for this company (or this level) — serve the shared default.
            docs = await col.find({**base, "company_id": None}).to_list(500)
            if not docs:
                docs = [d for d in await col.find(base).to_list(500)
                        if not d.get("company_id")]
    else:
        docs = await col.find({**base, "company_id": None}).to_list(500)
        if not docs:
            docs = [d for d in await col.find(base).to_list(500) if not d.get("company_id")]

    docs.sort(key=lambda d: (str(d.get("level") or ""), int(d.get("order") or 0)))

    # Rows are returned exactly as configured. Nothing is flagged, compared against the
    # seed or held back for confirmation — the document is used as it stands.
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def fork_level_for_company(company_id: str, level: str) -> int:
    """Give one company its own copy of a level, so editing it cannot touch anyone else.

    Insert-only and idempotent: if the company already owns the level, nothing happens.
    The shared default rows are never modified, only read.
    """
    level = str(level).upper()
    col = get_collection(COLL_LS_QUESTIONS)
    if await col.count_documents({"company_id": str(company_id), "level": level}):
        return 0

    defaults = [d for d in await col.find({"level": level}).to_list(200)
                if not d.get("company_id")]
    if not defaults:
        defaults = seed_rows_for_level(level)

    now = datetime.utcnow()
    copies = []
    for d in defaults:
        row = {k: v for k, v in d.items() if k != "_id"}
        row["company_id"] = str(company_id)
        row["forked_from_default_at"] = now
        row["created_at"] = now
        row["updated_at"] = now
        copies.append(row)
    if copies:
        await col.insert_many(copies, ordered=False)
    logger.info("Leadership %s forked to company %s (%d questions)",
                level, company_id, len(copies))
    return len(copies)


async def restore_level_questions(level: str, company_id: Optional[str] = None) -> dict:
    """Re-insert any question from the document that is missing from a level.

    Insert-only: existing rows, including their edited text and weightages, are left
    exactly as they are. Scoped to the company's own copy when it has one.
    """
    level = str(level).upper()
    col = get_collection(COLL_LS_QUESTIONS)
    scope = {"level": level, "company_id": str(company_id) if company_id else None}

    rows = await col.find(scope).to_list(200)
    if not rows and company_id:
        # The company reads the shared default, so restoring belongs there — forking a
        # level just to add a missing question would silently detach it from the default.
        scope = {"level": level, "company_id": None}
        rows = await col.find(scope).to_list(200)

    present = {d.get("item_id") for d in rows}
    missing = [r for r in seed_rows_for_level(level) if r["item_id"] not in present]
    if missing:
        now = datetime.utcnow()
        for r in missing:
            r["company_id"] = scope["company_id"]
            r["created_at"] = now
            r["updated_at"] = now
        await col.insert_many(missing, ordered=False)
    return {"level": level, "restored": len(missing)}


async def update_question(question_id: str, updates: dict,
                          company_id: Optional[str] = None) -> bool:
    """Reword a question or restate its options — for ONE company.

    If the row being edited is a shared default and a company is editing it, that
    company's copy of the level is created first and the edit lands on the copy. The
    default is never modified, so no other client's rubric — or scores — move because of
    an edit made for someone else.
    """
    fields = {k: v for k, v in updates.items() if v is not None}
    if not fields:
        return False

    col = get_collection(COLL_LS_QUESTIONS)
    row = await col.find_one({"_id": ObjectId(str(question_id))})
    if not row:
        return False

    fields["updated_at"] = datetime.utcnow()

    if company_id and not row.get("company_id"):
        await fork_level_for_company(company_id, row.get("level"))
        res = await col.update_one(
            {"company_id": str(company_id), "level": row.get("level"),
             "item_id": row.get("item_id")},
            {"$set": fields})
        return res.matched_count > 0

    res = await col.update_one({"_id": ObjectId(str(question_id))}, {"$set": fields})
    return res.matched_count > 0


async def set_weightages(level: str, weightages: Dict[str, float],
                         company_id: Optional[str] = None) -> dict:
    """Write a level's weightage column for one company.

    Totalling exactly 100 is validated by the payload model and re-checked here so a
    direct service call cannot bypass it — a half-configured level produces a
    plausible-looking wrong score rather than an obvious error.
    """
    level = str(level).upper()
    total = round(sum(weightages.values()), 2)
    if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
        raise ValueError(
            f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)")

    col = get_collection(COLL_LS_QUESTIONS)
    if company_id:
        await fork_level_for_company(company_id, level)
    scope = {"level": level, "company_id": str(company_id) if company_id else None}

    known = {d.get("item_id") for d in await col.find(scope).to_list(200)}
    unknown = [i for i in weightages if i not in known]
    if unknown:
        raise ValueError(f"Unknown question(s) for {level}: {', '.join(unknown)}")

    now = datetime.utcnow()
    for item_id, w in weightages.items():
        await col.update_one({**scope, "item_id": item_id},
                             {"$set": {"weightage": round(float(w), 2), "updated_at": now}})
    return {"level": level, "updated": len(weightages), "total": total}


async def weightage_summary(company_id: Optional[str] = None) -> List[dict]:
    """Per-level totals, so the admin screen can flag a level that does not add to 100."""
    await seed_questions_if_empty()
    out = []
    for level in LEVELS:
        rows = await get_questions(level, company_id=company_id)
        total = round(sum(float(r.get("weightage") or 0) for r in rows), 2)
        out.append({
            "level": level,
            "label": LEVEL_LABELS.get(level, level),
            "theme": LEVEL_THEMES.get(level, ""),
            "questions": len(rows),
            "total_weightage": total,
            "is_valid": abs(total - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
            # True once this company holds its own copy of the level, so the screen can say
            # whether an edit here affects only them.
            "company_owned": bool(rows and rows[0].get("company_id")),
        })
    return out


# ─────────────────────────────────────────────────────────────
# Cycles
# ─────────────────────────────────────────────────────────────
async def list_cycles(company_id: str, limit: int = 50) -> List[dict]:
    from app.services.leadership_link_service import window_is_closed

    docs = await get_collection(COLL_LS_CYCLES).find(
        {"company_id": str(company_id)}).sort("cycle", -1).to_list(limit)
    out = []
    for d in docs:
        await sync_cycle_status(d)
        d["_id"] = str(d["_id"])
        d["label"] = cycle_label(d.get("cycle") or "")
        d["subject_count"] = await get_collection(COLL_LS_SUBJECTS).count_documents(
            {"company_id": str(company_id), "cycle": d.get("cycle")})
        d["response_count"] = await get_collection(COLL_LS_RESPONSES).count_documents(
            {"company_id": str(company_id), "cycle": d.get("cycle")})
        # Additive: lets the UI disable dispatch without re-deriving the window in JS, and
        # mirrors exactly what assert_dispatchable enforces server-side — including HR's
        # own Close date, so the button greys out on the date they set rather than at the
        # end of the calendar month.
        d["expired"] = window_is_closed(d)
        d["can_dispatch"] = d.get("status") != CYCLE_CLOSED and not d["expired"]
        # Opening is gated on the set-up before it (enrol -> panel -> mail), so the button
        # can say why rather than failing on click. Computed for DRAFTS only: that is the
        # only status the gate applies to, and it costs two queries per cycle.
        if d.get("status") == CYCLE_DRAFT:
            readiness = await open_readiness(company_id, d.get("cycle") or "")
            d["open_readiness"] = readiness
            d["can_open"] = readiness["ready"]
            d["open_blocked_reason"] = readiness["reason"]
        else:
            d["can_open"] = True
            d["open_blocked_reason"] = ""
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────────
# Status from the clock
#
# The collection window owns draft/open/closed. HR owns computed/published. Nothing owns
# both, which is what stops the two disagreeing.
# ─────────────────────────────────────────────────────────────
# Reached by a decision, not by a date. A cycle here has had its scores frozen and possibly
# shown to leaders, so no clock may move it — only HR, and only forward.
CYCLE_MANUAL = (CYCLE_COMPUTED, CYCLE_PUBLISHED)


def validate_window(opens, closes, cycle: str = "") -> None:
    """Refuse a window that could never be open.

    Checked on the SERVER because the dates now decide the cycle's status, when its links
    expire and what the invitation quotes — a window with the close before the open would
    take a cycle from draft straight to closed, collecting nothing, and the two dialogs
    that guard it in the UI are not the only way in.
    """
    if not opens or not closes:
        return
    a = opens if getattr(opens, "tzinfo", None) else opens.replace(tzinfo=timezone.utc)
    b = closes if getattr(closes, "tzinfo", None) else closes.replace(tzinfo=timezone.utc)
    if b <= a:
        raise ValueError(
            (f"{cycle_label(cycle)}: " if cycle else "")
            + "the close date must be after the open date, or the feedback window would "
              "never be open.")


def derived_status(cyc: dict, now=None) -> str:
    """What this cycle's status should be right now.

    `computed` and `published` are returned untouched: a published score has been read by
    the leader it describes, and a window closing afterwards must not reopen that. Every
    other cycle takes its status from the window — which is HR's Open/Close dates when they
    set them and the cycle's calendar months when they did not.
    """
    from app.services.leadership_link_service import (
        WINDOW_CLOSED, WINDOW_PENDING, window_state,
    )
    stored = str((cyc or {}).get("status") or CYCLE_DRAFT)
    if stored in CYCLE_MANUAL:
        return stored
    state = window_state(cyc or {}, now)
    if state == WINDOW_PENDING:
        return CYCLE_DRAFT
    return CYCLE_CLOSED if state == WINDOW_CLOSED else CYCLE_OPEN


async def sync_cycle_status(cyc: Optional[dict], now=None) -> Optional[dict]:
    """Bring one cycle's STORED status in line with the clock, and return it.

    The write matters: `chase_non_submitters`, `notify_window_closing` and the quorum and
    RRO chasers all query Mongo by status, so a status that lived only in Python would leave
    them acting on a stale one. Written only when it actually changes, so a read of an
    unchanged cycle costs nothing.

    `closed_at` is stamped the first time a cycle closes so the history still records when,
    exactly as the manual Close used to.
    """
    if not cyc:
        return cyc
    previous = str(cyc.get("status") or CYCLE_DRAFT)
    target = derived_status(cyc, now)
    if target == previous:
        return cyc

    updates = {"status": target, "updated_at": datetime.utcnow()}
    if target == CYCLE_CLOSED and not cyc.get("closed_at"):
        updates["closed_at"] = datetime.utcnow()

    col = get_collection(COLL_LS_CYCLES)
    # The PREVIOUS status is part of the filter, so this is a compare-and-set: a request
    # and the nightly sweep landing on the same cycle at the same moment cannot both apply
    # the transition, and `closed_at` can therefore only ever be stamped once. The loser
    # matches nothing and adopts the winner's write rather than repeating it.
    res = await col.update_one(
        {"company_id": str(cyc.get("company_id")), "cycle": str(cyc.get("cycle")),
         "status": previous},
        {"$set": updates})

    if getattr(res, "matched_count", 0):
        logger.info("Leadership cycle %s/%s moved %s -> %s by its window",
                    cyc.get("company_id"), cyc.get("cycle"), previous, target)
        cyc.update(updates)
        return cyc

    # Somebody else got there first. Read back what they wrote so this caller returns the
    # cycle as it actually stands rather than as it hoped to leave it.
    fresh = await col.find_one(
        {"company_id": str(cyc.get("company_id")), "cycle": str(cyc.get("cycle"))})
    if fresh:
        for key in ("status", "updated_at", "closed_at"):
            if key in fresh:
                cyc[key] = fresh[key]
    return cyc


async def sync_all_cycle_statuses(now=None) -> dict:
    """Reconcile every cycle that a clock could have moved.

    Runs before the nightly jobs. Without it a cycle nobody opened in the UI would sit at
    its old status until somebody did, and the reminder ladder would skip it on the very
    day it opened. Cycles already computed or published are not fetched at all.
    """
    # Streamed rather than collected: `to_list(2000)` silently stopped reconciling at the
    # 2000th cycle, and a cycle the sweep skips is invisible to every status-driven job
    # below it. The cursor walks the whole collection in batches instead, so the ceiling is
    # gone without holding every cycle in memory at once.
    cursor = get_collection(COLL_LS_CYCLES).find(
        {"status": {"$nin": list(CYCLE_MANUAL)}}).batch_size(200)
    checked = moved = 0
    async for cyc in cursor:
        checked += 1
        before = str(cyc.get("status") or CYCLE_DRAFT)
        await sync_cycle_status(cyc, now)
        if str(cyc.get("status")) != before:
            moved += 1
    return {"checked": checked, "moved": moved}


async def get_cycle(company_id: str, cycle: str) -> Optional[dict]:
    doc = await get_collection(COLL_LS_CYCLES).find_one(
        {"company_id": str(company_id), "cycle": str(cycle)})
    if doc:
        # Every read reconciles, so no caller can act on a status the clock has passed.
        await sync_cycle_status(doc)
        doc["_id"] = str(doc["_id"])
        doc["label"] = cycle_label(doc.get("cycle") or "")
    return doc


async def assert_dispatchable(company_id: str, cycle: str) -> dict:
    """Raise unless invitations may still be sent for this cycle.

    Two independent reasons to refuse, both server-side so a stale browser tab or a direct
    API call cannot bypass them:

      • the cycle is CLOSED — its scores are frozen, so collecting more feedback would
        change nothing and would invite people to a form that no longer counts;
      • the collection WINDOW has shut — every link dies with the window, so the message
        would deliver a URL that answers 410 the moment it is clicked.

    The window is HR's configured Close date when they set one, and the cycle's calendar
    months when they did not. It is the same test the giver's form applies, so an
    invitation can never be sent to a form that would refuse it.

    Sending BEFORE the Open date is deliberately allowed: inviting people ahead of a window
    is normal, and the form tells whoever arrives early exactly when to come back.

    Returns the cycle document, so callers do not fetch it twice.
    """
    from app.services.leadership_link_service import survey_window, window_is_closed

    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("This cycle does not exist")
    # `computed` and `published` refuse alongside `closed`. They are what a closed cycle
    # becomes, so a cycle that has moved past collection must not be reachable by a send —
    # and a published one has already been read by the leader it scores.
    if cyc.get("status") in (CYCLE_CLOSED, CYCLE_COMPUTED, CYCLE_PUBLISHED):
        raise ValueError(
            f"{cycle_label(cycle)} is {cyc.get('status')}. Its scores are final, so "
            "invitations and reminders can no longer be sent.")
    if window_is_closed(cyc):
        closes = survey_window(cyc)[1]
        raise ValueError(
            f"The {cycle_label(cycle)} feedback window closed on "
            f"{closes.strftime('%d %b %Y, %H:%M UTC') if closes else 'its closing date'}. "
            "Feedback links have expired, so nothing further can be sent.")
    return cyc



def _name_list(rows: List[dict], limit: int = 4) -> str:
    """'Asha, Bilal, Chen and 2 more' — for an error a human reads."""
    names = [str(r.get("subject_name") or r.get("subject_id") or "") for r in rows]
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


# Both mean "did not arrive", but they are fixed in different places — a missing number on
# a user record, versus Meta refusing the message. open_readiness only needs to know the
# invitation is still outstanding; the tracking screen is where they are told apart.
FAILED_STATES = (WA_FAILED, WA_UNREACHABLE)


def _delivery_status(row: dict) -> str:
    """Delivery status of one invitation, tolerating rows from the email era."""
    return row.get("wa_status") or row.get("email_status") or ""


async def open_readiness(company_id: str, cycle: str) -> dict:
    """Whether a draft cycle has finished the set-up that has to precede collection.

    The module's order of work is Create -> enrol the leaders -> mail their panels -> Open.
    Enrolment and dispatch each live on the Leaders screen, neither of them visible from the
    Cycles page, so nothing stopped a cycle being opened with nobody enrolled or with every
    invitation still sitting unmailed in the database. Such a cycle reads as collecting while
    no form exists that anyone could fill.

    Reported as structure rather than a bare boolean, so the button and the refusal can both
    name WHO is missing instead of only saying no.

    A submitted link counts as delivered whatever its mail row says — the giver evidently
    received it. Only pending and failed rows hold a cycle back, and each has a remedy on the
    Leaders screen: resend it, or drop that giver and pick another.
    """
    subjects = await get_collection(COLL_LS_SUBJECTS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    rows = await get_collection(COLL_LS_ASSIGNMENTS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(2000)
    panels: Dict[str, List[dict]] = {}
    for r in rows:
        panels.setdefault(str(r.get("subject_id")), []).append(r)

    no_panel: List[dict] = []
    unmailed: List[dict] = []
    for s in subjects:
        sid = str(s.get("subject_id"))
        head = {"subject_id": sid, "subject_name": s.get("subject_name") or sid}
        panel = panels.get(sid) or []
        if not panel:
            no_panel.append(head)
            continue
        waiting = [r for r in panel
                   if r.get("status") != LINK_SUBMITTED
                   and _delivery_status(r) != WA_SENT]
        if waiting:
            unmailed.append({
                **head,
                "panel_size": len(panel),
                "failed": sum(1 for r in waiting if _delivery_status(r) in FAILED_STATES),
                "pending": sum(1 for r in waiting if _delivery_status(r) not in FAILED_STATES),
            })

    if not subjects:
        reason = ("no leaders are enrolled in it yet. Enrol at least one on the Leaders "
                  "screen first.")
    elif no_panel:
        reason = (f"{len(no_panel)} enrolled leader(s) have no feedback panel yet "
                  f"({_name_list(no_panel)}). Assign each a panel and mail their "
                  "invitations first.")
    elif unmailed:
        failed = sum(r["failed"] for r in unmailed)
        reason = (f"feedback invitations have not gone out for {len(unmailed)} leader(s) "
                  f"({_name_list(unmailed)}). "
                  + (f"{failed} send(s) failed — resend them, or replace those givers."
                     if failed else "Send them from the Leaders screen first."))
    else:
        reason = ""

    return {
        "subjects": len(subjects),
        "panels_missing": no_panel,
        "mail_pending": unmailed,
        "ready": bool(subjects) and not no_panel and not unmailed,
        "reason": reason,
    }


async def panel_shortfall(company_id: str, cycle: str, subject_id: str) -> Dict[str, int]:
    """How many givers each relation is still short of, for one leader's panel.

    The document is specific about who is asked: "hum aapke 8 logon se feedback lenge — 2
    superiors, 2 peers, 2 other departments, aur 2 direct reports". That is not decoration.
    A single superior's rating IS that superior's opinion, and a leader reading a 360° score
    built from two juniors is reading something the label does not describe.

    Returns {relation: missing} for every relation the cycle's degree collects. An empty
    dict means the panel is complete. Reporting the shortfall rather than a bare boolean
    lets the caller tell HR exactly who is still needed.
    """
    cyc = await get_cycle(company_id, cycle)
    subject = await get_subject(company_id, cycle, subject_id)
    # Per SUBJECT, not per cycle: a leader with no direct reports is on 180° even inside a
    # 360° cycle, and asking for groups they cannot have would hold them out of dispatch
    # permanently.
    wanted = DEGREE_RELATIONS.get(effective_degree(cyc, subject), RELATIONS)

    rows = await get_collection(COLL_LS_ASSIGNMENTS).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).to_list(500)

    have: Dict[str, int] = {}
    for r in rows:
        rel = str(r.get("relation") or "")
        have[rel] = have.get(rel, 0) + 1

    return {rel: RECOMMENDED_PER_RELATION - have.get(rel, 0)
            for rel in wanted
            if have.get(rel, 0) < RECOMMENDED_PER_RELATION}


def describe_shortfall(missing: Dict[str, int]) -> str:
    """'2 x Supervisor, 1 x Junior / Direct report' — for an error a human reads.

    Counted rather than pluralised: the labels already carry parentheses ("Peer (same
    department)"), and appending an "s" to those reads as a typo.
    """
    return ", ".join(f"{n} x {RELATION_LABELS.get(rel, rel)}" for rel, n in missing.items())


async def incomplete_panels(company_id: str, cycle: str) -> Dict[str, dict]:
    """{subject_id: {name, missing, summary}} for every enrolled leader whose panel is short.

    Used by the cycle-wide dispatch, which mails the leaders that ARE ready and reports the
    rest rather than refusing the whole batch — one unfinished panel should not hold up
    seven finished ones.
    """
    out: Dict[str, dict] = {}
    for s in await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle),
    }).to_list(500):
        sid = str(s.get("subject_id"))
        missing = await panel_shortfall(company_id, cycle, sid)
        if missing:
            out[sid] = {"subject_name": s.get("subject_name") or sid,
                        "missing": missing,
                        "summary": describe_shortfall(missing)}
    return out


def effective_degree(cyc: dict, subject: Optional[dict] = None) -> str:
    """The degree that actually applies to one leader.

    Set per cycle, overridable per subject. The override is not a nicety: a leader with no
    direct reports cannot be a 360° subject, and without it their panel can never be
    completed — `incomplete_panels` would hold them out of every dispatch forever, with no
    way to say why.
    """
    if subject and subject.get("mode_override"):
        return str(subject["mode_override"])
    return str((cyc or {}).get("degree") or DEGREE_360)


def effective_quorum(cyc: dict, subject: Optional[dict] = None) -> int:
    """The quorum that can actually be met — for a cycle, or for one leader inside it.

    `quorum` is stored per cycle and defaults to DEFAULT_QUORUM (5), but a 180 degree panel
    is four people: two superiors and two same-department peers. A stored five is then
    unreachable by arithmetic, so every leader on 180 read as below quorum however many of
    their panel replied — and the freeze warning named them all, every time.

    Capped rather than corrected in the database, so cycles already carrying a five start
    behaving without their stored settings being rewritten underneath HR.

    Per SUBJECT as well as per cycle: a leader overridden to 180 inside a 360 cycle has a
    four-person panel and must not be held to the cycle's eight.
    """
    stored = int((cyc or {}).get("quorum") or DEFAULT_QUORUM)
    capped = min(stored, panel_size_for(effective_degree(cyc, subject)))
    return max(MIN_RESPONSES_FLOOR, capped)


def effective_min_responses(cyc: dict, subject: Optional[dict] = None) -> int:
    """The anonymity floor that can actually be met. Same cap, same reason as
    effective_quorum — a stored threshold above the panel means no score is ever computed.

    Never drops below MIN_RESPONSES_FLOOR: the cap protects reachability, and must not be
    allowed to trade anonymity away for it.
    """
    stored = int((cyc or {}).get("min_responses") or MIN_RESPONSES_FLOOR)
    capped = min(stored, panel_size_for(effective_degree(cyc, subject)))
    return max(MIN_RESPONSES_FLOOR, capped)


async def create_cycle(company_id: str, payload, user: dict) -> dict:
    cycle = str(payload.cycle or current_cycle())
    cycle_label(cycle)  # validates the code shape; raises ValueError on nonsense
    existing = await get_collection(COLL_LS_CYCLES).find_one(
        {"company_id": str(company_id), "cycle": cycle})
    if existing:
        raise ValueError(f"A cycle already exists for {cycle_label(cycle)}")

    validate_window(getattr(payload, "opens_at", None),
                    getattr(payload, "closes_at", None), cycle)

    now = datetime.utcnow()
    doc = {
        "company_id": str(company_id),
        "cycle": cycle,
        "period": cycle_period(cycle),
        "degree": payload.degree,
        # Anonymity floor: fewest responses before a number is shown at all.
        "min_responses": max(int(payload.min_responses or MIN_RESPONSES_FLOOR),
                             MIN_RESPONSES_FLOOR),
        # Confidence floor: fewest responses before a score may be FROZEN and released.
        # The document's panel is 8; a result from three of them is not the 360° view its
        # label claims. Capped at the panel the DEGREE collects from — a 180° cycle has
        # four givers, so the default of five would be unreachable from the moment the
        # cycle was created.
        "quorum": min(int(getattr(payload, "quorum", None) or DEFAULT_QUORUM),
                      panel_size_for(payload.degree)),
        # Empty = equal across the groups in play. Stored empty rather than filled in, so
        # the screen can honestly say "default" instead of showing invented numbers.
        "group_weightages": getattr(payload, "group_weightages", None) or {},
        # HR's collection window. Independent of the cycle's calendar months, so a window
        # can be opened late or EXTENDED — which is the remedy when quorum is not met.
        "opens_at": getattr(payload, "opens_at", None),
        "closes_at": getattr(payload, "closes_at", None),
        "status": CYCLE_DRAFT,
        "notes": payload.notes or "",
        "created_by": _display_name(user),
        "created_by_id": str(user.get("_id") or ""),
        "created_at": now,
        "updated_at": now,
        "closed_at": None,
        "computed_at": None,
        "published_at": None,
    }
    await get_collection(COLL_LS_CYCLES).insert_one(doc)
    await seed_questions_if_empty()
    doc["_id"] = str(doc.get("_id", ""))
    doc["label"] = cycle_label(cycle)
    return doc


async def update_cycle(company_id: str, cycle: str, updates: dict, user: dict) -> dict:
    """Edit a cycle, or move it along the state machine.

    The state machine is the point. `draft → open → closed → computed → published`, with
    every step checked here rather than trusted from the caller, because the same three
    guarantees hang off it: feedback is only accepted while collecting, a score is only
    frozen once, and a leader sees nothing until HR publishes.
    """
    fields = {k: v for k, v in updates.items() if v is not None}
    if not fields:
        raise ValueError("Nothing to update")

    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("Cycle not found")
    current = cyc.get("status") or CYCLE_DRAFT
    target = fields.get("status")

    if target and target != current:
        if target not in CYCLE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(CYCLE_STATUSES)}")
        # draft / open / closed belong to the clock now. Refused here rather than quietly
        # ignored: a caller asking to open a cycle has to learn that the Open date is the
        # control, or it will keep asking and keep appearing not to work.
        # Reverting a compute is HR undoing their own decision, not reopening collection,
        # so it stays available — the clock re-derives from `closed` on the next read.
        reverting = current == CYCLE_COMPUTED and target == CYCLE_CLOSED
        if target not in CYCLE_MANUAL and not reverting:
            raise ValueError(
                f"{cycle_label(cycle)} moves between draft, open and closed on its own "
                "Open and Close dates. Change those dates instead — a cycle can no longer "
                "be opened or closed by hand.")
        if not can_transition(current, target):
            allowed = CYCLE_TRANSITIONS.get(current) or []
            raise ValueError(
                f"{cycle_label(cycle)} is {current} and cannot become {target}"
                + (f" — it can only move to {', '.join(allowed)}." if allowed else
                   ". A published cycle is final."))

    # Both thresholds count REPLIES, so neither may exceed the panel the degree collects
    # from — four at 180°, eight at 360°. Checked here rather than on CycleUpdate because
    # the degree in play may be the stored one or may be changing in this same PATCH.
    degree = str(fields.get("degree") or cyc.get("degree") or DEGREE_360)
    panel = panel_size_for(degree)
    for key in ("min_responses", "quorum"):
        if key in fields and int(fields[key]) > panel:
            raise ValueError(
                f"A {degree}° cycle collects from {panel} givers "
                f"({RECOMMENDED_PER_RELATION} per relation), so {key} cannot be "
                f"{fields[key]}.")
    if "degree" in fields:
        # Narrowing 360° to 180° shrinks the panel from eight to four, which can strand a
        # threshold that was legal under the old degree. Bring the stored ones down with it
        # rather than leaving a cycle that can never be scored.
        for key in ("min_responses", "quorum"):
            if key not in fields and int(cyc.get(key) or MIN_RESPONSES_FLOOR) > panel:
                fields[key] = panel

    # The readiness gate that used to gate draft -> open is gone with the button. A date
    # arrives whether or not the panels were built, so blocking it could only ever mean
    # refusing to acknowledge the clock. `open_readiness` still reports, and the Cycles
    # screen still warns — it advises now rather than blocks.

    # Settings are frozen once collection starts: changing a weightage, the degree or the
    # quorum midway would score the responses already in hand against different rules from
    # the ones they were collected under.
    locked = {"degree", "group_weightages", "quorum", "min_responses"}
    if current not in (CYCLE_DRAFT,) and (locked & set(fields)):
        raise ValueError(
            f"{cycle_label(cycle)} has already opened. Its degree, quorum and weightages "
            "are fixed so that every response is scored under the rules it was collected "
            "under.")

    # The window itself freezes at `computed`. Moving a close date forward used to reopen
    # collection on a cycle whose scores were already frozen — and, once published, already
    # read by the leader they describe: the status stayed put while the window, the links
    # and dispatch all came back to life. Feedback arriving after publication is exactly
    # what the closed / computed / published split exists to prevent.
    if current in CYCLE_MANUAL and ({"opens_at", "closes_at"} & set(fields)):
        raise ValueError(
            f"{cycle_label(cycle)} is {current}. Its feedback window is fixed — scores "
            "have been frozen from what was collected inside it, so the dates can no "
            "longer move. Un-compute it first if it genuinely needs to collect again.")

    # Checked against the MERGED window: a PATCH may carry only one of the two dates, and
    # the one already stored is what the new one has to be coherent with.
    if {"opens_at", "closes_at"} & set(fields):
        validate_window(fields.get("opens_at", cyc.get("opens_at")),
                        fields.get("closes_at", cyc.get("closes_at")), cycle)

    # Computing is not gated on any approval of the rubric: the seeded questions and
    # options are the single source of truth and are scored exactly as they stand.
    now = datetime.utcnow()
    fields["updated_at"] = now
    if target == CYCLE_CLOSED:
        fields["closed_at"] = now
    if target == CYCLE_COMPUTED:
        fields["computed_at"] = now
    if target == CYCLE_PUBLISHED:
        fields["published_at"] = now
        fields["published_by"] = _display_name(user)

    await get_collection(COLL_LS_CYCLES).update_one(
        {"company_id": str(company_id), "cycle": str(cycle)}, {"$set": fields})

    if target == CYCLE_COMPUTED:
        await snapshot_cycle_scores(company_id, cycle)
    return await get_cycle(company_id, cycle)


async def delete_cycle(company_id: str, cycle: str) -> dict:
    """Delete a cycle that has collected nothing, and everything set up under it.

    For the cycle opened by mistake — wrong window, wrong degree, duplicate. Two things
    stop it, both for the same reason: something exists that deleting would destroy and
    nobody could reconstruct.

      • ANY FEEDBACK — responses carry no giver identity by design, so a deleted response
        cannot be traced back and asked for again. This mirrors `remove_subject`, which
        refuses to un-enrol a leader for exactly the same reason.
      • PUBLISHED — leaders and their reporting managers have been emailed that a score
        is ready, and RRO conversations may already reference it. Deleting it would erase
        a number people were shown.

    Otherwise the cycle and everything scaffolded under it goes: subjects, panel links,
    any frozen score rows and any discussion or briefing tracking. The counts come back so
    the caller can say what was removed — invalidating eight already-emailed links is
    worth reporting rather than doing quietly.
    """
    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("This cycle does not exist")

    responses = await get_collection(COLL_LS_RESPONSES).count_documents({
        "company_id": str(company_id), "cycle": str(cycle)})
    if responses:
        raise ValueError(
            f"{cycle_label(cycle)} already holds {responses} submitted "
            f"response{'' if responses == 1 else 's'}. Feedback is anonymous and cannot be "
            "collected again, so the cycle cannot be deleted.")
    if cyc.get("status") == CYCLE_PUBLISHED:
        raise ValueError(
            f"{cycle_label(cycle)} has been published — its leaders and their managers "
            "were told their scores were ready, so it stays as a record.")

    removed = {}
    for key, coll in (("subjects", COLL_LS_SUBJECTS), ("links", COLL_LS_ASSIGNMENTS),
                      ("scores", COLL_LS_SCORES), ("discussions", COLL_LS_DISCUSSIONS),
                      ("briefings", COLL_LS_BRIEFINGS)):
        res = await get_collection(coll).delete_many({
            "company_id": str(company_id), "cycle": str(cycle)})
        removed[key] = res.deleted_count

    res = await get_collection(COLL_LS_CYCLES).delete_one({
        "company_id": str(company_id), "cycle": str(cycle)})
    removed["cycle"] = res.deleted_count
    logger.info("Leadership cycle %s deleted [company=%s] %s", cycle, company_id, removed)
    return {"deleted": True, "cycle": cycle, "label": cycle_label(cycle), "removed": removed}


async def quorum_report(company_id: str, cycle: str) -> dict:
    """Who is short of quorum, so HR can extend the window instead of publishing a thin score.

    Names leaders, never raters, and reports counts only — "3 of 8 responses", never which
    three.
    """
    cyc = await get_cycle(company_id, cycle) or {}
    quorum = effective_quorum(cyc)
    subjects = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    short = []
    for s in subjects:
        n = await get_collection(COLL_LS_RESPONSES).count_documents({
            "company_id": str(company_id), "cycle": str(cycle),
            "subject_id": str(s.get("subject_id"))})
        panel = await get_collection(COLL_LS_ASSIGNMENTS).count_documents({
            "company_id": str(company_id), "cycle": str(cycle),
            "subject_id": str(s.get("subject_id"))})
        # Per subject, not per cycle: a leader overridden to 180° inside a 360° cycle has
        # four givers, and holding them to the cycle's eight would keep them below quorum
        # even with a full panel.
        want = effective_quorum(cyc, s)
        if n < want:
            short.append({"subject_id": str(s.get("subject_id")),
                          "subject_name": s.get("subject_name"),
                          "responses": n, "panel_size": panel,
                          "quorum": want, "short_by": want - n})
    # The anonymity floor travels with the report: below it no score exists at all, which
    # is a different warning from a thin one, and the caller cannot derive it from the
    # stored value once the degree has capped it.
    return {"quorum": quorum, "subjects": len(subjects),
            "min_responses": effective_min_responses(cyc),
            "below_quorum": short, "all_met": not short}


# ─────────────────────────────────────────────────────────────
# Subjects (the leaders being rated)
# ─────────────────────────────────────────────────────────────
async def _find_person(person_id: str, company_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(str(person_id))
    except Exception:
        return None
    for coll in PERSON_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc and str(doc.get("company_id") or "") == str(company_id):
            return doc
    return None


async def list_company_people(company_id: str) -> List[dict]:
    """The company's active roster — the pool HR picks leaders and givers from.

    `leadership_level` is carried through deliberately. This projection is what
    `list_eligible_people()` reads, and while the field was missing every levelled user
    was reported as unlevelled: the level was stored correctly on the user, but the
    eligible list was built from a dict that had already dropped it. It is copied from the
    user record as-is and never inferred from `designation` — see `leadership_level_of`.
    """
    people = []
    query = {"company_id": str(company_id), "is_active": {"$ne": False}}
    for coll in PERSON_COLLECTIONS:
        for u in await get_collection(coll).find(query).to_list(2000):
            people.append({
                "person_id": str(u["_id"]),
                "name": _display_name(u),
                "email": u.get("email"),
                # The number the invitation will go to. Carried so the panel builder can show
                # who is unreachable BEFORE the send, rather than after it lands in the ledger
                # as "no mobile number on this person's record".
                "mobile": str(u.get("mobile") or u.get("phone") or "").strip(),
                "designation": u.get("designation"),
                "department": u.get("department"),
                "reporting_manager": u.get("reporting_manager"),
                "leadership_level": leadership_level_of(u) or None,
            })
    people.sort(key=lambda p: (p.get("name") or "").lower())
    return people


async def list_subjects(company_id: str, cycle: str) -> List[dict]:
    from app.services.leadership_link_service import effective_status

    subjects = await get_collection(COLL_LS_SUBJECTS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    assignments = await get_collection("tpms_leadership_assignments").find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(4000)
    by_subject: Dict[str, list] = {}
    for a in assignments:
        by_subject.setdefault(str(a.get("subject_id")), []).append(a)

    # The cycle's own degree, so each row can say what its panel SHOULD hold.
    cyc = await get_cycle(company_id, cycle) or {}

    now = datetime.now(timezone.utc)
    out = []
    for s in subjects:
        s["_id"] = str(s["_id"])
        panel = by_subject.get(str(s.get("subject_id")), [])
        s["panel_size"] = len(panel)
        # What the panel SHOULD hold, for THIS leader's degree. Additive: the column used
        # to print "/ 8" whatever the cycle collected, so a full 180° panel of four
        # read as half-built.
        s["panel_target"] = panel_size_for(effective_degree(cyc, s))
        s["submitted_count"] = len([p for p in panel if p.get("status") == "submitted"])
        s["pending_count"] = len([p for p in panel
                                  if effective_status(p, now, cyc) in ("sent", "opened")])
        s["level_label"] = LEVEL_LABELS.get(s.get("level") or "", s.get("level") or "")
        out.append(s)
    out.sort(key=lambda x: (x.get("subject_name") or "").lower())
    return out


def leadership_level_of(person: dict) -> str:
    """A person's Leadership level, or "" if nobody has set one.

    Read from the explicit `leadership_level` field ONLY. It is deliberately never derived
    from the free-text `designation`: "Sr. Manager" and "Senior Manager" are the same job
    and would land on different levels — or on none — so a leader would silently drop out
    of a cycle with nothing on screen to say why.
    """
    return str(person.get("leadership_level") or "").strip().upper()


def is_eligible(person: dict) -> bool:
    """"Applicable from L4 (Asst Managers) and above.\""""
    return leadership_level_of(person) in LEVELS


async def list_eligible_people(company_id: str) -> dict:
    """The roster split into who can be enrolled and who cannot yet.

    `unlevelled` is the important half: people whose designation looks senior but who
    carry no `leadership_level`. They are listed rather than hidden, so HR fixes the user
    record before the cycle opens instead of discovering the omission afterwards.
    """
    eligible, unlevelled, other = [], [], []
    for p in await list_company_people(company_id):
        level = leadership_level_of(p)
        row = {**p, "leadership_level": level or None}
        if level in LEVELS:
            row["level_label"] = LEVEL_LABELS.get(level, level)
            eligible.append(row)
        elif level:
            other.append(row)          # levelled, but below L4
        else:
            unlevelled.append(row)
    return {"eligible": eligible, "unlevelled": unlevelled, "below_l4": other,
            "levels": [{"code": lv, "label": LEVEL_LABELS[lv]} for lv in LEVELS]}


async def add_subject(company_id: str, cycle: str, subject_id: str, level: str,
                      user: dict, mode_override: Optional[str] = None) -> dict:
    person = await _find_person(subject_id, company_id)
    if not person:
        raise ValueError("That person is not on this company's roster")

    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("This cycle does not exist")
    if cyc.get("status") not in CYCLE_COLLECTING:
        raise ValueError(
            f"{cycle_label(cycle)} is {cyc.get('status')}. Leaders can only be enrolled "
            "while a cycle is still being set up or collecting.")

    level = str(level or "").upper()
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")

    # Eligibility is the user's own recorded level, not the caller's claim. Enrolling a
    # leader at a level they do not hold would score them against a rubric written for a
    # different job.
    on_record = leadership_level_of(person)
    if not on_record:
        raise ValueError(
            f"{_display_name(person)} has no Leadership level on their user record. "
            "Set it to L4, L5, L6 or L7 before enrolling them — it must not be guessed "
            "from their designation.")
    if on_record != level:
        raise ValueError(
            f"{_display_name(person)} is recorded as {LEVEL_LABELS.get(on_record, on_record)}. "
            f"Enrol them at that level, or correct their user record first.")

    questions = await get_questions(level, company_id=company_id)
    if not questions:
        raise ValueError(f"No active questions configured for {level}")

    if mode_override and mode_override not in DEGREE_RELATIONS:
        raise ValueError(f"mode_override must be one of {', '.join(DEGREE_RELATIONS)}")

    existing = await get_collection(COLL_LS_SUBJECTS).find_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if existing:
        raise ValueError("This leader is already enrolled in this cycle")

    now = datetime.utcnow()
    doc = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "period": cycle_period(cycle),
        "subject_id": str(subject_id),
        "subject_name": _display_name(person),
        "designation": person.get("designation") or "",
        "department": person.get("department") or "",
        "reporting_manager": str(person.get("reporting_manager") or ""),
        "level": level,
        # A leader with no direct reports cannot be a 360° subject; the override is how
        # that is said, rather than leaving their panel permanently incomplete.
        "mode_override": mode_override or None,
        # THE RUBRIC THEY ARE SCORED AGAINST, frozen at enrolment.
        #
        # Without this, every score was recomputed from whatever the question master said
        # today — so editing a weightage retroactively moved scores that had already been
        # discussed at RRO. The snapshot is what makes a published number permanent.
        "rubric": [{
            "item_id": q["item_id"],
            "title": q.get("title", ""),
            "prompt": q.get("prompt", ""),
            "weightage": float(q.get("weightage") or 0),
            "options": [dict(o) for o in (q.get("options") or [])],
        } for q in questions],
        "rubric_fingerprint": rubric_fingerprint(questions),
        "enrolled_by": _display_name(user),
        "enrolled_by_id": str(user.get("_id") or ""),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_LS_SUBJECTS).insert_one(doc)
    doc["_id"] = str(doc.get("_id", ""))
    return doc


async def set_subject_mode(company_id: str, cycle: str, subject_id: str,
                           mode_override: Optional[str]) -> dict:
    """Put one leader on a different degree from the rest of the cycle."""
    if mode_override and mode_override not in DEGREE_RELATIONS:
        raise ValueError(f"mode_override must be one of {', '.join(DEGREE_RELATIONS)}")

    cyc = await get_cycle(company_id, cycle)
    if cyc and cyc.get("status") not in CYCLE_COLLECTING:
        raise ValueError("The degree can only be changed while a cycle is still collecting")

    res = await get_collection(COLL_LS_SUBJECTS).update_one(
        {"company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)},
        {"$set": {"mode_override": mode_override or None,
                  "updated_at": datetime.utcnow()}})
    if not res.matched_count:
        raise ValueError("This leader is not enrolled in this cycle")
    return await get_subject(company_id, cycle, subject_id)


async def get_subject(company_id: str, cycle: str, subject_id: str) -> Optional[dict]:
    doc = await get_collection(COLL_LS_SUBJECTS).find_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def remove_subject(company_id: str, cycle: str, subject_id: str) -> dict:
    """Un-enrol a leader who has collected no feedback yet. Once any response exists the
    subject stays — deleting would destroy collected feedback."""
    responses = await get_collection(COLL_LS_RESPONSES).count_documents({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if responses:
        raise ValueError("Feedback has already been submitted for this leader; they cannot be removed")

    await get_collection("tpms_leadership_assignments").delete_many({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    res = await get_collection(COLL_LS_SUBJECTS).delete_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    return {"removed": res.deleted_count}


async def set_panel(company_id: str, cycle: str, subject_id: str,
                    givers: List, user: dict) -> dict:
    """Set a subject's feedback panel and mint a link for each member.

    Members already holding a link keep it (and their submitted feedback). Members dropped
    from the list lose their unsubmitted link. Nothing already submitted is ever removed.

    LOCKED ONCE ANY FEEDBACK HAS ARRIVED. Swapping a panel member mid-collection narrows
    the pool the responses came from, and a group of two that quietly became a group of
    one is a signed statement — the suppression rule cannot save it, because it is applied
    to the count at read time and the count still says two.
    """
    from app.services.leadership_link_service import create_assignment, remove_assignment

    subject = await get_subject(company_id, cycle, subject_id)
    if not subject:
        raise ValueError("This leader is not enrolled in this cycle")

    cyc = await get_cycle(company_id, cycle)
    if (cyc or {}).get("status") not in CYCLE_COLLECTING:
        raise ValueError(
            f"{cycle_label(cycle)} is {(cyc or {}).get('status')}. Panels cannot be "
            "changed once a cycle has closed.")

    received = await get_collection(COLL_LS_RESPONSES).count_documents({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if received:
        raise ValueError(
            f"Feedback has already been received for {subject.get('subject_name')}. "
            "The panel is fixed from the first response onward, so that nobody can work "
            "out who said what by comparing who was on it before and after.")

    allowed = set(DEGREE_RELATIONS.get(effective_degree(cyc, subject), RELATIONS))

    company = None
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(str(company_id))})
    except Exception:
        company = None
    company_name = (company or {}).get("name") or ""

    wanted: Dict[str, str] = {}
    warnings: List[str] = []
    for g in givers:
        if g.relation not in allowed:
            raise ValueError(
                f"{RELATION_LABELS.get(g.relation, g.relation)} is not collected in a "
                f"{(cyc or {}).get('degree', DEGREE_360)}° cycle")
        if str(g.giver_id) == str(subject_id):
            raise ValueError("A leader cannot be on their own feedback panel")
        person = await _find_person(g.giver_id, company_id)
        if not person:
            raise ValueError("A selected feedback giver is not on this company's roster")
        warning = _relation_mismatch(subject, person, g.relation)
        if warning:
            warnings.append(warning)
        wanted[str(g.giver_id)] = g.relation

    created = 0
    for giver_id, relation in wanted.items():
        person = await _find_person(giver_id, company_id)
        await create_assignment(
            company_id=company_id, company_name=company_name, cycle=cycle,
            subject=subject, giver=person, relation=relation, assigned_by=user)
        created += 1

    # Drop anyone no longer on the panel (unsubmitted only).
    existing = await get_collection("tpms_leadership_assignments").find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).to_list(500)
    removed = 0
    for row in existing:
        if str(row.get("giver_id")) not in wanted:
            if await remove_assignment(company_id, cycle, subject_id, row.get("giver_id")):
                removed += 1

    return {"panel_size": created, "removed": removed, "warnings": warnings}


def _relation_mismatch(subject: dict, giver: dict, relation: str) -> str:
    """Where the org data disagrees with the label HR put on a panel member.

    Reported, never enforced. `reporting_manager` and `department` are frequently
    incomplete on a real roster, so refusing the panel would block HR over a data gap they
    cannot fix today — but a panel of eight juniors labelled 2/2/2/2 passes a pure count
    check, and the score would then be presented as a 360° view it is not.
    """
    subject_id = str(subject.get("subject_id") or "")
    giver_id = str(giver.get("_id") or "")
    name = _display_name(giver)
    giver_mgr = str(giver.get("reporting_manager") or "")
    subject_mgr = str(subject.get("reporting_manager") or "")
    same_dept = (str(giver.get("department") or "").strip().lower()
                 == str(subject.get("department") or "").strip().lower())

    if relation == REL_DIRECT_REPORT and giver_mgr and giver_mgr != subject_id:
        return f"{name} is marked a direct report but does not report to this leader."
    if relation == REL_SUPERIOR and subject_mgr and giver_id != subject_mgr:
        return (f"{name} is marked a superior but is not this leader's reporting manager. "
                "Confirm they are the level above.")
    if relation == REL_PEER and not same_dept and giver.get("department"):
        return f"{name} is marked a same-department peer but is in another department."
    if relation == REL_OTHER_DEPT and same_dept and giver.get("department"):
        return f"{name} is marked an other-department peer but is in this leader's department."
    if giver_mgr and giver_mgr == subject_id and relation != REL_DIRECT_REPORT:
        return f"{name} reports to this leader but is not marked a direct report."
    return ""


# ─────────────────────────────────────────────────────────────
# Response capture
# ─────────────────────────────────────────────────────────────
async def record_response(assignment: dict, answers: List) -> dict:
    """Store one giver's completed form — with NO link back to the giver.

    The response document carries the cycle, the subject, the relation group and the
    answers. It does not carry `giver_id`, and it never has a field that can be joined to
    one. "Ye feedback completely confidential hoga" cannot be kept by hiding the identity
    in the API layer: one aggregation, one export, one support query and the promise is
    gone. The only way to keep it is for the join not to exist.

    Duplicate submission is prevented on the ASSIGNMENT instead, which is where it
    belongs: `claim_for_submission()` flips that row to submitted atomically, and only the
    caller that wins the flip reaches this function.

    Every (question, option) pair is validated against the live master for the SUBJECT's
    level, so a client cannot post a score the rubric does not offer.
    """
    level = str(assignment.get("subject_level") or "").upper()
    company_id = str(assignment.get("company_id"))
    questions = await get_questions(level, company_id=company_id)
    if not questions:
        raise ValueError(f"No active questions configured for {level}")

    stored = _validate_answers(answers, questions, level)

    now = datetime.utcnow()
    await get_collection(COLL_LS_RESPONSES).insert_one({
        "company_id": company_id,
        "cycle": str(assignment.get("cycle")),
        "subject_id": str(assignment.get("subject_id")),
        "period": assignment.get("period"),
        "subject_level": level,
        # The relation group is the ONLY thing about the giver that is kept. It is what
        # makes a group breakdown possible, and it identifies nobody on its own — the
        # breakdown itself is suppressed below MIN_GROUP_FOR_BREAKDOWN.
        "relation": assignment.get("relation"),
        "answers": stored,
        # NO `assignment_ref`. It used to be stored so a support question about a single
        # submission could be traced, but the assignment row holds giver_id / giver_name /
        # giver_email — so the reference WAS a join from an answer to a person, one hop
        # long. "Ye feedback completely confidential hoga" cannot survive a field whose
        # whole purpose is to be followed, however narrow the intended use. Nothing reads
        # it: duplicate submission is prevented on the assignment by claim_for_submission,
        # and scoring aggregates by subject and relation, neither of which needs it.
        "submitted_at": now,
        "created_at": now,
        "updated_at": now,
    })
    return {"saved": len(stored)}


def _validate_answers(answers: List, questions: List[dict], level: str) -> Dict[str, dict]:
    """Answers → stored form, or ValueError.

    EVERY active question must be answered. A part-filled form used to be accepted and
    then counted as a whole response: it advanced the quorum, while its unanswered
    questions dropped out of the weightage denominator, so the leader's headline number
    was quietly computed out of less than 100 and read as a low score.
    """
    by_id = {q["item_id"]: q for q in questions}
    stored: Dict[str, dict] = {}

    for a in answers:
        q = by_id.get(a.question_id)
        if not q:
            raise ValueError(f"Unknown question '{a.question_id}' for {level}")
        option = next((o for o in (q.get("options") or [])
                       if str(o.get("option_id")) == str(a.option_id)), None)
        if not option:
            raise ValueError(f"Unknown option '{a.option_id}' for question '{a.question_id}'")
        stored[a.question_id] = {
            "option_id": option["option_id"],
            "option_label": option.get("label", ""),
            "score": float(option.get("score") or 0),
        }

    missing = [q["item_id"] for q in questions if q["item_id"] not in stored]
    if missing:
        raise ValueError(
            f"Please answer every question before submitting — "
            f"{len(missing)} still unanswered.")
    return stored


# ─────────────────────────────────────────────────────────────
# Scoring
#
# GROUP-WEIGHTED, NOT RATER-WEIGHTED.
#
# Every rater's answers are averaged WITHIN their relation group first, and the four group
# results are then weighted against each other. Averaging all eight raters flat — which is
# what this did before — lets whichever group happened to respond most decide the number:
# if both superiors reply and one junior does, the superiors carry two thirds of the
# weight. A leader who is admired upward and feared downward then scores well, which is
# the single failure mode a 360° instrument exists to catch.
#
# Groups with no responses are dropped and the remaining weights renormalised, so a
# missing group lowers confidence (reported as `groups_scored`) rather than silently
# deflating the score.
#
# The rubric is the one SNAPSHOTTED onto the subject at enrolment, never today's master —
# see `add_subject`. Editing a weightage must not move a score a manager already discussed.
# ─────────────────────────────────────────────────────────────
def _rubric_for(subject: dict, live: List[dict]) -> List[dict]:
    """The questions this subject is scored against.

    Prefers the snapshot taken when they were enrolled. Falls back to the live master for
    subjects enrolled before snapshots existed — their scores can still move if the
    rubric is edited, which is exactly what `rubric_snapshot` reports so the score card
    can say so rather than pretending otherwise.
    """
    snap = subject.get("rubric") or []
    return snap if snap else live


def _score_answers(responses: List[dict], questions: List[dict]) -> dict:
    """Weighted parameter scores over one already-selected set of responses."""
    parameters = []
    total = 0.0
    applicable = 0.0

    for q in questions:
        item_id = q["item_id"]
        weightage = float(q.get("weightage") or 0)
        scores = [
            float((r.get("answers") or {}).get(item_id, {}).get("score"))
            for r in responses
            if (r.get("answers") or {}).get(item_id, {}).get("score") is not None
        ]

        if scores:
            avg = sum(scores) / len(scores)
            achievement = avg / SCALE_MAX * 100
            weighted = achievement * weightage / 100
            total += weighted
            applicable += weightage
        else:
            avg = achievement = weighted = None

        parameters.append({
            "item_id": item_id,
            "title": q.get("title", ""),
            "prompt": q.get("prompt", ""),
            "weightage": _round(weightage),
            "max_score": _round(weightage),
            "average_rating": _round(avg),          # 1..5
            "achievement": _round(achievement),     # 0..100
            "weighted_score": _round(weighted or 0),
            "answered_by": len(scores),
            "has_data": bool(scores),
        })

    return {
        "parameters": parameters,
        "leadership_score": _round(total),
        "applicable_weightage": _round(applicable),
        "unearned_weightage": _round(round(sum(p["weightage"] for p in parameters), 2) - applicable),
        "score_on_applicable": _round(total / applicable * 100) if applicable else None,
    }


def group_weights(cyc: dict, relations: List[str]) -> Dict[str, float]:
    """How much each relation group counts, normalised to 1 over the groups in play.

    Equal unless HR sets otherwise. The document does not say whether a direct report's
    view should outweigh a superior's — they see day-to-day leadership most closely, which
    is an argument for more, and they are the most exposed, which is an argument for
    care — so the neutral split is the only defensible default, and the screen labels it
    as a default rather than a decision.
    """
    configured = (cyc or {}).get("group_weightages") or {}
    raw = {rel: float(configured.get(rel, 0) or 0) for rel in relations}
    if sum(raw.values()) <= 0:
        raw = {rel: 1.0 for rel in relations}
    total = sum(raw.values())
    return {rel: v / total for rel, v in raw.items()}


def _combine_groups(by_group: Dict[str, dict], weights: Dict[str, float]) -> Optional[float]:
    """Group scores → one number, renormalised over the groups that actually responded."""
    live = {rel: g for rel, g in by_group.items() if g.get("leadership_score") is not None}
    if not live:
        return None
    weight_sum = sum(weights.get(rel, 0) for rel in live) or float(len(live))
    return round(sum(g["leadership_score"] * (weights.get(rel, 0) or 1) for rel, g in live.items())
                 / weight_sum, 2)


async def subject_score(company_id: str, cycle: str, subject_id: str,
                        include_relations: bool = False,
                        for_leader: bool = False) -> dict:
    """One leader's Leadership Score for one cycle.

    NEVER includes giver identity or an individual response — responses do not carry one.
    `include_relations` adds the per-group breakdown and is passed True only for HR/staff;
    even then a group with fewer than MIN_GROUP_FOR_BREAKDOWN responses is withheld,
    because a group of one names the person who filled it.

    `for_leader` withholds everything until the cycle is PUBLISHED. Without that, a subject
    could watch their own number move during collection and difference it after each
    submission, which recovers one named person's rating no matter what the group
    suppression does.
    """
    subject = await get_subject(company_id, cycle, subject_id)
    if not subject:
        raise ValueError("This leader is not enrolled in this cycle")

    cyc = await get_cycle(company_id, cycle) or {}
    status = cyc.get("status") or CYCLE_DRAFT

    # A frozen result is the truth for any cycle that has been computed: it is what HR
    # reviewed and what the leader was shown. Recomputing would let a later weightage edit
    # silently rewrite a score that has already been discussed at RRO.
    if status in (CYCLE_COMPUTED, CYCLE_PUBLISHED):
        frozen = await get_collection(COLL_LS_SCORES).find_one(
            {"company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
        if frozen:
            frozen.pop("_id", None)
            frozen["cycle_status"] = status
            frozen["frozen"] = True
            if for_leader and status != CYCLE_PUBLISHED:
                return _withheld(frozen, "not_published")
            if not include_relations:
                frozen.pop("by_relation", None)
            return frozen

    head = await _score_head(company_id, cycle, subject, cyc)

    if for_leader and status != CYCLE_PUBLISHED:
        return _withheld(head, "not_published")

    return await _compute_subject_score(company_id, cycle, subject, cyc, head,
                                        include_relations=include_relations)


def _withheld(head: dict, reason: str) -> dict:
    """A score a leader may not see yet — with no number in the payload at all.

    Zeroing or rounding would still leak: the response count alone, watched over a few
    days, tells a leader when each of eight people replied.
    """
    keep = {"company_id", "cycle", "cycle_label", "period", "subject_id", "subject_name",
            "designation", "department", "level", "level_label", "level_theme",
            "cycle_status"}
    return {
        **{k: v for k, v in head.items() if k in keep},
        "state": reason,
        "parameters": [],
        "leadership_score": None,
        "message": "Your score will be available once HR publishes this cycle.",
    }


async def _score_head(company_id: str, cycle: str, subject: dict, cyc: dict) -> dict:
    responses = await get_collection(COLL_LS_RESPONSES).count_documents({
        "company_id": str(company_id), "cycle": str(cycle),
        "subject_id": str(subject.get("subject_id"))})
    panel_size = await get_collection(COLL_LS_ASSIGNMENTS).count_documents({
        "company_id": str(company_id), "cycle": str(cycle),
        "subject_id": str(subject.get("subject_id"))})
    level = subject.get("level") or ""
    return {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "cycle_label": cycle_label(cycle),
        "period": cycle_period(cycle),
        "subject_id": str(subject.get("subject_id")),
        "subject_name": subject.get("subject_name"),
        "designation": subject.get("designation"),
        "department": subject.get("department"),
        "level": level,
        "level_label": LEVEL_LABELS.get(level, level),
        "level_theme": LEVEL_THEMES.get(level, ""),
        "response_count": responses,
        "panel_size": panel_size,
        "degree": effective_degree(cyc, subject),
        "cycle_status": cyc.get("status"),
    }


async def _compute_subject_score(company_id: str, cycle: str, subject: dict, cyc: dict,
                                 head: dict, *, include_relations: bool) -> dict:
    subject_id = str(subject.get("subject_id"))
    min_responses = effective_min_responses(cyc, subject)
    quorum = effective_quorum(cyc, subject)

    live = await get_questions(subject.get("level"), company_id=company_id)
    questions = _rubric_for(subject, live)

    responses = await get_collection(COLL_LS_RESPONSES).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": subject_id,
    }).to_list(200)

    head = {
        **head,
        "min_responses": min_responses,
        "quorum": quorum,
        "meets_quorum": len(responses) >= quorum,
        "rubric_snapshot": bool(subject.get("rubric")),
    }

    if len(responses) < min_responses:
        # Below the anonymity floor nothing is computed at all — there is no partial
        # number to leak and no breakdown to attribute to anyone.
        return {**head, "state": "awaiting_responses", "parameters": [],
                "leadership_score": None}

    relations = DEGREE_RELATIONS.get(effective_degree(cyc, subject), RELATIONS)
    weights = group_weights(cyc, relations)

    # Score each relation group on its own, then weight the groups against each other.
    by_group: Dict[str, dict] = {}
    for rel in relations:
        group = [r for r in responses if str(r.get("relation") or "") == rel]
        by_group[rel] = ({**_score_answers(group, questions), "response_count": len(group)}
                         if group else
                         {"parameters": [], "leadership_score": None, "response_count": 0})

    overall = _combine_groups(by_group, weights)

    # Parameter-wise, combined the same way — the RRO conversation is parameter-wise, so
    # a parameter total must be built like the headline number, not like a flat average.
    parameters = []
    for i, q in enumerate(questions):
        per_group = {}
        for rel in relations:
            p = (by_group[rel]["parameters"] or [None] * len(questions))[i] \
                if by_group[rel]["parameters"] else None
            if p and p["has_data"]:
                per_group[rel] = p
        achievement = None
        if per_group:
            wsum = sum(weights.get(rel, 0) for rel in per_group) or float(len(per_group))
            achievement = round(
                sum(p["achievement"] * (weights.get(rel, 0) or 1)
                    for rel, p in per_group.items()) / wsum, 2)
        weightage = float(q.get("weightage") or 0)
        parameters.append({
            "item_id": q["item_id"],
            "title": q.get("title", ""),
            "prompt": q.get("prompt", ""),
            "weightage": _round(weightage),
            "achievement": achievement,
            "weighted_score": _round(achievement * weightage / 100) if achievement is not None else None,
            "answered_by": sum(p["answered_by"] for p in per_group.values()),
            "has_data": bool(per_group),
            "groups_scored": len(per_group),
        })

    scored = [p for p in parameters if p["has_data"]]
    focus = sorted(scored, key=lambda p: p["achievement"])[:2]

    payload = {
        **head,
        "state": "scored",
        "leadership_score": overall,
        "parameters": parameters,
        # The two weakest parameters, named. "Generally scores self-explanatory hote hain"
        # is what the document says; a bare number is not actionable, and a manager
        # opening an RRO needs to know where to start.
        "focus_areas": [{"item_id": p["item_id"], "title": p["title"],
                         "achievement": p["achievement"]} for p in focus],
        "groups_scored": len([g for g in by_group.values() if g["leadership_score"] is not None]),
        "groups_expected": len(relations),
        "group_weightages": {rel: _round(w * 100) for rel, w in weights.items()},
        "group_weightage_is_default": not (cyc.get("group_weightages") or {}),
    }

    if include_relations:
        payload["by_relation"] = [{
            "relation": rel,
            "relation_label": RELATION_LABELS[rel],
            "response_count": by_group[rel]["response_count"],
            "leadership_score": (by_group[rel]["leadership_score"]
                                 if by_group[rel]["response_count"] >= MIN_GROUP_FOR_BREAKDOWN
                                 else None),
            # Withheld rather than shown: a group of one names its author.
            "withheld": by_group[rel]["response_count"] < MIN_GROUP_FOR_BREAKDOWN,
            "weightage": _round(weights.get(rel, 0) * 100),
        } for rel in relations]

    return payload


async def cycle_scores(company_id: str, cycle: str, include_relations: bool = False,
                       for_leader: bool = False) -> dict:
    """Every enrolled leader's score for a cycle.

    `for_leader` withholds every number until the cycle is published. It must be passed
    for anyone who is not running the module — the leader being rated AND their reporting
    manager — because publication is the moment the document releases scores to both.
    """
    subjects = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    rows = []
    for s in subjects:
        try:
            rows.append(await subject_score(company_id, cycle, s.get("subject_id"),
                                            include_relations=include_relations,
                                            for_leader=for_leader))
        except ValueError:
            continue

    scored = [r for r in rows if r.get("leadership_score") is not None]
    rows.sort(key=lambda r: (r.get("leadership_score") is not None,
                             r.get("leadership_score") or 0), reverse=True)

    cyc = await get_cycle(company_id, cycle) or {}
    return {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "cycle_label": cycle_label(cycle),
        "status": cyc.get("status"),
        "degree": cyc.get("degree"),
        "rows": rows,
        "below_quorum": [r["subject_id"] for r in rows if not r.get("meets_quorum", True)],
        "summary": {
            "leaders": len(rows),
            "scored": len(scored),
            "average_score": _round(sum(r["leadership_score"] for r in scored) / len(scored))
            if scored else None,
            "highest": scored[0]["leadership_score"] if scored else None,
            "lowest": scored[-1]["leadership_score"] if scored else None,
        },
    }


async def snapshot_cycle_scores(company_id: str, cycle: str) -> dict:
    """Freeze a cycle's scores into COLL_LS_SCORES.

    This is what every later read returns, so a weightage edit can never move a number a
    manager has already discussed. Responses themselves are left untouched.
    """
    subjects = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(500)
    cyc = await get_cycle(company_id, cycle) or {}

    now = datetime.utcnow()
    col = get_collection(COLL_LS_SCORES)
    frozen = 0
    for s in subjects:
        head = await _score_head(company_id, cycle, s, cyc)
        row = await _compute_subject_score(company_id, cycle, s, cyc, head,
                                           include_relations=True)
        await col.update_one(
            {"company_id": str(company_id), "cycle": str(cycle),
             "subject_id": row["subject_id"]},
            {"$set": {**row, "computed_at": now}},
            upsert=True,
        )
        frozen += 1
    logger.info("Leadership scores frozen: %s rows [company=%s cycle=%s]",
                frozen, company_id, cycle)
    return {"snapshotted": frozen, "cycle": cycle}


async def subject_history(company_id: str, subject_id: str, limit: int = 12,
                          published_only: bool = False) -> List[dict]:
    """A leader's score across past cycles — the trend an RRO conversation builds on.

    Reads the FROZEN rows only. Recomputing history from live responses meant every past
    score moved whenever a weightage was edited, so a leader could open their card and
    find last cycle's number different from the one they were shown.

    Carries the parameter breakdown, so the card can show a per-parameter delta rather
    than only a movement in the total — the discussion is parameter-wise.
    """
    rows = await get_collection(COLL_LS_SCORES).find({
        "company_id": str(company_id), "subject_id": str(subject_id),
    }).to_list(200)

    if published_only:
        # A frozen row exists from the moment a cycle is COMPUTED, which is before anyone
        # outside HR may see it. Without this filter the trend chart would hand a leader
        # the current cycle's number while HR was still reviewing it.
        published = {str(c.get("cycle")) for c in await get_collection(COLL_LS_CYCLES).find(
            {"company_id": str(company_id), "status": CYCLE_PUBLISHED}).to_list(200)}
        rows = [r for r in rows if str(r.get("cycle")) in published]

    rows.sort(key=lambda r: str(r.get("cycle") or ""), reverse=True)

    out = []
    for r in rows[:limit]:
        out.append({
            "cycle": r.get("cycle"),
            "cycle_label": r.get("cycle_label") or cycle_label(r.get("cycle") or ""),
            "level": r.get("level"),
            "leadership_score": r.get("leadership_score"),
            "response_count": r.get("response_count"),
            "state": r.get("state"),
            "parameters": [{"item_id": p.get("item_id"), "title": p.get("title"),
                            "achievement": p.get("achievement")}
                           for p in (r.get("parameters") or [])],
        })
    return out


def parameter_deltas(current: dict, previous: Optional[dict]) -> List[dict]:
    """Per-parameter movement against the previous cycle, matched on item_id.

    Matched by id rather than position: a level can gain or lose a question between
    cycles, and lining the lists up by index would silently compare one parameter against
    a different one.
    """
    if not previous:
        return []
    before = {p.get("item_id"): p.get("achievement") for p in (previous.get("parameters") or [])}
    out = []
    for p in current.get("parameters") or []:
        was = before.get(p.get("item_id"))
        now = p.get("achievement")
        out.append({
            "item_id": p.get("item_id"),
            "title": p.get("title"),
            "previous": was,
            "current": now,
            "delta": _round(now - was) if (was is not None and now is not None) else None,
        })
    return out


# ─────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────
async def audit(user: dict, action: str, detail: str, **meta) -> None:
    """Record a read or change of confidential Leadership data.

    Every read of a giver panel goes through here. Panel access is the one thing that can
    undo "ye feedback completely confidential hoga" from the inside, so it is never
    silent: if someone looks at who rates whom, there is a row saying who looked and when.

    Never raises. An audit failure must not take down the request it is describing — but
    it is logged loudly, because an unaudited panel read is exactly what this exists to
    prevent going unnoticed.
    """
    try:
        from app.services.activity_log_service import log_activity
        await log_activity(user, action, "leadership", details=detail, meta=meta or {})
    except Exception as e:                                   # pragma: no cover
        logger.warning("Leadership audit write failed (%s): %s | %s", action, detail, e)


# ─────────────────────────────────────────────────────────────
# RRO discussion and action plan
#
# "Their respective reporting Manager should discuss the score with each leader during RRO
# and every two months this should happen."
#
# This is the last step of the documented process and the reason the score exists at all —
# the "one thing" is improvement, and a number nobody acts on improves nothing. Without it
# the module produced a figure and stopped.
# ─────────────────────────────────────────────────────────────
async def get_discussion(company_id: str, cycle: str, subject_id: str) -> Optional[dict]:
    doc = await get_collection(COLL_LS_DISCUSSIONS).find_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def log_discussion(company_id: str, cycle: str, subject_id: str,
                         payload, user: dict) -> dict:
    """Record the RRO conversation and the action plan that came out of it."""
    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("This cycle does not exist")
    if cyc.get("status") != CYCLE_PUBLISHED:
        # Discussing a number the leader has not been shown is not the RRO conversation
        # the document describes.
        raise ValueError(
            f"{cycle_label(cycle)} has not been published yet. Scores are discussed at RRO "
            "once HR releases them.")

    subject = await get_subject(company_id, cycle, subject_id)
    if not subject:
        raise ValueError("This leader is not enrolled in this cycle")

    now = datetime.utcnow()
    items = [{
        "text": str(getattr(a, "text", "") or "").strip(),
        "owner": str(getattr(a, "owner", "") or "").strip(),
        "due_date": getattr(a, "due_date", None),
        "done": bool(getattr(a, "done", False)),
    } for a in (payload.action_items or []) if str(getattr(a, "text", "") or "").strip()]

    doc = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "subject_id": str(subject_id),
        "subject_name": subject.get("subject_name"),
        "manager_id": str(user.get("_id") or ""),
        "manager_name": _display_name(user),
        "notes": (payload.notes or "").strip(),
        "parameters_discussed": list(payload.parameters_discussed or []),
        "action_items": items,
        "discussed_at": payload.discussed_at or now,
        "updated_at": now,
    }
    await get_collection(COLL_LS_DISCUSSIONS).update_one(
        {"company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)},
        {"$set": doc,
         # The leader's acknowledgement belongs to the leader. Re-saving the notes must
         # not quietly clear it, nor set it on their behalf.
         "$setOnInsert": {"created_at": now, "acknowledged_at": None,
                          "acknowledged_by_leader": False}},
        upsert=True,
    )
    return await get_discussion(company_id, cycle, subject_id)


async def acknowledge_discussion(company_id: str, cycle: str, subject_id: str,
                                 user: dict, comment: str = "") -> dict:
    """The leader confirming the conversation happened. Only they can do this."""
    if str(user.get("_id")) != str(subject_id):
        raise ValueError("Only the leader themselves can acknowledge their RRO discussion")

    res = await get_collection(COLL_LS_DISCUSSIONS).update_one(
        {"company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)},
        {"$set": {"acknowledged_by_leader": True,
                  "acknowledged_at": datetime.utcnow(),
                  "leader_comment": (comment or "").strip()}})
    if not res.matched_count:
        raise ValueError("No RRO discussion has been logged for this cycle yet")
    return await get_discussion(company_id, cycle, subject_id)


async def pending_discussions(company_id: str, cycle: str) -> List[dict]:
    """Published leaders whose RRO conversation has not been logged."""
    subjects = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(500)
    logged = {str(d.get("subject_id")) for d in await get_collection(COLL_LS_DISCUSSIONS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(500)}
    return [{"subject_id": str(s.get("subject_id")),
             "subject_name": s.get("subject_name"),
             "reporting_manager": s.get("reporting_manager")}
            for s in subjects if str(s.get("subject_id")) not in logged]


# ─────────────────────────────────────────────────────────────
# Briefing tracker
#
# "Pre Leadership Score Briefing: It has to be done only till L4 (Asst Managers only)"
# against process item 1, "MD should take a session of Leadership Expectations with L4 and
# above". The document says both, so the module records both and does not choose: `type`
# distinguishes the MD's expectations session from HR's pre-briefing, and the L4-only rule
# is reported as guidance rather than enforced.
# ─────────────────────────────────────────────────────────────
BRIEFING_PRE = "pre"
BRIEFING_POST = "post"
BRIEFING_TYPES = [BRIEFING_PRE, BRIEFING_POST]


async def record_briefing(company_id: str, cycle: str, user_id: str, briefing_type: str,
                          conducted_by: str, user: dict, notes: str = "") -> dict:
    if briefing_type not in BRIEFING_TYPES:
        raise ValueError(f"type must be one of {', '.join(BRIEFING_TYPES)}")
    person = await _find_person(user_id, company_id)
    if not person:
        raise ValueError("That person is not on this company's roster")

    now = datetime.utcnow()
    doc = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "user_id": str(user_id),
        "user_name": _display_name(person),
        "level": leadership_level_of(person) or None,
        "type": briefing_type,
        "conducted_by": (conducted_by or "").strip() or _display_name(user),
        "conducted_at": now,
        "notes": (notes or "").strip(),
        "recorded_by_id": str(user.get("_id") or ""),
        "updated_at": now,
    }
    await get_collection(COLL_LS_BRIEFINGS).update_one(
        {"company_id": str(company_id), "cycle": str(cycle),
         "user_id": str(user_id), "type": briefing_type},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return doc


async def briefing_status(company_id: str, cycle: str) -> dict:
    """Who has been briefed and who has not, for this cycle."""
    rows = await get_collection(COLL_LS_BRIEFINGS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(1000)
    done = {(str(r.get("user_id")), r.get("type")) for r in rows}

    people = await list_company_people(company_id)
    eligible = [p for p in people if is_eligible(p)]

    return {
        "cycle": str(cycle),
        "records": [{k: v for k, v in r.items() if k != "_id"} for r in rows],
        "pre_pending": [
            {"person_id": p["person_id"], "name": p["name"],
             "leadership_level": leadership_level_of(p)}
            for p in eligible if (p["person_id"], BRIEFING_PRE) not in done],
        # The document restricts the pre-briefing to L4 in one place and to "L4 and above"
        # in another. Both readings are surfaced; neither is enforced.
        "l4_only_pending": [
            {"person_id": p["person_id"], "name": p["name"]}
            for p in eligible
            if leadership_level_of(p) == LEVEL_L4 and (p["person_id"], BRIEFING_PRE) not in done],
        "note": ("The source document says the pre-briefing is “only till L4 (Asst "
                 "Managers only)”, while the process list says the MD's Leadership "
                 "Expectations session covers “L4 and above”. Both lists are shown; HR "
                 "should confirm which applies."),
    }


# ─────────────────────────────────────────────────────────────
# Organisation roll-up
# ─────────────────────────────────────────────────────────────
async def dashboard(company_id: str, cycle: Optional[str] = None) -> dict:
    """Distribution, by level and by department — the MD's view of a cycle.

    Built from FROZEN scores only, so the roll-up cannot disagree with the cards the
    leaders were shown. Carries no rater information of any kind.
    """
    query = {"company_id": str(company_id)}
    if cycle:
        query["cycle"] = str(cycle)
    else:
        latest = await get_collection(COLL_LS_CYCLES).find(
            {"company_id": str(company_id), "status": CYCLE_PUBLISHED}).to_list(200)
        latest.sort(key=lambda c: str(c.get("cycle") or ""), reverse=True)
        if not latest:
            return {"cycle": None, "scored": 0, "bands": [], "by_level": [],
                    "by_department": [], "trend": []}
        query["cycle"] = str(latest[0]["cycle"])

    rows = [r for r in await get_collection(COLL_LS_SCORES).find(query).to_list(1000)
            if r.get("leadership_score") is not None]

    def bucket(key):
        out: Dict[str, List[float]] = {}
        for r in rows:
            out.setdefault(str(r.get(key) or "—"), []).append(float(r["leadership_score"]))
        return sorted(
            [{"key": k, "label": LEVEL_LABELS.get(k, k), "leaders": len(v),
              "average": _round(sum(v) / len(v)),
              "lowest": _round(min(v)), "highest": _round(max(v))}
             for k, v in out.items()],
            key=lambda x: x["key"])

    # Bands start at 20, not 0: with options worth 1/2/4/5 the lowest attainable score is
    # 20/100, so a 0-20 band could never contain anybody and would make the spread look
    # healthier than it is.
    edges = [(20, 40, "Needs attention"), (40, 55, "Developing"),
             (55, 70, "On track"), (70, 85, "Strong"), (85, 100.01, "Exemplary")]
    bands = [{"band": label, "from": lo, "to": int(hi),
              "leaders": len([r for r in rows if lo <= r["leadership_score"] < hi])}
             for lo, hi, label in edges]

    history = await get_collection(COLL_LS_SCORES).find(
        {"company_id": str(company_id)}).to_list(2000)
    per_cycle: Dict[str, List[float]] = {}
    for r in history:
        if r.get("leadership_score") is not None:
            per_cycle.setdefault(str(r.get("cycle")), []).append(float(r["leadership_score"]))
    trend = sorted([{"cycle": c, "cycle_label": cycle_label(c), "leaders": len(v),
                     "average": _round(sum(v) / len(v))}
                    for c, v in per_cycle.items()], key=lambda x: x["cycle"])

    scores = [r["leadership_score"] for r in rows]
    return {
        "cycle": query["cycle"],
        "cycle_label": cycle_label(query["cycle"]),
        "scored": len(rows),
        "average": _round(sum(scores) / len(scores)) if scores else None,
        "bands": bands,
        "by_level": bucket("level"),
        "by_department": bucket("department"),
        "trend": trend[-12:],
        "scale_note": ("Options are worth 1, 2, 4 or 5 — the source document awards no 3 — "
                       "so the lowest attainable score is 20, not 0."),
    }
