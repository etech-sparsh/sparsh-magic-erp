"""HRMS > Client Hiring, steps 3-4 — sourcing, screening, and the CV share.

PRO-fit SOP sections 10, 11, 13 and 14. Sparsh finds people, measures them against the
approved Position Scorecard, shortlists on the numbers, and delivers a shortlist to the
client. The client's verdict on a CV is what lets a candidate into assessment.

-- Nothing starts without an agreed benchmark -----------------------------------------
Section 6: no candidate is sourced or presented without an approved Position Scorecard.
`assert_sourcing_allowed` is asked once, here, at the point a candidate is created, rather
than re-derived: the benchmark is what every score below is measured against, so sourcing
before it exists would produce numbers with no meaning.

-- The threshold is a number, not a habit ----------------------------------------------
Section 13 sets a decision guide and then says "no candidate shall be shortlisted solely
on personal recommendation without meeting the minimum score threshold". So the threshold
is enforced rather than printed: a candidate averaging below it cannot be shortlisted, and
the refusal names the figure.

-- Three parties, four capabilities ----------------------------------------------------
The recruiter sources and screens. The Team Lead delivers the shortlist — the RACI makes
delivery their accountability, not the recruiter's. The client decides. No Sparsh role
holds CLIENT_CANDIDATE_DECIDE: a CV gate the supplier can open for itself is not a gate.

-- What the client sees ----------------------------------------------------------------
A candidate becomes visible to the client when they are SHARED, and not before. Sourcing
and screening are Sparsh's working process, and a client reading it would be reading an
opinion that has not been formed yet. Enforced on the read path, not on a screen.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CANDIDATE_ACTIONED, AUDIT_CLIENT_CANDIDATE_ADDED,
    AUDIT_CLIENT_CANDIDATE_UPDATED, CLIENT_CANDIDATE_CLOSED,
    CLIENT_CANDIDATE_POOL,
    CLIENT_CANDIDATE_TRANSITIONS, CLIENT_CANDIDATE_VISIBLE_TO_CLIENT,
    CLIENT_SCORE_FIELDS, CLIENT_SHORTLIST_MIN_SCORE, CLIENT_TRACK_FLAG,
    COLL_CLIENT_CANDIDATES, ENTITY_CLIENT_CANDIDATE,
    Cap, ClientCandidateStatus, client_score_band,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

MAX_CTC = 1_000_000_000

# What a client is shown. Everything Sparsh's own working notes contain and the client has
# no business reading is absent by CONSTRUCTION rather than removed afterwards: the shape
# is a whitelist, so a field added to the record later is invisible to the client until
# somebody decides otherwise and adds it here.
#
# The SOP's section 14 says what the client gets: the CV, the Talent Fit, Competency and
# Preliminary Interview scores, and a comparative scorecard. `screening_notes` is
# deliberately NOT in it -- those are the recruiter's candid observations, written to be
# read internally.
CLIENT_VISIBLE_FIELDS = (
    "ccn_no", "company_id", "cr_no", "candidate_name", "email", "phone",
    "source", "cv_reference", "current_employer", "notice_period",
    "current_ctc", "expected_ctc",
    "tfs_score", "competency_score", "pi_score", "average_score", "score_band",
    "status", "shared_at", "client_decision", "created_at", "updated_at",
)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _client_view(doc: dict) -> dict:
    """The shared candidate, as the client may see them."""
    return {key: doc.get(key) for key in CLIENT_VISIBLE_FIELDS if key in doc}


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _is_client_side(actor: dict) -> bool:
    if (actor or {}).get(CLIENT_TRACK_FLAG):
        return True
    return not is_internal_user(actor)


def _money(value, label: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount < 0 or amount > MAX_CTC:
        raise HTTPException(status_code=422, detail=f"{label} is not a plausible figure.")
    return round(amount, 2)


def _score(value, label: str) -> Optional[float]:
    """A score on the SOP's five-point scale."""
    if value in (None, ""):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if not 0 <= amount <= 5:
        raise HTTPException(
            status_code=422,
            detail=f"{label} is scored from 0 to 5 (SOP section 13).")
    return round(amount, 2)


def _average(doc: dict) -> Optional[float]:
    """The figure the decision guide bands. None until something has been scored."""
    values = [doc.get(key) for key, _ in CLIENT_SCORE_FIELDS]
    have = [float(v) for v in values if v is not None]
    if not have:
        return None
    return round(sum(have) / len(have), 2)


async def _require_visible(actor: dict, company_id: str, ccn_no: str) -> dict:
    """One candidate, or 404. A client is refused one not yet shared with them."""
    doc = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if (_is_client_side(actor)
            and doc.get("status") not in CLIENT_CANDIDATE_VISIBLE_TO_CLIENT):
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return doc


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_client_candidates(actor: dict, company_id: Optional[str], *,
                                 cr_no: str = None, status: str = None,
                                 limit: int = 200) -> dict:
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    elif _is_client_side(actor):
        raise HTTPException(status_code=403, detail="No company in scope.")
    if cr_no:
        query["cr_no"] = cr_no

    client_side = _is_client_side(actor)
    if client_side:
        allowed = sorted(CLIENT_CANDIDATE_VISIBLE_TO_CLIENT)
        query["status"] = ({"$in": allowed} if not status
                           else (status if status in CLIENT_CANDIDATE_VISIBLE_TO_CLIENT
                                 else "__none__"))
    elif status:
        query["status"] = status

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CLIENT_CANDIDATES).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [(_client_view(r) if client_side else _out(r)) for r in rows]
    return {
        "client_candidates": out,
        "total": len(out),
        "awaiting_client": sum(
            1 for r in out
            if r.get("status") == ClientCandidateStatus.SHARED_WITH_CLIENT.value),
    }


async def get_client_candidate(actor: dict, company_id: str, ccn_no: str) -> dict:
    doc = await _require_visible(actor, company_id, ccn_no)
    return _client_view(doc) if _is_client_side(actor) else _out(doc)


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
async def create_client_candidate(actor: dict, company_id: str, payload: dict) -> dict:
    """Source a candidate against a role whose benchmark the client has approved."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    cr_no = clean_text(payload.get("cr_no"), limit=40)
    if not cr_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")
    name = clean_text(payload.get("candidate_name"), limit=180)
    if not name:
        raise HTTPException(status_code=422, detail="A candidate needs a name.")

    # SOP section 6 -- the one gate, asked once, here.
    from app.services.hrms_client_scorecard_service import assert_sourcing_allowed
    scorecard = await assert_sourcing_allowed(company_id, cr_no)

    now = datetime.now(timezone.utc)
    ccn_no = await next_business_id("client_candidate", str(company_id), now.year)
    doc = {
        "ccn_no": ccn_no,
        "company_id": str(company_id),
        "cr_no": cr_no,
        # The benchmark this person is being measured against, stamped as it stood.
        "psc_no": scorecard.get("psc_no"),
        "candidate_name": name,
        "email": clean_text(payload.get("email"), limit=180),
        "phone": clean_text(payload.get("phone"), limit=40),
        "source": clean_text(payload.get("source"), limit=120),
        "cv_reference": clean_text(payload.get("cv_reference"), limit=500),
        "current_employer": clean_text(payload.get("current_employer"), limit=180),
        "notice_period": clean_text(payload.get("notice_period"), limit=60),
        "current_ctc": _money(payload.get("current_ctc"), "Current CTC"),
        "expected_ctc": _money(payload.get("expected_ctc"), "Expected CTC"),
        "tfs_score": None, "competency_score": None, "pi_score": None,
        "average_score": None, "score_band": client_score_band(None),
        "screening_notes": None,
        "status": ClientCandidateStatus.SOURCED.value,
        "shared_at": None,
        "client_decision": None,
        "sourced_by": str(actor.get("_id") or ""),
        "sourced_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_CANDIDATES).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_CANDIDATE_ADDED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"{name} sourced for {cr_no}", company_id)
    return _out(doc)


async def update_client_candidate(actor: dict, company_id: str, ccn_no: str,
                                  payload: dict) -> dict:
    """Record details and scores. Refused once the client has been given the CV.

    Editing a candidate the client is currently reading would change the thing under
    consideration while it is being considered — the same reason an internal scorecard
    freezes at review.
    """
    current = await _require_visible(actor, company_id, ccn_no)
    if current.get("status") in CLIENT_CANDIDATE_CLOSED:
        raise HTTPException(
            status_code=409,
            detail=f'{ccn_no} is "{current.get("status")}" and can no longer be changed.')
    if current.get("status") in CLIENT_CANDIDATE_VISIBLE_TO_CLIENT:
        raise HTTPException(
            status_code=409,
            detail=(f"{ccn_no} is with the client. Amending a CV somebody is reviewing "
                    f"would change what they are deciding on."))

    updates: dict = {}
    for field, limit in (("candidate_name", 180), ("email", 180), ("phone", 40),
                         ("source", 120), ("cv_reference", 500),
                         ("current_employer", 180), ("notice_period", 60),
                         ("screening_notes", 4000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    for field, label in (("current_ctc", "Current CTC"), ("expected_ctc", "Expected CTC")):
        if payload.get(field) is not None:
            updates[field] = _money(payload[field], label)
    for field, label in CLIENT_SCORE_FIELDS:
        if payload.get(field) is not None:
            updates[field] = _score(payload[field], label)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    merged = {**current, **updates}
    updates["average_score"] = _average(merged)
    updates["score_band"] = client_score_band(updates["average_score"])
    updates["updated_at"] = datetime.now(timezone.utc)

    await get_collection(COLL_CLIENT_CANDIDATES).update_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_CANDIDATE_UPDATED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                ", ".join(sorted(k for k in updates
                                 if k not in ("updated_at", "score_band"))), company_id)
    return await get_client_candidate(actor, company_id, ccn_no)


# ─────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────
def _assert_screened(doc: dict) -> None:
    """A screen is a measurement, so it needs the measurement (SOP section 11)."""
    if doc.get("tfs_score") is None:
        raise HTTPException(
            status_code=422,
            detail=("Record the Talent Fit Score first. Section 11 screens a CV by "
                    "validating it against the Position Scorecard, and a screen with no "
                    "score is an opinion nobody can audit."))


def _assert_shortlistable(doc: dict) -> None:
    """SOP section 13's threshold, enforced rather than printed."""
    if doc.get("pi_score") is None:
        raise HTTPException(
            status_code=422,
            detail="Record the Preliminary Interview Score before shortlisting.")
    average = _average(doc)
    band = client_score_band(average)
    if not band["may_shortlist"]:
        raise HTTPException(
            status_code=409,
            detail=(f'{doc.get("candidate_name")} averages {average} '
                    f'("{band["label"]}"). Section 13 sets the shortlist threshold at '
                    f"{CLIENT_SHORTLIST_MIN_SCORE}, and says no candidate is shortlisted "
                    f"on recommendation alone without meeting it."))


async def act_on_client_candidate(actor: dict, company_id: str, ccn_no: str,
                                  action: str, payload: dict = None) -> dict:
    """Move along CLIENT_CANDIDATE_TRANSITIONS."""
    payload = payload or {}
    spec = CLIENT_CANDIDATE_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_CANDIDATE_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, ccn_no)
    status = current.get("status")
    if status in CLIENT_CANDIDATE_CLOSED:
        raise HTTPException(
            status_code=409,
            detail=f'{ccn_no} is "{status}" and cannot progress.')
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{ccn_no} is "{status}", so "{action}" does not apply to them.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail=("Say why. A candidate turned down with no reason leaves nobody able "
                    "to explain it later, least of all to the candidate."))

    # SOP section 11 screens a CV by validating it against the Position Scorecard, so the
    # score is what MAKES it a screen. This used to be checked only on telephonic-pass,
    # one step too late: a candidate could sit in "Screened" -- a status that asserts a
    # measurement happened -- with no measurement behind it. Kept on telephonic-pass as
    # well, which costs nothing and guards the revive path.
    if action in ("screen", "telephonic-pass"):
        _assert_screened(current)
    if action == "shortlist":
        _assert_shortlistable(current)

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    if action == "share":
        updates["shared_at"] = now
        updates["shared_by_name"] = _actor_name(actor)
    if action.startswith("client-"):
        updates["client_decision"] = {
            "decision": action.split("-", 1)[1],
            "remarks": remarks,
            "by": str(actor.get("_id") or ""),
            "by_name": _actor_name(actor),
            "at": now,
        }

    result = await get_collection(COLL_CLIENT_CANDIDATES).update_one(
        {"ccn_no": ccn_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this candidate. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_CANDIDATE_ACTIONED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    # Read back WITHOUT re-applying the client filter: refusing to show somebody the
    # result of their own action is never the right reading of a visibility rule.
    fresh = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})
    return _client_view(fresh) if _is_client_side(actor) else _out(fresh)


# ─────────────────────────────────────────────────────────────
# The gate step 5 asks
# ─────────────────────────────────────────────────────────────
async def assert_assessment_allowed(company_id: str, ccn_no: str) -> dict:
    """The client's CV approval is what opens the assessment stage.

    Your flow makes this the branch point: "CV approval becomes the gate that allows the
    candidate to enter the assessment stage". Written once, here, so step 5 asks rather
    than re-derives.
    """
    doc = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": ccn_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if doc.get("status") == ClientCandidateStatus.CLIENT_APPROVED.value:
        return _out(doc)
    raise HTTPException(
        status_code=409,
        detail=(f'{doc.get("candidate_name")} is "{doc.get("status")}". The assessment '
                f"stage opens when the client approves the CV, and not before."))


# ─────────────────────────────────────────────────────────────
# The available candidate pool
# ─────────────────────────────────────────────────────────────
async def list_candidate_pool(actor: dict, *, limit: int = 200,
                              search: str = None) -> dict:
    """Candidates whose run ended at one client but who are still available.

    SPARSH-SIDE ONLY, and the refusal below is the whole reason this function is not a
    filter on the ordinary list. The pool spans every engagement: it is the one query in
    Client Hiring that deliberately crosses tenants, so it must be unreachable from a
    client-side caller by construction rather than by remembering to pass a company id.

    What comes back is the PERSON, not the engagement. No requisition, no client decision,
    no rejection reason, no company name -- a recruiter looking for somebody to re-source
    needs to know who is available and how to reach them, not who turned them down.
    """
    if not is_internal_user(actor) or actor.get(CLIENT_TRACK_FLAG):
        raise HTTPException(
            status_code=403,
            detail=("The available candidate pool spans every client engagement and is "
                    "Sparsh's alone. Your own company's candidates are on the candidate "
                    "list."))
    if not can(actor, Cap.CLIENT_CANDIDATE_WRITE):
        raise HTTPException(
            status_code=403,
            detail=(f"Reading the pool needs {Cap.CLIENT_CANDIDATE_WRITE.value} -- it is "
                    f"a sourcing surface, not a report."))

    query: dict = {"status": {"$in": sorted(CLIENT_CANDIDATE_POOL)}}
    if search:
        term = clean_text(search, limit=120) or ""
        query["candidate_name"] = {"$regex": re.escape(term), "$options": "i"}

    rows = await get_collection(COLL_CLIENT_CANDIDATES).find(query).sort(
        "updated_at", -1).to_list(limit)

    # One entry per PERSON, not per engagement: somebody passed over by three clients is
    # one candidate worth re-sourcing, not three rows to scroll past.
    people: dict = {}
    for r in rows:
        key = (r.get("email") or r.get("phone") or r.get("ccn_no") or "").lower()
        entry = people.get(key)
        if entry is None:
            people[key] = {
                "ccn_no": r.get("ccn_no"),
                # The tenant this record belongs to. Business ids are minted PER COMPANY,
                # so CCN-2026-001 exists in every engagement and the number alone cannot
                # identify anybody -- re-sourcing on it would pull whichever row Mongo
                # happened to return first. This endpoint is Sparsh-only, so carrying the
                # company here is not a leak; what stays out is the rejection itself.
                "from_company_id": r.get("company_id"),
                "candidate_name": r.get("candidate_name"),
                "email": r.get("email"),
                "phone": r.get("phone"),
                "current_employer": r.get("current_employer"),
                "notice_period": r.get("notice_period"),
                "current_ctc": r.get("current_ctc"),
                "expected_ctc": r.get("expected_ctc"),
                "cv_reference": r.get("cv_reference"),
                "tfs_score": r.get("tfs_score"),
                "average_score": r.get("average_score"),
                "score_band": r.get("score_band"),
                "source": r.get("source"),
                "last_status": r.get("status"),
                "last_seen": r.get("updated_at"),
                "engagements": 1,
            }
        else:
            entry["engagements"] += 1
    out = sorted(people.values(), key=lambda p: p.get("last_seen") or 0, reverse=True)
    return {"client_candidate_pool": out, "total": len(out)}


async def resource_from_pool(actor: dict, company_id: str, payload: dict) -> dict:
    """Source somebody from the pool into a different requisition.

    Creates a NEW candidate record in the TARGET tenant, carrying the person's details
    forward. It does not move or re-point the original, which stays with the client who
    rejected them -- their record, their decision, their history.

    The target is gated exactly like any other sourcing: the requisition must have a
    scorecard the client has approved, because a candidate re-sourced into a role with no
    agreed benchmark is the same mistake as a candidate sourced into one.
    """
    if not is_internal_user(actor) or actor.get(CLIENT_TRACK_FLAG):
        raise HTTPException(
            status_code=403,
            detail="Sourcing from the pool is Sparsh's, across engagements.")
    # The SAME capability the pool's own list requires. Being Sparsh staff was the only
    # check here, so an operator refused the GET (403, "Reading the pool needs
    # client_candidate.write") could still POST this and write a candidate record into a
    # client's tenant -- the read was gated and the write was not. Sourcing somebody into
    # an engagement is exactly what CLIENT_CANDIDATE_WRITE means everywhere else on this
    # track (screen, shortlist, telephonic), so it means it here too.
    if not can(actor, Cap.CLIENT_CANDIDATE_WRITE):
        raise HTTPException(
            status_code=403,
            detail=(f"Sourcing from the pool needs {Cap.CLIENT_CANDIDATE_WRITE.value} -- "
                    f"it places a candidate into a client's engagement."))

    source_ccn = clean_text(payload.get("ccn_no"), limit=40)
    source_company = clean_text(payload.get("from_company_id"), limit=64)
    cr_no = clean_text(payload.get("cr_no"), limit=40)
    if not source_ccn or not cr_no or not source_company:
        raise HTTPException(
            status_code=422,
            detail=("Name the candidate to source (number AND the engagement they are "
                    "on) and the requisition to source them into."))

    # BOTH halves of the key. `ccn_no` is minted per company, so a lookup on the number
    # alone would match a different person in a different engagement.
    origin = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"ccn_no": source_ccn, "company_id": str(source_company)})
    if not origin:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if origin.get("status") not in CLIENT_CANDIDATE_POOL:
        raise HTTPException(
            status_code=409,
            detail=(f'{origin.get("candidate_name")} is "{origin.get("status")}" and is '
                    f"still live on that engagement. The pool is for candidates whose run "
                    f"has ended."))
    if str(source_company) == str(company_id) and origin.get("cr_no") == cr_no:
        raise HTTPException(
            status_code=409,
            detail="That is the requisition they were already considered for.")

    # Same gate as ordinary sourcing -- an approved scorecard, in the TARGET tenant.
    # Imported here rather than at module scope: the scorecard service imports this one,
    # and a top-level import would close the cycle.
    from app.services.hrms_client_scorecard_service import assert_sourcing_allowed
    scorecard = await assert_sourcing_allowed(company_id, cr_no)

    now = datetime.now(timezone.utc)
    ccn_no = await next_business_id("client_candidate", str(company_id), now.year)
    doc = {
        "ccn_no": ccn_no,
        "company_id": str(company_id),
        "cr_no": cr_no,
        "psc_no": scorecard.get("psc_no"),
        "candidate_name": origin.get("candidate_name"),
        "email": origin.get("email"),
        "phone": origin.get("phone"),
        "source": "Candidate pool",
        "cv_reference": origin.get("cv_reference"),
        "current_employer": origin.get("current_employer"),
        "notice_period": origin.get("notice_period"),
        "current_ctc": origin.get("current_ctc"),
        "expected_ctc": origin.get("expected_ctc"),
        # Scores are NOT carried over. They were measured against a different client's
        # scorecard, and a number that means "strong for Acme" means nothing for Globex.
        "tfs_score": None, "competency_score": None, "pi_score": None,
        "average_score": None, "score_band": None,
        # A Sparsh-side breadcrumb, never in the client view: it is how a recruiter knows
        # they already have this person's CV, and it is not the new client's business.
        "sourced_from_ccn": source_ccn,
        "sourced_from_company": str(source_company),
        "status": ClientCandidateStatus.SOURCED.value,
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_CANDIDATES).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_CANDIDATE_ADDED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"sourced from the pool ({source_ccn}) into {cr_no}", company_id)
    return await get_client_candidate(actor, company_id, ccn_no)
