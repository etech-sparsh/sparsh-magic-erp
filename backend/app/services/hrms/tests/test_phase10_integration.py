"""Phase 10 integration harness -- analytics and reports over HTTP.

The security questions this phase raises are all route-level: is `entity` really an
allow-list, is `by` really an allow-list, can a client retarget another tenant, can a
hiring manager reach the export they are not granted, and does the download actually stream
with the headers the UI relies on.

Run:  python -m app.services.hrms.tests.test_phase10_integration   (from backend/)
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

    async def fake_dashboard(actor, company_id, **kw):
        seen["dashboard"] = (company_id, kw)
        return {"range": {"from": "2026-01-01", "to": "2026-03-31"},
                "scoped_to_own_requisitions": False, "kpis": [],
                "positions": {}, "offer_outcomes": {}, "onboarding_states": {},
                "time_to_hire": {}}

    async def fake_funnel(actor, company_id, **kw):
        seen["funnel"] = (company_id, kw)
        return {"total": 0, "stages": [], "lost": {}, "unranked": 0,
                "range": {"from": "2026-01-01", "to": "2026-03-31"}}

    async def fake_breakdown(actor, company_id, by, **kw):
        seen["breakdown"] = (company_id, by, kw)
        return {"by": by, "label": by.title(), "total": 0, "rows": [], "truncated": False,
                "range": {"from": "2026-01-01", "to": "2026-03-31"}}

    async def fake_report(actor, company_id, entity, **kw):
        seen["report"] = (company_id, entity, kw)
        return {"entity": entity, "columns": [{"key": "uk", "label": "Candidate ID"}],
                "rows": [{"uk": "CAN-01"}], "total": 1, "page": kw.get("page", 1),
                "page_size": kw.get("page_size", 25), "pages": 1,
                "salary_visible": True, "scoped_to_own_requisitions": False,
                "range": {"from": "2026-01-01", "to": "2026-03-31"}}

    async def fake_export(actor, company_id, entity, **kw):
        seen["export"] = (company_id, entity, kw)
        return {"entity": entity,
                "columns": [("uk", "Candidate ID"), ("candidate_name", "Name")],
                "rows": [["CAN-01", "Asha"], ["CAN-02", "Bela"]],
                "total": 9, "returned": 2, "truncated": True,
                "range": ("2026-01-01", "2026-03-31")}

    R.analytics.dashboard = fake_dashboard
    R.analytics.funnel = fake_funnel
    R.analytics.breakdown = fake_breakdown
    R.analytics.report = fake_report
    R.analytics.export_rows = fake_export

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

    try:
        section("Capabilities via /health")
        for label, user in (("HR", HR), ("MD", MD), ("INTERNAL", INTERNAL)):
            as_user(user)
            caps = client.get("/api/hrms/health").json()["capabilities"]
            check(f"{label} has analytics.read, report.read and report.export",
                  all(c in caps for c in
                      ("analytics.read", "report.read", "report.export")))
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has analytics.read", "analytics.read" in caps)
        check("HOD has report.read", "report.read" in caps)
        check("HOD does NOT have report.export", "report.export" not in caps)
        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("employee has no analytics or report capability",
              not any(c.startswith(("analytics.", "report.")) for c in caps))

        section("Capability gating per endpoint")
        as_user(EMP)
        for path in ("/api/hrms/analytics/dashboard", "/api/hrms/analytics/funnel",
                     "/api/hrms/analytics/breakdown", "/api/hrms/reports/candidates"):
            check(f"employee -> {path} 403", client.get(path).status_code == 403)
        as_user(HOD)
        check("HOD -> dashboard 200",
              client.get("/api/hrms/analytics/dashboard").status_code == 200)
        check("HOD -> funnel 200",
              client.get("/api/hrms/analytics/funnel").status_code == 200)
        check("HOD -> report 200",
              client.get("/api/hrms/reports/candidates").status_code == 200)
        check("HOD -> EXPORT 403 — the whole point of the separate capability",
              client.get("/api/hrms/reports/candidates/export").status_code == 403)
        as_user(HR)
        check("HR -> export 200",
              client.get("/api/hrms/reports/candidates/export").status_code == 200)

        section("Route ordering — /export must not be swallowed by /{entity}")
        seen.pop("export", None)
        seen.pop("report", None)
        client.get("/api/hrms/reports/offers/export")
        check("the export route was reached", "export" in seen)
        check("and the paginated report route was NOT", "report" not in seen)

        section("Entity is an allow-list, not a collection name")
        for bad in ("learners", "staff", "hrms_audit_log", "companies", "../users",
                    "candidates%00"):
            code = client.get(f"/api/hrms/reports/{bad}").status_code
            check(f"entity '{bad}' refused (got {code})", code in (404, 422))
        seen.pop("report", None)
        client.get("/api/hrms/reports/learners")
        check("no rejected entity reached the service", "report" not in seen)
        for good in ("candidates", "requisitions", "interviews", "offers", "onboarding"):
            check(f"entity '{good}' accepted",
                  client.get(f"/api/hrms/reports/{good}").status_code == 200)

        section("Breakdown dimension is an allow-list too")
        # 'platform' is in this list because it was RETIRED, not merely never allowed: a
        # posting has no platform now, so the dimension must be refused rather than group a
        # field nothing writes.
        for bad in ("can_email", "ctc", "password", "$where", "platform"):
            check(f"breakdown by '{bad}' refused",
                  client.get("/api/hrms/analytics/breakdown",
                             params={"by": bad}).status_code == 422)
        for good in ("source", "department", "designation", "referral_source"):
            check(f"breakdown by '{good}' accepted",
                  client.get("/api/hrms/analytics/breakdown",
                             params={"by": good}).status_code == 200)

        section("Pagination and format bounds")
        check("page 0 -> 422", client.get("/api/hrms/reports/candidates",
                                          params={"page": 0}).status_code == 422)
        check("page -1 -> 422", client.get("/api/hrms/reports/candidates",
                                           params={"page": -1}).status_code == 422)
        check("page_size 0 -> 422", client.get("/api/hrms/reports/candidates",
                                               params={"page_size": 0}).status_code == 422)
        check("page_size beyond the cap -> 422",
              client.get("/api/hrms/reports/candidates",
                         params={"page_size": 5000}).status_code == 422)
        check("page_size at the cap -> 200",
              client.get("/api/hrms/reports/candidates",
                         params={"page_size": 100}).status_code == 200)
        check("an unknown export format -> 422",
              client.get("/api/hrms/reports/candidates/export",
                         params={"fmt": "exe"}).status_code == 422)
        for fmt in ("csv", "xlsx"):
            check(f"format '{fmt}' accepted",
                  client.get("/api/hrms/reports/candidates/export",
                             params={"fmt": fmt}).status_code == 200)

        section("The download itself")
        r = client.get("/api/hrms/reports/candidates/export", params={"fmt": "csv"})
        check("streams as CSV", r.headers["content-type"].startswith("text/csv"))
        check("is sent as an attachment",
              "attachment" in r.headers.get("content-disposition", ""))
        check("with a dated filename",
              "hrms_candidates_2026-01-01_to_2026-03-31.csv"
              in r.headers.get("content-disposition", ""))
        check("truncation is announced in a header",
              r.headers.get("x-export-truncated") == "true")
        check("row counts are announced too",
              r.headers.get("x-export-rows") == "2" and r.headers.get("x-export-total") == "9")
        body = r.content.decode("utf-8-sig")
        check("the file carries the human column labels", "Candidate ID" in body)
        check("the file carries the data", "Asha" in body)
        check("and states the truncation INSIDE the file, not only in a header",
              "truncated to the first" in body)

        rx = client.get("/api/hrms/reports/candidates/export", params={"fmt": "xlsx"})
        check("XLSX streams with the spreadsheet media type",
              "spreadsheetml" in rx.headers["content-type"])
        check("XLSX body is a real zip container", rx.content[:2] == b"PK")
        check("XLSX filename ends .xlsx",
              ".xlsx" in rx.headers.get("content-disposition", ""))

        section("Date range reaches the service verbatim")
        seen.pop("dashboard", None)
        client.get("/api/hrms/analytics/dashboard",
                   params={"date_from": "2026-01-01", "date_to": "2026-02-01"})
        kw = seen["dashboard"][1]
        check("date_from passed through", kw["date_from"] == "2026-01-01")
        check("date_to passed through", kw["date_to"] == "2026-02-01")

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/analytics/dashboard", params={"company_id": OTHER})
        check("a client cannot retarget the dashboard", seen["dashboard"][0] == COMPANY)
        client.get("/api/hrms/analytics/funnel", params={"company_id": OTHER})
        check("nor the funnel", seen["funnel"][0] == COMPANY)
        client.get("/api/hrms/reports/candidates", params={"company_id": OTHER})
        check("nor a report", seen["report"][0] == COMPANY)
        client.get("/api/hrms/reports/candidates/export", params={"company_id": OTHER})
        check("nor an export — the most damaging one to get wrong",
              seen["export"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/analytics/dashboard", params={"company_id": OTHER})
        check("internal staff may target a company", seen["dashboard"][0] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/analytics/dashboard").status_code == 400)
        check("internal export without a company -> 400",
              client.get("/api/hrms/reports/candidates/export").status_code == 400)

        section("Analytics is READ-ONLY at the routing layer")
        as_user(HR)
        for path in ("/api/hrms/analytics/dashboard", "/api/hrms/analytics/funnel",
                     "/api/hrms/reports/candidates"):
            for verb in ("post", "patch", "delete", "put"):
                code = getattr(client, verb)(path).status_code
                check(f"{verb.upper()} {path} -> 405", code == 405)

        section("SWEEP: no new public surface")
        app.dependency_overrides.pop(get_current_user, None)
        for path in ("/api/hrms/analytics/dashboard", "/api/hrms/analytics/funnel",
                     "/api/hrms/analytics/breakdown", "/api/hrms/reports/candidates",
                     "/api/hrms/reports/candidates/export"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)

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

        section("Regression — earlier phases intact")
        for path in ("/api/hrms/health", "/api/hrms/onboarding", "/api/hrms/offers",
                     "/api/hrms/interviews", "/api/hrms/assessments",
                     "/api/hrms/candidates", "/api/hrms/employees",
                     "/api/hrms/requisitions"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)
        for path in ("/api/hrms/public/apply/ZZ-ZZZZZZ",
                     "/api/hrms/public/assess/" + "A" * 22,
                     "/api/hrms/public/offer/" + "A" * 22,
                     "/api/hrms/public/onboard/" + "A" * 22):
            check(f"{path} still anonymous",
                  client.get(path).status_code not in (401, 403))
        check("the ERP's own /reports module is untouched and still admin-gated",
              client.get("/api/reports/overview").status_code in (401, 403))
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
