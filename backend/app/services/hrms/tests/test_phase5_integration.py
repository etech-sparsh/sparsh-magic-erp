"""Phase 5 integration harness -- candidates, screening, journey over HTTP.

Exercises capability gating per endpoint, route ordering, request validation and tenant
pinning, with dependency overrides instead of live credentials so it runs offline.

Run:  python -m app.services.hrms.tests.test_phase5_integration   (from backend/)
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

    async def fake_list(actor, company_id, **kw):
        seen["company_id"] = company_id
        seen["kw"] = kw
        return {"candidates": [], "total": 0, "columns": []}

    async def fake_get(actor, company_id, uk):
        seen["get"] = (company_id, uk)
        return {"uk": uk, "application_status": "Applied", "allowed_next": ["Shortlisted"]}

    async def fake_create(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"uk": "CAN-001"}

    async def fake_update(actor, company_id, uk, payload):
        seen["update"] = (company_id, uk, payload)
        return {"uk": uk, **payload}

    async def fake_delete(actor, company_id, uk):
        seen["delete"] = (company_id, uk)
        return {"deleted": True, "uk": uk}

    async def fake_screen(actor, company_id, payload):
        seen["screen"] = (company_id, payload)
        return {"moved": [], "skipped": [], "moved_count": 0, "skipped_count": 0}

    async def fake_journey(actor, company_id, uk):
        seen["journey"] = (company_id, uk)
        return {"candidate": {"uk": uk}, "rail": [], "events": [], "terminal": False}

    R.candidates.list_candidates = fake_list
    R.candidates.get_candidate = fake_get
    R.candidates.create_candidate = fake_create
    R.candidates.update_candidate = fake_update
    R.candidates.delete_candidate = fake_delete
    R.candidates.screen_candidates = fake_screen
    R.candidates.get_journey = fake_journey

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
    VALID = {"candidate_name": "Asha Rao", "can_contact": "9876543210"}

    try:
        section("Capabilities surfaced by /health")
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        for c in ("candidate.read", "candidate.write", "candidate.screen"):
            check(f"HR has {c}", c in caps)
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has candidate.read", "candidate.read" in caps)
        check("HOD lacks candidate.write", "candidate.write" not in caps)
        check("HOD lacks candidate.screen", "candidate.screen" not in caps)
        as_user(INTERNAL)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("INTERNAL has candidate.write", "candidate.write" in caps)
        check("INTERNAL lacks candidate.screen (hiring decisions stay with the client)",
              "candidate.screen" not in caps)
        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("employee lacks candidate.read", "candidate.read" not in caps)

        section("Capability gating per endpoint")
        as_user(EMP)
        for method, path, body in (("get", "/api/hrms/candidates", None),
                                   ("get", "/api/hrms/candidates/CAN-1", None),
                                   ("get", "/api/hrms/candidates/CAN-1/journey", None)):
            check(f"employee -> {path} 403",
                  getattr(client, method)(path).status_code == 403)
        check("employee -> create 403",
              client.post("/api/hrms/candidates", json=VALID).status_code == 403)
        check("employee -> screen 403",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"], "action": "hold"}).status_code == 403)

        as_user(HOD)
        check("HOD -> list 200", client.get("/api/hrms/candidates").status_code == 200)
        check("HOD -> journey 200",
              client.get("/api/hrms/candidates/CAN-1/journey").status_code == 200)
        check("HOD -> create 403",
              client.post("/api/hrms/candidates", json=VALID).status_code == 403)
        check("HOD -> patch 403",
              client.patch("/api/hrms/candidates/CAN-1",
                           json={"notice_period": "30d"}).status_code == 403)
        check("HOD -> delete 403",
              client.delete("/api/hrms/candidates/CAN-1").status_code == 403)
        check("HOD -> screen 403",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"], "action": "hold"}).status_code == 403)

        as_user(INTERNAL)
        check("INTERNAL -> create 201",
              client.post("/api/hrms/candidates", json=VALID,
                          params={"company_id": COMPANY}).status_code == 201)
        check("INTERNAL -> screen 403",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"], "action": "hold"},
                          params={"company_id": COMPANY}).status_code == 403)

        as_user(HR)
        check("HR -> screen 200",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"], "action": "hold"}).status_code == 200)

        section("Route ordering -- /screen must beat /{uk}")
        # If '/candidates/screen' were captured by '/candidates/{uk}', a POST would 405
        # (that path only accepts GET/PATCH/DELETE) instead of reaching the screener.
        seen.pop("screen", None)
        client.post("/api/hrms/candidates/screen", json={"uks": ["CAN-9"], "action": "hold"})
        check("/candidates/screen reached the screening service", "screen" in seen)
        check("the uk list arrived intact", seen["screen"][1]["uks"] == ["CAN-9"])

        section("Request validation")
        check("create without a name -> 422",
              client.post("/api/hrms/candidates", json={"can_contact": "9"}).status_code == 422)
        check("screen without uks -> 422",
              client.post("/api/hrms/candidates/screen",
                          json={"action": "hold"}).status_code == 422)
        check("screen without an action -> 422",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"]}).status_code == 422)
        check("an unknown action is rejected by the schema -> 422",
              client.post("/api/hrms/candidates/screen",
                          json={"uks": ["CAN-1"], "action": "banish"}).status_code == 422)
        check("an invalid status is rejected by the schema -> 422",
              client.patch("/api/hrms/candidates/CAN-1",
                           json={"application_status": "Promoted"}).status_code == 422)
        check("a valid status is accepted",
              client.patch("/api/hrms/candidates/CAN-1",
                           json={"application_status": "Shortlisted"}).status_code == 200)
        check("limit bounds enforced",
              client.get("/api/hrms/candidates", params={"limit": 501}).status_code == 422)
        check("negative skip rejected",
              client.get("/api/hrms/candidates", params={"skip": -1}).status_code == 422)

        section("Forged fields are dropped by the schema")
        seen.pop("payload", None)
        client.post("/api/hrms/candidates",
                    json={**VALID, "uk": "CAN-EVIL", "company_id": "C-EVIL",
                          "application_status": "Selected"})
        for forged in ("uk", "company_id", "application_status"):
            check(f"forged '{forged}' dropped on create", forged not in seen["payload"])

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/candidates", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/candidates/screen",
                    json={"uks": ["CAN-1"], "action": "hold"}, params={"company_id": OTHER})
        check("client cannot screen in another tenant", seen["screen"][0] == COMPANY)
        client.get("/api/hrms/candidates/CAN-1/journey", params={"company_id": OTHER})
        check("client cannot read another tenant's journey", seen["journey"][0] == COMPANY)

        as_user(INTERNAL)
        client.get("/api/hrms/candidates", params={"company_id": OTHER})
        check("internal may target a chosen company", seen["company_id"] == OTHER)
        check("internal without a company gets 400",
              client.get("/api/hrms/candidates").status_code == 400)

        section("Company gate + auth")
        as_user({"_id": "z", "role": "clientuser", "_source_collection": "learners",
                 "company_id": "C_OFF", "governance_role": "HR"})
        for path in ("/api/hrms/candidates", "/api/hrms/candidates/CAN-1/journey"):
            check(f"disabled company -> 403 on {path}", client.get(path).status_code == 403)

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/hrms/candidates", "/api/hrms/candidates/CAN-1",
                     "/api/hrms/candidates/CAN-1/journey"):
            check(f"no token -> 401 on {path}", client.get(path).status_code == 401)
        app.dependency_overrides[get_current_user] = lambda: current["user"]

        section("Regression -- earlier phases and other modules intact")
        as_user(SUPER)
        check("/api/hrms/health 200", client.get("/api/hrms/health").status_code == 200)
        as_user(HR)
        for path in ("/api/hrms/employees", "/api/hrms/requisitions", "/api/hrms/jd",
                     "/api/hrms/postings", "/api/hrms/departments"):
            check(f"{path} not broken", client.get(path).status_code in (200, 503))
        # The property that matters is "does not require a token". Asserting a specific code
        # would couple this to DB availability -- offline the handler reaches the store and
        # answers 503, which is still proof it was not gated by auth.
        check("public apply route still anonymous (never 401/403)",
              client.get("/api/hrms/public/apply/ZZ-ZZZZZZ").status_code not in (401, 403))
        check("API root still 200", client.get("/").status_code == 200)

        app.dependency_overrides.pop(get_current_user, None)
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
