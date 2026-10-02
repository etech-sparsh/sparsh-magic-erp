"""Phase 1 integration harness -- HRMS foundation, HTTP layer.

Exercises the real FastAPI routes end to end (routing, dependencies, status codes, response
shapes) using dependency overrides instead of live credentials, so it runs offline and in CI.

Complements test_phase1_foundation.py, which covers the pure logic. This one answers a
different question: does the wiring actually behave over HTTP?

Run:  python -m app.services.hrms.tests.test_phase1_integration   (from backend/)
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


SUPERADMIN = {"_id": "u1", "role": "superadmin", "_source_collection": "staff"}
STAFF_ADMIN = {"_id": "u2", "role": "admin", "_source_collection": "staff"}
CLIENT_MD = {"_id": "u4", "role": "clientadmin", "_source_collection": "learners", "company_id": "C1"}
CLIENT_HR = {"_id": "u5", "role": "clientuser", "_source_collection": "learners",
             "company_id": "C1", "governance_role": "HR"}
CLIENT_EMP = {"_id": "u7", "role": "clientuser", "_source_collection": "learners",
              "company_id": "C1", "governance_role": "IMPLEMENTOR"}
DISABLED_CO_USER = {"_id": "u9", "role": "clientuser", "_source_collection": "learners",
                    "company_id": "C_OFF", "governance_role": "HR"}


def main() -> None:
    import main as app_main
    from app.controllers.auth_controller import get_current_user
    from app.utils import hrms_access as A
    import app.services.hrms_audit_service as aud

    app = app_main.app

    # HRMS is enabled for C1 only. Avoids any DB dependency in this harness.
    async def fake_enabled(company_id):
        return company_id == "C1"

    A.is_hrms_enabled = fake_enabled

    # Audit reads return a fixed row set -- we are testing the ROUTE, not the store.
    captured = {}

    async def fake_read_audit(**kwargs):
        captured.update(kwargs)
        return [{"action": "x", "entity": "company", "company_id": kwargs.get("company_id")}]

    import app.routes.hrms as hrms_routes
    hrms_routes.read_audit = fake_read_audit

    current = {"user": SUPERADMIN}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    def as_user(u):
        current["user"] = u

    client = TestClient(app)

    try:
        # -----------------------------------------------------
        section("GET /api/hrms/health -- role resolution over HTTP")
        # -----------------------------------------------------
        as_user(SUPERADMIN)
        r = client.get("/api/hrms/health")
        check("superadmin 200", r.status_code == 200)
        body = r.json()
        check("role resolves to admin", body["role"] == "admin")
        check("enabled flag true", body["enabled"] is True)
        check("is_internal true", body["is_internal"] is True)
        check("internal scope is unbounded (company_id null)", body["company_id"] is None)
        check("capabilities include module.access", "module.access" in body["capabilities"])
        # The invariant is "ADMIN holds ALL capabilities EXCEPT the client company's own
        # five decisions", not "ADMIN holds exactly N" -- a hardcoded count would break
        # every time a phase registers a new capability. The exception is deliberate:
        # administrative access is not the authority to decide on a client's behalf.
        from app.models.hrms import (Cap as _Cap, CLIENT_DECISION_CAPS as _DECISIONS,
                                     CLIENT_OWNED_CAPS as _OWNED)
        check("admin gets every registered capability bar the client's own",
              len(body["capabilities"]) == len(_Cap) - len(_DECISIONS | _OWNED))
        check("and none of those five is in the served list",
              not ({c.value for c in _DECISIONS} & set(body["capabilities"])))
        check("capabilities are sorted", body["capabilities"] == sorted(body["capabilities"]))

        as_user(CLIENT_HR)
        body = client.get("/api/hrms/health").json()
        check("client HR resolves to hr", body["role"] == "hr")
        check("client scoped to own company", body["company_id"] == "C1")
        check("client is_internal false", body["is_internal"] is False)
        check("HR has audit.read", "audit.read" in body["capabilities"])
        check("HR lacks module.admin", "module.admin" not in body["capabilities"])

        as_user(CLIENT_EMP)
        body = client.get("/api/hrms/health").json()
        check("employee resolves to employee", body["role"] == "employee")
        # The invariant is "a plain employee can never MUTATE anyone else's data", not an
        # exact capability list -- later phases legitimately grant them read/self-service
        # capabilities (e.g. requisition.create, which is deliberate design intent).
        check("employee holds module.access", "module.access" in body["capabilities"])
        check("employee holds no write capability",
              not any(c.endswith(".write") for c in body["capabilities"]))
        check("employee holds no approval capability",
              not any("approve" in c or "review" in c for c in body["capabilities"]))
        check("employee cannot see salary", "employee.salary.read" not in body["capabilities"])

        as_user(CLIENT_MD)
        body = client.get("/api/hrms/health").json()
        check("clientadmin resolves to md", body["role"] == "md")
        check("MD has module.admin", "module.admin" in body["capabilities"])

        # -----------------------------------------------------
        section("Company gate -- module off means unreachable by URL")
        # -----------------------------------------------------
        as_user(DISABLED_CO_USER)
        r = client.get("/api/hrms/health")
        check("disabled company -> 403", r.status_code == 403)
        check("403 carries an actionable reason",
              "not enabled" in r.json().get("detail", "").lower())
        r = client.get("/api/hrms/audit")
        check("gate applies to EVERY endpoint, not just health", r.status_code == 403)

        as_user(STAFF_ADMIN)
        check("internal staff bypass the company gate",
              client.get("/api/hrms/health").status_code == 200)

        # -----------------------------------------------------
        section("GET /api/hrms/audit -- capability gating")
        # -----------------------------------------------------
        as_user(CLIENT_EMP)
        r = client.get("/api/hrms/audit")
        check("employee without audit.read -> 403", r.status_code == 403)

        as_user(CLIENT_HR)
        r = client.get("/api/hrms/audit")
        check("HR with audit.read -> 200", r.status_code == 200)
        check("response shape {audit, count}", set(r.json().keys()) == {"audit", "count"})

        # -----------------------------------------------------
        section("Tenant isolation over HTTP")
        # -----------------------------------------------------
        as_user(CLIENT_HR)
        client.get("/api/hrms/audit", params={"company_id": "C_OTHER"})
        check("client CANNOT read another tenant via query param (pinned to own)",
              captured.get("company_id") == "C1")

        as_user(SUPERADMIN)
        client.get("/api/hrms/audit", params={"company_id": "C_OTHER"})
        check("internal MAY target another company", captured.get("company_id") == "C_OTHER")

        client.get("/api/hrms/audit")
        check("internal unscoped when no company given", captured.get("company_id") is None)

        # -----------------------------------------------------
        section("Query validation")
        # -----------------------------------------------------
        as_user(SUPERADMIN)
        check("limit=0 rejected (422)",
              client.get("/api/hrms/audit", params={"limit": 0}).status_code == 422)
        check("limit=501 rejected (422)",
              client.get("/api/hrms/audit", params={"limit": 501}).status_code == 422)
        check("limit=500 accepted",
              client.get("/api/hrms/audit", params={"limit": 500}).status_code == 200)
        check("non-numeric limit rejected (422)",
              client.get("/api/hrms/audit", params={"limit": "abc"}).status_code == 422)

        # -----------------------------------------------------
        section("Unauthenticated access")
        # -----------------------------------------------------
        app.dependency_overrides.pop(get_current_user, None)
        r = client.get("/api/hrms/health")
        check("no token -> 401 (never 200)", r.status_code == 401)
        r = client.get("/api/hrms/audit")
        check("audit needs auth too -> 401", r.status_code == 401)
        app.dependency_overrides[get_current_user] = lambda: current["user"]

        # -----------------------------------------------------
        section("Company toggle authorization")
        # -----------------------------------------------------
        as_user(CLIENT_MD)
        r = client.patch("/api/companies/C1/hrms-access", json={"enabled": True})
        check("client MD cannot toggle the module -> 403", r.status_code == 403)

        as_user(CLIENT_EMP)
        r = client.patch("/api/companies/C1/hrms-access", json={"enabled": True})
        check("employee cannot toggle the module -> 403", r.status_code == 403)

        as_user(SUPERADMIN)
        r = client.patch("/api/companies/C1/hrms-access", json={})
        check("missing 'enabled' rejected (422)", r.status_code == 422)
        r = client.patch("/api/companies/C1/hrms-access", json={"enabled": "yes-please"})
        check("non-boolean 'enabled' rejected (422)", r.status_code == 422)

        # -----------------------------------------------------
        section("Regression -- existing modules still routed")
        # -----------------------------------------------------
        r = client.get("/")
        check("API root still responds 200", r.status_code == 200)
        check("root banner unchanged", r.json().get("status") == "success")

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            code = client.get(path).status_code
            # 401 (auth required) is the correct answer; 404 would mean we broke routing.
            check(f"{path} still routed (got {code}, not 404)", code != 404)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
