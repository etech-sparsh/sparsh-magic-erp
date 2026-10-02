"""Phase 4 SECURITY harness -- the public surface, over HTTP.

This is the most important test in the module. It guards the only endpoints in the ERP
reachable with no token, by anyone, which accept files and personal data.

Every assertion here encodes a rule from the header comment of routes/hrms_public.py. If one
of these fails, do not "fix the test" -- the rule it protects has been broken.

Also sweeps the WHOLE application to prove Phase 4 did not accidentally make any other
endpoint public.

Run:  python -m app.services.hrms.tests.test_phase4_public_security   (from backend/)
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
LIVE = "CP-AAA111"
EXTERNAL = "NK-BBB222"
PAUSED = "LI-CCC333"

VALID = {
    "candidate_name": "Asha Rao",
    "can_email": "asha@example.com",
    "can_contact": "9876543210",
    "declaration": True,
}


def main() -> None:
    import main as app_main
    import app.routes.hrms_public as PUB
    import app.utils.hrms_public_guard as G
    from app.controllers.auth_controller import get_current_user

    app = app_main.app
    client = TestClient(app)

    # ---- Stub the service + limiter so this harness tests the ROUTE layer only ----
    seen = {}
    limited = {"scopes": []}

    async def fake_get(code):
        seen["get"] = code
        from fastapi import HTTPException
        if code == EXTERNAL:
            return {"ok": True, "external": True, "external_url": "https://x.example",
                    "title": "T", "platform": "Naukri"}
        if code == PAUSED:
            raise HTTPException(status_code=410, detail=G.CLOSED_LINK)
        if code != LIVE:
            raise HTTPException(status_code=404, detail=G.INVALID_LINK)
        return {"ok": True, "external": False, "posting_code": code, "title": "Analyst"}

    async def fake_submit(code, payload):
        seen["submit"] = (code, payload)
        return {"ok": True, "duplicate": False, "reference": "CAN-001",
                "message": "Your application has been submitted."}

    async def fake_limit(scope, identifier):
        limited["scopes"].append((scope, identifier))

    PUB.postings.get_public_posting = fake_get
    PUB.postings.submit_application = fake_submit
    PUB.enforce_rate_limit = fake_limit

    try:
        # =================================================================
        section("RULE 1: the public routes require NO authentication")
        # =================================================================
        # No dependency_overrides, no Authorization header -- a real anonymous caller.
        r = client.get(f"/api/hrms/public/apply/{LIVE}")
        check("GET job ad with no token -> 200 (never 401)", r.status_code == 200)
        r = client.post(f"/api/hrms/public/apply/{LIVE}", json=VALID)
        check("POST application with no token -> 200 (never 401)", r.status_code == 200)

        # A stale/garbage Authorization header must be ignored, not rejected -- an applicant
        # may have an unrelated token in their browser.
        r = client.get(f"/api/hrms/public/apply/{LIVE}",
                       headers={"Authorization": "Bearer garbage.token.here"})
        check("a garbage bearer token does not break the public route", r.status_code == 200)

        section("RULE 1b: the public router is NOT company-gated")
        # Gating on hrms_enabled would let an applicant infer a client's subscription state
        # from a shared link.
        check("no hrms_enabled check on the public router",
              client.get(f"/api/hrms/public/apply/{LIVE}").status_code == 200)

        # =================================================================
        section("RULE 2: the code is validated BEFORE it reaches a query")
        # =================================================================
        seen.clear()
        injections = [
            '{"$ne":null}', '{"$gt":""}', "../../etc/passwd", "..%2f..%2fetc",
            "CP-AAA111'", 'CP-AAA111"', "CP-AAA111;drop", "<script>alert(1)</script>",
            "CP-AAA11", "CP-AAA1111", "cp-aaa111%00", "*", "%2e%2e%2f",
        ]
        blocked = 0
        for payload in injections:
            code = client.get(f"/api/hrms/public/apply/{payload}").status_code
            if code in (404, 400, 422):
                blocked += 1
        check(f"all {len(injections)} malformed/injection codes refused "
              f"(got {blocked})", blocked == len(injections))
        check("no malformed code ever reached the service", "get" not in seen)

        seen.clear()
        client.get("/api/hrms/public/apply/cp-aaa111")
        check("a valid lowercase code is normalised to upper before the query",
              seen.get("get") == LIVE)

        # =================================================================
        section("RULE 3: every endpoint is rate limited BEFORE doing work")
        # =================================================================
        limited["scopes"].clear()
        client.get(f"/api/hrms/public/apply/{LIVE}")
        check("GET is rate limited per IP", ("view",) == tuple(s for s, _ in limited["scopes"]))

        limited["scopes"].clear()
        client.post(f"/api/hrms/public/apply/{LIVE}", json=VALID)
        scopes = [s for s, _ in limited["scopes"]]
        check("POST is limited per IP", "apply" in scopes)
        check("POST is ALSO limited per posting code (defeats a proxy pool)",
              "apply-posting" in scopes)
        check("the per-code limit keys on the code, not the IP",
              any(ident == LIVE for s, ident in limited["scopes"] if s == "apply-posting"))

        limited["scopes"].clear()
        client.get(f"/api/hrms/public/apply/{LIVE}",
                   headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
        check("the limiter keys on the first forwarded hop",
              any(ident == "203.0.113.5" for _s, ident in limited["scopes"]))

        # A malformed code must be rejected without consuming limiter budget or DB work.
        limited["scopes"].clear()
        client.get("/api/hrms/public/apply/{$ne:null}")
        check("a malformed code is rejected before the limiter is even consulted",
              limited["scopes"] == [])

        # =================================================================
        section("RULE 4: errors are vague and identical (no existence oracle)")
        # =================================================================
        missing = client.get("/api/hrms/public/apply/ZZ-ZZZZZZ")
        malformed = client.get("/api/hrms/public/apply/ZZ-ZZZ")
        check("a well-formed but unknown code -> 404", missing.status_code == 404)
        check("a malformed code -> 404 as well", malformed.status_code == 404)
        check("both return the IDENTICAL message",
              missing.json()["detail"] == malformed.json()["detail"])
        check("the message reveals nothing internal",
              missing.json()["detail"] == "This application link is not valid.")

        closed = client.get(f"/api/hrms/public/apply/{PAUSED}")
        check("a closed posting -> 410 (distinguishable for the applicant)",
              closed.status_code == 410)
        check("the closed message reveals nothing internal",
              "no longer accepting" in closed.json()["detail"].lower()
              and "compan" not in closed.json()["detail"].lower())

        # =================================================================
        section("RULE 5: responses expose only what a candidate needs")
        # =================================================================
        body = client.get(f"/api/hrms/public/apply/{LIVE}").json()
        for leak in ("company_id", "request_no", "jd_no", "requires_assessment",
                     "posted_by", "notes", "created_at", "_id"):
            check(f"public ad omits {leak}", leak not in body)

        ext = client.get(f"/api/hrms/public/apply/{EXTERNAL}").json()
        check("external posting exposes only its destination",
              set(ext) <= {"ok", "external", "external_url", "title", "platform"})

        submitted = client.post(f"/api/hrms/public/apply/{LIVE}", json=VALID).json()
        check("the submit response returns only a reference and a message",
              set(submitted) <= {"ok", "duplicate", "reference", "message"})
        check("the submit response leaks no internal id",
              "company_id" not in submitted and "_id" not in submitted)

        # =================================================================
        section("Request validation at the schema layer")
        # =================================================================
        for missing_field in ("candidate_name", "can_email", "can_contact"):
            payload = {k: v for k, v in VALID.items() if k != missing_field}
            check(f"missing '{missing_field}' -> 422",
                  client.post(f"/api/hrms/public/apply/{LIVE}",
                              json=payload).status_code == 422)
        check("a non-JSON body -> 422",
              client.post(f"/api/hrms/public/apply/{LIVE}",
                          content="not json").status_code == 422)
        check("an array body -> 422",
              client.post(f"/api/hrms/public/apply/{LIVE}", json=[1, 2]).status_code == 422)
        # Unknown keys are ignored, not trusted: a crafted field must not reach the document.
        seen.clear()
        client.post(f"/api/hrms/public/apply/{LIVE}",
                    json={**VALID, "application_status": "Selected", "company_id": "C-EVIL",
                          "uk": "CAN-999", "requires_assessment": False})
        payload = seen["submit"][1]
        for forged in ("application_status", "company_id", "uk", "requires_assessment"):
            check(f"a forged '{forged}' field is dropped by the schema", forged not in payload)

        # =================================================================
        section("SWEEP: Phase 4 made nothing else public")
        # =================================================================
        # Enumerate every GET route in the app and confirm only the intended ones answer
        # without a token. This is the assertion that catches an accidental leak in a
        # LATER phase, not just this one.
        app.dependency_overrides.pop(get_current_user, None)
        # Prefixes only -- "/" is deliberately NOT here: as a prefix it matches every path
        # and would silently make the sweep test nothing at all.
        intended_public_prefixes = ("/api/hrms/public/", "/api/auth/")
        # Pre-existing, deliberately-anonymous endpoints owned by other modules. The
        # Assistant's own router documents these as liveness/readiness probes, which have to
        # answer without a token to be useful to a container orchestrator. Allow-listed by
        # EXACT path (never by prefix) so a future /api/assistant/* route is still swept.
        # See OUT_OF_SCOPE_FINDINGS OOS-005 for the mild flag disclosure in /ready.
        # Meta's WhatsApp webhook verification handshake. Meta GETs this URL before it
        # will POST to it, unauthenticated by protocol -- it cannot take a token and still
        # work. The POST alongside it is signature-verified (HMAC), which is the real
        # control; this GET only ever echoes back a challenge it was already sent.
        intended_public_exact = {"/api/assistant/health", "/api/assistant/ready",
                                 "/api/leadership/whatsapp-status"}
        leaked = []
        checked = 0
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if "GET" not in methods or "{" in path or not path.startswith("/api/"):
                continue
            if any(path.startswith(p) for p in intended_public_prefixes):
                continue
            if path in intended_public_exact:
                continue
            checked += 1
            code = client.get(path).status_code
            if code not in (401, 403, 404, 405, 422):
                leaked.append((path, code))
        check(f"swept {checked} authenticated GET routes", checked > 20)
        if leaked:
            for path, code in leaked[:10]:
                print(f"     LEAK: {path} answered {code} with no token")
        check("no authenticated route answers without a token", not leaked)

        section("Regression: the authenticated HRMS surface still needs a token")
        for path in ("/api/hrms/health", "/api/hrms/postings", "/api/hrms/employees",
                     "/api/hrms/requisitions", "/api/hrms/jd"):
            check(f"{path} -> 401 without a token",
                  client.get(path).status_code == 401)

        section("Regression: other modules still routed and still protected")
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities", "/api/holidays"):
            code = client.get(path).status_code
            check(f"{path} protected (got {code})", code == 401)
        check("API root still public", client.get("/").status_code == 200)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
