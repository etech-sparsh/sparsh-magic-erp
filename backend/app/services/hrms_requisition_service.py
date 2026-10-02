"""HRMS > hiring requisitions (FMS) + their job descriptions.

The recruitment entry point, and the phase that establishes the approval pattern reused by
assessments, interviews, offers and onboarding.

-- One unified approval chain -------------------------------------------------------
A requisition is raised WITH its JD and the two are approved together:

    raise -> Pending HR Review -> [HR forwards] -> Pending MD Approval -> [MD approves]
             -> Approved   (JD flips to Approved, which is what unlocks Phase 4 posting)

Either stage may reject, which closes the requisition and rejects the JD. The source's
separate JD submit/approve workflow does not exist here -- it is documented as removed and
its route as deprecated-but-still-present (BACKEND_ANALYSIS 5.3, 6.7), so we simply never
build it.

-- Three correctness properties worth stating --------------------------------------
1. **Transitions are table-driven** (models.hrms.INTERNAL_REQ_TRANSITIONS). The guard, the tests and
   the docs read from one source; an action absent from the table cannot happen.
2. **Transitions are compare-and-swap.** The status is part of the update FILTER, so two
   concurrent approvals cannot both succeed -- the loser matches nothing and gets a 409.
   A read-then-write would let both through.
3. **Create is all-or-nothing.** Mongo transactions need a session the rest of this codebase
   never uses, so the JD is written first and deleted again if the requisition insert fails.
   The invariant that matters -- "every requisition has a JD" -- therefore always holds.
   (A transaction would additionally prevent a briefly-orphaned JD; see the Phase 3 report.)
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_JD_UPDATED, AUDIT_REQ_CLOSED, AUDIT_REQ_CREATED, AUDIT_REQ_DELETED,
    AUDIT_REQ_UPDATED, COLL_DEPARTMENTS, COLL_DESIGNATIONS, COLL_JOB_DESCRIPTIONS,
    COLL_REQUISITIONS, ENTITY_JD, ENTITY_REQUISITION, JdStatus, REQ_AUDIT_ACTIONS,
    ReqApproval, ReqClosing, is_iso_date,
)
# ── Phase 11-R additions (Items 4, 6, 7) ──
from app.models.hrms import (
    AUDIT_REQ_ESCALATED, MAX_ESCALATION_LEVELS, REQ_CONDITIONAL_REMARK_REASONS,
    REQ_CONDITIONAL_REMARKS, BudgetStatus, Cap, EscalationStatus,
    RequisitionType, budget_delta, budget_status,
)
# ── Internal (in-house) recruitment track ──
from app.models.hrms import (
    INTERNAL_ESCALATION_ROUTING, INTERNAL_REQ_TRANSITIONS, PRE_BUDGET_STATES,
    REQUISITION_TRACK_INTERNAL,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_access import can
from app.utils.hrms_access import tenant_member

# Statuses in which a requisition's details may still be edited. Once MD has approved it,
# the terms are what the approver signed off on -- changing them afterwards would make the
# approval meaningless.
#
# Phase 11-R adds PENDING_ESCALATION: a requisition still working its way up the reporting
# chain has not been finally approved by anyone, so the same editing logic applies to it.
EDITABLE_STATUSES = {ReqApproval.PENDING_ESCALATION.value,
                     # The pre-approval states: none of them represents a final sign-off by
                     # anybody.
                     ReqApproval.PENDING_HR_VERIFICATION.value,
                     ReqApproval.PENDING_BUDGET.value,
                     ReqApproval.PENDING_SCORECARD.value}


def assert_sourcing_allowed(req: dict) -> None:
    """Refuse any sourcing against an internal requisition that has not cleared its budget.

    SOP §11: "No internal role may be sourced without prior written headcount and budget
    approval from Management/Finance." Sourcing means publishing a posting or putting a
    candidate against the requisition -- both are entry points into the pipeline, so both
    call this.

    It lives HERE, in the service that owns the approval chain, rather than being copied
    into the posting and candidate services. Two copies of a gate is one gate and one bug
    waiting to drift out of step with it, and this particular gate is the SOP's only
    mandatory control.

    """
    status = req.get("approval_status")
    if status in PRE_BUDGET_STATES:
        raise HTTPException(
            status_code=409,
            detail=(f"{req.get('request_no')} has not cleared budget approval yet "
                    f'(it is "{status}"). No internal role may be sourced before '
                    f"Management or Finance has approved the headcount and salary band."))


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    # ── Phase 11-R, Item 6 ── budget_status is DERIVED on every read, never stored, so a
    # corrected figure is reflected immediately and no flag can go stale. Documents written
    # before this phase have neither figure and read "Not Set", which is the truth.
    doc["budget_status"] = budget_status(doc)
    doc["budget_delta"] = budget_delta(doc)
    # Defaults for pre-phase documents, so every consumer sees a consistent shape without
    # each one re-deriving `doc.get("x") or default`.
    doc.setdefault("requisition_type", RequisitionType.NEW_POSITION.value)
    doc.setdefault("escalation_chain", [])
    doc.setdefault("sanction_snapshot", None)
    return doc


# -------------------------------------------------------------
# Validation
# -------------------------------------------------------------
async def _resolve_master(coll_name: str, master_id: str, company_id: str, label: str) -> dict:
    """A master reference must exist AND belong to this company. Being part of the query
    rather than a post-check means a crafted id from another tenant simply finds nothing."""
    doc = await get_collection(coll_name).find_one(
        {"_id": _oid(master_id, label.lower()), "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=422, detail=f"{label} does not exist for this company.")
    return doc


async def _validate_requisition(payload: dict, company_id: str, *, partial: bool) -> dict:
    """Validate and normalise requisition fields. Raises 422 naming the offending field."""
    out = {}

    for field, label in (("experience_required", "Required experience"),
                         ("qualification", "Qualification"),
                         ("essential_skills", "Required skills")):
        if field in payload:
            value = (payload[field] or "").strip()
            if not value and not partial:
                raise HTTPException(status_code=422, detail=f"{label} is required.")
            if not value and partial:
                raise HTTPException(status_code=422, detail=f"{label} cannot be cleared.")
            out[field] = value

    if "vacancy" in payload and payload["vacancy"] is not None:
        try:
            vacancy = int(payload["vacancy"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Vacancy must be a whole number.")
        if vacancy < 1:
            raise HTTPException(status_code=422, detail="Vacancy must be at least 1.")
        if vacancy > 1000:
            raise HTTPException(status_code=422, detail="Vacancy is implausibly large.")
        out["vacancy"] = vacancy

    if "offering_ctc" in payload:
        if payload["offering_ctc"] is None:
            out["offering_ctc"] = None
        else:
            try:
                ctc = float(payload["offering_ctc"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Offered CTC must be a number.")
            if ctc < 0:
                raise HTTPException(status_code=422, detail="Offered CTC cannot be negative.")
            out["offering_ctc"] = ctc

    if "required_date" in payload:
        value = payload["required_date"]
        if not value:
            raise HTTPException(status_code=422, detail="Required-by date is required.")
        if not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="Required-by date must be a valid date in YYYY-MM-DD format.")
        out["required_date"] = value

    for field in ("urgency_level", "work_location", "gender_preferred", "employment_type"):
        if field in payload and payload[field] is not None:
            out[field] = getattr(payload[field], "value", payload[field])

    if "notes" in payload:
        out["notes"] = (payload["notes"] or "").strip() or None

    for field, coll, label in (("department_id", COLL_DEPARTMENTS, "Department"),
                               ("designation_id", COLL_DESIGNATIONS, "Designation")):
        if field in payload and payload[field]:
            master = await _resolve_master(coll, payload[field], company_id, label)
            out[field] = str(payload[field])
            out[f"{field[:-3]}_name"] = master.get("name")

    if "assignee_id" in payload and payload["assignee_id"]:
        assignee = await tenant_member(
            company_id, payload["assignee_id"], {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
        if not assignee:
            raise HTTPException(
                status_code=422, detail="The assignee must be a user of this company.")
        out["assignee_id"] = str(payload["assignee_id"])
        out["assignee_name"] = (assignee.get("full_name")
                                or f"{assignee.get('first_name') or ''} {assignee.get('last_name') or ''}".strip()
                                or assignee.get("email"))

    # ── Internal Recruitment SOP §3 ── "role, reporting line, and business justification",
    # the three things the HOD's own raise is defined by. Reporting line is validated
    # exactly like `assignee_id` above -- a real user of this company -- and is who the NEW
    # HIRE reports to, not who runs the recruitment.
    if "reporting_manager_id" in payload and payload["reporting_manager_id"]:
        manager = await tenant_member(
            company_id, payload["reporting_manager_id"], {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
        if not manager:
            raise HTTPException(
                status_code=422,
                detail="The reporting manager must be a user of this company.")
        out["reporting_manager_id"] = str(payload["reporting_manager_id"])
        out["reporting_manager_name"] = (
            manager.get("full_name")
            or f"{manager.get('first_name') or ''} {manager.get('last_name') or ''}".strip()
            or manager.get("email"))
    elif "reporting_manager_id" in payload:
        out["reporting_manager_id"] = None
        out["reporting_manager_name"] = None

    if "business_justification" in payload:
        # Required by the raise FORM (Internal Recruitment SOP §3), not by this service --
        # an untouched value is simply not recorded, exactly like `notes`. Enforcing it here
        # too would refuse every caller that predates this field, including the ~10 test
        # fixtures that build a requisition as setup for something else entirely.
        out["business_justification"] = (payload["business_justification"] or "").strip() or None

    out.update(_validate_budget(payload))
    out.update(await _validate_replacement(payload, company_id))
    return out


def _validate_budget(payload: dict) -> dict:
    """Item 6 — the two budget figures, their references and their dates.

    Nothing here computes `budget_status`: it is derived on every read (models.budget_status)
    so a later correction can never leave a stale flag behind. This only checks that the
    numbers ARE numbers and the dates ARE dates.
    """
    out = {}
    for field, label in (("budget_sanctioned_amount", "Sanctioned budget"),
                         ("budget_hod_amount", "HOD-approved budget")):
        if field in payload:
            if payload[field] is None:
                out[field] = None
                continue
            try:
                amount = float(payload[field])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{label} must be a number.")
            if amount < 0:
                raise HTTPException(status_code=422, detail=f"{label} cannot be negative.")
            if amount > 1_000_000_000:
                raise HTTPException(status_code=422, detail=f"{label} is implausibly large.")
            out[field] = amount

    for field, label in (("budget_sanctioned_on", "Sanction date"),
                         ("budget_hod_on", "HOD approval date")):
        if field in payload:
            value = payload[field]
            if value and not is_iso_date(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} must be a valid date in YYYY-MM-DD format.")
            out[field] = value or None

    for field, limit in (("budget_sanctioned_by", 60), ("budget_hod_by", 60),
                         ("budget_sanctioned_ref", 200), ("budget_remarks", 2000)):
        if field in payload:
            value = (payload[field] or "")
            out[field] = str(value).strip()[:limit] or None
    return out


async def _validate_replacement(payload: dict, company_id: str) -> dict:
    """Item 7 — replacement vs a genuinely new position.

    A Replacement REQUIRES the person being replaced and a reason. Without both, the
    distinction is a label nobody can act on: "replacement" that names nobody cannot be
    checked against the leaver, and the sanctioned-strength arithmetic depends on knowing
    a seat is being vacated rather than added.
    """
    out = {}
    if "requisition_type" in payload and payload["requisition_type"] is not None:
        value = getattr(payload["requisition_type"], "value", payload["requisition_type"])
        if value not in {t.value for t in RequisitionType}:
            raise HTTPException(
                status_code=422,
                detail=f"Requisition type must be one of: "
                       f"{', '.join(t.value for t in RequisitionType)}.")
        out["requisition_type"] = value

    if "replacement_reason" in payload:
        out["replacement_reason"] = (payload["replacement_reason"] or "").strip()[:2000] or None
    if "last_working_day" in payload:
        value = payload["last_working_day"]
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="Last working day must be a valid date in YYYY-MM-DD format.")
        out["last_working_day"] = value or None

    if "replacement_for_user_id" in payload:
        user_id = payload["replacement_for_user_id"]
        if user_id:
            # Same tenant check the assignee and forward_to_id references get: part of the
            # query, so a user from another company simply is not found.
            person = await tenant_member(company_id, user_id, {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
            if not person:
                raise HTTPException(
                    status_code=422,
                    detail="The person being replaced must be a user of this company.")
            out["replacement_for_user_id"] = str(user_id)
            out["replacement_for_name"] = (
                person.get("full_name")
                or f"{person.get('first_name') or ''} {person.get('last_name') or ''}".strip()
                or person.get("email"))
        else:
            out["replacement_for_user_id"] = None
            out["replacement_for_name"] = None
    elif payload.get("replacement_for_name"):
        out["replacement_for_name"] = str(payload["replacement_for_name"]).strip()[:140]
    return out


def _assert_replacement_complete(merged: dict) -> None:
    """The cross-field rule, checked against the MERGED result.

    Applied after an edit as well as on create, so an update cannot empty out the fields
    that made a Replacement valid when it was raised -- the same discipline _validate_jd
    applies to a JD's mandatory content.
    """
    if merged.get("requisition_type") != RequisitionType.REPLACEMENT.value:
        return
    if not merged.get("replacement_for_user_id") and not merged.get("replacement_for_name"):
        raise HTTPException(
            status_code=422,
            detail="Name the employee being replaced, or switch this to a new position.")
    if not merged.get("replacement_reason"):
        raise HTTPException(
            status_code=422,
            detail="Give the reason for the replacement (resignation, transfer, and so on).")


def _validate_jd(jd: dict, *, partial: bool = False) -> dict:
    """A JD is mandatory content, not a formality.

    The rule -- responsibilities OR at least one attachment -- comes straight from the
    source's own server-side check, and is the one piece of its validation the analysis
    praises as correctly enforced (BACKEND_ANALYSIS 5.2).
    """
    out = {}
    for field in ("title", "responsibilities", "skills", "qualifications",
                  "experience", "ctc", "location", "benefits",
                  "job_summary", "key_competencies", "culture_fit",
                  "additional_requirements"):
        if field in jd:
            out[field] = (jd[field] or "").strip() or None

    if "employment_type" in jd and jd["employment_type"] is not None:
        out["employment_type"] = getattr(jd["employment_type"], "value", jd["employment_type"])

    if "attachments" in jd and jd["attachments"] is not None:
        attachments = jd["attachments"] or []
        if not isinstance(attachments, list):
            raise HTTPException(status_code=422, detail="Attachments must be a list.")
        if len(attachments) > 10:
            raise HTTPException(status_code=422, detail="At most 10 attachments are allowed.")
        cleaned = []
        for a in attachments:
            if not isinstance(a, dict) or not a.get("url"):
                raise HTTPException(
                    status_code=422, detail="Each attachment needs a name and a url.")
            cleaned.append({"name": (a.get("name") or "attachment").strip(),
                            "url": str(a["url"]).strip()})
        out["attachments"] = cleaned

    if not partial:
        if not out.get("responsibilities") and not out.get("attachments"):
            raise HTTPException(
                status_code=422,
                detail="Provide a Job Description - enter responsibilities or attach a JD file.")
    return out


# JD field  <-  requisition field it inherits from when left blank.
#
# The same facts are entered once, on the requisition, and the JD is what a candidate is
# eventually shown. Asking for them twice is how the two drift apart, so the JD inherits
# the requisition's answer at raise time and the JD document is complete AT REST -- which
# is what every reader needs, because only the public advert ever fell back to the
# requisition and the JD library, the requisition drawer and the printable forms all read
# the stored document directly.
#
# `benefits`, `responsibilities` and `attachments` are absent deliberately: they have no
# requisition counterpart and are authored on the JD itself.
JD_FROM_REQUISITION = (
    ("experience",      "experience_required"),
    ("qualifications",  "qualification"),
    ("skills",          "essential_skills"),
    ("location",        "work_location"),
    ("employment_type", "employment_type"),
)


def _jd_ctc_from(requisition: dict) -> Optional[str]:
    """The requisition's numeric CTC as the JD's free-text one.

    Formatted with the module's own money convention (hrms_offer_service._money): grouped
    digits and NO currency symbol, because HRMS never asks which currency a company works
    in and inventing one would be worse than omitting it.
    """
    value = requisition.get("offering_ctc")
    if value is None or value == "":
        return None
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return None


def _seed_jd_from_requisition(jd: dict, requisition: dict) -> dict:
    """Fill the JD's blank fields from the requisition it was raised with.

    Only ever fills a field that is BLANK -- a JD authored with its own wording keeps every
    word of it, so this can never overwrite something a person typed. That is what makes it
    safe to run unconditionally on create.

    Returns a new dict rather than mutating, so the caller's validated JD stays the record
    of what was actually submitted.
    """
    out = dict(jd)
    for jd_field, req_field in JD_FROM_REQUISITION:
        if out.get(jd_field):
            continue
        inherited = requisition.get(req_field)
        if inherited not in (None, ""):
            out[jd_field] = getattr(inherited, "value", inherited)
    if not out.get("ctc"):
        ctc = _jd_ctc_from(requisition)
        if ctc:
            out["ctc"] = ctc
    return out


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
def _visibility_filter(actor: dict) -> dict:
    """Extra clause restricting who sees which requisitions.

    Everyone with `requisition.read` sees their company's requisitions -- hiring is not
    secret WITHIN a tenant, and an employee who raised one must be able to track it. Row
    scoping tightens only for a plain EMPLOYEE, who sees the ones they raised.

    """
    from app.models.hrms import HrmsRole
    from app.utils.hrms_access import hrms_role

    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        return {"created_by": str(actor.get("_id") or "")}
    return {}


async def list_requisitions(actor: dict, company_id: str, *, search: str = None,
                            approval_status: str = None, closing_status: str = None,
                            department_id: str = None,
                            limit: int = 100, skip: int = 0) -> dict:
    # Only Sparsh Magic's own requisitions. Rows from the decommissioned client-hiring
    # track (a stored track of "client", or none at all on the oldest) are not part of
    # hiring any more; they stay in the database and out of every list.
    query = {"company_id": str(company_id), "requisition_track": REQUISITION_TRACK_INTERNAL}
    query.update(_visibility_filter(actor))
    if approval_status:
        query["approval_status"] = approval_status
    if closing_status:
        query["closing_status"] = closing_status
    if department_id:
        query["department_id"] = department_id
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"request_no": {"$regex": safe, "$options": "i"}},
            {"designation_name": {"$regex": safe, "$options": "i"}},
            {"created_by_name": {"$regex": safe, "$options": "i"}},
        ]

    coll = get_collection(COLL_REQUISITIONS)
    total = await coll.count_documents(query)
    limit = max(1, min(int(limit or 100), 200))
    rows = await coll.find(query).sort("created_at", -1).skip(
        max(0, int(skip or 0))).limit(limit).to_list(limit)

    # Stat tiles come from the same scoped query, so the counts always agree with the list.
    base = {"company_id": str(company_id), "requisition_track": REQUISITION_TRACK_INTERNAL,
            **_visibility_filter(actor)}
    stats = {
        "total": total,
        "pending_hr": await coll.count_documents(
            {**base, "approval_status": ReqApproval.PENDING_HR_VERIFICATION.value}),
        "pending_budget": await coll.count_documents(
            {**base, "approval_status": ReqApproval.PENDING_BUDGET.value}),
        "pending_scorecard": await coll.count_documents(
            {**base, "approval_status": ReqApproval.PENDING_SCORECARD.value}),
        "open": await coll.count_documents({**base, "closing_status": ReqClosing.OPEN.value,
                                            "approval_status": ReqApproval.APPROVED.value}),
    }
    return {"requisitions": [_out(r) for r in rows], "total": total,
            "limit": limit, "skip": skip, "stats": stats}


async def get_requisition(actor: dict, company_id: str, request_no: str,
                          *, with_jd: bool = True) -> dict:
    query = {"request_no": request_no, "company_id": str(company_id),
             "requisition_track": REQUISITION_TRACK_INTERNAL}
    query.update(_visibility_filter(actor))
    doc = await get_collection(COLL_REQUISITIONS).find_one(query)
    if not doc:
        # 404 rather than 403 for an out-of-scope row: a 403 would confirm the id exists.
        raise HTTPException(status_code=404, detail="Requisition not found.")

    out = _out(doc)
    if with_jd and doc.get("jd_no"):
        jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one({"jd_no": doc["jd_no"]})
        out["jd"] = _out(jd) if jd else None
    return out


# -------------------------------------------------------------
# Create
# -------------------------------------------------------------
async def create_requisition(actor: dict, company_id: str, payload: dict) -> dict:
    """Raise a requisition and its JD together.

    Deliberately open to ANY authenticated HRMS user: whoever raises a requisition becomes
    its hiring manager and later co-reviews its candidates' assessments. That is the
    source's documented design intent (FRONTEND_ANALYSIS 5), not an oversight.
    """
    jd_payload = payload.get("jd") or {}
    if hasattr(jd_payload, "model_dump"):
        jd_payload = jd_payload.model_dump(exclude_unset=True)
    # ── Internal Recruitment SOP §3 ── the JD is no longer authored by the HOD at raise time
    # -- it is HR's job, once Management/Finance has cleared headcount and budget (see the
    # gate in update_jd). A requisition raised with no `jd` in the payload opens with an
    # empty placeholder JD rather than being forced through the "responsibilities or an
    # attachment" content check below; a caller that DOES supply content (a pre-SOP-redesign
    # form) keeps that check exactly as before.
    jd_was_supplied = bool(jd_payload)

    clean = await _validate_requisition(payload, company_id, partial=False)
    # Assignee (recruiter) is no longer collected at raise time -- removed from every
    # requisition-creation form (the direct raise, and converting an accepted job request).
    # A requisition left unassigned is not a broken one: every downstream reader already
    # treats `assignee_id` as optional (e.g. hrms_posting_service only notifies "if
    # req.get('assignee_id')"), so nothing else needed to change.
    for required in ("department_id", "designation_id", "required_date"):
        if required not in clean:
            label = required.replace("_id", "").replace("_", " ").capitalize()
            raise HTTPException(status_code=422, detail=f"{label} is required.")
    clean.setdefault("vacancy", 1)
    clean.setdefault("requisition_type", RequisitionType.NEW_POSITION.value)
    _assert_replacement_complete(clean)

    jd_clean = _validate_jd(jd_payload, partial=not jd_was_supplied)
    jd_clean.setdefault("title", clean.get("designation_name"))
    # Everything the requisition already knows, carried onto the JD that will be published
    # from it. Runs after both are validated, so it inherits CLEANED values (the resolved
    # enum strings, the checked CTC) rather than whatever arrived on the wire.
    jd_clean = _seed_jd_from_requisition(jd_clean, clean)

    year = datetime.now(timezone.utc).year
    request_no = await next_business_id("requisition", str(company_id), year)
    jd_no = await next_business_id("jd", str(company_id), year)
    now = datetime.now(timezone.utc)

    actor_id = str(actor.get("_id") or "")
    actor_name = (actor.get("full_name")
                  or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
                  or actor.get("email") or "Unknown")

    jd_doc = {
        "jd_no": jd_no, "request_no": request_no, "company_id": str(company_id),
        "status": JdStatus.PENDING_APPROVAL.value, "version": 1,
        "created_by": actor_id, "created_at": now,
        **jd_clean,
    }
    req_doc = {
        "request_no": request_no, "company_id": str(company_id), "jd_no": jd_no,
        "requisition_track": REQUISITION_TRACK_INTERNAL,
        "approval_status": ReqApproval.PENDING_HR_VERIFICATION.value,
        "closing_status": ReqClosing.OPEN.value,
        # ── Internal track ── the budget gate's record. Null until `budget-approve` clears,
        # and read by the posting service, the candidate service and the offer band check.
        "budget_approved_by": None, "budget_approved_by_name": None,
        "budget_approved_at": None, "budget_remarks_approver": None,
        "approved_headcount": None,
        "approved_salary_band_min": None, "approved_salary_band_max": None,
        # SLA actuals, stamped as each milestone happens (SOP §8). Targets are computed from
        # SLA_MILESTONES against these; nothing here is derived in the browser.
        "sla_actuals": {},
        "created_by": actor_id, "created_by_name": actor_name, "created_at": now,
        "hr_reviewed_by": None, "hr_reviewed_at": None, "hr_remarks": None,
        "approved_by": None, "approved_at": None, "md_remarks": None, "salary_change": None,
        # ── Phase 11-R, Item 7 ── the escalation ladder starts empty; it is BUILT when HR
        # forwards an over-sanction requisition, from the reporting chain as it stands then.
        "escalation_chain": [],
        "escalation_level": 0,
        "sanction_snapshot": None,
        **clean,
    }

    # Item 7: evaluate the sanctioned-strength position AT RAISE TIME and store the figures,
    # so the raiser and the first approver see the same numbers. `exclude_self=False`
    # because this requisition does not exist yet and cannot be double-counted.
    from app.services import hrms_sanction_service as sanctions
    try:
        req_doc["sanction_snapshot"] = await sanctions.snapshot_for(
            company_id, req_doc, exclude_self=False)
    except Exception as e:
        # A snapshot is context for the approver, not a precondition for raising. Failing
        # the whole requisition because a headcount count errored would be the wrong trade;
        # the snapshot is re-evaluated at every approval step anyway.
        print(f"[WARN] HRMS sanction snapshot failed for {request_no}: {e}")

    jds = get_collection(COLL_JOB_DESCRIPTIONS)
    await jds.insert_one(dict(jd_doc))
    try:
        await get_collection(COLL_REQUISITIONS).insert_one(dict(req_doc))
    except Exception:
        # Compensating delete: without a transaction this is how we keep the invariant
        # "every requisition has a JD" true. A JD with no requisition is inert; a
        # requisition with no JD would break the approval chain. Scoped by company_id too --
        # `jd_no` is unique only within a company, so another tenant's requisition raised at
        # the same instant could otherwise be deleted by mistake.
        await jds.delete_one({"jd_no": jd_no, "company_id": str(company_id)})
        raise

    await audit(actor, AUDIT_REQ_CREATED, ENTITY_REQUISITION, request_no,
                f"{clean.get('designation_name')} x{clean.get('vacancy', 1)}", company_id)

    # Route to HR -- the requisition is now waiting on them, and nobody watches a queue they
    # were not told about.
    link = f"/hrms/requisitions/{request_no}"
    await notify_hrms_role(
        company_id, ["HR"],
        f"Hiring requisition {request_no} needs review",
        f"{actor_name} raised a requisition for {clean.get('designation_name')} "
        f"({clean.get('vacancy', 1)} vacancy). It is waiting for your review.",
        link=link, email=True)

    # Separation of duties means only an HR user can clear stage 1 -- MD deliberately cannot
    # (see PHASE_3_REPORT 3). If the company has designated no HR user, the requisition would
    # otherwise sit at "Pending HR Review" indefinitely with nobody notified and no visible
    # cause. Surface it immediately to the people who can fix it, rather than letting it
    # become a mystery a week later.
    if not await _has_hr_reviewer(company_id):
        await notify_hrms_role(
            company_id, ["MD"],
            f"No HR reviewer for requisition {request_no}",
            (f"{actor_name} raised a requisition for {clean.get('designation_name')}, but this "
             f"company has no user with the HR role, so it cannot be reviewed. Assign the HR "
             f"governance role to someone to unblock it."),
            kind="warning", link=link, email=True)
        await notify_user(
            actor_id, f"Requisition {request_no} raised - but no HR reviewer exists",
            ("Your requisition was created, but this company has no HR user to review it. "
             "Your MD has been notified."),
            kind="warning", link=link)

    # ── Phase 11-R, Item 6 ── budget mismatch / pending notifications.
    await _notify_budget_state(actor, company_id, request_no, req_doc, actor_id)

    # ── Phase 11-R, Item 7 ── warn the raiser and the MD when the position is
    # over-sanction, at raise time rather than at approval. Being told after HR has already
    # reviewed it is being told too late to reconsider.
    snapshot = req_doc.get("sanction_snapshot") or {}
    if snapshot.get("is_over_sanction"):
        figures = _sanction_sentence(snapshot)
        await notify_user(
            actor_id, f"Requisition {request_no} exceeds the sanctioned strength",
            (f"{figures} This requisition will be routed for escalation, and MD approval "
             f"remains mandatory."),
            kind="warning", link=link)
        await notify_hrms_role(
            company_id, ["MD"],
            f"Over-sanction requisition raised: {request_no}",
            f"{actor_name} raised a requisition for {clean.get('designation_name')}. "
            f"{figures}",
            kind="warning", link=link)

    return await get_requisition(actor, company_id, request_no)


def _sanction_sentence(snapshot: dict) -> str:
    """One plain-language sentence of the sanction figures, for a notification body.

    A notification that says only "over sanction" makes the reader open the screen to learn
    anything. The numbers travel with the message.
    """
    snapshot = snapshot or {}
    if snapshot.get("sanctioned") is None:
        return ("No sanctioned strength has been set for this department and designation, "
                "so the headcount is unauthorised.")
    return (f"Sanctioned {snapshot.get('sanctioned')}, currently filled "
            f"{snapshot.get('actual')}, already committed by open requisitions "
            f"{snapshot.get('open_requisitions')}, this request "
            f"{snapshot.get('requested')}.")


async def _notify_budget_state(actor, company_id: str, request_no: str, req: dict,
                               creator_id: str = None) -> None:
    """Item 6 — fire the budget notifications. Fire-and-forget, never raises.

    Two triggers, both derived from `budget_status` rather than from a stored flag:

      Mismatch -> HR, MD and the creator, WITH both figures and the delta in the body, so
                  the reader can act without opening the screen.
      Pending  -> the department head, because exactly one side has answered and the other
                  is the one holding it up.
    """
    try:
        state = budget_status(req)
        link = f"/hrms/requisitions/{request_no}"
        designation = req.get("designation_name") or "the role"

        if state == BudgetStatus.MISMATCH.value:
            delta = budget_delta(req)
            body = (
                f"The budgets recorded for {designation} ({request_no}) do not agree. "
                f"Management sanctioned {req.get('budget_sanctioned_amount')}, the HOD "
                f"approved {req.get('budget_hod_amount')}"
                + (f", a difference of {delta:+,.0f}." if delta is not None else "."))
            await notify_hrms_role(company_id, ["HR", "MD"],
                                   f"Budget mismatch on requisition {request_no}",
                                   body, kind="warning", link=link)
            if creator_id:
                await notify_user(creator_id,
                                  f"Budget mismatch on requisition {request_no}",
                                  body, kind="warning", link=link)

        elif state == BudgetStatus.PENDING.value:
            # Only one figure is in. Route to whoever owes the other one -- the department
            # head when the HOD approval is missing, HR otherwise.
            awaiting_hod = req.get("budget_hod_amount") is None
            body = (f"The {'HOD' if awaiting_hod else 'management'} budget for {designation} "
                    f"({request_no}) has not been recorded yet.")
            head_id = await _department_head(company_id, req.get("department_id"))
            if awaiting_hod and head_id:
                await notify_user(head_id,
                                  f"Budget approval outstanding on {request_no}",
                                  body, kind="warning", link=link)
            else:
                await notify_hrms_role(company_id, ["HR"],
                                       f"Budget approval outstanding on {request_no}",
                                       body, kind="warning", link=link)
    except Exception as e:
        print(f"[WARN] HRMS budget notification failed ({request_no}): {e}")


async def _department_head(company_id: str, department_id: str):
    """The HOD for a department, or None. Reads the Phase 2 master rather than guessing."""
    if not department_id:
        return None
    try:
        dept = await get_collection(COLL_DEPARTMENTS).find_one(
            {"_id": _oid(department_id, "department"), "company_id": str(company_id)},
            {"head_user_id": 1})
        return (dept or {}).get("head_user_id")
    except Exception:
        return None


async def _has_hr_reviewer(company_id: str) -> bool:
    """Whether the company has anyone who can clear the HR review stage.

    Checked explicitly rather than inferred from the notification result, so it stays
    correct regardless of how notifications are delivered or mocked.
    """
    doc = await get_collection("learners").find_one(
        {"company_id": str(company_id), "governance_role": "HR", "is_active": {"$ne": False}},
        {"_id": 1})
    return doc is not None


# -------------------------------------------------------------
# Update / delete
# -------------------------------------------------------------
async def update_requisition(actor: dict, company_id: str, request_no: str,
                             payload: dict) -> dict:
    current = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Requisition not found.")

    if current["approval_status"] not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(f'Requisition {request_no} is "{current["approval_status"]}" and can no '
                    f"longer be edited."))

    clean = await _validate_requisition(payload, company_id, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # Cross-field rules are checked against the MERGED document, so an edit cannot empty out
    # what made the requisition valid when it was raised.
    merged = {**current, **clean}
    _assert_replacement_complete(merged)

    # Re-evaluate the sanction snapshot whenever anything that feeds it changes. Headcount
    # and the position both move; a snapshot left over from raise time would show the
    # approver a world that no longer exists.
    if {"department_id", "designation_id", "vacancy"} & set(clean):
        from app.services import hrms_sanction_service as sanctions
        try:
            clean["sanction_snapshot"] = await sanctions.snapshot_for(company_id, merged)
        except Exception as e:
            print(f"[WARN] HRMS sanction re-snapshot failed for {request_no}: {e}")

    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_REQUISITIONS).update_one(
        {"request_no": request_no, "company_id": str(company_id)}, {"$set": clean})
    await audit(actor, AUDIT_REQ_UPDATED, ENTITY_REQUISITION, request_no,
                ", ".join(sorted(k for k in clean if k != "updated_at")), company_id)

    # Item 6: a budget edit can CREATE a mismatch, so the notification fires on update as
    # well as on create — the correction is exactly the moment people need to know.
    if any(k.startswith("budget_") for k in clean):
        await _notify_budget_state(actor, company_id, request_no, merged,
                                   current.get("created_by"))

    return await get_requisition(actor, company_id, request_no)


async def delete_requisition(actor: dict, company_id: str, request_no: str) -> dict:
    """Delete a requisition and cascade to its JD.

    Mongo has no foreign keys, so the cascade is explicit. The source left orphans behind
    on every delete (BACKEND_ANALYSIS Risk #4); here the pair is removed together.
    """
    current = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    if current["approval_status"] == ReqApproval.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=("An approved requisition cannot be deleted. Set its status to Cancel or "
                    "Closed instead, so the hiring record is preserved."))

    await get_collection(COLL_REQUISITIONS).delete_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if current.get("jd_no"):
        # Scoped by company_id for the same reason update_jd's write is: `jd_no` is unique
        # only within a company, so this could otherwise delete another tenant's JD.
        await get_collection(COLL_JOB_DESCRIPTIONS).delete_one(
            {"jd_no": current["jd_no"], "company_id": str(company_id)})

    await audit(actor, AUDIT_REQ_DELETED, ENTITY_REQUISITION, request_no,
                current.get("designation_name"), company_id)
    return {"deleted": True, "request_no": request_no}


# -------------------------------------------------------------
# The approval chain
# -------------------------------------------------------------
async def act_on_requisition(actor: dict, company_id: str, request_no: str,
                             action: str, remarks: str = None,
                             salary_change: float = None,
                             budget: dict = None) -> dict:
    """Drive one transition of the approval state machine.

    Every rule is read from the transition table for the requisition's TRACK, and the write
    is a compare-and-swap on the current status, so concurrent approvals cannot both land.

    `budget` carries the approved headcount and salary band, and is required by (and only
    by) `budget-approve`.
    """
    coll = get_collection(COLL_REQUISITIONS)
    current = await coll.find_one({"request_no": request_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Requisition not found.")

    # A legacy client-track row is not part of hiring any more: it cannot be advanced.
    if current.get("requisition_track") != REQUISITION_TRACK_INTERNAL:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    transitions, escalation_routing = INTERNAL_REQ_TRANSITIONS, INTERNAL_ESCALATION_ROUTING

    if action not in transitions:
        raise HTTPException(
            status_code=422,
            detail=(f"Invalid action. Expected one of: "
                    f"{', '.join(transitions)}."))

    required_status, next_status, capability, remark_required = transitions[action]

    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=("You are not authorised to perform this approval step. HR verifies, "
                    "Management or Finance approves the budget, and the hiring manager "
                    "approves the scorecard."))

    remarks = (remarks or "").strip()
    if remark_required and not remarks:
        raise HTTPException(status_code=422, detail="A remark is required when rejecting.")

    if current["approval_status"] != required_status.value:
        raise HTTPException(
            status_code=409,
            detail=(f'Requisition {request_no} is "{current["approval_status"]}", '
                    f'not "{required_status.value}".'))

    # ── Phase 11-R, Item 6 ── the CONDITIONAL remark rule, read from the one table that
    # declares it. A budget mismatch does not block MD approval (that is a business call,
    # not a system one) but it does demand the approver say why -- an unexplained approval
    # over a known disagreement is exactly the record an audit later needs.
    predicate = REQ_CONDITIONAL_REMARKS.get(action)
    if predicate and predicate(current) and not remarks:
        raise HTTPException(
            status_code=422,
            detail=REQ_CONDITIONAL_REMARK_REASONS.get(action, "A remark is required."))

    now = datetime.now(timezone.utc)
    actor_id = str(actor.get("_id") or "")
    actor_name = (actor.get("full_name")
                  or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
                  or actor.get("email") or "Unknown")

    # ── Phase 11-R, Item 7 ── the over-sanction detour.
    #
    # The transition table still decides what is LEGAL. This decides, for one action, which
    # of two legal destinations it lands on -- and it only ever applies to `budget-approve`,
    # read from INTERNAL_ESCALATION_ROUTING rather than branched on inline, so the rule
    # lives beside the table it modifies. An IN-SANCTION requisition never enters this block.
    # ── Internal track ── the budget gate's payload.
    #
    # Validated BEFORE the state is written, so a malformed band cannot leave a requisition
    # marked approved with nothing to validate a later offer against. The figures are
    # mandatory precisely because the gate exists to record that a number was authorised.
    budget_updates = {}
    if action == "budget-approve":
        payload = budget or {}
        try:
            headcount = int(payload.get("approved_headcount"))
            band_min = float(payload.get("approved_salary_band_min"))
            band_max = float(payload.get("approved_salary_band_max"))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail=("Record the approved headcount and salary band. The band is what "
                        "every later offer on this requisition is checked against."))
        if headcount < 1:
            raise HTTPException(
                status_code=422, detail="Approved headcount must be at least 1.")
        if band_min < 0 or band_max < 0:
            raise HTTPException(
                status_code=422, detail="A salary band cannot be negative.")
        if band_min > band_max:
            raise HTTPException(
                status_code=422,
                detail="The minimum of the salary band cannot exceed its maximum.")
        # ── Phase INT-2 (Annexure C) ── where the figures came from.
        #
        # The standing band master is a CONVENIENCE, never an authority: it pre-fills the
        # approval form, and the offer check still reads the band stamped here rather than
        # the master. That separation is what stops a band edited in April retroactively
        # legalising an offer approved in March.
        #
        # An approver may still type something else -- Finance's standing band cannot know
        # about a scarce skill or a counter-offer. What is insisted on is that the deviation
        # is visible and explained: an override with no reason is indistinguishable from a
        # typo, and "why is this role's band non-standard" is the first thing an audit asks.
        from app.services import hrms_salary_band_service as bands
        prefill = await bands.prefill_for_requisition(company_id, current)
        decision = bands.resolve_band_decision(prefill, payload)
        if decision.get("override_reason_required") and not remarks:
            raise HTTPException(
                status_code=422,
                detail=(f"This band differs from the standing band for the role "
                        f'({decision.get("standing_min"):,.0f}-'
                        f'{decision.get("standing_max"):,.0f}). Record why, so the '
                        f"deviation is on the record rather than in somebody's memory."))

        budget_updates = {
            "approved_headcount": headcount,
            "approved_salary_band_min": band_min,
            "approved_salary_band_max": band_max,
            "budget_remarks_approver": remarks or None,
            "band_source": decision["band_source"],
            # The master row this was taken from (or deviated from), so the two are
            # traceable to each other without guessing from the numbers.
            "band_master_no": decision.get("band_no"),
        }

    # ── Internal track ── the scorecard gate is only real if a scorecard actually exists and
    # has been approved. Without this the requisition could reach Approved while the bar it
    # hires against was still a draft somebody meant to finish.
    if action == "scorecard-approve":
        from app.services.hrms_scorecard_service import assert_scorecard_approved
        await assert_scorecard_approved(company_id, request_no)

    escalation_updates = {}
    if action in escalation_routing:
        from app.services import hrms_sanction_service as sanctions
        try:
            snapshot = await sanctions.snapshot_for(company_id, current)
        except Exception as e:
            # Fail CLOSED on an evaluation error: treat it as needing escalation rather
            # than waving through a headcount nobody could verify.
            print(f"[WARN] HRMS sanction re-check failed for {request_no}: {e}")
            snapshot = {"is_over_sanction": True, "sanctioned": None, "actual": 0,
                        "open_requisitions": 0, "requested": current.get("vacancy") or 1,
                        "evaluated_at": now}
        escalation_updates["sanction_snapshot"] = snapshot

        if snapshot.get("is_over_sanction"):
            chain = await _build_escalation_chain(actor, company_id, current)
            if chain:
                next_status = escalation_routing[action]
                escalation_updates["escalation_chain"] = chain
                escalation_updates["escalation_level"] = 1
            else:
                # An orphaned raiser -- nobody above them resolves. Fail CLOSED by routing
                # STRAIGHT TO MD rather than auto-approving, and record why, so the gap in
                # the reporting data is visible instead of silently skipping a control.
                escalation_updates["escalation_chain"] = []
                escalation_updates["escalation_note"] = (
                    "Over-sanction, but no reporting chain could be resolved for the "
                    "raiser. Routed directly to MD.")
                await audit(actor, AUDIT_REQ_ESCALATED, ENTITY_REQUISITION, request_no,
                            escalation_updates["escalation_note"], company_id)

    # ── Item 7 ── an escalation step advances the LADDER, not the status, until the last
    # rung has acted. The transition table declares where the ladder ultimately leads
    # (PENDING_SCORECARD); this decides whether we are there yet.
    if action == "escalate-approve":
        chain = list(current.get("escalation_chain") or [])
        level = int(current.get("escalation_level") or 1)
        idx = level - 1
        if 0 <= idx < len(chain):
            actor_is_rung = str(chain[idx].get("user_id") or "") == actor_id
            # An MD may clear any rung -- they hold REQUISITION_ESCALATE precisely so a
            # ladder cannot stall on an absent approver. Anyone else must be THIS rung.
            if not actor_is_rung and not can(actor, Cap.REQUISITION_APPROVE_MD):
                raise HTTPException(
                    status_code=403,
                    detail=(f"This requisition is with {chain[idx].get('name')} at "
                            f"escalation level {level}. Only they, or the MD, can clear it."))
            chain[idx].update({"status": EscalationStatus.APPROVED.value,
                               "acted_at": now, "acted_by": actor_id,
                               "remarks": remarks or None})
        escalation_updates["escalation_chain"] = chain
        if level < len(chain):
            # Rungs remain: stay in escalation and move up one.
            next_status = ReqApproval.PENDING_ESCALATION
            escalation_updates["escalation_level"] = level + 1
        else:
            escalation_updates["escalation_level"] = len(chain)

    if action == "escalate-reject":
        chain = list(current.get("escalation_chain") or [])
        idx = int(current.get("escalation_level") or 1) - 1
        if 0 <= idx < len(chain):
            chain[idx].update({"status": EscalationStatus.REJECTED.value,
                               "acted_at": now, "acted_by": actor_id,
                               "remarks": remarks or None})
        escalation_updates["escalation_chain"] = chain

    updates = {"approval_status": next_status.value, "updated_at": now}
    updates.update(escalation_updates)
    updates.update(budget_updates)
    if action.startswith("hr-"):
        updates.update({"hr_reviewed_by": actor_id, "hr_reviewed_by_name": actor_name,
                        "hr_reviewed_at": now, "hr_remarks": remarks or None})
    elif action.startswith("escalate-"):
        updates.update({"escalation_last_actor": actor_id,
                        "escalation_last_actor_name": actor_name,
                        "escalation_last_acted_at": now})
    elif action.startswith("budget-"):
        # ── Internal track ── who committed the company's money, and when. Recorded on the
        # REJECT path too: "Finance declined this on the 4th" is as much a fact the audit
        # needs as an approval is.
        updates.update({"budget_approved_by": actor_id,
                        "budget_approved_by_name": actor_name,
                        "budget_approved_at": now})
        if action == "budget-approve":
            # SLA §8 milestone 1. Stamped here, at the moment it happened, rather than
            # inferred later from the audit trail -- deriving a metric from prose written
            # for a human is what the module already refuses to do for time-to-hire.
            updates["sla_actuals.budget_approved"] = now
    elif action.startswith("scorecard-"):
        updates.update({"scorecard_approved_by": actor_id,
                        "scorecard_approved_by_name": actor_name,
                        "scorecard_approved_at": now,
                        "scorecard_remarks": remarks or None})
        if action == "scorecard-approve":
            updates["sla_actuals.scorecard_approved"] = now
    else:
        updates.update({"approved_by": actor_id, "approved_by_name": actor_name,
                        "approved_at": now, "md_remarks": remarks or None})
        if action == "md-approve" and salary_change is not None:
            try:
                revised = float(salary_change)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Revised CTC must be a number.")
            if revised < 0:
                raise HTTPException(status_code=422, detail="Revised CTC cannot be negative.")
            updates["salary_change"] = revised
            updates["offering_ctc"] = revised

    if next_status == ReqApproval.REJECTED:
        updates["closing_status"] = ReqClosing.CLOSED.value

    # Compare-and-swap: the expected status is part of the FILTER. If another approver moved
    # this requisition since we read it, matched_count is 0 and we refuse rather than
    # silently overwriting their decision.
    result = await coll.update_one(
        {"request_no": request_no, "company_id": str(company_id),
         "approval_status": required_status.value},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This requisition was updated by someone else. Reload and try again.")

    # The JD is co-approved, which is what unlocks posting in Phase 4.
    if current.get("jd_no"):
        jd_status = (JdStatus.APPROVED.value if next_status == ReqApproval.APPROVED
                     else JdStatus.REJECTED.value if next_status == ReqApproval.REJECTED
                     else None)
        if jd_status:
            jd_updates = {"status": jd_status, "updated_at": now}
            if jd_status == JdStatus.APPROVED.value:
                jd_updates.update({"approved_by": actor_id, "approved_at": now})
            else:
                jd_updates["md_remarks"] = remarks or None
            # Scoped by company_id too -- `jd_no` is unique only within a company (see
            # update_jd's own note), so this could otherwise flip another tenant's JD.
            await get_collection(COLL_JOB_DESCRIPTIONS).update_one(
                {"jd_no": current["jd_no"], "company_id": str(company_id)},
                {"$set": jd_updates})

    await audit(actor, REQ_AUDIT_ACTIONS[action], ENTITY_REQUISITION, request_no,
                remarks or None, company_id)
    await _notify_transition(action, current, request_no, actor_name, remarks, company_id)

    # ── Phase 11-R, Item 7 ── when the requisition is sitting in the ladder, tell the rung
    # that now holds it. Read from the UPDATES rather than from `current`, because the level
    # we just advanced to is the one that matters.
    if updates.get("approval_status") == ReqApproval.PENDING_ESCALATION.value:
        await audit(actor, AUDIT_REQ_ESCALATED, ENTITY_REQUISITION, request_no,
                    f"level {updates.get('escalation_level')}", company_id)
        await _notify_escalation(
            current, request_no,
            updates.get("escalation_chain") or current.get("escalation_chain") or [],
            updates.get("escalation_level") or 1, company_id,
            updates.get("sanction_snapshot") or current.get("sanction_snapshot") or {})
    elif (action == "escalate-approve"
          and updates.get("approval_status") == ReqApproval.PENDING_SCORECARD.value):
        # The ladder is exhausted. The scorecard gate is next, and it is NOT optional -- the
        # transition table makes APPROVED reachable only from there
        # (models.budget_approval_is_mandatory).
        await notify_hrms_role(
            company_id, ["HR"],
            f"Over-sanction requisition {request_no} cleared escalation",
            f"The escalation chain for {current.get('designation_name') or 'this role'} is "
            f"complete; the position scorecard is the next gate. "
            f"{_sanction_sentence(current.get('sanction_snapshot') or {})}",
            kind="warning", link=f"/hrms/requisitions/{request_no}", email=True)

    return await get_requisition(actor, company_id, request_no)


async def _build_escalation_chain(actor: dict, company_id: str, req: dict) -> list:
    """Build the approval ladder for an over-sanction requisition.

    REUSES the existing hierarchy resolver (`hrms_employee_service.get_hierarchy`, behind
    GET /hrms/employees/{user_id}/hierarchy) rather than walking `reporting_manager` again
    here. A second walk would be a second set of depth caps and cycle guards to keep in
    step with the first, and the one that drifts is the one that loops forever.

    Three properties:
      * the RAISER is never a rung on their own ladder,
      * the chain is de-duplicated (a shared manager appears once),
      * it is capped at MAX_ESCALATION_LEVELS.

    Returns [] when nobody resolves. The caller treats that as "route straight to MD" — it
    must never be read as "approved".
    """
    raiser_id = str(req.get("created_by") or "")
    if not raiser_id:
        return []

    try:
        from app.services import hrms_employee_service as employees
        hierarchy = await employees.get_hierarchy(actor, raiser_id, company_id)
    except Exception as e:
        print(f"[WARN] HRMS escalation chain resolution failed: {e}")
        return []

    # `manager_chain` is the resolver's upward walk, already depth-capped and cycle-guarded.
    # A cycle is reported as a sentinel entry carrying `circular: True` and no real user;
    # it is skipped here rather than becoming an approver nobody can be.
    upward = (hierarchy or {}).get("manager_chain") or []

    chain, seen = [], {raiser_id}
    for person in upward:
        if len(chain) >= MAX_ESCALATION_LEVELS:
            break
        if (person or {}).get("circular"):
            break
        uid = str((person or {}).get("user_id") or "")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        chain.append({
            "level": len(chain) + 1,
            "user_id": uid,
            "name": person.get("name") or person.get("email") or "Manager",
            "role": person.get("governance_role") or "Manager",
            "status": EscalationStatus.PENDING.value,
            "acted_at": None,
            "acted_by": None,
            "remarks": None,
        })
    return chain


async def _notify_escalation(current, request_no, chain, level, company_id, snapshot):
    """Tell the rung that is now holding the requisition. Fire-and-forget."""
    try:
        idx = int(level or 1) - 1
        if not chain or not (0 <= idx < len(chain)):
            return
        rung = chain[idx]
        link = f"/hrms/requisitions/{request_no}"
        await notify_user(
            rung.get("user_id"),
            f"Requisition {request_no} needs your escalation approval",
            (f"{current.get('designation_name') or 'A role'} exceeds the sanctioned "
             f"strength. {_sanction_sentence(snapshot)} You are level {rung.get('level')} "
             f"of {len(chain)} in the approval chain; MD approval is still required after."),
            kind="warning", link=link, email=True)
    except Exception as e:
        print(f"[WARN] HRMS escalation notification failed ({request_no}): {e}")


async def _notify_transition(action, current, request_no, actor_name, remarks, company_id):
    """Tell whoever is now waiting.

    The source sent nothing on several of these steps, so a requisition could sit unseen in
    a queue. Every transition here notifies the next actor or the creator.
    """
    designation = current.get("designation_name") or "the role"
    creator = current.get("created_by")
    link = f"/hrms/requisitions/{request_no}"

    if action == "escalate-approve":
        # Every hop tells the raiser their requisition moved. The NEXT rung is notified by
        # act_on_requisition, which knows the level the ladder actually advanced to.
        if creator:
            await notify_user(
                creator, f"Requisition {request_no} cleared an escalation step",
                f"{actor_name} approved the escalation for {designation}.", link=link)
    elif action == "escalate-reject":
        if creator:
            await notify_user(
                creator, f"Requisition {request_no} rejected at escalation",
                f"Your requisition for {designation} was rejected during escalation "
                f"review. Reason: {remarks}", kind="warning", link=link, email=True)
        await notify_hrms_role(
            company_id, ["HR"], f"Requisition {request_no} rejected at escalation",
            f"{actor_name} rejected {designation} during the over-sanction review.",
            kind="warning", link=link)
    # Each gate tells the party that now holds the requisition. Without this a requisition
    # would sit silently at the budget gate, which is exactly the "sat unseen in a queue"
    # failure this function exists to prevent.
    elif action == "hr-verify":
        await notify_hrms_role(
            company_id, ["MD", "FINANCE"],
            f"Requisition {request_no} awaits budget approval",
            f"{actor_name} (HR) verified the internal requisition for {designation}. "
            f"No sourcing may begin until the headcount and budget are approved.",
            link=link, email=True)
    elif action == "budget-approve":
        await notify_hrms_role(
            company_id, ["HR"], f"Requisition {request_no} has budget approval",
            f"{actor_name} approved the headcount and salary band for {designation}. "
            f"The position scorecard is the next gate.", kind="success", link=link)
        if creator:
            await notify_user(creator, f"Requisition {request_no} is funded",
                              f"Headcount and budget approved for {designation}.",
                              kind="success", link=link)
    elif action == "scorecard-approve":
        if creator:
            await notify_user(creator, f"Requisition {request_no} approved",
                              f"The scorecard for {designation} is approved - sourcing is "
                              f"now enabled.", kind="success", link=link, email=True)
        await notify_hrms_role(
            company_id, ["HR"], f"Requisition {request_no} approved",
            f"{designation} is approved and ready to source.", kind="success", link=link)
    else:
        stage = ("HR review" if action == "hr-reject"
                 else "budget approval" if action == "budget-reject"
                 else "scorecard approval" if action == "scorecard-reject"
                 else "approval")
        if creator:
            await notify_user(creator, f"Requisition {request_no} rejected",
                              f"Your requisition for {designation} was rejected at {stage}. "
                              f"Reason: {remarks}", kind="warning", link=link, email=True)


async def close_requisition(actor: dict, company_id: str, request_no: str,
                            status: str) -> dict:
    """Set the closing status (Open/Hired/Closed/Hold/Cancel).

    Separate from the approval chain: approval decides whether to hire, closing status
    tracks what happened to the hiring effort.
    """
    value = getattr(status, "value", status)
    if value not in {s.value for s in ReqClosing}:
        raise HTTPException(
            status_code=422,
            detail=f"Status must be one of: {', '.join(s.value for s in ReqClosing)}.")

    now = datetime.now(timezone.utc)
    updates = {"closing_status": value, "updated_at": now}
    # SOP §13: "requisition and budget approval -- 3 years from requisition closure". The
    # anchor is the CLOSURE, so the floor can only be computed here, and only when the
    # requisition is actually leaving the Open state. Re-opening one clears it again, so a
    # requisition back in the market is not carrying a disposal date from a previous life.
    if value == ReqClosing.OPEN.value:
        updates["retention_until"] = None
        updates["closed_at"] = None
    else:
        from app.services.hrms_candidate_service import _add_years
        from app.services.hrms_config_service import retention_years_for
        updates["retention_until"] = _add_years(
            now.strftime("%Y-%m-%d"),
            await retention_years_for(company_id, "requisition"))
        updates.setdefault("closed_at", now)

    result = await get_collection(COLL_REQUISITIONS).update_one(
        {"request_no": request_no, "company_id": str(company_id)},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Requisition not found.")

    await audit(actor, AUDIT_REQ_CLOSED, ENTITY_REQUISITION, request_no, value, company_id)
    return await get_requisition(actor, company_id, request_no)


# -------------------------------------------------------------
# Job descriptions
# -------------------------------------------------------------
async def list_jds(actor: dict, company_id: str, *, status: str = None,
                   search: str = None, limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [{"jd_no": {"$regex": safe, "$options": "i"}},
                        {"title": {"$regex": safe, "$options": "i"}}]
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_JOB_DESCRIPTIONS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return {"job_descriptions": [_out(r) for r in rows], "total": len(rows)}


async def get_jd(actor: dict, company_id: str, jd_no: str) -> dict:
    doc = await get_collection(COLL_JOB_DESCRIPTIONS).find_one(
        {"jd_no": jd_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Job description not found.")
    return _out(doc)


async def update_jd(actor: dict, company_id: str, jd_no: str, payload: dict) -> dict:
    """Edit JD content.

    An Approved JD is frozen: it is what the MD signed off on and what candidates will be
    shown. Rejected and pending JDs stay editable so they can be corrected and re-raised.
    """
    coll = get_collection(COLL_JOB_DESCRIPTIONS)
    current = await coll.find_one({"jd_no": jd_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Job description not found.")
    if current.get("status") == JdStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=("An approved job description cannot be edited - it is what the MD "
                    "approved. Raise a new requisition to hire on different terms."))

    # ── Internal Recruitment SOP §3 ── Step 3 (Job Description / Position Scorecard) starts
    # only once Management/Finance has cleared headcount and budget -- writing JD content
    # any earlier would have HR describing a role nobody has funded yet.
    requisition = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": current.get("request_no"), "company_id": str(company_id)},
        {"approval_status": 1})
    if requisition and requisition.get("approval_status") in PRE_BUDGET_STATES:
        raise HTTPException(
            status_code=409,
            detail=("The Job Description cannot be written until Management or Finance has "
                    "approved headcount and budget for this requisition."))

    clean = _validate_jd(payload, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # Re-check the mandatory-content rule against the MERGED result, so an edit cannot empty
    # out a JD that was valid when it was raised.
    merged_resp = clean.get("responsibilities", current.get("responsibilities"))
    merged_att = clean.get("attachments", current.get("attachments") or [])
    if not merged_resp and not merged_att:
        raise HTTPException(
            status_code=422,
            detail="A job description needs responsibilities or at least one attachment.")

    clean["updated_at"] = datetime.now(timezone.utc)
    clean["version"] = int(current.get("version") or 1) + 1
    # `jd_no` is unique only WITHIN a company (the counter is scoped by company_id, not
    # globally) -- two tenants can legitimately mint the same business id. Filtering by
    # `jd_no` alone here would let one company's edit silently land on another's document
    # whenever their numbers happen to coincide, exactly as `find_one` above already scopes
    # its own lookup by `company_id` too.
    await coll.update_one({"jd_no": jd_no, "company_id": str(company_id)}, {"$set": clean})
    await audit(actor, AUDIT_JD_UPDATED, ENTITY_JD, jd_no,
                ", ".join(sorted(k for k in clean if k not in ("updated_at", "version"))),
                company_id)
    return await get_jd(actor, company_id, jd_no)
