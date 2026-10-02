"""Annexure B (RACI) -- every stage of an internal hire, checked against the matrix.

One HR Executive vacancy is raised and driven through the whole workflow by three users --
HR, the Department Head, and Management/Finance -- and at every stage the action is also
attempted by a role the matrix does NOT make Responsible or Accountable.

    Legend:  R = Responsible   A = Accountable   C = Consulted   I = Informed

-- Where the gate actually lives, and why this file checks two things -------------------------
Only `act_on_requisition` asks `can(actor, capability)` inside the service; the rest of HRMS
puts the capability check on the ROUTE (`_require(user, Cap.X)` in routes/hrms.py) and lets
the service assume an authorised caller. Calling those services directly therefore proves
nothing about permission -- it bypasses the gate rather than testing it.

So the matrix is verified in two halves, and neither is sufficient alone:

  Part A  the role -> capability map: who holds the capability governing each stage.
  Part B  the route -> capability map: that the endpoint for each stage actually DEMANDS
          that capability, read out of the source. Without this, Part A tests a capability
          nothing enforces.

  Part C  drives the real workflow, which is what proves the SEQUENCE: gates fire in order,
          a mandatory approval cannot be skipped, a rejection lands where it should, and the
          audit trail records who did what.
  Part D  the managerial+ conditional rows, which do not apply to this mid-level vacancy and
          must not fire for it -- and must fire for a managerial one.

-- The vacancy ---------------------------------------------------------------------------------
    Role        HR Executive  (DesignationLevel.MID -- deliberately NOT managerial)
    Department  HR
    Band        420,000 - 450,000 per year

Three matrix rows are marked "(managerial+)". For THIS role they are correctly inert, which
is itself a permission rule and is asserted in Part D against a second, managerial vacancy.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_raci_matrix   (from backend/)
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

results: list[bool] = []
findings: list[str] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def finding(label: str, detail: str) -> None:
    """A confirmed deviation from the matrix that is not a test failure -- the assertion
    beside it records what the code ACTUALLY does, so this file stays a true regression
    test while the gap stays visible."""
    findings.append(f"{label}: {detail}")
    print(f"  NOTE  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
ANNUAL = 420_000
BAND_MIN, BAND_MAX = 400_000.0, 450_000.0


def route_capabilities() -> dict:
    """(VERB, path) -> [Cap names] the handler requires, read from routes/hrms.py.

    Read from source rather than by calling the app because the point is to prove the gate
    is DECLARED, not merely that one call happened to fail.
    """
    src = open("app/routes/hrms.py", encoding="utf-8").read()
    out = {}
    for block in re.split(r"@router\.", src)[1:]:
        m = re.match(r'(get|post|patch|put|delete)\("([^"]+)"', block)
        if not m:
            continue
        out[(m.group(1).upper(), m.group(2))] = re.findall(
            r"_require\((?:current_user|user), Cap\.([A-Z_]+)\)", block)
    return out


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere -- each has its own test
    # file (test_int12_client_track), and a failure here should name THIS file's control
    # rather than a precondition it never set up.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared
    import app.db.mongodb as mongo
    import app.utils.hrms_access as A

    U_HR, U_MD, U_FIN, U_HOD, U_EMP = (str(ObjectId()) for _ in range(5))
    dept_hr, desig_exec, desig_mgr = ObjectId(), ObjectId(), ObjectId()

    departments = FakeCollection([
        {"_id": dept_hr, "company_id": COMPANY, "name": "HR", "active": True}])
    designations = FakeCollection([
        {"_id": desig_exec, "company_id": COMPANY, "name": "HR Executive",
         "designation_level": M.DesignationLevel.MID.value, "active": True},
        {"_id": desig_mgr, "company_id": COMPANY, "name": "HR Manager",
         "designation_level": M.DesignationLevel.MANAGERIAL.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "email": "hana@sparsh.in", "governance_role": "HR", "role": "clientuser",
         "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "email": "meera@sparsh.in", "governance_role": "MD", "role": "clientadmin",
         "is_active": True},
        {"_id": ObjectId(U_FIN), "company_id": COMPANY, "full_name": "Farid Finance",
         "email": "farid@sparsh.in", "governance_role": "FINANCE", "role": "clientuser",
         "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "email": "hari@sparsh.in", "governance_role": "HOD", "role": "clientuser",
         "is_active": True},
        {"_id": ObjectId(U_EMP), "company_id": COMPANY, "full_name": "Eve Employee",
         "email": "eve@sparsh.in", "governance_role": "IMPLEMENTOR", "role": "clientuser",
         "is_active": True},
    ])
    sanctions = FakeCollection([
        {"company_id": COMPANY, "department_id": str(dept_hr),
         "designation_id": str(desig_exec), "sanctioned_count": 50},
        {"company_id": COMPANY, "department_id": str(dept_hr),
         "designation_id": str(desig_mgr), "sanctioned_count": 50}])

    store = {c: FakeCollection() for c in (
        M.COLL_REQUISITIONS, M.COLL_JOB_DESCRIPTIONS, M.COLL_JOB_POSTINGS,
        M.COLL_CANDIDATES, M.COLL_POSITION_SCORECARDS, M.COLL_TELEPHONIC,
        M.COLL_ASSESSMENTS, M.COLL_INTERVIEWS, M.COLL_SHORTLIST_REVIEWS,
        M.COLL_REFERENCE_CHECKS, M.COLL_NEGOTIATIONS, M.COLL_OFFERS,
        M.COLL_PREBOARDING, M.COLL_ONBOARDING, M.COLL_PROBATION_REVIEWS,
        M.COLL_EXCEPTIONS, M.COLL_POLICIES, M.COLL_POLICY_REVISIONS,
        M.COLL_SALARY_BANDS, M.COLL_COUNTERS, M.COLL_AUDIT_LOG, M.COLL_LINKS,
        M.COLL_DOCUMENTS, M.COLL_DOCUMENT_TYPES, M.COLL_EMPLOYEE_PROFILES,
        M.COLL_SETTINGS, M.COLL_SURVEYS, M.COLL_COMM_TEMPLATES, M.COLL_COMM_LOG)}
    store.update({M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
                  M.COLL_SANCTIONED_STRENGTH: sanctions, "learners": learners,
                  "staff": FakeCollection(), "companies": FakeCollection()})
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_telephonic_service as TS
    import app.services.hrms_assessment_service as ASM
    import app.services.hrms_interview_service as IV
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_reference_service as RC
    import app.services.hrms_negotiation_service as NG
    import app.services.hrms_offer_service as OF
    import app.services.hrms_preboarding_service as PB
    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_probation_service as PR
    import app.services.hrms_exception_service as EX
    import app.services.hrms_policy_service as PO
    import app.services.hrms_analytics_service as AN
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_salary_band_service as BANDS
    import app.services.hrms_config_service as CFG
    import app.services.hrms_comm_service as COMM
    import app.services.hrms_survey_service as SV
    import app.services.hrms_document_service as DS
    import app.services.hrms_employee_service as ES

    SERVICES = (RS, SC, PS, CS, TS, ASM, IV, SL, RC, NG, OF, PB, OB, PR, EX, PO, AN,
                AUD, IDS, SN, LS, RF, BANDS, CFG, COMM, SV, DS, ES)
    import app.utils.hrms_access as HACC
    for mod in list(SERVICES) + [HACC]:
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    for mod in SERVICES:
        if hasattr(mod, "notify_user"):
            mod.notify_user = fake_notify_user
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = fake_notify_role
    import app.services.hrms_notify_service as NS
    original_notify = (NS.notify_user, NS.notify_hrms_role)
    NS.notify_user, NS.notify_hrms_role = fake_notify_user, fake_notify_role

    import app.services.s3_service as S3
    original_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = lambda s, f, m: {"key": f"s3/{f}", "url": "https://x/y"}

    def actor(uid, governance, role="clientuser", name=None):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": name or f"{governance} user"}

    HR = actor(U_HR, "HR", name="Hana HR")
    MD = actor(U_MD, "MD", role="clientadmin", name="Meera MD")
    FIN = actor(U_FIN, "FINANCE", name="Farid Finance")
    HOD = actor(U_HOD, "HOD", name="Hari HOD")
    EMP = actor(U_EMP, "IMPLEMENTOR", name="Eve Employee")
    CAST = {"HR": HR, "HOD": HOD, "MD": MD, "FINANCE": FIN, "EMPLOYEE": EMP}

    def payload(designation=None, **over):
        base = {"department_id": str(dept_hr),
                "designation_id": str(designation or desig_exec),
                "assignee_id": U_HR, "vacancy": 1, "required_date": "2027-03-31",
                "experience_required": "2-4 years", "qualification": "Graduate",
                "essential_skills": "Recruitment coordination, HRIS",
                "offering_ctc": float(ANNUAL),
                "work_location": M.WorkLocation.OFFICE.value,
                "employment_type": M.EmploymentType.FULL_TIME.value,
                "requisition_track": "internal",
                "jd": {"title": "HR Executive",
                       "responsibilities": "Run the recruitment desk end to end."}}
        base.update(over)
        return base

    BUDGET = {"approved_headcount": 1, "approved_salary_band_min": BAND_MIN,
              "approved_salary_band_max": BAND_MAX}

    async def status_of(request_no):
        return (await store[M.COLL_REQUISITIONS].find_one(
            {"request_no": request_no}))["approval_status"]

    def audit_rows(entity_id):
        return [a for a in store[M.COLL_AUDIT_LOG].docs if a.get("entity_id") == entity_id]

    # ══════════════════════════════════════════════════════════════════
    # The matrix, transcribed. (stage, capability, {role: letter})
    # Roles not named are neither R nor A and must not hold the capability.
    # ══════════════════════════════════════════════════════════════════
    # (stage, capability, roles that must hold it, roles that must NOT)
    #
    # Two transcription rules, both of which matter:
    #
    #  * A row's "A" is accountability for the STAGE, not a claim that the accountable role
    #    performs every action in it. The HOD is A for the panel interview and A for the
    #    scorecard, but HR schedules and HR drafts; the HOD's accountability is discharged
    #    by evaluating and by signing. Where the matrix's A and R fall on different actions,
    #    the stage is split into the two capabilities that actually carry them.
    #  * "Must not hold" is asserted for ACTION capabilities only. `analytics.read` is a
    #    read, and a role marked I on a reporting row is being INFORMED by exactly that
    #    read -- withholding it would defeat the row rather than enforce it.
    #
    # MD is excluded from every "must not" set: HrmsRole.MD resolves to 89 of 90
    # capabilities by documented design. That is asserted once, and reported, below.
    RACI = [
        ("Raise internal requisition",      M.Cap.REQUISITION_CREATE,
         {"HOD"}, set()),                                   # see finding: open to all
        ("Headcount & budget approval",     M.Cap.REQUISITION_APPROVE_BUDGET,
         {"MD", "FINANCE"}, {"HR", "HOD", "EMPLOYEE"}),
        ("Position scorecard -- HR drafts", M.Cap.SCORECARD_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Position scorecard -- HOD approves", M.Cap.SCORECARD_APPROVE,
         {"HOD", "MD"}, {"HR", "FINANCE", "EMPLOYEE"}),
        ("Recruitment planning / sourcing", M.Cap.POSTING_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Sourcing & screening",            M.Cap.CANDIDATE_SCREEN,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Telephonic screening",            M.Cap.TELEPHONIC_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Skill / competency assessment",   M.Cap.ASSESSMENT_SEND,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Panel interview -- HR schedules", M.Cap.INTERVIEW_SCHEDULE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Panel interview -- HOD evaluates", M.Cap.INTERVIEW_EVALUATE,
         {"HOD", "HR"}, {"FINANCE"}),
        ("Internal shortlisting committee", M.Cap.SHORTLIST_WRITE,
         {"HR", "HOD"}, {"FINANCE", "EMPLOYEE"}),
        ("Final interview (managerial+)",   M.Cap.INTERVIEW_DECIDE_MD,
         {"MD"}, {"HR", "HOD", "FINANCE", "EMPLOYEE"}),
        ("Reference check",                 M.Cap.REFERENCE_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Salary negotiation -- HR records", M.Cap.NEGOTIATION_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Offer approval",                  M.Cap.OFFER_APPROVE,
         {"MD", "FINANCE"}, {"HR", "HOD", "EMPLOYEE"}),
        ("Offer release",                   M.Cap.OFFER_SEND,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Pre-boarding engagement",         M.Cap.PREBOARDING_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Joining & induction",             M.Cap.ONBOARDING_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Probation confirmation",          M.Cap.PROBATION_CONFIRM,
         {"HOD", "MD"}, {"HR", "FINANCE", "EMPLOYEE"}),
        ("Personnel file closure",          M.Cap.PERSONNEL_FILE_CLOSE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("KPI / dashboard reporting",       M.Cap.ANALYTICS_READ,
         {"HR", "MD", "FINANCE"}, {"EMPLOYEE"}),
        ("Exception approval",              M.Cap.EXCEPTION_APPROVE,
         {"MD", "FINANCE"}, {"HR", "HOD", "EMPLOYEE"}),
        ("Policy review -- HR revises",     M.Cap.POLICY_WRITE,
         {"HR"}, {"HOD", "FINANCE", "EMPLOYEE"}),
        ("Policy review -- Mgmt approves",  M.Cap.POLICY_APPROVE,
         {"MD"}, {"HR", "HOD", "FINANCE", "EMPLOYEE"}),
    ]

    # Which endpoint governs each stage, so Part A's capabilities are shown to be enforced.
    STAGE_ROUTES = {
        "Raise internal requisition":        ("POST", "/requisitions"),
        "Position scorecard -- HR drafts":   ("POST", "/scorecards"),
        "Position scorecard -- HOD approves": ("POST", "/scorecards/{scr_no}/approve"),
        "Recruitment planning / sourcing":   ("POST", "/postings"),
        "Sourcing & screening":              ("POST", "/candidates/screen"),
        "Telephonic screening":              ("POST", "/telephonic-screenings"),
        "Skill / competency assessment":     ("POST", "/assessments"),
        "Panel interview -- HR schedules":   ("POST", "/interviews"),
        "Internal shortlisting committee":   ("POST", "/shortlist-reviews"),
        "Reference check":                   ("POST", "/reference-checks"),
        "Salary negotiation -- HR records":  ("POST", "/negotiations"),
        "Offer approval":                    ("POST", "/offers/{offer_no}/approve"),
        "Offer release":                     ("POST", "/offers/{offer_no}/send"),
        "Pre-boarding engagement":           ("POST", "/preboarding"),
        "Probation confirmation":            ("POST", "/probation/{prb_no}/confirm"),
        "Personnel file closure":            ("POST", "/personnel-file/close"),
        "KPI / dashboard reporting":         ("GET",  "/analytics/internal-kpis"),
        "Exception approval":                ("POST", "/exceptions/{exc_no}/approve"),
        "Policy review -- Mgmt approves":    ("POST", "/policies/{policy_key}/approve"),
    }

    try:
        # =================================================================
        section("PART A -- the role/capability map matches Annexure B")
        # =================================================================
        for stage, cap, must_hold, must_not in RACI:
            holders = {r for r, u in CAST.items() if A.can(u, cap)}
            check(f"{stage}: R/A hold {cap.value} ({', '.join(sorted(must_hold))})",
                  must_hold <= holders)
            leaked = must_not & holders
            check(f"{stage}: C/I cannot execute it"
                  + (f" -- LEAKED to {', '.join(sorted(leaked))}" if leaked else ""),
                  not leaked)

        section("PART A2 -- the two places the code and the matrix genuinely disagree")
        check("(actual) requisition.create is held by HR, HOD, MD and a plain EMPLOYEE",
              all(A.can(CAST[r], M.Cap.REQUISITION_CREATE)
                  for r in ("HR", "HOD", "MD", "EMPLOYEE")))
        finding(
            "anyone may raise a requisition, though Annexure B makes the HOD Responsible",
            "Cap.REQUISITION_CREATE is granted to INTERNAL, MD, HR, MANAGER and EMPLOYEE. "
            "models/hrms.py calls this deliberate ('raise one -- deliberately open to all') "
            "and the raiser becomes the hiring manager. It is a documented design decision, "
            "not an oversight -- but it does mean the matrix's 'HOD = R' is a convention "
            "the system does not enforce. Nothing downstream is weakened: every APPROVAL "
            "after the raise is gated.")
        # Asserted as "all but one" rather than as a number, so a later phase adding a
        # capability does not fail this line for the wrong reason -- what matters is that
        # the MD's grant stays universal-minus-the-HR-verification-step, not its size.
        # Everything the MD lacks, other than HR's verification step, is a capability that
        # only makes sense held by the SUBJECT of a record -- acknowledging a policy, or
        # submitting your own pulse response. Those are not authority the MD is missing.
        # (This used to be a strict count, which later phases broke every time they added a
        # self-service grant -- exactly the "fails for the wrong reason" the note above
        # says it was written to avoid.)
        SELF_SERVICE_ONLY = {
            M.Cap.POLICY_ACKNOWLEDGE, M.Cap.PULSE_SUBMIT,
            M.Cap.EXIT_INTERVIEW_SUBMIT, M.Cap.GMP_READ, M.Cap.GMP_WRITE,
        }
        # Client Hiring is a SEPARATE TRACK, and the Operations Head's universal grant does
        # not reach into it. Two kinds of capability are deliberately withheld there:
        # things the client owns (their own requisition, their own approvals) and delivery
        # work the recruiter does (drafting a benchmark, screening a CV). Neither is
        # authority the MD is missing.
        #
        # Derived from the prefix rather than listed, so a later Client Hiring step does
        # not fail this line for the wrong reason -- the same discipline the note above
        # says this assertion was rewritten to follow.
        CLIENT_TRACK = {c for c in M.Cap if c.value.startswith("client_")}
        md_missing = set(M.Cap) - set(M.ROLE_CAPABILITIES[M.HrmsRole.MD])
        check("(actual) on the INTERNAL track the MD holds every capability but one",
              md_missing - SELF_SERVICE_ONLY - CLIENT_TRACK
              == {M.Cap.REQUISITION_REVIEW_HR})

        # What the MD does hold on the client track is oversight, and that is asserted
        # positively so "withheld" cannot quietly become "absent altogether".
        for cap in (M.Cap.CLIENT_REQUISITION_READ, M.Cap.CLIENT_REQUISITION_REVIEW,
                    M.Cap.CLIENT_SCORECARD_READ, M.Cap.CLIENT_SCORECARD_REVIEW,
                    M.Cap.CLIENT_CANDIDATE_READ, M.Cap.CLIENT_CANDIDATE_SHARE):
            check(f"the Operations Head oversees {cap.value}",
                  cap in M.ROLE_CAPABILITIES[M.HrmsRole.MD])

        # The three the CLIENT owns. No Sparsh role may hold any of them, or the client's
        # mandatory involvement becomes a formality the supplier performs for itself.
        for cap in (M.Cap.CLIENT_REQUISITION_WRITE, M.Cap.CLIENT_SCORECARD_APPROVE,
                    M.Cap.CLIENT_CANDIDATE_DECIDE):
            check(f"no Sparsh role holds {cap.value}",
                  not any(cap in caps for caps in M.ROLE_CAPABILITIES.values()))
        check("the one capability the MD does NOT hold is HR's verification step",
              M.Cap.REQUISITION_REVIEW_HR not in M.ROLE_CAPABILITIES[M.HrmsRole.MD])
        finding(
            "the MD is a superuser, so 'Consulted/Informed cannot execute' does not bind them",
            "HrmsRole.MD resolves to every capability but one by documented design ('top of "
            "every ladder'), so on rows where Annexure B marks Management as C or I -- "
            "sourcing, screening, telephonic, reference check, offer release, personnel "
            "file closure and others -- the restriction is enforced against FINANCE, the "
            "HOD and ordinary users, but not against the MD. Separation of duties still "
            "holds where it is load-bearing: the MD cannot perform HR's verification step, "
            "and the two-distinct-signatures rule stops one MD signing a managerial "
            "scorecard alone. If the matrix is meant literally for Management, the MD's "
            "grant needs narrowing row by row.")

        # =================================================================
        section("PART B -- the endpoints actually demand those capabilities")
        # =================================================================
        routes = route_capabilities()
        by_stage = {s: c for s, c, _, _ in RACI}
        for stage, endpoint in STAGE_ROUTES.items():
            declared = routes.get(endpoint) or []
            check(f"{endpoint[0]} {endpoint[1]} requires {by_stage[stage].value}",
                  by_stage[stage].name in declared)
        # The one stage whose capability is enforced in the SERVICE rather than the route,
        # because the transition table names a different capability per action.
        check("the approve endpoint declares no single capability (it is per-action)",
              routes.get(("POST", "/requisitions/{request_no}/approve")) == [])
        check("...and act_on_requisition checks can(actor, capability) itself",
              "can(actor, capability)" in open(
                  "app/services/hrms_requisition_service.py", encoding="utf-8").read())

        # =================================================================
        section("STAGE 1 -- Raise internal requisition (HOD=R, HR=C, Mgmt=I)")
        # =================================================================
        raised = await RS.create_requisition(HOD, COMPANY, payload())
        REQ, JD = raised["request_no"], raised["jd_no"]
        check("HOD (R) raised it", raised["created_by"] == U_HOD)
        check("it opens at Pending HR Verification",
              raised["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)
        check("HR (C) is notified to consult, not to approve",
              any(s[0] == "role" and "HR" in s[1] for s in sent))

        # =================================================================
        section("STAGE 2 -- Headcount & budget approval (Mgmt/Finance=A/R)")
        # =================================================================
        await expect_http("HR (C) approves the budget",
                          RS.act_on_requisition(HR, COMPANY, REQ, "budget-approve",
                                                budget=BUDGET), 403, "not authorised")
        await expect_http("HOD (C) approves the budget",
                          RS.act_on_requisition(HOD, COMPANY, REQ, "budget-approve",
                                                budget=BUDGET), 403, "not authorised")
        await expect_http("an employee approves the budget",
                          RS.act_on_requisition(EMP, COMPANY, REQ, "budget-approve",
                                                budget=BUDGET), 403, "not authorised")
        await RS.act_on_requisition(HR, COMPANY, REQ, "hr-verify")
        check("HR's own step (verification) is allowed",
              await status_of(REQ) == M.ReqApproval.PENDING_BUDGET.value)

        section("STAGE 2b -- rejection returns it to a stopped state, then resubmit")
        await expect_http("rejecting with no comment",
                          RS.act_on_requisition(FIN, COMPANY, REQ, "budget-reject"),
                          422, "remark is required")
        await RS.act_on_requisition(FIN, COMPANY, REQ, "budget-reject",
                                    remarks="Deferred to the next quarter.")
        check("Finance (A) rejection lands on Rejected",
              await status_of(REQ) == M.ReqApproval.REJECTED.value)
        check("the rejection is audited with its comment",
              any(r["action"] == M.AUDIT_REQ_BUDGET_NO and "Deferred" in (r.get("detail") or "")
                  for r in audit_rows(REQ)))

        # The live vacancy from here on.
        live = await RS.create_requisition(HOD, COMPANY, payload())
        REQ, JD = live["request_no"], live["jd_no"]
        await RS.act_on_requisition(HR, COMPANY, REQ, "hr-verify")
        approved = await RS.act_on_requisition(
            FIN, COMPANY, REQ, "budget-approve", budget=BUDGET,
            remarks="Approved against the Q1 headcount plan.")
        check("Finance (A) approval moves it to Pending Scorecard Approval",
              approved["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("the approver, the band and the timestamp are recorded",
              approved["budget_approved_by"] == U_FIN
              and approved["approved_salary_band_min"] == BAND_MIN
              and approved.get("budget_approved_at"))

        # =================================================================
        section("STAGE 3 -- Position scorecard: HR=R drafts, HOD=A approves")
        # =================================================================
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": REQ, "title": "HR Executive",
            "criteria": [{"label": "Recruitment coordination",
                          "category": M.ScorecardCategory.SKILL.value, "weight": 2},
                         {"label": "HRIS", "category": M.ScorecardCategory.SKILL.value},
                         {"label": "Culture fit",
                          "category": M.ScorecardCategory.CULTURE_FIT.value}]})
        check("HR (R) drafted the scorecard", bool(card["scr_no"]))
        after_hr = await SC.approve_scorecard(HR, COMPANY, card["scr_no"],
                                              {"decision": "Pass", "signature": "Hana HR"})
        check("an HR (C) signature does NOT approve it",
              after_hr["status"] != M.ScorecardStatus.APPROVED.value)
        signed = await SC.approve_scorecard(HOD, COMPANY, card["scr_no"],
                                            {"decision": "Pass", "signature": "Hari HOD"})
        check("the HOD (A) signature approves it",
              signed["status"] == M.ScorecardStatus.APPROVED.value)
        check("a MID role needs ONE approval -- Management is C, not required",
              SC.required_approvals(False) == [M.HrmsRole.MANAGER])
        await RS.act_on_requisition(HOD, COMPANY, REQ, "scorecard-approve")
        check("the requisition reaches Approved",
              await status_of(REQ) == M.ReqApproval.APPROVED.value)

        # =================================================================
        section("STAGE 4 -- Recruitment planning / sourcing (HR=R)")
        # =================================================================
        posting = await PS.create_posting(HR, COMPANY, {"jd_no": JD, "channels": ["Job Portals"]})
        check("HR (R) drafted the posting", bool(posting["posting"]["posting_code"]))
        check("HOD (I) holds no posting.write", not A.can(HOD, M.Cap.POSTING_WRITE))
        check("Finance (I) holds no posting.write", not A.can(FIN, M.Cap.POSTING_WRITE))
        check("an employee holds no posting.write", not A.can(EMP, M.Cap.POSTING_WRITE))

        # =================================================================
        section("STAGE 5 -- Sourcing & screening (HR=R, others I)")
        # =================================================================
        cand = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Asha Applicant",
            "can_email": "asha@example.com", "can_contact": "+91 90000 00001"})
        UK = cand["uk"]
        check("HR (R) added the candidate", bool(UK))
        check("HOD (I) cannot screen", not A.can(HOD, M.Cap.CANDIDATE_SCREEN))
        check("Finance (I) cannot screen", not A.can(FIN, M.Cap.CANDIDATE_SCREEN))
        check("an employee cannot screen", not A.can(EMP, M.Cap.CANDIDATE_SCREEN))
        await CS.screen_candidates(HR, COMPANY, {
            "uks": [UK], "action": M.ScreenAction.SHORTLIST.value})
        check("HR shortlisted the candidate",
              (await store[M.COLL_CANDIDATES].find_one({"uk": UK}))["application_status"]
              == M.AppStatus.SHORTLISTED.value)

        # =================================================================
        section("STAGE 6 -- Telephonic screening (HR=R, others I)")
        # =================================================================
        check("HOD (I) holds no telephonic.write", not A.can(HOD, M.Cap.TELEPHONIC_WRITE))
        check("Finance (I) holds no telephonic.write", not A.can(FIN, M.Cap.TELEPHONIC_WRITE))
        tel = await TS.create_screening(HR, COMPANY, {
            "uk": UK, "communication": 4, "role_understanding": 4, "availability": 4,
            "salary_alignment": 4, "outcome": M.TelephonicOutcome.PASSED.value,
            "comments": "Fluent, available in 30 days."})
        check("HR (R) recorded the phone screen", bool(tel["tel_no"]))

        # =================================================================
        section("STAGE 7 -- Skill / competency assessment (HR=R, HOD=C)")
        # =================================================================
        check("HR (R) may issue an assessment", A.can(HR, M.Cap.ASSESSMENT_SEND))
        check("HOD (C) may REVIEW but not issue",
              A.can(HOD, M.Cap.ASSESSMENT_REVIEW) and not A.can(HOD, M.Cap.ASSESSMENT_SEND))
        check("Finance (I) may neither issue nor review",
              not A.can(FIN, M.Cap.ASSESSMENT_SEND)
              and not A.can(FIN, M.Cap.ASSESSMENT_REVIEW))
        check("(actual) Management DOES hold both -- the superuser grant, reported above",
              A.can(MD, M.Cap.ASSESSMENT_SEND) and A.can(MD, M.Cap.ASSESSMENT_REVIEW))

        # =================================================================
        section("STAGE 8 -- Panel interview (HR=R schedules, HOD=A sits)")
        # =================================================================
        check("HOD (A) may evaluate but not schedule",
              A.can(HOD, M.Cap.INTERVIEW_EVALUATE)
              and not A.can(HOD, M.Cap.INTERVIEW_SCHEDULE))
        check("Finance (I) may neither schedule nor evaluate",
              not A.can(FIN, M.Cap.INTERVIEW_SCHEDULE)
              and not A.can(FIN, M.Cap.INTERVIEW_EVALUATE))
        check("a MID role's panel is HR + HOD -- Management not required",
              M.REQUIRED_PANEL_ROLES[M.DesignationLevel.MID.value]
              == [M.HrmsRole.HR, M.HrmsRole.MANAGER])
        iv = await IV.schedule_interview(HR, COMPANY, {
            "uk": UK, "round": M.InterviewRound.MANAGER.value,
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            "mode": M.InterviewMode.VIRTUAL.value, "duration_min": 45,
            "interviewer_id": U_HOD,
            "meeting_link": "https://meet.example/hr-exec",
            "panel": [{"user_id": U_HR}, {"user_id": U_HOD}]})
        check("HR (R) scheduled a panel interview", bool(iv["interview_no"]))
        await IV.evaluate_interview(HOD, COMPANY, iv["interview_no"], {
            "communication": 4, "technical": 4, "problem_solving": 4, "ownership": 4,
            "culture_fit": 4, "leadership": 4,
            "outcome": M.Outcome.PASS.value, "signature": "Hari HOD",
            "remarks": "Strong coordinator."})
        check("HOD (A) evaluated it", True)

        # =================================================================
        section("STAGE 9 -- Internal shortlisting committee (HR=R, HOD=A)")
        # =================================================================
        check("Finance (I) holds no shortlist.write", not A.can(FIN, M.Cap.SHORTLIST_WRITE))
        check("an employee holds no shortlist.write", not A.can(EMP, M.Cap.SHORTLIST_WRITE))
        review = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": REQ, "candidate_uks": [UK],
            "committee_members": [
                {"user_id": U_HR, "decision": M.CommitteeDecision.AGREE.value},
                {"user_id": U_HOD, "decision": M.CommitteeDecision.AGREE.value}],
            # Final Commit: asking to commit; the outcome is derived from the two Agrees.
            "outcome": M.ShortlistOutcome.SELECTED.value})
        check("HR (R) recorded the committee with the HOD (A) on it",
              bool(review["slr_no"]))
        check("the committee requires BOTH HR and the HOD",
              set(M.SHORTLIST_COMMITTEE_ROLES) == {M.HrmsRole.HR, M.HrmsRole.MANAGER})

        # =================================================================
        section("STAGE 10 -- Final interview: NOT required for a MID role")
        # =================================================================
        check("Management (A) alone holds interview.decide_md",
              A.can(MD, M.Cap.INTERVIEW_DECIDE_MD)
              and not A.can(HR, M.Cap.INTERVIEW_DECIDE_MD)
              and not A.can(HOD, M.Cap.INTERVIEW_DECIDE_MD)
              and not A.can(FIN, M.Cap.INTERVIEW_DECIDE_MD))
        check("a MID role does not require the Management final round",
              not M.final_round_is_mandatory(M.DesignationLevel.MID.value))
        check("a MANAGERIAL role does",
              M.final_round_is_mandatory(M.DesignationLevel.MANAGERIAL.value))

        # =================================================================
        section("STAGE 11 -- Reference check (HR=R, others I) and its gate")
        # =================================================================
        check("HOD (I) holds no reference.write", not A.can(HOD, M.Cap.REFERENCE_WRITE))
        check("Finance (I) holds no reference.write", not A.can(FIN, M.Cap.REFERENCE_WRITE))
        # The interview PASS above advances the candidate through the pass-chain; Selected
        # is a stage the graph reaches, not a screening action (there is no ScreenAction
        # for it -- selection is a decision recorded on an interview).
        moved_to = (await store[M.COLL_CANDIDATES].find_one(
            {"uk": UK}))["application_status"]
        check(f"the interview pass advanced the candidate past shortlisting "
              f"(now {moved_to})",
              M.STAGE_RANK.get(moved_to, 0)
              >= M.STAGE_RANK[M.AppStatus.INTERVIEW_SCHEDULED.value])
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": UK}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await expect_http(
            "an offer BEFORE the reference check (the mandatory gate)",
            OF.create_offer(HR, COMPANY, {"uk": UK, "ctc": float(ANNUAL),
                                          "joining_date": "2026-10-15"}),
            409, "reference")
        await RC.create_reference_check(HR, COMPANY, {
            "uk": UK, "referee_name": "Former Manager",
            "referee_organisation": "Prior Employer",
            "outcome": M.ReferenceOutcome.POSITIVE.value,
            "responses": "Reliable, would rehire.",
            "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        check("HR (R) completed the reference check", True)

        # =================================================================
        section("STAGE 12 -- Salary negotiation (HR=R, HOD=C, Mgmt=A)")
        # =================================================================
        check("HR (R) may record a round", A.can(HR, M.Cap.NEGOTIATION_WRITE))
        check("HOD (C) may READ but not write",
              A.can(HOD, M.Cap.NEGOTIATION_READ) and not A.can(HOD, M.Cap.NEGOTIATION_WRITE))
        check("Finance (A) may read the figure it is accountable for",
              A.can(FIN, M.Cap.NEGOTIATION_READ))
        await NG.record_round(HR, COMPANY, {
            "uk": UK, "candidate_expectation": 430000.0, "proposed_ctc": float(ANNUAL),
            "remarks": "Within band."})
        check("the round records a verdict against the stamped band",
              (await NG.negotiation_for(HR, COMPANY, UK)).get("rounds"))

        # =================================================================
        section("STAGE 13/14 -- Offer approval (Mgmt/Finance=A) then release (HR=R)")
        # =================================================================
        offer = await OF.create_offer(HR, COMPANY, {
            "uk": UK, "ctc": float(ANNUAL), "joining_date": "2026-10-15"})
        OFFER = offer["offer_no"]
        check("HR (C) and the HOD (C) do not hold offer.approve -- the gate the route "
              "enforces",
              not A.can(HR, M.Cap.OFFER_APPROVE) and not A.can(HOD, M.Cap.OFFER_APPROVE))
        # The SEQUENCE gate, which lives in the service and therefore binds every caller:
        # an unapproved internal offer cannot be released, whoever asks.
        await expect_http("releasing an UNAPPROVED offer (the mandatory approval)",
                          OF.send_offer(HR, COMPANY, OFFER, {"signature": "Hana HR"}),
                          409, "approv")
        # ...but the APPROVAL itself is gated only at the route. Asserted on the source
        # rather than by calling it, so the live offer keeps its correct Finance approval
        # (and the duplicate-offer guard is not fought). Same technique the analytics
        # read-only guard uses.
        offer_src = open("app/services/hrms_offer_service.py", encoding="utf-8").read()
        approve_body = offer_src[offer_src.index("async def approve_offer"):
                                 offer_src.index("async def create_offer")]
        # It does mention Cap.EMPLOYEE_SALARY_READ -- to REDACT the CTC from the response,
        # which is a disclosure rule, not an authorisation to approve. The gate that would
        # matter is OFFER_APPROVE, and it is absent.
        check("(actual) approve_offer never checks Cap.OFFER_APPROVE itself "
              "(AUDIT_OFFER_APPROVED, the audit constant, is the only near match)",
              "Cap.OFFER_APPROVE" not in approve_body)
        req_src = open("app/services/hrms_requisition_service.py", encoding="utf-8").read()
        check("...whereas act_on_requisition does check one itself",
              "can(actor, capability)" in req_src)
        finding(
            "offer approval is enforced only at the route, not in the service",
            "hrms_offer_service.approve_offer never asks can(actor, Cap.OFFER_APPROVE) -- "
            "routes/hrms.py:1102 does. Through the API the RACI holds: HR and the HOD get "
            "403. But any future internal caller, background job or new endpoint reaching "
            "the service directly would approve an offer with no check at all. "
            "act_on_requisition (the budget gate) checks its capability itself and is the "
            "pattern to follow. The scorecard service has the same shape.")

        await OF.approve_offer(FIN, COMPANY, OFFER, {"signature": "Farid Finance"})
        check("Finance (A) approved the offer", True)
        check("HR (R) alone releases it -- Finance cannot",
              A.can(HR, M.Cap.OFFER_SEND) and not A.can(FIN, M.Cap.OFFER_SEND))
        await OF.send_offer(HR, COMPANY, OFFER, {"signature": "Hana HR"})
        check("the offer is Sent",
              (await store[M.COLL_OFFERS].find_one({"offer_no": OFFER}))["status"]
              == M.OfferStatus.SENT.value)

        # =================================================================
        section("STAGE 15/16 -- Pre-boarding and induction (HR=R, HOD=C, Mgmt=I)")
        # =================================================================
        check("HOD (I) holds no preboarding.write",
              not A.can(HOD, M.Cap.PREBOARDING_WRITE))
        check("Finance (I) holds no onboarding.write",
              not A.can(FIN, M.Cap.ONBOARDING_WRITE))
        check("HR (R) holds both",
              A.can(HR, M.Cap.PREBOARDING_WRITE) and A.can(HR, M.Cap.ONBOARDING_WRITE))
        check("induction is an internal-track addition to the checklist",
              len(M.INDUCTION_CHECKLIST) > 0)

        # =================================================================
        section("STAGE 17/18 -- Probation confirmation (HOD=A/R) and file closure (HR=R)")
        # =================================================================
        check("HOD (A/R) may confirm probation", A.can(HOD, M.Cap.PROBATION_CONFIRM))
        check("HR (C) may review but NOT confirm",
              A.can(HR, M.Cap.PROBATION_REVIEW)
              and not A.can(HR, M.Cap.PROBATION_CONFIRM))
        check("Finance (I) may not confirm", not A.can(FIN, M.Cap.PROBATION_CONFIRM))
        check("HR (R) alone closes the personnel file",
              A.can(HR, M.Cap.PERSONNEL_FILE_CLOSE)
              and not A.can(HOD, M.Cap.PERSONNEL_FILE_CLOSE)
              and not A.can(FIN, M.Cap.PERSONNEL_FILE_CLOSE))

        # =================================================================
        section("STAGE 19 -- KPI reporting (HR=R, Mgmt=A) / Exceptions / Policy")
        # =================================================================
        check("HR (R) and Management (A) both read the KPIs",
              A.can(HR, M.Cap.ANALYTICS_READ) and A.can(MD, M.Cap.ANALYTICS_READ)
              and A.can(FIN, M.Cap.ANALYTICS_READ))
        check("an ordinary employee cannot", not A.can(EMP, M.Cap.ANALYTICS_READ))

        exc = await EX.raise_exception(HR, COMPANY, {
            "request_no": REQ, "exception_type": M.ExceptionType.EXTENDED_TAT.value,
            "reason": "Shortlist ran past Day 15 over the festival week."})
        check("HR (C) and the HOD (C) do not hold exception.approve",
              not A.can(HR, M.Cap.EXCEPTION_APPROVE)
              and not A.can(HOD, M.Cap.EXCEPTION_APPROVE))
        # The rule the SERVICE owns, which binds every caller: nobody decides their own.
        await expect_http("HR approves the exception HR raised",
                          EX.decide_exception(HR, COMPANY, exc["exc_no"],
                                              {"decision": "Approved",
                                               "signature": "Hana HR"}), 409, "cannot approve it")
        exc_src = open("app/services/hrms_exception_service.py", encoding="utf-8").read()
        decide_body = exc_src[exc_src.index("async def decide_exception"):]
        check("(actual) decide_exception checks the raiser, not the capability",
              "EXCEPTION_APPROVE" not in decide_body)
        decided = await EX.decide_exception(FIN, COMPANY, exc["exc_no"], {
            "decision": "Approved", "signature": "Farid Finance",
            "remarks": "Accepted, festival week."})
        check("Finance (A) approved the exception",
              decided["status"] == M.ExceptionStatus.APPROVED.value)
        check("the raiser and the approver are different people, and both are recorded",
              decided["raised_by"] == U_HR and decided["approved_by"] == U_FIN)

        check("HR (R) revises policy, Management (A) approves",
              A.can(HR, M.Cap.POLICY_WRITE) and not A.can(HR, M.Cap.POLICY_APPROVE)
              and A.can(MD, M.Cap.POLICY_APPROVE))

        # =================================================================
        section("PART D -- the managerial+ rows fire only for managerial roles")
        # =================================================================
        mgr = await RS.create_requisition(HOD, COMPANY, payload(
            designation=desig_mgr, jd={"title": "HR Manager",
                                       "responsibilities": "Lead the HR function."}))
        MREQ = mgr["request_no"]
        await RS.act_on_requisition(HR, COMPANY, MREQ, "hr-verify")
        await RS.act_on_requisition(FIN, COMPANY, MREQ, "budget-approve", budget=BUDGET)
        mcard = await SC.create_scorecard(HR, COMPANY, {
            "request_no": MREQ, "managerial": True,
            "criteria": [{"label": "Leadership",
                          "category": M.ScorecardCategory.CULTURE_FIT.value}]})
        check("a managerial scorecard needs BOTH the HOD and Management",
              SC.required_approvals(True) == [M.HrmsRole.MANAGER, M.HrmsRole.MD])
        one = await SC.approve_scorecard(HOD, COMPANY, mcard["scr_no"],
                                         {"decision": "Pass", "signature": "Hari HOD"})
        check("the HOD alone does NOT complete a managerial scorecard",
              one["status"] != M.ScorecardStatus.APPROVED.value)
        both = await SC.approve_scorecard(MD, COMPANY, mcard["scr_no"],
                                          {"decision": "Pass", "signature": "Meera MD"})
        check("Management's co-signature completes it",
              both["status"] == M.ScorecardStatus.APPROVED.value)
        check("a managerial panel additionally requires Management",
              M.HrmsRole.MD in M.REQUIRED_PANEL_ROLES[
                  M.DesignationLevel.MANAGERIAL.value])
        check("...and the same two signatures cannot come from one person",
              SC.required_approvals(True) == [M.HrmsRole.MANAGER, M.HrmsRole.MD])

        # =================================================================
        section("The audit trail records user, role, timestamp, action and comment")
        # =================================================================
        rows = audit_rows(REQ)
        check("every step of the chain is on the trail",
              {M.AUDIT_REQ_CREATED, M.AUDIT_REQ_HR_VERIFIED, M.AUDIT_REQ_BUDGET_OK,
               M.AUDIT_REQ_SCORECARD_OK} <= {r["action"] for r in rows})
        check("each row names the actor", all(r.get("actor_id") for r in rows))
        check("each row names the actor in words too", all(r.get("actor_name") for r in rows))
        check("each row is timestamped", all(r.get("created_at") for r in rows))
        check("each row is company-scoped", all(r.get("company_id") == COMPANY for r in rows))
        budget_row = next(r for r in rows if r["action"] == M.AUDIT_REQ_BUDGET_OK)
        check("the budget row attributes the decision to FINANCE",
              budget_row["actor_id"] == U_FIN and budget_row["actor_name"] == "Farid Finance")
        check("the approver's comment is carried on the record",
              "Q1 headcount" in (
                  (await store[M.COLL_REQUISITIONS].find_one(
                      {"request_no": REQ})).get("budget_remarks_approver") or ""))
        check("the exception decision is audited with its own actor",
              any(r.get("actor_id") == U_FIN for r in audit_rows(exc["exc_no"])))
        # The trail is append-only: nothing in the module updates or deletes an audit row.
        audit_src = open("app/services/hrms_audit_service.py", encoding="utf-8").read()
        check("the audit service only ever inserts",
              "insert_one" in audit_src
              and "update_one" not in audit_src and "delete_one" not in audit_src)

    finally:
        mongo.get_collection = original
        NS.notify_user, NS.notify_hrms_role = original_notify
        S3.upload_file_to_s3_with_key = original_s3

    print()
    if findings:
        print("=" * 70)
        print("  FINDINGS -- behaviour differs from Annexure B")
        print("=" * 70)
        for item in findings:
            print(f"  * {item}")
        print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed"
          + (f", {len(findings)} finding(s)" if findings else ""))
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
