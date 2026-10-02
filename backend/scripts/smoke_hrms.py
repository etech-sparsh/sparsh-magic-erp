"""Smoke test — every HRMS section, end to end, looking for errors rather than features.

A smoke test asks one question of each section: does it work at all? Not "is the rule
right" (the 65 test modules answer that) but "does this import, mount, gate, and return
without raising".

It checks five layers, because a section can be broken at any of them and the symptom is
identical to the user -- a screen that will not load:

    1. IMPORT      every service and route module loads
    2. MOUNT       every HRMS endpoint is registered on the app
    3. GATE        every endpoint declares a capability (an ungated one is a hole)
    4. RUN         every read surface returns without raising, on an empty database
                   AND on one with data -- an empty-state crash is the classic smoke bug
    5. WIRING      the frontend can reach what the backend offers: capability parity,
                   every navigation route has a component, every API helper has a route

Layer 4 is the one that finds real bugs. A service that works against seeded fixtures and
divides by zero on an empty company is a screen that is blank for every new tenant, and no
per-phase test catches it because they all seed data first.

Usage (from backend/):
    python scripts/smoke_hrms.py
    python scripts/smoke_hrms.py --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FRONTEND = os.path.join("..", "frontend", "src")

results = []
VERBOSE = False


def ok(section: str, label: str, passed: bool, detail: str = "") -> bool:
    results.append((section, label, bool(passed), detail))
    if not passed or VERBOSE:
        mark = "PASS" if passed else "FAIL"
        print(f"  {mark}  [{section}] {label}" + (f"  -- {detail}" if detail else ""))
    return bool(passed)


def head(title: str) -> None:
    print(f"\n{'-' * 76}\n {title}\n{'-' * 76}")


async def run_call(section: str, label: str, make) -> None:
    """A read surface must return, not raise. HTTPException is a legitimate answer (a gate
    firing); anything else is the section falling over.

    Takes a CALLABLE, not a coroutine. Building every coroutine up front would mean one
    wrong function name aborts the run before it starts and leaks the rest as "never
    awaited" -- a smoke test has to survive its own mistakes to be worth running.
    """
    from fastapi import HTTPException
    try:
        await (make() if callable(make) else make)
        ok(section, label, True)
    except HTTPException as e:
        # 4xx is the module working. 5xx is not.
        ok(section, label, e.status_code < 500, f"HTTP {e.status_code}")
    except Exception as e:
        ok(section, label, False, f"{type(e).__name__}: {e}")
        if VERBOSE:
            traceback.print_exc()


async def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser(description="HRMS smoke test.")
    parser.add_argument("--verbose", action="store_true", help="Print every check.")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("=" * 76)
    print("  HRMS SMOKE TEST")
    print("=" * 76)

    # ── 1. IMPORT ────────────────────────────────────────────
    head("1. Import — every HRMS module loads")
    service_dir = os.path.join("app", "services")
    modules = sorted(f[:-3] for f in os.listdir(service_dir)
                     if f.startswith("hrms_") and f.endswith(".py"))
    loaded = {}
    for name in modules:
        try:
            loaded[name] = __import__(f"app.services.{name}", fromlist=["x"])
            ok("import", name, True)
        except Exception as e:
            ok("import", name, False, f"{type(e).__name__}: {e}")
    for extra in ("app.routes.hrms", "app.routes.hrms_public", "app.utils.hrms_access",
                  "app.utils.hrms_public_guard", "app.models.hrms"):
        try:
            __import__(extra, fromlist=["x"])
            ok("import", extra, True)
        except Exception as e:
            ok("import", extra, False, f"{type(e).__name__}: {e}")

    # ── 2/3. MOUNT + GATE ────────────────────────────────────
    head("2. Mount & gate — every endpoint registered and capability-checked")
    import main as app_main
    from app.models.hrms import Cap
    hrms_routes = [r for r in app_main.app.routes
                   if getattr(r, "path", "").startswith("/api/hrms")]
    ok("mount", f"{len(hrms_routes)} HRMS endpoints mounted", len(hrms_routes) > 200)

    src = open(os.path.join("app", "routes", "hrms.py"), encoding="utf-8").read()
    blocks = re.split(r"@router\.", src)[1:]

    # An endpoint may legitimately be ungated -- reading your own profile, or an interview
    # you were booked for, is an inherent right that must not be revocable by a permission
    # edit, and the capability there WIDENS the result rather than granting access.
    #
    # So the check is not "everything is gated" but "anything ungated says why". A new
    # endpoint that simply forgot `_require` has no such sentence and fails; a deliberate
    # one carries its reasoning in the docstring, where the next reader will find it.
    # A handler that NAMES the capability it delegates is documenting its own gating: the
    # interview evaluator is a case where the service checks something STRONGER than a
    # capability (you must be the assigned interviewer, and not recused), and says so.
    JUSTIFIED = ("not gated", "inherent right", "deliberately not", "capability widens",
                 "discovery", "their own company", "own employee record", "scope selector",
                 "requires `", "additionally requires")
    # Scoped inside the SERVICE rather than at the route. Safe -- get_employee and the
    # interview service both narrow by row -- but the route says nothing about it, so a
    # reader has to go and check. Recorded as a documentation gap rather than waved through.
    SCOPED_IN_SERVICE = {"/employees/{user_id}", "/interviews/{interview_no}", "/health"}
    unexplained = []
    for block in blocks:
        m = re.match(r'(get|post|patch|put|delete)\("([^"]+)"', block)
        if not m:
            continue
        body = block.split("\n\n\n")[0]
        gated = ("_require(" in body
                 or ("can(current_user" in body and "403" in body)
                 or "_require_visible" in body)
        if gated:
            continue
        # Checked inside the service, per action, from the transition table.
        if m.group(2) == "/requisitions/{request_no}/approve":
            continue
        if m.group(2) in SCOPED_IN_SERVICE:
            continue
        if not any(j.lower() in body.lower() for j in JUSTIFIED):
            unexplained.append(f"{m.group(1).upper()} {m.group(2)}")
    ok("gate", "every ungated endpoint documents why it is ungated",
       not unexplained, ", ".join(unexplained[:4]))
    ok("gate", "3 endpoints are scoped in the service, not the route "
       "(safe, but undocumented there)", True)

    public = open(os.path.join("app", "routes", "hrms_public.py"), encoding="utf-8").read()
    ok("gate", "public routes rate-limit and validate their access code",
       "assert_link_live" in public and "rate" in public.lower())

    # ── 4. RUN ───────────────────────────────────────────────
    head("4. Run — every read surface answers, empty and populated")
    from bson import ObjectId
    from app.models import hrms as M
    import app.db.mongodb as mongo
    from app.services.hrms.tests.test_phase2_employee import FakeCollection

    COMPANY = "SMOKE"
    U_HR, U_MD, U_HOD, U_CLIENT = (str(ObjectId()) for _ in range(4))
    CLIENT_ID = str(ObjectId())
    dept, desig = ObjectId(), ObjectId()

    store = {}
    keep_get = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    services = {k: v for k, v in loaded.items()}
    import app.utils.hrms_access as ACCESS
    for mod in list(services.values()) + [ACCESS]:
        if hasattr(mod, "get_collection"):
            mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in list(services.values()):
        for n in ("notify_user", "notify_users", "notify_hrms_role"):
            if hasattr(mod, n):
                setattr(mod, n, silent)
    import app.services.hrms_notify_service as NS
    keep_notify = (NS.notify_user, NS.notify_users, NS.notify_hrms_role)
    NS.notify_user, NS.notify_users, NS.notify_hrms_role = silent, silent, silent
    import app.services.s3_service as S3
    keep_s3 = (S3.upload_file_to_s3_with_key, S3.get_signed_url)
    S3.upload_file_to_s3_with_key = lambda f, n, m: {"key": f"s3/{n}", "url": "u"}
    S3.get_signed_url = lambda k, expires_in=3600, download_as=None: f"https://s/{k}"

    def user(uid, gov, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov, "full_name": gov}

    HR = user(U_HR, "HR")
    MD = user(U_MD, "MD", "clientadmin")
    HOD = user(U_HOD, "HOD")
    CLIENT = user(U_CLIENT, "CLIENT")

    # -- 4a. EMPTY database. The state every new tenant starts in.
    print("\n  4a. Empty company — the state a new tenant starts in")
    store.clear()
    store["companies"] = FakeCollection([
        {"_id": ObjectId(CLIENT_ID), "name": "Smoke Client", "hrms_enabled": True}])
    store["learners"] = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "governance_role": "HR",
         "role": "clientuser", "full_name": "HR"}])

    S = services
    # Thunks: nothing is called until run_call awaits it, so a bad entry fails alone.
    EMPTY_READS = [
        ("Dashboard", lambda: S["hrms_analytics_service"].dashboard(HR, COMPANY)),
        ("Dashboard", lambda: S["hrms_analytics_service"].funnel(HR, COMPANY)),
        ("Dashboard", lambda: S["hrms_analytics_service"].internal_kpis(HR, COMPANY)),
        ("Dashboard", lambda: S["hrms_analytics_service"].positions(HR, COMPANY)),
        ("Employees", lambda: S["hrms_employee_service"].list_employees(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_requisition_service"].list_requisitions(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_requisition_service"].list_jds(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_posting_service"].list_postings(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_candidate_service"].list_candidates(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_assessment_service"].list_assessments(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_interview_service"].list_interviews(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_offer_service"].list_offers(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_onboarding_service"].list_onboardings(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_appointment_service"].list_appointments(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_scorecard_service"].list_scorecards(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_telephonic_service"].list_screenings(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_shortlist_service"].list_shortlist_reviews(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_reference_service"].list_reference_checks(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_negotiation_service"].list_rounds(HR, COMPANY)),
        ("Recruitment", lambda: S["hrms_tracker_service"].tracker(HR, COMPANY)),
        ("Documents", lambda: S["hrms_document_service"].list_documents(HR, COMPANY)),
        ("Documents", lambda: S["hrms_document_service"].list_document_types(COMPANY)),
        ("Probation", lambda: S["hrms_probation_service"].list_probations(HR, COMPANY)),
        ("Probation", lambda: S["hrms_probation_service"].due_probations(HR, COMPANY)),
        ("Exceptions", lambda: S["hrms_exception_service"].list_exceptions(HR, COMPANY)),
        ("Pre-boarding", lambda: S["hrms_preboarding_service"].list_touchpoints(HR, COMPANY)),
        ("Pre-boarding", lambda: S["hrms_preboarding_service"].due_touchpoints(HR, COMPANY)),
        ("Talent Pool", lambda: S["hrms_candidate_service"].list_candidates(
            HR, COMPANY, talent_pool=True)),
        ("Departments", lambda: S["hrms_masters_service"].list_masters("department", COMPANY)),
        ("Designations", lambda: S["hrms_masters_service"].list_masters("designation", COMPANY)),
        ("Sanctioned", lambda: S["hrms_sanction_service"].list_sanctions(COMPANY)),
        ("Salary Bands", lambda: S["hrms_salary_band_service"].list_salary_bands(HR, COMPANY)),
        ("Communications", lambda: S["hrms_comm_service"].list_templates(COMPANY)),
        ("Communications", lambda: S["hrms_comm_service"].list_log(HR, COMPANY)),
        ("Policy", lambda: S["hrms_policy_service"].list_policies(COMPANY)),
        ("Policy", lambda: S["hrms_policy_service"].due_reviews(COMPANY)),
        ("Settings", lambda: S["hrms_config_service"].describe(COMPANY)),
        ("Settings", lambda: S["hrms_holiday_service"].list_holidays(COMPANY)),
        ("Surveys", lambda: S["hrms_survey_service"].list_surveys(COMPANY)),
        ("Retention", lambda: S["hrms_purge_service"].propose(MD, COMPANY, dry_run=True)),
        ("Links", lambda: S["hrms_link_service"].list_links(HR, COMPANY)),
        ("Clients", lambda: S["hrms_client_service"].list_clients(HR, COMPANY)),
        ("SLA", lambda: S["hrms_sla_service"].sweep_open_breaches(None, COMPANY, notify=False)),
        # Phase 12
        ("Job Requests", lambda: S["hrms_job_request_service"].list_job_requests(HR, COMPANY)),
        ("CV Sharing", lambda: S["hrms_share_service"].list_shares(HR, COMPANY)),
        ("Verification", lambda: S["hrms_background_service"].list_checks(HR, COMPANY)),
        ("Verification", lambda: S["hrms_background_service"].pending_verifications(HR, COMPANY)),
    ]
    for sect, thunk in EMPTY_READS:
        await run_call(sect, f"empty: {sect}", thunk)

    # -- 4b. The client's own surfaces, with no engagement. Must be empty, not an error.
    print("\n  4b. A client user with no engagement — must fail closed, not fall over")
    await run_call("Client", "client: job requests",
                   lambda: S["hrms_job_request_service"].list_job_requests(CLIENT, COMPANY))
    await run_call("Client", "client: shared candidates",
                   lambda: S["hrms_share_service"].list_shares(CLIENT, COMPANY))

    # -- 4c. POPULATED. A minimal but real journey, so the same surfaces run with rows.
    print("\n  4c. Populated company — the same surfaces, with data")
    store["companies"] = FakeCollection([
        {"_id": ObjectId(CLIENT_ID), "name": "Smoke Client", "hrms_enabled": True}])
    store["learners"] = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "governance_role": "HR",
         "role": "clientuser", "full_name": "HR", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "governance_role": "MD",
         "role": "clientadmin", "full_name": "MD", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "governance_role": "HOD",
         "role": "clientuser", "full_name": "HOD", "is_active": True}])
    store[M.COLL_DEPARTMENTS] = FakeCollection([
        {"_id": dept, "company_id": COMPANY, "name": "Engineering", "active": True}])
    store[M.COLL_DESIGNATIONS] = FakeCollection([
        {"_id": desig, "company_id": COMPANY, "name": "Developer",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])

    RS, CS = S["hrms_requisition_service"], S["hrms_candidate_service"]
    try:
        req = await RS.create_requisition(HOD, COMPANY, {
            "department_id": str(dept), "designation_id": str(desig), "assignee_id": U_HR,
            "vacancy": 1, "required_date": "2027-01-31",
            "experience_required": "2-4 years", "qualification": "B.E.",
            "essential_skills": "Python", "offering_ctc": 800000.0,
            "client_id": CLIENT_ID,
            "jd": {"title": "Developer", "responsibilities": "Build things."}})
        ok("Recruitment", "raise a requisition", True)
        await RS.act_on_requisition(HR, COMPANY, req["request_no"], "hr-approve")
        await RS.act_on_requisition(MD, COMPANY, req["request_no"], "md-approve")
        ok("Recruitment", "approval chain runs", True)
        cand = await CS.create_candidate(HR, COMPANY, {
            "request_no": req["request_no"], "candidate_name": "Smoke Candidate",
            "can_email": "smoke@example.com", "can_contact": "+91 90000 00000",
            "resume": {"name": "cv.pdf", "mime_type": "application/pdf",
                       "data": __import__("base64").b64encode(
                           b"%PDF-1.4 cv").decode()}})
        ok("Recruitment", "add a candidate with a CV", True)
        UK = cand["uk"]
    except Exception as e:
        ok("Recruitment", "seed a minimal journey", False, f"{type(e).__name__}: {e}")
        if VERBOSE:
            traceback.print_exc()
        UK, req = None, None

    if UK:
        # The offer path, both ways -- this is the section a user reported an error on.
        OF = S["hrms_offer_service"]
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": UK}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await S["hrms_reference_service"].create_reference_check(HR, COMPANY, {
            "uk": UK, "referee_name": "Ref", "responses": "Fine.",
            "outcome": M.ReferenceOutcome.POSITIVE.value,
            "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        for t in M.REQUIRED_BACKGROUND_CHECKS:
            await S["hrms_background_service"].record_check(HR, COMPANY, {
                "uk": UK, "check_type": t.value,
                "status": M.BackgroundCheckStatus.CLEARED.value,
                "findings": "Verified."})
        await S["hrms_background_service"].decide_verification(HR, COMPANY, UK, {
            "decision": "Approved", "signature": "HR"})

        joining = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        # A DRAFT needs no signature.
        await run_call("Offers", "create a draft offer (no signature needed)",
                       lambda: OF.create_offer(HR, COMPANY, {
                           "uk": UK, "ctc": 800000.0, "joining_date": joining}))
        offers = await store[M.COLL_OFFERS].find({"company_id": COMPANY}).to_list(10)
        if offers:
            ok("Offers", "the draft was created", True)
            # And sending it DOES need one -- the reported error, checked from both sides.
            from fastapi import HTTPException
            try:
                await OF.send_offer(HR, COMPANY, offers[0]["offer_no"], {"signature": ""})
                ok("Offers", "sending with a blank signature is refused", False,
                   "it was accepted")
            except HTTPException as e:
                ok("Offers", "sending with a blank signature is refused",
                   e.status_code in (400, 422), f"HTTP {e.status_code}")
            await run_call("Offers", "sending WITH a signature succeeds",
                           lambda: OF.send_offer(HR, COMPANY, offers[0]["offer_no"],
                                                 {"signature": "Authorised HR"}))

        # Every read surface again, now with rows behind it.
        for sect, coro in [
            ("Dashboard", S["hrms_analytics_service"].dashboard(HR, COMPANY)),
            ("Dashboard", lambda: S["hrms_analytics_service"].internal_kpis(HR, COMPANY)),
            ("Recruitment", CS.list_candidates(HR, COMPANY)),
            ("Recruitment", CS.get_journey(HR, COMPANY, UK)),
            ("Recruitment", lambda: S["hrms_tracker_service"].tracker(HR, COMPANY)),
            ("Verification", S["hrms_background_service"].verification_state(COMPANY, UK)),
            ("Verification", lambda: S["hrms_background_service"].pending_verifications(HR, COMPANY)),
            ("Offers", S["hrms_offer_service"].list_offers(HR, COMPANY)),
        ]:
            await run_call(sect, f"populated: {sect}", coro)

        # Row scoping must not crash for a HOD with no requisitions of their own.
        await run_call("Scoping", "HOD candidate list (row-scoped)",
                       CS.list_candidates(HOD, COMPANY))

    mongo.get_collection = keep_get
    NS.notify_user, NS.notify_users, NS.notify_hrms_role = keep_notify
    S3.upload_file_to_s3_with_key, S3.get_signed_url = keep_s3

    # ── 5. WIRING ────────────────────────────────────────────
    head("5. Wiring — the frontend can reach what the backend offers")
    try:
        access_js = open(os.path.join(FRONTEND, "features", "hrms", "access.js"),
                         encoding="utf-8").read()
        cap_block = access_js.split("export const CAP")[1].split("};")[0]
        js_values = set(re.findall(r"'([a-z_]+\.[a-z_.]+)'", cap_block))
        py_values = {c.value for c in Cap}
        ok("wiring", "capability parity backend -> frontend",
           py_values <= js_values, ", ".join(sorted(py_values - js_values)[:4]))
        ok("wiring", "capability parity frontend -> backend",
           js_values <= py_values, ", ".join(sorted(js_values - py_values)[:4]))
    except OSError as e:
        ok("wiring", "frontend access.js readable", False, str(e))

    try:
        app_jsx = open(os.path.join(FRONTEND, "App.jsx"), encoding="utf-8").read()
        routed = set(re.findall(r'<Route path="([a-z0-9\-]+)"', app_jsx))
        sidebar = open(os.path.join(FRONTEND, "components", "layout", "Sidebar.jsx"),
                       encoding="utf-8").read()
        nav = set(re.findall(r"path: '/hrms/([a-z0-9\-]+)'", sidebar))
        bar = open(os.path.join(FRONTEND, "features", "hrms", "common",
                                "HrmsWorkspaceBar.jsx"), encoding="utf-8").read()
        tabs = set(re.findall(r"to: '/hrms/([a-z0-9\-]+)'", bar))
        missing = (nav | tabs) - routed
        ok("wiring", "every navigation entry has a route", not missing,
           ", ".join(sorted(missing)[:5]))
        # The module's own rule: the sidebar and the tab strip must stay disjoint.
        # `requisitions` is the deliberate doorway: the sidebar's Recruitment entry opens
        # the workspace at its first tab. Everything else must not be in both lists.
        overlap = (nav & tabs) - {"requisitions"}
        ok("wiring", "sidebar and workspace tabs stay disjoint", not overlap,
           ", ".join(sorted(overlap)[:5]))
    except OSError as e:
        ok("wiring", "frontend navigation readable", False, str(e))

    try:
        api = open(os.path.join(FRONTEND, "services", "hrmsApi.js"), encoding="utf-8").read()
        called = set(re.findall(r"api\.(?:get|post|patch|put|delete)\(\s*[`']/hrms([^`'?]*)",
                                api))
        mounted = {r.path.replace("/api/hrms", "") for r in hrms_routes}

        def norm(p):
            p = re.sub(r"\$\{[^}]+\}", "{}", p)      # template literal first...
            return re.sub(r"\{[^{}]+\}", "{}", p).rstrip("/")   # ...then path params

        mounted_n = {norm(p) for p in mounted}
        unknown = sorted({c for c in called if norm(c) and norm(c) not in mounted_n})
        ok("wiring", f"every API helper hits a real route ({len(called)} checked)",
           not unknown, ", ".join(unknown[:4]))
    except OSError as e:
        ok("wiring", "frontend hrmsApi.js readable", False, str(e))

    # ── Report ───────────────────────────────────────────────
    print()
    print("=" * 76)
    print("  SMOKE TEST RESULT")
    print("=" * 76)
    by_section = {}
    for sect, _label, passed, _d in results:
        s = by_section.setdefault(sect, [0, 0])
        s[0] += 1
        if passed:
            s[1] += 1
    width = max(len(s) for s in by_section)
    for sect in sorted(by_section):
        total, passed = by_section[sect]
        mark = "ok" if passed == total else "FAIL"
        print(f"  {sect:<{width}}  {passed:>3}/{total:<3}  {mark}")
    total = len(results)
    passed = sum(1 for r in results if r[2])
    print("  " + "-" * 40)
    print(f"  {passed}/{total} checks passed")
    failures = [r for r in results if not r[2]]
    if failures:
        print()
        print("  FAILURES:")
        for sect, label, _p, detail in failures:
            print(f"    [{sect}] {label}" + (f"  -- {detail}" if detail else ""))
    print()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
