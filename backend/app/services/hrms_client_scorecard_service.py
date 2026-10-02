"""HRMS > Client Hiring, step 2 — the Position Scorecard.

PRO-fit SOP sections 4, 5.2, 6 and 8. Sparsh drafts the evaluation benchmark for a role,
the Team Lead reviews it before it leaves the building, and the client approves it. Only
then may sourcing begin.

-- Why the order matters --------------------------------------------------------------
Section 6: "No candidate shall be presented to a client without an approved Position
Scorecard as the evaluation benchmark." Section 13 then measures every candidate against
it — the Talent Fit Score is literally a CV validated against this document.

A benchmark agreed AFTER candidates exist is a yardstick chosen to fit the people already
found. That is why the SOP puts approval at step 4, before sourcing at step 5, and why
`sourcing_allowed` below is the gate later steps must ask rather than re-deriving.

-- Three parties, three capabilities ---------------------------------------------------
The section 8 approval matrix reads "PSC — Recruiter: Draft, Team Lead: Review, Client:
Approve (mandatory)". Each is a different capability held by a different side:

  * the recruiter writes it and cannot approve it, internally or on the client's behalf
  * the Team Lead reviews it and cannot write it
  * the client approves it and cannot write it

No Sparsh role holds CLIENT_SCORECARD_APPROVE. The client's mandatory sign-off is only
mandatory if Sparsh cannot supply it for them.

-- What the client can see -------------------------------------------------------------
A scorecard still with Sparsh is work in progress. The client sees it once it is shared
and after it is approved, and not before — showing somebody a draft invites approval of
the wrong version. Enforced on the read path, not just hidden on a screen.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_SCORECARD_ACTIONED, AUDIT_CLIENT_SCORECARD_CREATED,
    AUDIT_CLIENT_SCORECARD_UPDATED, CLIENT_SCORECARD_EDITABLE,
    CLIENT_SCORECARD_SECTIONS, CLIENT_SCORECARD_TRANSITIONS,
    CLIENT_SCORECARD_VISIBLE_TO_CLIENT, COLL_CLIENT_REQUISITIONS,
    COLL_CLIENT_SCORECARDS, CLIENT_TRACK_FLAG, ENTITY_CLIENT_SCORECARD,
    Cap, ClientReqStatus, ClientScorecardStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

SECTION_LIMIT = 8000


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _is_client_side(actor: dict) -> bool:
    """Whether this caller is a client company's user rather than Sparsh staff.

    Reads the gate's own stamp first. Falling back to `is_internal_user` keeps the service
    honest when it is called outside a request (a test, a script), where the stamp that the
    router applies has never been set.
    """
    if (actor or {}).get(CLIENT_TRACK_FLAG):
        return True
    return not is_internal_user(actor)


async def _require_activated_requisition(company_id: str, cr_no: str) -> dict:
    """The requisition a scorecard hangs off, and it must have cleared feasibility.

    A scorecard drafted against a requisition Sparsh has not yet agreed to deliver is work
    against a job that may never exist. SOP section 7: nothing proceeds until the NMF and
    MRF are complete and internally reviewed.
    """
    req = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": cr_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    if req.get("status") != ClientReqStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{cr_no} is "{req.get("status")}". A Position Scorecard is drafted '
                    f"against a requisition Sparsh has assessed and approved, not before."))
    return req


async def _require_visible(actor: dict, company_id: str, psc_no: str) -> dict:
    """One scorecard, or 404.

    `company_id` is part of the query, so another tenant's number answers exactly as a
    number that does not exist. A client is additionally refused a scorecard that has not
    been shared with them yet — same 404, for the same reason: "it exists but you may not
    see it yet" is itself information.
    """
    doc = await get_collection(COLL_CLIENT_SCORECARDS).find_one(
        {"psc_no": psc_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Position Scorecard not found.")
    if (_is_client_side(actor)
            and doc.get("status") not in CLIENT_SCORECARD_VISIBLE_TO_CLIENT):
        raise HTTPException(status_code=404, detail="Position Scorecard not found.")
    return doc


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_client_scorecards(actor: dict, company_id: Optional[str], *,
                                 cr_no: str = None, status: str = None,
                                 limit: int = 100) -> dict:
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    elif _is_client_side(actor):
        raise HTTPException(status_code=403, detail="No company in scope.")
    if cr_no:
        query["cr_no"] = cr_no
    if status:
        query["status"] = status
    # A client's list never contains a draft, whatever they filter by.
    if _is_client_side(actor):
        query["status"] = ({"$in": sorted(CLIENT_SCORECARD_VISIBLE_TO_CLIENT)}
                           if not status
                           else (status if status in CLIENT_SCORECARD_VISIBLE_TO_CLIENT
                                 else "__none__"))

    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_CLIENT_SCORECARDS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "client_scorecards": out,
        "total": len(out),
        "awaiting_client": sum(
            1 for r in out
            if r.get("status") == ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value),
    }


async def get_client_scorecard(actor: dict, company_id: str, psc_no: str) -> dict:
    return _out(await _require_visible(actor, company_id, psc_no))


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
def _sections_from(payload: dict) -> dict:
    return {key: clean_text(payload.get(key), limit=SECTION_LIMIT)
            for key, _label in CLIENT_SCORECARD_SECTIONS
            if payload.get(key) is not None}


async def create_client_scorecard(actor: dict, company_id: str, payload: dict) -> dict:
    """Draft a Position Scorecard against an approved requisition."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")
    cr_no = clean_text(payload.get("cr_no"), limit=40)
    if not cr_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")
    req = await _require_activated_requisition(company_id, cr_no)

    existing = await get_collection(COLL_CLIENT_SCORECARDS).find_one(
        {"company_id": str(company_id), "cr_no": cr_no})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{cr_no} already has a Position Scorecard ({existing["psc_no"]}, '
                    f'{existing["status"]}). One role, one benchmark.'))

    now = datetime.now(timezone.utc)
    psc_no = await next_business_id("client_scorecard", str(company_id), now.year)
    doc = {
        "psc_no": psc_no,
        "company_id": str(company_id),
        "cr_no": cr_no,
        # Denormalised so a reader sees which role this benchmark is for without a join.
        "role_title": req.get("role_title"),
        **{key: None for key, _label in CLIENT_SCORECARD_SECTIONS},
        **_sections_from(payload),
        "status": ClientScorecardStatus.DRAFT.value,
        "internal_review": None,
        "client_approval": None,
        "drafted_by": str(actor.get("_id") or ""),
        "drafted_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_SCORECARDS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_SCORECARD_CREATED, ENTITY_CLIENT_SCORECARD, psc_no,
                f"drafted for {cr_no}", company_id)
    return _out(doc)


async def update_client_scorecard(actor: dict, company_id: str, psc_no: str,
                                  payload: dict) -> dict:
    """Amend the draft. Only while it is still a draft."""
    current = await _require_visible(actor, company_id, psc_no)
    if current.get("status") not in CLIENT_SCORECARD_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=(f'{psc_no} is "{current.get("status")}" and cannot be edited. '
                    f"Editing a scorecard somebody is reviewing would make their "
                    f"approval meaningless — have it returned first."))

    updates = _sections_from(payload)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_SCORECARDS).update_one(
        {"psc_no": psc_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_SCORECARD_UPDATED, ENTITY_CLIENT_SCORECARD, psc_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_scorecard(actor, company_id, psc_no)


def _assert_complete(doc: dict) -> None:
    """All five sections, checked when it is submitted rather than while it is typed."""
    missing = [label for key, label in CLIENT_SCORECARD_SECTIONS if not doc.get(key)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=("A Position Scorecard is the benchmark every later score is measured "
                    "against, so it cannot go out half-written. Still needed: "
                    + ", ".join(missing) + "."))


async def act_on_client_scorecard(actor: dict, company_id: str, psc_no: str,
                                  action: str, payload: dict = None) -> dict:
    """Move along CLIENT_SCORECARD_TRANSITIONS.

    The capability for each action is read from the table, so the gate cannot drift from
    the state machine it guards.
    """
    payload = payload or {}
    spec = CLIENT_SCORECARD_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_SCORECARD_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, psc_no)
    status = current.get("status")
    if status == ClientScorecardStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(f"{psc_no} is approved and is now the benchmark candidates are being "
                    f"measured against. Changing it would move the yardstick mid-search."))
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{psc_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say what needs to change. A scorecard returned with no reason "
                   "cannot be corrected.")

    if action == "submit-for-review":
        _assert_complete(current)

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    stamp = {"decision": action, "remarks": remarks,
             "by": str(actor.get("_id") or ""), "by_name": _actor_name(actor), "at": now}
    if action.startswith("internal-"):
        updates["internal_review"] = stamp
    if action.startswith("client-"):
        updates["client_approval"] = stamp
    # A return sends it back to Draft, so BOTH prior stamps are cleared. Whatever the Team
    # Lead passed and whatever the client saw was a version that is about to be rewritten,
    # and a record still showing "internally approved" against a document being changed is
    # a claim about a version nobody will read again. The state machine makes the review
    # happen a second time regardless; this stops the record implying otherwise meanwhile.
    if action.endswith("-return"):
        updates["internal_review"] = None
        updates["client_approval"] = None

    result = await get_collection(COLL_CLIENT_SCORECARDS).update_one(
        {"psc_no": psc_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this scorecard. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_SCORECARD_ACTIONED, ENTITY_CLIENT_SCORECARD, psc_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)

    # Read back WITHOUT the client-visibility filter, deliberately.
    #
    # A client who returns a scorecard sends it to Draft, and a client may not normally see
    # a draft -- so re-reading through `get_client_scorecard` answered them 404 for the
    # result of their own action. Refusing to show somebody what they just did is never the
    # right reading of a rule that exists to stop them seeing work in progress. The content
    # is the version they were looking at a moment ago; nothing new is disclosed.
    fresh = await get_collection(COLL_CLIENT_SCORECARDS).find_one(
        {"psc_no": psc_no, "company_id": str(company_id)})
    return _out(fresh)


# ─────────────────────────────────────────────────────────────
# The gate later steps ask
# ─────────────────────────────────────────────────────────────
async def approved_scorecard_for(company_id: str, cr_no: str) -> Optional[dict]:
    """The approved benchmark for this requisition, or None."""
    doc = await get_collection(COLL_CLIENT_SCORECARDS).find_one(
        {"company_id": str(company_id), "cr_no": cr_no,
         "status": ClientScorecardStatus.APPROVED.value})
    return _out(doc) if doc else None


async def assert_sourcing_allowed(company_id: str, cr_no: str) -> dict:
    """SOP section 6 — refuse to source against a role with no agreed benchmark.

    Written here, once, so step 3 and everything after it ask the same question rather than
    each re-deriving what "ready to source" means. Returns the scorecard so the caller can
    measure against it without a second read.
    """
    scorecard = await approved_scorecard_for(company_id, cr_no)
    if scorecard:
        return scorecard
    raise HTTPException(
        status_code=409,
        detail=(f"{cr_no} has no Position Scorecard the client has approved. SOP section 6 "
                f"asks for an agreed benchmark before any candidate is sourced or "
                f"presented, so that everyone is measuring the same thing."))
