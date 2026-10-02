"""HRMS ▸ employee master.

Closes the single biggest gap in both analysis documents: "Employee Management -- Not found
in current HRMS" (FRONTEND_ANALYSIS §2, BACKEND_ANALYSIS §2). Every later phase depends on
this -- onboarding creates employees here, leave and payroll compute over them, reporting
aggregates them.

── The central design decision ───────────────────────────────────────────────────
An employee is a **composition**, not a copy:

    EmployeeView  =  user document (staff/learners)      -- identity, owned by the ERP
                  +  hrms_employee_profiles document      -- HR data, owned by HRMS
                  +  resolved master names                -- department / designation
                  +  resolved reporting manager

HRMS never writes to `staff` or `learners`. Identity has exactly one owner, so a rename or
an email change is instantly correct everywhere with no sync step.

The source did the opposite: it kept its own `users` table and joined every HR-ops record on
`users.name`, so renaming a person silently orphaned their leave history, balance ledger and
permission grants (BACKEND_ANALYSIS §4.4, Risk #4). Keying on the immutable ObjectId removes
that failure mode entirely rather than mitigating it.

── Row scoping ───────────────────────────────────────────────────────────────────
Reads are broad but scoped, writes are narrow:
  ADMIN / INTERNAL  every company (a specific one when asked)
  MD / HR           their own company
  MANAGER (HOD)     their own department + their direct reports
  EMPLOYEE          themselves only (via the self route; not a capability, so it cannot
                    be revoked by a permission edit)
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AADHAAR_RE, AUDIT_EMPLOYEE_CREATED, AUDIT_EMPLOYEE_UPDATED, AUDIT_SALARY_CHANGED,
    AUDIT_EMPLOYEE_LINKED, COLL_DEPARTMENTS, COLL_DESIGNATIONS,
    COLL_EMPLOYEE_PROFILES, ENTITY_EMPLOYEE,
    IFSC_RE, PAN_RE, UAN_RE, Cap, EmploymentStatus, EmploymentType, HrmsRole, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, hrms_role, is_internal_user

USER_COLLECTIONS = ("learners", "staff")

# Identity fields surfaced on an EmployeeView. Everything else on the user doc (password,
# permissions, session_type, ...) is deliberately NOT exposed by the HRMS directory.
_USER_PROJECTION = {
    "first_name": 1, "last_name": 1, "full_name": 1, "email": 1, "mobile": 1,
    "role": 1, "governance_role": 1, "company_id": 1, "is_active": 1,
    "reporting_manager": 1, "designation": 1, "department": 1, "joining_date": 1,
    "emergency_mobile": 1,
}


def _oid(value: str, label: str = "user") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
            or user.get("email")
            or "Unknown")


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────
async def _validate_profile(payload: dict, company_id: str, *, partial: bool) -> dict:
    """Validate and normalise a profile payload. Raises 422 with a field-specific message.

    Every rule the source enforced only in the browser is enforced here (BACKEND_ANALYSIS
    §8 lists PAN-or-Aadhaar and duplicate detection as client-only). Identity documents are
    uppercased before validation so a lowercase PAN is accepted rather than rejected on a
    technicality.
    """
    out = {}

    # -- Salary --
    if "base_salary" in payload and payload["base_salary"] is not None:
        try:
            salary = float(payload["base_salary"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Base salary must be a number.")
        if salary < 0:
            raise HTTPException(status_code=422, detail="Base salary cannot be negative.")
        if salary > 100_000_000:
            raise HTTPException(status_code=422, detail="Base salary is implausibly large.")
        out["base_salary"] = salary

    # -- Dates --
    for field, label in (("date_of_birth", "Date of birth"),
                         ("joined_on", "Joining date"),
                         ("resigned_on", "Resignation date")):
        if field in payload and payload[field]:
            if not is_iso_date(payload[field]):
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} must be a valid date in YYYY-MM-DD format.")
            out[field] = payload[field]
        elif field in payload:
            out[field] = None

    # -- Identity documents (uppercased, then format-checked) --
    for field, pattern, label, hint in (
        ("pan", PAN_RE, "PAN", "e.g. ABCDE1234F"),
        ("aadhaar", AADHAAR_RE, "Aadhaar", "12 digits"),
        ("uan", UAN_RE, "UAN", "12 digits"),
        ("bank_ifsc", IFSC_RE, "IFSC code", "e.g. HDFC0001234"),
    ):
        if field in payload:
            raw = (payload[field] or "").strip().upper()
            if not raw:
                out[field] = None
                continue
            if not pattern.match(raw):
                raise HTTPException(status_code=422, detail=f"{label} is not valid ({hint}).")
            out[field] = raw

    if "bank_account" in payload:
        acct = (payload["bank_account"] or "").strip()
        if acct and not acct.isdigit():
            raise HTTPException(status_code=422, detail="Bank account number must be digits only.")
        if acct and not (6 <= len(acct) <= 20):
            raise HTTPException(status_code=422, detail="Bank account number must be 6-20 digits.")
        out["bank_account"] = acct or None

    # -- Enums (Pydantic already coerced these; str() normalises Enum -> value) --
    for field in ("employment_status", "employment_type", "gender"):
        if field in payload and payload[field] is not None:
            out[field] = getattr(payload[field], "value", payload[field])

    # -- Free text --
    for field in ("pf_number", "esi_number", "bank_name", "blood_group", "address",
                  "emergency_contact_name", "emergency_contact_phone",
                  "emergency_contact_relation", "employee_code"):
        if field in payload:
            out[field] = (payload[field] or "").strip() or None

    # -- Master references must exist AND belong to this company --
    for field, coll_name, label in (("department_id", COLL_DEPARTMENTS, "Department"),
                                    ("designation_id", COLL_DESIGNATIONS, "Designation")):
        if field in payload:
            raw = payload[field]
            if not raw:
                out[field] = None
                continue
            found = await get_collection(coll_name).find_one(
                {"_id": _oid(raw, label.lower()), "company_id": str(company_id)}
            )
            if not found:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} does not exist for this company.")
            out[field] = str(raw)

    return out


def _check_date_order(joined_on, resigned_on) -> None:
    """Joining must not be after resignation.

    ISO date strings compare correctly lexically, which is why HRMS keeps dates as strings
    end to end -- no Date object, so no server-timezone drift.
    """
    if joined_on and resigned_on and joined_on > resigned_on:
        raise HTTPException(
            status_code=422,
            detail="Joining date cannot be after the resignation date.")


# ─────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────
async def _find_user(user_id: str) -> tuple:
    """Locate a user in either identity collection. Returns (doc, collection) or (None, None)."""
    oid = _oid(user_id)
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid}, _USER_PROJECTION)
        if doc:
            return doc, coll
    return None, None


def _compose(user: Optional[dict], profile: Optional[dict], *, departments: dict,
             designations: dict, managers: dict, include_salary: bool) -> dict:
    """Merge a user document and its HR profile into one EmployeeView.

    `include_salary` is passed in rather than read from a global so the caller decides once,
    from the capability check, and the redaction cannot be forgotten at a call site.

    `user` may be None. Phase 9 creates an employee record at onboarding, BEFORE the person
    has a login — those rows carry an `identity_snapshot` taken from the candidate and are
    flagged `pending_user_link`. Identity is still single-sourced: once a real account is
    linked, the user document wins and the snapshot is ignored.
    """
    profile = profile or {}
    snapshot = profile.get("identity_snapshot") or {}
    view = {
        "user_id": str(user["_id"]) if user else None,
        "name": _display_name(user) if user else (snapshot.get("name") or "Unknown"),
        "email": user.get("email") if user else snapshot.get("email"),
        "mobile": user.get("mobile") if user else snapshot.get("mobile"),
        "role": user.get("role") if user else None,
        "governance_role": user.get("governance_role") if user else None,
        "company_id": str((user or profile).get("company_id") or ""),
        "is_active": user.get("is_active", True) if user else True,
        "has_profile": bool(profile),
        # True while the employee exists but has no login yet. The directory shows this
        # rather than pretending the record is complete.
        "pending_user_link": bool(profile) and not user,
        "source_uk": profile.get("source_uk"),

        "employee_code": profile.get("employee_code"),
        "employment_status": profile.get("employment_status"),
        "employment_type": profile.get("employment_type"),
        "gender": profile.get("gender"),
        "date_of_birth": profile.get("date_of_birth"),
        # Fall back to the legacy `users.joining_date` so an employee without an HR profile
        # still shows the date the ERP already knows.
        "joined_on": profile.get("joined_on") or (user or {}).get("joining_date"),
        "resigned_on": profile.get("resigned_on"),

        "department_id": profile.get("department_id"),
        "designation_id": profile.get("designation_id"),
        "department": departments.get(profile.get("department_id")),
        "designation": designations.get(profile.get("designation_id")),
        # The raw directory strings, kept visible so nothing is lost while HR migrates onto
        # the masters and so a mismatch is obvious rather than silent.
        "legacy_department": (user or {}).get("department"),
        "legacy_designation": (user or {}).get("designation"),

        "reporting_manager_id": (user or {}).get("reporting_manager"),
        "reporting_manager": managers.get(str((user or {}).get("reporting_manager") or "")),

        "pan": profile.get("pan"),
        "aadhaar": profile.get("aadhaar"),
        "uan": profile.get("uan"),
        "pf_number": profile.get("pf_number"),
        "esi_number": profile.get("esi_number"),
        "bank_name": profile.get("bank_name"),
        "bank_account": profile.get("bank_account"),
        "bank_ifsc": profile.get("bank_ifsc"),
        "blood_group": profile.get("blood_group"),
        "address": profile.get("address"),
        "emergency_contact_name": profile.get("emergency_contact_name"),
        "emergency_contact_phone": (profile.get("emergency_contact_phone")
                                    or (user or {}).get("emergency_mobile")),
        "emergency_contact_relation": profile.get("emergency_contact_relation"),
    }
    # Salary is OMITTED entirely rather than nulled, so a client cannot confuse "you may not
    # see this" with "this employee has no salary set".
    if include_salary:
        view["base_salary"] = profile.get("base_salary")
    return view


async def _identity_source(company_id: str) -> tuple:
    """Which identity collection holds this tenant's people. See hrms_access for the rule.

    The directory does not simply stamp `company_id` onto the staff records instead: that
    field being null is what the rest of the ERP relies on to tell an operator apart from a
    company's own user (see `list_users` in routes/user.py, and org_tools' company filter).
    Resolving it per tenant keeps that boundary where it is.
    """
    from app.utils.hrms_access import tenant_identity_source
    return await tenant_identity_source(company_id)


async def _resolve_lookups(company_id: str, users: list) -> tuple:
    """Batch-resolve department names, designation names and manager names.

    One query per lookup regardless of result size -- the alternative (resolving per row)
    is the classic N+1 that would make a 500-employee directory unusable.
    """
    departments = {
        str(d["_id"]): d.get("name")
        for d in await get_collection(COLL_DEPARTMENTS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
    }
    designations = {
        str(d["_id"]): d.get("name")
        for d in await get_collection(COLL_DESIGNATIONS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
    }

    manager_ids = {str(u.get("reporting_manager")) for u in users if u.get("reporting_manager")}
    managers = {}
    if manager_ids:
        oids = []
        for m in manager_ids:
            try:
                oids.append(ObjectId(m))
            except (InvalidId, TypeError):
                continue
        if oids:
            for coll in USER_COLLECTIONS:
                for doc in await get_collection(coll).find(
                        {"_id": {"$in": oids}},
                        {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1}).to_list(1000):
                    managers[str(doc["_id"])] = _display_name(doc)
    return departments, designations, managers


# ─────────────────────────────────────────────────────────────
# Row scoping
# ─────────────────────────────────────────────────────────────
async def _manager_scope(actor: dict, company_id: str) -> dict:
    """Extra user-query clause restricting a MANAGER to their own corner of the directory.

    A hiring manager sees their direct reports plus anyone in their department. If they have
    no HR profile (so no department), it degrades to direct reports only -- never to
    "everyone", because a scoping gap must fail closed.
    """
    actor_id = str(actor.get("_id") or "")
    clauses = [{"reporting_manager": actor_id}, {"_id": _oid(actor_id)}]

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one({"user_id": actor_id})
    dept_id = (profile or {}).get("department_id")
    if dept_id:
        peers = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id), "department_id": dept_id}, {"user_id": 1}
        ).to_list(2000)
        peer_oids = []
        for p in peers:
            try:
                peer_oids.append(ObjectId(p["user_id"]))
            except (InvalidId, TypeError, KeyError):
                continue
        if peer_oids:
            clauses.append({"_id": {"$in": peer_oids}})
    return {"$or": clauses}


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
async def list_employees(actor: dict, company_id: str, *, search: str = None,
                         department_id: str = None, designation_id: str = None,
                         status: str = None, include_inactive: bool = False,
                         limit: int = 200, skip: int = 0) -> dict:
    """The employee directory, scoped to what `actor` may see."""
    if not company_id:
        raise HTTPException(
            status_code=400,
            detail="A company must be selected to list employees.")

    source, query = await _identity_source(company_id)
    if not include_inactive:
        query["is_active"] = {"$ne": False}

    if search:
        safe = _escape_regex(search.strip())
        query["$and"] = [{"$or": [
            {"full_name": {"$regex": safe, "$options": "i"}},
            {"first_name": {"$regex": safe, "$options": "i"}},
            {"last_name": {"$regex": safe, "$options": "i"}},
            {"email": {"$regex": safe, "$options": "i"}},
            {"mobile": {"$regex": safe, "$options": "i"}},
        ]}]

    if hrms_role(actor) == HrmsRole.MANAGER:
        scope = await _manager_scope(actor, company_id)
        query.setdefault("$and", []).append(scope)

    # Profile-driven filters resolve to a user-id set first, because the filterable fields
    # live on the profile while the base query runs over the user collection.
    profile_filter = {"company_id": str(company_id)}
    if department_id:
        profile_filter["department_id"] = department_id
    if designation_id:
        profile_filter["designation_id"] = designation_id
    if status:
        profile_filter["employment_status"] = status
    if len(profile_filter) > 1:
        matched = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            profile_filter, {"user_id": 1}).to_list(5000)
        oids = []
        for m in matched:
            try:
                oids.append(ObjectId(m["user_id"]))
            except (InvalidId, TypeError, KeyError):
                continue
        if not oids:
            return {"employees": [], "total": 0, "limit": limit, "skip": skip}
        query["_id"] = {"$in": oids}

    users_coll = get_collection(source)
    total = await users_coll.count_documents(query)
    # The full matching id set (unpaginated), so the orphan check below isn't fooled by a
    # profile whose linked user simply falls on a different page.
    matched_user_ids = {
        str(d["_id"]) for d in await users_coll.find(query, {"_id": 1}).to_list(20000)
    }
    limit = max(1, min(int(limit or 200), 500))
    users = await users_coll.find(query, _USER_PROJECTION).sort(
        "full_name", 1).skip(max(0, int(skip or 0))).limit(limit).to_list(limit)

    profiles = {}
    if users:
        ids = [str(u["_id"]) for u in users]
        for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
                {"user_id": {"$in": ids}}).to_list(len(ids)):
            profiles[p["user_id"]] = p

    departments, designations, managers = await _resolve_lookups(company_id, users)
    include_salary = can(actor, Cap.EMPLOYEE_SALARY_READ)

    rows = [
        _compose(u, profiles.get(str(u["_id"])), departments=departments,
                 designations=designations, managers=managers,
                 include_salary=include_salary)
        for u in users
    ]

    # Employees created by onboarding have no login yet, so they are absent from the user
    # query above. Fetch them separately rather than leaving a new hire invisible in the
    # directory the moment their Employee ID is issued.
    unlinked = await _unlinked_profiles(
        company_id, search=search, department_id=department_id,
        designation_id=designation_id, status=status)
    for profile in unlinked:
        rows.append(_compose(None, profile, departments=departments,
                             designations=designations, managers=managers,
                             include_salary=include_salary))

    # A profile can carry a `user_id` that no longer resolves to a learner of THIS company
    # -- the account was moved to another company, or the profile was linked against the
    # wrong one to begin with. `_unlinked_profiles` correctly skips it (its `user_id` field
    # IS set), and the query above never finds it either, so without this it vanishes from
    # the directory entirely instead of surfacing the inconsistency HR needs to fix.
    orphaned = await _orphaned_linked_profiles(
        company_id, matched_user_ids, search=search, department_id=department_id,
        designation_id=designation_id, status=status)
    for profile in orphaned:
        row = _compose(None, profile, departments=departments, designations=designations,
                       managers=managers, include_salary=include_salary)
        row["pending_user_link"] = False
        row["link_broken"] = True
        rows.append(row)

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    return {
        "employees": rows,
        "total": total + len(unlinked) + len(orphaned),
        "limit": limit,
        "skip": skip,
        "salary_visible": include_salary,
        "pending_links": sum(1 for r in rows if r.get("pending_user_link")),
        "broken_links": sum(1 for r in rows if r.get("link_broken")),
    }


async def _unlinked_profiles(company_id: str, *, search: str = None,
                             department_id: str = None, designation_id: str = None,
                             status: str = None) -> list:
    """Employee profiles that exist without a login account.

    Matched on the ABSENCE of `user_id` (not a null value) so they line up exactly with the
    sparse unique index -- see the index comment in models/hrms.py.
    """
    query = {"company_id": str(company_id), "user_id": {"$exists": False}}
    if department_id:
        query["department_id"] = department_id
    if designation_id:
        query["designation_id"] = designation_id
    if status:
        query["employment_status"] = status

    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(query).to_list(500)
    if search:
        needle = search.strip().lower()
        rows = [
            r for r in rows
            if needle in ((r.get("identity_snapshot") or {}).get("name") or "").lower()
            or needle in ((r.get("identity_snapshot") or {}).get("email") or "").lower()
            or needle in (r.get("employee_code") or "").lower()
        ]
    return rows


async def _orphaned_linked_profiles(company_id: str, matched_user_ids: set, *,
                                    search: str = None, department_id: str = None,
                                    designation_id: str = None, status: str = None) -> list:
    """Employee profiles whose `user_id` no longer resolves to a learner of THIS company.

    `_unlinked_profiles` deliberately matches on the ABSENCE of `user_id`; a profile that
    HAS one but whose target has since moved to another company (or was linked against the
    wrong one) falls through both that query and the main user-driven one, and used to
    disappear from the directory rather than surface as the data problem it is.

    Filtered exactly like `_unlinked_profiles`, so a search or filter narrows this set too
    rather than always injecting every orphan regardless of what the caller asked for.
    """
    query = {"company_id": str(company_id), "user_id": {"$exists": True, "$nin": [None, ""]}}
    if department_id:
        query["department_id"] = department_id
    if designation_id:
        query["designation_id"] = designation_id
    if status:
        query["employment_status"] = status

    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(query).to_list(2000)
    rows = [r for r in rows if r.get("user_id") not in matched_user_ids]
    if search:
        needle = search.strip().lower()
        rows = [
            r for r in rows
            if needle in ((r.get("identity_snapshot") or {}).get("name") or "").lower()
            or needle in ((r.get("identity_snapshot") or {}).get("email") or "").lower()
            or needle in (r.get("employee_code") or "").lower()
        ]
    return rows


async def get_employee(actor: dict, user_id: str, *, company_id: str = None,
                       force_salary: bool = None) -> dict:
    """One employee, composed. Raises 404 when the user does not exist or is out of scope.

    Out-of-scope reads deliberately return 404 rather than 403: a 403 would confirm that a
    given id exists in another tenant, which is an information leak in a multi-tenant system.
    """
    user, _coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found.")

    user_company = str(user.get("company_id") or "")
    if not is_internal_user(actor):
        if user_company != str(actor.get("company_id") or ""):
            raise HTTPException(status_code=404, detail="Employee not found.")
    elif company_id:
        # Resolved per tenant rather than by comparing `company_id` directly: Sparsh Magic's
        # own people are `staff` and carry none, so a flat comparison 404s every one of them.
        from app.utils.hrms_access import tenant_member
        if not await tenant_member(company_id, user_id, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Employee not found.")

    is_self = str(actor.get("_id") or "") == str(user_id)
    if not is_self and not can(actor, Cap.EMPLOYEE_READ):
        raise HTTPException(status_code=403, detail="You may only view your own profile.")

    if not is_self and hrms_role(actor) == HrmsRole.MANAGER:
        scope = await _manager_scope(actor, user_company)
        visible = await get_collection("learners").find_one(
            {"$and": [{"_id": _oid(user_id)}, scope]}, {"_id": 1})
        if not visible:
            raise HTTPException(status_code=404, detail="Employee not found.")

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one({"user_id": str(user_id)})
    departments, designations, managers = await _resolve_lookups(user_company, [user])

    # You may always see your own pay; otherwise it takes the capability.
    include_salary = (force_salary if force_salary is not None
                      else (is_self or can(actor, Cap.EMPLOYEE_SALARY_READ)))
    return _compose(user, profile, departments=departments, designations=designations,
                    managers=managers, include_salary=include_salary)


async def get_employee_by_code(actor: dict, company_id: str,
                               employee_code: str) -> Optional[dict]:
    """One employee addressed by EMPLOYEE CODE rather than by login id.

    Needed because an employee created by onboarding has no `user_id` at all until their
    account is linked -- deliberately so, see the onboarding module's own note. Every
    caller that addresses people by ObjectId therefore cannot reach a brand-new joiner,
    which is exactly the person somebody is most likely to open.

    Returns None rather than raising when there is no such code, so a caller can fall back
    to the user-id path without catching.
    """
    if not employee_code:
        return None
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        return None
    if not can(actor, Cap.EMPLOYEE_READ):
        raise HTTPException(status_code=403, detail="You may only view your own profile.")

    user = None
    if profile.get("user_id"):
        user, _coll = await _find_user(profile["user_id"])
    departments, designations, managers = await _resolve_lookups(
        company_id, [user] if user else [])
    return _compose(user, profile, departments=departments, designations=designations,
                    managers=managers,
                    include_salary=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def create_profile(actor: dict, company_id: str, payload: dict) -> dict:
    """Create the HR profile for an existing user."""
    user_id = str(payload.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=422, detail="A user must be selected.")

    user, coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if coll != "learners":
        # HRMS is a client-company module: employees are a company's own people. Guarding
        # this stops a Sparsh staff account being turned into a client's employee record.
        raise HTTPException(
            status_code=422,
            detail="Only company users can be added as employees.")
    if str(user.get("company_id") or "") != str(company_id):
        raise HTTPException(status_code=403, detail="That user belongs to another company.")

    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    if await profiles.find_one({"user_id": user_id}):
        raise HTTPException(status_code=409, detail="This user already has an employee profile.")

    if payload.get("base_salary") is not None and not can(actor, Cap.EMPLOYEE_SALARY_WRITE):
        raise HTTPException(status_code=403, detail="You may not set salary.")

    clean = await _validate_profile(payload, company_id, partial=False)
    _check_date_order(clean.get("joined_on"), clean.get("resigned_on"))

    code = clean.get("employee_code")
    if code:
        if await profiles.find_one({"company_id": str(company_id), "employee_code": code}):
            raise HTTPException(status_code=409, detail=f"Employee code '{code}' is already in use.")
    else:
        code = await next_business_id("employee", str(company_id), datetime.now(timezone.utc).year)

    doc = {
        "user_id": user_id,
        "company_id": str(company_id),
        "employee_code": code,
        "employment_status": clean.get("employment_status", EmploymentStatus.ACTIVE.value),
        "employment_type": clean.get("employment_type"),
        "created_at": datetime.now(timezone.utc),
        "created_by": str(actor.get("_id")) if actor.get("_id") else None,
    }
    for field, value in clean.items():
        doc.setdefault(field, value)
        doc[field] = value

    try:
        await profiles.insert_one(doc)
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(status_code=409, detail="This user already has an employee profile.")
        raise

    await audit(actor, AUDIT_EMPLOYEE_CREATED, ENTITY_EMPLOYEE, user_id,
                f"{_display_name(user)} ({code})", company_id)
    return await get_employee(actor, user_id, company_id=company_id)


async def update_profile(actor: dict, user_id: str, payload: dict, company_id: str) -> dict:
    """Update an employee profile, creating it on first write if absent.

    Upserting keeps the UI simple: HR edits an employee from the directory without caring
    whether a profile row already exists.
    """
    user, coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if str(user.get("company_id") or "") != str(company_id):
        raise HTTPException(status_code=404, detail="Employee not found.")

    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    current = await profiles.find_one({"user_id": str(user_id)}) or {}

    # The gate is on INTENT TO WRITE, not on whether the value differs.
    #
    # A delta check looks equivalent but is not: with no salary stored yet, writing 0
    # compares `0.0 != (None or 0)` -> False, so the capability check would be skipped and a
    # caller without EMPLOYEE_SALARY_WRITE could set a salary. "Writing the same value" is
    # not a meaningful exemption from a permission check either way.
    salary_write_attempted = ("base_salary" in payload and payload["base_salary"] is not None)
    if salary_write_attempted and not can(actor, Cap.EMPLOYEE_SALARY_WRITE):
        raise HTTPException(status_code=403, detail="You may not change salary.")
    # The delta is still needed, but only to decide whether to write a dedicated audit line.
    salary_changing = (salary_write_attempted
                       and float(payload["base_salary"]) != current.get("base_salary"))

    clean = await _validate_profile(payload, company_id, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    _check_date_order(
        clean.get("joined_on", current.get("joined_on")),
        clean.get("resigned_on", current.get("resigned_on")),
    )

    code = clean.get("employee_code")
    if code and code != current.get("employee_code"):
        clash = await profiles.find_one({
            "company_id": str(company_id), "employee_code": code,
            "user_id": {"$ne": str(user_id)},
        })
        if clash:
            raise HTTPException(status_code=409, detail=f"Employee code '{code}' is already in use.")

    clean["updated_at"] = datetime.now(timezone.utc)
    await profiles.update_one(
        {"user_id": str(user_id)},
        {"$set": clean,
         "$setOnInsert": {"user_id": str(user_id), "company_id": str(company_id),
                          "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

    changed = sorted(k for k in clean if k != "updated_at")
    await audit(actor, AUDIT_EMPLOYEE_UPDATED, ENTITY_EMPLOYEE, str(user_id),
                ", ".join(changed), company_id)
    if salary_changing:
        # Pay changes get their own audit line so a payroll dispute can be traced without
        # reading every field-level update row.
        await audit(actor, AUDIT_SALARY_CHANGED, ENTITY_EMPLOYEE, str(user_id),
                    f"{current.get('base_salary')} -> {clean.get('base_salary')}", company_id)

    return await get_employee(actor, user_id, company_id=company_id)


async def get_hierarchy(actor: dict, user_id: str, company_id: str) -> dict:
    """Reporting chain upward + direct reports downward.

    The upward walk is depth-capped and cycle-guarded: `reporting_manager` has no database
    constraint preventing A->B->A, and an unguarded walk would hang the request.
    """
    employee = await get_employee(actor, user_id, company_id=company_id)

    chain, seen, cursor, depth = [], {str(user_id)}, employee.get("reporting_manager_id"), 0
    while cursor and depth < 10:
        cursor = str(cursor)
        if cursor in seen:
            chain.append({"user_id": cursor, "name": "(circular reference)", "circular": True})
            break
        seen.add(cursor)
        manager, _c = await _find_user(cursor)
        if not manager:
            break
        chain.append({
            "user_id": cursor,
            "name": _display_name(manager),
            "email": manager.get("email"),
            "governance_role": manager.get("governance_role"),
        })
        cursor = manager.get("reporting_manager")
        depth += 1

    reports = await get_collection("learners").find(
        {"company_id": str(company_id), "reporting_manager": str(user_id),
         "is_active": {"$ne": False}},
        {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1, "governance_role": 1},
    ).sort("full_name", 1).to_list(500)

    return {
        "employee": {"user_id": employee["user_id"], "name": employee["name"]},
        "manager_chain": chain,
        "direct_reports": [
            {"user_id": str(r["_id"]), "name": _display_name(r), "email": r.get("email"),
             "governance_role": r.get("governance_role")}
            for r in reports
        ],
        "report_count": len(reports),
    }


async def list_linkable_users(actor: dict, company_id: str) -> list:
    """Company users who do NOT yet have an employee profile -- the picker for "Add employee".

    Without this the UI would offer everyone and rely on a 409 to explain the mistake.
    """
    # `.get`, not `[...]`: a profile created by onboarding has no `user_id` key at all, and
    # subscripting one would raise KeyError for every caller of this picker.
    existing = {
        p.get("user_id") for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id)}, {"user_id": 1}).to_list(5000)
    } - {None}
    source, query = await _identity_source(company_id)
    users = await get_collection(source).find(
        {**query, "is_active": {"$ne": False}}, _USER_PROJECTION
    ).sort("full_name", 1).to_list(2000)
    return [
        {"user_id": str(u["_id"]), "name": _display_name(u), "email": u.get("email"),
         "governance_role": u.get("governance_role"), "legacy_department": u.get("department"),
         "legacy_designation": u.get("designation")}
        for u in users if str(u["_id"]) not in existing
    ]


def _escape_regex(value: str) -> str:
    import re
    return re.escape(value)


async def create_from_onboarding(actor: dict, company_id: str, *, employee_code: str,
                                 identity: dict, source_uk: str,
                                 joined_on: str = None, department_id: str = None,
                                 designation_id: str = None, assignment: dict = None,
                                 extra: dict = None) -> dict:
    """Create an employee record for someone who has no login account yet (Phase 9).

    This is the moment recruitment becomes an employee, and it is the link both analysis
    documents said was missing entirely.

    HRMS still does NOT write to `staff`/`learners`. Instead the profile carries an
    `identity_snapshot` and omits `user_id` (the index is sparse), so:
      * the new hire appears in the directory immediately, flagged `pending_user_link`;
      * nothing is duplicated into an identity collection HRMS does not own;
      * `link_user` later attaches the real account, after which the user document is the
        single source of identity and the snapshot is ignored.
    """
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    if await profiles.find_one({"company_id": str(company_id),
                                "employee_code": employee_code}):
        raise HTTPException(
            status_code=409, detail=f"Employee code '{employee_code}' is already in use.")

    now = datetime.now(timezone.utc)
    doc = {
        # `user_id` is deliberately ABSENT, not None -- a null value would still be indexed
        # by the unique index and only one such row could exist.
        "company_id": str(company_id),
        "employee_code": employee_code,
        "identity_snapshot": {
            "name": identity.get("name"),
            "email": identity.get("email"),
            "mobile": identity.get("mobile"),
        },
        "source_uk": source_uk,
        "employment_status": EmploymentStatus.ACTIVE.value,
        "employment_type": EmploymentType.FULL_TIME.value,
        "joined_on": joined_on,
        "department_id": department_id,
        "designation_id": designation_id,
        "created_at": now,
        "created_by": str(actor.get("_id")) if actor and actor.get("_id") else None,
    }
    # §7.5 Stage 6 -- what HR assigned at joining. Applied over the defaults above, so
    # a company that records an employment category or a payroll group gets theirs rather
    # than the fallback, and one that records neither is unaffected.
    for key, value in (assignment or {}).items():
        if value not in (None, ""):
            doc[key] = getattr(value, "value", value)
    for key, value in (extra or {}).items():
        if value is not None:
            doc[key] = value

    await profiles.insert_one(dict(doc))
    await audit(actor, AUDIT_EMPLOYEE_CREATED, ENTITY_EMPLOYEE, employee_code,
                f"{identity.get('name')} created from onboarding ({source_uk})", company_id)
    doc.pop("_id", None)
    return doc


async def link_user(actor: dict, company_id: str, employee_code: str, user_id: str) -> dict:
    """Attach an onboarding-created employee record to a real login account.

    After this the user document is the single source of identity -- the snapshot stays for
    history but is no longer read (see `_compose`).
    """
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    profile = await profiles.find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="Employee record not found.")
    if profile.get("user_id"):
        raise HTTPException(
            status_code=409, detail="This employee is already linked to a user account.")

    user, coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if coll != "learners" or str(user.get("company_id") or "") != str(company_id):
        raise HTTPException(
            status_code=422, detail="The account must belong to a user of this company.")
    if await profiles.find_one({"user_id": str(user_id)}):
        raise HTTPException(
            status_code=409, detail="That user already has an employee profile.")

    await profiles.update_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"$set": {"user_id": str(user_id), "linked_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_EMPLOYEE_LINKED, ENTITY_EMPLOYEE, employee_code,
                f"linked to {_display_name(user)}", company_id)
    return await get_employee(actor, user_id, company_id=company_id)
