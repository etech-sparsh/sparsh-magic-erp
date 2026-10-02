"""HRMS > interviews and scorecard evaluation.

Schedules rounds, enforces the assessment gate, records structured evaluations and drives
the pass-chain to Selected.

-- Two independent checks on every advance ------------------------------------------
`PASS_NEXT` (models/hrms.py) says where a passed round INTENDS to send a candidate.
`FORWARD_TRANSITIONS` (Phase 5) says whether that move is LEGAL from where they actually
are. Both must agree. A single trusted table would let a stale round type push a candidate
somewhere the lifecycle forbids.

-- Row scoping ----------------------------------------------------------------------
Reading your OWN interviews is an inherent right, not a capability: an interviewer must be
able to see the interview they were booked for, and that must not be revocable by a
permission edit. `interview.read` WIDENS the list; it does not unlock it.

  HR / MD / ADMIN / INTERNAL   every interview in the company
  MANAGER                      their own interviews + candidates on requisitions they raised
  EMPLOYEE / anyone else       only interviews where they are the interviewer

-- Phase INT-2: interview governance (SOP §5) -----------------------------------------
Three rules were added, and all three are INTERNAL-TRACK ONLY. A client-track booking is
byte-for-byte the call it always was: every one of the functions below returns immediately
for a client requisition, before it reads anything.

  1. PANEL COMPOSITION. HR + the Department Head for junior and mid roles, plus Management
     for senior and managerial ones. Read from REQUIRED_PANEL_ROLES, not branched -- and a
     panel missing a role is a 422 that NAMES the missing roles, because "invalid panel" is
     a message somebody has to guess their way out of.
  2. THE MANDATORY MANAGEMENT FINAL ROUND. For managerial and above, `Selected` is
     unreachable without an evaluated MD Round that passed. Checked at the point the round
     is evaluated AND again at offer creation, so a hand-set status cannot route around it.
  3. CONFLICT OF INTEREST. A panel member who has recused themselves may not submit a
     scorecard. Declaring a conflict is not disqualifying; standing down is what removes it,
     and having stood down you do not then score the person.

One person cannot cover two role-slots. The MD holds every capability on this track, so
without that check a single MD would satisfy "HR + HOD + Management" alone -- which is the
same failure a two-stage approval one person completes has, and it is refused here with the
same reasoning hrms_scorecard_service refuses it on a managerial scorecard.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    INTERVIEW_NOTICE_HOURS,
    AUDIT_INTERVIEW_CANCELLED, AUDIT_INTERVIEW_EVALUATED, AUDIT_INTERVIEW_RESCHEDULED,
    AUDIT_INTERVIEW_SCHEDULED, AUDIT_INTERVIEW_UPDATED, AUDIT_STAGE_CHANGED,
    COLL_CANDIDATES, COLL_INTERVIEWS, COLL_REQUISITIONS, COMPETENCY_KEYS,
    DEFAULT_DURATION_MIN, DURATION_STEP_MIN, ENTITY_CANDIDATE, ENTITY_INTERVIEW,
    MAX_SCORE, MIN_DURATION_MIN, MIN_SCORE, OUTCOME_STATUS, PASS_NEXT,
    PRE_ASSESSMENT_STATUSES, AppStatus, Cap, HrmsRole, InterviewMode, InterviewRound,
    InterviewStatus, Outcome, can_transition,
)
# ── Phase INT-2 ── interview governance (SOP §5).
from app.models.hrms import (
    COLL_DESIGNATIONS, COLL_INTERVIEW_WINDOWS, FINAL_ROUND, FINAL_ROUND_PASSING, WEEKDAYS,
    REQUISITION_TRACK_INTERNAL, designation_level, final_round_is_mandatory, required_panel_roles,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_ics import build_invite
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_user
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_public_guard import clean_text
from app.utils.hrms_access import tenant_member


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _parse_when(value: str) -> datetime:
    """Parse an ISO-8601 datetime. Naive input is treated as IST, matching the rest of HRMS."""
    from app.services.hrms_ics import IST
    if not value:
        raise HTTPException(status_code=422, detail="Pick a date and time.")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="That date and time could not be read. Use a full date and time.")
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed


def _validate_duration(value) -> int:
    try:
        duration = int(value if value is not None else DEFAULT_DURATION_MIN)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Duration must be a whole number of minutes.")
    if duration < MIN_DURATION_MIN:
        raise HTTPException(
            status_code=422, detail=f"Duration must be at least {MIN_DURATION_MIN} minutes.")
    if duration % DURATION_STEP_MIN:
        raise HTTPException(
            status_code=422,
            detail=f"Duration must be in {DURATION_STEP_MIN}-minute steps.")
    return duration


def _validate_place(mode, meeting_link, location) -> tuple:
    """Virtual needs a link, Offline needs a location. An interview nobody can find is not
    scheduled, it is only recorded."""
    mode = getattr(mode, "value", mode)
    link = clean_text(meeting_link, limit=500)
    place = clean_text(location, limit=300)
    if mode == InterviewMode.VIRTUAL.value:
        if not link:
            raise HTTPException(
                status_code=422, detail="A virtual interview needs a meeting link.")
        if not link.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422, detail="The meeting link must start with http:// or https://.")
        return mode, link, None
    if not place:
        raise HTTPException(
            status_code=422, detail="An in-person interview needs a location.")
    return mode, None, place


async def _resolve_interviewer(company_id: str, interviewer_id: str) -> dict:
    if not interviewer_id:
        raise HTTPException(status_code=422, detail="Choose who will take the interview.")
    person = await tenant_member(company_id, interviewer_id, {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
    if not person:
        raise HTTPException(
            status_code=422, detail="The interviewer must be a user of this company.")
    return person


def _person_name(doc: dict) -> str:
    return (doc.get("full_name")
            or f"{doc.get('first_name') or ''} {doc.get('last_name') or ''}".strip()
            or doc.get("email") or "Unknown")


# ─────────────────────────────────────────────────────────────
# Phase INT-2 — interview governance (SOP §5). Internal track only.
# ─────────────────────────────────────────────────────────────
def _is_internal(req: dict) -> bool:
    return (req or {}).get("requisition_track") == REQUISITION_TRACK_INTERNAL


async def _requisition_for(company_id: str, request_no: str) -> dict:
    if not request_no:
        return {}
    return await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)}) or {}


async def _level_for(company_id: str, req: dict):
    """The seniority band of a requisition's designation.

    Resolved from the designation MASTER rather than from anything on the requisition, for
    the reason the masters exist at all: a band typed onto one requisition would disagree
    with the next one for the same role. An unbanded designation reads as the default (mid),
    so nothing breaks on a row created before this phase.
    """
    designation_id = (req or {}).get("designation_id")
    if not designation_id:
        return designation_level(None)
    try:
        oid = ObjectId(str(designation_id))
    except (InvalidId, TypeError):
        return designation_level(None)
    row = await get_collection(COLL_DESIGNATIONS).find_one(
        {"_id": oid, "company_id": str(company_id)}, {"designation_level": 1, "name": 1})
    return designation_level(row)


async def _resolve_panel(company_id: str, panel) -> list:
    """Resolve panel entries to real users of this company, with their HRMS roles.

    Every member must be a user of the SAME company, exactly as `_resolve_interviewer`
    demands of the interviewer -- a panel drawn from another tenant is not a panel, it is a
    scoping hole. Their ROLE is resolved server-side from the user record; a caller cannot
    declare "this person counts as HR".
    """
    out = []
    for entry in panel or []:
        entry = dict(entry or {})
        user_id = str(entry.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=422, detail="Every panel member needs a user.")
        person = await tenant_member(company_id, user_id)
        if not person:
            raise HTTPException(
                status_code=422,
                detail="Every panel member must be a user of this company.")
        role = hrms_role(person)
        out.append({
            "user_id": user_id,
            "name": _person_name(person),
            "email": person.get("email"),
            # Stamped at scheduling time. If somebody's governance role changes next month,
            # the record still says who sat on the panel AS WHAT -- which is the question an
            # audit asks, and it cannot be answered by re-deriving it later.
            "role": role.value if role else None,
            "coi_declared": bool(entry.get("coi_declared")),
            "coi_relationship": clean_text(entry.get("coi_relationship"), limit=200),
            "recused": bool(entry.get("recused")),
        })
    return out


def assert_panel_composition(panel: list, level, *, round_name: str = None) -> None:
    """Refuse a panel that does not cover the roles this seniority band requires.

    Two independent conditions, and both matter:

      * every required ROLE is covered, and
      * by at least as many DIFFERENT PEOPLE as there are required roles.

    The second is not redundant. An MD holds every capability on this track, so a panel of
    one MD would otherwise satisfy "HR + HOD + Management" on their own -- one person wearing
    three hats is not a panel, it is an interview with extra paperwork. This is the same
    "two different users" rule hrms_scorecard_service applies to a managerial scorecard.

    A RECUSED member is counted as absent (SOP §11): somebody who has stood down over a
    conflict cannot also be the reason the panel is quorate.
    """
    required = required_panel_roles(level)
    active = [m for m in (panel or []) if not m.get("recused")]
    covered = {m.get("role") for m in active if m.get("role")}

    missing = [r.value for r in required if r.value not in covered]
    if missing:
        recused_note = ""
        if any(m.get("recused") for m in (panel or [])):
            recused_note = (" A recused member does not count towards the panel.")
        raise HTTPException(
            status_code=422,
            detail=(f"This role needs a panel covering "
                    f"{', '.join(r.value for r in required)}. Still missing: "
                    f"{', '.join(missing)}.{recused_note}"))

    people = {str(m.get("user_id")) for m in active if m.get("user_id")}
    if len(people) < len(required):
        raise HTTPException(
            status_code=422,
            detail=(f"A panel of {len(people)} cannot cover {len(required)} required roles. "
                    f"{', '.join(r.value for r in required)} must be "
                    f"{len(required)} different people -- one person holding two of the "
                    f"seats is not a panel."))


async def assert_final_round_complete(company_id: str, candidate: dict, req: dict) -> None:
    """SOP §5: managerial and above may not reach `Selected` without a passed MD round.

    Written as a TABLE ASSERTION in the spirit of `budget_approval_is_mandatory()`: the rule
    is read from `final_round_is_mandatory` and `FINAL_ROUND`, so a future change that made
    the MD round optional for managerial roles would fail this check loudly instead of
    quietly deleting the gate.

    Called from TWO places on purpose -- when a round is evaluated, and again when an offer
    is created. The second is what makes a hand-set `Selected` status useless as a way round
    it: the offer still asks whether the round happened.
    """
    if not _is_internal(req):
        return
    level = await _level_for(company_id, req)
    if not final_round_is_mandatory(level):
        return

    rounds = await get_collection(COLL_INTERVIEWS).find(
        {"company_id": str(company_id), "uk": candidate.get("uk"),
         "round": FINAL_ROUND.value},
        {"interview_no": 1, "outcome": 1, "status": 1}).to_list(50)
    passed = [r for r in rounds if r.get("outcome") in FINAL_ROUND_PASSING]
    if passed:
        return

    if rounds:
        detail = (f'{candidate.get("candidate_name")} has a {FINAL_ROUND.value} on record '
                  f'but it has not been passed. A "{level.value}" role needs a Management '
                  f"final interview with a Pass before the offer stage.")
    else:
        detail = (f'{candidate.get("candidate_name")} has not sat the {FINAL_ROUND.value}. '
                  f'A "{level.value}" role needs a final interview with Management before '
                  f"the offer stage (SOP section 5).")
    raise HTTPException(status_code=409, detail=detail)


async def interview_window_warning(company_id: str, req: dict, when: datetime) -> Optional[str]:
    """Whether this booking falls outside the department's batch interview windows.

    A WARNING, returned in the response, never a refusal. Annexure C asks for batching to
    reduce panel disruption; a hard block would make an urgent hire impossible at 4pm on a
    Friday, which is exactly when an urgent hire happens. So the caller is told, and the
    booking goes through.

    No windows defined at all means no warning: a company that has not opted into batching
    is not "always out of window".
    """
    department_id = (req or {}).get("department_id")
    if not department_id or when is None:
        return None
    windows = await get_collection(COLL_INTERVIEW_WINDOWS).find(
        {"company_id": str(company_id), "department_id": str(department_id),
         "active": True}).to_list(50)
    if not windows:
        return None

    from app.services.hrms_ics import IST
    local = when.astimezone(IST)
    weekday = WEEKDAYS[local.weekday()]
    clock = local.strftime("%H:%M")

    for w in windows:
        if w.get("weekday") != weekday:
            continue
        if str(w.get("start_time") or "") <= clock <= str(w.get("end_time") or ""):
            return None

    slots = ", ".join(
        f'{w.get("weekday")} {w.get("start_time")}-{w.get("end_time")}'
        for w in windows[:5])
    return (f"{weekday} {clock} is outside this department's interview windows ({slots}). "
            f"The booking has been made -- batching is a preference, not a rule.")


# -------------------------------------------------------------
# Scoping
# -------------------------------------------------------------
async def _scope_filter(actor: dict, company_id: str) -> dict:
    """The query clause limiting which interviews `actor` may see.

    Reading your own is never gated -- see the module docstring.
    """
    actor_id = str(actor.get("_id") or "")
    role = hrms_role(actor)

    if can(actor, Cap.INTERVIEW_READ) and role != HrmsRole.MANAGER:
        return {}

    clauses = [{"interviewer_id": actor_id}]
    if role == HrmsRole.MANAGER:
        rows = await get_collection(COLL_REQUISITIONS).find(
            {"company_id": str(company_id), "created_by": actor_id},
            {"request_no": 1}).to_list(2000)
        if rows:
            clauses.append({"request_no": {"$in": [r["request_no"] for r in rows]}})
    return {"$or": clauses}


async def _require_visible(actor: dict, company_id: str, interview_no: str) -> dict:
    query = {"interview_no": interview_no, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_INTERVIEWS).find_one(query)
    if not doc:
        # 404 rather than 403: a 403 would confirm the interview exists.
        raise HTTPException(status_code=404, detail="Interview not found.")
    return doc


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_interviews(actor: dict, company_id: str, *, status: str = None,
                          round_name: str = None, uk: str = None,
                          limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if status:
        query["status"] = status
    if round_name:
        query["round"] = round_name
    if uk:
        query["uk"] = uk

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_INTERVIEWS).find(query).sort(
        "scheduled_at", 1).limit(limit).to_list(limit)

    actor_id = str(actor.get("_id") or "")
    now = datetime.now(timezone.utc)
    today = now.date()
    out, stats = [], {"today": 0, "upcoming": 0, "completed": 0, "dropped": 0}

    for r in rows:
        item = _out(r)
        item["is_mine"] = str(r.get("interviewer_id") or "") == actor_id
        # Whether THIS caller may evaluate is decided server-side, so the UI never offers a
        # button the API will refuse.
        item["can_evaluate"] = _may_evaluate(actor, r)
        when = r.get("scheduled_at")
        if isinstance(when, datetime):
            aware = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            item["day"] = aware.date().isoformat()
            if r.get("status") == InterviewStatus.SCHEDULED.value:
                if aware.date() == today:
                    stats["today"] += 1
                elif aware.date() > today:
                    stats["upcoming"] += 1
        if r.get("status") == InterviewStatus.COMPLETED.value:
            stats["completed"] += 1
        elif r.get("status") in (InterviewStatus.CANCELLED.value,
                                 InterviewStatus.NO_SHOW.value):
            stats["dropped"] += 1
        out.append(item)

    return {"interviews": out, "total": len(out), "stats": stats}


def _may_evaluate(actor: dict, doc: dict) -> bool:
    """Who may score this interview.

    The assigned interviewer, or anyone holding `interview.evaluate` within scope. An MD
    round additionally requires `interview.decide_md` -- the final call is the MD's,
    whoever happens to have conducted the conversation.
    """
    if doc.get("round") == InterviewRound.MD.value and not can(actor, Cap.INTERVIEW_DECIDE_MD):
        return False
    if str(doc.get("interviewer_id") or "") == str(actor.get("_id") or ""):
        return True
    return can(actor, Cap.INTERVIEW_EVALUATE)


async def schedulable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who may be booked for an interview.

    Excludes terminal stages, and any candidate whose role requires an assessment they have
    not yet passed. The picker and the server apply the SAME rule, so the UI cannot offer
    somebody the API will refuse.
    """
    rows = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id)}).sort("created_at", -1).to_list(1000)
    out = []
    for r in rows:
        status = r.get("application_status")
        if not _is_schedulable(r):
            continue
        out.append({"uk": r["uk"], "candidate_name": r.get("candidate_name"),
                    "application_status": status, "request_no": r.get("request_no"),
                    "requires_assessment": bool(r.get("requires_assessment"))})
    return out


def _is_schedulable(candidate: dict) -> bool:
    status = candidate.get("application_status")
    try:
        current = AppStatus(status)
    except ValueError:
        return False
    if current in (AppStatus.REJECTED, AppStatus.DUPLICATE, AppStatus.OFFER_DECLINED,
                   AppStatus.EMPLOYEE_CREATED, AppStatus.PROBATION_CONFIRMED):
        return False
    if candidate.get("requires_assessment") and current in PRE_ASSESSMENT_STATUSES:
        return False
    # The lifecycle graph is the final word: an interview only makes sense from a stage that
    # can legally reach Interview Scheduled (or is already in the interview chain).
    return (can_transition(status, AppStatus.INTERVIEW_SCHEDULED.value)
            or current in (AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                           AppStatus.MD_ROUND))


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def schedule_interview(actor: dict, company_id: str, payload: dict) -> dict:
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    status = candidate.get("application_status")
    # THE ASSESSMENT GATE. Enforced here as well as in the picker, because the picker is a
    # convenience and this is the boundary.
    if candidate.get("requires_assessment"):
        try:
            current = AppStatus(status)
        except ValueError:
            current = None
        if current in PRE_ASSESSMENT_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(f'{candidate.get("candidate_name")} is at "{status}". This role '
                        f'requires an assessment, so interviews can only be scheduled once '
                        f'they reach "{AppStatus.ASSESSMENT_PASSED.value}".'))
    if not _is_schedulable(candidate):
        raise HTTPException(
            status_code=409,
            detail=f'{candidate.get("candidate_name")} is at "{status}" and cannot be interviewed.')

    raw_round = getattr(payload.get("round"), "value", payload.get("round")) \
        or InterviewRound.HR.value
    try:
        round_name = InterviewRound(raw_round).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Round must be one of: {', '.join(r.value for r in InterviewRound)}.")

    when = _parse_when(payload.get("scheduled_at"))
    if when < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(
            status_code=422, detail="An interview cannot be scheduled in the past.")

    duration = _validate_duration(payload.get("duration_min"))
    mode, link, location = _validate_place(
        payload.get("mode") or InterviewMode.VIRTUAL, payload.get("meeting_link"),
        payload.get("location"))
    interviewer = await _resolve_interviewer(company_id, payload.get("interviewer_id"))

    # ── Phase INT-2 ── panel composition (SOP §5). Everything below is checked BEFORE
    # anything is written, so a refused panel cannot leave a half-booked interview behind --
    # the same all-or-nothing rule the offer service follows.
    req = await _requisition_for(company_id, candidate.get("request_no"))
    panel = await _resolve_panel(company_id, payload.get("panel"))
    window_warning = None
    if _is_internal(req):
        # ── Phase INT-4 ── the telephonic gate (SOP step 5). Asked first, because it is the
        # cheapest refusal to act on: being told to make a ten-minute call is better than
        # being told the panel is wrong after assembling one. Silent once the candidate is
        # already being interviewed, so an in-flight pipeline is never gated retroactively.
        from app.services.hrms_telephonic_service import assert_telephonic_cleared
        await assert_telephonic_cleared(company_id, candidate, req)

        level = await _level_for(company_id, req)
        assert_panel_composition(panel, level, round_name=round_name)
        window_warning = await interview_window_warning(company_id, req, when)

    year = datetime.now(timezone.utc).year
    interview_no = await next_business_id("interview", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "interview_no": interview_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "request_no": candidate.get("request_no"),
        "round": round_name,
        "mode": mode,
        "scheduled_at": when,
        "duration_min": duration,
        "interviewer_id": str(interviewer["_id"]),
        "interviewer_name": _person_name(interviewer),
        "interviewer_email": interviewer.get("email"),
        "meeting_link": link,
        "location": location,
        "notes": clean_text(payload.get("notes"), limit=2000),
        # ── Phase INT-2 ── who else is in the room, with their role stamped as it stood.
        # Empty on the client track and on any booking made before this phase, which is
        # exactly what `assert_panel_composition` reads as "no panel" -- and it is never
        # asked about a client requisition.
        "panel": panel,
        "status": InterviewStatus.SCHEDULED.value,
        "outcome": None,
        # Incremented on every reschedule so a calendar client treats the new invite as an
        # update to the same booking rather than a second one.
        "ics_sequence": 0,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
    }
    # ── Phase INT-10 ── Annexure C asks for logistics at least 24 hours ahead. Recorded
    # rather than enforced (a hard refusal would push a Friday-for-Monday booking
    # off-system), so it can be warned about now and measured later. INTERNAL TRACK ONLY,
    # like every other Annexure control: a client-track booking carries no new keys.
    if _is_internal(req):
        doc["notice_hours"] = _notice_hours(when, now)
        doc["short_notice"] = doc["notice_hours"] < INTERVIEW_NOTICE_HOURS
    await get_collection(COLL_INTERVIEWS).insert_one(dict(doc))

    if can_transition(status, AppStatus.INTERVIEW_SCHEDULED.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": uk, "company_id": str(company_id)},
            {"$set": {"application_status": AppStatus.INTERVIEW_SCHEDULED.value,
                      "updated_at": now}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{status} -> {AppStatus.INTERVIEW_SCHEDULED.value}", company_id)

    await audit(actor, AUDIT_INTERVIEW_SCHEDULED, ENTITY_INTERVIEW, interview_no,
                f"{round_name} for {candidate.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_INTERVIEW_SCHEDULED, ENTITY_CANDIDATE, uk,
                f"{interview_no}: {round_name}", company_id)
    await _notify_scheduled(doc, rescheduled=False)
    told = None
    if _is_internal(req):
        told = await _tell_candidate(actor, company_id, doc)
        await get_collection(COLL_INTERVIEWS).update_one(
            {"interview_no": interview_no, "company_id": str(company_id)},
            {"$set": {"candidate_notified": told}})
        doc["candidate_notified"] = told
    out = _out(doc)
    # Surfaced, not enforced. Present only when there IS one, so a caller can render it
    # without first deciding whether an empty string means "fine" or "unchecked".
    warnings = [w for w in (window_warning, _short_notice_warning(doc, told)) if w]
    if warnings:
        out["warning"] = " ".join(warnings)
    return out


def _as_utc(value) -> Optional[datetime]:
    """A datetime as aware UTC. Mongo hands back NAIVE UTC through this client; the API
    hands in AWARE IST -- compared raw, the same instant reads as two different times."""
    if not isinstance(value, datetime):
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _moment_changed(when: datetime, stored) -> bool:
    """Whether `when` is a different instant from the stored time, to the millisecond.

    Without normalising, a PATCH that merely echoed the unchanged time was a "reschedule":
    the ICS sequence bumped, the interviewer was re-notified and the candidate re-emailed.
    """
    previous = _as_utc(stored)
    if previous is None:
        return True
    return int(_as_utc(when).timestamp() * 1000) != int(previous.timestamp() * 1000)


def _when_text(when) -> str:
    """The interview time in the ERP's operating zone, labelled as such."""
    from app.services.hrms_ics import IST
    moment = _as_utc(when)
    if moment is None:
        return str(when)
    return moment.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def _notice_hours(when, now) -> float:
    """Hours between booking and interview, to one decimal. Negative if already past."""
    try:
        return round((_as_utc(when) - _as_utc(now)).total_seconds() / 3600.0, 1)
    except (TypeError, AttributeError):
        return 0.0


def _short_notice_warning(doc: dict, told: Optional[str] = None) -> Optional[str]:
    """The warning, worded by what actually happened rather than by what was attempted."""
    if not doc.get("short_notice"):
        return None
    head = (f"Short notice: this interview is {doc.get('notice_hours')} hours away. Annexure "
            f"C asks for logistics to be confirmed at least {INTERVIEW_NOTICE_HOURS} hours "
            f"ahead. ")
    if told == "Sent":
        return head + "A confirmation has been emailed to the candidate."
    return (head + f"The candidate has NOT been emailed"
            + (f" ({told.lower()})" if told else "")
            + " -- confirm the logistics by phone.")


async def _tell_candidate(actor: dict, company_id: str, doc: dict) -> Optional[str]:
    """The candidate's own confirmation (Annexure C), through the communications log.

    Returns the log row's status (`Sent` / `Skipped` / `Failed`) or None, so the caller can
    SAY what happened. `fire_event` swallows every delivery problem -- a failed email must
    never fail a booking -- and logs the attempt, so "did we tell them" is answerable later
    from one place.
    """
    from app.services.hrms_comm_service import fire_event
    where = doc.get("meeting_link") or doc.get("location") or doc.get("mode") or ""
    row = await fire_event(actor, company_id, doc.get("uk"), "interview_scheduled",
                           variables={"round": doc.get("round"),
                                      "when": _when_text(doc.get("scheduled_at")),
                                      "where": where})
    return (row or {}).get("status")


async def _notify_scheduled(doc: dict, *, rescheduled: bool) -> None:
    verb = "rescheduled" if rescheduled else "scheduled"
    when_text = _when_text(doc["scheduled_at"])
    where = doc.get("meeting_link") or doc.get("location") or ""
    await notify_user(
        doc["interviewer_id"],
        f"Interview {verb}: {doc.get('candidate_name')}",
        f"{doc['round']} on {when_text} ({doc['duration_min']} min). {where}".strip(),
        link="/hrms/interviews", email=True)


def invite_for(doc: dict, *, cancelled: bool = False) -> str:
    """The RFC 5545 invite for one interview."""
    where = doc.get("location") or doc.get("meeting_link") or ""
    description = (f"Round: {doc.get('round')}\n"
                   f"Mode: {doc.get('mode')}\n"
                   f"Interviewer: {doc.get('interviewer_name') or ''}")
    if doc.get("notes"):
        description += f"\nNotes: {doc['notes']}"
    when = doc["scheduled_at"]
    if not isinstance(when, datetime):
        when = _parse_when(str(when))
    return build_invite(
        uid=f"{doc['interview_no']}@sparsh-hrms",
        summary=f"{doc.get('round')}: {doc.get('candidate_name')}",
        start=when,
        duration_min=doc.get("duration_min") or DEFAULT_DURATION_MIN,
        description=description,
        location=where,
        url=doc.get("meeting_link"),
        attendee_emails=[e for e in (doc.get("interviewer_email"),
                                     doc.get("candidate_email")) if e],
        sequence=int(doc.get("ics_sequence") or 0),
        cancelled=cancelled,
    )


async def update_interview(actor: dict, company_id: str, interview_no: str,
                           payload: dict) -> dict:
    """Reschedule, change the venue, or set a status."""
    current = await _require_visible(actor, company_id, interview_no)
    if not (can(actor, Cap.INTERVIEW_SCHEDULE)
            or str(current.get("interviewer_id") or "") == str(actor.get("_id") or "")):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned interviewer or a scheduler can change this interview.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview has been cancelled.")

    updates, rescheduled = {}, False

    if payload.get("scheduled_at") is not None:
        when = _parse_when(payload["scheduled_at"])
        if when < datetime.now(timezone.utc) - timedelta(minutes=1):
            raise HTTPException(
                status_code=422, detail="An interview cannot be moved into the past.")
        if _moment_changed(when, current.get("scheduled_at")):
            updates["scheduled_at"] = when
            updates["ics_sequence"] = int(current.get("ics_sequence") or 0) + 1
            updates["status"] = InterviewStatus.SCHEDULED.value
            rescheduled = True

    if payload.get("duration_min") is not None:
        updates["duration_min"] = _validate_duration(payload["duration_min"])

    if payload.get("mode") is not None or payload.get("meeting_link") is not None \
            or payload.get("location") is not None:
        mode = payload.get("mode") or current.get("mode")
        mode, link, location = _validate_place(
            mode,
            payload.get("meeting_link", current.get("meeting_link")),
            payload.get("location", current.get("location")))
        updates.update({"mode": mode, "meeting_link": link, "location": location})

    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)

    # ── Phase INT-2 ── the panel may legitimately change: somebody is away, or declares a
    # conflict and stands down. The composition rule is therefore re-checked on every edit,
    # so a panel cannot be quietly edited down below what the SOP requires after the booking
    # was made -- which would make the check at scheduling time a formality.
    if payload.get("panel") is not None:
        req = await _requisition_for(company_id, current.get("request_no"))
        panel = await _resolve_panel(company_id, payload["panel"])
        if _is_internal(req):
            assert_panel_composition(panel, await _level_for(company_id, req),
                                     round_name=current.get("round"))
        updates["panel"] = panel

    if payload.get("status") is not None:
        raw = getattr(payload["status"], "value", payload["status"])
        try:
            new_status = InterviewStatus(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid interview status.")
        if new_status == InterviewStatus.COMPLETED and not current.get("outcome"):
            # Completed without a scorecard would leave the candidate stranded mid-chain
            # with no record of why.
            raise HTTPException(
                status_code=409,
                detail="Record the evaluation to mark this interview completed.")
        updates["status"] = new_status.value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)}, {"$set": updates})

    action = AUDIT_INTERVIEW_RESCHEDULED if rescheduled else AUDIT_INTERVIEW_UPDATED
    await audit(actor, action, ENTITY_INTERVIEW, interview_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    fresh = await get_collection(COLL_INTERVIEWS).find_one({"interview_no": interview_no})
    told = None
    if rescheduled:
        await _notify_scheduled(fresh, rescheduled=True)
        # ── Phase INT-10 ── a moved interview is a new notice period and a new set of
        # logistics the candidate has not been told. Internal track only, as at booking.
        req = await _requisition_for(company_id, current.get("request_no"))
        if _is_internal(req):
            moved_at = datetime.now(timezone.utc)
            stamps = {"notice_hours": _notice_hours(fresh.get("scheduled_at"), moved_at)}
            stamps["short_notice"] = stamps["notice_hours"] < INTERVIEW_NOTICE_HOURS
            fresh.update(stamps)
            told = await _tell_candidate(actor, company_id, fresh)
            stamps["candidate_notified"] = told
            fresh["candidate_notified"] = told
            await get_collection(COLL_INTERVIEWS).update_one(
                {"interview_no": interview_no, "company_id": str(company_id)},
                {"$set": stamps})
    out = _out(fresh)
    warning = _short_notice_warning(fresh, told) if rescheduled else None
    if warning:
        out["warning"] = warning
    return out


async def cancel_interview(actor: dict, company_id: str, interview_no: str) -> dict:
    """Cancel an interview.

    Marked Cancelled rather than deleted: the fact that a round was booked and dropped is
    part of the hiring record, and Phase 5's journey reads it.
    """
    current = await _require_visible(actor, company_id, interview_no)
    if not can(actor, Cap.INTERVIEW_SCHEDULE):
        raise HTTPException(status_code=403, detail="You may not cancel interviews.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview is already cancelled.")

    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)},
        {"$set": {"status": InterviewStatus.CANCELLED.value,
                  "ics_sequence": int(current.get("ics_sequence") or 0) + 1,
                  "cancelled_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_INTERVIEW_CANCELLED, ENTITY_INTERVIEW, interview_no,
                current.get("round"), company_id)
    await notify_user(
        current["interviewer_id"], f"Interview cancelled: {current.get('candidate_name')}",
        f"The {current.get('round')} has been cancelled.", kind="warning",
        link="/hrms/interviews", email=True)
    return {"cancelled": True, "interview_no": interview_no}


async def evaluate_interview(actor: dict, company_id: str, interview_no: str,
                             payload: dict) -> dict:
    """Record the scorecard and advance the candidate."""
    current = await _require_visible(actor, company_id, interview_no)

    if current.get("round") == InterviewRound.MD.value and not can(actor, Cap.INTERVIEW_DECIDE_MD):
        raise HTTPException(
            status_code=403,
            detail="Only the MD can record the decision for an MD round.")
    if not _may_evaluate(actor, current):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned interviewer or an authorised evaluator can score this.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview was cancelled.")
    if current.get("outcome"):
        raise HTTPException(
            status_code=409, detail="This interview has already been evaluated.")

    # ── Phase INT-2, SOP §11 ── a recused panel member may not score the candidate.
    # Standing down over a conflict and then submitting a scorecard is not standing down.
    # Checked against the stored panel, not the request, so it cannot be sidestepped by
    # omitting the flag on this call.
    actor_id = str(actor.get("_id") or "")
    recused = next((m for m in (current.get("panel") or [])
                    if str(m.get("user_id")) == actor_id and m.get("recused")), None)
    if recused:
        raise HTTPException(
            status_code=422,
            detail=(f'You recused yourself from this panel'
                    + (f' ({recused.get("coi_relationship")})'
                       if recused.get("coi_relationship") else "")
                    + ". A member who has stood down cannot score the candidate."))

    raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
    try:
        outcome = Outcome(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Decision must be Pass, Fail or Hold.")

    signature = clean_text(payload.get("signature"), limit=120)
    if not signature:
        # The source left this optional despite the UI implying otherwise
        # (BACKEND_ANALYSIS 8). An unsigned evaluation that later justifies a rejection is
        # exactly the record you want attributable.
        raise HTTPException(
            status_code=422, detail="Type your name to sign this evaluation.")

    scores = {}
    for key in COMPETENCY_KEYS:
        value = payload.get(key, 0)
        try:
            score = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key}: score must be a whole number.")
        if score < MIN_SCORE or score > MAX_SCORE:
            raise HTTPException(
                status_code=422,
                detail=f"{key}: score must be between {MIN_SCORE} and {MAX_SCORE}.")
        scores[f"score_{key}"] = score

    now = datetime.now(timezone.utc)
    average = round(sum(scores.values()) / len(scores), 2) if scores else 0

    # Conditional on the outcome still being unset: two evaluators submitting at once must
    # not both write.
    result = await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id), "outcome": None},
        {"$set": {**scores, "outcome": outcome.value, "average_score": average,
                  "eval_remarks": clean_text(payload.get("remarks"), limit=4000),
                  "eval_signature": signature,
                  "eval_by": str(actor.get("_id") or ""), "eval_by_name": _actor_name(actor),
                  "eval_at": now, "status": InterviewStatus.COMPLETED.value,
                  "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="This interview has already been evaluated.")

    await audit(actor, AUDIT_INTERVIEW_EVALUATED, ENTITY_INTERVIEW, interview_no,
                f"{current.get('round')}: {outcome.value} (avg {average})", company_id)

    await _advance_candidate(actor, company_id, current, outcome)

    fresh = await get_collection(COLL_INTERVIEWS).find_one({"interview_no": interview_no})
    return _out(fresh)


async def _advance_candidate(actor: dict, company_id: str, interview: dict,
                             outcome: Outcome) -> None:
    """Move the candidate per PASS_NEXT, re-checked against the lifecycle graph."""
    uk = interview["uk"]
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        return
    current_status = candidate.get("application_status")

    if outcome == Outcome.PASS:
        try:
            target = PASS_NEXT[InterviewRound(interview.get("round"))]
        except (ValueError, KeyError):
            return
    else:
        target = OUTCOME_STATUS[outcome]

    # Second, independent check: PASS_NEXT says where to go, the graph says whether it is
    # legal from where the candidate actually is.
    if not can_transition(current_status, target.value):
        await audit(actor, AUDIT_INTERVIEW_EVALUATED, ENTITY_CANDIDATE, uk,
                    f"outcome {outcome.value}; stage left at {current_status} "
                    f"(no legal move to {target.value})", company_id)
        return

    # ── Phase INT-2 ── the §5 gates on `Selected`. A passed MD round is the usual road to
    # Selected, so this normally passes trivially -- but the shortlisting-committee check
    # does not, and this is the path that would otherwise skip it.
    #
    # The EVALUATION IS ALREADY RECORDED at this point and must stay recorded: an interview
    # that happened, happened, and rolling it back because a committee record is missing
    # would lose the scorecard somebody just wrote. So a refusal here leaves the candidate
    # where they are and says why, in the audit trail, rather than raising.
    if target is AppStatus.SELECTED:
        from app.services.hrms_candidate_service import assert_selectable
        try:
            await assert_selectable(actor, company_id, candidate)
        except HTTPException as e:
            await audit(actor, AUDIT_INTERVIEW_EVALUATED, ENTITY_CANDIDATE, uk,
                        f"passed {interview.get('round')}; NOT selected -- {e.detail}",
                        company_id)
            if interview.get("interviewer_id"):
                await notify_user(
                    interview["interviewer_id"],
                    f"{interview.get('candidate_name')} passed, but is not Selected",
                    str(e.detail), kind="warning", link="/hrms/candidates")
            return

    now = datetime.now(timezone.utc)
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {"application_status": target.value,
                  # Stamped on the candidate as a first-class timestamp, not left to be
                  # parsed back out of the audit trail's prose later.
                  **({"selected_at": now} if target is AppStatus.SELECTED else {}),
                  "updated_at": now}})
    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                f"{current_status} -> {target.value}", company_id)

    # ── Internal track ── SOP §8 measures "offer released" from FINAL SELECTION, so the
    # clock for that milestone starts here. First selection on the requisition only: a
    # second person selected later does not restart the deadline for the first offer.
    if target is AppStatus.SELECTED and interview.get("request_no"):
        from app.services.hrms_sla_service import stamp_if_internal
        await stamp_if_internal(actor, company_id, interview["request_no"],
                                "final_selection", when=now)

    if interview.get("interviewer_id"):
        await notify_user(
            interview["interviewer_id"],
            f"{interview.get('candidate_name')}: {outcome.value}",
            f"The {interview.get('round')} outcome was recorded. "
            f"Candidate is now {target.value}.",
            link="/hrms/candidates")
