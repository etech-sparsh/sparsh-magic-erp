"""Phase 9 integration harness -- onboarding over HTTP, plus the FOURTH public surface.

Also carries the regression for Finding #1: a real route hands its service
`body.model_dump()`, which turns nested `UploadIn` models into plain dicts. Every public
upload path is exercised through HTTP here so that shape can never silently break again.

Run:  python -m app.services.hrms.tests.test_phase9_integration   (from backend/)
"""
from __future__ import annotations

from fastapi.testclient import TestClient

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


COMPANY = "C1"
OTHER = "C2"
GOOD_CODE = "AbCdEfGhIjKlMnOpQrStUv"
PDF = {"name": "pan.pdf", "mime_type": "application/pdf", "data": "aGVsbG8="}


def main() -> None:
    import main as app_main
    from app.controllers.auth_controller import get_current_user
    from app.utils import hrms_access as A
    import app.routes.hrms as R
    import app.routes.hrms_public as PUB

    app = app_main.app

    async def fake_enabled(company_id):
        return company_id in (COMPANY, OTHER)

    A.is_hrms_enabled = fake_enabled

    seen = {}
    limited = []

    async def fake_list(actor, company_id, **kw):
        seen["company_id"] = company_id
        seen["list_kw"] = kw
        return []

    async def fake_onboardable(actor, company_id):
        seen["company_id"] = company_id
        return []

    async def fake_get(actor, company_id, no):
        seen["get"] = (company_id, no)
        return {"onb_no": no, "status": "Pre-Onboarding"}

    async def fake_start(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"onb_no": "ONB-2026-001"}

    async def fake_details(actor, company_id, no, payload):
        seen["details"] = (company_id, no, payload)
        return {"onb_no": no, **payload}

    async def fake_bg(actor, company_id, no, payload):
        seen["bg"] = (company_id, no, payload)
        return {"onb_no": no, "bg_verification": payload.get("bg_verification")}

    async def fake_verify(actor, company_id, no):
        seen["verify"] = (company_id, no)
        return {"onb_no": no, "pre_status": "Verified"}

    async def fake_docs(actor, company_id, no, payload):
        seen["docs"] = (company_id, no, payload)
        return {"onb_no": no, "documents": payload.get("documents") or []}

    async def fake_checklist(actor, company_id, no, payload):
        seen["checklist"] = (company_id, no, payload)
        return {"onb_no": no}

    async def fake_generate(actor, company_id, no):
        seen["generate"] = (company_id, no)
        return {"onb_no": no, "employee_id": "EMP-2026-001"}

    async def fake_link(actor, company_id, code, user_id):
        seen["link"] = (company_id, code, user_id)
        return {"employee_code": code, "user_id": user_id}

    async def fake_public_get(code):
        seen["public_get"] = code
        from fastapi import HTTPException
        from app.utils.hrms_public_guard import INVALID_LINK
        if code != GOOD_CODE:
            raise HTTPException(status_code=404, detail=INVALID_LINK)
        return {"ok": True, "already_submitted": False, "candidate_name": "Asha",
                "designation": "Analyst", "joining_date": "2099-01-01",
                "max_documents": 15, "max_references": 5}

    async def fake_public_submit(code, payload):
        seen["public_submit"] = (code, payload)
        # Decode exactly as the service does, on the shape the ROUTE actually delivers.
        from app.utils.hrms_public_guard import decode_upload
        seen["decoded"] = [decode_upload(u) for u in (payload.get("documents") or [])]
        return {"ok": True, "message": "Recorded."}

    async def fake_limit(scope, identifier):
        limited.append((scope, identifier))

    R.onboarding.list_onboardings = fake_list
    R.onboarding.onboardable_candidates = fake_onboardable
    R.onboarding.get_onboarding = fake_get
    R.onboarding.start_onboarding = fake_start
    R.onboarding.update_details = fake_details
    R.onboarding.update_bg = fake_bg
    R.onboarding.verify_documents = fake_verify
    R.onboarding.add_documents = fake_docs
    R.onboarding.set_checklist = fake_checklist
    R.onboarding.generate_employee_id = fake_generate
    R.employees.link_user = fake_link
    PUB.onboarding.get_public_onboarding = fake_public_get
    PUB.onboarding.submit_public_onboarding = fake_public_submit
    PUB.enforce_rate_limit = fake_limit

    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}
    MD = {"_id": "md", "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY}
    HR = {"_id": "hr", "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR"}
    HOD = {"_id": "hod", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": "emp", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}

    current = {"user": HR}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    def as_user(u):
        current["user"] = u

    client = TestClient(app)
    START = {"uk": "CAN-001", "joining_date": "2099-01-01"}

    try:
        section("Capabilities via /health")
        for label, user, expect in (("HR", HR, True), ("MD", MD, True),
                                    ("INTERNAL", INTERNAL, True)):
            as_user(user)
            caps = client.get("/api/hrms/health").json()["capabilities"]
            check(f"{label} has all three onboarding capabilities",
                  all(c in caps for c in ("onboarding.read", "onboarding.write",
                                          "onboarding.generate_id")) is expect)
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has onboarding.read", "onboarding.read" in caps)
        check("HOD lacks onboarding.write", "onboarding.write" not in caps)
        check("HOD lacks onboarding.generate_id", "onboarding.generate_id" not in caps)
        as_user(EMP)
        check("employee has no onboarding capability",
              not any(c.startswith("onboarding.")
                      for c in client.get("/api/hrms/health").json()["capabilities"]))

        section("Capability gating per endpoint")
        as_user(EMP)
        check("employee -> list 403",
              client.get("/api/hrms/onboarding").status_code == 403)
        check("employee -> start 403",
              client.post("/api/hrms/onboarding", json=START).status_code == 403)
        as_user(HOD)
        check("HOD -> list 200", client.get("/api/hrms/onboarding").status_code == 200)
        check("HOD -> detail 200",
              client.get("/api/hrms/onboarding/ONB-1").status_code == 200)
        check("HOD -> start 403",
              client.post("/api/hrms/onboarding", json=START).status_code == 403)
        check("HOD -> checklist 403",
              client.post("/api/hrms/onboarding/ONB-1/checklist",
                          json={"key": "induction", "done": True}).status_code == 403)
        check("HOD -> verify 403",
              client.post("/api/hrms/onboarding/ONB-1/verify").status_code == 403)
        check("HOD -> generate-id 403",
              client.post("/api/hrms/onboarding/ONB-1/generate-id").status_code == 403)
        check("HOD -> onboardable picker 403",
              client.get("/api/hrms/onboarding/onboardable").status_code == 403)
        as_user(HR)
        check("HR -> start 201",
              client.post("/api/hrms/onboarding", json=START).status_code == 201)
        check("HR -> verify 200",
              client.post("/api/hrms/onboarding/ONB-1/verify").status_code == 200)
        check("HR -> generate-id 200",
              client.post("/api/hrms/onboarding/ONB-1/generate-id").status_code == 200)

        section("generate_id is a SEPARATE gate from write")
        # Someone may run an onboarding without being allowed to create staff records.
        import app.models.hrms as M
        original_caps = dict(M.ROLE_CAPABILITIES)
        M.ROLE_CAPABILITIES[M.HrmsRole.HR] = (
            set(M.ROLE_CAPABILITIES[M.HrmsRole.HR]) - {M.Cap.ONBOARDING_GENERATE_ID})
        try:
            as_user(HR)
            check("write-only user -> checklist still 200",
                  client.post("/api/hrms/onboarding/ONB-1/checklist",
                              json={"key": "induction", "done": True}).status_code == 200)
            check("write-only user -> generate-id 403",
                  client.post("/api/hrms/onboarding/ONB-1/generate-id").status_code == 403)
        finally:
            M.ROLE_CAPABILITIES.clear()
            M.ROLE_CAPABILITIES.update(original_caps)

        section("Linking an account is gated on employee.write")
        as_user(HOD)
        check("HOD -> link 403",
              client.post("/api/hrms/employees/link/EMP-1",
                          json={"user_id": "u1"}).status_code == 403)
        as_user(HR)
        r = client.post("/api/hrms/employees/link/EMP-1", json={"user_id": "u1"})
        check("HR -> link 200", r.status_code == 200)
        check("the employee code reaches the service", seen["link"][1] == "EMP-1")

        section("Route ordering -- /onboardable must beat /{onb_no}")
        as_user(HR)
        seen.pop("get", None)
        r = client.get("/api/hrms/onboarding/onboardable")
        check("/onboarding/onboardable reaches the picker", r.status_code == 200)
        check("it did NOT fall through to the detail route", "get" not in seen)

        section("Validation")
        check("start without uk -> 422",
              client.post("/api/hrms/onboarding", json={}).status_code == 422)
        check("checklist without a key -> 422",
              client.post("/api/hrms/onboarding/ONB-1/checklist",
                          json={"done": True}).status_code == 422)
        check("checklist without done -> 422",
              client.post("/api/hrms/onboarding/ONB-1/checklist",
                          json={"key": "induction"}).status_code == 422)
        check("bg without an outcome -> 422",
              client.post("/api/hrms/onboarding/ONB-1/bg", json={}).status_code == 422)
        check("an unknown bg outcome -> 422",
              client.post("/api/hrms/onboarding/ONB-1/bg",
                          json={"bg_verification": "Vibes"}).status_code == 422)
        check("a known bg outcome -> 200",
              client.post("/api/hrms/onboarding/ONB-1/bg",
                          json={"bg_verification": "Cleared"}).status_code == 200)
        check("link without a user_id -> 422",
              client.post("/api/hrms/employees/link/EMP-1", json={}).status_code == 422)

        section("Forged fields dropped by the schema")
        seen.pop("payload", None)
        client.post("/api/hrms/onboarding",
                    json={**START, "status": "Completed", "access_code": "mine",
                          "employee_id": "EMP-EVIL", "onb_no": "ONB-EVIL",
                          "checklist": [], "company_id": "C-EVIL",
                          "pre_status": "Verified"})
        for forged in ("status", "access_code", "employee_id", "onb_no", "checklist",
                       "company_id", "pre_status"):
            check(f"forged '{forged}' dropped at the door", forged not in seen["payload"])
        seen.pop("details", None)
        client.patch("/api/hrms/onboarding/ONB-1",
                     json={"joining_date": "2099-02-02", "employee_id": "EMP-EVIL",
                           "status": "Completed", "submission": {"pan": "X"}})
        for forged in ("employee_id", "status", "submission"):
            check(f"'{forged}' cannot be patched", forged not in seen["details"][2])
        check("the legitimate field survives", "joining_date" in seen["details"][2])

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/onboarding", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/onboarding/ONB-1/generate-id", params={"company_id": OTHER})
        check("client cannot mint an employee in another tenant",
              seen["generate"][0] == COMPANY)
        client.post("/api/hrms/employees/link/EMP-1", json={"user_id": "u1"},
                    params={"company_id": OTHER})
        check("client cannot link in another tenant", seen["link"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/onboarding", params={"company_id": OTHER})
        check("internal may target a company", seen["company_id"] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/onboarding").status_code == 400)

        # =================================================================
        section("PUBLIC pre-onboarding -- the fourth anonymous surface")
        # =================================================================
        app.dependency_overrides.pop(get_current_user, None)
        check("GET with no token -> 200",
              client.get(f"/api/hrms/public/onboard/{GOOD_CODE}").status_code == 200)
        check("POST with no token -> 200",
              client.post(f"/api/hrms/public/onboard/{GOOD_CODE}",
                          json={"pan": "ABCDE1234F"}).status_code == 200)
        check("a garbage bearer token does not break it",
              client.get(f"/api/hrms/public/onboard/{GOOD_CODE}",
                         headers={"Authorization": "Bearer nope"}).status_code == 200)

        section("PUBLIC pre-onboarding -- code validated before any query")
        seen.pop("public_get", None)
        injections = ['{"$ne":null}', "../../etc/passwd", "short", "a" * 65,
                      "has spaces here 1234567", "<script>alert(1)</script>"]
        blocked = sum(1 for p in injections
                      if client.get(f"/api/hrms/public/onboard/{p}").status_code
                      in (404, 400, 422))
        check(f"all {len(injections)} malformed codes refused (got {blocked})",
              blocked == len(injections))
        check("no malformed code reached the service", "public_get" not in seen)

        section("PUBLIC pre-onboarding -- no existence oracle")
        missing = client.get("/api/hrms/public/onboard/" + "Z" * 22)
        malformed = client.get("/api/hrms/public/onboard/short")
        check("unknown and malformed share a status",
              missing.status_code == malformed.status_code == 404)
        check("and a byte-identical message",
              missing.json()["detail"] == malformed.json()["detail"])

        section("PUBLIC pre-onboarding -- rate limited before any work")
        limited.clear()
        client.get(f"/api/hrms/public/onboard/{GOOD_CODE}")
        check("view is limited on its own scope", ("onboard-view", "testclient") in limited)
        limited.clear()
        client.post(f"/api/hrms/public/onboard/{GOOD_CODE}", json={"pan": "ABCDE1234F"})
        check("submit is limited on its own, tighter scope",
              ("onboard-submit", "testclient") in limited)
        limited.clear()
        client.get("/api/hrms/public/onboard/bad")
        check("a malformed code is rejected BEFORE the limiter", limited == [])

        section("PUBLIC pre-onboarding -- exposes only what a new hire needs")
        body = client.get(f"/api/hrms/public/onboard/{GOOD_CODE}").json()
        for leak in ("company_id", "uk", "onb_no", "offer_no", "request_no", "access_code",
                     "checklist", "bg_verification", "employee_id", "submission",
                     "created_by", "reporting_manager_id"):
            check(f"public form omits {leak}", leak not in body)

        section("PUBLIC pre-onboarding -- forged fields dropped")
        seen.pop("public_submit", None)
        client.post(f"/api/hrms/public/onboard/{GOOD_CODE}",
                    json={"pan": "ABCDE1234F", "employee_id": "EMP-EVIL",
                          "pre_status": "Verified", "status": "Completed",
                          "checklist": [], "company_id": "C-EVIL", "uk": "CAN-EVIL"})
        payload = seen["public_submit"][1]
        for forged in ("employee_id", "pre_status", "status", "checklist", "company_id",
                       "uk"):
            check(f"forged '{forged}' dropped from a public submission",
                  forged not in payload)

        # =================================================================
        section("REGRESSION (Finding #1) -- uploads survive body.model_dump()")
        # =================================================================
        # A route hands its service `body.model_dump()`, which turns nested UploadIn models
        # into plain dicts. Reading only attributes made every real upload look like it had
        # no mime type, so the guard rejected it with 415. Asserted here through HTTP, on
        # every public surface that accepts a file.
        seen.pop("decoded", None)
        r = client.post(f"/api/hrms/public/onboard/{GOOD_CODE}",
                        json={"pan": "ABCDE1234F", "documents": [PDF]})
        check("an onboarding upload is accepted over HTTP", r.status_code == 200)
        check("the document arrived as a dict, as the route delivers it",
              isinstance(seen["public_submit"][1]["documents"][0], dict))
        check("and decoded correctly rather than 415-ing",
              seen["decoded"] == [(b"hello", "pan.pdf", "application/pdf")])

        from app.utils.hrms_public_guard import decode_upload
        from app.models.hrms import UploadIn, PublicApplicationIn, PublicAssessmentIn
        model = UploadIn(**PDF)
        check("decode_upload accepts the MODEL shape too",
              decode_upload(model) == (b"hello", "pan.pdf", "application/pdf"))
        check("both shapes give identical results",
              decode_upload(model) == decode_upload(PDF))

        # The same defect existed on Phase 4's resume and Phase 6's attachments.
        app_body = PublicApplicationIn(candidate_name="A", can_email="a@b.com",
                                       can_contact="9876543210", resume=UploadIn(**PDF))
        check("Phase 4 resume survives model_dump",
              decode_upload(app_body.model_dump()["resume"])[2] == "application/pdf")
        asm_body = PublicAssessmentIn(response="x", attachments=[UploadIn(**PDF)])
        check("Phase 6 attachment survives model_dump",
              decode_upload(asm_body.model_dump()["attachments"][0])[2] == "application/pdf")
        check("a genuinely bad mime is still refused",
              _refuses(decode_upload, {"name": "x.exe",
                                       "mime_type": "application/x-msdownload",
                                       "data": "aGk="}, 415))
        check("a missing mime is still refused",
              _refuses(decode_upload, {"name": "x", "mime_type": "", "data": "aGk="}, 415))

        section("SWEEP: still nothing else public")
        intended_prefixes = ("/api/hrms/public/", "/api/auth/")
        # Meta's WhatsApp webhook verification handshake: unauthenticated by protocol
        # (Meta GETs it before it will POST), and the POST alongside it is HMAC-signed,
        # which is the actual control. This GET only echoes back a challenge it was sent.
        intended_exact = {"/api/assistant/health", "/api/assistant/ready",
                          "/api/leadership/whatsapp-status"}
        leaked, checked = [], 0
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if "GET" not in methods or "{" in path or not path.startswith("/api/"):
                continue
            if any(path.startswith(p) for p in intended_prefixes) or path in intended_exact:
                continue
            checked += 1
            if client.get(path).status_code not in (401, 403, 404, 405, 422):
                leaked.append(path)
        check(f"swept {checked} authenticated GET routes", checked > 20)
        check("no authenticated route answers without a token", not leaked)

        section("Regression -- earlier phases intact")
        for path in ("/api/hrms/health", "/api/hrms/onboarding", "/api/hrms/offers",
                     "/api/hrms/interviews", "/api/hrms/assessments",
                     "/api/hrms/candidates", "/api/hrms/employees"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)
        for path in ("/api/hrms/public/apply/ZZ-ZZZZZZ",
                     "/api/hrms/public/assess/" + "A" * 22,
                     "/api/hrms/public/offer/" + "A" * 22,
                     "/api/hrms/public/onboard/" + "A" * 22):
            check(f"{path} still anonymous",
                  client.get(path).status_code not in (401, 403))
        check("API root still 200", client.get("/").status_code == 200)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            check(f"{path} still protected", client.get(path).status_code == 401)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


def _refuses(fn, arg, status) -> bool:
    from fastapi import HTTPException
    try:
        fn(arg)
        return False
    except HTTPException as e:
        return e.status_code == status


if __name__ == "__main__":
    main()
