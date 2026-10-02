"""Two rules that were written, tested and not in effect -- now in effect.

-- F2: an internal requisition closes on PROBATION CONFIRMATION -----------------------------
SOP §7 says an internal requisition closes when the hire is confirmed, because with no
client handover nothing is final until then. `hrms_probation_service` has always had the
closer for it, and it never ran: `reconcile_requisition_closure` fired on every offer
ACCEPTANCE with no track guard, `FILLED_STATUSES` counts `Offer Accepted`, and the probation
closer refuses anything that is not still Open. So the requisition was already Hired months
early and the SOP's closer returned False every time.

The tests below drive both tracks through acceptance and confirmation and pin which one
closes where -- including the multi-vacancy case, where confirming the FIRST of three hires
must not retire a role still two short.

-- F3: `retention_until` is stamped when a record is created --------------------------------
The retention table has been right since INT-2 and almost nothing wrote the field it selects
on. It was stamped on the talent-pool paths only -- never on a hand-added CV, never on a
public application, never on an offer, never on a requisition -- and `joined_at`, the anchor
the three-year SELECTED period runs from, was read in one place and written in none.

The purge deliberately proposes nothing for a row with no date, so the effect was that the
policy applied to almost no records at all, while the retention test passed because its
fixture wrote the date by hand.

These tests assert the stamp at each point of creation, the recompute at joining, and -- the
one that matters most -- that the purge now actually selects an expired unselected CV.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int11_closure_and_retention   (from backend/)
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"


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

    U_HR, U_MD, U_FIN, U_HOD = (str(ObjectId()) for _ in range(4))
    dept, desig = ObjectId(), ObjectId()

    departments = FakeCollection([
        {"_id": dept, "company_id": COMPANY, "name": "HR", "active": True}])
    designations = FakeCollection([
        {"_id": desig, "company_id": COMPANY, "name": "HR Executive",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_FIN), "company_id": COMPANY, "full_name": "Farid Finance",
         "governance_role": "FINANCE", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "governance_role": "HOD", "role": "clientuser", "is_active": True},
    ])

    store = {c: FakeCollection() for c in (
        M.COLL_REQUISITIONS, M.COLL_JOB_DESCRIPTIONS, M.COLL_JOB_POSTINGS,
        M.COLL_CANDIDATES, M.COLL_OFFERS, M.COLL_ONBOARDING, M.COLL_PROBATION_REVIEWS,
        M.COLL_EMPLOYEE_PROFILES, M.COLL_COUNTERS, M.COLL_AUDIT_LOG, M.COLL_LINKS,
        M.COLL_SETTINGS, M.COLL_SALARY_BANDS, M.COLL_PURGE_BATCHES,
        M.COLL_REFERENCE_CHECKS, M.COLL_POSITION_SCORECARDS, M.COLL_SANCTIONED_STRENGTH)}
    store.update({M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
                  "learners": learners, "staff": FakeCollection(),
                  "companies": FakeCollection()})
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_offer_service as OF
    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_probation_service as PR
    import app.services.hrms_posting_service as PS
    import app.services.hrms_purge_service as PU
    import app.services.hrms_config_service as CFG
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_reference_service as RC
    import app.services.hrms_salary_band_service as BANDS
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_telephonic_service as TS

    SERVICES = (RS, CS, OF, OB, PR, PS, PU, CFG, AUD, IDS, SN, LS, RF, SC, RC, BANDS,
                SL, TS)
    for mod in SERVICES:
        mod.get_collection = mongo.get_collection

    # Resume upload is mandatory on the public form as of this phase, so F3's
    # submit_application() call now actually reaches the upload step -- fake it out rather
    # than hitting real S3, the same as test_e2e_recruitment_journey does.
    def fake_s3(stream, filename, mime):
        return {"key": f"s3/{filename}", "url": "https://signed.example/x"}

    import app.services.s3_service as S3
    original_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = fake_s3

    async def silent(*a, **kw):
        return None
    for mod in SERVICES:
        if hasattr(mod, "notify_user"):
            mod.notify_user = silent
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = silent
    import app.services.hrms_notify_service as NS
    keep_notify = (NS.notify_user, NS.notify_hrms_role)
    NS.notify_user, NS.notify_hrms_role = silent, silent

    # The shortlist-committee and telephonic gates are separate controls with their own
    # test files (test_int2_shortlist_committee, test_int4_telephonic). Stubbed so this file
    # measures the closure and retention rules and nothing else.
    async def _cleared(*a, **kw):
        return None
    SL.assert_shortlist_cleared = _cleared
    TS.assert_telephonic_cleared = _cleared

    def actor(uid, gov, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov, "full_name": f"{gov} user"}

    HR, MD, FIN, HOD = (actor(U_HR, "HR"), actor(U_MD, "MD", "clientadmin"),
                        actor(U_FIN, "FINANCE"), actor(U_HOD, "HOD"))
    TODAY = datetime.now(timezone.utc)

    def payload(track="internal", vacancy=1, **over):
        base = {"department_id": str(dept), "designation_id": str(desig),
                "assignee_id": U_HR, "vacancy": vacancy, "required_date": "2027-03-31",
                "experience_required": "2-4 years", "qualification": "Graduate",
                "essential_skills": "Coordination", "offering_ctc": 420000.0,
                "requisition_track": track,
                "jd": {"title": "HR Executive", "responsibilities": "Run the desk."}}
        base.update(over)
        return base

    async def approve_internal(request_no):
        await RS.act_on_requisition(HR, COMPANY, request_no, "hr-verify")
        await RS.act_on_requisition(FIN, COMPANY, request_no, "budget-approve", budget={
            "approved_headcount": 3, "approved_salary_band_min": 400000.0,
            "approved_salary_band_max": 450000.0})
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": request_no, "criteria": [{"label": "Core"}]})
        await SC.approve_scorecard(HOD, COMPANY, card["scr_no"],
                                   {"decision": "Pass", "signature": "HOD"})
        await RS.act_on_requisition(HOD, COMPANY, request_no, "scorecard-approve")

    async def add_accepted_candidate(request_no, name):
        c = await CS.create_candidate(HR, COMPANY, {
            "request_no": request_no, "candidate_name": name,
            "can_email": f"{name.lower()}@example.com", "can_contact": "+91 90000 00000"})
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": c["uk"]}, {"$set": {"application_status": M.AppStatus.OFFER_ACCEPTED.value}})
        return c["uk"]

    async def closing_of(request_no):
        return (await store[M.COLL_REQUISITIONS].find_one(
            {"request_no": request_no}))["closing_status"]

    try:
        # =================================================================
        section("F2 -- an accepted offer does NOT close an internal requisition")
        # =================================================================
        internal = await RS.create_requisition(HOD, COMPANY, payload())
        IREQ = internal["request_no"]
        await approve_internal(IREQ)
        uk1 = await add_accepted_candidate(IREQ, "Asha")

        result = await OF.reconcile_requisition_closure(HR, COMPANY, IREQ)
        check("the acceptance-time closer declines to close it", result is None)
        check("the internal requisition is still Open",
              await closing_of(IREQ) == M.ReqClosing.OPEN.value)

        section("F2 -- probation confirmation is what closes the internal one")
        await store[M.COLL_EMPLOYEE_PROFILES].insert_one({
            "_id": ObjectId(), "company_id": COMPANY, "employee_code": "EMP-1",
            "employee_name": "Asha", "status": "Active", "uk": uk1})
        prb = await PR.open_probation(HR, COMPANY, {
            "employee_code": "EMP-1", "request_no": IREQ, "uk": uk1,
            "started_on": (TODAY - timedelta(days=200)).strftime("%Y-%m-%d"),
            "duration_months": 6})
        check("a probation review was opened against the requisition", bool(prb["prb_no"]))
        # The statutory gate is a different control with its own file; waive it here so this
        # test is measuring the closer and nothing else.
        PR.assert_statutory_checks_complete = lambda *a, **kw: _noop()

        async def _noop():
            return None

        async def _chain(prb_no):
            # §7.5 Stage 12: the manager recommends and HR endorses before anybody decides.
            await PR.submit_review(HOD, COMPANY, prb_no, {
                "performance": 4, "conduct": 4, "attendance": 4, "competence": 4,
                "suitability": 4, "recommendation": "Confirm", "signature": "Hari HOD"})
            await PR.hr_review(HR, COMPANY, prb_no, {"decision": "Endorsed", "signature": "HR"})
        await _chain(prb["prb_no"])
        confirmed = await PR.confirm_probation(HOD, COMPANY, prb["prb_no"], {
            "outcome": M.ProbationOutcome.CONFIRMED.value, "signature": "Hari HOD",
            "remarks": "Confirmed."})
        check("the requisition closes as Hired on confirmation",
              await closing_of(IREQ) == M.ReqClosing.HIRED.value)
        row = await store[M.COLL_REQUISITIONS].find_one({"request_no": IREQ})
        check("it records WHICH probation closed it",
              row.get("closed_on_probation_confirmation") == prb["prb_no"])
        check("it also stamps closed_at, so 'when did this close' has one answer",
              bool(row.get("closed_at")))
        check("the closure is audited",
              any(a["action"] == M.AUDIT_REQ_CLOSED and a.get("entity_id") == IREQ
                  for a in store[M.COLL_AUDIT_LOG].docs))

        section("F2 -- three vacancies do not close on the first confirmation")
        multi = await RS.create_requisition(HOD, COMPANY, payload(vacancy=3))
        MREQ = multi["request_no"]
        await approve_internal(MREQ)
        for i, name in enumerate(("Cara", "Dev", "Esha"), start=1):
            uk = await add_accepted_candidate(MREQ, name)
            await store[M.COLL_EMPLOYEE_PROFILES].insert_one({
                "_id": ObjectId(), "company_id": COMPANY, "employee_code": f"EMP-M{i}",
                "employee_name": name, "status": "Active", "uk": uk})
        prbs = []
        for i in range(1, 4):
            p = await PR.open_probation(HR, COMPANY, {
                "employee_code": f"EMP-M{i}", "request_no": MREQ,
                "started_on": (TODAY - timedelta(days=200)).strftime("%Y-%m-%d"),
                "duration_months": 6})
            prbs.append(p["prb_no"])
        await _chain(prbs[0])
        await PR.confirm_probation(HOD, COMPANY, prbs[0], {
            "outcome": M.ProbationOutcome.CONFIRMED.value, "signature": "H", "remarks": "ok"})
        check("1 of 3 confirmed -- still Open",
              await closing_of(MREQ) == M.ReqClosing.OPEN.value)
        await _chain(prbs[1])
        await PR.confirm_probation(HOD, COMPANY, prbs[1], {
            "outcome": M.ProbationOutcome.CONFIRMED.value, "signature": "H", "remarks": "ok"})
        check("2 of 3 confirmed -- still Open",
              await closing_of(MREQ) == M.ReqClosing.OPEN.value)
        await _chain(prbs[2])
        await PR.confirm_probation(HOD, COMPANY, prbs[2], {
            "outcome": M.ProbationOutcome.CONFIRMED.value, "signature": "H", "remarks": "ok"})
        check("3 of 3 confirmed -- NOW it closes",
              await closing_of(MREQ) == M.ReqClosing.HIRED.value)

        # =================================================================
        section("F3 -- retention_until is stamped when a candidate is created")
        # =================================================================
        fresh = await RS.create_requisition(HOD, COMPANY, payload())
        FREQ = fresh["request_no"]
        await approve_internal(FREQ)
        manual = await CS.create_candidate(HR, COMPANY, {
            "request_no": FREQ, "candidate_name": "Farah",
            "can_email": "farah@example.com", "can_contact": "+91 90000 00002"})
        mrow = await store[M.COLL_CANDIDATES].find_one({"uk": manual["uk"]})
        check("a hand-added CV carries a retention floor",
              bool(mrow.get("retention_until")))
        expected_unselected = M.RETENTION_YEARS["candidate_unselected"]
        check(f"an unselected CV is kept {expected_unselected} year(s) from application",
              mrow["retention_until"][:4]
              == str(int(str(mrow["applied_at"])[:4]) + expected_unselected))

        section("F3 -- and when one arrives through the public form")
        posting = await PS.create_posting(HR, COMPANY, {"jd_no": fresh["jd_no"], "channels": ["Job Portals"]})
        code = posting["posting"]["posting_code"]
        await PS.publish_posting(HR, COMPANY, code)
        applied = await PS.submit_application(code, {
            "candidate_name": "Gita", "can_email": "gita@example.com",
            "can_contact": "+91 90000 00003", "declaration": True,
            "referral_source": M.ReferralSource.JOB_PORTAL.value,
            # Internal track: the SOP §11 acknowledgements are mandatory on this form.
            "eeo_ack": True, "data_use_ack": True,
            "resume": {"name": "gita.pdf", "mime_type": "application/pdf",
                       "data": base64.b64encode(b"%PDF-1.4 curriculum vitae").decode()}})
        grow = await store[M.COLL_CANDIDATES].find_one({"uk": applied["reference"]})
        check("a public application carries a retention floor",
              bool(grow.get("retention_until")))

        section("F3 -- joining rewrites the floor to the SELECTED period")
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": manual["uk"]},
            {"$set": {"application_status": M.AppStatus.PRE_ONBOARDING.value}})
        before = (await store[M.COLL_CANDIDATES].find_one(
            {"uk": manual["uk"]}))["retention_until"]
        await OB._advance_candidate(HR, COMPANY, manual["uk"], M.AppStatus.JOINED)
        after = await store[M.COLL_CANDIDATES].find_one({"uk": manual["uk"]})
        check("joined_at is written -- it was read everywhere and written nowhere",
              bool(after.get("joined_at")))
        check("the floor moved out to the selected period",
              after["retention_until"] > before)
        selected_years = M.RETENTION_YEARS["candidate_selected"]
        check(f"a joiner is kept {selected_years} years FROM JOINING",
              after["retention_until"][:4]
              == str(int(str(after["joined_at"])[:4]) + selected_years))

        section("F3 -- offers and requisitions are stamped too")
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": applied["reference"]},
            {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await RC.create_reference_check(HR, COMPANY, {
            "uk": applied["reference"], "referee_name": "Prior Manager",
            "outcome": M.ReferenceOutcome.POSITIVE.value,
            "responses": "Would rehire.", "checked_on": TODAY.strftime("%Y-%m-%d")})
        offer = await OF.create_offer(HR, COMPANY, {
            "uk": applied["reference"], "ctc": 420000.0,
            "joining_date": (TODAY + timedelta(days=30)).strftime("%Y-%m-%d")})
        orow = await store[M.COLL_OFFERS].find_one({"offer_no": offer["offer_no"]})
        check("an offer carries a retention floor -- it was a purge target that could "
              "never match a row", bool(orow.get("retention_until")))

        closed_req = await RS.close_requisition(HR, COMPANY, FREQ,
                                                M.ReqClosing.CLOSED.value)
        crow = await store[M.COLL_REQUISITIONS].find_one({"request_no": FREQ})
        check("closing a requisition stamps its retention floor",
              bool(crow.get("retention_until")))
        check("...anchored on the closure, per the SOP",
              crow["retention_until"][:4]
              == str(TODAY.year + M.RETENTION_YEARS["requisition"]))
        await RS.close_requisition(HR, COMPANY, FREQ, M.ReqClosing.OPEN.value)
        reopened = await store[M.COLL_REQUISITIONS].find_one({"request_no": FREQ})
        check("re-opening it clears the floor -- a live role carries no disposal date",
              reopened.get("retention_until") is None)

        # =================================================================
        section("F3 -- the purge now actually selects an expired CV")
        # =================================================================
        # An ordinary rejected applicant, expired. Before this change they carried no
        # `retention_until` at all and the purge skipped them for ever.
        stale = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Old Applicant", "can_email": "old@example.com",
            "can_contact": "+91 90000 00009"})
        srow = await store[M.COLL_CANDIDATES].find_one({"uk": stale["uk"]})
        check("the stale CV was stamped at creation", bool(srow.get("retention_until")))
        proposal = await PU.propose(
            MD, COMPANY,
            as_of=(TODAY + timedelta(days=370 * 2)).strftime("%Y-%m-%d"), dry_run=True)
        picked = {i for g in proposal["groups"] for i in g["ids"]}
        check("the purge proposes it once its floor has passed", stale["uk"] in picked)
        check("the proposal is a dry run and wrote no batch",
              len(store[M.COLL_PURGE_BATCHES].docs) == 0)

    finally:
        mongo.get_collection = original
        S3.upload_file_to_s3_with_key = original_s3
        NS.notify_user, NS.notify_hrms_role = keep_notify

    print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed")
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
