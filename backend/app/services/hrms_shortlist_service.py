"""HRMS > the internal shortlisting committee (internal recruitment track, SOP §5).

"HR and the Department Head shall jointly finalise the shortlist before the final
interview."

-- Why this needed a record ----------------------------------------------------------------
Until this phase the act existed and the decision did not. HR shortlisted candidates, the HOD
was consulted somewhere off-system, and the pipeline moved. Nothing recorded WHO agreed, on
WHICH candidates, or on what evidence -- so "we jointly finalised the shortlist" was a claim
the module could neither support nor contradict.

That matters most in the case the SOP is actually worried about: a candidate progressed to a
final interview that the department head never agreed to see. With a record, that is a gap
somebody can point at. Without one it is an argument about memory.

-- Two ROLES and two PEOPLE ----------------------------------------------------------------
SOP §5 requires HR and the Department Head. Both must be covered, and by two DIFFERENT
people, for exactly the reason hrms_scorecard_service refuses a managerial scorecard signed
twice by one person: an MD holds every capability on this track, so without the second check
one person could convene, agree with themselves and call it a committee.

Finance is deliberately absent from the capability grant. Finance approves what a role costs;
it never decides who fills it, and this record is entirely about who fills it.

-- What it gates, and how narrowly ---------------------------------------------------------
On the internal track, `Selected` requires a FINALISED committee record naming that
candidate. The gate is deliberately at `Selected` rather than at the final interview: booking
a conversation is cheap and reversible, and blocking it would push scheduling off-system,
which is how a control stops being one. Selection is the commitment.

Bypassed only by an approved `Relaxed Scorecard` exception -- there is no override flag, the
same rule every other gate on this track follows.

-- Internal track only ---------------------------------------------------------------------
A client-track requisition never has one. The client owns the shortlist there, and their
verdict is already recorded as a client-share response.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SHORTLIST_CONVENED, AUDIT_SHORTLIST_DECIDED, AUDIT_STAGE_CHANGED, AppStatus,
    COLL_CANDIDATES, COLL_INTERVIEWS, COLL_POSITION_SCORECARDS, COLL_REQUISITIONS,
    COLL_SHORTLIST_REVIEWS, ENTITY_CANDIDATE, ENTITY_SHORTLIST, FINAL_ROUND,
    FINAL_ROUND_PASSING, RETENTION_YEARS, SHORTLIST_CLEARS_SELECTION,
    SHORTLIST_COMMITTEE_ROLES, SHORTLIST_LIVE_OUTCOMES, SHORTLIST_MIN_MEMBERS,
    CommitteeDecision, REQUISITION_TRACK_INTERNAL, ShortlistOutcome, can_transition,
    final_commit_outcome, score_band,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role
from app.utils.hrms_public_guard import clean_text
from app.utils.hrms_access import tenant_member

MAX_COMMITTEE_MEMBERS = 10
MAX_SHORTLIST_CANDIDATES = 100


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _add_years(iso_date: str, years: int) -> str:
    """`iso_date` plus N years, clamped for 29 February. Pure."""
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


async def _require_internal_requisition(company_id: str, request_no: str) -> dict:
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That requisition does not exist for this company.")
    track = req.get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        raise HTTPException(
            status_code=409,
            detail=f"{request_no} is a legacy client-track requisition and is not part of hiring any more.")
    return req


# -------------------------------------------------------------
# Committee composition
# -------------------------------------------------------------
async def _resolve_members(company_id: str, members) -> list:
    """Resolve committee entries to users of this company, with their roles stamped.

    The role is resolved SERVER-SIDE from the user record. A caller cannot declare that
    somebody "counts as HR" any more than they can declare their own capabilities.
    """
    if not isinstance(members, list):
        raise HTTPException(status_code=422, detail="Name the committee members.")
    if len(members) > MAX_COMMITTEE_MEMBERS:
        raise HTTPException(
            status_code=422,
            detail=f"A committee of more than {MAX_COMMITTEE_MEMBERS} is a meeting, not a "
                   f"committee.")

    out, seen = [], set()
    for entry in members:
        entry = dict(entry or {})
        user_id = str(entry.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=422, detail="Every member needs a user.")
        if user_id in seen:
            raise HTTPException(
                status_code=422,
                detail="The same person is listed twice on this committee.")
        seen.add(user_id)
        person = await tenant_member(company_id, user_id)
        if not person:
            raise HTTPException(
                status_code=422,
                detail="Every committee member must be a user of this company.")

        raw_decision = getattr(entry.get("decision"), "value", entry.get("decision"))
        try:
            decision = CommitteeDecision(raw_decision or CommitteeDecision.AGREE.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"A member's decision must be one of: "
                        f"{', '.join(d.value for d in CommitteeDecision)}."))

        role = hrms_role(person)
        out.append({
            "user_id": user_id,
            "name": (person.get("full_name") or person.get("email") or "Unknown"),
            # Stamped as it stood. If somebody's governance role changes next quarter the
            # record still says who sat AS WHAT, which is the question an audit asks.
            "role": role.value if role else None,
            "decision": decision.value,
            "remarks": clean_text(entry.get("remarks"), limit=2000),
            # ── SOP §11 conflict of interest ──
            "coi_declared": bool(entry.get("coi_declared")),
            "coi_relationship": clean_text(entry.get("coi_relationship"), limit=200),
            "recused": bool(entry.get("recused")),
        })
    return out


def committee_state(members: list) -> dict:
    """Who is covered, who is missing, and whether that is a committee at all.

    A RECUSED member counts as absent, exactly as they do on an interview panel: somebody
    who stood down over a conflict cannot also be the reason the committee is quorate.

    Returned rather than raised, so a screen can show "still needed: manager" while the
    record is being assembled and only the finalisation is refused.
    """
    active = [m for m in (members or []) if not m.get("recused")]
    covered = {m.get("role") for m in active if m.get("role")}
    people = {str(m.get("user_id")) for m in active if m.get("user_id")}

    outstanding = [r.value for r in SHORTLIST_COMMITTEE_ROLES if r.value not in covered]
    complete = not outstanding and len(people) >= SHORTLIST_MIN_MEMBERS
    if not outstanding and len(people) < SHORTLIST_MIN_MEMBERS:
        outstanding = ["a second, independent member"]
    return {
        "required_roles": [r.value for r in SHORTLIST_COMMITTEE_ROLES],
        "covered_roles": sorted(r for r in covered if r),
        "outstanding_roles": outstanding,
        "member_count": len(people),
        "objections": [m.get("name") for m in active
                       if m.get("decision") == CommitteeDecision.OBJECT.value],
        "complete": complete,
    }


def assert_committee_complete(members: list) -> None:
    """Refuse to FINALISE a shortlist the SOP's committee has not actually formed."""
    state = committee_state(members)
    if state["complete"]:
        return
    raise HTTPException(
        status_code=422,
        detail=(f"A shortlisting committee needs "
                f"{', '.join(state['required_roles'])} — two different people. Still "
                f"needed: {', '.join(state['outstanding_roles'])}."))


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_shortlist_reviews(actor: dict, company_id: str, *, request_no: str = None,
                                 outcome: str = None, uk: str = None,
                                 limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if request_no:
        query["request_no"] = request_no
    if outcome:
        query["outcome"] = outcome
    if uk:
        query["candidate_uks"] = uk
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_SHORTLIST_REVIEWS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [{**_out(r), "committee_state": committee_state(r.get("committee_members"))}
           for r in rows]
    return {
        "shortlist_reviews": out,
        "total": len(out),
        # What a governance screen leads with: sittings that were convened and never decided.
        "pending": sum(1 for r in out
                       if r.get("outcome") == ShortlistOutcome.PENDING.value),
    }


async def get_shortlist_review(company_id: str, slr_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_SHORTLIST_REVIEWS).find_one(
        {"slr_no": slr_no, "company_id": str(company_id)})
    if not doc:
        return None
    out = _out(doc)
    out["committee_state"] = committee_state(doc.get("committee_members"))

    # A sitting that has not been decided carries a LIVE preview of what committing now
    # would produce; a decided one carries the rationale frozen at the moment it was
    # decided. The screen renders whichever is present, so it never has to ask the user for
    # a conclusion it can work out itself.
    if doc.get("outcome") == ShortlistOutcome.PENDING.value:
        state = out["committee_state"]
        if state.get("complete") and doc.get("candidate_uks"):
            req = await get_collection(COLL_REQUISITIONS).find_one(
                {"request_no": doc.get("request_no"),
                 "company_id": str(company_id)}) or {}
            out["commit_preview"] = await commit_preview(
                company_id, req, doc.get("committee_members"), doc.get("candidate_uks"))
    return out


# -------------------------------------------------------------
# The gate
# -------------------------------------------------------------
async def assert_shortlist_cleared(company_id: str, candidate: dict, req: dict) -> None:
    """Refuse to select an internal candidate no committee has finalised (SOP §5).

    Silent on the client track and on a candidate with no requisition -- there is no
    committee to have sat, and refusing would strand a walk-in CV nobody attached to a
    vacancy.

    Bypassed only by an approved `Relaxed Scorecard` exception. Progressing somebody the
    committee has not agreed on IS a relaxation of the selection criteria, which is the
    deviation that type names, so it does not get an exception type of its own.
    """
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return
    request_no = (req or {}).get("request_no")
    uk = (candidate or {}).get("uk")
    if not request_no or not uk:
        return

    cleared = await get_collection(COLL_SHORTLIST_REVIEWS).find_one({
        "company_id": str(company_id),
        "request_no": request_no,
        "outcome": {"$in": sorted(SHORTLIST_CLEARS_SELECTION)},
        "candidate_uks": uk,
    })
    if cleared:
        return

    from app.services.hrms_exception_service import approved_exception_for
    if await approved_exception_for(company_id, "shortlist", request_no, uk):
        return

    raise HTTPException(
        status_code=409,
        detail=(f'{candidate.get("candidate_name") or uk} has not been finalised by the '
                f"shortlisting committee for {request_no}. SOP section 5 asks HR and the "
                f"Department Head to agree the shortlist before the final interview. "
                f"Record the committee's decision, or log an approved Relaxed Scorecard "
                f"exception."))


# -------------------------------------------------------------
# Final Commit
# -------------------------------------------------------------
async def _final_round_passed(company_id: str, uks) -> bool:
    """Whether EVERY named candidate has already passed the Management final round.

    All of them, not any: one sitting carries one outcome, so if a single candidate still
    owes the round then the sitting as a whole routes to the final interview. Selecting the
    group on the strength of one person's completed round is exactly the hole SOP section 5
    exists to close.
    """
    uks = [u for u in (uks or []) if u]
    if not uks:
        return False
    rounds = await get_collection(COLL_INTERVIEWS).find(
        {"company_id": str(company_id), "uk": {"$in": uks},
         "round": FINAL_ROUND.value},
        {"uk": 1, "outcome": 1}).to_list(200)
    passed = {r.get("uk") for r in rounds if r.get("outcome") in FINAL_ROUND_PASSING}
    return all(u in passed for u in uks)


async def commit_preview(company_id: str, req: dict, members, uks) -> dict:
    """What recording the decision right now WOULD produce, and why.

    Served to the screen so the committee sees the consequence before it commits, instead of
    choosing a conclusion from a dropdown. Read-only.
    """
    from app.services.hrms_interview_service import _level_for
    level = await _level_for(company_id, req or {})
    final_passed = await _final_round_passed(company_id, uks)
    outcome = final_commit_outcome(members, level=level, final_round_passed=final_passed)
    objectors = [m.get("name") for m in (members or [])
                 if not m.get("recused")
                 and m.get("decision") == CommitteeDecision.OBJECT.value]
    if outcome is ShortlistOutcome.REJECTED:
        because = f"not approved by {', '.join(objectors)}"
    elif outcome is ShortlistOutcome.FINAL_INTERVIEW_REQUIRED:
        because = (f'a "{getattr(level, "value", level)}" role needs the Management final '
                   f"interview before selection")
    else:
        because = "approved by the committee, with no final round outstanding"
    return {
        "outcome": outcome.value,
        "because": because,
        "designation_level": getattr(level, "value", level),
        "final_round_passed": final_passed,
        "objections": objectors,
    }


# Where each Final Commit outcome leaves the candidates it names.
COMMIT_CANDIDATE_STATUS = {
    ShortlistOutcome.SELECTED: AppStatus.SELECTED,
    ShortlistOutcome.REJECTED: AppStatus.REJECTED,
    ShortlistOutcome.FINAL_INTERVIEW_REQUIRED: AppStatus.FINAL_INTERVIEW_REQUIRED,
}


async def _apply_commit(actor: dict, company_id: str, outcome, uks, slr_no: str) -> list:
    """Move the named candidates to where the commit puts them.

    Best-effort PER CANDIDATE and deliberately not transactional: the decision is already
    recorded, and a candidate whose status could not be advanced must not un-record a
    committee's minutes. Anything skipped is returned so the caller can say so out loud
    rather than leaving the screen to imply it worked.

    `Selected` still goes through `assert_selectable`. The sitting written a moment ago is
    what satisfies that gate, so it passes -- and if it does not, the derivation and the gate
    disagree, which is a defect that should surface here rather than be papered over.
    """
    target = COMMIT_CANDIDATE_STATUS.get(outcome)
    if not target:
        return []
    from app.services.hrms_candidate_service import assert_selectable

    skipped = []
    for uk in (uks or []):
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": uk, "company_id": str(company_id)})
        if not candidate:
            continue
        current = candidate.get("application_status") or AppStatus.APPLIED.value
        if current == target.value:
            continue
        # "Needs the Management final round" is already true of somebody sitting IN it.
        #
        # Passing an earlier round advances a candidate to MD Round automatically, so on
        # the normal managerial path the commit arrives to find them already where it was
        # going to send them. There is no edge back from MD Round, and rightly so -- moving
        # them from "in the final round" to "needs a final round" would be a regression.
        # Without this the routing was reported as a candidate who could not be moved,
        # which reads as a failure on a path where nothing went wrong.
        if (target is AppStatus.FINAL_INTERVIEW_REQUIRED
                and current in (AppStatus.MD_ROUND.value, AppStatus.SELECTED.value)):
            continue
        if not can_transition(current, target.value):
            skipped.append(f'{candidate.get("candidate_name") or uk} (at "{current}")')
            continue
        if target is AppStatus.SELECTED:
            try:
                await assert_selectable(actor, company_id, candidate)
            except HTTPException as e:
                skipped.append(f'{candidate.get("candidate_name") or uk}: {e.detail}')
                continue
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": uk, "company_id": str(company_id)},
            {"$set": {"application_status": target.value,
                      "updated_at": datetime.now(timezone.utc)}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{current} -> {target.value} ({slr_no})", company_id)
    return skipped


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def _resolve_candidates(company_id: str, request_no: str, uks) -> list:
    """Check every named candidate exists and is actually on this requisition.

    The same rule the exception log applies to a candidate-scoped waiver, and for the same
    reason: a committee decision that names somebody from another vacancy would lift a gate
    on work it never reviewed.
    """
    uks = [str(u).strip() for u in (uks or []) if str(u or "").strip()]
    if len(uks) > MAX_SHORTLIST_CANDIDATES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_SHORTLIST_CANDIDATES} candidates per sitting.")

    resolved, seen = [], set()
    for uk in uks:
        if uk in seen:
            continue
        seen.add(uk)
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": uk, "company_id": str(company_id)},
            {"uk": 1, "candidate_name": 1, "request_no": 1, "scorecard_score": 1,
             "scorecard_band": 1})
        if not candidate:
            raise HTTPException(status_code=422, detail=f"{uk} is not a candidate here.")
        if candidate.get("request_no") != request_no:
            raise HTTPException(
                status_code=422,
                detail=(f"{uk} is not a candidate on {request_no}. A committee decides on "
                        f"the shortlist for one vacancy."))
        resolved.append(candidate)
    return resolved


async def _retention_years(company_id: str, record_type: str) -> int:
    """This company's retention floor for `record_type` (Phase INT-5)."""
    from app.services.hrms_config_service import retention_years_for
    return await retention_years_for(company_id, record_type)


async def _bands(company_id: str) -> dict:
    """This company's band floors (Phase INT-5)."""
    from app.services.hrms_config_service import score_bands_for
    return await score_bands_for(company_id)


def _decision_guide(candidates: list, bands: dict = None) -> list:
    """The scoring band beside each candidate, so the committee decides on the evidence.

    Read from the candidate's stored scorecard evaluation and re-banded through
    `score_band` rather than copying the stored label. That way a committee sitting after
    the four-band guide landed sees the CURRENT guide, not whichever one happened to be in
    force when somebody was scored. The number is the fact; the band is its reading.
    """
    return [{
        "uk": c.get("uk"),
        "candidate_name": c.get("candidate_name"),
        "weighted_score": c.get("scorecard_score"),
        "decision_guide_band": score_band(c.get("scorecard_score"), bands),
    } for c in candidates]


async def _resolve_outcome(company_id: str, req: dict, members, uks, raw):
    """Turn what the caller ASKED for into what the committee's own verdicts SUPPORT.

    Returns `(outcome, preview)`. `preview` is None when nothing was decided.

    The caller may ask to commit; it may not choose the answer. Passing "Selected" is read
    as "record the decision now", and what gets written is whatever `final_commit_outcome`
    derives from the members' verdicts and the seniority of the role. That is the whole
    point of the change: a sitting can no longer be recorded as Selected over an objection.
    """
    raw = getattr(raw, "value", raw)
    try:
        requested = ShortlistOutcome(raw or ShortlistOutcome.PENDING.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=("Outcome must be one of: "
                    + ", ".join(o.value for o in SHORTLIST_LIVE_OUTCOMES)
                    + ", or Pending while the sitting is still open."))

    if requested is ShortlistOutcome.PENDING:
        return requested, None

    if requested not in SHORTLIST_LIVE_OUTCOMES:
        # FINALISED / DEFERRED. Readable history, not a decision anybody may record now.
        raise HTTPException(
            status_code=422,
            detail=(f'"{requested.value}" is how sittings were recorded before Final '
                    f"Commit. Record each member's approval instead and the outcome "
                    f"follows from it."))

    # Committing is the act that decides someone's candidacy, so THAT is what needs a real
    # committee. Convening one and coming back to it later is a normal way to work.
    assert_committee_complete(members)
    if not uks:
        raise HTTPException(
            status_code=422,
            detail="Name the candidates this committee is deciding on. A commit about "
                   "nobody decides nothing -- leave the sitting Pending instead.")

    preview = await commit_preview(company_id, req, members, uks)
    return ShortlistOutcome(preview["outcome"]), preview


async def create_shortlist_review(actor: dict, company_id: str, payload: dict) -> dict:
    """Convene a committee sitting. Convening decides nothing until the outcome is set."""
    request_no = clean_text(payload.get("request_no"), limit=40)
    if not request_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")
    req = await _require_internal_requisition(company_id, request_no)

    members = await _resolve_members(company_id, payload.get("committee_members"))
    candidates = await _resolve_candidates(company_id, request_no,
                                           payload.get("candidate_uks"))
    uks = [c["uk"] for c in candidates]

    outcome, preview = await _resolve_outcome(
        company_id, req, members, uks, payload.get("outcome"))

    now = datetime.now(timezone.utc)
    slr_no = await next_business_id("shortlist", str(company_id), now.year)
    decided_at = now if outcome is not ShortlistOutcome.PENDING else None

    doc = {
        "slr_no": slr_no,
        "company_id": str(company_id),
        "request_no": request_no,
        "candidate_uks": uks,
        "committee_members": members,
        "decision_guide": _decision_guide(candidates, await _bands(company_id)),
        "outcome": outcome.value,
        # WHY the outcome is what it is, frozen beside it. Recomputing this later would read
        # today's designation band and today's interview record, which is not what the
        # committee decided on.
        "commit_rationale": preview,
        "notes": clean_text(payload.get("notes"), limit=4000),
        "decided_at": decided_at,
        "convened_by": str(actor.get("_id") or ""),
        "convened_by_name": _actor_name(actor),
        # SOP §13. Selection records live with the requisition, so the requisition's own
        # retention floor is the right one. A floor, not a purge date.
        "retention_until": _add_years(
            now.strftime("%Y-%m-%d"),
            await _retention_years(company_id, "requisition")),
        "created_at": now,
    }
    await get_collection(COLL_SHORTLIST_REVIEWS).insert_one(dict(doc))
    await audit(actor, AUDIT_SHORTLIST_CONVENED, ENTITY_SHORTLIST, slr_no,
                f"{len(candidates)} candidate(s) on {request_no}, "
                f"{len(members)} member(s), outcome {outcome.value}", company_id)

    skipped = []
    if preview:
        skipped = await _apply_commit(actor, company_id, outcome, uks, slr_no)

    out = _out(doc)
    out["committee_state"] = committee_state(members)
    if skipped:
        out["warning"] = ("The decision is recorded, but these candidates were not moved: "
                          + "; ".join(skipped) + ".")
    return out


async def update_shortlist_review(actor: dict, company_id: str, slr_no: str,
                                  payload: dict) -> dict:
    """Record members, candidates or the outcome.

    A DECIDED sitting is frozen. What the committee agreed on the day is the record; a
    second decision is a second sitting, not an edit of the first -- the same rule that
    freezes an approved scorecard, and for the same reason.
    """
    coll = get_collection(COLL_SHORTLIST_REVIEWS)
    current = await coll.find_one({"slr_no": slr_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Shortlist review not found.")
    if current.get("outcome") != ShortlistOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{slr_no} was already decided ("{current.get("outcome")}"). Convene a '
                    f"new sitting rather than rewriting what this one agreed."))

    updates = {}
    if payload.get("committee_members") is not None:
        updates["committee_members"] = await _resolve_members(
            company_id, payload["committee_members"])
    if payload.get("candidate_uks") is not None:
        candidates = await _resolve_candidates(
            company_id, current.get("request_no"), payload["candidate_uks"])
        updates["candidate_uks"] = [c["uk"] for c in candidates]
        updates["decision_guide"] = _decision_guide(candidates,
                                                    await _bands(company_id))
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=4000)

    decided, preview = None, None
    if payload.get("outcome") is not None:
        members = updates.get("committee_members", current.get("committee_members"))
        uks = updates.get("candidate_uks", current.get("candidate_uks"))
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": current.get("request_no"), "company_id": str(company_id)}) or {}
        decided, preview = await _resolve_outcome(
            company_id, req, members, uks, payload["outcome"])

    if decided is not None:
        updates["outcome"] = decided.value
        if preview:
            updates["commit_rationale"] = preview
            updates["decided_at"] = datetime.now(timezone.utc)
            updates["decided_by"] = str(actor.get("_id") or "")
            updates["decided_by_name"] = _actor_name(actor)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    # Compare-and-swap on the pending state: two members finalising at once must not both
    # land, the same rule the exception log and the requisition chain follow.
    result = await coll.update_one(
        {"slr_no": slr_no, "company_id": str(company_id),
         "outcome": ShortlistOutcome.PENDING.value},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This sitting was decided by someone else. Reload and try again.")

    await audit(actor, AUDIT_SHORTLIST_DECIDED, ENTITY_SHORTLIST, slr_no,
                (updates.get("outcome") or "updated")
                + f' on {current.get("request_no")}', company_id)

    skipped = []
    if preview:
        skipped = await _apply_commit(
            actor, company_id, decided,
            updates.get("candidate_uks", current.get("candidate_uks")), slr_no)

    out = await get_shortlist_review(company_id, slr_no)
    if skipped:
        out["warning"] = ("The decision is recorded, but these candidates were not moved: "
                          + "; ".join(skipped) + ".")
    return out
