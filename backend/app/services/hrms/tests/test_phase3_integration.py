"""Phase 3 integration harness -- requisitions + JDs over HTTP.

Exercises the real FastAPI routes: capability gating per endpoint, route ordering, request
validation, tenant pinning and the approval endpoint's authorization, with dependency
overrides instead of live credentials so it runs offline.

Run:  python -m app.services.hrms.tests.test_phase3_integration   (from backend/)
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

    seen = {}

    async def fake_list_reqs(actor, company_id, **kw):
        seen["company_id"] = company_id
        seen["kwargs"] = kw
        return {"requisitions": [], "total": 0, "stats": {}}

    async def fake_create(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"request_no": "HR-REQ-2026-001"}

    # `budget` carries the internal track's approved headcount and salary band. The route
    # always passes it, so the double must accept it or this stops testing the route.
    async def fake_act(actor, company_id, request_no, action, remarks=None,
                       salary_change=None, budget=None):
        seen["act"] = (company_id, request_no, action, remarks, salary_change)
        seen["budget"] = budget
        return {"request_no": request_no, "approval_status": "Pending MD Approval"}

    async def fake_list_jds(actor, company_id, **kw):
        seen["company_id"] = company_id
        return {"job_descriptions": [], "total": 0}

    async def fake_update(actor, company_id, request_no, payload):
        seen["company_id"] = company_id
        return {"request_no": request_no, **payload}

    async def fake_close(actor, company_id, request_no, status):
        seen["close"] = (company_id, request_no, status)
        return {"request_no": request_no, "closing_status": status}

    async def fake_update_jd(actor, company_id, jd_no, payload):
        seen["company_id"] = company_id
        return {"jd_no": jd_no, **payload}

    # Every service the routes call is stubbed, so these assertions test the ROUTE layer
    # (capability gate, wiring, tenant pinning) deterministically. Anything left unmocked
    # would reach the DB and return 503 here, testing connectivity rather than routing.
    R.requisitions.list_requisitions = fake_list_reqs
    R.requisitions.create_requisition = fake_create
    R.requisitions.act_on_requisition = fake_act
    R.requisitions.list_jds = fake_list_jds
    R.requisitions.update_requisition = fake_update
    R.requisitions.close_requisition = fake_close
    R.requisitions.update_jd = fake_update_jd

    SUPER = {"_id": "sa", "role": "superadmin", "_source_collection": "staff"}
    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}
    MD = {"_id": "md", "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY}
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

    VALID = {
        "department_id": "d1", "designation_id": "g1", "vacancy": 1,
        "experience_required": "2y", "qualification": "B.Com",
        "essential_skills": "Excel", "required_date": "2026-12-01",
        "assignee_id": "u1", "jd": {"responsibilities": "Do the thing."},
    }

    try:
        # -----------------------------------------------------
        section("Capabilities surfaced by /health")
        # -----------------------------------------------------
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HR has requisition.review_hr", "requisition.review_hr" in caps)
        check("HR lacks requisition.approve_md", "requisition.approve_md" not in caps)

        as_user(MD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("MD has requisition.approve_md", "requisition.approve_md" in caps)
        check("MD lacks requisition.review_hr", "requisition.review_hr" not in caps)

        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("employee has requisition.create", "requisition.create" in caps)
        check("employee has requisition.read", "requisition.read" in caps)
        check("employee lacks requisition.write", "requisition.write" not in caps)

        # -----------------------------------------------------
        section("Requisition endpoints -- capability gating")
        # -----------------------------------------------------
        as_user(EMP)
        check("employee -> list 200", client.get("/api/hrms/requisitions").status_code == 200)
        check("employee -> create 201",
              client.post("/api/hrms/requisitions", json=VALID).status_code == 201)
        check("employee -> edit 403",
              client.patch("/api/hrms/requisitions/X", json={"vacancy": 2}).status_code == 403)
        check("employee -> delete 403",
              client.delete("/api/hrms/requisitions/X").status_code == 403)
        check("employee -> close 403",
              client.post("/api/hrms/requisitions/X/close", json={"status": "Hold"}).status_code == 403)

        as_user(HOD)
        check("HOD -> create 201",
              client.post("/api/hrms/requisitions", json=VALID).status_code == 201)
        check("HOD -> edit 403",
              client.patch("/api/hrms/requisitions/X", json={"vacancy": 2}).status_code == 403)

        as_user(HR)
        check("HR -> edit 200",
              client.patch("/api/hrms/requisitions/X", json={"vacancy": 2}).status_code == 200)
        check("HR -> close 200",
              client.post("/api/hrms/requisitions/X/close", json={"status": "Hold"}).status_code == 200)
        check("close passes the enum VALUE, not the Enum object", seen["close"][2] == "Hold")

        # -----------------------------------------------------
        section("Approve endpoint -- gated INSIDE the service, from the transition table")
        # -----------------------------------------------------
        as_user(HR)
        r = client.post("/api/hrms/requisitions/X/approve", json={"action": "hr-approve"})
        check("HR may run the HR stage", r.status_code == 200)
        check("action reached the service", seen["act"][2] == "hr-approve")

        # No _require() sits on this route on purpose: the per-action capability lives in the
        # same table that defines the state machine, so the gate cannot drift from the rule.
        check("the route itself carries no blanket capability gate",
              client.post("/api/hrms/requisitions/X/approve",
                          json={"action": "md-approve"}).status_code == 200)

        section("JD endpoints")
        as_user(EMP)
        check("employee -> JD list 200", client.get("/api/hrms/jd").status_code == 200)
        check("employee -> JD edit 403",
              client.patch("/api/hrms/jd/JD-1", json={"ctc": "x"}).status_code == 403)
        as_user(HOD)
        check("HOD -> JD edit 403",
              client.patch("/api/hrms/jd/JD-1", json={"ctc": "x"}).status_code == 403)
        as_user(HR)
        check("HR -> JD edit reaches the service",
              client.patch("/api/hrms/jd/JD-1", json={"ctc": "x"}).status_code == 200)
        # There is deliberately no create and no independent approve for JDs.
        check("no POST /jd endpoint exists",
              client.post("/api/hrms/jd", json={"title": "x"}).status_code == 405)
        check("no JD approve endpoint exists",
              client.post("/api/hrms/jd/JD-1/approve", json={}).status_code == 404)

        # -----------------------------------------------------
        section("Request validation")
        # -----------------------------------------------------
        as_user(HR)
        # `assignee_id` and `jd` are deliberately absent from this list: neither is collected
        # at raise time any more. A requisition left unassigned is not incomplete (see
        # create_requisition's own note), and the JD is authored by HR in Step 3, once
        # Management/Finance has cleared headcount and budget (Internal Recruitment SOP §3).
        for missing in ("department_id", "designation_id", "experience_required",
                        "qualification", "essential_skills", "required_date"):
            payload = {k: v for k, v in VALID.items() if k != missing}
            code = client.post("/api/hrms/requisitions", json=payload).status_code
            check(f"missing '{missing}' rejected (422)", code == 422)

        # The unknown-action rule lives in the service, which is stubbed here -- asserting it
        # against a stub would test the stub. It is covered against the REAL implementation
        # in test_phase3_requisition ("unknown action -> 422 'Invalid action'"). What this
        # layer owns is that the action string reaches the service untouched.
        client.post("/api/hrms/requisitions/X/approve", json={"action": "md-reject"})
        check("the action string reaches the service verbatim", seen["act"][2] == "md-reject")
        check("remarks and salary reach the service",
              client.post("/api/hrms/requisitions/X/approve",
                          json={"action": "md-approve", "remarks": "ok", "salary_change": 500}
                          ).status_code == 200 and seen["act"][3] == "ok" and seen["act"][4] == 500)
        check("missing action rejected (422)",
              client.post("/api/hrms/requisitions/X/approve", json={}).status_code == 422)
        check("invalid closing status rejected (422)",
              client.post("/api/hrms/requisitions/X/close",
                          json={"status": "Vanished"}).status_code == 422)
        check("limit bounds enforced",
              client.get("/api/hrms/requisitions", params={"limit": 201}).status_code == 422)
        check("negative skip rejected",
              client.get("/api/hrms/requisitions", params={"skip": -1}).status_code == 422)

        # -----------------------------------------------------
        section("Tenant pinning")
        # -----------------------------------------------------
        as_user(HR)
        client.get("/api/hrms/requisitions", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/requisitions", json=VALID, params={"company_id": OTHER})
        check("client cannot create into another tenant", seen["company_id"] == COMPANY)
        client.post("/api/hrms/requisitions/X/approve", json={"action": "hr-approve"},
                    params={"company_id": OTHER})
        check("client cannot approve in another tenant", seen["act"][0] == COMPANY)
        client.get("/api/hrms/jd", params={"company_id": OTHER})
        check("client cannot list another tenant's JDs", seen["company_id"] == COMPANY)

        as_user(INTERNAL)
        client.get("/api/hrms/requisitions", params={"company_id": OTHER})
        check("internal may target a chosen company", seen["company_id"] == OTHER)
        check("internal without a company gets 400",
              client.get("/api/hrms/requisitions").status_code == 400)

        # -----------------------------------------------------
        section("Company gate + auth apply to Phase 3 routes")
        # -----------------------------------------------------
        as_user({"_id": "z", "role": "clientuser", "_source_collection": "learners",
                 "company_id": "C_OFF", "governance_role": "HR"})
        for path in ("/api/hrms/requisitions", "/api/hrms/jd"):
            check(f"disabled company -> 403 on {path}", client.get(path).status_code == 403)

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/hrms/requisitions", "/api/hrms/jd"):
            check(f"no token -> 401 on {path}", client.get(path).status_code == 401)
        app.dependency_overrides[get_current_user] = lambda: current["user"]

        # -----------------------------------------------------
        section("Regression -- earlier phases and other modules intact")
        # -----------------------------------------------------
        as_user(SUPER)
        check("/api/hrms/health 200", client.get("/api/hrms/health").status_code == 200)
        as_user(HR)
        for path in ("/api/hrms/employees", "/api/hrms/departments", "/api/hrms/designations"):
            check(f"{path} still 200-or-503 (not broken)",
                  client.get(path).status_code in (200, 503))
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
