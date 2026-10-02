"""Phase 6 integration harness -- assessments over HTTP, including the public surface.

Exercises capability gating, route ordering, validation, tenant pinning, and the security
properties of the second public endpoint (128-bit access codes, no auth, no oracle).

Run:  python -m app.services.hrms.tests.test_phase6_integration   (from backend/)
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
GOOD_CODE = "AbCdEfGhIjKlMnOpQrStUv"          # 22 chars, matches the access-code pattern


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
        seen["kw"] = kw
        return {"assessments": [], "total": 0, "stats": {}}

    async def fake_send(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"assessment_no": "ASM-2026-001"}

    async def fake_review(actor, company_id, no, payload):
        seen["review"] = (company_id, no, payload)
        return {"assessment_no": no, "status": "Reviewed"}

    async def fake_assessable(actor, company_id):
        seen["company_id"] = company_id
        return []

    async def fake_public_get(code):
        seen["public_get"] = code
        from fastapi import HTTPException
        if code != GOOD_CODE:
            from app.utils.hrms_public_guard import INVALID_LINK
            raise HTTPException(status_code=404, detail=INVALID_LINK)
        return {"ok": True, "already_done": False, "title": "Excel task",
                "assessment_no": "ASM-2026-001"}

    async def fake_public_submit(code, payload):
        seen["public_submit"] = (code, payload)
        return {"ok": True, "message": "Your assessment has been submitted."}

    async def fake_limit(scope, identifier):
        limited.append((scope, identifier))

    R.assessments.list_assessments = fake_list
    R.assessments.send_assessment = fake_send
    R.assessments.review_assessment = fake_review
    R.assessments.assessable_candidates = fake_assessable
    PUB.assessments.get_public_assessment = fake_public_get
    PUB.assessments.submit_public_assessment = fake_public_submit
    PUB.enforce_rate_limit = fake_limit

    SUPER = {"_id": "sa", "role": "superadmin", "_source_collection": "staff"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}
    HR = {"_id": "hr", "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR"}
    HOD = {"_id": "hod", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": "emp", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}

    current = {"user": SUPER}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    def as_user(u):
        current["user"] = u

    client = TestClient(app)
    SEND = {"uk": "CAN-001", "title": "Excel task", "max_score": 100}

    try:
        section("Capabilities via /health")
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        for c in ("assessment.read", "assessment.send", "assessment.review"):
            check(f"HR has {c}", c in caps)
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has assessment.review (they are the manager slot)",
              "assessment.review" in caps)
        check("HOD lacks assessment.send", "assessment.send" not in caps)
        as_user(INTERNAL)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("INTERNAL can send", "assessment.send" in caps)
        check("INTERNAL cannot review (a hiring decision)", "assessment.review" not in caps)
        as_user(EMP)
        check("employee has no assessment capability",
              not any(c.startswith("assessment.")
                      for c in client.get("/api/hrms/health").json()["capabilities"]))

        section("Capability gating per endpoint")
        as_user(EMP)
        check("employee -> list 403", client.get("/api/hrms/assessments").status_code == 403)
        check("employee -> send 403",
              client.post("/api/hrms/assessments", json=SEND).status_code == 403)
        check("employee -> review 403",
              client.post("/api/hrms/assessments/ASM-1/review",
                          json={"decision": "Pass"}).status_code == 403)

        as_user(HOD)
        check("HOD -> list 200", client.get("/api/hrms/assessments").status_code == 200)
        check("HOD -> review 200",
              client.post("/api/hrms/assessments/ASM-1/review",
                          json={"decision": "Pass"}).status_code == 200)
        check("HOD -> send 403",
              client.post("/api/hrms/assessments", json=SEND).status_code == 403)
        check("HOD -> assessable picker 403",
              client.get("/api/hrms/assessments/assessable").status_code == 403)

        as_user(INTERNAL)
        check("INTERNAL -> send 201",
              client.post("/api/hrms/assessments", json=SEND,
                          params={"company_id": COMPANY}).status_code == 201)
        check("INTERNAL -> review 403",
              client.post("/api/hrms/assessments/ASM-1/review", json={"decision": "Pass"},
                          params={"company_id": COMPANY}).status_code == 403)

        section("Route ordering -- /assessable must beat /{assessment_no}")
        as_user(HR)
        seen.pop("company_id", None)
        r = client.get("/api/hrms/assessments/assessable")
        check("/assessments/assessable reaches the picker", r.status_code == 200)
        check("picker returns its own shape", "candidates" in r.json())

        section("Validation")
        check("send without uk -> 422",
              client.post("/api/hrms/assessments", json={"title": "x"}).status_code == 422)
        check("send without title -> 422",
              client.post("/api/hrms/assessments", json={"uk": "CAN-1"}).status_code == 422)
        check("review without a decision -> 422",
              client.post("/api/hrms/assessments/ASM-1/review", json={}).status_code == 422)
        check("an invalid decision is rejected by the schema -> 422",
              client.post("/api/hrms/assessments/ASM-1/review",
                          json={"decision": "Maybe"}).status_code == 422)
        check("limit bounds enforced",
              client.get("/api/hrms/assessments", params={"limit": 501}).status_code == 422)

        section("Forged fields dropped by the schema")
        seen.pop("payload", None)
        client.post("/api/hrms/assessments",
                    json={**SEND, "status": "Reviewed", "hr_decision": "Pass",
                          "access_code": "mine", "company_id": "C-EVIL"})
        for forged in ("status", "hr_decision", "access_code", "company_id"):
            check(f"forged '{forged}' dropped", forged not in seen["payload"])

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/assessments", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/assessments/ASM-1/review", json={"decision": "Pass"},
                    params={"company_id": OTHER})
        check("client cannot review in another tenant", seen["review"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/assessments", params={"company_id": OTHER})
        check("internal may target a company", seen["company_id"] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/assessments").status_code == 400)

        # =================================================================
        section("PUBLIC assess surface -- no authentication")
        # =================================================================
        app.dependency_overrides.pop(get_current_user, None)
        r = client.get(f"/api/hrms/public/assess/{GOOD_CODE}")
        check("GET with no token -> 200 (never 401)", r.status_code == 200)
        r = client.post(f"/api/hrms/public/assess/{GOOD_CODE}", json={"response": "hi"})
        check("POST with no token -> 200 (never 401)", r.status_code == 200)
        check("a garbage bearer token does not break it",
              client.get(f"/api/hrms/public/assess/{GOOD_CODE}",
                         headers={"Authorization": "Bearer nonsense"}).status_code == 200)

        section("PUBLIC assess -- code validated before any query")
        seen.pop("public_get", None)
        injections = ['{"$ne":null}', "../../etc/passwd", "short", "a" * 65,
                      "has spaces here 1234567", "code/with/slashes12345",
                      "<script>alert(1)</script>", "%2e%2e%2f"]
        blocked = 0
        for payload in injections:
            if client.get(f"/api/hrms/public/assess/{payload}").status_code in (404, 400, 422):
                blocked += 1
        check(f"all {len(injections)} malformed codes refused (got {blocked})",
              blocked == len(injections))
        check("no malformed code reached the service", "public_get" not in seen)

        section("PUBLIC assess -- case is PRESERVED (entropy matters)")
        seen.pop("public_get", None)
        client.get(f"/api/hrms/public/assess/{GOOD_CODE.lower()}")
        check("a lower-cased code is NOT folded to match (unlike posting codes)",
              seen.get("public_get") == GOOD_CODE.lower())

        section("PUBLIC assess -- no existence oracle")
        missing = client.get("/api/hrms/public/assess/" + "Z" * 22)
        malformed = client.get("/api/hrms/public/assess/short")
        check("unknown code -> 404", missing.status_code == 404)
        check("malformed code -> 404", malformed.status_code == 404)
        check("both return the IDENTICAL message",
              missing.json()["detail"] == malformed.json()["detail"])

        section("PUBLIC assess -- rate limited before work")
        limited.clear()
        client.get(f"/api/hrms/public/assess/{GOOD_CODE}")
        check("GET limited on assess-view", ("assess-view",) == tuple(s for s, _ in limited))
        limited.clear()
        client.post(f"/api/hrms/public/assess/{GOOD_CODE}", json={"response": "x"})
        check("POST limited on assess-submit",
              ("assess-submit",) == tuple(s for s, _ in limited))
        limited.clear()
        client.get("/api/hrms/public/assess/bad")
        check("a malformed code is rejected before the limiter is consulted", limited == [])

        section("PUBLIC assess -- response exposes only what a candidate needs")
        body = client.get(f"/api/hrms/public/assess/{GOOD_CODE}").json()
        for leak in ("company_id", "uk", "manager_id", "hr_decision", "manager_decision",
                     "access_code", "created_by", "request_no", "score"):
            check(f"public view omits {leak}", leak not in body)

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
        for path in ("/api/hrms/health", "/api/hrms/assessments", "/api/hrms/candidates",
                     "/api/hrms/postings", "/api/hrms/employees"):
            check(f"{path} -> 401 without a token",
                  client.get(path).status_code == 401)
        check("public apply route still anonymous",
              client.get("/api/hrms/public/apply/ZZ-ZZZZZZ").status_code not in (401, 403))
        check("API root still 200", client.get("/").status_code == 200)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            check(f"{path} still protected", client.get(path).status_code == 401)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
