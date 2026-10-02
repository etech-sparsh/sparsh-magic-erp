"""HRMS > sanctioned strength vs actual headcount (Phase 11-R, Item 7).

The authorised headcount per position, and the live comparison a requisition is judged
against.

-- Sanctioned is STORED; actual is DERIVED ------------------------------------------------
This is the whole design. `sanctioned_count` is a decision somebody made, so it is written
down. `actual` is a fact about the world, so it is COUNTED from `hrms_employee_profiles` on
every read and never stored. A stored actual would be wrong the moment somebody resigns —
and "somebody resigned, can we backfill" is precisely the question this feature exists to
answer, so being stale exactly then would make it useless.

`open_requisitions` is counted the same way: approved, still-open requisitions represent
seats already committed. Leaving them out would let five requisitions for one seat each all
pass the check independently, which is the classic double-spend of headcount.

-- Granularity: department + designation ---------------------------------------------------
Confirmed with the business (PHASE_11R_REPORT §Decisions). A location axis was considered and
rejected for this phase: employee profiles carry no location field, so `actual` could not be
derived per location, and a sanctioned figure you cannot compare against anything is worse
than none.

-- No figure at all means OVER-SANCTION ----------------------------------------------------
See models.is_over_sanction. A headcount nobody has authorised is exactly the case that
should be escalated rather than waved through, so the rule fails CLOSED. Companies that do
not run sanctioned strength will find everything escalates — which is why the requisition
form says so plainly before the requisition is raised.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SANCTION_CREATED, AUDIT_SANCTION_DELETED, AUDIT_SANCTION_UPDATED,
    COLL_DEPARTMENTS, COLL_DESIGNATIONS, COLL_EMPLOYEE_PROFILES, COLL_REQUISITIONS,
    COLL_SANCTIONED_STRENGTH, ENTITY_SANCTION, PAYABLE_STATUSES, ReqApproval, ReqClosing,
    is_iso_date, is_over_sanction,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _resolve_masters(company_id: str, department_id: str, designation_id: str) -> tuple:
    """Both references must exist AND belong to this company.

    Part of the query rather than a post-check, so a crafted id from another tenant finds
    nothing — the same rule hrms_requisition_service._resolve_master applies.
    """
    dept = await get_collection(COLL_DEPARTMENTS).find_one(
        {"_id": _oid(department_id, "department"), "company_id": str(company_id)})
    if not dept:
        raise HTTPException(
            status_code=422, detail="Department does not exist for this company.")
    desig = await get_collection(COLL_DESIGNATIONS).find_one(
        {"_id": _oid(designation_id, "designation"), "company_id": str(company_id)})
    if not desig:
        raise HTTPException(
            status_code=422, detail="Designation does not exist for this company.")
    return dept, desig


def _validate_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422, detail="Sanctioned count must be a whole number.")
    if count < 0:
        raise HTTPException(status_code=422, detail="Sanctioned count cannot be negative.")
    if count > 100000:
        raise HTTPException(status_code=422, detail="Sanctioned count is implausibly large.")
    return count


# -------------------------------------------------------------
# The master
# -------------------------------------------------------------
async def list_sanctions(company_id: str, *, department_id: str = None) -> dict:
    """Every sanctioned figure, each with its live actual and availability."""
    query = {"company_id": str(company_id)}
    if department_id:
        query["department_id"] = str(department_id)
    rows = await get_collection(COLL_SANCTIONED_STRENGTH).find(query).sort(
        "department_name", 1).to_list(1000)

    out = []
    for r in rows:
        item = _out(r)
        live = await position_status(
            company_id, r.get("department_id"), r.get("designation_id"))
        item.update({k: live[k] for k in
                     ("actual", "open_requisitions", "available", "is_over_sanction")})
        out.append(item)

    return {
        "sanctions": out,
        "total": len(out),
        "stats": {
            "positions": len(out),
            "sanctioned": sum(int(r.get("sanctioned_count") or 0) for r in out),
            "actual": sum(int(r.get("actual") or 0) for r in out),
            "over_sanction": sum(1 for r in out if r.get("is_over_sanction")),
        },
    }


async def set_sanction(actor: dict, company_id: str, payload: dict) -> dict:
    """Create or replace the sanctioned figure for a position.

    An upsert rather than a create: the unique index makes one figure per position the
    rule, so "set it again" is the natural operation and a 409 on the second attempt would
    just make the caller delete-then-create for no benefit.
    """
    department_id = str(payload.get("department_id") or "")
    designation_id = str(payload.get("designation_id") or "")
    if not department_id or not designation_id:
        raise HTTPException(
            status_code=422, detail="Choose both a department and a designation.")

    dept, desig = await _resolve_masters(company_id, department_id, designation_id)
    count = _validate_count(payload.get("sanctioned_count"))

    effective_from = payload.get("effective_from")
    if effective_from and not is_iso_date(effective_from):
        raise HTTPException(
            status_code=422,
            detail="Effective-from must be a valid date in YYYY-MM-DD format.")

    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_SANCTIONED_STRENGTH)
    key = {"company_id": str(company_id), "department_id": department_id,
           "designation_id": designation_id}
    existing = await coll.find_one(key)

    doc = {
        **key,
        "department_name": dept.get("name"),
        "designation_name": desig.get("name"),
        "sanctioned_count": count,
        "effective_from": effective_from or None,
        "notes": clean_text(payload.get("notes"), limit=1000),
        "updated_by": str(actor.get("_id") or ""),
        "updated_at": now,
    }
    if existing:
        await coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        await audit(actor, AUDIT_SANCTION_UPDATED, ENTITY_SANCTION,
                    f"{dept.get('name')}/{desig.get('name')}",
                    f"{existing.get('sanctioned_count')} -> {count}", company_id)
    else:
        doc["created_at"] = now
        await coll.insert_one(dict(doc))
        await audit(actor, AUDIT_SANCTION_CREATED, ENTITY_SANCTION,
                    f"{dept.get('name')}/{desig.get('name')}", str(count), company_id)

    fresh = await coll.find_one(key)
    out = _out(fresh)
    out.update(await position_status(company_id, department_id, designation_id))
    return out


async def update_sanction(actor: dict, company_id: str, sanction_id: str,
                          payload: dict) -> dict:
    coll = get_collection(COLL_SANCTIONED_STRENGTH)
    oid = _oid(sanction_id, "sanctioned strength")
    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Sanctioned strength not found.")

    updates = {}
    if payload.get("sanctioned_count") is not None:
        updates["sanctioned_count"] = _validate_count(payload["sanctioned_count"])
    if payload.get("effective_from") is not None:
        value = payload["effective_from"]
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="Effective-from must be a valid date in YYYY-MM-DD format.")
        updates["effective_from"] = value or None
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=1000)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    updates["updated_by"] = str(actor.get("_id") or "")
    await coll.update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_SANCTION_UPDATED, ENTITY_SANCTION,
                f"{current.get('department_name')}/{current.get('designation_name')}",
                ", ".join(sorted(k for k in updates
                                 if k not in ("updated_at", "updated_by"))), company_id)

    fresh = await coll.find_one({"_id": oid})
    out = _out(fresh)
    out.update(await position_status(
        company_id, fresh.get("department_id"), fresh.get("designation_id")))
    return out


async def delete_sanction(actor: dict, company_id: str, sanction_id: str) -> dict:
    """Remove a sanctioned figure.

    Allowed freely — unlike a department, nothing points AT a sanction row. The consequence
    is stated rather than hidden: the position reverts to "no sanctioned figure", which
    means every future requisition for it escalates (is_over_sanction fails closed).
    """
    coll = get_collection(COLL_SANCTIONED_STRENGTH)
    oid = _oid(sanction_id, "sanctioned strength")
    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Sanctioned strength not found.")

    await coll.delete_one({"_id": oid})
    await audit(actor, AUDIT_SANCTION_DELETED, ENTITY_SANCTION,
                f"{current.get('department_name')}/{current.get('designation_name')}",
                str(current.get("sanctioned_count")), company_id)
    return {
        "deleted": True,
        "id": sanction_id,
        "note": ("This position now has no sanctioned figure, so future requisitions for it "
                 "will be routed for escalation."),
    }


# -------------------------------------------------------------
# The live comparison
# -------------------------------------------------------------
async def actual_headcount(company_id: str, department_id: str, designation_id: str) -> int:
    """Employees currently ON the payroll for this position.

    PAYABLE_STATUSES is reused rather than re-listed: it is the Phase 2 declaration of "still
    on the payroll", and the sanctioned-strength check must mean the same thing by it that
    payroll will.
    """
    if not department_id or not designation_id:
        return 0
    return await get_collection(COLL_EMPLOYEE_PROFILES).count_documents({
        "company_id": str(company_id),
        "department_id": str(department_id),
        "designation_id": str(designation_id),
        "employment_status": {"$in": [s.value for s in PAYABLE_STATUSES]},
    })


async def committed_vacancies(company_id: str, department_id: str, designation_id: str,
                              *, exclude_request_no: str = None) -> int:
    """Seats already committed by APPROVED, still-OPEN requisitions.

    Only Approved+Open counts. A requisition awaiting approval has committed nothing yet
    (counting it would let a pending requisition block itself), and a Hired/Closed/Cancelled
    one is spent -- its people are already in `actual`, so counting both would double them.

    `exclude_request_no` keeps a requisition from being measured against itself when it is
    re-evaluated at an approval step.
    """
    if not department_id or not designation_id:
        return 0
    query = {
        "company_id": str(company_id),
        "department_id": str(department_id),
        "designation_id": str(designation_id),
        "approval_status": ReqApproval.APPROVED.value,
        "closing_status": ReqClosing.OPEN.value,
    }
    if exclude_request_no:
        query["request_no"] = {"$ne": exclude_request_no}
    rows = await get_collection(COLL_REQUISITIONS).find(
        query, {"vacancy": 1}).to_list(2000)
    return sum(int(r.get("vacancy") or 1) for r in rows)


async def position_status(company_id: str, department_id: str, designation_id: str, *,
                          requested: int = 0, exclude_request_no: str = None) -> dict:
    """The live sanctioned/actual/available picture for one position.

    This is what the requisition form reads on every change, and what the approval chain
    re-evaluates at each step — headcount moves between raising and approving, and an
    approver deserves the figures as they are when they decide, not as they were weeks ago.
    """
    sanction = await get_collection(COLL_SANCTIONED_STRENGTH).find_one({
        "company_id": str(company_id),
        "department_id": str(department_id or ""),
        "designation_id": str(designation_id or "")})
    sanctioned = (int(sanction["sanctioned_count"])
                  if sanction and sanction.get("sanctioned_count") is not None else None)

    actual = await actual_headcount(company_id, department_id, designation_id)
    committed = await committed_vacancies(company_id, department_id, designation_id,
                                          exclude_request_no=exclude_request_no)

    over = is_over_sanction(sanctioned, actual, committed, requested)
    return {
        "sanctioned": sanctioned,
        "actual": actual,
        "open_requisitions": committed,
        # None, not a negative number, when nothing is sanctioned: "we do not know" and
        # "there is no room" are different answers and must not render the same.
        "available": (None if sanctioned is None
                      else max(0, sanctioned - actual - committed)),
        "requested": requested,
        "is_over_sanction": over,
        "has_sanction": sanctioned is not None,
    }


async def snapshot_for(company_id: str, requisition: dict, *,
                       exclude_self: bool = True) -> dict:
    """The evaluated figures STORED on a requisition at raise time and at each approval.

    Stored deliberately, and this is the one place a derived figure is written down: the
    approver must be able to see the numbers the decision was made on, and re-deriving them
    later would show a different world. The live figures are still computed alongside it.
    """
    now = datetime.now(timezone.utc)
    status = await position_status(
        company_id,
        requisition.get("department_id"), requisition.get("designation_id"),
        requested=int(requisition.get("vacancy") or 1),
        exclude_request_no=(requisition.get("request_no") if exclude_self else None))
    return {
        "sanctioned": status["sanctioned"],
        "actual": status["actual"],
        "open_requisitions": status["open_requisitions"],
        "requested": status["requested"],
        "is_over_sanction": status["is_over_sanction"],
        "evaluated_at": now,
    }
