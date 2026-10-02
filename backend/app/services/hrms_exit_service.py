"""HRMS > Exit Management (BA/Functional Design v2.2, §7.18, §22.2, §7.21).

Resignation submitted -> notice calculated from status + designation level -> HR/manager
records acceptance, with an approval gate on any waiver (BR-016) -> a Handover Plan and
departmental Clearance/Asset-Return/Access-Clearance tasks run in parallel (§22.2) -> an Exit
Interview is captured -> Finance approves the F&F (BR-021) -> the case closes and the employee
is marked separated.

-- Identity: keyed by employee_code, like probation -----------------------------------------
The same convention hrms_probation_service already uses: a separation is a post-hire
EMPLOYEE fact, addressed by the company's own employee_code rather than the ERP's internal
user id, so a case reads the same way a probation record or a payslip eventually will.

-- One open case at a time, enforced in code rather than a unique index --------------------
A rehired-and-separated-again employee legitimately gets a SECOND separation row, so the
uniqueness a database index would give is the wrong tool; `_assert_no_open_case` checks it
instead, against CLOSED_SEPARATION_STAGES.

-- F&F has no payroll engine behind it -------------------------------------------------------
§7.13 (Payroll Processing) is unbuilt. FnfInput captures the figures a real payroll run would
otherwise supply, entered by hand, so a settlement can still be prepared, reviewed with a real
maker/checker gate, and paid -- it cannot compute LOP, PF or TDS from first principles, because
nothing in this codebase does that yet. Asset/clearance recoveries ARE rolled up automatically
(§22.2 step 196), because those numbers already live in this module's own collections.
"""
from datetime import datetime, timezone
import re
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.utils.hrms_public_guard import clean_text
from app.models.hrms import (
    AUDIT_ACCESS_CLEARANCE_CREATED, AUDIT_ACCESS_CLEARANCE_UPDATED,
    AUDIT_ASSET_RETURN_CREATED, AUDIT_ASSET_RETURN_UPDATED,
    AUDIT_CLEARANCE_ACTIONED, AUDIT_CLEARANCE_CREATED,
    AUDIT_EXIT_INTERVIEW_SAVED, AUDIT_NOMINEE_DETAILS_SAVED,
    AUDIT_FNF_APPROVED, AUDIT_FNF_PAID, AUDIT_FNF_REJECTED, AUDIT_FNF_SAVED,
    AUDIT_HANDOVER_ACCEPTED, AUDIT_HANDOVER_CREATED, AUDIT_HANDOVER_UPDATED,
    AUDIT_SEPARATION_CLOSED, AUDIT_SEPARATION_DECIDED, AUDIT_SEPARATION_INITIATED,
    AUDIT_SEPARATION_WAIVED, AUDIT_SEPARATION_WITHDRAWN,
    CLOSED_SEPARATION_STAGES,
    COLL_ACCESS_CLEARANCES, COLL_ASSET_RETURNS, COLL_CLEARANCE_TASKS,
    COLL_DESIGNATIONS, COLL_EMPLOYEE_PROFILES, COLL_EXIT_INTERVIEWS,
    COLL_ALUMNI, COLL_FNF_SETTLEMENTS, COLL_HANDOVER_TASKS, COLL_PROBATION_REVIEWS,
    COLL_SEPARATIONS,
    ENTITY_ACCESS_CLEARANCE, ENTITY_ASSET_RETURN, ENTITY_CLEARANCE,
    ENTITY_EXIT_INTERVIEW, ENTITY_FNF, ENTITY_HANDOVER, ENTITY_SEPARATION,
    MAX_TASKS_PER_SEPARATION,
    AccessClearanceStatus, AssetReturnStatus, ClearanceOwnerType, ClearanceStatus,
    EmploymentStatus, ExitType, FnfStatus, HandoverStatus, HrmsRole, ProbationOutcome,
    SeparationStage,
    notice_days_for,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _out_with_id(doc: dict) -> dict:
    """Like `_out`, but for the three child collections that carry no business id of their
    own (handover/clearance/access-clearance items) — the Mongo `_id` IS their identity, so
    it is kept, as a string, the same convention hrms_document_service uses for the same
    reason."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _oid(value: str, label: str = "record") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _add_days(iso_date: str, days: int) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in iso_date.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def _require_iso_date(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid YYYY-MM-DD date.")
    return value


async def _find_user(user_id: str) -> tuple:
    oid = _oid(user_id)
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc, coll
    return None, None


def _display_name(user: Optional[dict]) -> Optional[str]:
    if not user:
        return None
    return (user.get("full_name")
            or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
            or user.get("email"))


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _designation_level(company_id: str, designation_id: Optional[str]) -> Optional[int]:
    if not designation_id:
        return None
    try:
        doc = await get_collection(COLL_DESIGNATIONS).find_one(
            {"_id": ObjectId(str(designation_id)), "company_id": str(company_id)})
    except (InvalidId, TypeError):
        return None
    return (doc or {}).get("level")


async def _is_on_probation(company_id: str, employee_code: str) -> bool:
    """The latest probation review's outcome decides this. No record at all reads as
    Confirmed — the same "assume the safer-for-the-company reading only where the doc is
    silent" principle notice_days_for's own default level follows, and consistent with an
    employee whose probation was simply never tracked in this system."""
    row = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        sort=[("started_on", -1)])
    if not row:
        return False
    return row.get("outcome") in (ProbationOutcome.PENDING.value, ProbationOutcome.EXTENDED.value)


async def _reporting_manager_id(profile: dict) -> Optional[str]:
    """Who signs off this person's handover.

    The linked login is asked first, because that is the record a manager change is made
    on once somebody has an account. The PROFILE's own `reporting_manager_id` is the
    fallback, and it is the only answer for an employee created straight through
    onboarding: confirm_joining records their manager there, and `link_user` is a separate,
    optional step that may never happen. Reading only the login left `reporting_manager_id`
    empty on the separation, so nobody at all could accept the handover -- and BR-025 then
    refused to close the exit, leaving a forced closure as the only way out of a case where
    nothing had actually gone wrong.
    """
    user_id = profile.get("user_id")
    if user_id:
        user, _coll = await _find_user(user_id)
        if (user or {}).get("reporting_manager"):
            return user["reporting_manager"]
    return profile.get("reporting_manager_id")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    """The employee code belonging to the caller, or None if they have no profile."""
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str((actor or {}).get("_id") or "")})
    return (profile or {}).get("employee_code")


async def assert_own_case(actor: dict, company_id: str, employee_code: str) -> None:
    """An employee may only act on their OWN exit.

    SEPARATION_INITIATE and EXIT_INTERVIEW_WRITE are granted to every employee so they can
    resign and complete their own exit interview (7.18 step 137, 22.2 step 195). Without
    this check that grant also let any employee open a separation case against ANY
    colleague -- the capability comment in models/hrms.py flagged the missing ownership
    check as a follow-up, and this is it.

    Anyone holding SEPARATION_MANAGE is acting for HR and is not restricted; the check
    only binds callers whose sole route in is the self-service grant.
    """
    from app.models.hrms import Cap
    from app.utils.hrms_access import can
    if can(actor, Cap.SEPARATION_MANAGE):
        return
    own = await _own_employee_code(actor, company_id)
    if not own or own != employee_code:
        raise HTTPException(
            status_code=403,
            detail="You can only do this for your own employment record.")


async def _get_separation(company_id: str, sep_no: str) -> dict:
    doc = await get_collection(COLL_SEPARATIONS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Separation '{sep_no}' not found.")
    return doc


def _require_open(sep: dict) -> None:
    if sep.get("stage") in CLOSED_SEPARATION_STAGES:
        raise HTTPException(
            status_code=409,
            detail=f"{sep['sep_no']} is already \"{sep.get('stage')}\" — no further action is possible.")


async def _task_count(coll_name: str, company_id: str, sep_no: str) -> int:
    return await get_collection(coll_name).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no})


# ─────────────────────────────────────────────────────────────
# §7.18 — Resignation & Notice Period
# ─────────────────────────────────────────────────────────────
async def initiate_separation(actor: dict, company_id: str, payload: dict) -> dict:
    """§7.18 steps 137-139: raise a case and calculate the notice obligation.

    The calculation is a STARTING POINT, not a verdict — `notice_basis` tells the caller
    whether it rests on a real designation level or the safe default, and `decide_separation`
    / `approve_separation` are how a waiver or early release then gets recorded (BR-016).
    """
    employee_code = str(payload.get("employee_code") or "").strip()
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")

    # An employee resigns for themselves; HR raises a case for anybody.
    await assert_own_case(actor, company_id, employee_code)

    existing_open = await get_collection(COLL_SEPARATIONS).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "stage": {"$nin": list(CLOSED_SEPARATION_STAGES)},
    })
    if existing_open:
        raise HTTPException(
            status_code=409,
            detail=f"{employee_code} already has an open separation ({existing_open['sep_no']}).")

    profile = await _get_profile(company_id, employee_code)
    exit_type = payload.get("exit_type") or ExitType.RESIGNATION.value
    resignation_date = _require_iso_date(
        payload.get("resignation_date"), "Resignation date") or _today()

    level = await _designation_level(company_id, profile.get("designation_id"))
    on_probation = await _is_on_probation(company_id, employee_code)
    calculated_days = notice_days_for(on_probation, level)
    calculated_lwd = _add_days(resignation_date, calculated_days)
    proposed_lwd = _require_iso_date(payload.get("proposed_lwd"), "Proposed LWD") or calculated_lwd

    manager_id = await _reporting_manager_id(profile)
    year = datetime.now(timezone.utc).year
    sep_no = await next_business_id("separation", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "sep_no": sep_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        # A profile created by onboarding carries the person's name in identity_snapshot
        # rather than in a top-level field, so without this the case -- and every
        # notification and alumni row built from it -- was addressed to nobody.
        "employee_name": (profile.get("display_name") or profile.get("full_name")
                          or (profile.get("identity_snapshot") or {}).get("name")),
        "user_id": profile.get("user_id"),
        "reporting_manager_id": manager_id,
        "exit_type": exit_type,
        "reason": payload.get("reason"),
        "resignation_date": resignation_date,
        "employment_status_at_exit": profile.get("employment_status"),
        "designation_level": level,
        "notice_basis": "designation level" if level else "no designation level on file — assumed L1",
        "on_probation_at_exit": on_probation,
        "calculated_notice_days": calculated_days,
        "calculated_lwd": calculated_lwd,
        "proposed_lwd": proposed_lwd,
        "recommended_lwd": None,
        "waiver_days": None,
        "shortfall_days": None,
        "waiver_approved": None,
        "waiver_remarks": None,
        "final_lwd": None,           # set once accepted (decide_separation), or on approval
        "stage": SeparationStage.INITIATED.value,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_SEPARATIONS).insert_one(doc)

    # §7.18 step 142: status moves to Notice Period the moment the case is opened — the
    # obligation exists from here, whatever HR later decides about a waiver.
    #
    # A profile never linked to a portal login (Phase 9's employee.link_user is a separate,
    # optional step — see hrms_employee_service.link_user) has no `user_id`, and
    # update_profile looks a profile up BY user_id, so there is nothing for it to find. The
    # separation record above already carries employment_status_at_exit correctly either
    # way; this is only the sync onto the login-linked profile row, which simply does not
    # exist yet for an unlinked employee. Skipping it (rather than `profile["user_id"]`,
    # which raised an unhandled KeyError -> 500 here) is the same "no linked account yet"
    # case this codebase already treats as normal elsewhere.
    if profile.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        await update_profile(actor, profile["user_id"],
                             {"employment_status": EmploymentStatus.ON_NOTICE.value}, company_id)

    await audit(actor, AUDIT_SEPARATION_INITIATED, ENTITY_SEPARATION, sep_no,
               f"{employee_code}, {exit_type}, calculated notice {calculated_days}d "
               f"(LWD {calculated_lwd})", company_id)
    # 7.18 step 2: the reporting manager is told, and HR picks up the retention
    # conversation. Nothing here notified anybody before.
    await _notify_exit(company_id, doc, "initiated")
    return _out(doc)


async def list_separations(actor: dict, company_id: str, *, stage: Optional[str] = None,
                           employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if stage:
        query["stage"] = stage
    if employee_code:
        query["employee_code"] = employee_code
    rows = await get_collection(COLL_SEPARATIONS).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def get_separation(actor: dict, company_id: str, sep_no: str) -> dict:
    """One case, composed with the child-collection counts the Exit tab (§22.1) needs to
    show progress without five separate round trips."""
    sep = await _get_separation(company_id, sep_no)
    out = _out(sep)

    handover_total = await _task_count(COLL_HANDOVER_TASKS, company_id, sep_no)
    handover_done = await get_collection(COLL_HANDOVER_TASKS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": HandoverStatus.ACCEPTED.value})
    clearance_total = await _task_count(COLL_CLEARANCE_TASKS, company_id, sep_no)
    clearance_done = await get_collection(COLL_CLEARANCE_TASKS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no,
         "status": {"$in": [ClearanceStatus.CLEARED.value, ClearanceStatus.WAIVED.value]}})
    asset_total = await _task_count(COLL_ASSET_RETURNS, company_id, sep_no)
    asset_pending = await get_collection(COLL_ASSET_RETURNS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": AssetReturnStatus.PENDING.value})
    access_total = await _task_count(COLL_ACCESS_CLEARANCES, company_id, sep_no)
    access_pending = await get_collection(COLL_ACCESS_CLEARANCES).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": AccessClearanceStatus.PENDING.value})
    interview = await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    fnf = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})

    out["progress"] = {
        "handover": {"done": handover_done, "total": handover_total},
        "clearance": {"done": clearance_done, "total": clearance_total},
        "asset_returns": {"pending": asset_pending, "total": asset_total},
        "access_clearances": {"pending": access_pending, "total": access_total},
        "exit_interview_done": bool(interview),
        "fnf_status": (fnf or {}).get("status"),
    }
    return out


async def decide_separation(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """§7.18 steps 140-142: HR/manager records acceptance. Any revision away from the
    CALCULATED notice needs SeparationApprovalIn before it takes effect (BR-016) — recording
    it here only proposes it; `final_lwd` stays the calculated date until approved.

    Also opens the standard departmental clearance tasks (§22.2 step 192: "System creates
    Departmental Clearance tasks") — this is the point the doc's own step sequence puts that
    system action, right after notice is accepted and before handover/clearance work starts.
    """
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)

    revised_lwd = _require_iso_date(payload.get("revised_lwd"), "Revised LWD")
    waiver_days = payload.get("waiver_days")
    shortfall_days = payload.get("shortfall_days")
    needs_approval = bool(
        waiver_days or shortfall_days
        or (revised_lwd and revised_lwd != sep.get("calculated_lwd")))

    updates = {
        "recommended_lwd": revised_lwd or sep.get("calculated_lwd"),
        "waiver_days": waiver_days,
        "shortfall_days": shortfall_days,
        "decision_remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    if not needs_approval:
        # Nothing to approve — the calculated notice stands, so it is final immediately.
        updates["final_lwd"] = updates["recommended_lwd"]
        updates["waiver_approved"] = None
    if sep.get("stage") == SeparationStage.INITIATED.value:
        updates["stage"] = SeparationStage.HANDOVER_CLEARANCE.value

    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})

    if not await get_collection(COLL_CLEARANCE_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no}):
        await _seed_clearance_tasks(actor, company_id, sep)

    await audit(actor, AUDIT_SEPARATION_DECIDED, ENTITY_SEPARATION, sep_no,
               f"recommended LWD {updates['recommended_lwd']}"
               + (" — awaiting approval" if needs_approval else " — final"), company_id)
    fresh = await _get_separation(company_id, sep_no)
    await _notify_exit(company_id, fresh, "decided")
    if fresh.get("recommended_lwd") and not fresh.get("final_lwd"):
        # Early release: BR-016 needs somebody to approve it, and nothing told them.
        await _notify_exit(company_id, fresh, "approval_needed")
    return await get_separation(actor, company_id, sep_no)


async def approve_separation(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """The written approval BR-016 requires before a waiver or early release takes effect."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if not sep.get("recommended_lwd") or sep.get("final_lwd"):
        raise HTTPException(
            status_code=409,
            detail="Nothing is pending approval on this case.")

    approved = bool(payload.get("approved"))
    updates = {
        "waiver_approved": approved,
        "waiver_remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    if approved:
        updates["final_lwd"] = sep["recommended_lwd"]
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})

    await audit(actor, AUDIT_SEPARATION_WAIVED, ENTITY_SEPARATION, sep_no,
               f"{'approved' if approved else 'rejected'}: LWD {sep['recommended_lwd']}", company_id)
    return await get_separation(actor, company_id, sep_no)


async def withdraw_separation(actor: dict, company_id: str, sep_no: str, remarks: Optional[str]) -> dict:
    """An employee changing their mind, or HR raising a case in error. Reverts the employee
    to Active — the only stage transition in this module that undoes an employment_status
    change rather than advancing it."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.WITHDRAWN.value, "withdrawal_remarks": remarks,
                  "updated_at": datetime.now(timezone.utc)}})
    if sep.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        await update_profile(actor, sep["user_id"],
                             {"employment_status": EmploymentStatus.ACTIVE.value}, company_id)
    await audit(actor, AUDIT_SEPARATION_WITHDRAWN, ENTITY_SEPARATION, sep_no, remarks, company_id)
    return await get_separation(actor, company_id, sep_no)


# ─────────────────────────────────────────────────────────────
# §22.2 — Handover Plan
# ─────────────────────────────────────────────────────────────
async def create_handover_task(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if await _task_count(COLL_HANDOVER_TASKS, company_id, sep_no) >= MAX_TASKS_PER_SEPARATION:
        raise HTTPException(status_code=400, detail="This case already carries the maximum number of handover tasks.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "sep_no": sep_no,
        "task": payload.get("task"),
        "description": payload.get("description"),
        "assigned_to": payload.get("assigned_to"),
        "owner_id": payload.get("owner_id") or sep.get("reporting_manager_id"),
        "due_date": _require_iso_date(payload.get("due_date"), "Due date"),
        "attachment": payload.get("attachment"),
        "status": HandoverStatus.PENDING.value,
        "completion_evidence": None,
        "manager_acceptance": None,
        "remarks": None,
        "created_at": now,
        "updated_at": now,
    }
    if not doc["task"]:
        raise HTTPException(status_code=422, detail="Describe the task or knowledge item.")
    result = await get_collection(COLL_HANDOVER_TASKS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_HANDOVER_CREATED, ENTITY_HANDOVER, str(result.inserted_id),
               f"{sep_no}: {doc['task']}", company_id)
    return _out_with_id(doc)


async def list_handover_tasks(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_HANDOVER_TASKS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def _get_handover_task(company_id: str, sep_no: str, task_id: str) -> dict:
    doc = await get_collection(COLL_HANDOVER_TASKS).find_one(
        {"_id": _oid(task_id, "handover task"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Handover task not found.")
    return doc


async def update_handover_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                               payload: dict) -> dict:
    """The doer (or HR, editing the plan) updates a task — including marking it Submitted,
    which is what puts it in front of the manager for acceptance."""
    await _get_handover_task(company_id, sep_no, task_id)
    clean = {k: v for k, v in payload.items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_HANDOVER_TASKS).update_one(
        {"_id": _oid(task_id)}, {"$set": clean})
    await audit(actor, AUDIT_HANDOVER_UPDATED, ENTITY_HANDOVER, task_id,
               ", ".join(sorted(clean.keys())), company_id)
    return _out_with_id(await _get_handover_task(company_id, sep_no, task_id))


async def accept_handover_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                               payload: dict) -> dict:
    """§22.2 step 191: the reporting manager's sign-off. The one place in this module a
    capability check alone is not enough — a manager may only accept work on THEIR OWN
    report's case, enforced by the caller matching `sep.reporting_manager_id` against actor.

    Enforced here, not just documented: `Cap.HANDOVER_APPROVE` is a role-wide grant (every
    HOD/Manager in the company holds it, the same as every other capability in this module),
    so without this check any manager could accept or reject a handover on any OTHER
    manager's report — exactly the cross-department mistake the docstring above already
    claimed was impossible. MD (and internal staff via the ADMIN implicit-grant) are exempt,
    the same override authority they hold everywhere else in this module (the named manager
    may be unavailable, on leave, or the one leaving)."""
    task = await _get_handover_task(company_id, sep_no, task_id)
    if hrms_role(actor) is HrmsRole.MANAGER:
        sep = await _get_separation(company_id, sep_no)
        manager_id = str(sep.get("reporting_manager_id") or "")
        if not manager_id or manager_id != str(actor.get("_id") or ""):
            raise HTTPException(
                status_code=403,
                detail="Only this employee's reporting manager may accept or reject their handover.")
    accepted = bool(payload.get("accepted"))
    updates = {
        "status": HandoverStatus.ACCEPTED.value if accepted else HandoverStatus.REJECTED.value,
        "manager_acceptance": accepted,
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_HANDOVER_TASKS).update_one({"_id": task["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_HANDOVER_ACCEPTED, ENTITY_HANDOVER, task_id,
               "accepted" if accepted else "rejected", company_id)
    return _out_with_id(await _get_handover_task(company_id, sep_no, task_id))


# ─────────────────────────────────────────────────────────────
# §22.2 — Departmental Clearance
# ─────────────────────────────────────────────────────────────
# The five standing functions the BA doc names by name (step 192). A company that needs a
# sixth adds it with create_clearance_task — this list is the FLOOR every case gets for free,
# not the ceiling.
_STANDARD_CLEARANCE_OWNERS = [
    (ClearanceOwnerType.MANAGER, "Manager clearance", "reporting_manager_id"),
    (ClearanceOwnerType.HR, "HR clearance", None),
    (ClearanceOwnerType.IT, "IT clearance", None),
    (ClearanceOwnerType.ADMIN, "Admin clearance", None),
    (ClearanceOwnerType.FINANCE, "Finance clearance", None),
]


async def _seed_clearance_tasks(actor: dict, company_id: str, sep: dict) -> None:
    now = datetime.now(timezone.utc)
    docs = []
    for owner_type, label, owner_field in _STANDARD_CLEARANCE_OWNERS:
        docs.append({
            "company_id": str(company_id),
            "sep_no": sep["sep_no"],
            "owner_type": owner_type.value,
            "owner_id": sep.get(owner_field) if owner_field else None,
            "task": label,
            "due_date": sep.get("final_lwd") or sep.get("recommended_lwd") or sep.get("calculated_lwd"),
            "status": ClearanceStatus.PENDING.value,
            "recovery_amount": None,
            "evidence": None,
            "remarks": None,
            "created_at": now,
            "updated_at": now,
        })
    if docs:
        await get_collection(COLL_CLEARANCE_TASKS).insert_many(docs)
        await audit(actor, AUDIT_CLEARANCE_CREATED, ENTITY_CLEARANCE, sep["sep_no"],
                   f"{len(docs)} standard departmental clearance tasks opened", company_id)


async def create_clearance_task(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """§22.2: '... and any other configured function' — a clearance owner beyond the five
    standard ones."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "sep_no": sep_no,
        "owner_type": payload.get("owner_type"),
        "owner_id": payload.get("owner_id"),
        "task": payload.get("task"),
        "due_date": _require_iso_date(payload.get("due_date"), "Due date"),
        "status": ClearanceStatus.PENDING.value,
        "recovery_amount": None, "evidence": None, "remarks": None,
        "created_at": now, "updated_at": now,
    }
    if not doc["task"]:
        raise HTTPException(status_code=422, detail="Describe the clearance task.")
    result = await get_collection(COLL_CLEARANCE_TASKS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_CLEARANCE_CREATED, ENTITY_CLEARANCE, str(result.inserted_id),
               f"{sep_no}: {doc['task']}", company_id)
    return _out_with_id(doc)


async def list_clearance_tasks(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_CLEARANCE_TASKS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def act_on_clearance_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                                payload: dict) -> dict:
    doc = await get_collection(COLL_CLEARANCE_TASKS).find_one(
        {"_id": _oid(task_id, "clearance task"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Clearance task not found.")
    updates = {
        "status": payload.get("status"),
        "recovery_amount": payload.get("recovery_amount"),
        "evidence": payload.get("evidence"),
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_CLEARANCE_TASKS).update_one({"_id": doc["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_CLEARANCE_ACTIONED, ENTITY_CLEARANCE, task_id,
               f"{doc.get('task')}: {updates['status']}", company_id)
    return _out_with_id({**doc, **updates})


# ─────────────────────────────────────────────────────────────
# §22.2 — Asset Return Requests
# ─────────────────────────────────────────────────────────────
async def create_asset_return(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """The employee or HR may initiate this (§22.2) — the route allows either without an
    extra capability check when the actor IS the separating employee."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if not payload.get("description"):
        raise HTTPException(status_code=422, detail="Describe the asset.")
    year = datetime.now(timezone.utc).year
    ast_no = await next_business_id("asset_return", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "ast_no": ast_no,
        "company_id": str(company_id), "sep_no": sep_no,
        "asset_id": payload.get("asset_id"),
        "category": payload.get("category"),
        "description": payload.get("description"),
        "issued_date": _require_iso_date(payload.get("issued_date"), "Issued date"),
        "return_request_date": _today(),
        "expected_return_date": _require_iso_date(
            payload.get("expected_return_date"), "Expected return date"),
        "returned_date": None,
        "condition": None,
        "missing_or_damaged": False,
        "recovery_amount": None,
        "received_by": None,
        "attachment": None,
        "status": AssetReturnStatus.PENDING.value,
        "remarks": None,
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_ASSET_RETURNS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_ASSET_RETURN_CREATED, ENTITY_ASSET_RETURN, ast_no,
               f"{sep_no}: {doc['description']}", company_id)
    return _out(doc)


async def list_asset_returns(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_ASSET_RETURNS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out(r) for r in rows]


async def update_asset_return(actor: dict, company_id: str, sep_no: str, ast_no: str,
                              payload: dict) -> dict:
    """HR/Admin confirms receipt and condition (§22.2)."""
    doc = await get_collection(COLL_ASSET_RETURNS).find_one(
        {"ast_no": ast_no, "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Asset return '{ast_no}' not found.")
    clean = {k: v for k, v in payload.items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")
    for field in ("returned_date",):
        if field in clean:
            clean[field] = _require_iso_date(clean[field], "Returned date")
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_ASSET_RETURNS).update_one({"_id": doc["_id"]}, {"$set": clean})
    await audit(actor, AUDIT_ASSET_RETURN_UPDATED, ENTITY_ASSET_RETURN, ast_no,
               ", ".join(sorted(clean.keys())), company_id)
    return _out({**doc, **clean})


# ─────────────────────────────────────────────────────────────
# §22.2 — Access Clearance
# ─────────────────────────────────────────────────────────────
async def create_access_clearance(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "sep_no": sep_no,
        "system_type": payload.get("system_type"),
        "description": payload.get("description"),
        "owner_id": payload.get("owner_id"),
        "status": AccessClearanceStatus.PENDING.value,
        "remarks": None,
        "created_at": now, "updated_at": now,
    }
    if not doc["system_type"]:
        raise HTTPException(status_code=422, detail="Select the system/access type.")
    result = await get_collection(COLL_ACCESS_CLEARANCES).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_ACCESS_CLEARANCE_CREATED, ENTITY_ACCESS_CLEARANCE,
               str(result.inserted_id), f"{sep_no}: {doc['system_type']}", company_id)
    return _out_with_id(doc)


async def list_access_clearances(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_ACCESS_CLEARANCES).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def update_access_clearance(actor: dict, company_id: str, sep_no: str, item_id: str,
                                  payload: dict) -> dict:
    doc = await get_collection(COLL_ACCESS_CLEARANCES).find_one(
        {"_id": _oid(item_id, "access clearance"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Access clearance item not found.")
    updates = {
        "status": payload.get("status"),
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_ACCESS_CLEARANCES).update_one({"_id": doc["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_ACCESS_CLEARANCE_UPDATED, ENTITY_ACCESS_CLEARANCE, item_id,
               f"{doc.get('system_type')}: {updates['status']}", company_id)
    return _out_with_id({**doc, **updates})


# ─────────────────────────────────────────────────────────────
# §22.2 step 195 — Exit Interview Form
# ─────────────────────────────────────────────────────────────
async def save_exit_interview(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Upsert — one interview per case (COLL_EXIT_INTERVIEWS carries a unique index on
    (company_id, sep_no)), so a re-submission corrects the same record rather than
    accumulating duplicates."""
    sep = await _get_separation(company_id, sep_no)   # 404s if the case does not exist
    # EXIT_INTERVIEW_WRITE is granted to every employee so they can complete their OWN
    # exit interview. Without this it also let them write to anybody else's.
    await assert_own_case(actor, company_id, sep.get("employee_code"))
    now = datetime.now(timezone.utc)
    clean = {k: v for k, v in payload.items() if v is not None}
    clean["updated_at"] = now
    await get_collection(COLL_EXIT_INTERVIEWS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": clean,
         "$setOnInsert": {"company_id": str(company_id), "sep_no": sep_no, "created_at": now}},
        upsert=True)
    await audit(actor, AUDIT_EXIT_INTERVIEW_SAVED, ENTITY_EXIT_INTERVIEW, sep_no, None, company_id)
    return _out(await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no}))


async def get_exit_interview(actor: dict, company_id: str, sep_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    return _out(doc) if doc else None


# ─────────────────────────────────────────────────────────────
# §7.20 step 157 — Demise/Missing nominee & legal documentation
# ─────────────────────────────────────────────────────────────
async def save_nominee_details(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Kept ON the separation record itself, not a parallel collection — this is
    exit-type-specific data about ONE case (Demise/Missing), the same reason handover/
    clearance/asset-return already live alongside it rather than in COLL_EMPLOYEE_PROFILES.
    Nothing in the BA doc says this is restricted to those two exit types, so it is not
    enforced here either — a company that wants to record it for other types may."""
    sep = await _get_separation(company_id, sep_no)
    clean = {k: v for k, v in payload.items() if v is not None}
    now = datetime.now(timezone.utc)
    await get_collection(COLL_SEPARATIONS).update_one(
        {"_id": sep["_id"]}, {"$set": {"nominee_details": clean, "updated_at": now}})
    await audit(actor, AUDIT_NOMINEE_DETAILS_SAVED, ENTITY_SEPARATION, sep_no,
               "nominee/legal documentation saved", company_id)
    return _out(await _get_separation(company_id, sep_no))


# ─────────────────────────────────────────────────────────────
# §7.21 — Full & Final Settlement
# ─────────────────────────────────────────────────────────────
async def _rolled_up_recoveries(company_id: str, sep_no: str) -> float:
    """§22.2 step 196: unreturned assets and clearance recoveries feed F&F automatically."""
    total = 0.0
    for coll_name in (COLL_ASSET_RETURNS, COLL_CLEARANCE_TASKS):
        async for row in get_collection(coll_name).find(
                {"company_id": str(company_id), "sep_no": sep_no,
                 "recovery_amount": {"$ne": None}}):
            total += float(row.get("recovery_amount") or 0)
    return round(total, 2)


def _fnf_total(inputs: dict, rolled_up_recovery: float) -> float:
    earnings = (
        float(inputs.get("payable_days") or 0)
        + float(inputs.get("leave_encashment") or 0)
        + float(inputs.get("variable_pay_hold_release") or 0)
        + float(inputs.get("other_earnings") or 0)
    )
    # notice_pay_or_shortfall may itself be negative (a recovery) — added as-is.
    earnings += float(inputs.get("notice_pay_or_shortfall") or 0)
    deductions = (
        float(inputs.get("advance_recovery") or 0)
        + float(inputs.get("other_deductions") or 0)
        + rolled_up_recovery
    )
    return round(earnings - deductions, 2)


async def save_fnf(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """HR/Payroll prepares the settlement (the maker half of BR-021's maker/checker gate).
    Upsert while still Draft/Prepared; once Approved or Paid it is closed to further edits —
    a correction after approval is a new decision, not a silent rewrite of an approved figure,
    the same discipline BR-020 asks of real payroll."""
    sep = await _get_separation(company_id, sep_no)
    existing = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if existing and existing.get("status") in (FnfStatus.APPROVED.value, FnfStatus.PAID.value):
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} is already \"{existing['status']}\" and cannot be edited.")

    inputs = {k: v for k, v in payload.items() if k != "remarks"}
    rolled_up = await _rolled_up_recoveries(company_id, sep_no)
    total = _fnf_total(inputs, rolled_up)
    now = datetime.now(timezone.utc)
    doc = {
        **inputs,
        "rolled_up_recovery": rolled_up,
        "total_settlement": total,
        "remarks": payload.get("remarks"),
        "status": FnfStatus.PREPARED.value,
        "prepared_by": str(actor.get("_id")) if actor.get("_id") else None,
        "approved_by": None, "approved_at": None,
        "paid_on": None, "payment_reference": None,
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": doc,
         "$setOnInsert": {"company_id": str(company_id), "sep_no": sep_no, "created_at": now}},
        upsert=True)
    if sep.get("stage") not in (SeparationStage.FNF_PENDING.value,):
        await get_collection(COLL_SEPARATIONS).update_one(
            {"company_id": str(company_id), "sep_no": sep_no},
            {"$set": {"stage": SeparationStage.FNF_PENDING.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_SAVED, ENTITY_FNF, sep_no,
               f"total {total} (recoveries rolled up: {rolled_up})", company_id)
    return await get_fnf(actor, company_id, sep_no)


async def get_fnf(actor: dict, company_id: str, sep_no: str) -> dict:
    doc = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No F&F prepared yet for {sep_no}.")
    return _out(doc)


async def approve_fnf(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Finance's checker gate (BR-021)."""
    doc = await get_fnf(actor, company_id, sep_no)
    if doc.get("status") != FnfStatus.PREPARED.value:
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} is \"{doc.get('status')}\", not awaiting approval.")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    updates = {
        "status": FnfStatus.APPROVED.value if approved else FnfStatus.REJECTED.value,
        "approved_by": str(actor.get("_id")) if actor.get("_id") else None,
        "approved_at": now,
        "approval_remarks": payload.get("remarks"),
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})
    if approved:
        await get_collection(COLL_SEPARATIONS).update_one(
            {"company_id": str(company_id), "sep_no": sep_no},
            {"$set": {"stage": SeparationStage.FNF_APPROVED.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_APPROVED if approved else AUDIT_FNF_REJECTED,
               ENTITY_FNF, sep_no, payload.get("remarks"), company_id)
    return await get_fnf(actor, company_id, sep_no)


async def mark_fnf_paid(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    doc = await get_fnf(actor, company_id, sep_no)
    if doc.get("status") != FnfStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} must be Approved before it can be marked paid.")
    now = datetime.now(timezone.utc)
    updates = {
        "status": FnfStatus.PAID.value,
        "paid_on": _require_iso_date(payload.get("paid_on"), "Paid on") or _today(),
        "payment_reference": payload.get("reference"),
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.SETTLED.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_PAID, ENTITY_FNF, sep_no,
               updates["payment_reference"], company_id)
    return await get_fnf(actor, company_id, sep_no)


# ─────────────────────────────────────────────────────────────
# §22.2 step 199 — Closure
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# The Last Working Day (7.18 step 10)
# ─────────────────────────────────────────────────────────────
async def _revoke_login(company_id: str, employee_code: str) -> bool:
    """Deactivate the leaver's login. Returns whether a row was actually changed.

    Same write `close_separation` has always done -- what changes is WHEN. Closure sits
    behind the F&F being paid, which is typically weeks after the person stopped coming
    in; leaving their account live for that window is the gap this closes.
    """
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code}, {"user_id": 1})
    user_id = (profile or {}).get("user_id")
    if not user_id:
        return False
    for coll_name in USER_COLLECTIONS:
        result = await get_collection(coll_name).update_one(
            {"_id": _oid(user_id)}, {"$set": {"is_active": False}})
        if getattr(result, "modified_count", 0):
            return True
    return False


async def run_lwd_sweep(company_id: str) -> dict:
    """On the last working day: revoke access, and open the F&F if nobody has.

    Anchored on `final_lwd` -- the approved date -- and never on the calculated one, which
    is only a proposal until somebody accepts it. Idempotent: `lwd_processed_at` is stamped
    on the case, so a re-run does nothing and a case processed by hand first is skipped.

    Deliberately does NOT close the case. Closure means the F&F is settled and the
    clearances are done, which is a human judgement (BR-025); this only does the two
    things that should not wait for it.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cases = await get_collection(COLL_SEPARATIONS).find({
        "company_id": str(company_id),
        "stage": {"$nin": list(CLOSED_SEPARATION_STAGES)},
        "final_lwd": {"$ne": None, "$lte": today},
        "lwd_processed_at": None,
    }).to_list(500)

    revoked = fnf_opened = 0
    for case in cases:
        sep_no = case["sep_no"]
        now = datetime.now(timezone.utc)
        changes = {"lwd_processed_at": now, "updated_at": now}

        if await _revoke_login(company_id, case.get("employee_code")):
            revoked += 1
            changes["access_revoked_at"] = now
            await audit(None, AUDIT_SEPARATION_DECIDED, ENTITY_SEPARATION, sep_no,
                        "login deactivated on the last working day", company_id)

        # Open the F&F so it is waiting for Finance rather than waiting to be remembered.
        existing = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
            {"company_id": str(company_id), "sep_no": sep_no})
        if not existing:
            await get_collection(COLL_FNF_SETTLEMENTS).insert_one({
                "company_id": str(company_id), "sep_no": sep_no,
                "employee_code": case.get("employee_code"),
                "status": FnfStatus.DRAFT.value,
                "opened_by_system": True,
                "created_at": now, "updated_at": now,
            })
            fnf_opened += 1
            if case.get("stage") not in (SeparationStage.FNF_PENDING.value,
                                         SeparationStage.FNF_APPROVED.value,
                                         SeparationStage.SETTLED.value):
                changes["stage"] = SeparationStage.FNF_PENDING.value

        await get_collection(COLL_SEPARATIONS).update_one(
            {"sep_no": sep_no, "company_id": str(company_id)}, {"$set": changes})
        await _notify_exit(company_id, case, "lwd_reached")

    return {"checked": len(cases), "access_revoked": revoked, "fnf_opened": fnf_opened}


# ─────────────────────────────────────────────────────────────
# Notifications (7.18 step 2 and the rest of the chain)
# ─────────────────────────────────────────────────────────────
async def _notify_exit(company_id: str, case: dict, event: str, **extra) -> None:
    """Tell whoever the event concerns. Best-effort, never load-bearing.

    This module sent nothing at all before: a resignation reached the reporting manager
    only if somebody told them out of band, which is exactly what step 2 of the workflow
    exists to prevent.
    """
    try:
        from app.services.hrms_notify_service import notify_hrms_role, notify_user
        name = case.get("employee_name") or case.get("employee_code")
        sep_no = case.get("sep_no")
        link = f"/hrms/separations/{sep_no}"
        manager_id = case.get("reporting_manager_id")

        if event == "initiated":
            if manager_id:
                await notify_user(
                    manager_id, f"{name} has resigned",
                    f"{name} raised {sep_no}. Their notice runs to "
                    f"{case.get('calculated_lwd')}. You own their handover acceptance.",
                    link=link)
            await notify_hrms_role(
                company_id, ["HR"], f"Exit initiated: {name}",
                f"{sep_no} ({case.get('exit_type')}). Notice calculated to "
                f"{case.get('calculated_lwd')}. Start the retention conversation and "
                f"record the decision.", link=link, email=True)
        elif event == "decided":
            if manager_id:
                await notify_user(
                    manager_id, f"Last working day set for {name}",
                    f"{sep_no}: {case.get('final_lwd') or case.get('recommended_lwd')}. "
                    f"Handover and clearance are open.", link=link)
        elif event == "approval_needed":
            await notify_hrms_role(
                company_id, ["HR", "admin"], f"Early release needs approval: {name}",
                f"{sep_no} proposes leaving before the notice period ends. "
                f"It cannot complete until somebody approves the waiver.",
                link=link, email=True)
        elif event == "lwd_reached":
            await notify_hrms_role(
                company_id, ["HR"], f"Last working day reached: {name}",
                f"{sep_no}: access has been revoked and the full & final settlement is "
                f"open for input.", link=link, email=True)
        elif event == "closed":
            await notify_hrms_role(
                company_id, ["HR"], f"Exit closed: {name}",
                f"{sep_no} is closed and {name} has been archived to alumni.", link=link)
    except Exception as e:                          # pragma: no cover - defensive
        print(f"[WARN] exit notification ({event}) not sent for "
              f"{case.get('sep_no')}: {e}")


async def close_separation(actor: dict, company_id: str, sep_no: str, *,
                           force: bool = False, force_reason: str = None) -> dict:
    """BR-025: exit cannot be treated as complete until mandatory handover and clearance
    tasks are completed or formally waived. `force` is HR's explicit override for a task that
    will never close (e.g. an absconding case with no handover possible) — recorded as such
    in the audit line rather than silently skipped.
    """
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)

    # An override with no reason is indistinguishable from a mistake six months later,
    # and this one closes an exit with work outstanding.
    force_reason = clean_text(force_reason, limit=2000) if force else None
    if force and not force_reason:
        raise HTTPException(
            status_code=422,
            detail=("Say why this exit is being closed with tasks outstanding. A forced "
                    "closure with no reason cannot be reviewed later."))

    if not force:
        open_handover = await get_collection(COLL_HANDOVER_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": {"$nin": [HandoverStatus.ACCEPTED.value, HandoverStatus.REJECTED.value]}})
        open_clearance = await get_collection(COLL_CLEARANCE_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": ClearanceStatus.PENDING.value})
        fnf = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
            {"company_id": str(company_id), "sep_no": sep_no})
        # Asset returns and access items were NOT checked before, which meant a case
        # could be closed with a laptop outstanding and a live VPN account -- the two
        # things the business rule most obviously means by "clearance".
        open_assets = await get_collection(COLL_ASSET_RETURNS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": AssetReturnStatus.PENDING.value})
        open_access = await get_collection(COLL_ACCESS_CLEARANCES).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": AccessClearanceStatus.PENDING.value})
        problems = []
        if open_handover:
            problems.append(f"{open_handover} handover task(s) not yet accepted/rejected")
        if open_clearance:
            problems.append(f"{open_clearance} clearance task(s) still pending")
        if open_assets:
            problems.append(f"{open_assets} asset(s) not yet returned or written off")
        if open_access:
            problems.append(f"{open_access} access item(s) not yet disabled")
        if not fnf or fnf.get("status") != FnfStatus.PAID.value:
            problems.append("F&F is not marked Paid")
        if problems:
            raise HTTPException(
                status_code=409,
                detail="Cannot close: " + "; ".join(problems) + ". Pass force to override with a recorded reason.")

    now = datetime.now(timezone.utc)
    final_lwd = sep.get("final_lwd") or sep.get("calculated_lwd")
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.CLOSED.value, "closed_at": now, "updated_at": now}})

    status = (EmploymentStatus.TERMINATED.value
             if sep.get("exit_type") in (ExitType.TERMINATION.value, ExitType.ABSCONDING.value)
             else EmploymentStatus.RESIGNED.value)
    if sep.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        await update_profile(actor, sep["user_id"],
                             {"employment_status": status, "resigned_on": final_lwd}, company_id)
        for coll in USER_COLLECTIONS:
            await get_collection(coll).update_one(
                {"_id": ObjectId(sep["user_id"])}, {"$set": {"is_active": False}})
    elif sep.get("employee_code"):
        # An employee created straight through onboarding (Stage 9) has no login yet, so
        # `update_profile` -- keyed on `user_id` -- has nothing to find and this whole
        # deactivation silently never ran. BR-025 and this function's own docstring say the
        # employee "is deactivated and moved to Resigned/Terminated on close" with no carve-out
        # for one who never got a login; there is no `is_active` flag to clear here, only the
        # employment_status write, but that write is the one this function must not skip.
        await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
            {"company_id": str(company_id), "employee_code": sep["employee_code"]},
            {"$set": {"employment_status": status, "resigned_on": final_lwd,
                      "updated_at": now}})

    # §7.15 BR: "If employee leaves before 12 months, held 25% is not payable." Any
    # variable-pay hold still sitting as Held at closure has, by definition, not already
    # gone through a manual Release (the escape hatch when the 12-month condition was
    # genuinely met) — so it is forfeited here rather than left for someone to remember.
    from app.services.hrms_variable_pay_service import forfeit_holds_for_separation
    await forfeit_holds_for_separation(company_id, sep["employee_code"], sep_no)

    await _archive_to_alumni(company_id, sep, final_lwd)

    await audit(actor, AUDIT_SEPARATION_CLOSED, ENTITY_SEPARATION, sep_no,
               f"LWD {final_lwd}"
               + (f" (forced: {force_reason})" if force else ""), company_id)
    await _notify_exit(company_id, sep, "closed")
    return await get_separation(actor, company_id, sep_no)


async def _archive_to_alumni(company_id: str, sep: dict, final_lwd: str) -> None:
    """Write the alumni record the closure step is supposed to leave behind.

    A leaver previously just had their employment_status flipped and their login switched
    off -- there was no record you could ask "who has left, when, and would we take them
    back". This is that record: a small, deliberate summary rather than a copy of the
    personnel file, because an alumni list is read by people who should not be reading
    somebody's old salary or their exit interview verbatim.

    Best-effort: the exit is already closed, and failing to write the archive must not
    undo that.
    """
    try:
        interview = await get_collection(COLL_EXIT_INTERVIEWS).find_one(
            {"company_id": str(company_id), "sep_no": sep["sep_no"]}) or {}
        profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"company_id": str(company_id),
             "employee_code": sep.get("employee_code")}) or {}
        now = datetime.now(timezone.utc)
        await get_collection(COLL_ALUMNI).update_one(
            {"company_id": str(company_id), "employee_code": sep.get("employee_code")},
            {"$set": {
                "company_id": str(company_id),
                "employee_code": sep.get("employee_code"),
                "employee_name": sep.get("employee_name"),
                "sep_no": sep["sep_no"],
                "exit_type": sep.get("exit_type"),
                "joined_on": profile.get("joined_on"),
                "last_working_day": final_lwd,
                "department_id": profile.get("department_id"),
                "designation_id": profile.get("designation_id"),
                # The one judgement worth carrying forward, and the reason an alumni list
                # is useful at all: would we hire them again.
                "rehire_recommended": interview.get("rehire_recommended"),
                "archived_at": now,
            }},
            upsert=True)
        await audit(None, AUDIT_SEPARATION_CLOSED, ENTITY_SEPARATION, sep["sep_no"],
                    "archived to alumni", company_id)
    except Exception as e:                          # pragma: no cover - defensive
        print(f"[WARN] alumni archive failed for {sep.get('sep_no')}: {e}")


async def list_alumni(actor: dict, company_id: str, *, search: str = None,
                      rehire_only: bool = False, limit: int = 200) -> dict:
    """Former employees, as a list somebody can actually search when rehiring."""
    query = {"company_id": str(company_id)}
    if rehire_only:
        query["rehire_recommended"] = True
    if search:
        term = clean_text(search, limit=80)
        if term:
            safe = re.escape(term)
            query["$or"] = [
                {"employee_name": {"$regex": safe, "$options": "i"}},
                {"employee_code": {"$regex": safe, "$options": "i"}},
            ]
    rows = await get_collection(COLL_ALUMNI).find(query).sort(
        "last_working_day", -1).to_list(min(limit, 500))
    return {"alumni": [_out(r) for r in rows], "total": len(rows)}
