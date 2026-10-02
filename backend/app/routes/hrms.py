"""
HRMS ▸ authenticated API routes.

Mounted under /api/hrms.

  GET /hrms/health   module status + the caller's resolved role and capability set
  GET /hrms/audit    audit trail (capability-gated; the filterable Phase 15 API builds here)

Router-wide guard: `_hrms_company_gate` refuses a client-side user whose company has HRMS
switched off, on EVERY endpoint — so the module cannot be reached by typing a URL. Internal
staff pass; the data layer (hrms_access.hrms_enabled_company_ids) hides disabled companies
from what they see instead. This mirrors routes/tpms.py exactly.

Phase 1 ships the foundation only. Later phases add their routers/endpoints here.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.controllers.auth_controller import get_current_user
from app.models.hrms import (
    DEFAULT_REPORT_PAGE_SIZE, MAX_REPORT_PAGE_SIZE,
    BreakdownBy, ExportFormat, ReportEntity,
    Cap, DepartmentIn, DepartmentUpdate, DesignationIn, DesignationUpdate,
    EmployeeLinkIn, EmployeeProfileIn, EmployeeProfileUpdate, HrmsHealthResponse,
    OnboardingBgIn, OnboardingChecklistIn, OnboardingDetailsIn, OnboardingDocReviewIn,
    OnboardingJoiningIn,
    OnboardingDocumentsIn,
    OnboardingIn,
    AssessmentIn, AssessmentReviewIn, CandidateIn, CandidateUpdate, CvScreeningIn,
    InterviewEvaluateIn, InterviewIn, InterviewUpdate,
    OfferIn, OfferRevokeIn, OfferSendIn, OfferUpdate,
    JobDescriptionUpdate, PostingExecApprovalIn, PostingIn, PostingUpdate,
    RequisitionAction, RequisitionClose, RequisitionIn, RequisitionUpdate, ScreenIn,
)
# ── Phase 11-R — recruitment review enhancements ──
from app.models.hrms import (
    AppointmentCancelIn, AppointmentIn, AppointmentSendIn, AppointmentUpdate,
    ScorecardApproveIn, ScorecardEvaluateIn, ScorecardIn, ScorecardUpdate,
    ReferenceCheckIn, ReferenceCheckUpdate, OfferApproveIn,
    TelephonicScreeningIn, TelephonicScreeningUpdate, NegotiationRoundIn,
    ConfigUpdateIn, ConfigResetIn, HolidayIn, HolidayImportIn,
    ClientNeedMappingIn, ClientRequisitionAction, ClientRequisitionUpdate,
    ClientAssessmentAction, ClientAssessmentIn, ClientAssessmentUpdate,
    ClientInterviewAction, ClientInterviewIn, ClientInterviewUpdate,
    ClientJoiningAction, ClientJoiningIn, ClientJoiningUpdate, ClientTouchpointIn,
    ClientOfferAction, ClientOfferIn, ClientOfferUpdate,
    ClientReferenceCheckIn,
    ClientCandidateAction, ClientCandidateIn, ClientCandidateUpdate,
    ClientScorecardAction, ClientScorecardIn, ClientScorecardUpdate,
    ClientPostingAction, ClientPostingIn, ClientPostingUpdate, ClientPoolSourceIn,
    PersonnelFileCloseIn, ProbationConfirmIn, ProbationHrReviewIn,
    ProbationIn, ProbationReviewIn, ProbationUpdate,
    ExceptionDecisionIn, ExceptionIn,
    DocumentIn, DocumentStatusIn, DocumentTypeIn, DocumentTypeUpdate, DocumentUpdate,
    LinkRevokeIn, SanctionedStrengthIn, SanctionedStrengthUpdate,
)
# -- Phase 12 - background verification --
from app.models.hrms import (
    BackgroundApproveIn, BackgroundCheckIn, BackgroundCheckUpdate, UploadIn,
)
from app.models.hrms import InterviewMediaIn
# ── Phase INT-2 — the remaining Internal Recruitment SOP controls ──
from app.models.hrms import (
    PRINTABLE_DOCUMENTS,
    CommSendIn, CommTemplateUpdate, InterviewWindowIn, InterviewWindowUpdate,
    PolicyApplicabilityIn, PolicyApproveIn, PolicyDocumentIn, PolicyIn, PolicyRevisionIn,
    PreboardingTouchpointIn, PurgeApproveIn,
    SalaryBandIn, SalaryBandUpdate, ShortlistReviewIn, ShortlistReviewUpdate, TalentPoolIn,
)
# ── Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21) ──
from app.models.hrms import (
    AccessClearanceIn, AccessClearanceUpdate,
    AssetReturnIn, AssetReturnUpdate,
    ClearanceActionIn, ClearanceTaskIn,
    ExitInterviewIn,
    FnfDecisionIn, FnfInput, FnfPaidIn,
    HandoverAcceptIn, HandoverTaskIn, HandoverTaskUpdate,
    ResignationIn, SeparationApprovalIn, SeparationDecisionIn,
)
# ── Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9) ──
from app.models.hrms import (
    AttendanceLockIn, AttendanceMarkIn, AttendanceUnlockIn,
    CoffEarnActionIn, CoffEarnIn,
    LeaveActionIn, LeaveApplyIn, LeaveBalanceAdjustIn, LeaveCancelIn, LeaveTypeConfigIn,
    OdActionIn, OdRequestIn,
    RegularizationActionIn, RegularizationIn,
)
# ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
from app.models.hrms import (
    AbscondingContactIn, AbscondingFinalActionIn, AbscondingFlagIn, AbscondingWarningIn,
    DisciplineCaseIn, DisciplineCloseIn, DisciplineDecisionIn, DisciplineInvestigationIn,
    DisciplineRecommendationIn,
    MovementActionIn, MovementIn,
    NomineeDetailsIn, RetirementPolicyIn,
)
# ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
from app.models.hrms import (
    AdvancePolicyIn, PayrollAdjustmentsIn, PayrollApprovalIn, PayrollRecordAdjustIn,
    PayrollRunCreateIn,
    SalaryAdvanceActionIn, SalaryAdvanceIn, SalaryComponentIn, SalaryStructureIn,
    VariablePayApprovalIn, VariablePayHoldActionIn, VariablePayPolicyIn,
    VariablePayQuarterCreateIn, VariablePayRecordIn,
)
# ── Phase PAYSLIP-1 (§22.7, §22.7 Payslip Template Configuration) ──
from app.models.hrms import PayslipTemplateIn
# ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
from app.models.hrms import PipCreateIn, PipDecisionIn, PipReviewIn
# ── Phase GMP-1 — Group Mediclaim Policy ──
from app.models.hrms import GmpIn
from app.models.hrms import GovernanceRoleIn
from app.models.hrms import LetterGenerateIn, LetterPreviewIn, LetterReissueIn, LetterTemplateIn
from app.models.hrms import (
    OrientationCompleteIn, OrientationPlanIn, OrientationScheduleIn, OrientationWaiveIn,
)
from app.models.hrms import PulseConfigIn, PulseSubmitIn
from app.services import hrms_client_requisition_service as client_reqs
from app.services import hrms_client_posting_service as client_postings
from app.services import hrms_client_scorecard_service as client_scorecards
from app.services import hrms_client_candidate_service as client_cands
from app.services import hrms_client_assessment_service as client_assess
from app.services import hrms_client_interview_service as client_ints
from app.services import hrms_client_offer_service as client_offers
from app.services import hrms_client_joining_service as client_join
from app.services import hrms_client_analytics_service as client_stats
from app.services import hrms_analytics_service as analytics
from app.services import hrms_employee_service as employees
from app.services import hrms_masters_service as masters
from app.services import hrms_assessment_service as assessments
from app.services import hrms_candidate_service as candidates
from app.services import hrms_interview_service as interviews
from app.services import hrms_offer_service as offers
from app.services import hrms_exception_service as exceptions
from app.services import hrms_probation_service as probation
from app.services import hrms_reference_service as references
from app.services import hrms_scorecard_service as scorecards
from app.services import hrms_telephonic_service as telephonic
from app.services import hrms_negotiation_service as negotiation
from app.services import hrms_config_service as config_svc
from app.services import hrms_holiday_service as holidays_svc
from app.services import hrms_tracker_service as tracker_svc
from app.services import hrms_sla_service as sla
from app.services import hrms_onboarding_service as onboarding
from app.services import hrms_posting_service as postings
from app.services import hrms_requisition_service as requisitions
# ── Phase 11-R ──
from app.services import hrms_appointment_service as appointments
from app.services import hrms_document_service as documents
from app.services import hrms_link_service as links
from app.services import hrms_sanction_service as sanctions
# ── Phase INT-2 ──
from app.services import hrms_comm_service as comms
from app.services import hrms_interview_window_service as interview_windows
from app.services import hrms_policy_service as policies
from app.services import hrms_preboarding_service as preboarding
from app.services import hrms_purge_service as purge
from app.services import hrms_record_document_service as record_documents
from app.services import hrms_salary_band_service as salary_bands
from app.services import hrms_shortlist_service as shortlists
from app.services import hrms_survey_service as surveys
# ── Phase 12: background verification ──
from app.services import hrms_background_service as background
from app.services import hrms_interview_media_service as interview_media
# ── Phase EXIT-1 ──
from app.services import hrms_exit_service as exit_mgmt
# ── Phase ATT-1 ──
from app.services import hrms_attendance_service as attendance_mgmt
from app.services import hrms_leave_service as leave_mgmt
# ── Phase MOVE-1 ──
from app.services import hrms_movement_service as movement_mgmt
from app.services import hrms_discipline_service as discipline_mgmt
from app.services import hrms_absconding_service as absconding_mgmt
from app.services import hrms_retirement_service as retirement_mgmt
# ── Phase PAY-1 ──
from app.services import hrms_payroll_service as payroll_mgmt
from app.services import hrms_salary_advance_service as advance_mgmt
from app.services import hrms_variable_pay_service as vp_mgmt
# ── Phase PAYSLIP-1 ──
from app.services import hrms_payslip_service as payslip_mgmt
# ── Phase PIP-1 ──
from app.services import hrms_pip_service as pip_mgmt
# ── Phase GMP-1 ──
from app.services import hrms_gmp_service as gmp_mgmt
from app.services import hrms_access_admin_service as access_admin_mgmt
from app.services import hrms_letter_service as letter_mgmt
from app.services import hrms_orientation_service as orientation_mgmt
from app.services import hrms_pulse_service as pulse_mgmt
# ── Phase 360-1 — Employee 360° (§6) ──
from app.services import hrms_employee_360_service as employee_360_mgmt
from app.services.hrms_audit_service import read_audit
from app.utils.hrms_access import (
    NO_ACCESS_MESSAGE, can, capabilities_for, ensure_hrms_enabled, hrms_role,
    is_internal_user, scope_company_id,
)


async def _hrms_company_gate(current_user: dict = Depends(get_current_user)) -> None:
    """Router-wide guard — see module docstring."""
    await ensure_hrms_enabled(current_user)


router = APIRouter(prefix="/hrms", tags=["HRMS"], dependencies=[Depends(_hrms_company_gate)])


def _require(user: dict, capability: Cap) -> None:
    """Capability gate. Every protected endpoint calls this and nothing else, so there is
    exactly one place a permission decision can be made (and audited)."""
    if not can(user, capability):
        raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)


def _require_any(user: dict, *capabilities: Cap) -> None:
    """Capability gate for an endpoint two different roles reach by different routes.

    Used where HR acts on anybody's record and the subject acts on their own: both are
    legitimate, they hold different capabilities, and WHICH of the two the caller is gets
    settled by an ownership check in the service, not here.
    """
    if not any(can(user, c) for c in capabilities):
        raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)


def _company(user: dict, requested: str = None) -> str:
    """The company this request operates on, with tenant pinning applied.

    A client-side caller is always pinned to their own company -- a `company_id` in the
    query string is ignored, not honoured. An internal caller must name one, because
    "every company at once" is not a meaningful scope for employee data.
    """
    scoped = scope_company_id(user, requested)
    if not scoped:
        raise HTTPException(
            status_code=400,
            detail="Select a company to work with (company_id is required).")
    return scoped


@router.get("/health", response_model=HrmsHealthResponse)
async def hrms_health(current_user: dict = Depends(get_current_user)):
    """Module status for the caller.

    Returns the caller's RESOLVED role and capability list rather than raw role strings,
    so the frontend gates on exactly what the server enforces. The source HRMS derived
    permissions independently on each side and ended up "rendering actions unconditionally
    that the API will 403 for" (FRONTEND_ANALYSIS §5) — this endpoint is what prevents that.

    Reaching this endpoint at all means the company gate passed, so `enabled` is true by
    construction; it is returned explicitly because the client shape should not depend on
    inferring status from an HTTP code.
    """
    role = hrms_role(current_user)
    company_id = scope_company_id(current_user)
    return HrmsHealthResponse(
        enabled=True,
        role=role.value if role else None,
        capabilities=sorted(c.value for c in capabilities_for(current_user)),
        company_id=company_id,
        is_internal=is_internal_user(current_user),
    )


@router.get("/audit")
async def hrms_audit(
    entity: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Read the HRMS audit trail.

    Tenant-scoped: a client-side caller is pinned to their own company regardless of the
    `company_id` query param (see hrms_access.scope_company_id), so a crafted query string
    cannot read another tenant's trail.
    """
    _require(current_user, Cap.AUDIT_READ)

    rows = await read_audit(
        company_id=scope_company_id(current_user, company_id),
        entity=entity,
        entity_id=entity_id,
        actor_id=actor_id,
        limit=limit,
    )
    return {"audit": rows, "count": len(rows)}


@router.get("/companies")
async def hrms_companies(current_user: dict = Depends(get_current_user)):
    """Companies this caller may work with inside HRMS.

    Internal staff need a scope selector, since every employee endpoint requires a company.
    This is HRMS's own list rather than `GET /api/companies` on purpose: that route is gated
    by the Companies module's `companies.read` permission, which a staff admin may not hold,
    and reusing it would couple HRMS's scoping to another module's permission model.

    Client-side users get exactly their own company, so the same UI works for both without
    branching.

    ── When nothing is enabled ──────────────────────────────────────────────
    Internal staff are never gated by the company toggle (`ensure_hrms_enabled` returns
    early for them) because they administer the module. But this list used to be filtered
    by that same toggle, so switching HRMS off everywhere put them INSIDE the module with an
    empty scope selector, and every endpoint then answered "company_id is required" — an
    error telling them to pick a company from a dropdown that had nothing in it.

    So when no company has the module on, internal staff fall back to the companies that
    actually hold HRMS records. Sparsh Magic's own internal hiring lives in one of them: an
    internal requisition is a row in the operator's own database, so
    "internal hiring" is not something that exists outside a company and can be reached
    without one.

    Every row carries `hrms_enabled`, so the UI can say plainly that it is working in a
    company whose module is switched off rather than implying everything is normal. This
    widens nothing for anybody else: client-side users are still refused at the door by
    `ensure_hrms_enabled`, which is what the toggle is actually for.
    """
    from bson import ObjectId

    from app.db.mongodb import get_collection
    from app.utils.hrms_access import (
        hrms_enabled_company_ids, hrms_tenant_company_ids)

    if is_internal_user(current_user):
        ids = await hrms_enabled_company_ids()
        if not ids:
            ids = await hrms_tenant_company_ids()
        oids = []
        for i in ids:
            try:
                oids.append(ObjectId(i))
            except Exception:
                continue
        rows = await get_collection("companies").find(
            {"_id": {"$in": oids}}, {"name": 1, "hrms_enabled": 1}).sort(
                "name", 1).to_list(500)
    else:
        own = str(current_user.get("company_id") or "")
        rows = []
        if own:
            try:
                doc = await get_collection("companies").find_one(
                    {"_id": ObjectId(own)}, {"name": 1, "hrms_enabled": 1})
                if doc:
                    rows = [doc]
            except Exception:
                rows = []

    return {"companies": [
        {"id": str(r["_id"]), "name": r.get("name"),
         # False here does NOT mean "you may not work in this company" -- for internal
         # staff it means "the module is off, so this company's own users cannot reach it".
         "hrms_enabled": bool(r.get("hrms_enabled", False))}
        for r in rows]}


# =============================================================
# Phase 2 - Departments
# =============================================================
@router.get("/departments")
async def list_departments(
    company_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_READ)
    return {"departments": await masters.list_masters(
        "department", _company(current_user, company_id), include_inactive)}


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.create_master(
        "department", _company(current_user, company_id), body.model_dump(), current_user)


@router.patch("/departments/{department_id}")
async def update_department(
    department_id: str,
    body: DepartmentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.update_master(
        "department", _company(current_user, company_id), department_id,
        body.model_dump(exclude_unset=True), current_user)


@router.delete("/departments/{department_id}")
async def delete_department(
    department_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.delete_master(
        "department", _company(current_user, company_id), department_id, current_user)


# =============================================================
# Phase 2 - Designations
# =============================================================
@router.get("/designations")
async def list_designations(
    company_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_READ)
    return {"designations": await masters.list_masters(
        "designation", _company(current_user, company_id), include_inactive)}


@router.post("/designations", status_code=201)
async def create_designation(
    body: DesignationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.create_master(
        "designation", _company(current_user, company_id), body.model_dump(), current_user)


@router.patch("/designations/{designation_id}")
async def update_designation(
    designation_id: str,
    body: DesignationUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.update_master(
        "designation", _company(current_user, company_id), designation_id,
        body.model_dump(exclude_unset=True), current_user)


@router.delete("/designations/{designation_id}")
async def delete_designation(
    designation_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.delete_master(
        "designation", _company(current_user, company_id), designation_id, current_user)


@router.get("/masters/suggestions")
async def master_suggestions(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Distinct department/designation values already on this company's users, with counts.

    READ-ONLY against `learners` -- nothing is written there and nothing is auto-created.
    It exists so HR can build a clean master from real data instead of retyping it. See
    hrms_masters_service.suggest_from_directory for why we do not auto-seed.
    """
    _require(current_user, Cap.DEPARTMENT_READ)
    return await masters.suggest_from_directory(_company(current_user, company_id))


# =============================================================
# Phase 2 - Employees
# =============================================================
@router.get("/employees")
async def list_employees(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """The employee directory. Row-scoped: a MANAGER sees only their department and their
    direct reports; salary is omitted entirely without `employee.salary.read`."""
    _require(current_user, Cap.EMPLOYEE_READ)
    return await employees.list_employees(
        current_user, _company(current_user, company_id),
        search=search, department_id=department_id, designation_id=designation_id,
        status=status, include_inactive=include_inactive, limit=limit, skip=skip)


@router.get("/employees/linkable")
async def linkable_users(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Company users without an employee profile yet -- the 'Add employee' picker.
    Declared before /employees/{user_id} so the static path wins."""
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return {"users": await employees.list_linkable_users(
        current_user, _company(current_user, company_id))}


@router.get("/employees/me")
async def my_employee_profile(current_user: dict = Depends(get_current_user)):
    """Your own employee record.

    Reading your own profile is an inherent right, not a capability -- it is deliberately
    not gated by `employee.read`, so it can never be revoked by a permission edit. Your own
    salary is always visible to you.
    """
    return await employees.get_employee(
        current_user, str(current_user.get("_id")), force_salary=True)


@router.post("/employees", status_code=201)
async def create_employee(
    body: EmployeeProfileIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.create_profile(
        current_user, _company(current_user, company_id), body.model_dump(exclude_unset=True))


@router.get("/employees/{user_id}")
async def get_employee(
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return await employees.get_employee(
        current_user, user_id, company_id=scope_company_id(current_user, company_id))


@router.patch("/employees/{user_id}")
async def update_employee(
    user_id: str,
    body: EmployeeProfileUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.update_profile(
        current_user, user_id, body.model_dump(exclude_unset=True),
        _company(current_user, company_id))


@router.get("/employees/{user_id}/hierarchy")
async def employee_hierarchy(
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reporting chain upward + direct reports. The upward walk is depth-capped and
    cycle-guarded -- `reporting_manager` has no DB constraint against A->B->A."""
    _require(current_user, Cap.EMPLOYEE_READ)
    return await employees.get_hierarchy(
        current_user, user_id, _company(current_user, company_id))


# =============================================================
# Phase 3 - Requisitions (FMS)
# =============================================================
@router.get("/requisitions")
async def list_requisitions(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None),
    closing_status: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Requisition list + stat tiles. A plain employee sees only the ones they raised."""
    _require(current_user, Cap.REQUISITION_READ)
    return await requisitions.list_requisitions(
        current_user, _company(current_user, company_id),
        search=search, approval_status=approval_status, closing_status=closing_status,
        department_id=department_id, limit=limit, skip=skip)


@router.post("/requisitions", status_code=201)
async def create_requisition(
    body: RequisitionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Raise a requisition together with its job description.

    Open to any HRMS user by design: whoever raises one becomes its hiring manager and
    later co-reviews its candidates' assessments (FRONTEND_ANALYSIS 5).
    """
    _require(current_user, Cap.REQUISITION_CREATE)
    return await requisitions.create_requisition(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/requisitions/{request_no}")
async def get_requisition(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_READ)
    return await requisitions.get_requisition(
        current_user, _company(current_user, company_id), request_no)


@router.patch("/requisitions/{request_no}")
async def update_requisition(
    request_no: str,
    body: RequisitionUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_WRITE)
    return await requisitions.update_requisition(
        current_user, _company(current_user, company_id), request_no,
        body.model_dump(exclude_unset=True))


@router.delete("/requisitions/{request_no}")
async def delete_requisition(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_WRITE)
    return await requisitions.delete_requisition(
        current_user, _company(current_user, company_id), request_no)


@router.post("/requisitions/{request_no}/approve")
async def act_on_requisition(
    request_no: str,
    body: RequisitionAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One transition of the approval chain.

    hr-verify | budget-approve | scorecard-approve, each with its -reject twin
    (+ escalate-approve | escalate-reject when over sanctioned strength)

    The per-action capability is enforced inside the service from the same transition
    table that defines the state machine -- so the gate can never drift from the rule it
    guards.
    """
    return await requisitions.act_on_requisition(
        current_user, _company(current_user, company_id), request_no,
        body.action, body.remarks, body.salary_change,
        budget={"approved_headcount": body.approved_headcount,
                "approved_salary_band_min": body.approved_salary_band_min,
                "approved_salary_band_max": body.approved_salary_band_max})


@router.get("/requisitions/{request_no}/sla")
async def requisition_sla(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Milestone targets against actuals for one requisition (SOP §8).

    Everything except the actual timestamps is computed on read, so a target changed in the
    SOP takes effect immediately and a stored breach flag can never go stale.
    """
    _require(current_user, Cap.REQUISITION_READ)
    scoped = _company(current_user, company_id)
    req = await requisitions.get_requisition(current_user, scoped, request_no)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return await sla.sla_for(scoped, req)


@router.get("/sla/breaches")
async def sla_breaches(
    notify: bool = Query(False, description="fire escalations for anything newly overdue"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open internal requisitions with a milestone that is overdue and still incomplete.

    The dangerous half of breach detection: a milestone recorded late announces itself, but
    one never recorded at all is silent precisely because nothing is happening. Intended to
    be driven by a scheduled job; `notify` is off by default so opening a screen does not
    quietly email people.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await sla.sweep_open_breaches(
        current_user, _company(current_user, company_id), notify=notify)


@router.post("/requisitions/{request_no}/close")
async def close_requisition(
    request_no: str,
    body: RequisitionClose,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_CLOSE)
    return await requisitions.close_requisition(
        current_user, _company(current_user, company_id), request_no, body.status)


# =============================================================
# Phase 3 - Job Descriptions
# =============================================================
@router.get("/jd")
async def list_jds(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """The JD library. JDs are authored with their requisition and approved together, so
    there is deliberately no create endpoint and no independent approve/reject path."""
    _require(current_user, Cap.JD_READ)
    return await requisitions.list_jds(
        current_user, _company(current_user, company_id),
        status=status, search=search, limit=limit)


@router.get("/jd/{jd_no}")
async def get_jd(
    jd_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JD_READ)
    return await requisitions.get_jd(
        current_user, _company(current_user, company_id), jd_no)


@router.patch("/jd/{jd_no}")
async def update_jd(
    jd_no: str,
    body: JobDescriptionUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JD_WRITE)
    return await requisitions.update_jd(
        current_user, _company(current_user, company_id), jd_no,
        body.model_dump(exclude_unset=True))


# =============================================================
# Phase 4 - Job Postings (authenticated side)
# =============================================================
@router.get("/postings")
async def list_postings(
    company_id: Optional[str] = Query(None),
    jd_no: Optional[str] = Query(None),
    live_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Postings + KPI tiles. `application_count` is computed from candidates on every read,
    never stored, so it cannot drift from reality."""
    _require(current_user, Cap.POSTING_READ)
    return await postings.list_postings(
        current_user, _company(current_user, company_id),
        jd_no=jd_no, live_status=live_status, search=search, limit=limit)


@router.post("/postings", status_code=201)
async def create_posting(
    body: PostingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft a posting against an APPROVED job description (SOP Step 4). Opens as Draft, or
    Pending Management Approval if it names Executive Search among its channels -- either
    way, publishing is a separate step (`POST /postings/{code}/publish`)."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.create_posting(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/postings/{code}")
async def get_posting(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One posting, with its approved JD's content joined on for the HR preview screen."""
    _require(current_user, Cap.POSTING_READ)
    return await postings.get_posting(
        current_user, _company(current_user, company_id), code)


@router.get("/postings/{code}/history")
async def get_posting_history(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The posting's own history, reconstructed from the audit trail."""
    _require(current_user, Cap.POSTING_READ)
    return await postings.get_posting_history(
        current_user, _company(current_user, company_id), code)


@router.post("/postings/{code}/publish")
async def publish_posting(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Take a Draft posting live. Refused while it is still Pending Management Approval."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.publish_posting(
        current_user, _company(current_user, company_id), code)


@router.post("/postings/{code}/approve-exec-search")
async def approve_posting_exec_search(
    code: str,
    body: PostingExecApprovalIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Management clears an Executive Search posting so it can be published."""
    _require(current_user, Cap.POSTING_APPROVE_EXEC_SEARCH)
    return await postings.approve_exec_search(
        current_user, _company(current_user, company_id), code, body.remarks)


@router.patch("/postings/{code}")
async def update_posting(
    code: str,
    body: PostingUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.update_posting(
        current_user, _company(current_user, company_id), code,
        body.model_dump(exclude_unset=True))


@router.delete("/postings/{code}")
async def delete_posting(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a posting. Applications already received are KEPT -- deleting the channel must
    not delete the people who came through it."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.delete_posting(
        current_user, _company(current_user, company_id), code)


# =============================================================
# Phase 5 - Candidates, screening, journey
# =============================================================
@router.get("/candidates")
async def list_candidates(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    posting_code: Optional[str] = Query(None),
    talent_pool: Optional[bool] = Query(
        None, description="Phase INT-2: only pooled candidates, or only unpooled ones."),
    tags: Optional[str] = Query(
        None, description="Comma-separated talent-pool tags. Matches ANY of them."),
    source: Optional[str] = Query(
        None, description="Application source. Comma-separated matches ANY of them."),
    location: Optional[str] = Query(None, description="Substring match on current location."),
    experience: Optional[str] = Query(
        None, description="Substring match on total experience (stored as free text)."),
    date_from: Optional[str] = Query(None, description="Applied on or after, YYYY-MM-DD."),
    date_to: Optional[str] = Query(None, description="Applied on or before, YYYY-MM-DD."),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """The candidate pipeline / applicant pool. Row-scoped: a hiring manager sees only
    candidates on requisitions they raised. Column counts and the source breakdown come
    from the same scoped query as the rows, so the totals always match what the caller can
    open.

    `talent_pool` and `tags` are the Annexure C sourcing filter. The pool is deliberately a
    FILTER on this list rather than a collection of its own, so a pooled candidate keeps the
    same scoping, the same row security and the same retention as every other CV."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.list_candidates(
        current_user, _company(current_user, company_id),
        search=search, status=status, request_no=request_no,
        posting_code=posting_code, talent_pool=talent_pool, tags=tags,
        source=source, location=location, experience=experience,
        date_from=date_from, date_to=date_to,
        limit=limit, skip=skip)


@router.post("/candidates", status_code=201)
async def create_candidate(
    body: CandidateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Add a candidate by hand -- a walk-in, referral or agency CV that never went through
    a public posting."""
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.create_candidate(
        current_user, _company(current_user, company_id), body.model_dump(exclude_unset=True))


@router.post("/candidates/screen")
async def screen_candidates(
    body: ScreenIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Bulk triage: shortlist / review / hold / duplicate / reject / forward.

    Returns `moved` and `skipped` -- partial success is deliberate, so a batch where a few
    candidates sit at an incompatible stage still moves the rest and says which blocked.

    Declared before /candidates/{uk} so the static path wins.
    """
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await candidates.screen_candidates(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/candidates/{uk}")
async def get_candidate(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.get_candidate(
        current_user, _company(current_user, company_id), uk)


@router.patch("/candidates/{uk}")
async def update_candidate(
    uk: str,
    body: CandidateUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a candidate, including moving their stage.

    A stage move is validated against the lifecycle graph -- an illegal jump (Applied ->
    Joined, say) is a 409 listing what IS allowed from here, not a silent write.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.update_candidate(
        current_user, _company(current_user, company_id), uk,
        body.model_dump(exclude_unset=True))


@router.delete("/candidates/{uk}")
async def delete_candidate(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.delete_candidate(
        current_user, _company(current_user, company_id), uk)


@router.get("/candidates/{uk}/journey")
async def candidate_journey(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The candidate's full history, reconstructed from the audit trail.

    This is the only read path over the audit log a normal user reaches, and the reason
    every write since Phase 1 has been audited with a stable action name and entity id.
    """
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.get_journey(
        current_user, _company(current_user, company_id), uk)


@router.get("/candidates/{uk}/screening")
async def candidate_screening(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The HR Screening page's four blocks in one call (SOP §1-§3): who the candidate is,
    what the approved role and its Position Scorecard actually require, what CV /
    telephonic / assessment screening has found, and where interview and shortlisting
    stand."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.get_screening(
        current_user, _company(current_user, company_id), uk)


@router.post("/candidates/{uk}/cv-screening")
async def record_cv_screening(
    uk: str,
    body: CvScreeningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record HR's reading of the CV against the approved Position Scorecard (SOP §1).

    Records the finding; it does not move the candidate. Moving them stays with
    `POST /candidates/screen`, so a screen can be written down before anybody decides what
    to do about it."""
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await candidates.record_cv_screening(
        current_user, _company(current_user, company_id), uk, body.model_dump())


# =============================================================
# Phase 6 - Assessments (dual review)
# =============================================================
@router.get("/assessments")
async def list_assessments(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    mine: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Assessments + KPI tiles.

    Each row carries `my_slot`, `my_decision` and `awaiting_me`, so the UI knows whether
    THIS caller still owes a decision without re-deriving the dual-review rules client-side.
    `mine=true` narrows to exactly those.
    """
    _require(current_user, Cap.ASSESSMENT_READ)
    return await assessments.list_assessments(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, mine=mine, limit=limit)


@router.get("/assessments/assessable")
async def assessable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be sent an assessment -- those whose role REQUIRES one, who are at
    the assessment stage, and who have no open assessment already. Declared before
    /assessments/{no} so the static path wins."""
    _require(current_user, Cap.ASSESSMENT_SEND)
    return {"candidates": await assessments.assessable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/assessments", status_code=201)
async def send_assessment(
    body: AssessmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ASSESSMENT_SEND)
    return await assessments.send_assessment(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/assessments/{assessment_no}/review")
async def review_assessment(
    assessment_no: str,
    body: AssessmentReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record ONE reviewer's Pass/Fail.

    The caller fills the manager slot if they raised the requisition, otherwise the HR slot.
    The candidate advances only when every required slot has passed; either Fail decides it.
    """
    _require(current_user, Cap.ASSESSMENT_REVIEW)
    return await assessments.review_assessment(
        current_user, _company(current_user, company_id), assessment_no, body.model_dump())


# =============================================================
# Phase 7 - Interviews + scorecard evaluation
# =============================================================
@router.get("/interviews")
async def list_interviews(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    round_name: Optional[str] = Query(None, alias="round"),
    uk: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """The interview feed, sorted for day-grouping.

    Deliberately NOT gated by `interview.read`. Seeing the interview you were booked for is
    an inherent right -- an interviewer who cannot open their own booking cannot do the job,
    and that must not be revocable by a permission edit. The capability WIDENS the list to
    the whole company; without it the service scopes you to your own.

    Each row carries `can_evaluate`, decided server-side, so the UI never offers a button
    the API will refuse.
    """
    return await interviews.list_interviews(
        current_user, _company(current_user, company_id),
        status=status, round_name=round_name, uk=uk, limit=limit)


@router.get("/interviews/schedulable")
async def schedulable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be booked.

    Applies the SAME assessment gate the scheduler enforces, so the picker cannot offer
    somebody the API will refuse. Declared before /interviews/{no} so the static path wins.
    """
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return {"candidates": await interviews.schedulable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/interviews", status_code=201)
async def schedule_interview(
    body: InterviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Book an interview.

    Blocked when the candidate's role requires an assessment they have not passed -- a 409
    naming the stage they are actually at.
    """
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interviews.schedule_interview(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/interviews/{interview_no}")
async def update_interview(
    interview_no: str,
    body: InterviewUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reschedule, move the venue, or set a status.

    Allowed to a scheduler OR the assigned interviewer. A reschedule bumps the calendar
    sequence so clients treat the new invite as an update, not a second booking.
    """
    return await interviews.update_interview(
        current_user, _company(current_user, company_id), interview_no,
        body.model_dump(exclude_unset=True))


@router.delete("/interviews/{interview_no}")
async def cancel_interview(
    interview_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Cancel an interview. Marked Cancelled, never deleted -- a dropped round is part of
    the hiring record and the candidate journey reads it."""
    return await interviews.cancel_interview(
        current_user, _company(current_user, company_id), interview_no)


@router.post("/interviews/{interview_no}/evaluate")
async def evaluate_interview(
    interview_no: str,
    body: InterviewEvaluateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record the scorecard and advance the candidate.

    Six competencies 0-5, a decision, and a REQUIRED typed signature. An MD round
    additionally requires `interview.decide_md` -- the final call is the MD's, whoever
    conducted the conversation.
    """
    return await interviews.evaluate_interview(
        current_user, _company(current_user, company_id), interview_no, body.model_dump())


@router.get("/interviews/{interview_no}/invite.ics")
async def interview_invite(
    interview_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Download the RFC 5545 invite for an interview.

    Served as a file rather than emailed as an attachment: the shared notification service
    has no attachment channel, and adding one would mean editing a module outside HRMS.
    A link also stays correct after a reschedule, whereas a mailed .ics goes stale.
    See PHASE_7_REPORT for the recommendation to add attachment support later.
    """
    from fastapi.responses import Response
    doc = await interviews._require_visible(
        current_user, _company(current_user, company_id), interview_no)
    body = interviews.invite_for(
        doc, cancelled=doc.get("status") == "Cancelled")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{interview_no}.ics"'},
    )


# =============================================================
# Phase 8 - Offers
# =============================================================
@router.get("/offers")
async def list_offers(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Offers + KPI tiles.

    `ctc` is OMITTED for a caller without `employee.salary.read` — an offer is a
    compensation document, so it follows the same boundary Phase 2 drew for salary rather
    than inventing a second rule. The response reports `ctc_visible` so the UI knows.
    """
    _require(current_user, Cap.OFFER_READ)
    return await offers.list_offers(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, limit=limit)


@router.get("/offers/offerable")
async def offerable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be offered — Selected, and without a live offer already.
    Each carries a suggested CTC (JD → requisition → the candidate's expectation).
    Declared before /offers/{no} so the static path wins."""
    _require(current_user, Cap.OFFER_WRITE)
    return {"candidates": await offers.offerable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/offers", status_code=201)
async def create_offer(
    body: OfferIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an offer. `send_now` drafts and issues in one action, which additionally
    requires `offer.send`."""
    _require(current_user, Cap.OFFER_WRITE)
    if body.send_now:
        _require(current_user, Cap.OFFER_SEND)
    return await offers.create_offer(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/offers/{offer_no}")
async def update_offer(
    offer_no: str,
    body: OfferUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a DRAFT. Each edit archives the previous body and bumps the version, so what was
    offered at every point stays recoverable. Refused once sent."""
    _require(current_user, Cap.OFFER_WRITE)
    return await offers.update_offer(
        current_user, _company(current_user, company_id), offer_no,
        body.model_dump(exclude_unset=True))


@router.post("/offers/{offer_no}/send")
async def send_offer(
    offer_no: str,
    body: OfferSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the offer. Requires an authorised signatory — the letter commits the company
    to a salary and must be attributable."""
    _require(current_user, Cap.OFFER_SEND)
    return await offers.send_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.post("/offers/{offer_no}/approve")
async def approve_offer(
    offer_no: str,
    body: OfferApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Management's sign-off on an internal offer, mandatory before it can be sent.

    Separate from `offer.send` on purpose: verifying the figure sits inside the approved band
    says the offer is affordable; this says it should go out. Annexure B of the Internal
    Recruitment SOP makes the second one Management/Finance's call, not HR's.
    """
    _require(current_user, Cap.OFFER_APPROVE)
    return await offers.approve_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.post("/offers/{offer_no}/revoke")
async def revoke_offer(
    offer_no: str,
    body: OfferRevokeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Withdraw a sent offer before the candidate responds."""
    _require(current_user, Cap.OFFER_SEND)
    return await offers.revoke_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.delete("/offers/{offer_no}")
async def delete_offer(
    offer_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Delete a DRAFT only. A sent offer is part of the hiring record — revoke it instead."""
    _require(current_user, Cap.OFFER_WRITE)
    return await offers.delete_offer(
        current_user, _company(current_user, company_id), offer_no)


# ─────────────────────────────────────────────────────────────
# Phase 9 — onboarding
# ─────────────────────────────────────────────────────────────
@router.get("/onboarding")
async def list_onboardings(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The onboarding board. The access code is deliberately absent — see the service."""
    _require(current_user, Cap.ONBOARDING_READ)
    return await onboarding.list_onboardings(
        current_user, _company(current_user, company_id), status=status, search=search)


@router.get("/onboarding/onboardable")
async def onboardable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who have accepted an offer and are not yet being onboarded."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.onboardable_candidates(
        current_user, _company(current_user, company_id))


@router.get("/onboarding/{onb_no}")
async def get_onboarding(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ONBOARDING_READ)
    return await onboarding.get_onboarding(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/onboarding", status_code=201)
async def start_onboarding(
    body: OnboardingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open an onboarding for a candidate who has accepted their offer. Mints the
    pre-onboarding link the new hire fills in."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.start_onboarding(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/onboarding/{onb_no}")
async def update_onboarding_details(
    onb_no: str,
    body: OnboardingDetailsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Joining date, reporting manager, asset requirements."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.update_details(
        current_user, _company(current_user, company_id), onb_no,
        body.model_dump(exclude_unset=True))


@router.post("/onboarding/{onb_no}/bg")
async def update_onboarding_bg(
    onb_no: str,
    body: OnboardingBgIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record the background-verification outcome. Drives the `bg_cleared` checklist item in
    both directions — a withdrawn clearance un-ticks it."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.update_bg(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/verify")
async def verify_onboarding_documents(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Confirm a human has checked the KYC documents. Required before an Employee ID."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.verify_documents(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/onboarding/{onb_no}/documents")
async def add_onboarding_documents(
    onb_no: str,
    body: OnboardingDocumentsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR-side KYC upload, for documents handed over in person or by email."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.add_documents(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/documents/review")
async def review_onboarding_document(
    onb_no: str,
    body: OnboardingDocReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR's verdict on one uploaded joining document: Verified, Rejected or Exception."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.review_document(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/checklist")
async def set_onboarding_checklist(
    onb_no: str,
    body: OnboardingChecklistIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Tick or un-tick a joining-day task. The three system-owned items are refused here."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.set_checklist(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/joining")
async def confirm_onboarding_joining(
    onb_no: str,
    body: OnboardingJoiningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR confirming the joiner reported, on what date, and into which role (§7.5 Stage 6)."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.confirm_joining(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/generate-id")
async def generate_employee_id(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the Employee ID and create the employee record.

    Its own capability, separate from `onboarding.write`: this is the irreversible step that
    turns a candidate into an employee, and it should be possible to let someone run an
    onboarding without letting them create staff records.
    """
    _require(current_user, Cap.ONBOARDING_GENERATE_ID)
    return await onboarding.generate_employee_id(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/employees/link/{employee_code}")
async def link_employee_user(
    employee_code: str,
    body: EmployeeLinkIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Attach an onboarding-created employee record to a real login account.

    Gated on `employee.write` because it changes who an employee record IS — from that point
    the user document is the single source of identity.
    """
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.link_user(
        current_user, _company(current_user, company_id), employee_code, body.user_id)


# ─────────────────────────────────────────────────────────────
# Phase 10 — analytics & reports (READ-ONLY)
# ─────────────────────────────────────────────────────────────
@router.get("/analytics/dashboard")
async def analytics_dashboard(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    track: Optional[str] = Query(None, description="internal — adds the SOP §10 KPI block"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Headline KPIs, positions summary, offer outcomes and time-to-hire.

    A hiring manager gets the same shape scoped to their own requisitions — the response
    says so via `scoped_to_own_requisitions`, so the UI can label the numbers honestly
    rather than implying they are company-wide.

    `track=internal` adds `internal_kpis`, the Internal Recruitment SOP's own dashboard.
    Omitting it leaves the payload byte-for-byte what every existing caller receives.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.dashboard(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to, track=track)


@router.get("/analytics/funnel")
async def analytics_funnel(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The hiring funnel by EFFECTIVE rank, so it can never show more offers than
    interviews. See models/hrms.py STAGE_RANK."""
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.funnel(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to)


@router.get("/analytics/breakdown")
async def analytics_breakdown(
    by: BreakdownBy = Query(BreakdownBy.SOURCE),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Group counts along one allow-listed dimension."""
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.breakdown(
        current_user, _company(current_user, company_id), by.value,
        date_from=date_from, date_to=date_to)


@router.get("/reports/{entity}")
async def hrms_report(
    entity: ReportEntity,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_REPORT_PAGE_SIZE, ge=1, le=MAX_REPORT_PAGE_SIZE),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One page of a detailed report. `entity` is an enum, not a collection name."""
    _require(current_user, Cap.REPORT_READ)
    return await analytics.report(
        current_user, _company(current_user, company_id), entity.value,
        page=page, page_size=page_size, search=search,
        date_from=date_from, date_to=date_to)


@router.get("/reports/{entity}/export")
async def hrms_report_export(
    entity: ReportEntity,
    fmt: ExportFormat = Query(ExportFormat.CSV),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Download a report.

    Its own capability, separate from `report.read`: reading aggregate figures on screen
    and taking a file of personal data off the system are different acts, and a hiring
    manager is deliberately granted the first and not the second.

    Rendered server-side from already-scoped rows. Building the file in the browser would
    mean shipping rows the API had correctly withheld.
    """
    _require(current_user, Cap.REPORT_EXPORT)
    payload = await analytics.export_rows(
        current_user, _company(current_user, company_id), entity.value,
        search=search, date_from=date_from, date_to=date_to)

    if fmt == ExportFormat.XLSX:
        body = analytics.render_xlsx(payload)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = analytics.render_csv(payload)
        media = "text/csv; charset=utf-8"

    filename = analytics.export_filename(entity.value, fmt.value, payload["range"])
    return StreamingResponse(
        iter([body]),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Truncation is announced in a header AND inside the file, so it cannot be
            # missed by whichever one the recipient looks at.
            "X-Export-Truncated": "true" if payload["truncated"] else "false",
            "X-Export-Rows": str(payload["returned"]),
            "X-Export-Total": str(payload["total"]),
        },
    )


# =============================================================================
# Phase 11-R — recruitment review enhancements
# =============================================================================
# Seven items, appended as one block so the phase's whole API surface is readable in one
# place. Every endpoint follows the existing conventions without exception:
#   * `_require(user, Cap.X)` and nothing else decides permission,
#   * `_company(user, company_id)` pins the tenant (a client-side caller's company_id
#     query param is IGNORED, not honoured),
#   * static paths are declared BEFORE their `{param}` siblings so they win the match.

# ─────────────────────────────────────────────────────────────
# Item 1 — the public-link registry
# ─────────────────────────────────────────────────────────────
@router.get("/links")
async def list_hrms_links(
    kind: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every public link this company has issued, with its open count and live status.

    Status is COMPUTED per row (an expired link reads Expired without a nightly job), so
    the `status` filter is applied after projection — see hrms_link_service.list_links.
    A hiring manager sees links for their own requisitions only.
    """
    _require(current_user, Cap.LINK_READ)
    return await links.list_links(
        current_user, _company(current_user, company_id),
        kind=kind, status=status, search=search,
        date_from=date_from, date_to=date_to, limit=limit, skip=skip)


@router.get("/links/{link_id}")
async def get_hrms_link(
    link_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One link plus its open history (count, first sighting, last sighting)."""
    _require(current_user, Cap.LINK_READ)
    return await links.get_link(current_user, _company(current_user, company_id), link_id)


@router.post("/links/{link_id}/revoke")
async def revoke_hrms_link(
    link_id: str,
    body: LinkRevokeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Kill a live link. The public handlers refuse it from the next request onward —
    revocation here is ENFORCED by `assert_link_live`, not merely displayed."""
    _require(current_user, Cap.LINK_MANAGE)
    return await links.revoke(
        current_user, _company(current_user, company_id), link_id, body.reason)


@router.post("/links/{link_id}/reissue")
async def reissue_hrms_link(
    link_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Mint a fresh credential for the same record and revoke the old one.

    Delegates to the owning service so the new code is one that service knows about.
    An `apply` link cannot be reissued — its code is printed on published job ads.
    """
    _require(current_user, Cap.LINK_MANAGE)
    return await links.reissue(current_user, _company(current_user, company_id), link_id)


# ─────────────────────────────────────────────────────────────
# Item 2 — documentation
# ─────────────────────────────────────────────────────────────
@router.get("/document-types")
async def list_hrms_document_types(
    include_inactive: bool = Query(False),
    applies_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The company's document-type master. Seeds a sensible default set on first read."""
    _require(current_user, Cap.DOCUMENT_READ)
    return {"document_types": await documents.list_document_types(
        _company(current_user, company_id),
        include_inactive=include_inactive, applies_to=applies_to)}


@router.post("/document-types", status_code=201)
async def create_hrms_document_type(
    body: DocumentTypeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.create_document_type(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/document-types/{type_id}")
async def update_hrms_document_type(
    type_id: str,
    body: DocumentTypeUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.update_document_type(
        current_user, _company(current_user, company_id), type_id,
        body.model_dump(exclude_unset=True))


@router.delete("/document-types/{type_id}")
async def delete_hrms_document_type(
    type_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Blocked while any document still references the type — deactivate instead."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.delete_document_type(
        current_user, _company(current_user, company_id), type_id)


@router.get("/documents")
async def list_hrms_documents(
    owner_type: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    expiring_soon: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The document register. Expiry is computed per row, so the `status` filter runs
    after projection."""
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.list_documents(
        current_user, _company(current_user, company_id),
        owner_type=owner_type, owner_id=owner_id, status=status, type_id=type_id,
        search=search, expiring_soon=expiring_soon, limit=limit, skip=skip)


@router.get("/documents/checklist")
async def hrms_document_checklist(
    owner_type: str = Query(...),
    owner_id: str = Query(...),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every applicable type for this person, with its status or `Pending`, plus the
    read-only view over files already attached elsewhere (resume, KYC scans).

    Declared before /documents/{doc_no} so the static path wins.
    """
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.checklist(
        current_user, _company(current_user, company_id), owner_type, owner_id)


@router.post("/documents", status_code=201)
async def upload_hrms_document(
    body: DocumentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Upload a document, or a new version of one (supply `doc_no` for a version)."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.upload_document(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/documents/{doc_no}")
async def get_hrms_document(
    doc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.get_document(
        current_user, _company(current_user, company_id), doc_no)


@router.patch("/documents/{doc_no}")
async def update_hrms_document(
    doc_no: str,
    body: DocumentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Metadata only. The file is immutable — replacing it means adding a version."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.update_document(
        current_user, _company(current_user, company_id), doc_no,
        body.model_dump(exclude_unset=True))


@router.post("/documents/{doc_no}/status")
async def set_hrms_document_status(
    doc_no: str,
    body: DocumentStatusIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Verify, reject or move a document to Under Review.

    Its own capability, separate from `document.write`: collecting paperwork and ATTESTING
    to it are different acts, and Sparsh support staff deliberately hold the first and not
    the second — the same boundary that keeps REQUISITION_REVIEW_HR off the INTERNAL list.
    """
    _require(current_user, Cap.DOCUMENT_VERIFY)
    return await documents.set_status(
        current_user, _company(current_user, company_id), doc_no, body.model_dump())


@router.get("/documents/{doc_no}/url")
async def hrms_document_url(
    doc_no: str,
    version: Optional[int] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived signed URL, minted per request. Never stored — see the service."""
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.signed_url(
        current_user, _company(current_user, company_id), doc_no, version)


@router.delete("/documents/{doc_no}")
async def delete_hrms_document(
    doc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a register row. A VERIFIED document is refused — reject it instead."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.delete_document(
        current_user, _company(current_user, company_id), doc_no)


# ─────────────────────────────────────────────────────────────
# Item 3 — appointment letters
# ─────────────────────────────────────────────────────────────
@router.get("/appointments")
async def list_hrms_appointments(
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Appointment letters + KPI tiles. `ctc` is omitted without `employee.salary.read`,
    the same boundary Phase 8 draws for offers."""
    _require(current_user, Cap.APPOINTMENT_READ)
    return await appointments.list_appointments(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, search=search, limit=limit)


@router.get("/appointments/eligible")
async def appointable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who have accepted an offer and have no live letter yet.
    Declared before /appointments/{no} so the static path wins."""
    _require(current_user, Cap.APPOINTMENT_READ)
    return {"candidates": await appointments.eligible_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/appointments", status_code=201)
async def create_hrms_appointment(
    body: AppointmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an appointment letter, defaulting every term from the accepted offer."""
    _require(current_user, Cap.APPOINTMENT_WRITE)
    return await appointments.create_appointment(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/appointments/{appointment_no}")
async def get_hrms_appointment(
    appointment_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.APPOINTMENT_READ)
    return await appointments.get_appointment(
        current_user, _company(current_user, company_id), appointment_no)


@router.patch("/appointments/{appointment_no}")
async def update_hrms_appointment(
    appointment_no: str,
    body: AppointmentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a GENERATED letter. Refused once sent — the candidate is reading it."""
    _require(current_user, Cap.APPOINTMENT_WRITE)
    return await appointments.update_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump(exclude_unset=True))


@router.post("/appointments/{appointment_no}/send")
async def send_hrms_appointment(
    appointment_no: str,
    body: AppointmentSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the letter.

    Its own capability, separate from `appointment.write`: authoring a letter and COMMITTING
    the company to employing somebody are different acts — exactly the split Phase 8 draws
    between OFFER_WRITE and OFFER_SEND.
    """
    _require(current_user, Cap.APPOINTMENT_SEND)
    return await appointments.send_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump())


@router.post("/appointments/{appointment_no}/cancel")
async def cancel_hrms_appointment(
    appointment_no: str,
    body: AppointmentCancelIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Withdraw a letter and revoke its public link. An ACKNOWLEDGED letter is refused."""
    _require(current_user, Cap.APPOINTMENT_SEND)
    return await appointments.cancel_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump())


@router.get("/scorecards")
async def list_scorecards(
    request_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_READ)
    return await scorecards.list_scorecards(
        current_user, _company(current_user, company_id),
        request_no=request_no, status=status, limit=limit)


@router.post("/scorecards", status_code=201)
async def create_scorecard(
    body: ScorecardIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_WRITE)
    return await scorecards.create_scorecard(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/scorecards/{scr_no}")
async def get_scorecard(
    scr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_READ)
    doc = await scorecards.get_scorecard(_company(current_user, company_id), scr_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    return doc


@router.patch("/scorecards/{scr_no}")
async def update_scorecard(
    scr_no: str,
    body: ScorecardUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_WRITE)
    return await scorecards.update_scorecard(
        current_user, _company(current_user, company_id), scr_no,
        body.model_dump(exclude_unset=True))


@router.post("/scorecards/{scr_no}/approve")
async def approve_scorecard(
    scr_no: str,
    body: ScorecardApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One approval signature. The scorecard completes when every required role has signed."""
    _require(current_user, Cap.SCORECARD_APPROVE)
    return await scorecards.approve_scorecard(
        current_user, _company(current_user, company_id), scr_no, body.model_dump())


@router.post("/candidates/{uk}/scorecard-evaluate")
async def evaluate_against_scorecard(
    uk: str,
    body: ScorecardEvaluateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Score a candidate against their requisition's scorecard.

    Records the weighted score and its band; deliberately does NOT move the candidate. The
    band is advice for whoever reads it, not an instruction to the pipeline.
    """
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await scorecards.evaluate_candidate(
        current_user, _company(current_user, company_id), uk, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Internal track — reference checks
# ─────────────────────────────────────────────────────────────
# Mandatory before an internal offer (SOP §6). A candidate may have several referees; the
# offer gate asks whether ANY of them cleared.
@router.get("/reference-checks")
async def list_reference_checks(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_READ)
    return await references.list_reference_checks(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, outcome=outcome, limit=limit)


@router.post("/reference-checks", status_code=201)
async def create_reference_check(
    body: ReferenceCheckIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_WRITE)
    return await references.create_reference_check(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/reference-checks/{ref_no}")
async def get_reference_check(
    ref_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_READ)
    doc = await references.get_reference_check(_company(current_user, company_id), ref_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Reference check not found.")
    return doc


@router.patch("/reference-checks/{ref_no}")
async def update_reference_check(
    ref_no: str,
    body: ReferenceCheckUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_WRITE)
    return await references.update_reference_check(
        current_user, _company(current_user, company_id), ref_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# Per-company configuration (Phase INT-5, spec §42)
# ─────────────────────────────────────────────────────────────
# The rules this company runs by: SLA targets, retention periods, probation duration,
# reminder tiers and score band floors. READ is wide because a target you cannot see is one
# you cannot plan against; WRITE is Management's and Finance's, because Annexure B makes
# them "A" on policy review and these numbers are that policy expressed as data.
#
# No setting here turns a GATE off. The budget gate, the reference check, the scorecard
# approval and the telephonic screen are the controls the SOP is made of; a deviation goes
# through the exception log, where it is attributable.
@router.get("/settings")
async def get_hrms_settings(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_READ)
    return await config_svc.describe(_company(current_user, company_id))


@router.patch("/settings")
async def update_hrms_settings(
    body: ConfigUpdateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await config_svc.update_config(
        current_user, _company(current_user, company_id),
        body.model_dump(exclude_unset=True, exclude_none=True))


@router.post("/settings/reset")
async def reset_hrms_settings(
    body: ConfigResetIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Follow the module defaults again. Distinct from setting a value that HAPPENS to equal
    the default -- a stored value stays where it was put if the default ever moves."""
    _require(current_user, Cap.SETTINGS_WRITE)
    return await config_svc.reset_config(
        current_user, _company(current_user, company_id), body.keys)


# ─────────────────────────────────────────────────────────────
# The internal requisition tracker (Phase INT-7, Annexure C)
# ─────────────────────────────────────────────────────────────
# "Maintain a shared internal requisition tracker (status, scores, budget approval date)
# visible to HR, Department Head, and Management." One row per internal requisition, every
# stage rolled up, computed entirely server-side.
#
# Gated on `requisition.read` and scoped by the SAME visibility rule the requisition list
# uses, so a user never sees a row here they could not open there. Read-only by
# construction -- see hrms_tracker_service.
@router.get("/internal-requisitions/tracker")
async def internal_requisition_tracker(
    status: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    sla: Optional[str] = Query(None, description="breached | on_track | met | not_started"),
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_READ)
    return await tracker_svc.tracker(
        current_user, _company(current_user, company_id),
        status=status, department_id=department_id, sla=sla, limit=limit, skip=skip)


# ─────────────────────────────────────────────────────────────
# The working calendar (Phase INT-6, spec §26)
# ─────────────────────────────────────────────────────────────
# The dates SLA maths skips, for THIS company. Gated on the same capabilities as the rest of
# the rule set: a holiday moves a compliance due date, so it belongs with the numbers it
# moves rather than with the operational screens.
#
# HRMS's own calendar, never the ERP's global `holidays` master -- that collection has no
# company_id, so pointing per-company figures at it would let one admin's edit move every
# entity's due dates. `/import` ADOPTS dates from it as a copy.
@router.get("/holidays")
async def list_hrms_holidays(
    year: Optional[int] = Query(None, ge=1970, le=2200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_READ)
    return await holidays_svc.list_holidays(
        _company(current_user, company_id), year=year)


@router.post("/holidays", status_code=201)
async def add_hrms_holiday(
    body: HolidayIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.add_holiday(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/holidays/import")
async def import_hrms_holidays(
    body: HolidayImportIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Adopt one year of the ERP's global calendar. Safe to run twice — dates already on
    this calendar are reported as skipped rather than refused."""
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.import_from_erp(
        current_user, _company(current_user, company_id), year=body.year)


@router.delete("/holidays/{holiday_date}")
async def remove_hrms_holiday(
    holiday_date: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.remove_holiday(
        current_user, _company(current_user, company_id), holiday_date)


# ─────────────────────────────────────────────────────────────
# Internal track — salary negotiation (SOP step 9, spec §16)
# ─────────────────────────────────────────────────────────────
# The RECORD of the rounds. The RULE lives on the offer (`assert_within_band`) and does not
# move: recording an above-band round is allowed, issuing an offer at it is not, until the
# budget is re-approved or an Offer Outside Budget exception is approved.
@router.get("/negotiations")
async def list_negotiation_rounds(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_READ)
    return await negotiation.list_rounds(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, limit=limit)


@router.post("/negotiations", status_code=201)
async def record_negotiation_round(
    body: NegotiationRoundIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_WRITE)
    return await negotiation.record_round(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/negotiations/{neg_no}")
async def get_negotiation_round(
    neg_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_READ)
    doc = await negotiation.get_round(_company(current_user, company_id), neg_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Negotiation round not found.")
    return doc


@router.get("/candidates/{uk}/negotiation")
async def candidate_negotiation(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The spec §16 comparison surface: band, latest round, within/above/below, and whether
    an offer at the latest figure would pass the band gate today."""
    _require(current_user, Cap.NEGOTIATION_READ)
    return await negotiation.negotiation_for(
        current_user, _company(current_user, company_id), uk)


# ─────────────────────────────────────────────────────────────
# Internal track — telephonic screening (SOP step 5)
# ─────────────────────────────────────────────────────────────
# The brief call HR makes between CV screening and the panel. `telephonic.write` is HR's
# alone (Annexure B marks HR "R" and everybody else "I"); the HOD reads it because they
# interview off the back of it.
#
# The GATE this feeds lives on interview scheduling, not here -- see
# hrms_telephonic_service.assert_telephonic_cleared.
@router.get("/telephonic-screenings")
async def list_telephonic_screenings(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    return await telephonic.list_screenings(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, outcome=outcome, limit=limit)


# Declared BEFORE /telephonic-screenings/{tel_no}, or "screenable" is parsed as a tel_no --
# the same ordering /interviews/schedulable and /offers/offerable rely on.
@router.get("/telephonic-screenings/screenable")
async def screenable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    return await telephonic.screenable_candidates(
        current_user, _company(current_user, company_id))


@router.post("/telephonic-screenings", status_code=201)
async def create_telephonic_screening(
    body: TelephonicScreeningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_WRITE)
    return await telephonic.create_screening(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/telephonic-screenings/{tel_no}")
async def get_telephonic_screening(
    tel_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    doc = await telephonic.get_screening(_company(current_user, company_id), tel_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Telephonic screening not found.")
    return doc


@router.patch("/telephonic-screenings/{tel_no}")
async def update_telephonic_screening(
    tel_no: str,
    body: TelephonicScreeningUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_WRITE)
    return await telephonic.update_screening(
        current_user, _company(current_user, company_id), tel_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# Internal track — probation and personnel-file closure
# ─────────────────────────────────────────────────────────────
# Probation is an EMPLOYEE event, not a recruitment stage: the candidate lifecycle ends at
# joining. See hrms_probation_service for why no AppStatus was added.
@router.get("/probation")
async def list_probations(
    outcome: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    uk: Optional[str] = Query(None, description="the candidate this hire came from"),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_READ)
    return await probation.list_probations(
        current_user, _company(current_user, company_id),
        outcome=outcome, request_no=request_no, uk=uk, limit=limit)


@router.get("/probation/due")
async def due_probations(
    within_days: int = Query(30, ge=0, le=365),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reviews that are overdue, and those falling due inside the window.

    Split rather than merged: a missed commitment and a diary entry are two different
    conversations, and one date-sorted list leaves the reader to tell them apart.
    """
    _require(current_user, Cap.PROBATION_READ)
    return await probation.due_probations(
        current_user, _company(current_user, company_id), within_days=within_days)


@router.post("/probation", status_code=201)
async def open_probation(
    body: ProbationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open a review by hand. Internal-track joiners get one automatically at handover."""
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.open_probation(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/probation/{prb_no}")
async def get_probation(
    prb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_READ)
    doc = await probation.get_probation(_company(current_user, company_id), prb_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    return doc


@router.patch("/probation/{prb_no}")
async def update_probation(
    prb_no: str,
    body: ProbationUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.update_probation(
        current_user, _company(current_user, company_id), prb_no,
        body.model_dump(exclude_unset=True))


@router.post("/probation/{prb_no}/review")
async def review_probation(
    prb_no: str,
    body: ProbationReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The reporting manager's review and recommendation (7.5 Stage 12).

    Scores performance, conduct, attendance, competence and suitability, then recommends
    Confirm, Extend or Separate. A RECOMMENDATION -- HR reviews it and an authorised
    approver decides, which is why this takes PROBATION_REVIEW and not PROBATION_CONFIRM.
    """
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.submit_review(
        current_user, _company(current_user, company_id), prb_no, body.model_dump())


@router.post("/probation/{prb_no}/hr-review")
async def hr_review_probation(
    prb_no: str,
    body: ProbationHrReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR endorses the manager's recommendation, or returns it with a reason.

    The step between the recommendation and the authorised approval. Only an endorsed
    recommendation can be approved.
    """
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.hr_review(
        current_user, _company(current_user, company_id), prb_no, body.model_dump())


@router.post("/probation/{prb_no}/confirm")
async def confirm_probation(
    prb_no: str,
    body: ProbationConfirmIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Confirm, extend or end a probation.

    The hiring manager's call (Annexure B: "Probation review & confirmation -- Department
    Head: A/R"). A confirmation closes the requisition as Hired.
    """
    _require(current_user, Cap.PROBATION_CONFIRM)
    return await probation.confirm_probation(
        current_user, _company(current_user, company_id), prb_no, body.model_dump())


@router.post("/personnel-file/close")
async def close_personnel_file(
    body: PersonnelFileCloseIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record that the personnel file has been checked and closed (SOP §7, §9)."""
    _require(current_user, Cap.PERSONNEL_FILE_CLOSE)
    return await probation.close_personnel_file(
        current_user, _company(current_user, company_id), body.model_dump())


# ─────────────────────────────────────────────────────────────
# Internal track — the exception log
# ─────────────────────────────────────────────────────────────
# An APPROVED exception is the only thing that lifts the reference-check and salary-band
# gates. There is deliberately no override flag on either of those endpoints: a boolean in a
# payload records nothing and attributes nothing.
@router.get("/exceptions")
async def list_exceptions(
    request_no: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EXCEPTION_READ)
    return await exceptions.list_exceptions(
        current_user, _company(current_user, company_id),
        request_no=request_no, uk=uk, status=status,
        exception_type=exception_type, limit=limit)


@router.post("/exceptions", status_code=201)
async def raise_exception(
    body: ExceptionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Log a deviation for approval. Raising one grants nothing until it is approved."""
    _require(current_user, Cap.EXCEPTION_WRITE)
    return await exceptions.raise_exception(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/exceptions/{exc_no}")
async def get_exception(
    exc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EXCEPTION_READ)
    doc = await exceptions.get_exception(_company(current_user, company_id), exc_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    return doc


@router.post("/exceptions/{exc_no}/approve")
async def decide_exception(
    exc_no: str,
    body: ExceptionDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Approve or reject. Management/Finance only, and never the person who raised it."""
    _require(current_user, Cap.EXCEPTION_APPROVE)
    return await exceptions.decide_exception(
        current_user, _company(current_user, company_id), exc_no, body.model_dump())


@router.get("/analytics/positions")
async def analytics_positions(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The position-wise CV status matrix: one row per requisition, one column per stage.

    Same `_scope`, same SCAN_CAP and the same window validation as every other analytics
    endpoint. Read-only.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.positions(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to)


# ─────────────────────────────────────────────────────────────
# Item 7 — sanctioned strength
# ─────────────────────────────────────────────────────────────
@router.get("/sanctioned-strength")
async def list_sanctioned_strength(
    department_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every sanctioned figure, each with its LIVE actual headcount and availability.

    `actual` is counted from employee profiles on every read and never stored — a stored
    figure would be wrong the moment somebody resigned, which is exactly when it is asked.
    """
    _require(current_user, Cap.SANCTION_READ)
    return await sanctions.list_sanctions(
        _company(current_user, company_id), department_id=department_id)


@router.get("/sanctioned-strength/position")
async def sanctioned_position(
    department_id: str = Query(...),
    designation_id: str = Query(...),
    requested: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The live sanctioned/actual/available readout for one position.

    Read by the requisition form on every change, so the raiser is told BEFORE they submit
    that the request will be escalated. Declared before /{sanction_id} so the static path
    wins.
    """
    _require(current_user, Cap.SANCTION_READ)
    return await sanctions.position_status(
        _company(current_user, company_id), department_id, designation_id,
        requested=requested)


@router.post("/sanctioned-strength", status_code=201)
async def set_sanctioned_strength(
    body: SanctionedStrengthIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Create or replace the sanctioned figure for a position (an upsert — one figure per
    position is the rule, enforced by a unique index)."""
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.set_sanction(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/sanctioned-strength/{sanction_id}")
async def update_sanctioned_strength(
    sanction_id: str,
    body: SanctionedStrengthUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.update_sanction(
        current_user, _company(current_user, company_id), sanction_id,
        body.model_dump(exclude_unset=True))


@router.delete("/sanctioned-strength/{sanction_id}")
async def delete_sanctioned_strength(
    sanction_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a sanctioned figure. The position then has none, which means every future
    requisition for it is routed for escalation — the response says so explicitly."""
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.delete_sanction(
        current_user, _company(current_user, company_id), sanction_id)


# ═════════════════════════════════════════════════════════════
# Phase INT-2 — the remaining Internal Recruitment SOP controls
# ═════════════════════════════════════════════════════════════
# Every endpoint below is additive. None of them changes a status code, a payload or a
# message on any pre-existing route.


# ─────────────────────────────────────────────────────────────
# INT-2.1 — the internal shortlisting committee (SOP §5)
# ─────────────────────────────────────────────────────────────
# HR and the Department Head jointly finalise the shortlist. Two roles, two DIFFERENT
# people, and a finalised record is what lifts the gate on `Selected`.
@router.get("/shortlist-reviews")
async def list_shortlist_reviews(
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHORTLIST_READ)
    return await shortlists.list_shortlist_reviews(
        current_user, _company(current_user, company_id),
        request_no=request_no, outcome=outcome, uk=uk, limit=limit)


@router.post("/shortlist-reviews", status_code=201)
async def create_shortlist_review(
    body: ShortlistReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Convene a sitting. Convening decides nothing until the outcome is Finalised."""
    _require(current_user, Cap.SHORTLIST_WRITE)
    return await shortlists.create_shortlist_review(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/shortlist-reviews/{slr_no}")
async def get_shortlist_review(
    slr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHORTLIST_READ)
    doc = await shortlists.get_shortlist_review(_company(current_user, company_id), slr_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Shortlist review not found.")
    return doc


@router.patch("/shortlist-reviews/{slr_no}")
async def update_shortlist_review(
    slr_no: str,
    body: ShortlistReviewUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record members, candidates or the outcome. A DECIDED sitting is frozen."""
    _require(current_user, Cap.SHORTLIST_WRITE)
    return await shortlists.update_shortlist_review(
        current_user, _company(current_user, company_id), slr_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# INT-2.1 — batch interview windows (Annexure C)
# ─────────────────────────────────────────────────────────────
# A PREFERENCE, never a rule: scheduling outside a window warns in the response and books
# the interview anyway. `interview.schedule` governs, because a window is a scheduling
# artifact rather than a governance one.
@router.get("/interview-windows")
async def list_interview_windows(
    department_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_READ)
    return await interview_windows.list_windows(
        _company(current_user, company_id),
        department_id=department_id, include_inactive=include_inactive)


@router.post("/interview-windows", status_code=201)
async def create_interview_window(
    body: InterviewWindowIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.create_window(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/interview-windows/{window_id}")
async def update_interview_window(
    window_id: str,
    body: InterviewWindowUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.update_window(
        current_user, _company(current_user, company_id), window_id,
        body.model_dump(exclude_unset=True))


@router.delete("/interview-windows/{window_id}")
async def delete_interview_window(
    window_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.delete_window(
        current_user, _company(current_user, company_id), window_id)


# ─────────────────────────────────────────────────────────────
# INT-2.3 — pre-boarding engagement (SOP §6)
# ─────────────────────────────────────────────────────────────
# Tracking, not a control. NOTHING is gated on a touchpoint: a candidate with none onboards
# exactly as they always did. What it does is put people on a due list and flag the ones who
# say they are wavering.
@router.get("/preboarding")
async def list_preboarding(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PREBOARDING_READ)
    return await preboarding.list_touchpoints(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, sentiment=sentiment, limit=limit)


@router.get("/preboarding/due")
async def due_preboarding(
    within_days: int = Query(7, ge=0, le=90),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Accepted candidates nobody has spoken to lately.

    Split into `never_contacted` and `gone_quiet` rather than one sorted list, the same way
    `/probation/due` splits: "we have not started" and "we have let it slip" are two
    different conversations.
    """
    _require(current_user, Cap.PREBOARDING_READ)
    return await preboarding.due_touchpoints(
        current_user, _company(current_user, company_id), within_days=within_days)


@router.post("/preboarding", status_code=201)
async def record_preboarding_touchpoint(
    body: PreboardingTouchpointIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Log one contact. An `At Risk` sentiment notifies the recruiter and the HOD."""
    _require(current_user, Cap.PREBOARDING_WRITE)
    return await preboarding.record_touchpoint(
        current_user, _company(current_user, company_id), body.model_dump())


# ─────────────────────────────────────────────────────────────
# INT-2.5 — the standing salary-band master (Annexure C)
# ─────────────────────────────────────────────────────────────
# A CONVENIENCE, never an authority: the budget gate pre-fills from this table, and the
# offer check still reads the band stamped on the REQUISITION. A master edited in April must
# not retroactively legalise an offer approved in March.
@router.get("/salary-bands")
async def list_salary_bands(
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_BAND_READ)
    return await salary_bands.list_salary_bands(
        current_user, _company(current_user, company_id),
        department_id=department_id, designation_id=designation_id,
        status=status, limit=limit)


@router.get("/salary-bands/for-requisition/{request_no}")
async def salary_band_prefill(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The band the budget gate would pre-fill for this requisition, or null.

    A SUGGESTION in the shape the approval body expects, so the UI can fill the boxes and
    the approver can still change them. Nothing here writes.
    """
    _require(current_user, Cap.SALARY_BAND_READ)
    scoped = _company(current_user, company_id)
    req = await requisitions.get_requisition(current_user, scoped, request_no)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return {"request_no": request_no,
            "prefill": await salary_bands.prefill_for_requisition(scoped, req)}


@router.post("/salary-bands", status_code=201)
async def create_salary_band(
    body: SalaryBandIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Publish a band. An existing active band for the same position is superseded."""
    _require(current_user, Cap.SALARY_BAND_WRITE)
    return await salary_bands.create_salary_band(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/salary-bands/{band_no}")
async def get_salary_band(
    band_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_BAND_READ)
    doc = await salary_bands.get_salary_band(_company(current_user, company_id), band_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Salary band not found.")
    return doc


@router.patch("/salary-bands/{band_no}")
async def update_salary_band(
    band_no: str,
    body: SalaryBandUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit the descriptive fields or retire a band. The FIGURES are not editable -- publish
    a new band instead, so what was agreed last year still reads as what was agreed."""
    _require(current_user, Cap.SALARY_BAND_WRITE)
    return await salary_bands.update_salary_band(
        current_user, _company(current_user, company_id), band_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# INT-2.6 — the talent pool (Annexure C)
# ─────────────────────────────────────────────────────────────
# Listing is `GET /candidates?talent_pool=true&tags=` -- the pool is a filter on the
# candidate list, not a second collection. These two endpoints manage membership.
@router.post("/candidates/{uk}/talent-pool")
async def set_talent_pool(
    uk: str,
    body: TalentPoolIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Add a candidate to the pool, or take them out.

    Consent is REQUIRED to join and its expiry may not outlive the record's retention
    period. Leaving is unconditional -- consent is a thing somebody may withdraw.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.set_talent_pool(
        current_user, _company(current_user, company_id), uk, body.model_dump())


@router.post("/candidates/{uk}/source-to/{request_no}", status_code=201)
async def source_from_talent_pool(
    uk: str,
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Bring a pooled candidate forward onto a NEW requisition.

    Copies the CV into a new candidate record with its own uk and its own retention clock.
    It never re-points the old one: the original application is a record of what somebody
    applied for and when.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.create_from_pool(
        current_user, _company(current_user, company_id), uk, request_no)


# ─────────────────────────────────────────────────────────────
# INT-2.7 — candidate communications (Annexure C)
# ─────────────────────────────────────────────────────────────
# Everything goes out through hrms_notify_service. There is no second mail path; what is new
# here is the template and the append-only log.
@router.get("/communications")
async def list_communications(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    template_key: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COMM_READ)
    return await comms.list_log(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, template_key=template_key, limit=limit)


@router.get("/communications/templates")
async def list_comm_templates(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The six message templates plus the two consent statements, seeded on first read.

    The consent wording lives here rather than in code so legal can change it without a
    deploy -- which is exactly why editing a template is its own capability.
    """
    _require(current_user, Cap.COMM_READ)
    return {"templates": await comms.list_templates(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.patch("/communications/templates/{key}")
async def update_comm_template(
    key: str,
    body: CommTemplateUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COMM_TEMPLATE_WRITE)
    return await comms.update_template(
        current_user, _company(current_user, company_id), key,
        body.model_dump(exclude_unset=True))


@router.post("/communications/send", status_code=201)
async def send_communication(
    body: CommSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Send one templated message by hand.

    The facts -- name, designation, CTC, joining date -- are DERIVED from the record, never
    accepted from the caller. A sender who could type those in could quote a candidate a
    salary the record does not hold.
    """
    _require(current_user, Cap.COMM_WRITE)
    return await comms.send_template(
        current_user, _company(current_user, company_id), body.candidate_uk,
        body.template_key, variables=body.variables)


# ─────────────────────────────────────────────────────────────
# INT-2.8 — new-hire experience surveys (SOP §10)
# ─────────────────────────────────────────────────────────────
# Read is the AGGREGATE only. There is deliberately no endpoint that returns response rows,
# and the aggregation refuses a figure below SURVEY_MIN_RESPONSES -- a satisfaction survey a
# manager can de-anonymise measures nothing.
@router.get("/surveys")
async def list_surveys(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SURVEY_READ)
    return {"surveys": await surveys.list_surveys(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.get("/surveys/results")
async def survey_results(
    kind: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Mean scores. SCORES ONLY -- never rows, and never below the suppression threshold."""
    _require(current_user, Cap.SURVEY_READ)
    scoped = _company(current_user, company_id)
    return {
        "results": await surveys.aggregate(
            scoped, kind=kind, date_from=date_from, date_to=date_to),
        "response_rate": await surveys.issue_rate(scoped),
    }


# ─────────────────────────────────────────────────────────────
# INT-2.9 — the complete internal KPI set (SOP §10)
# ─────────────────────────────────────────────────────────────
@router.get("/analytics/internal-kpis")
async def analytics_internal_kpis(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    designation_level: Optional[str] = Query(
        None, description="junior | mid | senior | managerial"),
    hr_user_id: Optional[str] = Query(None, description="the assigned HR owner"),
    hod_user_id: Optional[str] = Query(None, description="whoever raised the requisition"),
    status: Optional[str] = Query(None, description="a ReqApproval value"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """All eight SOP KPIs, computed server-side and role-scoped.

    Already present inside `GET /analytics/dashboard`; exposed on its own so the dashboard's
    track filter can fetch just this block rather than the whole payload. Every ratio carries
    `eligible_n` and, where records were left out, `excluded_n` with the reason -- a joiner
    whose 90-day window has not matured is excluded from the denominator, never counted as
    retained.

    ── Phase INT-8 (spec §29) ── the six filters narrow the requisition set, and every
    figure downstream flows from it -- so a filtered KPI can never mix a filtered numerator
    with an unfiltered denominator. The response echoes `filters` so the UI can say what
    the figures cover.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.internal_kpis(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to,
        department_id=department_id, designation_id=designation_id,
        designation_level=designation_level, hr_user_id=hr_user_id,
        hod_user_id=hod_user_id, status=status)


# ─────────────────────────────────────────────────────────────
# INT-2.10 — statutory pre-employment checks (SOP §11)
# ─────────────────────────────────────────────────────────────
@router.get("/probation/{prb_no}/statutory")
async def probation_statutory_state(
    prb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """What is outstanding before this probation can be CONFIRMED.

    Read-only, and surfaced while the probation is still running rather than sprung at the
    moment somebody tries to confirm -- a control the user meets for the first time when it
    blocks them is a control that reads as a bug.
    """
    _require(current_user, Cap.PROBATION_READ)
    scoped = _company(current_user, company_id)
    review = await probation.get_probation(scoped, prb_no)
    if not review:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    return await probation.statutory_state(scoped, review.get("employee_code"))


# ─────────────────────────────────────────────────────────────
# INT-2.11 — the policy register and its review cycle (SOP §14)
# ─────────────────────────────────────────────────────────────
@router.get("/policies")
async def list_policies(
    include_withdrawn: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POLICY_READ)
    return await policies.list_policies(
        _company(current_user, company_id), include_withdrawn=include_withdrawn)


@router.get("/policies/due")
async def due_policy_reviews(
    within_days: int = Query(30, ge=0, le=365),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reviews overdue, and those falling due inside the window."""
    _require(current_user, Cap.POLICY_READ)
    return await policies.due_reviews(
        _company(current_user, company_id), within_days=within_days)


@router.post("/policies", status_code=201)
async def register_policy(
    body: PolicyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.register_policy(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/policies/mine")
async def my_policies(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.6 — the employee-facing HR Policy Library: every published policy applicable to
    the caller, each flagged with whether THEY have acknowledged the current version.
    Declared before /policies/{policy_key} so the static path wins."""
    _require(current_user, Cap.POLICY_READ)
    return await policies.my_policies(current_user, _company(current_user, company_id))


@router.get("/policies/acknowledgements/summary")
async def get_acknowledgement_dashboard(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.12 — pending/completed acknowledgement counts across every policy requiring one.
    Declared before /policies/{policy_key} so the static path wins."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.acknowledgement_dashboard(_company(current_user, company_id))


@router.get("/policies/{policy_key}")
async def get_policy(
    policy_key: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One policy plus its full Modification History (SOP §14's own table)."""
    _require(current_user, Cap.POLICY_READ)
    doc = await policies.get_policy(_company(current_user, company_id), policy_key)
    if not doc:
        raise HTTPException(status_code=404, detail="That policy is not in the register.")
    return doc


@router.post("/policies/{policy_key}/revisions", status_code=201)
async def log_policy_revision(
    policy_key: str,
    body: PolicyRevisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an amendment. It does NOT come into force until it is approved."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.log_revision(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


@router.post("/policies/{policy_key}/approve")
async def approve_policy_revision(
    policy_key: str,
    body: PolicyApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Make a revision the version in force. MD only, and signed."""
    _require(current_user, Cap.POLICY_APPROVE)
    return await policies.approve_revision(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


@router.patch("/policies/{policy_key}/applicability")
async def update_policy_applicability(
    policy_key: str,
    body: PolicyApplicabilityIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.6 — category, applicability and acknowledgement settings. Metadata, not a
    content revision, so `policy.write` alone is enough (no MD approval needed)."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.update_applicability(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


@router.post("/policies/{policy_key}/document")
async def upload_policy_document(
    policy_key: str,
    body: PolicyDocumentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The policy's own PDF, uploaded directly against the register."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.upload_policy_document(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


@router.post("/policies/{policy_key}/acknowledge")
async def acknowledge_policy(
    policy_key: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.6 step 227 — the employee's own act."""
    _require(current_user, Cap.POLICY_ACKNOWLEDGE)
    return await policies.acknowledge_policy(
        current_user, _company(current_user, company_id), policy_key)


@router.get("/policies/{policy_key}/acknowledgements")
async def get_policy_acknowledgements(
    policy_key: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.6 step 230 — HR's completion view for one policy."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.list_acknowledgements(_company(current_user, company_id), policy_key)


# ─────────────────────────────────────────────────────────────
# INT-2.12 — the retention purge (SOP §13)
# ─────────────────────────────────────────────────────────────
# Proposals are written by `scripts/hrms_retention_purge.py`, which defaults to a dry run.
# Execution requires an MD's typed signature here -- the same standard probation confirmation
# holds, because both destroy or end something.
@router.get("/purge-batches")
async def list_purge_batches(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.RETENTION_PURGE)
    return await purge.list_batches(
        _company(current_user, company_id), status=status, limit=limit)


@router.get("/purge-batches/{batch_no}")
async def get_purge_batch(
    batch_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The full proposal, INCLUDING the exact ids. A proposal that says "412 candidates"
    and does not say which is not something anybody can meaningfully approve."""
    _require(current_user, Cap.RETENTION_PURGE)
    doc = await purge.get_batch(_company(current_user, company_id), batch_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Purge batch not found.")
    return doc


@router.post("/purge-batches/{batch_no}/approve")
async def approve_purge_batch(
    batch_no: str,
    body: PurgeApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Authorise the purge and carry it out.

    Redacts rather than hard-deletes: the id and the audit spine survive and the PII fields
    are cleared, stamped with the batch number. An audit trail with dangling references
    proves nothing. It is not reversible.
    """
    _require(current_user, Cap.RETENTION_PURGE)
    return await purge.approve_and_execute(
        current_user, _company(current_user, company_id), batch_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# INT-2.13 — the printable documentation set (SOP §9)
# ─────────────────────────────────────────────────────────────
# ONE endpoint pattern for all five forms, gated by the entity's EXISTING read capability.
# Printing a record is reading it, so a separate `document.generate` capability would create
# a user who may read a probation review but not print it.
@router.get("/records/{entity}/{business_no}/document")
async def generate_record_document(
    entity: str,
    business_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Render one record as a PDF and return a signed URL.

    `entity` is an allow-list key (PRINTABLE_DOCUMENTS), never a collection name -- mapping
    a URL segment onto a collection would let a caller print any collection in the database.
    Every figure on the form is read from the record; nothing is re-entered.
    """
    spec = PRINTABLE_DOCUMENTS.get(entity)
    if not spec:
        raise HTTPException(
            status_code=404,
            detail=(f"There is no printable document for '{entity}'. Available: "
                    f"{', '.join(sorted(PRINTABLE_DOCUMENTS))}."))
    # The capability comes from the TABLE, so a new form cannot be added without deciding
    # who may read it.
    _require(current_user, spec[3])
    return await record_documents.generate(
        current_user, _company(current_user, company_id), entity, business_no)


# =============================================================
# Phase 12 -- background verification
# =============================================================
@router.get("/background-checks")
async def list_background_checks(
    uk: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.list_checks(
        current_user, _company(current_user, company_id),
        uk=uk, status=status, limit=limit)


@router.get("/background-checks/pending")
async def pending_verifications(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The work queue: candidates at Selected or Offer stage, and where each one's
    verification stands."""
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.pending_verifications(
        current_user, _company(current_user, company_id))


@router.post("/background-checks", status_code=201)
async def record_background_check(
    body: BackgroundCheckIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_WRITE)
    return await background.record_check(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/background-checks/{bgv_no}")
async def update_background_check(
    bgv_no: str,
    body: BackgroundCheckUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_WRITE)
    return await background.update_check(
        current_user, _company(current_user, company_id), bgv_no,
        body.model_dump(exclude_unset=True))


@router.get("/candidates/{uk}/verification")
async def candidate_verification(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One candidate's whole verification file, and whether it clears them for an offer."""
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.verification_state(
        _company(current_user, company_id), uk)


@router.post("/candidates/{uk}/verification/decide")
async def decide_verification(
    uk: str,
    body: BackgroundApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR's sign-off, and the step that unlocks the offer.

    Takes a typed signature -- the same standard probation confirmation and the retention
    purge hold, because all three either commit the company or end something.
    """
    _require(current_user, Cap.BACKGROUND_APPROVE)
    return await background.decide_verification(
        current_user, _company(current_user, company_id), uk, body.model_dump())


# -- Candidate CV (Phase 12, requirement 1) --------------------
@router.post("/candidates/{uk}/cv")
async def upload_candidate_cv(
    uk: str,
    body: UploadIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Attach or replace a candidate's CV.

    CANDIDATE_WRITE, not DOCUMENT_WRITE: the CV is part of the candidate record rather than
    a filed document.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.upload_cv(
        current_user, _company(current_user, company_id), uk, {"resume": body.model_dump()})


@router.get("/candidates/{uk}/cv")
async def get_candidate_cv(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived link to the CV. Audited on every open."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.cv_url(
        current_user, _company(current_user, company_id), uk)


@router.get("/candidates/{uk}/attachment")
async def get_candidate_attachment(
    uk: str,
    slot: str = Query(..., pattern="^(photo|certificate)$"),
    index: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived link to the photo or a certificate supplied on the application form."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.attachment_url(
        current_user, _company(current_user, company_id), uk, slot, index)


# =============================================================
# Phase 13 -- interview evidence (spec §10)
# =============================================================
# The report is viewable inline; the recording is watch-only, inline, with no download
# control anywhere.


@router.get("/interviews/{interview_no}/media")
async def get_interview_media(
    interview_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """What evidence is attached to one interview. Sparsh side -- includes storage keys."""
    _require(current_user, Cap.INTERVIEW_READ)
    return await interview_media.get_media(
        _company(current_user, company_id), interview_no)


@router.post("/interviews/{interview_no}/media/{kind}", status_code=201)
async def attach_interview_media(
    interview_no: str,
    kind: str,
    body: InterviewMediaIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Attach the report or the recording. `kind` is `report` or `recording`.

    Gated by `interview.media`, not by `interview.schedule`: booking a conversation and
    deciding what evidence of it is kept are different acts.
    """
    _require(current_user, Cap.INTERVIEW_MEDIA)
    return await interview_media.attach_media(
        current_user, _company(current_user, company_id), interview_no, kind,
        body.model_dump())


@router.delete("/interviews/{interview_no}/media/{kind}")
async def remove_interview_media(
    interview_no: str,
    kind: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_MEDIA)
    return await interview_media.remove_media(
        current_user, _company(current_user, company_id), interview_no, kind)


@router.get("/candidates/{uk}/interviews")
async def candidate_interviews(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every interview for one candidate, with the evidence each carries -- scores,
    panel and remarks included."""
    _require(current_user, Cap.INTERVIEW_READ)
    return {"interviews": await interview_media.interviews_for_candidate(
        _company(current_user, company_id), uk)}


@router.post("/separations", status_code=201)
async def initiate_separation(
    body: ResignationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.18 step 137. Notice is calculated, never supplied — see notice_days_for."""
    _require(current_user, Cap.SEPARATION_INITIATE)
    return await exit_mgmt.initiate_separation(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/separations")
async def list_separations(
    stage: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SEPARATION_READ)
    return await exit_mgmt.list_separations(
        current_user, _company(current_user, company_id),
        stage=stage, employee_code=employee_code, limit=limit)


@router.get("/separations/{sep_no}")
async def get_separation(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SEPARATION_READ)
    return await exit_mgmt.get_separation(current_user, _company(current_user, company_id), sep_no)


@router.patch("/separations/{sep_no}/decision")
async def decide_separation(
    sep_no: str,
    body: SeparationDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.18 steps 140-142: HR/manager records acceptance. Also opens the standard
    departmental clearance tasks the first time this is called (§22.2 step 192)."""
    _require(current_user, Cap.SEPARATION_MANAGE)
    return await exit_mgmt.decide_separation(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.post("/separations/{sep_no}/approve")
async def approve_separation(
    sep_no: str,
    body: SeparationApprovalIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The written approval BR-016 requires before a waiver/early release takes effect."""
    _require(current_user, Cap.SEPARATION_APPROVE)
    return await exit_mgmt.approve_separation(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.post("/separations/{sep_no}/withdraw")
async def withdraw_separation(
    sep_no: str,
    remarks: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SEPARATION_MANAGE)
    return await exit_mgmt.withdraw_separation(
        current_user, _company(current_user, company_id), sep_no, remarks)


@router.post("/separations/{sep_no}/close")
async def close_separation(
    sep_no: str,
    force: bool = Query(False, description="Override incomplete handover/clearance/F&F — BR-025"),
    force_reason: Optional[str] = Query(
        None, description="Required with force: why the exit is closed with work outstanding"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.2 step 199: employee access deactivated, record moves to Alumni/Separated."""
    _require(current_user, Cap.SEPARATION_MANAGE)
    return await exit_mgmt.close_separation(
        current_user, _company(current_user, company_id), sep_no,
        force=force, force_reason=force_reason)


@router.get("/alumni")
async def list_alumni(
    search: Optional[str] = Query(None),
    rehire_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Former employees, written at closure — searchable when rehiring.

    Gated on SEPARATION_READ: knowing who left and whether they would be taken back is
    exit information, and it is not something every employee should be able to browse.
    """
    _require(current_user, Cap.SEPARATION_READ)
    return await exit_mgmt.list_alumni(
        current_user, _company(current_user, company_id),
        search=search, rehire_only=rehire_only, limit=limit)


# ── Handover Plan ──
@router.post("/separations/{sep_no}/handover", status_code=201)
async def create_handover_task(
    sep_no: str,
    body: HandoverTaskIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.HANDOVER_WRITE)
    return await exit_mgmt.create_handover_task(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/handover")
async def list_handover_tasks(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.HANDOVER_READ)
    return await exit_mgmt.list_handover_tasks(
        current_user, _company(current_user, company_id), sep_no)


@router.patch("/separations/{sep_no}/handover/{task_id}")
async def update_handover_task(
    sep_no: str,
    task_id: str,
    body: HandoverTaskUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.HANDOVER_WRITE)
    return await exit_mgmt.update_handover_task(
        current_user, _company(current_user, company_id), sep_no, task_id,
        body.model_dump(exclude_unset=True))


@router.post("/separations/{sep_no}/handover/{task_id}/accept")
async def accept_handover_task(
    sep_no: str,
    task_id: str,
    body: HandoverAcceptIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.2 step 191: the reporting manager's sign-off."""
    _require(current_user, Cap.HANDOVER_APPROVE)
    return await exit_mgmt.accept_handover_task(
        current_user, _company(current_user, company_id), sep_no, task_id, body.model_dump())


# ── Departmental Clearance ──
@router.post("/separations/{sep_no}/clearance", status_code=201)
async def create_clearance_task(
    sep_no: str,
    body: ClearanceTaskIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The five standard tasks (Manager/HR/IT/Admin/Finance) are seeded automatically by
    /decision — this is for '... and any other configured function' (§22.2)."""
    _require(current_user, Cap.CLEARANCE_MANAGE)
    return await exit_mgmt.create_clearance_task(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/clearance")
async def list_clearance_tasks(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLEARANCE_READ)
    return await exit_mgmt.list_clearance_tasks(
        current_user, _company(current_user, company_id), sep_no)


@router.patch("/separations/{sep_no}/clearance/{task_id}")
async def act_on_clearance_task(
    sep_no: str,
    task_id: str,
    body: ClearanceActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The task's owner clears, rejects or waives it."""
    _require(current_user, Cap.CLEARANCE_ACT)
    return await exit_mgmt.act_on_clearance_task(
        current_user, _company(current_user, company_id), sep_no, task_id, body.model_dump())


# ── Asset Return Requests ──
@router.post("/separations/{sep_no}/asset-returns", status_code=201)
async def create_asset_return(
    sep_no: str,
    body: AssetReturnIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.2: the doc allows the employee OR HR to initiate this. SCOPE NOTE (EXIT-1): only
    the HR-side capability is wired so far — see the EMPLOYEE role comment in models/hrms.py
    for why self-initiation is not yet granted."""
    _require(current_user, Cap.CLEARANCE_MANAGE)
    return await exit_mgmt.create_asset_return(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/asset-returns")
async def list_asset_returns(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLEARANCE_READ)
    return await exit_mgmt.list_asset_returns(
        current_user, _company(current_user, company_id), sep_no)


@router.patch("/separations/{sep_no}/asset-returns/{ast_no}")
async def update_asset_return(
    sep_no: str,
    ast_no: str,
    body: AssetReturnUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR/Admin confirms receipt and condition."""
    _require(current_user, Cap.CLEARANCE_ACT)
    return await exit_mgmt.update_asset_return(
        current_user, _company(current_user, company_id), sep_no, ast_no,
        body.model_dump(exclude_unset=True))


# ── Access Clearance ──
@router.post("/separations/{sep_no}/access-clearance", status_code=201)
async def create_access_clearance(
    sep_no: str,
    body: AccessClearanceIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLEARANCE_MANAGE)
    return await exit_mgmt.create_access_clearance(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/access-clearance")
async def list_access_clearances(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLEARANCE_READ)
    return await exit_mgmt.list_access_clearances(
        current_user, _company(current_user, company_id), sep_no)


@router.patch("/separations/{sep_no}/access-clearance/{item_id}")
async def update_access_clearance(
    sep_no: str,
    item_id: str,
    body: AccessClearanceUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLEARANCE_ACT)
    return await exit_mgmt.update_access_clearance(
        current_user, _company(current_user, company_id), sep_no, item_id, body.model_dump())


# ── Exit Interview ──
@router.put("/separations/{sep_no}/exit-interview")
async def save_exit_interview(
    sep_no: str,
    body: ExitInterviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    # HR writes anybody's; the leaving employee submits their own. The service decides
    # which of those the caller actually is, by ownership.
    _require_any(current_user, Cap.EXIT_INTERVIEW_WRITE, Cap.EXIT_INTERVIEW_SUBMIT)
    return await exit_mgmt.save_exit_interview(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/exit-interview")
async def get_exit_interview(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EXIT_INTERVIEW_READ)
    doc = await exit_mgmt.get_exit_interview(current_user, _company(current_user, company_id), sep_no)
    if not doc:
        raise HTTPException(status_code=404, detail="No exit interview recorded yet.")
    return doc


# ── Full & Final Settlement ──
@router.put("/separations/{sep_no}/fnf")
async def save_fnf(
    sep_no: str,
    body: FnfInput,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.21: the maker half of BR-021. No payroll engine exists (§7.13) — see FnfInput's
    docstring for what this can and cannot compute."""
    _require(current_user, Cap.FNF_PREPARE)
    return await exit_mgmt.save_fnf(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.get("/separations/{sep_no}/fnf")
async def get_fnf(
    sep_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.FNF_READ)
    return await exit_mgmt.get_fnf(current_user, _company(current_user, company_id), sep_no)


@router.post("/separations/{sep_no}/fnf/approve")
async def approve_fnf(
    sep_no: str,
    body: FnfDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Finance's checker gate (BR-021)."""
    _require(current_user, Cap.FNF_APPROVE)
    return await exit_mgmt.approve_fnf(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


@router.post("/separations/{sep_no}/fnf/paid")
async def mark_fnf_paid(
    sep_no: str,
    body: FnfPaidIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Recording the payment run, after Finance has already approved the total."""
    _require(current_user, Cap.FNF_PREPARE)
    return await exit_mgmt.mark_fnf_paid(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9)
# ─────────────────────────────────────────────────────────────
@router.get("/attendance/shift-policy")
async def get_shift_policy(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ATTENDANCE_READ)
    return await attendance_mgmt.get_shift_policy(_company(current_user, company_id))


@router.put("/attendance/shift-policy")
async def save_shift_policy(
    body: dict,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.8's timing/grace numbers, adjustable — see the Phase ATT-1 module docstring."""
    _require(current_user, Cap.LEAVE_POLICY_MANAGE)
    return await attendance_mgmt.save_shift_policy(
        current_user, _company(current_user, company_id), body)


@router.post("/attendance/mark", status_code=201)
async def mark_attendance(
    body: AttendanceMarkIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ATTENDANCE_MARK)
    return await attendance_mgmt.mark_attendance(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/attendance")
async def list_attendance(
    employee_code: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ATTENDANCE_READ)
    return await attendance_mgmt.list_attendance(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        start_date=start_date, end_date=end_date, status=status, limit=limit)


@router.get("/attendance/late-coming")
async def late_coming_summary(
    employee_code: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.9: calendar marker + monthly late-coming card data."""
    _require(current_user, Cap.ATTENDANCE_READ)
    return await attendance_mgmt.late_coming_summary(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        start_date=start_date, end_date=end_date)


@router.post("/attendance/regularizations", status_code=201)
async def request_regularization(
    body: RegularizationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.9 step 63-64: self-service, the same reasoning SEPARATION_INITIATE established."""
    _require(current_user, Cap.ATTENDANCE_REGULARIZE_REQUEST)
    return await attendance_mgmt.request_regularization(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/attendance/regularizations")
async def list_regularizations(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ATTENDANCE_REGULARIZE_REQUEST)
    return await attendance_mgmt.list_regularizations(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, limit=limit)


@router.patch("/attendance/regularizations/{req_no}")
async def act_on_regularization(
    req_no: str,
    body: RegularizationActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.9 steps 66-68: manager first, HR final — see hrms_attendance_service for the order."""
    _require(current_user, Cap.ATTENDANCE_REGULARIZE_APPROVE)
    return await attendance_mgmt.act_on_regularization(
        current_user, _company(current_user, company_id), req_no, body.model_dump())


@router.post("/attendance/od", status_code=201)
async def request_od(
    body: OdRequestIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.OD_REQUEST)
    return await attendance_mgmt.request_od(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/attendance/od")
async def list_od_requests(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.OD_REQUEST)
    return await attendance_mgmt.list_od_requests(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, limit=limit)


@router.post("/attendance/od/{od_no}/action")
async def act_on_od(
    od_no: str,
    body: OdActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.OD_APPROVE)
    return await attendance_mgmt.act_on_od(
        current_user, _company(current_user, company_id), od_no, body.model_dump())


@router.get("/attendance/closure/{period}")
async def closure_dashboard(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.12 steps 84-85: what is still open before this period can be locked."""
    _require(current_user, Cap.ATTENDANCE_LOCK)
    return await attendance_mgmt.closure_dashboard(
        current_user, _company(current_user, company_id), period)


@router.post("/attendance/closure/{period}/lock")
async def lock_period(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ATTENDANCE_LOCK)
    return await attendance_mgmt.lock_period(
        current_user, _company(current_user, company_id), period)


@router.post("/attendance/closure/{period}/unlock")
async def unlock_period(
    period: str,
    body: AttendanceUnlockIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Post-lock changes require an authorised, reasoned reopen (§7.12 BR)."""
    _require(current_user, Cap.ATTENDANCE_LOCK)
    return await attendance_mgmt.unlock_period(
        current_user, _company(current_user, company_id), period, body.reason)


# ── §22.8 — leave-type policy register ──
@router.get("/leave/types")
async def list_leave_types(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LEAVE_READ)
    return await leave_mgmt.list_leave_types(current_user, _company(current_user, company_id))


@router.put("/leave/types/{code}")
async def save_leave_type(
    code: str,
    body: LeaveTypeConfigIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Policy values only — see the Phase ATT-1 module docstring for why none of these
    numbers are frozen defaults baked into logic."""
    _require(current_user, Cap.LEAVE_POLICY_MANAGE)
    payload = body.model_dump()
    payload["code"] = code
    return await leave_mgmt.save_leave_type(
        current_user, _company(current_user, company_id), payload)


@router.get("/leave/balances/{employee_code}")
async def get_leave_balances(
    employee_code: str,
    year: Optional[int] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LEAVE_READ)
    return await leave_mgmt.get_leave_balances(
        current_user, _company(current_user, company_id), employee_code, year)


@router.post("/leave/balances/adjust")
async def adjust_leave_balance(
    body: LeaveBalanceAdjustIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LEAVE_POLICY_MANAGE)
    return await leave_mgmt.adjust_leave_balance(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/leave", status_code=201)
async def apply_leave(
    body: LeaveApplyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.10 step 70: self-service, the same reasoning SEPARATION_INITIATE established."""
    _require(current_user, Cap.LEAVE_APPLY)
    return await leave_mgmt.apply_leave(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/leave")
async def list_leaves(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    leave_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LEAVE_READ)
    return await leave_mgmt.list_leaves(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, leave_type=leave_type, limit=limit)


@router.patch("/leave/{leave_no}")
async def act_on_leave(
    leave_no: str,
    body: LeaveActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.10 steps 73-75: manager first, HR final."""
    _require(current_user, Cap.LEAVE_APPROVE)
    return await leave_mgmt.act_on_leave(
        current_user, _company(current_user, company_id), leave_no, body.model_dump())


@router.post("/leave/{leave_no}/cancel")
async def cancel_leave(
    leave_no: str,
    body: LeaveCancelIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.10 step 76: controlled withdrawal, restoring the balance (or C-Off batches) it
    consumed."""
    _require(current_user, Cap.LEAVE_APPLY)
    return await leave_mgmt.cancel_leave(
        current_user, _company(current_user, company_id), leave_no, body.reason)


# ── §7.11 — Compensatory Off ──
@router.post("/coff/earn", status_code=201)
async def request_coff_earn(
    body: CoffEarnIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COFF_EARN_REQUEST)
    return await leave_mgmt.request_coff_earn(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/coff/ledger")
async def list_coff_ledger(
    employee_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LEAVE_READ)
    return await leave_mgmt.list_coff_ledger(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        status=status, limit=limit)


@router.post("/coff/earn/{batch_id}/action")
async def act_on_coff_earn(
    batch_id: str,
    body: CoffEarnActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COFF_APPROVE)
    return await leave_mgmt.act_on_coff_earn(
        current_user, _company(current_user, company_id), batch_id, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20)
# ─────────────────────────────────────────────────────────────
@router.post("/movements", status_code=201)
async def initiate_movement(
    body: MovementIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.16 steps 120-122. The current value is looked up server-side, never supplied."""
    _require(current_user, Cap.MOVEMENT_INITIATE)
    return await movement_mgmt.initiate_movement(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/movements")
async def list_movements(
    employee_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Also catches up any approved movement whose effective date has arrived — there is no
    scheduler in this codebase, so a page load is what applies a due movement (§7.16 step 125).
    """
    _require(current_user, Cap.MOVEMENT_READ)
    resolved_company = _company(current_user, company_id)
    await movement_mgmt.apply_due_movements(resolved_company)
    return await movement_mgmt.list_movements(
        current_user, resolved_company, employee_code=employee_code, status=status, limit=limit)


@router.patch("/movements/{move_no}")
async def act_on_movement(
    move_no: str,
    body: MovementActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.MOVEMENT_APPROVE)
    return await movement_mgmt.act_on_movement(
        current_user, _company(current_user, company_id), move_no, body.model_dump())


# ── Discipline / Redressal ──
@router.post("/discipline", status_code=201)
async def create_discipline_case(
    body: DisciplineCaseIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.17 step 128. A POSH/Harassment category is ALWAYS Restricted regardless of what is
    passed, and creating one additionally requires DISCIPLINE_POSH_* — enforced inside the
    service, since the capability needed depends on the case's OWN category, not a fixed one
    this route can check up front."""
    _require(current_user, Cap.DISCIPLINE_MANAGE)
    return await discipline_mgmt.create_case(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/discipline")
async def list_discipline_cases(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Restricted/POSH cases are silently excluded for a caller without POSH access — see
    hrms_discipline_service.list_cases."""
    _require(current_user, Cap.DISCIPLINE_READ)
    return await discipline_mgmt.list_cases(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, limit=limit)


@router.get("/discipline/{case_no}")
async def get_discipline_case(
    case_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DISCIPLINE_READ)
    return await discipline_mgmt.get_case(
        current_user, _company(current_user, company_id), case_no)


@router.post("/discipline/{case_no}/investigate")
async def add_investigation_note(
    case_no: str,
    body: DisciplineInvestigationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DISCIPLINE_MANAGE)
    return await discipline_mgmt.add_investigation_note(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


@router.post("/discipline/{case_no}/recommend")
async def record_recommendation(
    case_no: str,
    body: DisciplineRecommendationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DISCIPLINE_MANAGE)
    return await discipline_mgmt.record_recommendation(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


@router.post("/discipline/{case_no}/decide")
async def decide_discipline_case(
    case_no: str,
    body: DisciplineDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.17 step 133: management's separate approve-and-implement act."""
    _require(current_user, Cap.DISCIPLINE_DECIDE)
    return await discipline_mgmt.decide_case(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


@router.post("/discipline/{case_no}/close")
async def close_discipline_case(
    case_no: str,
    body: DisciplineCloseIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DISCIPLINE_MANAGE)
    return await discipline_mgmt.close_case(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


@router.get("/discipline/employee/{employee_code}/summary")
async def discipline_employee_summary(
    employee_code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.17 step 136: the permission-controlled summary Employee 360° will eventually
    embed — full 360° aggregation (§6) is a separate gap this does not close."""
    _require(current_user, Cap.DISCIPLINE_READ)
    return await discipline_mgmt.employee_summary(
        current_user, _company(current_user, company_id), employee_code)


# ── Absconding / Abandonment ──
@router.get("/absconding/policy")
async def get_absconding_policy(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ABSCONDING_READ)
    return await absconding_mgmt.get_absconding_policy(_company(current_user, company_id))


@router.put("/absconding/policy")
async def save_absconding_policy(
    body: dict,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.19's day-count/window numbers, adjustable — see DEFAULT_ABSCONDING_POLICY. Gated on
    ABSCONDING_MANAGE (not DECIDE): this is routine policy configuration, the same level HR
    holds for LEAVE_POLICY_MANAGE, not the case-by-case final-action sign-off."""
    _require(current_user, Cap.ABSCONDING_MANAGE)
    return await absconding_mgmt.save_absconding_policy(
        current_user, _company(current_user, company_id), body)


@router.post("/absconding", status_code=201)
async def flag_absconding_case(
    body: AbscondingFlagIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ABSCONDING_MANAGE)
    return await absconding_mgmt.flag_case(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/absconding")
async def list_absconding_cases(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ABSCONDING_READ)
    return await absconding_mgmt.list_cases(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, limit=limit)


@router.get("/absconding/{case_no}")
async def get_absconding_case(
    case_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ABSCONDING_READ)
    return await absconding_mgmt.get_case(
        current_user, _company(current_user, company_id), case_no)


@router.post("/absconding/{case_no}/contact")
async def log_absconding_contact(
    case_no: str,
    body: AbscondingContactIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ABSCONDING_MANAGE)
    return await absconding_mgmt.log_contact_attempt(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


@router.post("/absconding/{case_no}/warning/{stage}")
async def send_absconding_warning(
    case_no: str,
    stage: str,
    body: AbscondingWarningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.19 steps 150-152. `stage` is 'First' or 'Second'; the service enforces the
    configured window has elapsed since the prior stage."""
    _require(current_user, Cap.ABSCONDING_MANAGE)
    return await absconding_mgmt.send_warning(
        current_user, _company(current_user, company_id), case_no, stage, body.model_dump())


@router.post("/absconding/{case_no}/final-action")
async def absconding_final_action(
    case_no: str,
    body: AbscondingFinalActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.19 step 153: the authorised final decision — resolves the case or hands off to
    Exit Management (exit_type=Absconding)."""
    _require(current_user, Cap.ABSCONDING_DECIDE)
    return await absconding_mgmt.final_action(
        current_user, _company(current_user, company_id), case_no, body.model_dump())


# ── Retirement alert (§7.20) ──
@router.get("/retirement/policy")
async def get_retirement_policy(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.RETIREMENT_ALERT_READ)
    return await retirement_mgmt.get_retirement_policy(_company(current_user, company_id))


@router.put("/retirement/policy")
async def save_retirement_policy(
    body: RetirementPolicyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The retirement age itself is NOT frozen by the BA doc — see RetirementPolicyIn."""
    _require(current_user, Cap.MOVEMENT_APPROVE)
    return await retirement_mgmt.save_retirement_policy(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/retirement/upcoming")
async def list_upcoming_retirements(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.RETIREMENT_ALERT_READ)
    return await retirement_mgmt.list_upcoming_retirements(
        current_user, _company(current_user, company_id))


# ── §7.20 step 157 — Demise/Missing nominee & legal documentation ──
@router.put("/separations/{sep_no}/nominee-details")
async def save_nominee_details(
    sep_no: str,
    body: NomineeDetailsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SEPARATION_MANAGE)
    return await exit_mgmt.save_nominee_details(
        current_user, _company(current_user, company_id), sep_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7)
# ─────────────────────────────────────────────────────────────
@router.get("/salary-components")
async def list_salary_components(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_STRUCTURE_READ)
    return await payroll_mgmt.list_salary_components(
        current_user, _company(current_user, company_id))


@router.put("/salary-components/{code}")
async def save_salary_component(
    code: str,
    body: SalaryComponentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.7: payroll is component-driven, not a fixed set of fields — this is the master."""
    _require(current_user, Cap.SALARY_STRUCTURE_MANAGE)
    payload = body.model_dump()
    payload["code"] = code
    return await payroll_mgmt.save_salary_component(
        current_user, _company(current_user, company_id), payload)


@router.put("/salary-structures")
async def save_salary_structure(
    body: SalaryStructureIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_STRUCTURE_MANAGE)
    return await payroll_mgmt.save_salary_structure(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/salary-structures/{employee_code}")
async def get_salary_structure_history(
    employee_code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Full history, newest first — a structure is never edited in place (§7.16's "never
    overwrite" discipline applies here too)."""
    _require(current_user, Cap.SALARY_STRUCTURE_READ)
    return await payroll_mgmt.list_structure_history(
        current_user, _company(current_user, company_id), employee_code)


# ── Payroll runs ──
@router.post("/payroll/runs", status_code=201)
async def create_payroll_run(
    body: PayrollRunCreateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_PROCESS)
    return await payroll_mgmt.create_run(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/payroll/runs")
async def list_payroll_runs(
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_READ)
    return await payroll_mgmt.list_runs(current_user, _company(current_user, company_id), limit)


@router.get("/payroll/runs/{period}")
async def get_payroll_run(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_READ)
    return await payroll_mgmt.get_run(current_user, _company(current_user, company_id), period)


@router.post("/payroll/runs/{period}/calculate")
async def calculate_payroll(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.13 steps 91-94, safe to call again to rerun after resolving exceptions (step 96)."""
    _require(current_user, Cap.PAYROLL_PROCESS)
    return await payroll_mgmt.calculate_payroll(
        current_user, _company(current_user, company_id), period)


@router.get("/payroll/runs/{period}/records")
async def list_payroll_records(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_READ)
    return await payroll_mgmt.list_records(
        current_user, _company(current_user, company_id), period)


@router.patch("/payroll/runs/{period}/records/{employee_code}")
async def adjust_payroll_record(
    period: str,
    employee_code: str,
    body: PayrollRecordAdjustIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The maker's hand-entered statutory/one-off figures — no statutory engine exists yet
    (§7.13 BR: "requires payroll workshop")."""
    _require(current_user, Cap.PAYROLL_PROCESS)
    return await payroll_mgmt.adjust_record(
        current_user, _company(current_user, company_id), period, employee_code,
        body.model_dump(exclude_unset=True))


@router.put("/payroll/runs/{period}/records/{employee_code}/adjustments")
async def set_payroll_adjustments(
    period: str,
    employee_code: str,
    body: PayrollAdjustmentsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.7 — arbitrary named earning/deduction lines against the salary component master,
    alongside the fixed PF/ESI/arrears/etc. fields `adjust_payroll_record` already covers."""
    _require(current_user, Cap.PAYROLL_PROCESS)
    return await payroll_mgmt.set_adjustments(
        current_user, _company(current_user, company_id), period, employee_code,
        body.model_dump())


@router.post("/payroll/runs/{period}/decision")
async def decide_payroll_run(
    period: str,
    body: PayrollApprovalIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.13 steps 97-98: the checker's approval also locks the run."""
    _require(current_user, Cap.PAYROLL_APPROVE)
    return await payroll_mgmt.decide_run(
        current_user, _company(current_user, company_id), period, body.model_dump())


# ── Phase PAYSLIP-1 (§22.7, SM-HR-031/SM-HR-064) — the itemised payslip ──
@router.get("/payslips/{period}")
async def get_payslip(
    period: str,
    employee_code: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """An employee reads their OWN payslip (employee_code is ignored and resolved from
    their own profile — see hrms_payslip_service._resolve_employee_code); HR/Payroll must
    name one."""
    _require(current_user, Cap.PAYROLL_READ)
    return await payslip_mgmt.get_payslip(
        current_user, _company(current_user, company_id), period, employee_code)


@router.get("/payroll/runs/{period}/payslips")
async def list_payslips(
    period: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every payslip in one run — bulk, HR-only (hrms_payslip_service.list_payslips itself
    rejects an EMPLOYEE-role caller regardless of what the route allows)."""
    _require(current_user, Cap.PAYROLL_READ)
    return await payslip_mgmt.list_payslips(current_user, _company(current_user, company_id), period)


@router.get("/payslip-template")
async def get_payslip_template(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_READ)
    return await payslip_mgmt.get_payslip_template(_company(current_user, company_id))


@router.put("/payslip-template")
async def save_payslip_template(
    body: PayslipTemplateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PAYROLL_PROCESS)
    return await payslip_mgmt.save_payslip_template(
        current_user, _company(current_user, company_id), body.model_dump())


# ── Salary Advance ──
@router.get("/advances/policy")
async def get_advance_policy(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ADVANCE_READ)
    return await advance_mgmt.get_advance_policy(_company(current_user, company_id))


@router.put("/advances/policy")
async def save_advance_policy(
    body: AdvancePolicyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.14's 40%/window/quarter numbers, adjustable — see DEFAULT_ADVANCE_POLICY."""
    _require(current_user, Cap.ADVANCE_APPROVE)
    return await advance_mgmt.save_advance_policy(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/advances/eligibility/{employee_code}")
async def check_advance_eligibility(
    employee_code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Shown before the request form even opens (§7.14 steps 101-104)."""
    _require(current_user, Cap.ADVANCE_REQUEST)
    return await advance_mgmt.check_eligibility(
        current_user, _company(current_user, company_id), employee_code)


@router.post("/advances", status_code=201)
async def request_advance(
    body: SalaryAdvanceIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ADVANCE_REQUEST)
    return await advance_mgmt.request_advance(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/advances")
async def list_advances(
    status: Optional[str] = Query(None),
    employee_code: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ADVANCE_READ)
    return await advance_mgmt.list_advances(
        current_user, _company(current_user, company_id), status=status,
        employee_code=employee_code, limit=limit)


@router.get("/advances/{adv_no}")
async def get_advance(
    adv_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ADVANCE_READ)
    return await advance_mgmt.get_advance(current_user, _company(current_user, company_id), adv_no)


@router.post("/advances/{adv_no}/action")
async def act_on_advance(
    adv_no: str,
    body: SalaryAdvanceActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The normal Reporting-Manager/HR approval tier (§7.14 step 106)."""
    _require(current_user, Cap.ADVANCE_APPROVE)
    return await advance_mgmt.act_on_advance(
        current_user, _company(current_user, company_id), adv_no, body.model_dump())


@router.post("/advances/{adv_no}/action-emergency")
async def act_on_advance_emergency(
    adv_no: str,
    body: SalaryAdvanceActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The separate "Director HR / Finance" emergency route §7.14 names explicitly."""
    _require(current_user, Cap.ADVANCE_APPROVE_EMERGENCY)
    return await advance_mgmt.act_on_advance(
        current_user, _company(current_user, company_id), adv_no, body.model_dump())


# ── Variable Pay Quarterly ──
@router.get("/variable-pay/policy")
async def get_variable_pay_policy(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_READ)
    return await vp_mgmt.get_variable_pay_policy(_company(current_user, company_id))


@router.put("/variable-pay/policy")
async def save_variable_pay_policy(
    body: VariablePayPolicyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.15's ORM/IRM thresholds and 75/25 split, adjustable — see DEFAULT_VARIABLE_PAY_POLICY."""
    _require(current_user, Cap.VARIABLE_PAY_APPROVE)
    return await vp_mgmt.save_variable_pay_policy(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/variable-pay/quarters", status_code=201)
async def create_variable_pay_quarter(
    body: VariablePayQuarterCreateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_PROCESS)
    return await vp_mgmt.create_quarter(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/variable-pay/quarters")
async def list_variable_pay_quarters(
    limit: int = Query(50, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_READ)
    return await vp_mgmt.list_quarters(current_user, _company(current_user, company_id), limit)


@router.get("/variable-pay/quarters/{quarter}")
async def get_variable_pay_quarter(
    quarter: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_READ)
    return await vp_mgmt.get_quarter(current_user, _company(current_user, company_id), quarter)


@router.post("/variable-pay/quarters/{quarter}/records", status_code=201)
async def save_variable_pay_record(
    quarter: str,
    body: VariablePayRecordIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.15 step 111: enter (or re-enter) one employee's IRM score and quarterly target."""
    _require(current_user, Cap.VARIABLE_PAY_PROCESS)
    return await vp_mgmt.save_record(
        current_user, _company(current_user, company_id), quarter, body.model_dump())


@router.get("/variable-pay/quarters/{quarter}/records")
async def list_variable_pay_records(
    quarter: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_READ)
    return await vp_mgmt.list_records(current_user, _company(current_user, company_id), quarter)


@router.post("/variable-pay/quarters/{quarter}/calculate")
async def calculate_variable_pay(
    quarter: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_PROCESS)
    return await vp_mgmt.calculate_quarter(
        current_user, _company(current_user, company_id), quarter)


@router.post("/variable-pay/quarters/{quarter}/decision")
async def decide_variable_pay_quarter(
    quarter: str,
    body: VariablePayApprovalIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_APPROVE)
    return await vp_mgmt.decide_quarter(
        current_user, _company(current_user, company_id), quarter, body.model_dump())


@router.get("/variable-pay/hold-ledger")
async def list_variable_pay_hold_ledger(
    employee_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.VARIABLE_PAY_READ)
    return await vp_mgmt.list_hold_ledger(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        status=status, limit=limit)


@router.post("/variable-pay/hold-ledger/{hold_id}/action")
async def act_on_variable_pay_hold(
    hold_id: str,
    body: VariablePayHoldActionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§7.15 step 119: release or forfeit at FY-end/an eligibility milestone."""
    _require(current_user, Cap.VARIABLE_PAY_HOLD_MANAGE)
    return await vp_mgmt.act_on_hold(
        current_user, _company(current_user, company_id), hold_id, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase PIP-1 — Performance Improvement Plan (§22.5)
# ─────────────────────────────────────────────────────────────
@router.post("/pip", status_code=201)
async def initiate_pip(
    body: PipCreateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PIP_MANAGE)
    return await pip_mgmt.initiate_pip(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/pip")
async def list_pips(
    employee_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PIP_READ)
    return await pip_mgmt.list_pips(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        status=status, limit=limit)


@router.get("/pip/{pip_no}")
async def get_pip(
    pip_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PIP_READ)
    return await pip_mgmt.get_pip(current_user, _company(current_user, company_id), pip_no)


@router.post("/pip/{pip_no}/acknowledge")
async def acknowledge_pip(
    pip_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.5 step 217 — self-service, enforced to the plan's OWN employee."""
    _require(current_user, Cap.PIP_ACKNOWLEDGE)
    return await pip_mgmt.acknowledge_pip(
        current_user, _company(current_user, company_id), pip_no)


@router.post("/pip/{pip_no}/reviews", status_code=201)
async def add_pip_review(
    pip_no: str,
    body: PipReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.5 step 218."""
    _require(current_user, Cap.PIP_MANAGE)
    return await pip_mgmt.add_review(
        current_user, _company(current_user, company_id), pip_no, body.model_dump())


@router.post("/pip/{pip_no}/decision")
async def decide_pip(
    pip_no: str,
    body: PipDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.5 step 220."""
    _require(current_user, Cap.PIP_DECIDE)
    return await pip_mgmt.decide_pip(
        current_user, _company(current_user, company_id), pip_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase GMP-1 — Group Mediclaim Policy
# ─────────────────────────────────────────────────────────────
@router.get("/gmp/{employee_code}")
async def get_gmp_enrolment(
    employee_code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """An employee may read their own enrolment; HR/INTERNAL read the company's."""
    _require(current_user, Cap.GMP_READ)
    return await gmp_mgmt.get_gmp(current_user, _company(current_user, company_id), employee_code)


@router.put("/gmp/{employee_code}")
async def save_gmp_enrolment(
    employee_code: str,
    body: GmpIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.GMP_WRITE)
    return await gmp_mgmt.save_gmp(
        current_user, _company(current_user, company_id), employee_code, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase 360-1 — Employee 360° (§6)
# ─────────────────────────────────────────────────────────────
@router.get("/employees/{user_id}/360")
async def get_employee_360(
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One aggregated workspace over every module that already tracks this employee.
    No new capability gate: the base profile call decides who may open this at all (an
    inherent right for their own record, EMPLOYEE_READ otherwise), and each section inside
    is included only if the caller separately holds that section's own read capability —
    the same "restricted, permission-controlled summary" every source module already
    promises on its own screen."""
    return await employee_360_mgmt.get_employee_360(
        current_user, _company(current_user, company_id), user_id)


# ─────────────────────────────────────────────────────────────
# Phase ACCESS-1 — User / Role / Permission Administration (SM-HR-051)
# ─────────────────────────────────────────────────────────────
@router.get("/access/role-matrix")
async def hrms_role_matrix(current_user: dict = Depends(get_current_user)):
    """Read-only "review access" table — which capabilities each HRMS role holds, sourced
    directly from ROLE_CAPABILITIES so it can never drift from what the gates enforce."""
    _require(current_user, Cap.MODULE_ADMIN)
    return access_admin_mgmt.get_role_matrix()


@router.put("/access/employees/{user_id}/governance-role")
async def hrms_set_governance_role(
    user_id: str,
    body: GovernanceRoleIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Assign the HOD/HR/FINANCE/MD governance ladder position that `hrms_role()` resolves
    a client-side user's HRMS role from. Gated on MODULE_ADMIN, the same capability the
    module's own settings-administration surfaces resolve to — matching the BA doc's
    "Users: System Admin" line for this screen."""
    _require(current_user, Cap.MODULE_ADMIN)
    return await access_admin_mgmt.set_governance_role(
        current_user, user_id, _company(current_user, company_id), body.governance_role)


# ─────────────────────────────────────────────────────────────
# Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041)
# ─────────────────────────────────────────────────────────────
@router.get("/letters/templates")
async def list_letter_templates(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LETTER_MANAGE)
    return {"templates": await letter_mgmt.list_templates(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.put("/letters/templates/{key}")
async def save_letter_template(
    key: str,
    body: LetterTemplateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LETTER_MANAGE)
    return await letter_mgmt.save_template(
        current_user, _company(current_user, company_id), key, body.model_dump())


@router.post("/letters/preview")
async def preview_letter(
    body: LetterPreviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Preview — a pure render, nothing persisted."""
    _require(current_user, Cap.LETTER_MANAGE)
    return await letter_mgmt.preview_letter(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/letters", status_code=201)
async def generate_letter(
    body: LetterGenerateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Generate — produces a Draft, still regenerable until issued."""
    _require(current_user, Cap.LETTER_MANAGE)
    return await letter_mgmt.generate_letter(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/letters")
async def list_letters(
    employee_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LETTER_READ)
    return {"letters": await letter_mgmt.list_letters(
        current_user, _company(current_user, company_id),
        employee_code=employee_code, status=status, limit=limit)}


@router.get("/letters/{letter_no}")
async def get_letter(
    letter_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.LETTER_READ)
    return await letter_mgmt.get_letter(
        current_user, _company(current_user, company_id), letter_no)


@router.post("/letters/{letter_no}/issue")
async def issue_letter(
    letter_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue — the point of no return; from here the letter is immutable."""
    _require(current_user, Cap.LETTER_MANAGE)
    return await letter_mgmt.issue_letter(
        current_user, _company(current_user, company_id), letter_no)


@router.post("/letters/{letter_no}/reissue", status_code=201)
async def reissue_letter(
    letter_no: str,
    body: LetterReissueIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reissue — supersedes this letter and issues a new version."""
    _require(current_user, Cap.LETTER_MANAGE)
    return await letter_mgmt.reissue_letter(
        current_user, _company(current_user, company_id), letter_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Phase ORIENT-1 — Orientation & Training (§22.3, screen SM-HR-057)
# ─────────────────────────────────────────────────────────────
@router.get("/orientation/plans")
async def list_orientation_plans(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INDUCTION_WRITE)
    return {"plans": await orientation_mgmt.list_plans(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.post("/orientation/plans", status_code=201)
async def create_orientation_plan(
    body: OrientationPlanIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INDUCTION_WRITE)
    return await orientation_mgmt.save_plan(
        current_user, _company(current_user, company_id), None, body.model_dump())


@router.put("/orientation/plans/{plan_no}")
async def update_orientation_plan(
    plan_no: str,
    body: OrientationPlanIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INDUCTION_WRITE)
    return await orientation_mgmt.save_plan(
        current_user, _company(current_user, company_id), plan_no, body.model_dump())


@router.get("/orientation/assignments")
async def list_orientation_assignments(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INDUCTION_READ)
    return {"assignments": await orientation_mgmt.list_assignments(
        current_user, _company(current_user, company_id), status=status, limit=limit)}


@router.get("/orientation/assignments/{employee_code}")
async def get_orientation_assignment(
    employee_code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INDUCTION_READ)
    return await orientation_mgmt.get_assignment(
        current_user, _company(current_user, company_id), employee_code)


@router.post("/orientation/assignments/{employee_code}/schedule")
async def schedule_orientation_item(
    employee_code: str,
    body: OrientationScheduleIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.3 step 201."""
    _require(current_user, Cap.INDUCTION_WRITE)
    return await orientation_mgmt.schedule_item(
        current_user, _company(current_user, company_id), employee_code,
        body.item_id, body.trainer, body.scheduled_at)


@router.post("/orientation/assignments/{employee_code}/complete")
async def complete_orientation_item(
    employee_code: str,
    body: OrientationCompleteIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.3 step 203."""
    _require(current_user, Cap.INDUCTION_WRITE)
    return await orientation_mgmt.complete_item(
        current_user, _company(current_user, company_id), employee_code,
        body.item_id, body.remarks)


@router.post("/orientation/assignments/{employee_code}/waive")
async def waive_orientation_item(
    employee_code: str,
    body: OrientationWaiveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.3 step 204."""
    _require(current_user, Cap.INDUCTION_WRITE)
    return await orientation_mgmt.waive_item(
        current_user, _company(current_user, company_id), employee_code,
        body.item_id, body.reason)


# ─────────────────────────────────────────────────────────────
# Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4, screen SM-HR-058)
# ─────────────────────────────────────────────────────────────
@router.get("/pulse-surveys/config")
async def get_pulse_config(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PULSE_MANAGE)
    return {"questions": await pulse_mgmt.get_questions(_company(current_user, company_id))}


@router.put("/pulse-surveys/config")
async def save_pulse_config(
    body: PulseConfigIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PULSE_MANAGE)
    return {"questions": await pulse_mgmt.save_questions(
        current_user, _company(current_user, company_id), body.questions)}


@router.get("/pulse-surveys/summary")
async def get_pulse_summary(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.4 step 213."""
    _require(current_user, Cap.PULSE_MANAGE)
    return await pulse_mgmt.get_summary(_company(current_user, company_id))


@router.get("/pulse-surveys")
async def list_pulse_surveys(
    employee_code: Optional[str] = Query(None),
    milestone: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    follow_up_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PULSE_READ)
    return {"surveys": await pulse_mgmt.list_responses(
        current_user, _company(current_user, company_id), employee_code=employee_code,
        milestone=milestone, status=status, follow_up_only=follow_up_only, limit=limit)}


@router.get("/pulse-surveys/{employee_code}/{milestone}")
async def get_pulse_survey(
    employee_code: str,
    milestone: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PULSE_READ)
    return await pulse_mgmt.get_response(
        current_user, _company(current_user, company_id), employee_code, milestone)


@router.post("/pulse-surveys/{employee_code}/{milestone}/submit")
async def submit_pulse_survey(
    employee_code: str,
    milestone: str,
    body: PulseSubmitIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """§22.4 step 210 — self-service, enforced to the survey's OWN employee."""
    _require(current_user, Cap.PULSE_SUBMIT)
    return await pulse_mgmt.submit_response(
        current_user, _company(current_user, company_id), employee_code, milestone,
        body.scores, body.comment)


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 1 — Need Mapping → Manpower Requisition → feasibility
#
# A separate track with its own capabilities. A client-side caller reaches these and
# nothing else: `capabilities_for` narrows them to CLIENT_TRACK_CAPS, which holds the read
# and write capabilities below and no others, so every other endpoint in this router
# answers them 403.
#
# Every handler passes `scope_company_id`, which pins a client-side caller to their own
# company and ignores one they name. That is what makes a guessed requisition number
# unreachable rather than merely hidden.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-requisitions")
async def list_client_requisitions(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """A client's own requisitions; for Sparsh staff, the queue across clients."""
    _require(current_user, Cap.CLIENT_REQUISITION_READ)
    return await client_reqs.list_client_requisitions(
        current_user, scope_company_id(current_user, company_id),
        status=status, limit=limit)


@router.post("/client-requisitions", status_code=201)
async def create_client_requisition(
    body: ClientNeedMappingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 7 step 1 — the client raises a Need Mapping Form."""
    _require(current_user, Cap.CLIENT_REQUISITION_WRITE)
    return await client_reqs.create_client_requisition(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-requisitions/{cr_no}")
async def get_client_requisition(
    cr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_REQUISITION_READ)
    return await client_reqs.get_client_requisition(
        current_user, scope_company_id(current_user, company_id), cr_no)


@router.patch("/client-requisitions/{cr_no}")
async def update_client_requisition(
    cr_no: str,
    body: ClientRequisitionUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Amend either form while the requisition is still with the client."""
    _require(current_user, Cap.CLIENT_REQUISITION_WRITE)
    return await client_reqs.update_client_requisition(
        current_user, scope_company_id(current_user, company_id), cr_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-requisitions/{cr_no}/action")
async def act_on_client_requisition(
    cr_no: str,
    body: ClientRequisitionAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_REQ_TRANSITIONS.

    Deliberately declares no single capability: each action names its own in the transition
    table, and the service enforces it from there — so the client's two submit actions and
    Sparsh's three review actions cannot be confused for one another by a route-level gate
    that knows less than the table does.
    """
    return await client_reqs.act_on_client_requisition(
        current_user, scope_company_id(current_user, company_id), cr_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 2 — the Position Scorecard
#
# The recruiter drafts, the Team Lead reviews, the client approves. No Sparsh role holds
# the approval capability, which is what makes the client's sign-off mandatory rather than
# merely expected.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-scorecards")
async def list_client_scorecards(
    company_id: Optional[str] = Query(None),
    cr_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Scorecards in scope. A client never sees one still being drafted."""
    _require(current_user, Cap.CLIENT_SCORECARD_READ)
    return await client_scorecards.list_client_scorecards(
        current_user, scope_company_id(current_user, company_id),
        cr_no=cr_no, status=status, limit=limit)


@router.post("/client-scorecards", status_code=201)
async def create_client_scorecard(
    body: ClientScorecardIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 8 — the recruiter drafts it, against an approved requisition."""
    _require(current_user, Cap.CLIENT_SCORECARD_WRITE)
    return await client_scorecards.create_client_scorecard(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-scorecards/{psc_no}")
async def get_client_scorecard(
    psc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_SCORECARD_READ)
    return await client_scorecards.get_client_scorecard(
        current_user, scope_company_id(current_user, company_id), psc_no)


@router.patch("/client-scorecards/{psc_no}")
async def update_client_scorecard(
    psc_no: str,
    body: ClientScorecardUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Amend the draft. Refused once somebody is reviewing it."""
    _require(current_user, Cap.CLIENT_SCORECARD_WRITE)
    return await client_scorecards.update_client_scorecard(
        current_user, scope_company_id(current_user, company_id), psc_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-scorecards/{psc_no}/action")
async def act_on_client_scorecard(
    psc_no: str,
    body: ClientScorecardAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_SCORECARD_TRANSITIONS.

    No single route-level capability: each action names its own in the table, so the
    recruiter's submit, the Team Lead's review and the client's approval cannot be
    conflated by a gate that knows less than the table does.
    """
    return await client_scorecards.act_on_client_scorecard(
        current_user, scope_company_id(current_user, company_id), psc_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, steps 3-4 — sourcing, screening, and the CV share
#
# The recruiter sources and screens, the Team Lead delivers the shortlist, and the client
# decides. A client sees a candidate only once shared, and the payload they receive is a
# whitelist rather than the full record — Sparsh's screening notes are not theirs to read.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-candidates")
async def list_client_candidates(
    company_id: Optional[str] = Query(None),
    cr_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Candidates in scope. A client sees only those shared with them."""
    _require(current_user, Cap.CLIENT_CANDIDATE_READ)
    return await client_cands.list_client_candidates(
        current_user, scope_company_id(current_user, company_id),
        cr_no=cr_no, status=status, limit=limit)


@router.post("/client-candidates", status_code=201)
async def create_client_candidate(
    body: ClientCandidateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 10 — source against a role whose benchmark the client approved."""
    _require(current_user, Cap.CLIENT_CANDIDATE_WRITE)
    return await client_cands.create_client_candidate(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-candidates/{ccn_no}")
async def get_client_candidate(
    ccn_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_CANDIDATE_READ)
    return await client_cands.get_client_candidate(
        current_user, scope_company_id(current_user, company_id), ccn_no)


@router.patch("/client-candidates/{ccn_no}")
async def update_client_candidate(
    ccn_no: str,
    body: ClientCandidateUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Details and the three section 13 scores. Refused once the CV is with the client."""
    _require(current_user, Cap.CLIENT_CANDIDATE_WRITE)
    return await client_cands.update_client_candidate(
        current_user, scope_company_id(current_user, company_id), ccn_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-candidates/{ccn_no}/action")
async def act_on_client_candidate(
    ccn_no: str,
    body: ClientCandidateAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_CANDIDATE_TRANSITIONS. Each action names its own capability."""
    return await client_cands.act_on_client_candidate(
        current_user, scope_company_id(current_user, company_id), ccn_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 5 — the assessment
#
# Opened by the client's CV approval, administered and marked by Sparsh, delivered by the
# Team Lead, and closed by the client reading the result — which is what unlocks the
# interview stage.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-assessments")
async def list_client_assessments(
    company_id: Optional[str] = Query(None),
    ccn_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Assessments in scope. A client sees a result once it has been shared."""
    _require(current_user, Cap.CLIENT_ASSESSMENT_READ)
    return await client_assess.list_client_assessments(
        current_user, scope_company_id(current_user, company_id),
        ccn_no=ccn_no, status=status, limit=limit)


@router.post("/client-assessments", status_code=201)
async def create_client_assessment(
    body: ClientAssessmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue it — only to a candidate whose CV the client has approved."""
    _require(current_user, Cap.CLIENT_ASSESSMENT_MANAGE)
    return await client_assess.create_client_assessment(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-assessments/{cas_no}")
async def get_client_assessment(
    cas_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_ASSESSMENT_READ)
    return await client_assess.get_client_assessment(
        current_user, scope_company_id(current_user, company_id), cas_no)


@router.patch("/client-assessments/{cas_no}")
async def update_client_assessment(
    cas_no: str,
    body: ClientAssessmentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Paperwork and the mark. Recording a SCORE additionally needs the scoring
    capability, checked in the service — administering an assessment and marking it are
    separate jobs."""
    _require(current_user, Cap.CLIENT_ASSESSMENT_MANAGE)
    return await client_assess.update_client_assessment(
        current_user, scope_company_id(current_user, company_id), cas_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-assessments/{cas_no}/action")
async def act_on_client_assessment(
    cas_no: str,
    body: ClientAssessmentAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_ASSESSMENT_TRANSITIONS. Each action names its own capability."""
    return await client_assess.act_on_client_assessment(
        current_user, scope_company_id(current_user, company_id), cas_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 6 — interview, recording, client selection
#
# Sparsh schedules, conducts and scores; the Team Lead delivers the recording; the client
# watches it and selects. The selection is the client's alone.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-interviews")
async def list_client_interviews(
    company_id: Optional[str] = Query(None),
    ccn_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Interviews in scope. A client sees one once the recording has been shared."""
    _require(current_user, Cap.CLIENT_INTERVIEW_READ)
    return await client_ints.list_client_interviews(
        current_user, scope_company_id(current_user, company_id),
        ccn_no=ccn_no, status=status, limit=limit)


@router.post("/client-interviews", status_code=201)
async def create_client_interview(
    body: ClientInterviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Schedule it — only once the client has reviewed the assessment result."""
    _require(current_user, Cap.CLIENT_INTERVIEW_MANAGE)
    return await client_ints.create_client_interview(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-interviews/{cin_no}")
async def get_client_interview(
    cin_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_INTERVIEW_READ)
    return await client_ints.get_client_interview(
        current_user, scope_company_id(current_user, company_id), cin_no)


@router.patch("/client-interviews/{cin_no}")
async def update_client_interview(
    cin_no: str,
    body: ClientInterviewUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Scores, the panel's outcome, the recording link and the private notes."""
    _require(current_user, Cap.CLIENT_INTERVIEW_MANAGE)
    return await client_ints.update_client_interview(
        current_user, scope_company_id(current_user, company_id), cin_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-interviews/{cin_no}/action")
async def act_on_client_interview(
    cin_no: str,
    body: ClientInterviewAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_INTERVIEW_TRANSITIONS. Each action names its own capability."""
    return await client_ints.act_on_client_interview(
        current_user, scope_company_id(current_user, company_id), cin_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 7 — reference check and the offer
#
# Reference checks are Sparsh's and never reach a client. The offer follows the section 8
# matrix: the recruiter prepares, the Team Lead verifies, the client approves and issues.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-reference-checks")
async def list_client_reference_checks(
    company_id: Optional[str] = Query(None),
    ccn_no: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Sparsh only — the capability is absent from the client ceiling entirely."""
    _require(current_user, Cap.CLIENT_REFERENCE_READ)
    return await client_offers.list_client_references(
        current_user, scope_company_id(current_user, company_id),
        ccn_no=ccn_no, limit=limit)


@router.post("/client-reference-checks", status_code=201)
async def record_client_reference_check(
    body: ClientReferenceCheckIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 15 — last employer, conduct, reason for leaving."""
    _require(current_user, Cap.CLIENT_REFERENCE_WRITE)
    return await client_offers.record_client_reference(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-offers")
async def list_client_offers(
    company_id: Optional[str] = Query(None),
    ccn_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Offers in scope. A client sees one once it reaches them for approval."""
    _require(current_user, Cap.CLIENT_OFFER_READ)
    return await client_offers.list_client_offers(
        current_user, scope_company_id(current_user, company_id),
        ccn_no=ccn_no, status=status, limit=limit)


@router.post("/client-offers", status_code=201)
async def create_client_offer(
    body: ClientOfferIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Prepare the terms — only for somebody the client has selected."""
    _require(current_user, Cap.CLIENT_OFFER_WRITE)
    return await client_offers.create_client_offer(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-offers/{cof_no}")
async def get_client_offer(
    cof_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_OFFER_READ)
    return await client_offers.get_client_offer(
        current_user, scope_company_id(current_user, company_id), cof_no)


@router.get("/client-offers/{cof_no}/checkpoint")
async def client_offer_checkpoint(
    cof_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 16's three conditions, and what is still outstanding.

    Read-only, so a recruiter can see what is missing while the offer is still a draft
    rather than meeting the control for the first time when it refuses them.
    """
    _require(current_user, Cap.CLIENT_OFFER_READ)
    scoped = scope_company_id(current_user, company_id)
    offer = await client_offers.get_client_offer(current_user, scoped, cof_no)
    return await client_offers.offer_checkpoint(scoped, offer)


@router.patch("/client-offers/{cof_no}")
async def update_client_offer(
    cof_no: str,
    body: ClientOfferUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Amend the terms while the offer is still a draft."""
    _require(current_user, Cap.CLIENT_OFFER_WRITE)
    return await client_offers.update_client_offer(
        current_user, scope_company_id(current_user, company_id), cof_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-offers/{cof_no}/action")
async def act_on_client_offer(
    cof_no: str,
    body: ClientOfferAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_OFFER_TRANSITIONS. Each action names its own capability."""
    return await client_offers.act_on_client_offer(
        current_user, scope_company_id(current_user, company_id), cof_no,
        body.action, body.model_dump())


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, steps 8-9 — pre-boarding, joining, handover, closure
#
# The recruiter keeps the joiner warm, the CLIENT confirms in writing that they started,
# and the Team Lead's handover note is what closes the requisition.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-joinings")
async def list_client_joinings(
    company_id: Optional[str] = Query(None),
    ccn_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Joiners in scope, with the at-risk count section 19 exists to surface."""
    _require(current_user, Cap.CLIENT_JOINING_READ)
    return await client_join.list_client_joinings(
        current_user, scope_company_id(current_user, company_id),
        ccn_no=ccn_no, status=status, limit=limit)


@router.post("/client-joinings", status_code=201)
async def open_client_joining(
    body: ClientJoiningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open pre-boarding — only once a written acceptance is on record."""
    _require(current_user, Cap.CLIENT_JOINING_MANAGE)
    return await client_join.open_client_joining(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-joinings/{cjn_no}")
async def get_client_joining(
    cjn_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_JOINING_READ)
    return await client_join.get_client_joining(
        current_user, scope_company_id(current_user, company_id), cjn_no)


@router.post("/client-joinings/{cjn_no}/touchpoints", status_code=201)
async def record_client_touchpoint(
    cjn_no: str,
    body: ClientTouchpointIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SOP section 19 — one periodic contact. A log, never a gate."""
    _require(current_user, Cap.CLIENT_JOINING_MANAGE)
    return await client_join.record_touchpoint(
        current_user, scope_company_id(current_user, company_id), cjn_no,
        body.model_dump())


@router.patch("/client-joinings/{cjn_no}")
async def update_client_joining(
    cjn_no: str,
    body: ClientJoiningUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The joining date, client-side readiness, and section 20's post-joining results."""
    _require(current_user, Cap.CLIENT_JOINING_MANAGE)
    return await client_join.update_client_joining(
        current_user, scope_company_id(current_user, company_id), cjn_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-joinings/{cjn_no}/action")
async def act_on_client_joining(
    cjn_no: str,
    body: ClientJoiningAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_JOINING_TRANSITIONS. Each action names its own capability."""
    return await client_join.act_on_client_joining(
        current_user, scope_company_id(current_user, company_id), cjn_no,
        body.action, body.model_dump())


@router.get("/client-analytics")
async def client_recruitment_analytics(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Delivery analytics for the PRO-fit track.

    Deliberately NOT part of the internal recruitment dashboard. The two tracks measure
    different things -- an approval chain and a probation outcome on one side, delivery
    against a client's expectations on the other -- and one combined figure would be
    meaningless to both audiences.
    """
    _require(current_user, Cap.CLIENT_ANALYTICS_READ)
    return await client_stats.client_recruitment_analytics(
        current_user, scope_company_id(current_user, company_id))


@router.get("/client-companies")
async def list_client_companies(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The client companies in scope, for the client track's own picker.

    Separate from `/hrms/companies`, which lists HRMS tenants and on an in-house system
    means Sparsh Magic. A client-side caller gets their own company only, so this can
    never become a directory of who else Sparsh recruits for.
    """
    _require(current_user, Cap.CLIENT_REQUISITION_READ)
    return await client_stats.client_companies(
        current_user, scope_company_id(current_user, company_id))


# ═════════════════════════════════════════════════════════════════════════════
# Client Hiring, step 2b — the job posting and the applications against it
#
# The posting is Sparsh's: a client agrees the benchmark and reads the candidates, but the
# advert and its public link are Sparsh's professional work. So there is no client-side
# read here, and `scope_company_id` still pins anyone who tries.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-postings")
async def list_client_postings(
    company_id: Optional[str] = Query(None),
    cr_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_POSTING_READ)
    return await client_postings.list_client_postings(
        current_user, scope_company_id(current_user, company_id),
        cr_no=cr_no, status=status, limit=limit)


@router.post("/client-postings", status_code=201)
async def create_client_posting(
    body: ClientPostingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft a posting. Refused unless the client has approved the scorecard."""
    return await client_postings.create_client_posting(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-postings/{posting_no}")
async def get_client_posting(
    posting_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_POSTING_READ)
    return await client_postings.get_client_posting(
        current_user, scope_company_id(current_user, company_id), posting_no)


@router.patch("/client-postings/{posting_no}")
async def update_client_posting(
    posting_no: str,
    body: ClientPostingUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return await client_postings.update_client_posting(
        current_user, scope_company_id(current_user, company_id), posting_no,
        body.model_dump(exclude_unset=True))


@router.post("/client-postings/{posting_no}/action")
async def act_on_client_posting(
    posting_no: str,
    body: ClientPostingAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Move along CLIENT_POSTING_TRANSITIONS — publish, or close with a reason."""
    return await client_postings.act_on_client_posting(
        current_user, scope_company_id(current_user, company_id), posting_no,
        body.action, body.model_dump())


@router.get("/client-applications")
async def list_client_applications(
    company_id: Optional[str] = Query(None),
    posting_no: Optional[str] = Query(None),
    cr_no: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Everyone who applied, against a posting or a requisition.

    Reads the CANDIDATE collection: an applicant is a candidate who arrived a particular
    way, not a separate kind of record.
    """
    _require(current_user, Cap.CLIENT_CANDIDATE_READ)
    return await client_postings.list_applications(
        current_user, scope_company_id(current_user, company_id),
        posting_no=posting_no, cr_no=cr_no, limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# The available candidate pool
#
# THE ONE CLIENT-TRACK SURFACE THAT SPANS TENANTS, and therefore the one that refuses a
# client-side caller in the service rather than by scoping. A client rejecting a CV ends
# that person's run at that client, not their usefulness; re-sourcing them creates a NEW
# record in the new tenant and never exposes the old one.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client-candidate-pool")
async def list_client_candidate_pool(
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    return await client_cands.list_candidate_pool(
        current_user, limit=limit, search=search)


@router.post("/client-candidate-pool/source", status_code=201)
async def source_from_client_pool(
    body: ClientPoolSourceIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Source a pooled candidate into another requisition, as a fresh record."""
    return await client_cands.resource_from_pool(
        current_user, scope_company_id(current_user, company_id), body.model_dump())


@router.get("/client-history/{entity}/{record_no}")
async def client_record_history(
    entity: str,
    record_no: str,
    company_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """The status history of one client-track record, newest first.

    Read from the audit trail rather than a `history` array on the record: the trail
    already captures every transition with its actor, detail and timestamp, and a second
    copy on the document would be one more thing to keep in step.
    """
    _require(current_user, Cap.CLIENT_REQUISITION_READ)
    allowed = {"client_requisition", "client_scorecard", "client_posting",
               "client_candidate", "client_assessment", "client_interview",
               "client_offer", "client_joining"}
    if entity not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Entity must be one of: " + ", ".join(sorted(allowed)) + ".")
    rows = await read_audit(
        company_id=scope_company_id(current_user, company_id),
        entity=entity, entity_id=record_no, limit=limit)
    return {"entity": entity, "record_no": record_no, "history": rows,
            "total": len(rows)}
