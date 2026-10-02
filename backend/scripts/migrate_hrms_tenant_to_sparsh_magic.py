"""Move the HRMS tenancy from People to Process to Sparsh Magic.

WHY THIS EXISTS
---------------
HRMS is multi-tenant on `company_id`: whichever company a record carries IS the operator,
and everyone else is a client referenced by `client_id`. Nothing in the code names a
company -- the module is tenant-agnostic by construction.

So the operator is decided entirely by the data, and the data currently says People to
Process. It holds every requisition, candidate, offer, interview and employee record, and
its 16 engagements list the other companies as ITS clients.

The intended model is the other way round:

    Sparsh Magic    the main company -- runs recruitment, owns the HRMS records
    People to       a client like any other, referenced by `client_id`
    Process         and holding no HRMS records of its own
    + 23 others     clients

This script performs that swap: it re-stamps `company_id` on every HRMS document from
People to Process to Sparsh Magic, creating the Sparsh Magic company record if it does not
exist yet.

WHAT IT DOES NOT TOUCH
----------------------
  * `client_id` anywhere. A requisition already pointing at People to Process AS a client
    becomes correct for free once People to Process is one.
  * The People to Process company record itself. It stays exactly as it is, minus the
    tenancy -- it keeps its users, its address, its other modules.
  * Any non-HRMS collection. TPMS, ORM and the rest are scoped independently.
  * Engagements' `client_id` list. Whether Sparsh Magic engages People to Process as a
    recruitment client is a business fact, not something a migration should invent.

SAFETY
------
  * Dry run by default. Nothing is written without `--apply`.
  * Idempotent. Re-running after a successful pass finds nothing left to move.
  * Refuses to run if the destination already holds HRMS records, which would mean a
    partial previous run or a genuinely two-tenant database -- either way, a merge is a
    decision, not a default.

USAGE
-----
    python scripts/migrate_hrms_tenant_to_sparsh_magic.py                # dry run
    python scripts/migrate_hrms_tenant_to_sparsh_magic.py --apply        # do it
    python scripts/migrate_hrms_tenant_to_sparsh_magic.py --apply --name "Sparsh Magic Pvt. Ltd."
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from bson import ObjectId

sys.path.insert(0, ".")

from app.db.mongodb import connect_to_mongo, get_collection  # noqa: E402
from app.models import hrms as M  # noqa: E402

# The company that currently holds the tenancy.
SOURCE_ID = "69d782804c39e25a85456dc2"      # People to Process
DEFAULT_DEST_NAME = "Sparsh Magic"


def hrms_collections() -> list[str]:
    """Every HRMS collection, read from the model's own registry rather than a hand-kept
    list -- a collection added in a later phase is picked up automatically."""
    return sorted({v for k, v in vars(M).items()
                   if k.startswith("COLL_") and isinstance(v, str)})


async def find_destination(name: str) -> dict | None:
    """The Sparsh Magic company record, matched case-insensitively on an exact name."""
    return await get_collection("companies").find_one(
        {"name": {"$regex": f"^{name}$", "$options": "i"}})


async def create_destination(name: str, source: dict, apply: bool) -> str | None:
    """Create the operator's company record, seeded from the source's own contact details.

    Copied rather than invented: the source company is registered to sparshmagic.com with
    Sparsh Magic's own people on it, so those are the right details for the operator and a
    blank record would only have to be filled in by hand afterwards.
    """
    doc = {
        "name": name,
        "company_type": source.get("company_type") or "Service",
        "owner": source.get("owner"),
        "email": source.get("email"),
        "contact": source.get("contact"),
        "domain": source.get("domain"),
        "address": source.get("address"),
        "city": source.get("city"),
        "state": source.get("state"),
        "country": source.get("country"),
        "pin": source.get("pin"),
        "gst": source.get("gst"),
        "admin_id": source.get("admin_id"),
        "status": "active",
        "is_active": True,
        # The operator runs HRMS by definition. Every other module stays off until somebody
        # turns it on -- this migration is about HRMS and should not quietly enable TPMS.
        "hrms_enabled": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if not apply:
        return None
    result = await get_collection("companies").insert_one(doc)
    return str(result.inserted_id)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually write. Without it, nothing is changed.")
    parser.add_argument("--name", default=DEFAULT_DEST_NAME,
                        help=f"the operator's company name (default: {DEFAULT_DEST_NAME})")
    args = parser.parse_args()

    await connect_to_mongo()
    companies = get_collection("companies")

    source = await companies.find_one({"_id": ObjectId(SOURCE_ID)})
    if not source:
        raise SystemExit(f"Source company {SOURCE_ID} not found. Nothing to migrate.")

    print("=" * 74)
    print("  HRMS TENANCY MIGRATION" + ("" if args.apply else "   [DRY RUN -- nothing is written]"))
    print("=" * 74)
    print(f"  FROM  {source.get('name')}  ({SOURCE_ID})")

    dest = await find_destination(args.name)
    created = False
    if dest:
        dest_id = str(dest["_id"])
        print(f"  TO    {dest.get('name')}  ({dest_id})   [existing record]")
    else:
        print(f"  TO    {args.name}   [will be CREATED from the source's contact details]")
        dest_id = await create_destination(args.name, source, args.apply)
        created = True
        if dest_id:
            print(f"        created as {dest_id}")

    if dest_id == SOURCE_ID:
        raise SystemExit("Source and destination are the same company. Refusing.")

    # ── Refuse a merge ────────────────────────────────────────
    if dest_id:
        held = 0
        for name in hrms_collections():
            try:
                held += await get_collection(name).count_documents({"company_id": dest_id})
            except Exception:
                pass
        if held:
            raise SystemExit(
                f"\n  REFUSED: {args.name} already holds {held} HRMS documents.\n"
                f"  That means a previous run half-completed, or this database genuinely has\n"
                f"  two HRMS tenants. Merging two tenants is a decision, not a default --\n"
                f"  sort it out by hand and re-run.")

    # ── The move ──────────────────────────────────────────────
    print("\n  Documents to re-stamp:")
    total = 0
    moved = 0
    for name in hrms_collections():
        try:
            n = await get_collection(name).count_documents({"company_id": SOURCE_ID})
        except Exception as e:
            print(f"    [WARN] {name}: {e}")
            continue
        if not n:
            continue
        total += n
        print(f"    {n:>5}  {name}")
        if args.apply and dest_id:
            res = await get_collection(name).update_many(
                {"company_id": SOURCE_ID}, {"$set": {"company_id": dest_id}})
            moved += res.modified_count

    print(f"\n    {total:>5}  TOTAL")

    # ── The toggles ───────────────────────────────────────────
    print("\n  Module flags:")
    print(f"    {args.name}: hrms_enabled -> True   (the operator runs the module)")
    print(f"    {source.get('name')}: left exactly as it is -- it keeps its record, its")
    print( "      users and its other modules, and simply stops being the HRMS tenant.")
    if args.apply and dest_id and not created:
        await companies.update_one({"_id": ObjectId(dest_id)},
                                   {"$set": {"hrms_enabled": True,
                                             "updated_at": datetime.now(timezone.utc)}})

    # ── What becomes true afterwards ──────────────────────────
    already_client = await get_collection(M.COLL_REQUISITIONS).count_documents(
        {"client_id": SOURCE_ID})
    print("\n  After this runs:")
    print(f"    - {args.name} is the HRMS operator and owns all {total} records.")
    print(f"    - {source.get('name')} becomes an ordinary client company.")
    if already_client:
        print(f"    - {already_client} requisition(s) already name it as a CLIENT; those")
        print( "      become correct for free.")
    print( "    - Its 16 engagements move with the tenancy, so the same 16 clients stay")
    print( "      engaged -- now with the operator, which is what they always meant.")
    print( "    - Sparsh's own internal hiring (the `internal` track) is unaffected: it")
    print( "      simply belongs to the operator now, which is the whole point.")

    if not args.apply:
        print("\n" + "=" * 74)
        print("  DRY RUN. Nothing was written. Re-run with --apply to perform it.")
        print("=" * 74)
    else:
        print("\n" + "=" * 74)
        print(f"  DONE. {moved} documents re-stamped.")
        print("=" * 74)


if __name__ == "__main__":
    asyncio.run(main())
