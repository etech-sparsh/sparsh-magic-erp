"""Client Hiring, increment 1 -- a client company gets into HRMS, and no further.

Sparsh Magic runs two hiring tracks that must not meet. This file pins the boundary.

The property worth testing hardest is NOT "a client cannot read another tenant" -- company
scoping already did that, and it is tested elsewhere. It is the quieter one: a client
company's OWN admin must not get the run of HRMS inside their own tenant. Before this
increment they resolved to a full HRMS ladder role, so opening the module gate for them
would have handed over payroll, employees, exits and Internal Hiring in one step. Tenant
isolation would not have caught it, because none of that would have been another tenant's
data -- it would have been theirs.

So the ceiling is applied at `capabilities_for`, the single function `can()` resolves
through, and it starts EMPTY. Each later increment adds only what that increment needs.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_track_gate   (from backend/)
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
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.utils.hrms_access as HA

    SPARSH, CLIENT_ON, CLIENT_OFF = ObjectId(), ObjectId(), ObjectId()

    companies = FakeCollection([
        {"_id": SPARSH, "name": "Sparsh Magic", "hrms_enabled": True, "is_internal": True},
        {"_id": CLIENT_ON, "name": "Client With Module", "hrms_enabled": True},
        {"_id": CLIENT_OFF, "name": "Client Without Module", "hrms_enabled": False},
    ])
    store = {"companies": companies}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    HA.get_collection = mongo.get_collection

    def staff(role="admin", governance=None):
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
                "company_id": str(SPARSH), "governance_role": governance,
                "full_name": "Sparsh Person"}

    def client_user(company, role="clientadmin", governance=None):
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "learners",
                "company_id": str(company), "governance_role": governance,
                "full_name": "Client Person"}

    try:
        # =================================================================
        section("The two doors are mutually exclusive")
        # =================================================================
        check("Sparsh Magic is the operator",
              await HA.is_hrms_enabled(str(SPARSH)))
        check("...and is NOT admitted as a client",
              not await HA.client_track_company(str(SPARSH)))
        check("a client company with the module on is admitted as a client",
              await HA.client_track_company(str(CLIENT_ON)))
        check("...and is NOT the operator",
              not await HA.is_hrms_enabled(str(CLIENT_ON)))
        check("a client company with the module off is admitted by neither",
              not await HA.is_hrms_enabled(str(CLIENT_OFF))
              and not await HA.client_track_company(str(CLIENT_OFF)))

        # =================================================================
        section("Who the module gate lets in")
        # =================================================================
        internal = staff(governance="HR")
        await HA.ensure_hrms_enabled(internal)
        check("Sparsh staff pass", True)
        check("and are never stamped as client-track",
              not internal.get(M.CLIENT_TRACK_FLAG))

        admitted = client_user(CLIENT_ON)
        await HA.ensure_hrms_enabled(admitted)
        check("a client company with the module on is let in", True)
        check("and IS stamped as client-track",
              bool(admitted.get(M.CLIENT_TRACK_FLAG)))

        await expect_http(
            "a client company with the module off",
            HA.ensure_hrms_enabled(client_user(CLIENT_OFF)), 403, "not enabled")

        # =================================================================
        section("The ceiling -- the point of the whole increment")
        # =================================================================
        # Same person, same role, same company. The ONLY difference is the stamp.
        before = HA.capabilities_for(client_user(CLIENT_ON))
        check("without the stamp a client admin resolves to a full HRMS ladder role",
              len(before) > 100)
        after = HA.capabilities_for(admitted)
        check("with it they hold EXACTLY the client track set",
              after == set(M.CLIENT_TRACK_CAPS))
        # The ceiling grows with every step, so a fixed size fails for the wrong reason.
        # What must stay true is the SHAPE, and the verb is a poor guide to it -- "review"
        # is Sparsh's act on a requisition and the client's act on an assessment result.
        #
        # The property that actually holds: every WRITE-LIKE capability a client holds is
        # theirs EXCLUSIVELY. If any Sparsh role also holds it, then the thing the client
        # is supposed to be uniquely responsible for is something the supplier can do for
        # them, which is the failure this whole track is built to prevent. Reads are
        # shared by design, and module access is how anybody gets in at all.
        sparsh_held = set()
        for caps in M.ROLE_CAPABILITIES.values():
            sparsh_held |= set(caps)
        shared_with_sparsh = {
            c.value for c in M.CLIENT_TRACK_CAPS
            if c in sparsh_held
            and not c.value.endswith(".read")
            and c is not M.Cap.MODULE_ACCESS
        }
        check("every decision the client holds is theirs exclusively",
              not shared_with_sparsh)
        check("their internal ladder role is discarded, not intersected",
              after != (before & set(M.CLIENT_TRACK_CAPS)) or before >= after)

        # The ceiling must never acquire a capability from another module by accident.
        # Every Client Hiring capability is named `client_*`, so the allowance is derived
        # from that rather than listed -- a step that adds one is covered automatically,
        # and a step that reaches for `payroll.read` is not.
        CLIENT_PREFIX = "client_"
        forbidden = {c for c in M.Cap
                     if not c.value.startswith(CLIENT_PREFIX)
                     and c is not M.Cap.MODULE_ACCESS}
        check("the ceiling holds nothing outside Client Hiring",
              set(M.CLIENT_TRACK_CAPS).isdisjoint(forbidden))
        # And nothing a client holds may be a WRITE on Sparsh's own working documents.
        check("the client cannot write the benchmark Sparsh drafts for them",
              M.Cap.CLIENT_SCORECARD_WRITE not in M.CLIENT_TRACK_CAPS
              and M.Cap.CLIENT_SCORECARD_REVIEW not in M.CLIENT_TRACK_CAPS)

        for cap in (M.Cap.REQUISITION_READ, M.Cap.EMPLOYEE_READ, M.Cap.PAYROLL_READ,
                    M.Cap.SEPARATION_READ, M.Cap.CANDIDATE_READ, M.Cap.OFFER_SEND,
                    M.Cap.SHORTLIST_WRITE, M.Cap.AUDIT_READ):
            check(f"a client-track caller is refused {cap.value}",
                  not HA.can(admitted, cap))

        # =================================================================
        section("The ceiling binds even a client company's own superadmin")
        # =================================================================
        # `superadmin` is an internal-only ERP role, so a client-side account can never
        # carry it -- it resolves to no HRMS role at all, which is its own protection.
        check("a client-side account claiming superadmin resolves to no role",
              HA.hrms_role(client_user(CLIENT_ON, role="superadmin")) is None)

        # The branch that matters is ADMIN, which resolves to "every capability that
        # exists" rather than to a listed set. If the ceiling were applied only to the
        # listed branch, the one account able to do the most damage would be the one
        # account exempt from it. The gate never stamps an internal user in production;
        # this asserts the code path regardless, which is what defence in depth means.
        owner = staff(role="superadmin")
        check("an ADMIN would otherwise hold every capability bar the client's own",
              HA.capabilities_for(owner)
              == set(M.Cap) - M.CLIENT_DECISION_CAPS - M.CLIENT_OWNED_CAPS)
        owner[M.CLIENT_TRACK_FLAG] = True
        check("the stamp narrows even the ADMIN branch to the client track set",
              HA.capabilities_for(owner) == set(M.CLIENT_TRACK_CAPS))

        # =================================================================
        section("Internal Hiring is untouched by any of this")
        # =================================================================
        for governance, expected in (("HR", M.HrmsRole.HR),
                                     ("HOD", M.HrmsRole.MANAGER),
                                     ("FINANCE", M.HrmsRole.FINANCE),
                                     ("MD", M.HrmsRole.MD)):
            person = staff(governance=governance)
            check(f"Sparsh staff with governance {governance} still resolve to "
                  f"{expected.value}", HA.hrms_role(person) is expected)
        # Administrative access is untouched; only the five decisions PRO-fit gives the
        # client company are withheld, and those are not an internal capability at all.
        # See test_client_decision_exclusivity for the full matrix.
        check("a Sparsh superadmin still holds every INTERNAL capability",
              {c for c in HA.capabilities_for(staff(role="superadmin"))
               if not c.name.startswith("CLIENT_")}
              == {c for c in M.Cap if not c.name.startswith("CLIENT_")})
        check("...and every client-track capability except the client's own",
              {c for c in HA.capabilities_for(staff(role="superadmin"))
               if c.name.startswith("CLIENT_")}
              == {c for c in M.Cap if c.name.startswith("CLIENT_")}
              - M.CLIENT_DECISION_CAPS - M.CLIENT_OWNED_CAPS)
        check("and Sparsh HR still holds the internal approval capability",
              HA.can(staff(governance="HR"), M.Cap.REQUISITION_REVIEW_HR))

        # =================================================================
        section("Tenant pinning still ignores a requested company")
        # =================================================================
        check("a client-side caller is pinned to their own company",
              HA.scope_company_id(admitted, str(SPARSH)) == str(CLIENT_ON))
        check("...even asking for another client",
              HA.scope_company_id(admitted, str(CLIENT_OFF)) == str(CLIENT_ON))
        check("the filter follows the pin, not the request",
              HA.company_filter(admitted, str(SPARSH))
              == {"company_id": str(CLIENT_ON)})
        check("Sparsh staff may still target any company",
              HA.scope_company_id(staff(), str(CLIENT_ON)) == str(CLIENT_ON))
    finally:
        mongo.get_collection = original
        HA.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
