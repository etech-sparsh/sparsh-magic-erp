"""Phase INT-16 — administering HRMS when the module is switched off everywhere.

The reported symptom: switch HRMS off for every company and the module breaks for Sparsh
staff too, with `400 Select a company to work with` on every screen.

The cause was never the gate. `ensure_hrms_enabled` has always let internal staff through --
they administer the module -- but the company SELECTOR was filtered by the same toggle, so
with everything off they landed inside HRMS with an empty dropdown and no way to pick the
company their own data lives in.

What this file pins is the pair of properties that have to hold TOGETHER, because fixing the
first one carelessly breaks the second:

  1. Internal staff can always reach the company that holds the HRMS records, toggle or no
     toggle -- otherwise Sparsh Magic's own internal hiring becomes unadministrable.
  2. The fallback is NOT a way in. A client-side user of a switched-off company is still
     refused, which is the only thing the toggle was ever for.

Run:  python -m app.services.hrms.tests.test_int16_module_off
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

    import app.db.mongodb as mongo
    import app.utils.hrms_access as ACCESS
    import app.routes.hrms as ROUTES
    from app.models import hrms as M

    OPERATOR = str(ObjectId())      # the in-house company -- the one HRMS tenant
    CLIENT_CO = str(ObjectId())     # a client organisation, no HRMS records of its own
    EMPTY_CO = str(ObjectId())      # a company that has never touched HRMS

    # `is_internal` marks the single company the ERP is operated in-house by. HRMS needs
    # BOTH it and `hrms_enabled`, so a client company cannot be switched into the module
    # -- see utils/hrms_access.is_hrms_enabled. Only the operator carries it.
    companies = FakeCollection([
        {"_id": ObjectId(OPERATOR), "name": "People to Process", "hrms_enabled": False,
         "is_internal": True},
        {"_id": ObjectId(CLIENT_CO), "name": "Acme Manufacturing", "hrms_enabled": False,
         "is_internal": False},
        {"_id": ObjectId(EMPTY_CO), "name": "Unrelated Co", "hrms_enabled": False,
         "is_internal": False},
    ])
    # The operator owns the records. A client is named INSIDE a requisition's `client_id`,
    # never as its `company_id` -- which is why reading the data cannot mistake one for the
    # other, and this fixture says so explicitly.
    requisitions = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": OPERATOR,
         "requisition_track": "internal", "client_id": None},
        {"request_no": "HR-REQ-2026-002", "company_id": OPERATOR,
         "requisition_track": "client", "client_id": CLIENT_CO},
    ])
    profiles = FakeCollection([
        {"employee_code": "EMP-001", "company_id": OPERATOR},
    ])

    store = {
        "companies": companies,
        "hrms_requisitions": requisitions,
        "hrms_employee_profiles": profiles,
        "hrms_settings": FakeCollection(),
        "hrms_client_engagements": FakeCollection(),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    ACCESS.get_collection = mongo.get_collection

    def staff(role="admin"):
        return {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
                "company_id": None}

    def client_side(company_id):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company_id}

    try:
        # =================================================================
        section("Nothing is enabled -- which is the reported state")
        # =================================================================
        check("no company has the module switched on",
              await ACCESS.hrms_enabled_company_ids() == set())
        tenants = await ACCESS.hrms_tenant_company_ids()
        check("but the operator is found by its RECORDS, not by a flag",
              tenants == {OPERATOR})
        check("a client company is NOT mistaken for the operator",
              CLIENT_CO not in tenants)
        check("nor is a company that never used HRMS", EMPTY_CO not in tenants)

        # =================================================================
        section("Internal staff can still administer the module")
        # =================================================================
        listed = await ROUTES.hrms_companies(staff())
        rows = listed["companies"]
        check("the selector is no longer empty", len(rows) == 1)
        check("it offers the company the HRMS data actually lives in",
              rows[0]["id"] == OPERATOR)
        check("and says plainly that the module is off there",
              rows[0]["hrms_enabled"] is False)
        check("internal staff pass the module gate, as they always did",
              await ACCESS.ensure_hrms_enabled(staff()) is None)
        # The 400 the whole bug reduced to: a company to work in now exists, so the scope
        # resolves and every endpoint below it has something to scope BY.
        check("a company id can now be resolved for the request",
              ROUTES._company(staff(), rows[0]["id"]) == OPERATOR)

        # =================================================================
        section("The fallback is NOT a way in")
        # =================================================================
        await expect_http(
            "a user of the switched-off OPERATOR company",
            ACCESS.ensure_hrms_enabled(client_side(OPERATOR)), 403)
        await expect_http(
            "a client contact whose engagement is in a switched-off tenant",
            ACCESS.ensure_hrms_enabled(client_side(CLIENT_CO)), 403)
        client_list = await ROUTES.hrms_companies(client_side(CLIENT_CO))
        check("a client-side user's selector still shows only their own company",
              [r["id"] for r in client_list["companies"]] == [CLIENT_CO])

        # =================================================================
        section("Switching one back on restores normal behaviour")
        # =================================================================
        await companies.update_one({"_id": ObjectId(OPERATOR)},
                                   {"$set": {"hrms_enabled": True}})
        check("the enabled list is the source of truth again",
              await ACCESS.hrms_enabled_company_ids() == {OPERATOR})
        back = await ROUTES.hrms_companies(staff())
        check("the selector reports the module as ON",
              back["companies"][0]["hrms_enabled"] is True)
        # HRMS is an IN-HOUSE system: it recruits this company's own staff. A user of a
        # client company is refused even while the operator has the module ON.
        await expect_http(
            "a client-company user is refused even so -- HRMS is not for clients",
            ACCESS.ensure_hrms_enabled(client_side(CLIENT_CO)), 403)

        # With a company enabled, the fallback must NOT widen the list: a company holding
        # records but switched off is no longer offered, because there is now a real answer.
        await requisitions.insert_one(
            {"request_no": "HR-REQ-2026-003", "company_id": EMPTY_CO,
             "requisition_track": "internal"})
        narrowed = await ROUTES.hrms_companies(staff())
        check("the enabled list WINS -- the fallback only fires when it is empty",
              [r["id"] for r in narrowed["companies"]] == [OPERATOR])

    finally:
        mongo.get_collection = original
        ACCESS.get_collection = original

    print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed")
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
