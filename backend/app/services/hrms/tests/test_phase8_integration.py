"""Phase 8 integration harness -- offers over HTTP, including the third public surface.

Run:  python -m app.services.hrms.tests.test_phase8_integration   (from backend/)
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
        return {"offers": [], "total": 0, "stats": {}, "ctc_visible": False}

    async def fake_offerable(actor, company_id):
        seen["company_id"] = company_id
        return []

    async def fake_create(actor, company_id, payload):
        seen["company_id"] = company_id
        seen["payload"] = payload
        return {"offer_no": "OFR-2026-001"}

    async def fake_update(actor, company_id, no, payload):
        seen["update"] = (company_id, no, payload)
        return {"offer_no": no, **payload}

    async def fake_send(actor, company_id, no, payload):
        seen["send"] = (company_id, no, payload)
        return {"offer_no": no, "status": "Sent"}

    async def fake_revoke(actor, company_id, no, payload):
        seen["revoke"] = (company_id, no, payload)
        return {"revoked": True, "offer_no": no}

    async def fake_delete(actor, company_id, no):
        seen["delete"] = (company_id, no)
        return {"deleted": True, "offer_no": no}

    async def fake_public_get(code):
        seen["public_get"] = code
        from fastapi import HTTPException
        if code != GOOD_CODE:
            from app.utils.hrms_public_guard import INVALID_LINK
            raise HTTPException(status_code=404, detail=INVALID_LINK)
        return {"ok": True, "already_responded": False, "status": "Sent",
                "offer_no": "OFR-2026-001", "candidate_name": "Asha",
                "designation": "Analyst", "content": "Body"}

    async def fake_public_respond(code, payload):
        seen["public_respond"] = (code, payload)
        return {"ok": True, "status": "Accepted", "message": "Recorded."}

    async def fake_limit(scope, identifier):
        limited.append((scope, identifier))

    R.offers.list_offers = fake_list
    R.offers.offerable_candidates = fake_offerable
    R.offers.create_offer = fake_create
    R.offers.update_offer = fake_update
    R.offers.send_offer = fake_send
    R.offers.revoke_offer = fake_revoke
    R.offers.delete_offer = fake_delete
    PUB.offers.get_public_offer = fake_public_get
    PUB.offers.respond_to_offer = fake_public_respond
    PUB.enforce_rate_limit = fake_limit

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
    NEW = {"uk": "CAN-001", "ctc": 800000, "joining_date": "2099-01-01"}

    try:
        section("Capabilities via /health")
        as_user(HR)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        for c in ("offer.read", "offer.write", "offer.send"):
            check(f"HR has {c}", c in caps)
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has offer.read", "offer.read" in caps)
        check("HOD lacks offer.write", "offer.write" not in caps)
        as_user(INTERNAL)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("INTERNAL has offer.read", "offer.read" in caps)
        check("INTERNAL lacks offer.send", "offer.send" not in caps)
        as_user(EMP)
        check("employee has no offer capability",
              not any(c.startswith("offer.")
                      for c in client.get("/api/hrms/health").json()["capabilities"]))

        section("Capability gating per endpoint")
        as_user(EMP)
        check("employee -> list 403", client.get("/api/hrms/offers").status_code == 403)
        check("employee -> create 403",
              client.post("/api/hrms/offers", json=NEW).status_code == 403)
        as_user(HOD)
        check("HOD -> list 200", client.get("/api/hrms/offers").status_code == 200)
        check("HOD -> create 403",
              client.post("/api/hrms/offers", json=NEW).status_code == 403)
        check("HOD -> send 403",
              client.post("/api/hrms/offers/OFR-1/send",
                          json={"signature": "x"}).status_code == 403)
        check("HOD -> offerable picker 403",
              client.get("/api/hrms/offers/offerable").status_code == 403)
        as_user(INTERNAL)
        check("INTERNAL -> list 200",
              client.get("/api/hrms/offers", params={"company_id": COMPANY}).status_code == 200)
        check("INTERNAL -> create 403",
              client.post("/api/hrms/offers", json=NEW,
                          params={"company_id": COMPANY}).status_code == 403)
        as_user(HR)
        check("HR -> create 201", client.post("/api/hrms/offers", json=NEW).status_code == 201)
        check("HR -> send 200",
              client.post("/api/hrms/offers/OFR-1/send",
                          json={"signature": "Mira"}).status_code == 200)
        check("HR -> revoke 200",
              client.post("/api/hrms/offers/OFR-1/revoke", json={}).status_code == 200)

        section("create with send_now needs BOTH write and send")
        # A user with offer.write but not offer.send must not be able to issue a letter by
        # setting a flag on the create call.
        import app.models.hrms as M
        original_caps = dict(M.ROLE_CAPABILITIES)
        writer_only = set(M.ROLE_CAPABILITIES[M.HrmsRole.HR]) - {M.Cap.OFFER_SEND}
        M.ROLE_CAPABILITIES[M.HrmsRole.HR] = writer_only
        try:
            as_user(HR)
            check("write-only user -> plain create still 201",
                  client.post("/api/hrms/offers", json=NEW).status_code == 201)
            check("write-only user -> send_now create 403",
                  client.post("/api/hrms/offers",
                              json={**NEW, "send_now": True,
                                    "signature": "x"}).status_code == 403)
        finally:
            M.ROLE_CAPABILITIES.clear()
            M.ROLE_CAPABILITIES.update(original_caps)

        section("Route ordering -- /offerable must beat /{offer_no}")
        as_user(HR)
        r = client.get("/api/hrms/offers/offerable")
        check("/offers/offerable reaches the picker", r.status_code == 200)
        check("picker returns its own shape", "candidates" in r.json())

        section("Validation")
        check("create without uk -> 422",
              client.post("/api/hrms/offers",
                          json={"ctc": 1, "joining_date": "2099-01-01"}).status_code == 422)
        check("create without ctc -> 422",
              client.post("/api/hrms/offers",
                          json={"uk": "CAN-1", "joining_date": "2099-01-01"}).status_code == 422)
        check("create without joining_date -> 422",
              client.post("/api/hrms/offers", json={"uk": "CAN-1", "ctc": 1}).status_code == 422)
        check("send without a signature -> 422",
              client.post("/api/hrms/offers/OFR-1/send", json={}).status_code == 422)
        check("limit bounds enforced",
              client.get("/api/hrms/offers", params={"limit": 501}).status_code == 422)

        section("Forged fields dropped by the schema")
        seen.pop("payload", None)
        client.post("/api/hrms/offers",
                    json={**NEW, "status": "Accepted", "access_code": "mine",
                          "offer_no": "OFR-EVIL", "version": 99, "company_id": "C-EVIL"})
        for forged in ("status", "access_code", "offer_no", "version", "company_id"):
            check(f"forged '{forged}' dropped", forged not in seen["payload"])
        seen.pop("update", None)
        client.patch("/api/hrms/offers/OFR-1",
                     json={"content": "x", "status": "Accepted", "history": [], "uk": "CAN-9"})
        for forged in ("status", "history", "uk"):
            check(f"'{forged}' cannot be patched", forged not in seen["update"][2])

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/offers", params={"company_id": OTHER})
        check("client cannot retarget the list", seen["company_id"] == COMPANY)
        client.post("/api/hrms/offers/OFR-1/send", json={"signature": "x"},
                    params={"company_id": OTHER})
        check("client cannot send in another tenant", seen["send"][0] == COMPANY)
        client.delete("/api/hrms/offers/OFR-1", params={"company_id": OTHER})
        check("client cannot delete in another tenant", seen["delete"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/offers", params={"company_id": OTHER})
        check("internal may target a company", seen["company_id"] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/offers").status_code == 400)

        # =================================================================
        section("PUBLIC offer surface -- no authentication")
        # =================================================================
        app.dependency_overrides.pop(get_current_user, None)
        check("GET with no token -> 200",
              client.get(f"/api/hrms/public/offer/{GOOD_CODE}").status_code == 200)
        check("POST with no token -> 200",
              client.post(f"/api/hrms/public/offer/{GOOD_CODE}",
                          json={"action": "accept", "signature": "A"}).status_code == 200)
        check("a garbage bearer token does not break it",
              client.get(f"/api/hrms/public/offer/{GOOD_CODE}",
                         headers={"Authorization": "Bearer nope"}).status_code == 200)

        section("PUBLIC offer -- code validated before any query")
        seen.pop("public_get", None)
        injections = ['{"$ne":null}', "../../etc/passwd", "short", "a" * 65,
                      "has spaces here 1234567", "<script>alert(1)</script>"]
        blocked = sum(1 for p in injections
                      if client.get(f"/api/hrms/public/offer/{p}").status_code in (404, 400, 422))
        check(f"all {len(injections)} malformed codes refused (got {blocked})",
              blocked == len(injections))
        check("no malformed code reached the service", "public_get" not in seen)

        section("PUBLIC offer -- no existence oracle")
        missing = client.get("/api/hrms/public/offer/" + "Z" * 22)
        malformed = client.get("/api/hrms/public/offer/short")
        check("unknown -> 404", missing.status_code == 404)
        check("malformed -> 404", malformed.status_code == 404)
        check("identical message", missing.json()["detail"] == malformed.json()["detail"])

        section("PUBLIC offer -- rate limited before work")
        limited.clear()
        client.get(f"/api/hrms/public/offer/{GOOD_CODE}")
        check("GET limited on offer-view", ("offer-view",) == tuple(s for s, _ in limited))
        limited.clear()
        client.post(f"/api/hrms/public/offer/{GOOD_CODE}", json={"action": "decline"})
        check("POST limited on offer-respond",
              ("offer-respond",) == tuple(s for s, _ in limited))
        limited.clear()
        client.get("/api/hrms/public/offer/bad")
        check("malformed code rejected before the limiter", limited == [])

        section("PUBLIC offer -- exposes only what a candidate needs")
        body = client.get(f"/api/hrms/public/offer/{GOOD_CODE}").json()
        for leak in ("company_id", "uk", "request_no", "access_code", "created_by",
                     "history", "sent_by"):
            check(f"public letter omits {leak}", leak not in body)

        section("PUBLIC offer -- request validation")
        check("no action -> 422",
              client.post(f"/api/hrms/public/offer/{GOOD_CODE}", json={}).status_code == 422)
        seen.pop("public_respond", None)
        client.post(f"/api/hrms/public/offer/{GOOD_CODE}",
                    json={"action": "accept", "signature": "A", "status": "Accepted",
                          "ctc": 99999999, "offer_no": "OFR-EVIL"})
        payload = seen["public_respond"][1]
        for forged in ("status", "ctc", "offer_no"):
            check(f"forged '{forged}' dropped from a public response", forged not in payload)

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
        for path in ("/api/hrms/health", "/api/hrms/offers", "/api/hrms/interviews",
                     "/api/hrms/assessments", "/api/hrms/candidates", "/api/hrms/employees"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)
        for path in ("/api/hrms/public/apply/ZZ-ZZZZZZ",
                     "/api/hrms/public/assess/" + "A" * 22):
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


if __name__ == "__main__":
    main()
