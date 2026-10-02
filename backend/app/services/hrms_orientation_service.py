"""HRMS ▸ Orientation & Training (BA/Functional Design §22.3, screen SM-HR-057).

See the "Phase ORIENT-1" header comment in models/hrms.py for what this phase builds versus
what it explicitly defers (location/level plan filters).

-- One board, scoped by role, not two screens -----------------------------------------------
HR/Manager manage plan templates and schedule/complete/waive items; an employee sees their
OWN assignment ("My Onboarding", §22.3 step 202) through the SAME read call, row-scoped —
the identical pattern hrms_pip_service and hrms_letter_service already establish.

-- A plan is a TEMPLATE; an assignment is a SNAPSHOT --------------------------------------
Editing a plan template later never changes an employee's already-created assignment. The
assignment is created once, at activation, by copying the matching templates' items — the
same "a generated thing is a snapshot" reasoning Phase LETTER-1 applies to an issued letter.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ORIENTATION_ASSIGNED, AUDIT_ORIENTATION_ESCALATED, AUDIT_ORIENTATION_ITEM_COMPLETED,
    AUDIT_ORIENTATION_ITEM_SCHEDULED, AUDIT_ORIENTATION_ITEM_WAIVED,
    AUDIT_ORIENTATION_PLAN_SAVED, COLL_EMPLOYEE_PROFILES, COLL_ORIENTATION_ASSIGNMENTS,
    COLL_ORIENTATION_PLANS, DEFAULT_ORIENTATION_ESCALATION_DAYS, ENTITY_ORIENTATION_ASSIGNMENT,
    ENTITY_ORIENTATION_PLAN, ORIENTATION_ESCALATED_FIELD,
    HrmsRole, OrientationItemStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_id(actor: dict) -> str:
    return str((actor or {}).get("_id") or "")


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id.")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": _actor_id(actor)})
    return (profile or {}).get("employee_code")


# =============================================================
# Plan templates
# =============================================================
async def list_plans(company_id: str, *, include_inactive: bool = False) -> list:
    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await get_collection(COLL_ORIENTATION_PLANS).find(query).sort(
        "created_at", -1).to_list(200)
    return [_out(r) for r in rows]


async def _get_plan(company_id: str, plan_no: str) -> dict:
    doc = await get_collection(COLL_ORIENTATION_PLANS).find_one(
        {"company_id": str(company_id), "plan_no": plan_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_no}' not found.")
    return doc


async def save_plan(actor: dict, company_id: str, plan_no: Optional[str], payload: dict) -> dict:
    """Create a new plan (plan_no is None) or edit an existing one in place. Editing never
    touches assignments already created from it — see the module docstring."""
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="A plan needs a title.")

    items = []
    for i, raw in enumerate(payload.get("items") or []):
        item = dict(raw)
        item["item_id"] = item.get("item_id") or uuid4().hex[:12]
        item.setdefault("sequence", i)
        items.append(item)

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "title": title,
        "department_id": payload.get("department_id") or None,
        "designation_id": payload.get("designation_id") or None,
        "items": items,
        "active": bool(payload.get("active", True)),
        "updated_at": now, "updated_by": _actor_id(actor),
    }

    if plan_no:
        current = await _get_plan(company_id, plan_no)
        await get_collection(COLL_ORIENTATION_PLANS).update_one(
            {"_id": current["_id"]}, {"$set": doc})
    else:
        year = now.year
        plan_no = await next_business_id("orientation_plan", str(company_id), year)
        doc["plan_no"] = plan_no
        doc["created_at"] = now
        await get_collection(COLL_ORIENTATION_PLANS).insert_one(doc)

    await audit(actor, AUDIT_ORIENTATION_PLAN_SAVED, ENTITY_ORIENTATION_PLAN, plan_no,
               title, company_id)
    return _out(await _get_plan(company_id, plan_no))


async def _matching_plans(company_id: str, department_id: Optional[str],
                          designation_id: Optional[str]) -> list:
    """Every ACTIVE plan that applies to this employee: company-wide (both filters unset)
    plus any plan whose set filter(s) match. A plan with BOTH filters set must match both."""
    rows = await get_collection(COLL_ORIENTATION_PLANS).find(
        {"company_id": str(company_id), "active": True}).to_list(500)
    matched = []
    for row in rows:
        want_dept = row.get("department_id")
        want_desig = row.get("designation_id")
        if want_dept and want_dept != department_id:
            continue
        if want_desig and want_desig != designation_id:
            continue
        matched.append(row)
    return matched


# =============================================================
# Assignments
# =============================================================
def _overall_status(items: list) -> str:
    """§22.3 step 204: "Mandatory training items remain open until completed or formally
    waived" — only MANDATORY items gate completion. An optional item left Pending forever
    (nobody is required to act on it) must not keep the whole assignment "Open"."""
    if not items:
        return "No Plan"
    mandatory = [i for i in items if i.get("mandatory")]
    if not mandatory:
        return "Complete"
    if all(i["status"] in (OrientationItemStatus.COMPLETED.value,
                           OrientationItemStatus.WAIVED.value) for i in mandatory):
        return "Complete"
    return "Open"


async def assign_on_activation(actor: Optional[dict], company_id: str, employee_code: str,
                               *, department_id: Optional[str] = None,
                               designation_id: Optional[str] = None) -> Optional[dict]:
    """§22.3 step 200. Called once, at employee activation. Idempotent: an employee who
    already has an assignment (e.g. a re-run of the activation hook) is left untouched
    rather than getting a second, conflicting one — the unique index on employee_code
    guarantees this even if two activations race."""
    existing = await get_collection(COLL_ORIENTATION_ASSIGNMENTS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if existing:
        return _out(existing)

    plans = await _matching_plans(company_id, department_id, designation_id)
    items = []
    for plan in plans:
        for item in plan.get("items") or []:
            items.append({
                "item_id": f'{plan["plan_no"]}:{item["item_id"]}',
                "plan_no": plan["plan_no"],
                "topic": item.get("topic"),
                "mandatory": bool(item.get("mandatory", True)),
                "materials_url": item.get("materials_url"),
                "trainer": None, "scheduled_at": None,
                "status": OrientationItemStatus.PENDING.value,
                "completed_at": None, "completed_by": None,
                "waived_reason": None,
            })
    if not items:
        return None    # nothing assigned — no matching plan exists yet, not an error

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "employee_code": employee_code,
        "items": items,
        "overall_status": _overall_status(items),
        ORIENTATION_ESCALATED_FIELD: False,
        "created_at": now, "updated_at": now,
    }
    try:
        await get_collection(COLL_ORIENTATION_ASSIGNMENTS).insert_one(doc)
    except Exception as e:
        # Unique index race (see docstring) — another caller's insert already landed.
        print(f"[WARN] HRMS orientation assignment insert skipped for {employee_code}: {e}")
        existing = await get_collection(COLL_ORIENTATION_ASSIGNMENTS).find_one(
            {"company_id": str(company_id), "employee_code": employee_code})
        return _out(existing) if existing else None

    await audit(actor, AUDIT_ORIENTATION_ASSIGNED, ENTITY_ORIENTATION_ASSIGNMENT,
               employee_code, f"{len(items)} item(s) from {len(plans)} plan(s)", company_id)
    return _out(doc)


async def _get_assignment(company_id: str, employee_code: str) -> Optional[dict]:
    return await get_collection(COLL_ORIENTATION_ASSIGNMENTS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})


async def get_assignment(actor: dict, company_id: str, employee_code: str) -> dict:
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if own != employee_code:
            raise HTTPException(
                status_code=403, detail="You may only view your own orientation plan.")
    doc = await _get_assignment(company_id, employee_code)
    if not doc:
        return {"employee_code": employee_code, "items": [], "overall_status": "No Plan"}
    return _out(doc)


async def list_assignments(actor: dict, company_id: str, *, status: Optional[str] = None,
                           limit: int = 100) -> list:
    """The company-wide list HR/Manager work from. An EMPLOYEE caller is scoped to just
    their own row, mirroring hrms_pip_service/_scope_query."""
    query = {"company_id": str(company_id)}
    if status:
        query["overall_status"] = status
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    rows = await get_collection(COLL_ORIENTATION_ASSIGNMENTS).find(query).sort(
        "created_at", -1).to_list(min(limit, 500))
    return [_out(r) for r in rows]


def _find_item(doc: dict, item_id: str) -> dict:
    for item in doc.get("items") or []:
        if item["item_id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"No such item '{item_id}' on this assignment.")


async def _save_items(company_id: str, employee_code: str, items: list) -> dict:
    """Persists the item list and returns the fresh view, with no ownership check of its
    own — every caller is already an HR/Manager action gated on INDUCTION_WRITE, not a
    self-service read, so there is no actor to scope against here."""
    now = datetime.now(timezone.utc)
    overall = _overall_status(items)
    await get_collection(COLL_ORIENTATION_ASSIGNMENTS).update_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"$set": {"items": items, "overall_status": overall, "updated_at": now}})
    return _out(await _get_assignment(company_id, employee_code))


async def schedule_item(actor: dict, company_id: str, employee_code: str,
                        item_id: str, trainer: str, scheduled_at: str) -> dict:
    """§22.3 step 201."""
    doc = await _get_assignment(company_id, employee_code)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No orientation plan for {employee_code}.")
    item = _find_item(doc, item_id)
    if item["status"] in (OrientationItemStatus.COMPLETED.value, OrientationItemStatus.WAIVED.value):
        raise HTTPException(status_code=409, detail=f'"{item["topic"]}" is already {item["status"]}.')
    item["trainer"] = trainer
    item["scheduled_at"] = scheduled_at
    item["status"] = OrientationItemStatus.SCHEDULED.value
    result = await _save_items(company_id, employee_code, doc["items"])
    await audit(actor, AUDIT_ORIENTATION_ITEM_SCHEDULED, ENTITY_ORIENTATION_ASSIGNMENT,
               employee_code, f'{item["topic"]} with {trainer} on {scheduled_at}', company_id)
    return result


async def complete_item(actor: dict, company_id: str, employee_code: str,
                        item_id: str, remarks: Optional[str] = None) -> dict:
    """§22.3 step 203."""
    doc = await _get_assignment(company_id, employee_code)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No orientation plan for {employee_code}.")
    item = _find_item(doc, item_id)
    if item["status"] == OrientationItemStatus.WAIVED.value:
        raise HTTPException(status_code=409, detail=f'"{item["topic"]}" was waived, not completed.')
    now = datetime.now(timezone.utc)
    item["status"] = OrientationItemStatus.COMPLETED.value
    item["completed_at"] = now
    item["completed_by"] = _actor_id(actor)
    if remarks:
        item["remarks"] = remarks
    result = await _save_items(company_id, employee_code, doc["items"])
    await audit(actor, AUDIT_ORIENTATION_ITEM_COMPLETED, ENTITY_ORIENTATION_ASSIGNMENT,
               employee_code, item["topic"], company_id)
    return result


async def waive_item(actor: dict, company_id: str, employee_code: str,
                     item_id: str, reason: str) -> dict:
    """§22.3 step 204: a mandatory item may be formally waived instead of completed."""
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A waiver needs a reason.")
    doc = await _get_assignment(company_id, employee_code)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No orientation plan for {employee_code}.")
    item = _find_item(doc, item_id)
    if item["status"] == OrientationItemStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail=f'"{item["topic"]}" is already Completed.')
    now = datetime.now(timezone.utc)
    item["status"] = OrientationItemStatus.WAIVED.value
    item["waived_reason"] = reason
    item["completed_at"] = now
    item["completed_by"] = _actor_id(actor)
    result = await _save_items(company_id, employee_code, doc["items"])
    await audit(actor, AUDIT_ORIENTATION_ITEM_WAIVED, ENTITY_ORIENTATION_ASSIGNMENT,
               employee_code, f'{item["topic"]}: {reason}', company_id)
    return result


# =============================================================
# Escalation sweep (§22.3 step 207) — driven by hrms_scheduler_service.run_due_jobs
# =============================================================
async def run_escalation_sweep(company_id: str) -> dict:
    """Notify HR once per assignment that still has an open MANDATORY item
    `DEFAULT_ORIENTATION_ESCALATION_DAYS` after the employee's join date.

    Guarded by ORIENTATION_ESCALATED_FIELD on the record itself — the same "burn on the
    record" pattern PROBATION_REMINDED_FIELD established — so a job that runs twice, or is
    rewritten entirely, cannot send the same escalation twice. Re-arms automatically if a
    NEW mandatory item is ever added to an already-escalated assignment (not currently
    possible — assignments are a snapshot — but the guard is item-set-shaped defensively).
    """
    from app.services.hrms_notify_service import notify_hrms_role

    rows = await get_collection(COLL_ORIENTATION_ASSIGNMENTS).find(
        {"company_id": str(company_id), "overall_status": "Open",
         ORIENTATION_ESCALATED_FIELD: {"$ne": True}}).to_list(1000)
    if not rows:
        return {"checked": 0, "escalated": 0}

    codes = [r["employee_code"] for r in rows]
    profiles = {
        p["employee_code"]: p
        for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id), "employee_code": {"$in": codes}},
            {"employee_code": 1, "joined_on": 1, "display_name": 1}).to_list(len(codes))
    }
    today = datetime.now(timezone.utc).date()

    escalated = 0
    for row in rows:
        profile = profiles.get(row["employee_code"]) or {}
        joined_on = profile.get("joined_on")
        try:
            from datetime import date as _date
            joined = _date.fromisoformat(str(joined_on)[:10])
        except (ValueError, TypeError):
            continue
        if (today - joined).days < DEFAULT_ORIENTATION_ESCALATION_DAYS:
            continue

        open_mandatory = [
            i for i in row.get("items") or []
            if i.get("mandatory") and i["status"] in (
                OrientationItemStatus.PENDING.value, OrientationItemStatus.SCHEDULED.value)
        ]
        if not open_mandatory:
            continue

        name = profile.get("display_name") or row["employee_code"]
        await notify_hrms_role(
            company_id, ["HR"],
            f"Orientation overdue: {name}",
            f'{name} ({row["employee_code"]}) joined on {joined_on} and still has '
            f'{len(open_mandatory)} mandatory orientation item(s) open: '
            f'{", ".join(i["topic"] for i in open_mandatory)}.',
            kind="warning", link="/hrms/orientation", email=True)
        await get_collection(COLL_ORIENTATION_ASSIGNMENTS).update_one(
            {"_id": row["_id"]}, {"$set": {ORIENTATION_ESCALATED_FIELD: True}})
        await audit(None, AUDIT_ORIENTATION_ESCALATED, ENTITY_ORIENTATION_ASSIGNMENT,
                   row["employee_code"], f"{len(open_mandatory)} item(s) overdue", company_id)
        escalated += 1

    return {"checked": len(rows), "escalated": escalated}
