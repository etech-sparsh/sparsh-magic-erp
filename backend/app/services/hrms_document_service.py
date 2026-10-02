"""HRMS > the document register (Phase 11-R, Item 2).

Every employee- and candidate-related document in one place, with per-document status,
versioning, expiry and retrieval.

-- What was wrong before ----------------------------------------------------------------
Documents existed only as scattered attachments hanging off other records: a candidate's
resume/photo/certificates on the candidate, KYC scans on the onboarding, JD files on the JD.
There was no register, no per-document status, no expiry, no version history and nowhere to
answer "has this person given us their PAN card yet".

-- Existing files are SURFACED, never COPIED -----------------------------------------------
This is the single most important design decision in this module. Candidate resumes and
onboarding KYC scans keep living on their own documents; `list_for_owner` projects them into
the register's view shape with `source: "linked"` and `read_only: true`. Copying the S3
objects into `hrms_documents` would create a second copy that drifts the moment either side
is edited, double the storage, and make "which one is current" unanswerable. Only documents
uploaded THROUGH this module get rows of their own.

-- Expiry is computed, never stored --------------------------------------------------------
`expiry_date < today` reads as Expired at read time, exactly as hrms_posting_service computes
a posting's expiry and hrms_link_service a link's. A stored flag would be wrong for a day
after every renewal, and the renewal is the case that matters.

-- The file is immutable; corrections are versions -----------------------------------------
`update_document` changes metadata only. Replacing a blurry scan adds a VERSION, so what was
actually submitted at each point survives — which is the whole reason to have a register
rather than a folder.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_DOCTYPE_CREATED, AUDIT_DOCTYPE_DELETED, AUDIT_DOCTYPE_UPDATED,
    AUDIT_DOCUMENT_DELETED, AUDIT_DOCUMENT_STATUS, AUDIT_DOCUMENT_UPDATED,
    AUDIT_DOCUMENT_UPLOADED, AUDIT_DOCUMENT_VERSIONED, COLL_CANDIDATES, COLL_DOCUMENTS,
    COLL_DOCUMENT_TYPES, COLL_EMPLOYEE_PROFILES, COLL_ONBOARDING, COLL_REQUISITIONS,
    DEFAULT_DOCUMENT_TYPES, DOCUMENT_EXPIRY_SOON_DAYS,
    DOCUMENT_STATUSES_REQUIRING_REMARKS, ENTITY_DOCUMENT, ENTITY_DOCUMENT_TYPE,
    MAX_DOCUMENT_VERSIONS, DocumentCategory, DocumentOwnerType, DocumentStatus, HrmsRole,
    is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role
from app.utils.hrms_public_guard import clean_text, decode_upload

APPLIES_TO_VALUES = {"candidate", "employee", "both"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "system")


# =============================================================
# Document types — the per-company master
# =============================================================
def _type_out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def list_document_types(company_id: str, *, include_inactive: bool = False,
                              applies_to: str = None) -> list:
    """The company's document types, seeding a sensible default set on first read.

    Seeding on READ rather than in a migration keeps this phase migration-free (§3.2) and
    means a company created later gets the same starting point without anybody remembering
    to run something. It fires exactly once — the moment any type exists, seeding stops.
    """
    coll = get_collection(COLL_DOCUMENT_TYPES)
    if not await coll.count_documents({"company_id": str(company_id)}):
        await _seed_types(company_id)

    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await coll.find(query).sort("name", 1).to_list(500)
    if applies_to in ("candidate", "employee"):
        rows = [r for r in rows if (r.get("applies_to") or "both") in (applies_to, "both")]
    return [_type_out(r) for r in rows]


async def _seed_types(company_id: str) -> None:
    now = datetime.now(timezone.utc)
    docs = [{
        "company_id": str(company_id),
        "name": name,
        "code": None,
        "category": category.value,
        "applies_to": applies_to,
        "mandatory": mandatory,
        "expires": expires,
        # ── Phase INT-2, SOP §11 ── distinct from `mandatory`: this one decides whether
        # probation confirmation is BLOCKED until the document is Verified. Seeded true on
        # the identity and education types only.
        "statutory_required": statutory,
        "active": True,
        "seeded": True,          # so an operator can tell defaults from their own additions
        "created_at": now,
    } for name, category, applies_to, mandatory, expires, statutory
        in DEFAULT_DOCUMENT_TYPES]
    try:
        await get_collection(COLL_DOCUMENT_TYPES).insert_many(docs)
    except Exception as e:
        # A concurrent first read may have seeded already; the unique index makes that safe
        # to ignore rather than a reason to fail the caller's list.
        print(f"[WARN] HRMS document-type seeding skipped for {company_id}: {e}")


def _clean_type_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Document type name is required.")
    if len(cleaned) > 120:
        raise HTTPException(
            status_code=422, detail="Document type name must be 120 characters or fewer.")
    return cleaned


async def create_document_type(actor: dict, company_id: str, payload: dict) -> dict:
    import re
    name = _clean_type_name(payload.get("name"))
    coll = get_collection(COLL_DOCUMENT_TYPES)
    # Case-insensitive check, because the unique index is case-SENSITIVE and 'PAN' / 'Pan'
    # would otherwise become two types. Same guard hrms_masters_service applies.
    if await coll.find_one({"company_id": str(company_id),
                            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(status_code=409, detail=f"Document type '{name}' already exists.")

    applies_to = (payload.get("applies_to") or "both").strip().lower()
    if applies_to not in APPLIES_TO_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"applies_to must be one of: {', '.join(sorted(APPLIES_TO_VALUES))}.")

    doc = {
        "company_id": str(company_id),
        "name": name,
        "code": clean_text(payload.get("code"), limit=40),
        "category": getattr(payload.get("category"), "value",
                            payload.get("category")) or DocumentCategory.OTHER.value,
        "applies_to": applies_to,
        "mandatory": bool(payload.get("mandatory")),
        "expires": bool(payload.get("expires")),
        # ── Phase INT-2, SOP §11 ── defaults FALSE on a hand-created type: a document HR
        # adds should never silently start blocking probation confirmations.
        "statutory_required": bool(payload.get("statutory_required")),
        "active": bool(payload.get("active", True)),
        "seeded": False,
        "created_at": datetime.now(timezone.utc),
        "created_by": str(actor.get("_id") or ""),
    }
    try:
        result = await coll.insert_one(dict(doc))
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(
                status_code=409, detail=f"Document type '{name}' already exists.")
        raise
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_DOCTYPE_CREATED, ENTITY_DOCUMENT_TYPE,
                str(result.inserted_id), name, company_id)
    return _type_out(doc)


async def update_document_type(actor: dict, company_id: str, type_id: str,
                               payload: dict) -> dict:
    import re
    coll = get_collection(COLL_DOCUMENT_TYPES)
    oid = _oid(type_id, "document type")
    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Document type not found.")

    updates = {}
    if payload.get("name") is not None:
        name = _clean_type_name(payload["name"])
        clash = await coll.find_one({
            "company_id": str(company_id), "_id": {"$ne": oid},
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
        if clash:
            raise HTTPException(
                status_code=409, detail=f"Document type '{name}' already exists.")
        updates["name"] = name
    if payload.get("code") is not None:
        updates["code"] = clean_text(payload["code"], limit=40)
    if payload.get("category") is not None:
        updates["category"] = getattr(payload["category"], "value", payload["category"])
    if payload.get("applies_to") is not None:
        applies_to = (payload["applies_to"] or "").strip().lower()
        if applies_to not in APPLIES_TO_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"applies_to must be one of: {', '.join(sorted(APPLIES_TO_VALUES))}.")
        updates["applies_to"] = applies_to
    for flag in ("mandatory", "expires", "active", "statutory_required"):
        if payload.get(flag) is not None:
            updates[flag] = bool(payload[flag])

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"_id": oid}, {"$set": updates})
    # A rename must follow through to the documents that denormalised it, or the register
    # shows a name the master no longer has.
    if "name" in updates:
        await get_collection(COLL_DOCUMENTS).update_many(
            {"company_id": str(company_id), "type_id": str(type_id)},
            {"$set": {"type_name": updates["name"]}})
    await audit(actor, AUDIT_DOCTYPE_UPDATED, ENTITY_DOCUMENT_TYPE, type_id,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    fresh = await coll.find_one({"_id": oid})
    return _type_out(fresh)


async def delete_document_type(actor: dict, company_id: str, type_id: str) -> dict:
    """Delete a type, refusing while documents still reference it.

    Referential integrity is application-enforced here exactly as it is for departments:
    deleting a referenced type would leave documents pointing at nothing. Deactivating is
    the non-destructive alternative and the message says so.
    """
    coll = get_collection(COLL_DOCUMENT_TYPES)
    oid = _oid(type_id, "document type")
    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Document type not found.")

    in_use = await get_collection(COLL_DOCUMENTS).count_documents(
        {"company_id": str(company_id), "type_id": str(type_id)})
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(f"'{current.get('name')}' is used by {in_use} document(s). Set it "
                    f"inactive instead of deleting, so the existing records stay readable."))

    await coll.delete_one({"_id": oid})
    await audit(actor, AUDIT_DOCTYPE_DELETED, ENTITY_DOCUMENT_TYPE, type_id,
                current.get("name"), company_id)
    return {"deleted": True, "id": type_id, "name": current.get("name")}


# =============================================================
# Documents
# =============================================================
def effective_status(doc: dict, today: str) -> str:
    """A document's status as it actually is. Pure — computed, never stored.

    Expiry outranks Uploaded/Under Review/Verified, because an expired verified document is
    expired. It does NOT override Rejected: a rejected document that also happens to be past
    its date is still rejected, which is the more actionable answer.
    """
    status = (doc or {}).get("status") or DocumentStatus.PENDING.value
    if status == DocumentStatus.REJECTED.value:
        return status
    expiry = (doc or {}).get("expiry_date")
    if expiry and today and str(expiry) < str(today):
        return DocumentStatus.EXPIRED.value
    return status


def _out(doc: dict, today: str = None) -> dict:
    today = today or _today()
    doc = dict(doc)
    doc.pop("_id", None)
    doc["status"] = effective_status(doc, today)
    doc["source"] = "register"
    doc["read_only"] = False
    versions = doc.get("versions") or []
    doc["version_count"] = len(versions)
    doc["latest_version"] = versions[-1] if versions else None
    return doc


async def _scope_filter(actor: dict, company_id: str) -> dict:
    """MANAGER narrowing for candidate documents, same rule and same fail-closed behaviour
    as hrms_candidate_service._scope_filter."""
    if hrms_role(actor) != HrmsRole.MANAGER:
        return {}
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "created_by": str(actor.get("_id") or "")},
        {"request_no": 1}).to_list(2000)
    return {"request_no": {"$in": [r["request_no"] for r in rows]}}


async def _resolve_owner(company_id: str, owner_type: str, owner_id: str) -> dict:
    """Resolve and VALIDATE the owner, returning {name, request_no}.

    The lookup is part of the query with company_id, not a post-check, so a crafted id from
    another tenant simply finds nothing — the same discipline
    hrms_requisition_service._resolve_master applies to masters.
    """
    owner_type = getattr(owner_type, "value", owner_type)
    if owner_type == DocumentOwnerType.CANDIDATE.value:
        doc = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": owner_id, "company_id": str(company_id)},
            {"candidate_name": 1, "request_no": 1})
        if not doc:
            raise HTTPException(
                status_code=422, detail="That candidate does not exist for this company.")
        return {"name": doc.get("candidate_name"), "request_no": doc.get("request_no")}

    if owner_type == DocumentOwnerType.EMPLOYEE.value:
        doc = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"employee_code": owner_id, "company_id": str(company_id)})
        if not doc:
            raise HTTPException(
                status_code=422, detail="That employee does not exist for this company.")
        return {"name": doc.get("employee_name") or doc.get("full_name") or owner_id,
                "request_no": None}

    raise HTTPException(status_code=422, detail="owner_type must be candidate or employee.")


async def _resolve_type(company_id: str, type_id: str) -> dict:
    doc = await get_collection(COLL_DOCUMENT_TYPES).find_one(
        {"_id": _oid(type_id, "document type"), "company_id": str(company_id)})
    if not doc:
        raise HTTPException(
            status_code=422, detail="That document type does not exist for this company.")
    return doc


def _validate_dates(payload: dict) -> dict:
    out = {}
    for field, label in (("issue_date", "Issue date"), ("expiry_date", "Expiry date")):
        if field in payload:
            value = payload[field]
            if value and not is_iso_date(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} must be a valid date in YYYY-MM-DD format.")
            out[field] = value or None
    if out.get("issue_date") and out.get("expiry_date") \
            and out["expiry_date"] < out["issue_date"]:
        raise HTTPException(
            status_code=422, detail="The expiry date cannot be before the issue date.")
    return out


async def _store(upload, prefix: str) -> dict:
    """Validate, decode and store one file. Returns the S3 KEY, never a URL.

    Signed URLs expire in an hour, so persisting one would leave dead links in every
    document row. Identical to hrms_posting_service._store_upload — the same helper shape
    rather than a second storage path.
    """
    raw, name, mime = decode_upload(upload, label="Document")
    if not raw:
        raise HTTPException(status_code=422, detail="Attach a file.")

    import io
    from app.services.s3_service import upload_file_to_s3_with_key
    try:
        result = upload_file_to_s3_with_key(io.BytesIO(raw), f"{prefix}_{name}", mime)
    except Exception as e:
        print(f"[WARN] HRMS document upload failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="The document could not be uploaded right now. Please try again.")
    return {"file_name": name,
            "s3_key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime, "size_bytes": len(raw)}


async def upload_document(actor: dict, company_id: str, payload: dict) -> dict:
    """Create a document, or add a version to an existing one.

    One entry point for both, because from the operator's side they are the same act —
    "here is the paperwork" — and making the client decide which it is invites the case
    where a corrected scan becomes a second, competing document row.
    """
    doc_no = (payload.get("doc_no") or "").strip()
    if doc_no:
        return await _add_version(actor, company_id, doc_no, payload)

    owner_type = getattr(payload.get("owner_type"), "value", payload.get("owner_type"))
    owner_id = (payload.get("owner_id") or "").strip()
    if not owner_id:
        raise HTTPException(status_code=422, detail="Select whose document this is.")

    owner = await _resolve_owner(company_id, owner_type, owner_id)
    dtype = await _resolve_type(company_id, payload.get("type_id"))
    dates = _validate_dates(payload)

    stored = await _store(payload.get("file"), "hrmsdoc")
    now = datetime.now(timezone.utc)
    year = now.year
    new_no = await next_business_id("document", str(company_id), year)

    doc = {
        "doc_no": new_no,
        "company_id": str(company_id),
        "owner_type": owner_type,
        "owner_id": owner_id,
        "owner_name": owner["name"],
        # Denormalised so the MANAGER row-scope narrowing works on this collection without
        # a join on every read.
        "request_no": owner["request_no"],
        "type_id": str(payload.get("type_id")),
        "type_name": dtype.get("name"),
        "category": dtype.get("category"),
        "status": DocumentStatus.UPLOADED.value,
        "current_version": 1,
        "versions": [{
            "version": 1, **stored,
            "uploaded_by": str(actor.get("_id") or ""),
            "uploaded_by_name": _actor_name(actor),
            "uploaded_at": now,
            "source": "hr",
        }],
        "issue_date": dates.get("issue_date"),
        "expiry_date": dates.get("expiry_date"),
        "verified_by": None, "verified_at": None,
        "remarks": clean_text(payload.get("remarks"), limit=2000),
        "created_at": now,
        "created_by": str(actor.get("_id") or ""),
        "updated_at": now,
    }
    await get_collection(COLL_DOCUMENTS).insert_one(dict(doc))
    await audit(actor, AUDIT_DOCUMENT_UPLOADED, ENTITY_DOCUMENT, new_no,
                f"{dtype.get('name')} for {owner['name']}", company_id)
    return _out(doc)


async def _add_version(actor: dict, company_id: str, doc_no: str, payload: dict) -> dict:
    """Add a version to an existing document.

    Uploading a new version resets the status to Uploaded: a document that was Verified and
    has since been REPLACED is not verified any more, and leaving the old verdict attached
    to a new file would be the register asserting something nobody checked.
    """
    current = await _require_visible(actor, company_id, doc_no)
    versions = list(current.get("versions") or [])
    if len(versions) >= MAX_DOCUMENT_VERSIONS:
        raise HTTPException(
            status_code=409,
            detail=(f"This document already has {MAX_DOCUMENT_VERSIONS} versions, which is "
                    f"the limit. Add it as a new document instead."))

    stored = await _store(payload.get("file"), "hrmsdoc")
    now = datetime.now(timezone.utc)
    next_version = int(current.get("current_version") or len(versions)) + 1
    versions.append({
        "version": next_version, **stored,
        "uploaded_by": str(actor.get("_id") or ""),
        "uploaded_by_name": _actor_name(actor),
        "uploaded_at": now,
        "source": "hr",
    })

    updates = {"versions": versions, "current_version": next_version,
               "status": DocumentStatus.UPLOADED.value,
               "verified_by": None, "verified_at": None, "updated_at": now}
    updates.update(_validate_dates(payload))
    if payload.get("remarks") is not None:
        updates["remarks"] = clean_text(payload["remarks"], limit=2000)

    await get_collection(COLL_DOCUMENTS).update_one(
        {"doc_no": doc_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_DOCUMENT_VERSIONED, ENTITY_DOCUMENT, doc_no,
                f"v{next_version}", company_id)
    return await get_document(actor, company_id, doc_no)


async def _require_visible(actor: dict, company_id: str, doc_no: str) -> dict:
    query = {"doc_no": doc_no, "company_id": str(company_id)}
    scope = await _scope_filter(actor, company_id)
    if scope:
        # A manager's narrowing applies to CANDIDATE documents (which carry a request_no).
        # Employee documents have none, so they are excluded rather than accidentally
        # matched by a `request_no: {$in: [...]}` that a null can never satisfy.
        query.update(scope)
    doc = await get_collection(COLL_DOCUMENTS).find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


async def get_document(actor: dict, company_id: str, doc_no: str) -> dict:
    return _out(await _require_visible(actor, company_id, doc_no))


async def list_documents(actor: dict, company_id: str, *, owner_type: str = None,
                         owner_id: str = None, status: str = None, type_id: str = None,
                         search: str = None, expiring_soon: bool = False,
                         limit: int = 200, skip: int = 0) -> dict:
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if owner_type:
        query["owner_type"] = getattr(owner_type, "value", owner_type)
    if owner_id:
        query["owner_id"] = owner_id
    if type_id:
        query["type_id"] = str(type_id)
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"doc_no": {"$regex": safe, "$options": "i"}},
            {"owner_name": {"$regex": safe, "$options": "i"}},
            {"owner_id": {"$regex": safe, "$options": "i"}},
            {"type_name": {"$regex": safe, "$options": "i"}},
        ]

    coll = get_collection(COLL_DOCUMENTS)
    limit = max(1, min(int(limit or 200), 500))
    rows = await coll.find(query).sort("created_at", -1).skip(
        max(0, int(skip or 0))).limit(limit).to_list(limit)

    today = _today()
    out = [_out(r, today) for r in rows]
    # Status is COMPUTED, so it is filtered after projection — a Mongo filter on the stored
    # value would miss every document that expired without anybody rewriting the row.
    if status:
        out = [r for r in out if r["status"] == status]
    if expiring_soon:
        horizon = (datetime.now(timezone.utc)
                   + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS)).strftime("%Y-%m-%d")
        out = [r for r in out
               if r.get("expiry_date") and today <= str(r["expiry_date"]) <= horizon]

    return {
        "documents": out,
        "total": len(out),
        "limit": limit,
        "skip": skip,
        "stats": {
            "uploaded": sum(1 for r in out if r["status"] == DocumentStatus.UPLOADED.value),
            "under_review": sum(1 for r in out
                                if r["status"] == DocumentStatus.UNDER_REVIEW.value),
            "verified": sum(1 for r in out if r["status"] == DocumentStatus.VERIFIED.value),
            "rejected": sum(1 for r in out if r["status"] == DocumentStatus.REJECTED.value),
            "expired": sum(1 for r in out if r["status"] == DocumentStatus.EXPIRED.value),
        },
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
    }


async def update_document(actor: dict, company_id: str, doc_no: str, payload: dict) -> dict:
    """Metadata only. The FILE is immutable — see the module docstring."""
    await _require_visible(actor, company_id, doc_no)
    updates = _validate_dates(payload)
    if payload.get("remarks") is not None:
        updates["remarks"] = clean_text(payload["remarks"], limit=2000)
    if payload.get("type_id") is not None:
        dtype = await _resolve_type(company_id, payload["type_id"])
        updates["type_id"] = str(payload["type_id"])
        updates["type_name"] = dtype.get("name")
        updates["category"] = dtype.get("category")

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_DOCUMENTS).update_one(
        {"doc_no": doc_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_DOCUMENT_UPDATED, ENTITY_DOCUMENT, doc_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_document(actor, company_id, doc_no)


async def set_status(actor: dict, company_id: str, doc_no: str, payload: dict) -> dict:
    """Verify, reject, or move a document to Under Review.

    Rejecting REQUIRES remarks — the same rule REQ_TRANSITIONS applies to a rejected
    requisition, and for the same reason: a refusal the owner cannot act on is a wall, not
    a decision.

    `Expired` cannot be set by hand. It is derived from `expiry_date`, and letting an
    operator stamp it would create the stale-flag problem the derivation exists to avoid.
    """
    current = await _require_visible(actor, company_id, doc_no)
    status = getattr(payload.get("status"), "value", payload.get("status"))
    if status not in {s.value for s in DocumentStatus}:
        raise HTTPException(status_code=422, detail="Unknown document status.")
    if status == DocumentStatus.EXPIRED.value:
        raise HTTPException(
            status_code=422,
            detail=("Expiry is derived from the document's expiry date and cannot be set "
                    "by hand. Edit the expiry date instead."))

    remarks = clean_text(payload.get("remarks"), limit=2000)
    if status in {s.value for s in DOCUMENT_STATUSES_REQUIRING_REMARKS} and not remarks:
        raise HTTPException(
            status_code=422,
            detail="A reason is required when rejecting a document, so it can be corrected.")

    now = datetime.now(timezone.utc)
    updates = {"status": status, "updated_at": now}
    if remarks is not None:
        updates["remarks"] = remarks
    if status == DocumentStatus.VERIFIED.value:
        updates.update({"verified_by": str(actor.get("_id") or ""),
                        "verified_by_name": _actor_name(actor), "verified_at": now})
    else:
        # Moving off Verified clears the verification, so the record never claims a document
        # was checked by somebody who has since been overruled.
        updates.update({"verified_by": None, "verified_by_name": None, "verified_at": None})

    await get_collection(COLL_DOCUMENTS).update_one(
        {"doc_no": doc_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_DOCUMENT_STATUS, ENTITY_DOCUMENT, doc_no,
                f"{current.get('status')} -> {status}"
                + (f": {remarks}" if remarks else ""), company_id)
    return await get_document(actor, company_id, doc_no)


async def delete_document(actor: dict, company_id: str, doc_no: str) -> dict:
    """Remove a document row.

    The S3 objects are deliberately LEFT in place. A delete here is a register correction
    ("this was filed against the wrong person"), and destroying the underlying scan of
    somebody's PAN card on a mis-click is not recoverable. Storage cleanup is an operational
    task with its own retention policy, not a side effect of a UI button.
    """
    current = await _require_visible(actor, company_id, doc_no)
    if current.get("status") == DocumentStatus.VERIFIED.value:
        raise HTTPException(
            status_code=409,
            detail=("A verified document is part of the compliance record. Reject it with a "
                    "reason instead of deleting it."))
    await get_collection(COLL_DOCUMENTS).delete_one(
        {"doc_no": doc_no, "company_id": str(company_id)})
    await audit(actor, AUDIT_DOCUMENT_DELETED, ENTITY_DOCUMENT, doc_no,
                f"{current.get('type_name')} for {current.get('owner_name')}", company_id)
    return {"deleted": True, "doc_no": doc_no}


async def signed_url(actor: dict, company_id: str, doc_no: str,
                     version: int = None) -> dict:
    """A short-lived download URL, minted on demand.

    Never stored: a signed URL expires, and a persisted one is a dead link waiting to
    happen. Same rule the candidate resume/photo attachments follow.
    """
    doc = await _require_visible(actor, company_id, doc_no)
    versions = doc.get("versions") or []
    if not versions:
        raise HTTPException(status_code=404, detail="This document has no file attached.")

    target = versions[-1]
    if version is not None:
        matches = [v for v in versions if int(v.get("version") or 0) == int(version)]
        if not matches:
            raise HTTPException(status_code=404, detail="That version does not exist.")
        target = matches[0]

    key = target.get("s3_key")
    if not key:
        raise HTTPException(status_code=404, detail="This document has no stored file.")

    from app.services.s3_service import get_signed_url
    try:
        url = get_signed_url(key, expires_in=300)          # 5 minutes: long enough to open
    except Exception as e:
        print(f"[WARN] HRMS signed URL failed ({doc_no}): {e}")
        raise HTTPException(
            status_code=503, detail="The document could not be retrieved right now.")
    return {"url": url, "file_name": target.get("file_name"),
            "version": target.get("version"), "expires_in": 300}


# =============================================================
# Checklist + the read-only view over existing attachments
# =============================================================
async def checklist(actor: dict, company_id: str, owner_type: str, owner_id: str) -> dict:
    """Every applicable document type for this owner, with its status or `Pending`.

    This is the question the module exists to answer: "what have we still not got from this
    person". A type with no document is Pending — an absence, stated, rather than a row that
    simply is not there.
    """
    owner_type = getattr(owner_type, "value", owner_type)
    owner = await _resolve_owner(company_id, owner_type, owner_id)
    types = await list_document_types(company_id, applies_to=owner_type)

    rows = await get_collection(COLL_DOCUMENTS).find(
        {"company_id": str(company_id), "owner_type": owner_type,
         "owner_id": owner_id}).to_list(500)
    today = _today()
    by_type = {str(r.get("type_id")): r for r in rows}

    items, missing_mandatory = [], 0
    for t in types:
        held = by_type.get(t["id"])
        status = effective_status(held, today) if held else DocumentStatus.PENDING.value
        if t.get("mandatory") and status not in (DocumentStatus.VERIFIED.value,
                                                 DocumentStatus.UPLOADED.value,
                                                 DocumentStatus.UNDER_REVIEW.value):
            missing_mandatory += 1
        items.append({
            "type_id": t["id"], "type_name": t["name"], "category": t.get("category"),
            "mandatory": bool(t.get("mandatory")), "expires": bool(t.get("expires")),
            "status": status,
            "doc_no": (held or {}).get("doc_no"),
            "expiry_date": (held or {}).get("expiry_date"),
            "current_version": (held or {}).get("current_version"),
        })

    return {
        "owner_type": owner_type, "owner_id": owner_id, "owner_name": owner["name"],
        "items": items,
        "total": len(items),
        "mandatory_total": sum(1 for i in items if i["mandatory"]),
        "mandatory_outstanding": missing_mandatory,
        "linked": await list_linked(company_id, owner_type, owner_id),
    }


async def list_linked(company_id: str, owner_type: str, owner_id: str) -> list:
    """Files that already live on OTHER records, projected into the register's view shape.

    READ-ONLY and never copied — see the module docstring. A candidate's resume stays the
    candidate's resume; this makes it visible from the Document Center so a recruiter does
    not have to remember which screen a file was attached on.
    """
    owner_type = getattr(owner_type, "value", owner_type)
    out = []

    def row(name, s3_key, type_name, uploaded_at, origin):
        return {"doc_no": None, "type_name": type_name, "owner_id": owner_id,
                "owner_type": owner_type, "status": DocumentStatus.UPLOADED.value,
                "file_name": name, "s3_key": s3_key, "uploaded_at": uploaded_at,
                "source": "linked", "read_only": True, "origin": origin}

    if owner_type == DocumentOwnerType.CANDIDATE.value:
        cand = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": owner_id, "company_id": str(company_id)})
        if cand:
            applied = cand.get("applied_at") or cand.get("created_at")
            if cand.get("resume"):
                out.append(row(cand["resume"].get("name"), cand["resume"].get("key"),
                               "Resume", applied, "application"))
            if cand.get("photo"):
                out.append(row(cand["photo"].get("name"), cand["photo"].get("key"),
                               "Photograph", applied, "application"))
            for cert in cand.get("certificates") or []:
                out.append(row(cert.get("name"), cert.get("key"),
                               "Certificate", applied, "application"))

        onb = await get_collection(COLL_ONBOARDING).find_one(
            {"uk": owner_id, "company_id": str(company_id)})
        for d in (onb or {}).get("documents") or []:
            out.append(row(d.get("name"), d.get("key"), "KYC document",
                           d.get("uploaded_at") or (onb or {}).get("created_at"),
                           "onboarding"))

    return out


async def file_system_document(actor, company_id: str, *, owner_type: str, owner_id: str,
                               owner_name: str, type_name: str, reference: str,
                               request_no: str = None, verified: bool = False) -> None:
    """File a document the SYSTEM generated (currently: the appointment letter).

    Idempotent on (owner, type, reference), so sending a letter and then acknowledging it
    updates one row rather than filing two. There is no S3 object: the letter is rendered
    from its own record on demand, and minting a duplicate PDF would be a second copy free
    to drift from the letter the candidate actually read.

    Never raises — the caller is completing a business action and must not be rolled back
    by a bookkeeping write.
    """
    coll = get_collection(COLL_DOCUMENTS)
    now = datetime.now(timezone.utc)

    dtype = await get_collection(COLL_DOCUMENT_TYPES).find_one(
        {"company_id": str(company_id), "name": type_name})
    if not dtype:
        # The types are seeded on first read; if this company has never opened the Document
        # Center the type may not exist yet, so create just this one rather than seeding
        # the whole default set behind the operator's back.
        result = await get_collection(COLL_DOCUMENT_TYPES).insert_one({
            "company_id": str(company_id), "name": type_name,
            "category": DocumentCategory.COMPANY_ISSUED.value,
            "applies_to": "candidate", "mandatory": False, "expires": False,
            "active": True, "seeded": True, "created_at": now})
        dtype = {"_id": result.inserted_id, "name": type_name,
                 "category": DocumentCategory.COMPANY_ISSUED.value}

    status = (DocumentStatus.VERIFIED.value if verified else DocumentStatus.UPLOADED.value)
    existing = await coll.find_one({
        "company_id": str(company_id), "owner_type": owner_type, "owner_id": owner_id,
        "type_id": str(dtype["_id"]), "reference": reference})

    if existing:
        updates = {"status": status, "updated_at": now}
        if verified:
            updates.update({"verified_at": now, "verified_by_name": _actor_name(actor)})
        await coll.update_one({"_id": existing["_id"]}, {"$set": updates})
        return

    doc_no = await next_business_id("document", str(company_id), now.year)
    await coll.insert_one({
        "doc_no": doc_no,
        "company_id": str(company_id),
        "owner_type": owner_type,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "request_no": request_no,
        "type_id": str(dtype["_id"]),
        "type_name": dtype.get("name"),
        "category": dtype.get("category"),
        "status": status,
        "reference": reference,
        "current_version": 1,
        "versions": [{"version": 1, "file_name": f"{reference}.pdf", "s3_key": None,
                      "mime_type": "application/pdf", "size_bytes": 0,
                      "uploaded_by": None, "uploaded_by_name": "system",
                      "uploaded_at": now, "source": "system"}],
        "issue_date": now.strftime("%Y-%m-%d"),
        "expiry_date": None,
        "verified_by": None,
        "verified_by_name": _actor_name(actor) if verified else None,
        "verified_at": now if verified else None,
        "remarks": None,
        "created_at": now,
        "updated_at": now,
    })
    await audit(actor, AUDIT_DOCUMENT_UPLOADED, ENTITY_DOCUMENT, doc_no,
                f"{type_name} filed automatically ({reference})", company_id)
