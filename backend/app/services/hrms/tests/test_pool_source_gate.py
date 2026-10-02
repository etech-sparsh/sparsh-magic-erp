"""Available Candidate pool -- reading it and sourcing from it need the SAME capability.

Found by the full-HRMS RBAC audit (2026-09-22). `list_candidate_pool` refused a caller
without CLIENT_CANDIDATE_WRITE with a 403, while `resource_from_pool` checked only that
the caller was Sparsh staff. So a Sparsh support operator (HrmsRole.INTERNAL) or an
IMPLEMENTOR (HrmsRole.EMPLOYEE) -- neither of whom could so much as LIST the pool --
could still POST /client-candidate-pool/source and create a candidate record inside a
client company's tenant.

The read was gated and the write was not, which is the wrong way round.

What this file pins:

  1. SYMMETRY. Whoever cannot read the pool cannot source from it either.
  2. THE RECRUITER STILL WORKS. HR holds CLIENT_CANDIDATE_WRITE, so the feature is intact.
  3. STILL SPARSH-ONLY. A client-track caller is refused first, whatever they hold.
  4. NOTHING IS WRITTEN ON A REFUSAL. A 403 must not leave a half-created candidate.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_pool_source_gate   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:  # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

ACME, OTHER, SPARSH = "client-acme", "client-other", "sparsh-magic"


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    from app.utils import hrms_access as HA
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)

    reqs = FakeCollection([
        {"cr_no": "CR-2026-001", "company_id": ACME, "role_title": "Backend Engineer",
         "role_level": M.ClientRoleLevel.MID.value, "salary_range_min": 900000,
         "salary_range_max": 1400000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
    ])
    scorecards = FakeCollection([
        {"psc_no": "PSC-2026-001", "company_id": ACME, "cr_no": "CR-2026-001",
         "status": M.ClientScorecardStatus.APPROVED.value, "created_at": NOW},
    ])
    candidates = FakeCollection([
        # Rejected on somebody else's engagement -- in the pool, re-sourceable.
        {"ccn_no": "CCN-2026-001", "company_id": OTHER, "cr_no": "CR-2025-009",
         "candidate_name": "Pooled Person", "email": "p@example.com",
         "status": M.ClientCandidateStatus.CLIENT_REJECTED.value, "created_at": NOW},
    ])
    store = {M.COLL_CLIENT_REQUISITIONS: reqs,
             M.COLL_CLIENT_SCORECARDS: scorecards,
             M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_candidate_service as CC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (CC, AUD, IDS, HA):
        mod.get_collection = mongo.get_collection

    def sparsh(role="staff", gov=None, name="Sparsh Person"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "company_id": SPARSH, "full_name": name}
        if gov:
            u["governance_role"] = gov
        return u

    def client_side():
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": ACME,
                "full_name": "Client Person", M.CLIENT_TRACK_FLAG: True}

    OPERATOR = sparsh("staff", None, "Sparsh Operator")          # INTERNAL
    IMPLEMENTOR = sparsh("staff", "IMPLEMENTOR", "Implementor")   # EMPLOYEE
    RECRUITER = sparsh("admin", "HR", "Sparsh Recruiter")         # HR
    CLIENT = client_side()

    def source_payload():
        return {"ccn_no": "CCN-2026-001", "from_company_id": OTHER,
                "cr_no": "CR-2026-001"}

    try:
        # =================================================================
        section("1. Whoever cannot READ the pool cannot SOURCE from it")
        # =================================================================
        for actor, label in ((OPERATOR, "Sparsh staff (INTERNAL)"),
                             (IMPLEMENTOR, "Sparsh IMPLEMENTOR (EMPLOYEE)")):
            role = HA.hrms_role(actor)
            check(f"{label} resolves to {role.name} and lacks CLIENT_CANDIDATE_WRITE",
                  not HA.can(actor, M.Cap.CLIENT_CANDIDATE_WRITE))
            await expect_http(
                f"...{label} cannot LIST the pool",
                CC.list_candidate_pool(actor, limit=10), 403, "needs")
            await expect_http(
                f"...{label} cannot SOURCE from it either",
                CC.resource_from_pool(actor, ACME, source_payload()), 403, "needs")

        # =================================================================
        section("4. A refusal writes nothing")
        # =================================================================
        check("no candidate record was created by the refused calls",
              len(candidates.docs) == 1)

        # =================================================================
        section("3. Still Sparsh's, whatever a client holds")
        # =================================================================
        check("a client-track caller holds CLIENT_CANDIDATE_WRITE? no",
              not HA.can(CLIENT, M.Cap.CLIENT_CANDIDATE_WRITE))
        await expect_http(
            "a client-side caller cannot source from the cross-tenant pool",
            CC.resource_from_pool(CLIENT, ACME, source_payload()), 403, "Sparsh")

        # =================================================================
        section("2. The recruiter the feature exists for is unaffected")
        # =================================================================
        check("HR holds CLIENT_CANDIDATE_WRITE",
              HA.can(RECRUITER, M.Cap.CLIENT_CANDIDATE_WRITE))
        pool = await CC.list_candidate_pool(RECRUITER, limit=10)
        rows = pool["client_candidate_pool"]
        check("HR can read the pool and the pooled person is in it",
              any(r.get("ccn_no") == "CCN-2026-001" for r in rows))

        made = await CC.resource_from_pool(RECRUITER, ACME, source_payload())
        check("HR can source them into the target engagement",
              bool(made.get("ccn_no")))
        check("...as a NEW record in the TARGET tenant",
              len(candidates.docs) == 2
              and any(d["company_id"] == ACME
                      and d.get("candidate_name") == "Pooled Person"
                      for d in candidates.docs))
        origin = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                            "company_id": OTHER})
        check("...and the original row is untouched, on the client who rejected them",
              origin["status"] == M.ClientCandidateStatus.CLIENT_REJECTED.value)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print("\n" + "=" * 64)
    print(f"  {passed}/{len(results)} checks passed")
    print("=" * 64)
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
