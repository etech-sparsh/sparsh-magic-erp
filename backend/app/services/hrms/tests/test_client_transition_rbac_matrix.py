"""Client Hiring -- EVERY action in EVERY transition table, against EVERY role.

The per-stage test files each check their own workflow. This one checks the thing no
single stage file can: that the whole track's permission surface is consistent. It walks
all eight CLIENT_*_TRANSITIONS tables and, for each action, calls the real service as each
of eleven actors -- so a capability quietly widened, a table gaining an action nobody
gated, or a Sparsh role acquiring a client decision all fail here rather than in
production.

Why this can be exhaustive and cheap at once: all eight `act_on_client_*` services check
the CAPABILITY FIRST, before the record is loaded or the state examined (verified below as
property 4). A caller who fails the gate is refused with 403 whatever the record says, so
the matrix needs no fixtures -- and if a service ever reordered those checks, the actor
without the capability would see a 404/409 instead and this file would say so.

Four properties:

  1. EVERY ACTION IS GATED. No action is reachable by an actor that lacks its capability.
  2. EVERY ACTION IS REACHABLE. Somebody can perform it -- a transition nobody holds is a
     dead workflow, which is as broken as an open one and much quieter.
  3. THE SIDES HOLD. Client-owned actions are refused to every Sparsh role (Superadmin
     included); Sparsh-owned actions are refused to every client-track caller.
  4. CAPABILITY IS CHECKED BEFORE THE RECORD. An unauthorised caller gets 403, never a 404
     that tells them whether the record exists.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_transition_rbac_matrix   (from backend/)
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

ACME, SPARSH = "client-acme", "sparsh-magic"


async def main() -> None:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models import hrms as M
    from app.utils import hrms_access as HA
    import app.db.mongodb as mongo

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_requisition_service as REQ
    import app.services.hrms_client_scorecard_service as SC
    import app.services.hrms_client_posting_service as PO
    import app.services.hrms_client_candidate_service as CA
    import app.services.hrms_client_assessment_service as AS
    import app.services.hrms_client_interview_service as IV
    import app.services.hrms_client_offer_service as OF
    import app.services.hrms_client_joining_service as JO
    import app.services.hrms_audit_service as AUD
    for mod in (REQ, SC, PO, CA, AS, IV, OF, JO, AUD, HA):
        mod.get_collection = mongo.get_collection

    # table -> (the service entry point, a record id that does NOT exist)
    WALK = [
        ("CLIENT_REQ_TRANSITIONS",       M.CLIENT_REQ_TRANSITIONS,       REQ.act_on_client_requisition, "CR-9999-999"),
        ("CLIENT_SCORECARD_TRANSITIONS", M.CLIENT_SCORECARD_TRANSITIONS, SC.act_on_client_scorecard,    "PSC-9999-999"),
        ("CLIENT_POSTING_TRANSITIONS",   M.CLIENT_POSTING_TRANSITIONS,   PO.act_on_client_posting,      "CJ-ZZZZZZ"),
        ("CLIENT_CANDIDATE_TRANSITIONS", M.CLIENT_CANDIDATE_TRANSITIONS, CA.act_on_client_candidate,    "CCN-9999-999"),
        ("CLIENT_ASSESSMENT_TRANSITIONS", M.CLIENT_ASSESSMENT_TRANSITIONS, AS.act_on_client_assessment, "CAS-9999-999"),
        ("CLIENT_INTERVIEW_TRANSITIONS", M.CLIENT_INTERVIEW_TRANSITIONS, IV.act_on_client_interview,    "CIN-9999-999"),
        ("CLIENT_OFFER_TRANSITIONS",     M.CLIENT_OFFER_TRANSITIONS,     OF.act_on_client_offer,        "COF-9999-999"),
        ("CLIENT_JOINING_TRANSITIONS",   M.CLIENT_JOINING_TRANSITIONS,   JO.act_on_client_joining,      "CJN-9999-999"),
    ]

    def sparsh(role="admin", gov=None, name="Sparsh"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "company_id": SPARSH, "full_name": name}
        if gov:
            u["governance_role"] = gov
        return u

    def client(role="clientadmin", name="Client"):
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "learners",
                "company_id": ACME, "full_name": name, M.CLIENT_TRACK_FLAG: True}

    ACTORS = {
        "Sparsh Superadmin":  sparsh("superadmin"),
        "Sparsh MD":          sparsh("admin", "MD"),
        "Sparsh HR":          sparsh("admin", "HR"),
        "Sparsh Team Lead":   sparsh("admin", "HOD"),
        "Sparsh Finance":     sparsh("admin", "FINANCE"),
        "Sparsh operator":    sparsh("staff"),
        "Sparsh implementor": sparsh("staff", "IMPLEMENTOR"),
        "Client admin":       client("clientadmin"),
        "Client user":        client("clientuser"),
    }
    SPARSH_SIDE = [k for k in ACTORS if k.startswith("Sparsh")]
    CLIENT_SIDE = [k for k in ACTORS if k.startswith("Client")]

    async def status_for(fn, actor, rec_id, action):
        """The HTTP status the service answers with. 0 means it did not refuse."""
        try:
            await fn(actor, ACME, rec_id, action, {"remarks": "x"})
            return 0
        except HTTPException as e:
            return e.status_code
        except Exception:                       # noqa: BLE001
            return -1

    try:
        total_actions = sum(len(t) for _, t, _, _ in WALK)
        print(f"\nWalking {total_actions} actions across {len(WALK)} tables "
              f"x {len(ACTORS)} actors = {total_actions * len(ACTORS)} calls")

        # =================================================================
        section("1 & 4. Every action refuses every actor that lacks its capability")
        # =================================================================
        holders: dict[tuple[str, str], list[str]] = {}
        leaks: list[str] = []
        wrong_code: list[str] = []
        for tname, table, fn, rec_id in WALK:
            for action, spec in table.items():
                cap = getattr(M.Cap, spec[2])
                allowed, refused = [], []
                for label, actor in ACTORS.items():
                    st = await status_for(fn, actor, rec_id, action)
                    if HA.can(actor, cap):
                        allowed.append(label)
                        # They hold it, so the gate must let them past it. The record does
                        # not exist, so 404 is the correct next answer.
                        if st == 403:
                            wrong_code.append(
                                f"{tname}.{action}: {label} holds {cap.name} but got 403")
                    else:
                        refused.append(label)
                        if st == 0:
                            leaks.append(
                                f"{tname}.{action}: {label} lacks {cap.name} and the "
                                f"action SUCCEEDED")
                        elif st != 403:
                            wrong_code.append(
                                f"{tname}.{action}: {label} lacks {cap.name} but got "
                                f"{st}, not 403 -- the capability is checked after the "
                                f"record, which tells an outsider it exists")
                holders[(tname, action)] = allowed

        check(f"no action succeeded for an actor lacking its capability "
              f"({len(leaks)} leak(s))", not leaks)
        for x in leaks:
            print(f"        {x}")
        check(f"every refusal is a 403, before the record is read "
              f"({len(wrong_code)} wrong)", not wrong_code)
        for x in wrong_code[:12]:
            print(f"        {x}")

        # =================================================================
        section("2. Every action is reachable by somebody")
        # =================================================================
        dead = [f"{t}.{a}" for (t, a), who in holders.items() if not who]
        check(f"no dead transitions ({len(dead)})", not dead)
        for x in dead:
            print(f"        {x}")

        # =================================================================
        section("3. The two sides hold")
        # =================================================================
        client_owned = M.CLIENT_DECISION_CAPS | M.CLIENT_OWNED_CAPS
        sparsh_leak, client_leak, unusable = [], [], []
        for tname, table, _fn, _r in WALK:
            for action, spec in table.items():
                cap = getattr(M.Cap, spec[2])
                who = holders[(tname, action)]
                s_holders = [w for w in who if w in SPARSH_SIDE]
                c_holders = [w for w in who if w in CLIENT_SIDE]
                if cap in client_owned:
                    if s_holders:
                        sparsh_leak.append(f"{tname}.{action} ({cap.name}) -> {s_holders}")
                    if not c_holders:
                        unusable.append(f"{tname}.{action} ({cap.name}) -> no client can")
                else:
                    if c_holders:
                        client_leak.append(f"{tname}.{action} ({cap.name}) -> {c_holders}")

        check(f"no client-owned action reaches a Sparsh role ({len(sparsh_leak)})",
              not sparsh_leak)
        for x in sparsh_leak:
            print(f"        {x}")
        check(f"every client-owned action IS usable by the client ({len(unusable)})",
              not unusable)
        for x in unusable:
            print(f"        {x}")
        # ── The one documented exception ──
        # `client-review` (the client reading the assessment result) is named like a client
        # decision and IS held by the client, but CLIENT_ASSESSMENT_REVIEW was never added
        # to CLIENT_DECISION_CAPS -- so Superadmin keeps it, by virtue of ADMIN resolving
        # to every capability minus the excluded sets. No other Sparsh role holds it.
        #
        # It is therefore the ONLY client-* action a Sparsh role can perform. That is a
        # live decision for the product owner, not a bug this file should silently pass
        # over: pinned here so it stays visible and cannot widen unnoticed. If the sixth
        # gate is ever made exclusive, delete this block -- the general rule above will
        # then cover it.
        KNOWN = {"CLIENT_ASSESSMENT_TRANSITIONS.client-review "
                 "(CLIENT_ASSESSMENT_REVIEW) -> ['Client admin', 'Client user']"}
        unexpected = [x for x in client_leak if x not in KNOWN]
        check(f"no Sparsh-owned action reaches a client-track caller, beyond the one "
              f"documented exception ({len(unexpected)} unexpected)", not unexpected)
        for x in unexpected:
            print(f"        {x}")
        review_holders = [w for w in holders[("CLIENT_ASSESSMENT_TRANSITIONS",
                                              "client-review")]
                          if w in SPARSH_SIDE]
        check("the exception is exactly Superadmin and nobody else on the Sparsh side",
              review_holders == ["Sparsh Superadmin"])
        others = [f"{t}.{a}" for (t, a), who in holders.items()
                  if a.startswith("client-") and a != "client-review"
                  and any(w in SPARSH_SIDE for w in who)]
        check("every OTHER client-* action is refused to all of Sparsh", not others)
        for x in others:
            print(f"        {x}")

        # =================================================================
        section("Coverage map (who may perform each action)")
        # =================================================================
        for tname, table, _fn, _r in WALK:
            print(f"\n  {tname}")
            for action, spec in table.items():
                who = holders[(tname, action)]
                side = ("CLIENT" if getattr(M.Cap, spec[2]) in client_owned else "sparsh")
                print(f"    {action:26} {side:7} {len(who)} actor(s): "
                      f"{', '.join(who) if who else 'NOBODY'}")
        check("coverage map produced for every table", True)

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
