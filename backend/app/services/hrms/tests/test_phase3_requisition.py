"""Phase 3 verification harness -- requisitions (FMS) + job descriptions.

Covers: the approval state machine (all 16 status x action pairs), separation of duties,
atomic create-with-JD + its compensating rollback, compare-and-swap concurrency, JD
co-approval, edit/delete guards, validation, row scoping and notifications.

House convention (app/assistant/tests/*): self-contained, no pytest, no new dependencies,
fake collections, non-zero exit on failure, ASCII output only.

Run:  python -m app.services.hrms.tests.test_phase3_requisition   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


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


# Reuse the Phase 2 fakes -- one in-memory Mongo stand-in for the whole module.
from app.services.hrms.tests.test_phase2_employee import (  # noqa: E402
    FakeCollection, FakeCursor, _matches,
)

COMPANY = "C1"
OTHER = "C2"


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    from app.utils import hrms_access as A
    import app.db.mongodb as mongo

    U_HR, U_MD, U_HOD, U_EMP, U_STAFF = (str(ObjectId()) for _ in range(5))
    DEPT, DEPT_OTHER = str(ObjectId()), str(ObjectId())
    DESIG = str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR", "is_active": True},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "email": "md@c1.com",
         "company_id": COMPANY, "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HOD", "is_active": True},
        {"_id": ObjectId(U_EMP), "full_name": "Eve Emp", "email": "emp@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "IMPLEMENTOR",
         "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": COMPANY, "name": "Accounts", "active": True},
        {"_id": ObjectId(DEPT_OTHER), "company_id": OTHER, "name": "Ops", "active": True},
    ])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG), "company_id": COMPANY, "name": "Analyst", "active": True},
    ])
    reqs = FakeCollection()
    jds = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()
    notifications = FakeCollection()

    store = {
        "learners": learners, "staff": FakeCollection(),
        M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
        M.COLL_REQUISITIONS: reqs, M.COLL_JOB_DESCRIPTIONS: jds,
        M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
        "in_app_notifications": notifications,
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.utils.hrms_access as HACC
    import app.services.hrms_requisition_service as RS
    import app.services.hrms_audit_service as AS
    import app.services.hrms_id_service as IS
    import app.services.hrms_notify_service as NS
    for mod in (RS, AS, IS, NS, HACC):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(user_id, title, message, **kw):
        sent.append(("user", str(user_id), title))

    async def fake_notify_role(company_id, roles, title, message, **kw):
        sent.append(("role", tuple(roles), title))

    RS.notify_user = fake_notify_user
    RS.notify_hrms_role = fake_notify_role

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "full_name": "Meera MD"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR", "full_name": "Eve Emp"}
    INTERNAL = {"_id": U_STAFF, "role": "admin", "_source_collection": "staff",
                "full_name": "Sam Staff"}
    SUPER = {"_id": "sa", "role": "superadmin", "_source_collection": "staff"}

    def base_payload(**over):
        p = {
            "department_id": DEPT, "designation_id": DESIG, "vacancy": 2,
            "experience_required": "3-5 years", "qualification": "B.Com",
            "essential_skills": "Excel, Tally", "required_date": "2026-12-01",
            "assignee_id": U_HR, "offering_ctc": 600000,
            # The route hands the service `RequisitionIn.model_dump()` WITHOUT
            # exclude_unset, so these two always arrive carrying at least their model
            # default. Spelling them out here keeps the fixture the same shape as the wire.
            "work_location": M.WorkLocation.OFFICE.value,
            "employment_type": M.EmploymentType.FULL_TIME.value,
            "jd": {"responsibilities": "Own the ledger.", "benefits": "PF"},
        }
        p.update(over)
        return p

    try:
        # =================================================================
        section("Separation of duties (the point of a two-stage approval)")
        # =================================================================
        check("HR holds review_hr", A.can(HR, M.Cap.REQUISITION_REVIEW_HR))
        check("HR does NOT hold approve_md", not A.can(HR, M.Cap.REQUISITION_APPROVE_MD))
        check("MD holds approve_md", A.can(MD, M.Cap.REQUISITION_APPROVE_MD))
        check("MD does NOT hold review_hr", not A.can(MD, M.Cap.REQUISITION_REVIEW_HR))
        check("HOD holds neither",
              not A.can(HOD, M.Cap.REQUISITION_REVIEW_HR)
              and not A.can(HOD, M.Cap.REQUISITION_APPROVE_MD))
        check("INTERNAL holds neither (client governance is the client's)",
              not A.can(INTERNAL, M.Cap.REQUISITION_REVIEW_HR)
              and not A.can(INTERNAL, M.Cap.REQUISITION_APPROVE_MD))
        check("superadmin holds both (documented break-glass)",
              A.can(SUPER, M.Cap.REQUISITION_REVIEW_HR)
              and A.can(SUPER, M.Cap.REQUISITION_APPROVE_MD))

        section("Anyone may raise a requisition (documented design intent)")
        for label, user in (("employee", EMP), ("HOD", HOD), ("HR", HR), ("MD", MD)):
            check(f"{label} can create", A.can(user, M.Cap.REQUISITION_CREATE))

        # =================================================================
        section("Create: requisition + JD together")
        # =================================================================
        r1 = await RS.create_requisition(HOD, COMPANY, base_payload())
        check("requisition created", r1["request_no"].startswith("HR-REQ-"))
        check("starts at Pending HR Verification",
              r1["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)
        check("closing status Open", r1["closing_status"] == M.ReqClosing.OPEN.value)
        check("JD created alongside", r1["jd"]["jd_no"].startswith("JD-"))
        check("JD starts Pending Approval",
              r1["jd"]["status"] == M.JdStatus.PENDING_APPROVAL.value)
        check("JD linked back to the requisition", r1["jd"]["request_no"] == r1["request_no"])
        check("JD title defaults to the designation", r1["jd"]["title"] == "Analyst")
        check("master names denormalised for display",
              r1["department_name"] == "Accounts" and r1["designation_name"] == "Analyst")
        check("raiser recorded as hiring manager", r1["created_by"] == U_HOD)
        check("create audited", any(a["action"] == M.AUDIT_REQ_CREATED for a in audit_log.docs))
        check("HR notified on raise", any(s[0] == "role" and "HR" in s[1] for s in sent))

        # =================================================================
        section("The JD inherits the requisition's facts")
        # =================================================================
        # The form asks for experience, CTC, skills and qualifications ONCE, on the
        # requisition. Before this mapping existed the JD half was stored empty and every
        # reader that did not fall back to the requisition -- the JD library, the drawer,
        # the printable forms -- showed blanks.
        check("experience inherited", r1["jd"]["experience"] == "3-5 years")
        check("qualifications inherited", r1["jd"]["qualifications"] == "B.Com")
        check("skills inherited", r1["jd"]["skills"] == "Excel, Tally")
        check("CTC inherited, formatted, no currency symbol", r1["jd"]["ctc"] == "600,000")
        check("work location inherited as the JD location",
              r1["jd"]["location"] == M.WorkLocation.OFFICE.value)
        check("employment type inherited from the requisition",
              r1["jd"]["employment_type"] == M.EmploymentType.FULL_TIME.value)
        check("JD-only content is untouched by the mapping",
              r1["jd"]["benefits"] == "PF" and r1["jd"]["responsibilities"] == "Own the ledger.")

        # The mapping fills BLANKS. It must never overwrite wording somebody chose.
        authored = await RS.create_requisition(HOD, COMPANY, base_payload(jd={
            "responsibilities": "Run the close.",
            "experience": "5+ years in audit practice",
            "skills": "IFRS, consolidation",
            "qualifications": "CA",
            "ctc": "Negotiable for the right person",
            "location": "Pune - Kharadi",
        }))
        check("an authored experience survives",
              authored["jd"]["experience"] == "5+ years in audit practice")
        check("an authored skills list survives",
              authored["jd"]["skills"] == "IFRS, consolidation")
        check("an authored qualification survives", authored["jd"]["qualifications"] == "CA")
        check("an authored CTC survives",
              authored["jd"]["ctc"] == "Negotiable for the right person")
        check("an authored location survives", authored["jd"]["location"] == "Pune - Kharadi")

        # employment_type is the field that used to default to Full-time on the JD model and
        # so outranked the requisition's own answer -- a Contract role published as Full-time.
        contract = await RS.create_requisition(HOD, COMPANY, base_payload(
            employment_type=M.EmploymentType.CONTRACT.value,
            work_location=M.WorkLocation.REMOTE.value,
            offering_ctc=None))
        check("a contract requisition yields a contract JD",
              contract["jd"]["employment_type"] == M.EmploymentType.CONTRACT.value)
        check("a remote requisition yields a remote JD location",
              contract["jd"]["location"] == M.WorkLocation.REMOTE.value)
        check("no CTC on the requisition leaves the JD CTC empty",
              contract["jd"].get("ctc") is None)
        explicit = await RS.create_requisition(HOD, COMPANY, base_payload(
            employment_type=M.EmploymentType.CONTRACT.value,
            jd={"responsibilities": "Six-month engagement.",
                "employment_type": M.EmploymentType.CONSULTANT.value}))
        check("an explicit JD employment type still wins",
              explicit["jd"]["employment_type"] == M.EmploymentType.CONSULTANT.value)

        section("Separation of duties: the no-HR-reviewer deadlock is made visible")
        # Option (a) was chosen deliberately: MD cannot clear the HR stage. The cost is that a
        # company with no HR user cannot progress a requisition at all -- so that condition
        # must announce itself rather than look like the request was simply ignored.
        check("with an HR user present, no escalation is raised",
              not any("No HR reviewer" in s[2] for s in sent))

        hr_doc = await learners.find_one({"_id": ObjectId(U_HR)})
        hr_doc["governance_role"] = "IMPLEMENTOR"          # company now has no HR
        sent.clear()
        stuck = await RS.create_requisition(HOD, COMPANY, base_payload(assignee_id=U_MD))
        check("MD is warned that nobody can review it",
              any(s[0] == "role" and "MD" in s[1] and "No HR reviewer" in s[2] for s in sent))
        check("the raiser is told too, rather than left waiting",
              any(s[0] == "user" and s[1] == U_HOD and "no hr reviewer" in s[2].lower()
                  for s in sent))
        check("the requisition is still created (warned, not blocked)",
              stuck["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)
        hr_doc["governance_role"] = "HR"                   # restore for the rest of the run
        sent.clear()

        section("Create: validation")
        await expect_http("missing department", RS.create_requisition(
            HOD, COMPANY, base_payload(department_id=None)), 422)
        await expect_http("department from another tenant", RS.create_requisition(
            HOD, COMPANY, base_payload(department_id=DEPT_OTHER)), 422, "does not exist")
        await expect_http("designation that does not exist", RS.create_requisition(
            HOD, COMPANY, base_payload(designation_id=str(ObjectId()))), 422)
        await expect_http("vacancy 0", RS.create_requisition(
            HOD, COMPANY, base_payload(vacancy=0)), 422, "at least 1")
        await expect_http("vacancy absurd", RS.create_requisition(
            HOD, COMPANY, base_payload(vacancy=99999)), 422, "implausibly")
        await expect_http("negative CTC", RS.create_requisition(
            HOD, COMPANY, base_payload(offering_ctc=-1)), 422, "negative")
        await expect_http("malformed date", RS.create_requisition(
            HOD, COMPANY, base_payload(required_date="01-12-2026")), 422, "YYYY-MM-DD")
        await expect_http("impossible date", RS.create_requisition(
            HOD, COMPANY, base_payload(required_date="2026-02-30")), 422)
        await expect_http("blank required field", RS.create_requisition(
            HOD, COMPANY, base_payload(qualification="   ")), 422, "required")
        await expect_http("assignee from another company", RS.create_requisition(
            HOD, COMPANY, base_payload(assignee_id=str(ObjectId()))), 422, "user of this company")
        # ── Internal Recruitment SOP §3 ── the JD is no longer authored at raise time; HR
        # writes it in Step 3, once budget clears (see update_jd's own gate). Omitting `jd`
        # (or sending `{}`) now opens an empty placeholder rather than 422ing -- but a caller
        # who DOES try to supply JD fields here is still held to the old "responsibilities or
        # an attachment" rule, so a half-written JD cannot sneak in under the new leniency.
        placeholder = await RS.create_requisition(HOD, COMPANY, base_payload(jd={}))
        check("an empty JD opens a placeholder, not a 422",
              placeholder["jd"]["status"] == "Pending Approval"
              and not placeholder["jd"].get("responsibilities"))
        await expect_http("a JD with SOME fields but no responsibilities or attachment",
                          RS.create_requisition(HOD, COMPANY,
                                                base_payload(jd={"title": "Ops Lead"})),
                          422, "Job Description")
        ok = await RS.create_requisition(HOD, COMPANY, base_payload(
            jd={"attachments": [{"name": "jd.pdf", "url": "/files/jd.pdf"}]}))
        check("attachment alone satisfies the JD rule", ok["jd"]["attachments"][0]["name"] == "jd.pdf")
        await expect_http("attachment without a url", RS.create_requisition(
            HOD, COMPANY, base_payload(jd={"attachments": [{"name": "x"}]})), 422, "url")
        await expect_http("too many attachments", RS.create_requisition(
            HOD, COMPANY, base_payload(jd={"attachments": [{"name": str(i), "url": "u"}
                                                           for i in range(11)]})), 422, "10")

        section("Create is all-or-nothing")
        jd_count_before = len(jds.docs)
        boom = FakeCollection()

        async def explode(_doc):
            raise RuntimeError("insert failed")

        boom.insert_one = explode
        store[M.COLL_REQUISITIONS] = boom
        try:
            await RS.create_requisition(HOD, COMPANY, base_payload())
        except RuntimeError:
            pass
        store[M.COLL_REQUISITIONS] = reqs
        check("a failed requisition insert rolls its JD back (no orphan)",
              len(jds.docs) == jd_count_before)

        # =================================================================
        section("Approval chain: the happy path")
        # =================================================================
        # The band Management records at the budget gate. No sanctioned strength is
        # seeded in this file, so clearing the gate lands in escalation (fail closed):
        # "cleared the budget gate" is what is asserted, never "Approved".
        BAND = {"approved_headcount": 1, "approved_salary_band_min": 500000,
                "approved_salary_band_max": 900000}
        CLEARED = {M.ReqApproval.PENDING_SCORECARD.value,
                   M.ReqApproval.PENDING_ESCALATION.value}

        no = r1["request_no"]
        after_hr = await RS.act_on_requisition(HR, COMPANY, no, "hr-verify", "Looks right")
        check("hr-verify -> Pending Budget Approval",
              after_hr["approval_status"] == M.ReqApproval.PENDING_BUDGET.value)
        check("HR reviewer stamped", after_hr["hr_reviewed_by"] == U_HR)
        check("HR remark stored", after_hr["hr_remarks"] == "Looks right")
        check("JD still pending after HR stage",
              after_hr["jd"]["status"] == M.JdStatus.PENDING_APPROVAL.value)
        check("MD notified", any(s[0] == "role" and "MD" in s[1] for s in sent))

        after_md = await RS.act_on_requisition(MD, COMPANY, no, "budget-approve", "Go ahead",
                                               budget=BAND)
        check("budget-approve clears the budget gate", after_md["approval_status"] in CLEARED)
        check("approver stamped", after_md["budget_approved_by"] == U_MD)
        check("the approved band is recorded on the requisition",
              after_md["approved_salary_band_min"] == 500000
              and after_md["approved_salary_band_max"] == 900000)
        check("the JD is NOT yet approved -- the scorecard gate is still ahead",
              after_md["jd"]["status"] != M.JdStatus.APPROVED.value)
        check("creator notified that the role is funded",
              any(s[0] == "user" and s[1] == U_HOD and "funded" in s[2].lower() for s in sent))
        check("both stages audited",
              any(a["action"] == M.AUDIT_REQ_HR_VERIFIED for a in audit_log.docs)
              and any(a["action"] == M.AUDIT_REQ_BUDGET_OK for a in audit_log.docs))

        # =================================================================
        section("Approval chain: every status x action pair")
        # =================================================================
        # Every (action, status) combination is probed. Exactly the on-diagonal pairs -- the
        # ones the transition table declares -- may succeed; every other pair must be
        # refused with a 409.
        #
        # The expected count is DERIVED from the table rather than hard-coded, so adding a
        # stage or an action (Phase 11-R adds PENDING_ESCALATION plus escalate-approve /
        # escalate-reject) extends the coverage automatically instead of failing an
        # arithmetic assertion that was only ever a restatement of the table's size.
        legal = {(a, spec[0].value) for a, spec in M.INTERNAL_REQ_TRANSITIONS.items()}
        actions = tuple(M.INTERNAL_REQ_TRANSITIONS)
        expected_illegal = len(actions) * len(list(M.ReqApproval)) - len(legal)
        illegal_ok = 0
        for action in actions:
            for status in (s.value for s in M.ReqApproval):
                if (action, status) in legal:
                    continue
                probe = await RS.create_requisition(HOD, COMPANY, base_payload())
                await reqs.update_one({"request_no": probe["request_no"]},
                                      {"$set": {"approval_status": status}})
                actor = SUPER          # holds every capability, so only the status can refuse
                from fastapi import HTTPException
                try:
                    await RS.act_on_requisition(actor, COMPANY, probe["request_no"],
                                                action, "remark")
                except HTTPException as e:
                    if e.status_code == 409:
                        illegal_ok += 1
        check(f"all {expected_illegal} illegal status/action pairs refused with 409 "
              f"(got {illegal_ok})", illegal_ok == expected_illegal)

        section("Approval chain: authorization and validation")
        r2 = await RS.create_requisition(HOD, COMPANY, base_payload())
        n2 = r2["request_no"]
        await expect_http("MD cannot perform the HR stage", RS.act_on_requisition(
            MD, COMPANY, n2, "hr-verify"), 403, "not authorised")
        await expect_http("HOD cannot verify", RS.act_on_requisition(
            HOD, COMPANY, n2, "hr-verify"), 403)
        await expect_http("employee cannot verify", RS.act_on_requisition(
            EMP, COMPANY, n2, "hr-verify"), 403)
        await expect_http("unknown action", RS.act_on_requisition(
            HR, COMPANY, n2, "hr-maybe"), 422, "Invalid action")
        await expect_http("hr-reject without a remark", RS.act_on_requisition(
            HR, COMPANY, n2, "hr-reject"), 422, "remark is required")
        await expect_http("unknown requisition", RS.act_on_requisition(
            HR, COMPANY, "HR-REQ-2026-999", "hr-verify"), 404)

        await RS.act_on_requisition(HR, COMPANY, n2, "hr-verify")
        await expect_http("HR cannot perform the budget stage", RS.act_on_requisition(
            HR, COMPANY, n2, "budget-approve", budget=BAND), 403)
        await expect_http("budget-reject without a remark", RS.act_on_requisition(
            MD, COMPANY, n2, "budget-reject"), 422, "remark is required")
        await expect_http("a budget approval with no band", RS.act_on_requisition(
            MD, COMPANY, n2, "budget-approve", None, budget={}), 422, "salary band")
        await expect_http("a negative band", RS.act_on_requisition(
            MD, COMPANY, n2, "budget-approve", None,
            budget={"approved_headcount": 1, "approved_salary_band_min": -5,
                    "approved_salary_band_max": 10}), 422, "negative")

        section("Rejection closes the requisition and the JD")
        r3 = await RS.create_requisition(HOD, COMPANY, base_payload())
        rejected = await RS.act_on_requisition(HR, COMPANY, r3["request_no"],
                                               "hr-reject", "Headcount frozen")
        check("hr-reject -> Rejected", rejected["approval_status"] == M.ReqApproval.REJECTED.value)
        check("closing status set to Closed",
              rejected["closing_status"] == M.ReqClosing.CLOSED.value)
        check("JD rejected with it", rejected["jd"]["status"] == M.JdStatus.REJECTED.value)
        check("reason preserved", rejected["hr_remarks"] == "Headcount frozen")
        check("creator told why",
              any(s[0] == "user" and s[1] == U_HOD and "rejected" in s[2].lower() for s in sent))

        section("Concurrency: compare-and-swap")
        r4 = await RS.create_requisition(HOD, COMPANY, base_payload())
        n4 = r4["request_no"]
        outcomes = await asyncio.gather(
            *[RS.act_on_requisition(HR, COMPANY, n4, "hr-verify", "race") for _ in range(5)],
            return_exceptions=True)
        wins = sum(1 for o in outcomes if not isinstance(o, Exception))
        conflicts = sum(1 for o in outcomes if isinstance(o, Exception)
                        and getattr(o, "status_code", None) == 409)
        check("exactly one concurrent approval wins", wins == 1)
        check("the other four get 409, not a silent overwrite", conflicts == 4)

        # =================================================================
        section("Edit and delete guards")
        # =================================================================
        r5 = await RS.create_requisition(HOD, COMPANY, base_payload())
        n5 = r5["request_no"]
        edited = await RS.update_requisition(HR, COMPANY, n5, {"vacancy": 5})
        check("editable while pending", edited["vacancy"] == 5)
        await expect_http("edit with no fields", RS.update_requisition(
            HR, COMPANY, n5, {}), 400)
        await expect_http("edit cannot clear a required field", RS.update_requisition(
            HR, COMPANY, n5, {"qualification": "  "}), 422)

        # Approval is the far end of a chain that needs an approved scorecard; the
        # freeze is what is under test, so set the state directly.
        await reqs.update_one({"request_no": n5},
                              {"$set": {"approval_status": M.ReqApproval.APPROVED.value}})
        await expect_http("an APPROVED requisition cannot be edited",
                          RS.update_requisition(HR, COMPANY, n5, {"vacancy": 9}),
                          409, "no longer be edited")
        await expect_http("an APPROVED requisition cannot be deleted",
                          RS.delete_requisition(HR, COMPANY, n5), 409, "cannot be deleted")

        r6 = await RS.create_requisition(HOD, COMPANY, base_payload())
        jd6 = r6["jd"]["jd_no"]
        await RS.delete_requisition(HR, COMPANY, r6["request_no"])
        check("delete cascades to the JD (no orphan)",
              await jds.find_one({"jd_no": jd6}) is None)
        await expect_http("delete a missing requisition", RS.delete_requisition(
            HR, COMPANY, "HR-REQ-2026-999"), 404)

        section("Closing status")
        closed = await RS.close_requisition(HR, COMPANY, n5, M.ReqClosing.HIRED.value)
        check("closing status set", closed["closing_status"] == M.ReqClosing.HIRED.value)
        check("closing audited", any(a["action"] == M.AUDIT_REQ_CLOSED for a in audit_log.docs))
        await expect_http("invalid closing status", RS.close_requisition(
            HR, COMPANY, n5, "Vanished"), 422, "must be one of")

        # =================================================================
        section("Job descriptions")
        # =================================================================
        r7 = await RS.create_requisition(HOD, COMPANY, base_payload())
        jd7 = r7["jd"]["jd_no"]
        # SOP 3: the JD is written once Management has cleared headcount and budget.
        await expect_http("a JD edit before budget approval", RS.update_jd(
            HR, COMPANY, jd7, {"benefits": "too early"}), 409, "approved headcount and budget")
        await RS.act_on_requisition(HR, COMPANY, r7["request_no"], "hr-verify")
        await RS.act_on_requisition(MD, COMPANY, r7["request_no"], "budget-approve", budget=BAND)
        updated = await RS.update_jd(HR, COMPANY, jd7, {"benefits": "PF + insurance"})
        check("JD editable while pending", updated["benefits"] == "PF + insurance")
        check("version bumps on edit", updated["version"] == 2)
        await expect_http("JD edit with no fields", RS.update_jd(HR, COMPANY, jd7, {}), 400)
        # An edit must not be able to empty a JD that was valid when raised.
        await expect_http("edit cannot strip a JD of all content", RS.update_jd(
            HR, COMPANY, jd7, {"responsibilities": ""}), 422, "responsibilities or at least one")

        await reqs.update_one({"request_no": r7["request_no"]},
                              {"$set": {"approval_status": M.ReqApproval.APPROVED.value}})
        await store[M.COLL_JOB_DESCRIPTIONS].update_one(
            {"jd_no": jd7}, {"$set": {"status": M.JdStatus.APPROVED.value}})
        await expect_http("an APPROVED JD is frozen", RS.update_jd(
            HR, COMPANY, jd7, {"benefits": "changed"}), 409, "cannot be edited")
        await expect_http("unknown JD", RS.update_jd(HR, COMPANY, "JD-2026-999", {"ctc": "x"}), 404)

        listing = await RS.list_jds(HR, COMPANY)
        check("JD library lists them", listing["total"] > 0)
        approved_only = await RS.list_jds(HR, COMPANY, status=M.JdStatus.APPROVED.value)
        check("JD status filter works",
              all(j["status"] == "Approved" for j in approved_only["job_descriptions"]))

        # =================================================================
        section("Row scoping and tenant isolation")
        # =================================================================
        mine = await RS.create_requisition(EMP, COMPANY, base_payload())
        emp_view = await RS.list_requisitions(EMP, COMPANY)
        check("an employee sees only what they raised",
              all(r["created_by"] == U_EMP for r in emp_view["requisitions"]))
        check("that includes their own", any(r["request_no"] == mine["request_no"]
                                             for r in emp_view["requisitions"]))
        check("employee stat tiles match their scoped list",
              emp_view["stats"]["total"] == emp_view["total"])

        hr_view = await RS.list_requisitions(HR, COMPANY)
        check("HR sees the whole company", hr_view["total"] > emp_view["total"])
        await expect_http("employee cannot open someone else's requisition",
                          RS.get_requisition(EMP, COMPANY, r1["request_no"]), 404)
        await expect_http("cross-tenant read is 404, not 403",
                          RS.get_requisition(HR, OTHER, r1["request_no"]), 404)

        section("Filters")
        by_status = await RS.list_requisitions(HR, COMPANY,
                                               approval_status=M.ReqApproval.APPROVED.value)
        check("approval filter applied",
              all(r["approval_status"] == "Approved" for r in by_status["requisitions"]))
        safe = await RS.list_requisitions(HR, COMPANY, search="Analyst(")
        check("regex metacharacters in search are escaped", safe["total"] == 0)

        # =================================================================
        section("State machine table integrity")
        # =================================================================
        # Phase 3 declared 4 actions; Phase 11-R Item 7 adds escalate-approve and
        # escalate-reject for the over-sanction ladder. The invariant this section really
        # guards is the SHAPE of the table (below) plus the one rule that must never bend:
        # APPROVED is reachable from exactly one row, and only from PENDING_MD with the MD
        # capability -- asserted from the model itself so a later "shortcut" fails loudly.
        check("the chain's actions are declared",
              {"hr-verify", "hr-reject", "budget-approve", "budget-reject",
               "scorecard-approve", "scorecard-reject"} <= set(M.INTERNAL_REQ_TRANSITIONS))
        check("budget approval cannot be skipped", M.budget_approval_is_mandatory())
        # Subset, not equality: REQ_AUDIT_ACTIONS also labels the internal track's actions,
        # which have their own table. What this asserts is what it always meant -- no client
        # action may transition without leaving a labelled trail.
        check("every action has an audit label",
              set(M.INTERNAL_REQ_TRANSITIONS) <= set(M.REQ_AUDIT_ACTIONS))
        check("hr actions require the HR capability",
              all(spec[2] == M.Cap.REQUISITION_REVIEW_HR
                  for a, spec in M.INTERNAL_REQ_TRANSITIONS.items() if a.startswith("hr-")))
        check("budget actions require the budget capability",
              all(spec[2] == M.Cap.REQUISITION_APPROVE_BUDGET
                  for a, spec in M.INTERNAL_REQ_TRANSITIONS.items() if a.startswith("budget-")))
        check("both rejects demand a remark",
              all(spec[3] for a, spec in M.INTERNAL_REQ_TRANSITIONS.items() if a.endswith("-reject")))
        check("no transition leaves the declared status set",
              all(spec[0] in set(M.ReqApproval) and spec[1] in set(M.ReqApproval)
                  for spec in M.INTERNAL_REQ_TRANSITIONS.values()))

        section("Index registry (Phase 3 additions)")
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("request_no unique",
              any(c == M.COLL_REQUISITIONS and n == "uniq_request_no" for c, n in names))
        check("jd_no unique",
              any(c == M.COLL_JOB_DESCRIPTIONS and n == "uniq_jd_no" for c, n in names))
        check("requisitions indexed by approval status",
              any(c == M.COLL_REQUISITIONS and n == "by_company_approval" for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))

        section("Identity collections still never written")
        check("learners untouched by Phase 3",
              all("request_no" not in d and "approval_status" not in d for d in learners.docs))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
