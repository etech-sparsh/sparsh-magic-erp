"""HRMS > Client Hiring, step 1 — Need Mapping, Manpower Requisition, feasibility review.

PRO-fit SOP section 7. A client company tells Sparsh Magic what it needs, formalises the
role and its budget, and Sparsh assesses whether the engagement is deliverable before any
sourcing begins.

-- Nothing here touches Internal Hiring ------------------------------------------------
Its own collection, its own statuses, its own transition table, its own capabilities, its
own service. The two tracks share the audit log and the id sequence and nothing else. That
is deliberate and load-bearing: Sparsh hiring its own staff and Sparsh recruiting for a
client are different processes with different approvers, and a shared requisition record
would force one set of gates onto both.

-- Two forms, one record ---------------------------------------------------------------
The SOP names a Need Mapping Form and a Manpower Requisition Form. They describe the same
vacancy at two levels of detail, so they are two STAGES of one row rather than two
collections. "No sourcing until both are complete" is then a status, not a join.

-- The control this step exists to enforce ---------------------------------------------
Section 7 step 3: the recruitment team assesses role clarity, compensation competitiveness
and timeline BEFORE the requisition is activated. So the client may raise and amend their
own requisition and may not review it, and `CLIENT_REQUISITION_REVIEW` is granted to Sparsh
roles only. A requisition that has not been approved cannot reach the Position Scorecard
stage, and a rejected one cannot progress at all — there is no edge out of Rejected in
CLIENT_REQ_TRANSITIONS, so that is a property of the table rather than a check somebody has
to remember.

-- Tenant isolation --------------------------------------------------------------------
Every read and every write is filtered by `company_id` taken from `scope_company_id`, which
ignores a company a client-side caller asks for and pins them to their own. A client
therefore cannot reach another client's requisition by guessing a number, and cannot reach
Sparsh Magic's internal hiring at all — that lives in a different collection AND a
different tenant. Sparsh staff are not pinned and see the queue across clients.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_REQ_ACTIONED, AUDIT_CLIENT_REQ_CREATED, AUDIT_CLIENT_REQ_UPDATED,
    CLIENT_REQ_CLOSED, CLIENT_REQ_EDITABLE, CLIENT_REQ_TRANSITIONS,
    COLL_CLIENT_REQUISITIONS, ENTITY_CLIENT_REQUISITION, FEASIBILITY_CHECKS,
    Cap, ClientReqStatus, ClientReqUrgency, EmploymentTypeClient,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_internal_user
from app.utils.hrms_public_guard import clean_text

MAX_VACANCIES = 500
MAX_SALARY = 1_000_000_000


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _money(value, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail=f"{label} must be more than zero.")
    if amount > MAX_SALARY:
        raise HTTPException(status_code=422, detail=f"{label} is not a plausible figure.")
    return round(amount, 2)


def _enum(value, enum_cls, label: str):
    raw = getattr(value, "value", value)
    try:
        return enum_cls(raw).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be one of: " + ", ".join(m.value for m in enum_cls) + ".")


async def _require_visible(actor: dict, company_id: str, cr_no: str) -> dict:
    """One requisition, or 404.

    `company_id` is part of the QUERY rather than a filter applied afterwards, so a caller
    who guesses another tenant's number gets the same answer as for a number that does not
    exist. 404 and not 403: telling a client that a requisition exists but belongs to
    somebody else is itself a disclosure.
    """
    doc = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": cr_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return doc


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def list_client_requisitions(actor: dict, company_id: Optional[str], *,
                                   status: str = None, limit: int = 100) -> dict:
    """The client's own requisitions, or the whole queue for Sparsh staff.

    `company_id` arrives already scoped by the route. For a client-side caller it is their
    own company and nothing else; for Sparsh staff it may be None, which means every client.
    """
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    elif not is_internal_user(actor):
        # Belt and braces. A client-side caller with no resolved company must see nothing,
        # never everything — the failure mode of an empty filter is a full table scan
        # across every tenant.
        raise HTTPException(status_code=403, detail="No company in scope.")
    if status:
        query["status"] = status

    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_CLIENT_REQUISITIONS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "client_requisitions": out,
        "total": len(out),
        # What a Sparsh reviewer leads with: what is sitting on them.
        "pending_feasibility": sum(
            1 for r in out if r.get("status") == ClientReqStatus.PENDING_FEASIBILITY.value),
    }


async def get_client_requisition(actor: dict, company_id: str, cr_no: str) -> dict:
    return _out(await _require_visible(actor, company_id, cr_no))


# ─────────────────────────────────────────────────────────────
# Write — the Need Mapping Form
# ─────────────────────────────────────────────────────────────
async def create_client_requisition(actor: dict, company_id: str, payload: dict) -> dict:
    """Raise a requisition by filling the Need Mapping Form (SOP section 7 step 1)."""
    if not company_id:
        raise HTTPException(status_code=422, detail="No company in scope.")

    context = clean_text(payload.get("business_context"), limit=4000)
    need = clean_text(payload.get("role_need"), limit=4000)
    if not context or not need:
        raise HTTPException(
            status_code=422,
            detail=("A Need Mapping Form needs the business context and the role need. "
                    "Sourcing against a vacancy nobody has explained is what this form "
                    "exists to prevent."))

    now = datetime.now(timezone.utc)
    cr_no = await next_business_id("client_requisition", str(company_id), now.year)
    doc = {
        "cr_no": cr_no,
        "company_id": str(company_id),
        # -- Need Mapping Form --
        "business_context": context,
        "role_need": need,
        "urgency": _enum(payload.get("urgency") or ClientReqUrgency.NORMAL,
                         ClientReqUrgency, "Urgency"),
        "engagement_expectations": clean_text(
            payload.get("engagement_expectations"), limit=4000),
        # -- Manpower Requisition Form, filled at the next stage --
        "role_title": None, "department_name": None, "reporting_line": None,
        "salary_range_min": None, "salary_range_max": None,
        "employment_type": None, "vacancies": None,
        # -- Feasibility review, filled by Sparsh --
        "feasibility": None,
        "status": ClientReqStatus.NEED_MAPPING.value,
        "raised_by": str(actor.get("_id") or ""),
        "raised_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_REQUISITIONS).insert_one(dict(doc))
    await audit(actor, AUDIT_CLIENT_REQ_CREATED, ENTITY_CLIENT_REQUISITION, cr_no,
                f"Need Mapping raised: {need[:80]}", company_id)
    return _out(doc)


async def update_client_requisition(actor: dict, company_id: str, cr_no: str,
                                    payload: dict) -> dict:
    """Amend either form while the requisition is still with the client."""
    current = await _require_visible(actor, company_id, cr_no)
    if current.get("status") not in CLIENT_REQ_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=(f'{cr_no} is "{current.get("status")}" and can no longer be edited. '
                    f"Only a requisition still with the client may be amended."))

    updates: dict = {}
    for field, limit in (("business_context", 4000), ("role_need", 4000),
                         ("engagement_expectations", 4000), ("role_title", 200),
                         ("department_name", 200), ("reporting_line", 200)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)

    if payload.get("urgency") is not None:
        updates["urgency"] = _enum(payload["urgency"], ClientReqUrgency, "Urgency")
    if payload.get("employment_type") is not None:
        updates["employment_type"] = _enum(
            payload["employment_type"], EmploymentTypeClient, "Employment type")
    if payload.get("vacancies") is not None:
        try:
            count = int(payload["vacancies"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Vacancies must be a whole number.")
        if not 1 <= count <= MAX_VACANCIES:
            raise HTTPException(
                status_code=422,
                detail=f"Vacancies must be between 1 and {MAX_VACANCIES}.")
        updates["vacancies"] = count

    lo = payload.get("salary_range_min")
    hi = payload.get("salary_range_max")
    if lo is not None:
        updates["salary_range_min"] = _money(lo, "The minimum of the salary range")
    if hi is not None:
        updates["salary_range_max"] = _money(hi, "The maximum of the salary range")
    new_lo = updates.get("salary_range_min", current.get("salary_range_min"))
    new_hi = updates.get("salary_range_max", current.get("salary_range_max"))
    if new_lo is not None and new_hi is not None and float(new_lo) > float(new_hi):
        raise HTTPException(
            status_code=422,
            detail="The bottom of the salary range cannot be above the top of it.")

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_REQUISITIONS).update_one(
        {"cr_no": cr_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_CLIENT_REQ_UPDATED, ENTITY_CLIENT_REQUISITION, cr_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_requisition(actor, company_id, cr_no)


# ─────────────────────────────────────────────────────────────
# The state machine
# ─────────────────────────────────────────────────────────────
def _assert_requisition_form_complete(doc: dict) -> None:
    """SOP section 7: no sourcing until BOTH forms are complete.

    Checked when the client submits for review rather than when they type, so a
    half-finished form can be saved and come back to.
    """
    required = [("role_title", "the role title"),
                ("department_name", "the department"),
                ("reporting_line", "the reporting line"),
                ("salary_range_min", "the salary range"),
                ("salary_range_max", "the salary range"),
                ("employment_type", "the employment type")]
    missing = []
    for field, label in required:
        if doc.get(field) in (None, ""):
            if label not in missing:
                missing.append(label)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=("The Manpower Requisition Form is not complete. Still needed: "
                    + ", ".join(missing) + "."))


def _feasibility_from(payload: dict) -> dict:
    """The three assessments SOP section 7 step 3 names, all required on an approval."""
    result = {}
    missing = []
    for key, label in FEASIBILITY_CHECKS:
        value = payload.get(key)
        if value is None:
            missing.append(label)
        else:
            result[key] = bool(value)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=("Record the feasibility assessment before approving. Still needed: "
                    + ", ".join(missing) + "."))
    return result


async def act_on_client_requisition(actor: dict, company_id: str, cr_no: str,
                                    action: str, payload: dict = None) -> dict:
    """Move a requisition along CLIENT_REQ_TRANSITIONS.

    The capability for each action is read FROM THE TABLE, so the gate can never drift from
    the state machine it guards — the same discipline the internal chain follows.
    """
    payload = payload or {}
    spec = CLIENT_REQ_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_REQ_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=(f'"{action}" needs {capability.value}, which your role does not hold.'))

    current = await _require_visible(actor, company_id, cr_no)
    status = current.get("status")

    if status in CLIENT_REQ_CLOSED:
        raise HTTPException(
            status_code=409,
            detail=(f'{cr_no} is "{status}" and cannot progress. Raise a new requisition '
                    f"if the need still stands."))
    if status != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{cr_no} is "{status}", so "{action}" does not apply to it.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail=("Say why. A refusal the client cannot act on is a wall, not a "
                    "decision."))

    updates: dict = {"status": target.value,
                     "updated_at": datetime.now(timezone.utc)}

    if action == "submit-requisition":
        _assert_requisition_form_complete(current)
    if action == "feasibility-approve":
        checks = _feasibility_from(payload)
        failed = [label for key, label in FEASIBILITY_CHECKS if not checks.get(key)]
        if failed:
            raise HTTPException(
                status_code=409,
                detail=("These feasibility checks did not pass: " + ", ".join(failed)
                        + ". Return the requisition to the client or reject it; an "
                        "approval that records a failed check contradicts itself."))
    if action.startswith("feasibility-"):
        updates["feasibility"] = {
            **(_feasibility_from(payload) if action == "feasibility-approve" else {}),
            "decision": action.split("-", 1)[1],
            "remarks": remarks,
            "reviewed_by": str(actor.get("_id") or ""),
            "reviewed_by_name": _actor_name(actor),
            "reviewed_at": updates["updated_at"],
        }

    # Conditional on the status as it was read: two reviewers acting at once must not both
    # land, the same rule the internal chain and the exception log follow.
    result = await get_collection(COLL_CLIENT_REQUISITIONS).update_one(
        {"cr_no": cr_no, "company_id": str(company_id), "status": status},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this requisition. Reload and try again.")

    await audit(actor, AUDIT_CLIENT_REQ_ACTIONED, ENTITY_CLIENT_REQUISITION, cr_no,
                f"{status} -> {target.value} ({action})"
                + (f": {remarks}" if remarks else ""), company_id)
    return await get_client_requisition(actor, company_id, cr_no)


async def is_activated(company_id: str, cr_no: str) -> bool:
    """Whether the Position Scorecard stage may begin for this requisition.

    The one thing later steps should ask. Written here rather than re-derived by each
    caller, so widening what counts as activated is a one-line change in one place.
    """
    doc = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": cr_no, "company_id": str(company_id)}, {"status": 1})
    return bool(doc) and doc.get("status") == ClientReqStatus.APPROVED.value
