"""HRMS ▸ department and designation masters.

Both are company-scoped reference data with identical shape, so they share one service
rather than two near-duplicates (DRY). The only real difference is which collection and
which audit action a call touches, so that is parameterised.

── Why these exist as masters ────────────────────────────────────────────────────
The source HRMS had no department or designation admin at all: departments were a
hard-coded dropdown that disagreed with a second hard-coded dropdown elsewhere in the same
screen, and designation was free text (FRONTEND_ANALYSIS §2, §15). Requisitions, JDs,
employees and reporting all key off these, so they are proper masters here.

── Why we do NOT seed from the user directory ────────────────────────────────────
The roadmap proposed seeding departments from distinct `users.department` values. Inspecting
the live data showed that field holds genuine but badly-normalised values -- 'ACCOUNT',
'Accounts', 'Account & Finance' and 'Accounts & Finance' all coexist, alongside the typo
'Administraion'. Auto-seeding would promote that mess into the authoritative master and
every later phase would inherit it.

Instead `suggest_from_directory()` returns the distinct values WITH usage counts, read-only,
so HR can create the clean set deliberately. Same review-before-import philosophy as the
Phase 12 holiday import. Nothing is ever written to staff/learners.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_DEPARTMENT_CREATED, AUDIT_DEPARTMENT_DELETED, AUDIT_DEPARTMENT_UPDATED,
    AUDIT_DESIGNATION_CREATED, AUDIT_DESIGNATION_DELETED, AUDIT_DESIGNATION_UPDATED,
    COLL_DEPARTMENTS, COLL_DESIGNATIONS, COLL_EMPLOYEE_PROFILES,
    ENTITY_DEPARTMENT, ENTITY_DESIGNATION,
)
from app.services.hrms_audit_service import audit

# Master kind -> (collection, entity name, audit actions, profile field referencing it)
_KINDS = {
    "department": (
        COLL_DEPARTMENTS, ENTITY_DEPARTMENT,
        (AUDIT_DEPARTMENT_CREATED, AUDIT_DEPARTMENT_UPDATED, AUDIT_DEPARTMENT_DELETED),
        "department_id",
    ),
    "designation": (
        COLL_DESIGNATIONS, ENTITY_DESIGNATION,
        (AUDIT_DESIGNATION_CREATED, AUDIT_DESIGNATION_UPDATED, AUDIT_DESIGNATION_DELETED),
        "designation_id",
    ),
}


def _spec(kind: str):
    if kind not in _KINDS:
        raise ValueError(f"Unknown master kind: {kind}")
    return _KINDS[kind]


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _clean_name(name: str, label: str) -> str:
    """Trim and collapse internal whitespace.

    Without this, 'Sales' and 'Sales ' are two different masters as far as the unique index
    is concerned -- exactly how the source ended up with four spellings of Accounts.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{label} name is required.")
    if len(cleaned) > 120:
        raise HTTPException(status_code=422, detail=f"{label} name must be 120 characters or fewer.")
    return cleaned


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _seniority(value):
    """The SOP's seniority band for a designation, validated.

    This field was accepted by DesignationIn and DesignationUpdate, passed through the
    route, and then silently dropped here -- so it could not be set through the API at all.
    Every designation therefore read as the default band, which quietly disabled two rules
    stated in terms of it: the panel composition for senior roles, and the mandatory
    Management final round before a managerial candidate can be selected. A control that
    cannot be configured is a control that never fires.

    None means "leave it unset", which `designation_level()` reads as the default band.
    """
    from app.models.hrms import DesignationLevel
    raw = getattr(value, "value", value)
    if raw is None or raw == "":
        return None
    try:
        return DesignationLevel(raw).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=("Seniority must be one of: "
                    + ", ".join(level.value for level in DesignationLevel) + "."))


async def list_masters(kind: str, company_id: str, include_inactive: bool = False) -> list:
    coll_name, _entity, _actions, _ref = _spec(kind)
    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await get_collection(coll_name).find(query).sort("name", 1).to_list(1000)
    return [_out(r) for r in rows]


async def get_master(kind: str, company_id: str, master_id: str) -> Optional[dict]:
    """Fetch one master, scoped to the company.

    company_id is part of the QUERY, not a post-filter, so a caller cannot read another
    tenant's master by guessing an ObjectId.
    """
    coll_name, _entity, _actions, _ref = _spec(kind)
    doc = await get_collection(coll_name).find_one(
        {"_id": _oid(master_id, kind), "company_id": str(company_id)}
    )
    return _out(doc) if doc else None


async def create_master(kind: str, company_id: str, payload: dict, actor: dict) -> dict:
    coll_name, entity, actions, _ref = _spec(kind)
    label = kind.capitalize()
    name = _clean_name(payload.get("name"), label)

    coll = get_collection(coll_name)
    # Case-insensitive duplicate check. The unique index is case-SENSITIVE, so without this
    # 'Sales' and 'sales' would both be accepted and become two masters.
    existing = await coll.find_one({
        "company_id": str(company_id),
        "name": {"$regex": f"^{_escape_regex(name)}$", "$options": "i"},
    })
    if existing:
        raise HTTPException(status_code=409, detail=f"{label} '{name}' already exists.")

    doc = {
        "company_id": str(company_id),
        "name": name,
        "code": (payload.get("code") or "").strip() or None,
        "description": (payload.get("description") or "").strip() or None,
        "active": bool(payload.get("active", True)),
        "created_at": datetime.now(timezone.utc),
        "created_by": str(actor.get("_id")) if actor.get("_id") else None,
    }
    if kind == "department":
        doc["head_user_id"] = payload.get("head_user_id") or None
    else:
        level = payload.get("level")
        doc["level"] = int(level) if level is not None else None
        # The SOP's band, separate from the numeric grade above on purpose: `level` is an
        # integer a company numbers however it likes, and the four fixed bands are what the
        # panel and final-round rules are actually written in terms of.
        doc["designation_level"] = _seniority(payload.get("designation_level"))

    try:
        result = await coll.insert_one(doc)
    except Exception as e:
        # The unique index is the real guard; the check above is only for a friendly message.
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(status_code=409, detail=f"{label} '{name}' already exists.")
        raise

    doc["_id"] = result.inserted_id
    await audit(actor, actions[0], entity, str(result.inserted_id), name, company_id)
    return _out(doc)


async def update_master(kind: str, company_id: str, master_id: str, payload: dict, actor: dict) -> dict:
    coll_name, entity, actions, _ref = _spec(kind)
    label = kind.capitalize()
    coll = get_collection(coll_name)
    oid = _oid(master_id, kind)

    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail=f"{label} not found.")

    updates = {}
    if payload.get("name") is not None:
        name = _clean_name(payload["name"], label)
        clash = await coll.find_one({
            "company_id": str(company_id),
            "_id": {"$ne": oid},
            "name": {"$regex": f"^{_escape_regex(name)}$", "$options": "i"},
        })
        if clash:
            raise HTTPException(status_code=409, detail=f"{label} '{name}' already exists.")
        updates["name"] = name

    for field in ("code", "description"):
        if payload.get(field) is not None:
            updates[field] = (payload[field] or "").strip() or None
    if payload.get("active") is not None:
        updates["active"] = bool(payload["active"])
    if kind == "department" and payload.get("head_user_id") is not None:
        updates["head_user_id"] = payload["head_user_id"] or None
    if kind == "designation" and payload.get("level") is not None:
        updates["level"] = int(payload["level"])
    # Present-but-None is meaningful here: it clears the band back to the default, which is
    # why this tests for the KEY rather than for a truthy value.
    if kind == "designation" and "designation_level" in payload:
        updates["designation_level"] = _seniority(payload["designation_level"])

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"_id": oid}, {"$set": updates})
    await audit(actor, actions[1], entity, master_id,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_master(kind, company_id, master_id)


async def delete_master(kind: str, company_id: str, master_id: str, actor: dict) -> dict:
    """Delete a master, refusing while any employee still references it.

    Referential integrity is application-enforced (Mongo has no FKs), and the source's
    total absence of it is called out as Risk #4. Deleting a referenced department would
    leave employees pointing at nothing, so we 409 and tell the caller how many rows block
    it -- deactivating (`active: false`) is the non-destructive alternative.
    """
    coll_name, entity, actions, ref_field = _spec(kind)
    label = kind.capitalize()
    coll = get_collection(coll_name)
    oid = _oid(master_id, kind)

    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail=f"{label} not found.")

    in_use = await get_collection(COLL_EMPLOYEE_PROFILES).count_documents(
        {"company_id": str(company_id), ref_field: master_id}
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(f"{label} '{current.get('name')}' is assigned to {in_use} employee(s). "
                    f"Reassign them first, or set it inactive instead of deleting."),
        )

    await coll.delete_one({"_id": oid})
    await audit(actor, actions[2], entity, master_id, current.get("name"), company_id)
    return {"deleted": True, "id": master_id, "name": current.get("name")}


async def suggest_from_directory(company_id: str) -> dict:
    """Distinct department/designation values already present on this company's users,
    with usage counts. READ-ONLY -- nothing is written to `learners`, and nothing is
    auto-created.

    Exists so HR can build a clean master from real data instead of retyping it, while
    still deciding that 'ACCOUNT', 'Accounts' and 'Accounts & Finance' should collapse into
    one entry. See the module docstring for why auto-seeding was rejected.
    """
    pipeline_for = lambda field: [
        {"$match": {"company_id": str(company_id), field: {"$nin": [None, ""]}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 200},
    ]
    learners = get_collection("learners")
    out = {}
    for kind, field in (("departments", "department"), ("designations", "designation")):
        rows = await learners.aggregate(pipeline_for(field)).to_list(200)
        out[kind] = [{"name": r["_id"], "count": r["count"]} for r in rows if r.get("_id")]

    # Flag which suggestions already exist so the UI can show "new" vs "already added".
    for kind, coll_name in (("departments", COLL_DEPARTMENTS), ("designations", COLL_DESIGNATIONS)):
        existing = {
            (d.get("name") or "").strip().lower()
            for d in await get_collection(coll_name).find(
                {"company_id": str(company_id)}, {"name": 1}
            ).to_list(1000)
        }
        for row in out[kind]:
            row["exists"] = row["name"].strip().lower() in existing
    return out


def _escape_regex(value: str) -> str:
    import re
    return re.escape(value)
