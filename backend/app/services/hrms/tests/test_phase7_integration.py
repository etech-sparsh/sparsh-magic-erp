"""Phase 7 integration harness -- interviews over HTTP.

Exercises capability gating, the inherent right to see your own bookings, route ordering,
validation, tenant pinning and the .ics download.

Run:  python -m app.services.hrms.tests.test_phase7_integration   (from backend/)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
SOON = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()


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
        return {"interviews": [], "total": 0, "stats": {}}

    async def fake_schedulable(actor, company_id):
        seen["company_id"] = company_id
        return []

    async def fake_schedule(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"interview_no": "INT-2026-001"}

    async def fake_update(actor, company_id, no, payload):
        seen["update"] = (company_id, no, payload)
        return {"interview_no": no, **payload}

    async def fake_cancel(actor, company_id, no):
        seen["cancel"] = (company_id, no)
        return {"cancelled": True, "interview_no": no}

    async def fake_evaluate(actor, company_id, no, payload):
        seen["evaluate"] = (company_id, no, payload)
        return {"interview_no": no, "outcome": payload.get("outcome")}

    async def fake_visible(actor, company_id, no):
        seen["visible"] = (company_id, no)
        return {"interview_no": no, "company_id": company_id, "round": "HR Round",
                "candidate_name": "Asha", "scheduled_at": datetime.now(timezone.utc),
                "duration_min": 45, "status": "Scheduled", "ics_sequence": 0,
                "interviewer_email": "i@x.com", "candidate_email": "a@x.com"}

    R.interviews.list_interviews = fake_list
    R.interviews.schedulable_candidates = fake_schedulable
    R.interviews.schedule_interview = fake_schedule
    R.interviews.update_interview = fake_update
    R.interviews.cancel_interview = fake_cancel
    R.interviews.evaluate_interview = fake_evaluate
    R.interviews._require_visible = fake_visible

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
    BOOK = {"uk": "CAN-001", "round": "HR Round", "mode": "Virtual",
            "scheduled_at": SOON, "duration_min": 45, "interviewer_id": "hod",
            "meeting_link": "https://meet.example/x"}
    CARD = {"technical": 4, "communication": 4, "problem_solving": 4, "behavior": 4,
            "confidence": 4, "team_fit": 4, "outcome": "Pass", "signature": "Hari"}

    try:
        section("Capabilities via /health")
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        for c in ("interview.read", "interview.schedule", "interview.evaluate"):
            check(f"HR has {c}", c in caps)
        check("HR lacks interview.decide_md", "interview.decide_md" not in caps)
        as_user(MD)
        check("MD has interview.decide_md",
              "interview.decide_md" in client.get("/api/hrms/health").json()["capabilities"])
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD can evaluate", "interview.evaluate" in caps)
        check("HOD cannot schedule", "interview.schedule" not in caps)
        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("EMPLOYEE can evaluate (may be an interviewer)", "interview.evaluate" in caps)
        check("EMPLOYEE cannot browse all", "interview.read" not in caps)
        as_user(INTERNAL)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("INTERNAL can schedule", "interview.schedule" in caps)
        check("INTERNAL cannot evaluate", "interview.evaluate" not in caps)

        # =================================================================
        section("Listing is an INHERENT RIGHT, not a capability")
        # =================================================================
        # An interviewer who cannot open their own booking cannot do the job, so the list
        # endpoint is not gated -- the capability only WIDENS what it returns.
        as_user(EMP)
        check("an employee WITHOUT interview.read can still list (scoped to their own)",
              client.get("/api/hrms/interviews").status_code == 200)
        as_user(HOD)
        check("a manager can list", client.get("/api/hrms/interviews").status_code == 200)

        section("Capability gating on the write paths")
        as_user(EMP)
        check("employee -> schedule 403",
              client.post("/api/hrms/interviews", json=BOOK).status_code == 403)
        check("employee -> schedulable picker 403",
              client.get("/api/hrms/interviews/schedulable").status_code == 403)
        as_user(HOD)
        check("HOD -> schedule 403",
              client.post("/api/hrms/interviews", json=BOOK).status_code == 403)
        check("HOD -> evaluate reaches the service",
              client.post("/api/hrms/interviews/INT-1/evaluate", json=CARD).status_code == 200)
        as_user(INTERNAL)
        check("INTERNAL -> schedule 201",
              client.post("/api/hrms/interviews", json=BOOK,
                          params={"company_id": COMPANY}).status_code == 201)
        as_user(HR)
        check("HR -> schedule 201",
              client.post("/api/hrms/interviews", json=BOOK).status_code == 201)
        check("HR -> schedulable picker 200",
              client.get("/api/hrms/interviews/schedulable").status_code == 200)

        section("Route ordering -- /schedulable must beat /{interview_no}")
        seen.pop("company_id", None)
        r = client.get("/api/hrms/interviews/schedulable")
        check("/interviews/schedulable reaches the picker", r.status_code == 200)
        check("picker returns its own shape", "candidates" in r.json())

        section("Validation")
        check("no uk -> 422",
              client.post("/api/hrms/interviews",
                          json={k: v for k, v in BOOK.items() if k != "uk"}).status_code == 422)
        check("no scheduled_at -> 422",
              client.post("/api/hrms/interviews",
                          json={k: v for k, v in BOOK.items()
                                if k != "scheduled_at"}).status_code == 422)
        check("invalid round rejected by the schema -> 422",
              client.post("/api/hrms/interviews",
                          json={**BOOK, "round": "Coffee"}).status_code == 422)
        check("invalid mode rejected -> 422",
              client.post("/api/hrms/interviews",
                          json={**BOOK, "mode": "Telepathy"}).status_code == 422)
        check("evaluate without a signature -> 422",
              client.post("/api/hrms/interviews/INT-1/evaluate",
                          json={k: v for k, v in CARD.items()
                                if k != "signature"}).status_code == 422)
        check("evaluate without an outcome -> 422",
              client.post("/api/hrms/interviews/INT-1/evaluate",
                          json={k: v for k, v in CARD.items()
                                if k != "outcome"}).status_code == 422)
        check("invalid outcome rejected by the schema -> 422",
              client.post("/api/hrms/interviews/INT-1/evaluate",
                          json={**CARD, "outcome": "Maybe"}).status_code == 422)
        check("limit bounds enforced",
              client.get("/api/hrms/interviews", params={"limit": 501}).status_code == 422)

        section("Forged fields dropped by the schema")
        seen.pop("payload", None)
        client.post("/api/hrms/interviews",
                    json={**BOOK, "status": "Completed", "outcome": "Pass",
                          "company_id": "C-EVIL", "interview_no": "INT-EVIL"})
        for forged in ("status", "outcome", "company_id", "interview_no"):
            check(f"forged '{forged}' dropped", forged not in seen["payload"])
        # The update model deliberately omits round/candidate/interviewer -- changing those
        # would make an existing scorecard meaningless.
        seen.pop("update", None)
        client.patch("/api/hrms/interviews/INT-1",
                     json={"notes": "ok", "round": "MD Round", "uk": "CAN-9",
                           "interviewer_id": "someone-else"})
        for forged in ("round", "uk", "interviewer_id"):
            check(f"'{forged}' cannot be changed after booking", forged not in seen["update"][2])

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/interviews", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/interviews/INT-1/evaluate", json=CARD,
                    params={"company_id": OTHER})
        check("client cannot evaluate in another tenant", seen["evaluate"][0] == COMPANY)
        client.delete("/api/hrms/interviews/INT-1", params={"company_id": OTHER})
        check("client cannot cancel in another tenant", seen["cancel"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/interviews", params={"company_id": OTHER})
        check("internal may target a company", seen["company_id"] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/interviews").status_code == 400)

        section("Calendar invite download")
        as_user(HR)
        r = client.get("/api/hrms/interviews/INT-2026-001/invite.ics")
        check("invite served 200", r.status_code == 200)
        check("served as text/calendar", "text/calendar" in r.headers.get("content-type", ""))
        check("offered as a download",
              "attachment" in r.headers.get("content-disposition", ""))
        check("body is a VCALENDAR", r.text.startswith("BEGIN:VCALENDAR"))
        check("invite is scoped through the same visibility check", "visible" in seen)

        section("Company gate + auth")
        as_user({"_id": "z", "role": "clientuser", "_source_collection": "learners",
                 "company_id": "C_OFF", "governance_role": "HR"})
        check("disabled company -> 403", client.get("/api/hrms/interviews").status_code == 403)

        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/hrms/interviews", "/api/hrms/interviews/schedulable",
                     "/api/hrms/interviews/INT-1/invite.ics"):
            check(f"no token -> 401 on {path}", client.get(path).status_code == 401)

        section("Regression -- earlier phases and other modules")
        for path in ("/api/hrms/health", "/api/hrms/assessments", "/api/hrms/candidates",
                     "/api/hrms/postings", "/api/hrms/employees", "/api/hrms/requisitions"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)
        check("public apply still anonymous",
              client.get("/api/hrms/public/apply/ZZ-ZZZZZZ").status_code not in (401, 403))
        check("public assess still anonymous",
              client.get("/api/hrms/public/assess/" + "A" * 22).status_code not in (401, 403))
        check("API root still 200", client.get("/").status_code == 200)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            check(f"{path} still protected", client.get(path).status_code == 401)

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
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
