"""Internal Hiring -- the approval chain, every action against every role.

The sibling file test_client_transition_rbac_matrix does this for the eight Client Hiring
tables. This one covers INTERNAL_REQ_TRANSITIONS, the internal requisition's approval
chain, which is where the SOP's separation of duties actually lives:

    HR verifies -> Management/Finance approve the budget -> the hiring manager approves
    the scorecard -> Approved.

Separation of duties is only real if NO SINGLE ROLE can drive the chain end to end. That is
the property this file exists to protect, and it is the one a well-meaning capability edit
is most likely to break.

Unlike the client services, `act_on_requisition` loads the record BEFORE checking the
capability, so every case here is seeded in the exact `from` state the action expects --
otherwise a 409 would mask the permission answer entirely.

Four properties:

  1. EVERY ACTION IS GATED. An actor without the capability is refused, and the record
     does not move.
  2. EVERY ACTION IS REACHABLE. Somebody can perform each one.
  3. SEPARATION OF DUTIES. No non-owner role can perform every step of the chain alone.
     Superadmin deliberately can -- it is the module owner and the break-glass account.
  4. THE CLIENT TRACK CANNOT TOUCH IT. Internal hiring is Sparsh's own vacancies; a client
     company's user is refused every action.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_approval_rbac_matrix  (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO, ACME = "sparsh-magic", "client-acme"


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone
    from fastapi import HTTPException

    from app.models import hrms as M
    from app.utils import hrms_access as HA
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)
    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RQ
    import app.services.hrms_audit_service as AUD
    for mod in (RQ, AUD, HA):
        mod.get_collection = mongo.get_collection

    def sparsh(role="admin", gov=None, name="Sparsh"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "company_id": CO, "full_name": name}
        if gov:
            u["governance_role"] = gov
        return u

    def client(name="Client"):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": ACME,
                "full_name": name, M.CLIENT_TRACK_FLAG: True}

    ACTORS = {
        "Superadmin":  sparsh("superadmin"),
        "MD":          sparsh("admin", "MD"),
        "HR":          sparsh("admin", "HR"),
        "Team Lead":   sparsh("admin", "HOD"),
        "Finance":     sparsh("admin", "FINANCE"),
        "Operator":    sparsh("staff"),
        "Implementor": sparsh("staff", "IMPLEMENTOR"),
        "Client admin": client(),
    }

    reqs = store.setdefault(M.COLL_REQUISITIONS, FakeCollection())

    def seed(request_no: str, status) -> None:
        reqs.docs.append({
            "request_no": request_no, "company_id": CO, "track": "internal",
            "position_title": "Backend Engineer", "approval_status": status.value,
            "headcount": 1, "raised_by": str(ObjectId()), "created_at": NOW,
            # enough for budget-approve's own payload validation to be reached
            "approved_headcount": 1,
        })

    async def attempt(actor, action, from_status):
        """Seed a fresh requisition in `from_status` and try `action` as `actor`."""
        rn = f"REQ-T-{len(reqs.docs):04d}"
        seed(rn, from_status)
        try:
            await RQ.act_on_requisition(
                actor, CO, rn, action, remarks="because",
                budget={"approved_headcount": 1,
                        "approved_salary_band_min": 100000,
                        "approved_salary_band_max": 200000})
            code = 0
        except HTTPException as e:
            code = e.status_code
        except Exception:                        # noqa: BLE001
            code = -1
        row = await reqs.find_one({"request_no": rn, "company_id": CO})
        return code, row.get("approval_status")

    try:
        table = M.INTERNAL_REQ_TRANSITIONS
        print(f"\nWalking {len(table)} internal approval actions x {len(ACTORS)} actors "
              f"= {len(table) * len(ACTORS)} calls")

        # =================================================================
        section("1. Every action refuses an actor without its capability")
        # =================================================================
        holders: dict[str, list[str]] = {}
        leaks, moved = [], []
        for action, spec in table.items():
            from_status, _to, cap, _rem = spec
            cap = cap if isinstance(cap, M.Cap) else getattr(M.Cap, cap)
            allowed = []
            for label, actor in ACTORS.items():
                code, status_after = await attempt(actor, action, from_status)
                if HA.can(actor, cap):
                    allowed.append(label)
                else:
                    if code == 0:
                        leaks.append(f"{action}: {label} lacks {cap.name} but SUCCEEDED")
                    if status_after != from_status.value:
                        moved.append(f"{action}: {label} was refused but the record "
                                     f"moved to {status_after}")
            holders[action] = allowed

        check(f"no action succeeded for an actor lacking its capability ({len(leaks)})",
              not leaks)
        for x in leaks:
            print(f"        {x}")
        check(f"a refused action never moved the record ({len(moved)})", not moved)
        for x in moved:
            print(f"        {x}")

        # =================================================================
        section("2. Every action is reachable")
        # =================================================================
        dead = [a for a, who in holders.items() if not who]
        check(f"no dead transitions ({len(dead)})", not dead)
        for x in dead:
            print(f"        {x}")

        # =================================================================
        section("3. Separation of duties -- nobody but the owner drives it alone")
        # =================================================================
        CHAIN = ["hr-verify", "budget-approve", "scorecard-approve"]
        for label in ACTORS:
            can_all = all(label in holders[a] for a in CHAIN)
            if label == "Superadmin":
                check("Superadmin CAN drive the whole chain (break-glass, by design)",
                      can_all)
            else:
                steps = [a for a in CHAIN if label in holders[a]]
                check(f"{label} cannot drive the chain alone "
                      f"(holds {len(steps)}/3: {steps or 'none'})", not can_all)

        # =================================================================
        section("4. A client-track caller is refused the internal chain outright")
        # =================================================================
        client_actor = ACTORS["Client admin"]
        refused = []
        for action, spec in table.items():
            code, _ = await attempt(client_actor, action, spec[0])
            refused.append(code != 0)
        check(f"client-track caller refused all {len(table)} internal actions",
              all(refused))

        # =================================================================
        section("Coverage map")
        # =================================================================
        for action, who in holders.items():
            print(f"    {action:20} {len(who)} actor(s): {', '.join(who) or 'NOBODY'}")
        check("coverage map produced", True)

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
