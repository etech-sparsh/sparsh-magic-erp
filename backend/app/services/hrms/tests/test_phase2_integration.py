"""Phase 2 integration harness -- employee master over HTTP.

Exercises the real FastAPI routes (routing order, dependencies, status codes, response
shapes, tenant pinning) with dependency overrides instead of live credentials, so it runs
offline.

Complements test_phase2_employee.py (pure logic). This one answers: does the wiring behave
over HTTP, and are the capability gates actually attached to the endpoints?

Run:  python -m app.services.hrms.tests.test_phase2_integration   (from backend/)
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


def main() -> None:
    import main as app_main
    from app.controllers.auth_controller import get_current_user
    from app.utils import hrms_access as A
    import app.routes.hrms as R

    app = app_main.app

    async def fake_enabled(company_id):
        return company_id in (COMPANY, OTHER)

    A.is_hrms_enabled = fake_enabled

    # Capture what the route layer passes down, so tenant pinning can be asserted at the
    # boundary rather than inferred from a response body.
    seen = {}

    async def fake_list_employees(actor, company_id, **kw):
        seen["company_id"] = company_id
        seen["kwargs"] = kw
        return {"employees": [], "total": 0, "limit": kw.get("limit"), "skip": kw.get("skip"),
                "salary_visible": False}

    async def fake_list_masters(kind, company_id, include_inactive=False):
        seen["company_id"] = company_id
        seen["kind"] = kind
        seen["include_inactive"] = include_inactive
        return []

    async def fake_create_master(kind, company_id, payload, actor):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"id": "new", "name": payload.get("name"), "company_id": company_id}

    async def fake_linkable(actor, company_id):
        seen["company_id"] = company_id
        return [{"user_id": "u1", "name": "Someone"}]

    async def fake_read_audit(**kw):
        return []

    R.employees.list_employees = fake_list_employees
    R.employees.list_linkable_users = fake_linkable
    R.masters.list_masters = fake_list_masters
    R.masters.create_master = fake_create_master
    R.read_audit = fake_read_audit

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

    try:
        # -----------------------------------------------------
        section("Capabilities are surfaced by /health")
        # -----------------------------------------------------
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        for c in ("employee.read", "employee.write", "employee.salary.read",
                  "department.write", "designation.write"):
            check(f"HR has {c}", c in caps)

        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has employee.read", "employee.read" in caps)
        check("HOD lacks employee.write", "employee.write" not in caps)
        check("HOD lacks employee.salary.read", "employee.salary.read" not in caps)

        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        # Invariant, not a snapshot -- see the same note in test_phase1_integration.
        check("Employee cannot read the directory", "employee.read" not in caps)
        check("Employee holds no write capability",
              not any(c.endswith(".write") for c in caps))

        as_user(INTERNAL)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("INTERNAL has employee.write", "employee.write" in caps)
        check("INTERNAL lacks client salary read", "employee.salary.read" not in caps)

        # -----------------------------------------------------
        section("Employee endpoints -- capability gating")
        # -----------------------------------------------------
        as_user(EMP)
        check("employee -> directory 403", client.get("/api/hrms/employees").status_code == 403)
        check("employee -> create 403",
              client.post("/api/hrms/employees", json={"user_id": "x"}).status_code == 403)
        check("employee -> linkable 403",
              client.get("/api/hrms/employees/linkable").status_code == 403)

        as_user(HOD)
        check("HOD -> directory 200", client.get("/api/hrms/employees").status_code == 200)
        check("HOD -> create 403",
              client.post("/api/hrms/employees", json={"user_id": "x"}).status_code == 403)
        check("HOD -> patch 403",
              client.patch("/api/hrms/employees/x", json={"gender": "Male"}).status_code == 403)

        as_user(HR)
        check("HR -> directory 200", client.get("/api/hrms/employees").status_code == 200)

        # -----------------------------------------------------
        section("Master endpoints -- capability gating")
        # -----------------------------------------------------
        as_user(HOD)
        check("HOD -> list departments 200",
              client.get("/api/hrms/departments").status_code == 200)
        check("HOD -> create department 403",
              client.post("/api/hrms/departments", json={"name": "X"}).status_code == 403)
        check("HOD -> delete department 403",
              client.delete("/api/hrms/departments/abc").status_code == 403)
        check("HOD -> create designation 403",
              client.post("/api/hrms/designations", json={"name": "X"}).status_code == 403)

        as_user(EMP)
        check("employee -> list departments 403",
              client.get("/api/hrms/departments").status_code == 403)
        check("employee -> suggestions 403",
              client.get("/api/hrms/masters/suggestions").status_code == 403)

        as_user(HR)
        r = client.post("/api/hrms/departments", json={"name": "Sales"})
        check("HR -> create department 201", r.status_code == 201)

        # -----------------------------------------------------
        section("Tenant pinning at the route boundary")
        # -----------------------------------------------------
        as_user(HR)
        client.get("/api/hrms/employees", params={"company_id": OTHER})
        check("client CANNOT retarget the directory via query param",
              seen["company_id"] == COMPANY)

        client.get("/api/hrms/departments", params={"company_id": OTHER})
        check("client CANNOT retarget masters via query param", seen["company_id"] == COMPANY)

        client.post("/api/hrms/departments", json={"name": "Y"}, params={"company_id": OTHER})
        check("client CANNOT create into another tenant", seen["company_id"] == COMPANY)

        as_user(INTERNAL)
        client.get("/api/hrms/employees", params={"company_id": OTHER})
        check("internal MAY target a chosen company", seen["company_id"] == OTHER)

        r = client.get("/api/hrms/employees")
        check("internal WITHOUT a company gets 400, not silent cross-tenant data",
              r.status_code == 400)
        check("400 explains what is required",
              "company" in r.json().get("detail", "").lower())

        # -----------------------------------------------------
        section("Route ordering -- static paths beat /{user_id}")
        # -----------------------------------------------------
        as_user(HR)
        # If '/employees/linkable' were captured by '/employees/{user_id}', the handler would
        # call ObjectId("linkable"), which raises -> 400 "Invalid user id". Reaching the
        # picker (200) proves the static route is matched first.
        r = client.get("/api/hrms/employees/linkable")
        check("/employees/linkable is not swallowed by /employees/{user_id}",
              r.status_code == 200)
        check("/employees/linkable returns the picker shape", "users" in r.json())

        as_user(EMP)
        # '/employees/me' must be reachable WITHOUT employee.read -- reading your own record
        # is an inherent right, not a capability.
        r = client.get("/api/hrms/employees/me")
        check("/employees/me is not 403 for a plain employee", r.status_code != 403)

        # -----------------------------------------------------
        section("Query validation")
        # -----------------------------------------------------
        as_user(HR)
        check("limit=0 rejected", client.get("/api/hrms/employees", params={"limit": 0}).status_code == 422)
        check("limit=501 rejected", client.get("/api/hrms/employees", params={"limit": 501}).status_code == 422)
        check("negative skip rejected", client.get("/api/hrms/employees", params={"skip": -1}).status_code == 422)
        check("limit=500 accepted", client.get("/api/hrms/employees", params={"limit": 500}).status_code == 200)
        r = client.post("/api/hrms/departments", json={})
        check("department name is required (422)", r.status_code == 422)
        r = client.post("/api/hrms/employees", json={})
        check("employee user_id is required (422)", r.status_code == 422)

        # -----------------------------------------------------
        section("Company gate + auth still apply to Phase 2 routes")
        # -----------------------------------------------------
        as_user({"_id": "z", "role": "clientuser", "_source_collection": "learners",
                 "company_id": "C_OFF", "governance_role": "HR"})
        for path in ("/api/hrms/employees", "/api/hrms/departments", "/api/hrms/designations"):
            check(f"disabled company -> 403 on {path}", client.get(path).status_code == 403)

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/hrms/employees", "/api/hrms/departments",
                     "/api/hrms/employees/me", "/api/hrms/companies"):
            check(f"no token -> 401 on {path}", client.get(path).status_code == 401)
        app.dependency_overrides[get_current_user] = lambda: current["user"]

        # -----------------------------------------------------
        section("Regression -- Phase 1 and other modules intact")
        # -----------------------------------------------------
        as_user(SUPER)
        check("/api/hrms/health still 200", client.get("/api/hrms/health").status_code == 200)
        check("/api/hrms/audit still 200", client.get("/api/hrms/audit").status_code == 200)
        check("API root still 200", client.get("/").status_code == 200)

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            code = client.get(path).status_code
            check(f"{path} still routed (got {code}, not 404)", code != 404)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
