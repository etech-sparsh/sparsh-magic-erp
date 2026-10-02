"""Stamp `retention_until` on records created before anything stamped it (SOP §13).

`retention_until` is the field the purge selects on, and until now almost nothing wrote it:
it was set on the talent-pool paths only. A hand-added CV, a public application, an offer
and a closed requisition all carried no disposal date, and the purge deliberately proposes
nothing for a row without one -- so the retention policy applied to a small fraction of the
records it was written for.

Records created from now on are stamped where they are created. This script is for the ones
already in the database.

-- What it computes -----------------------------------------------------------------------
Exactly what the services now compute, from the same helpers and the same per-company
config, so a backfilled row is indistinguishable from one stamped at creation:

    candidates    joined  -> `candidate_selected` years from joined_at (or joining date)
                  others  -> `candidate_unselected` years from applied_at / created_at
    offers                -> `offer` years from the offer's created_at
    requisitions  closed  -> `requisition` years from closed_at / updated_at
                  open    -> skipped: retention runs from CLOSURE, and this one has not

`joined_at` is backfilled too, from the onboarding record's joining date where one exists,
because it is the anchor the selected period runs from and it was never written either.

-- --report is the DEFAULT -----------------------------------------------------------------
No flags counts what is missing and writes nothing. `--apply` writes.

-- --company is REQUIRED --------------------------------------------------------------------
Retention is a per-business decision, and the sibling scripts follow the same rule. There is
no all-tenants mode.

-- It never shortens anything ----------------------------------------------------------------
A row that already has a `retention_until` is left exactly as it is, even if this script
would compute a different date. Somebody may have set it deliberately, and a script that
silently brought a disposal date FORWARD would be destroying records early.

Usage (from backend/):
    python scripts/backfill_retention_until.py --company <company_id>
    python scripts/backfill_retention_until.py --company <company_id> --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill retention_until on HRMS records that never got one.")
    parser.add_argument("--company", required=True,
                        help="The company to backfill. REQUIRED -- no all-tenants mode.")
    parser.add_argument("--apply", action="store_true",
                        help="WRITE the dates. Without this the script only counts.")
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.models.hrms import (
        COLL_CANDIDATES, COLL_OFFERS, COLL_ONBOARDING, COLL_REQUISITIONS, ReqClosing,
    )
    from app.services.hrms_candidate_service import _add_years, candidate_retention_until
    from app.services.hrms_config_service import config_for, retention_years_for

    company = str(args.company)
    await connect_to_mongo()
    try:
        years_map = (await config_for(company))["retention_years"]
        planned = {"candidates": [], "offers": [], "requisitions": []}
        joined_backfill = []

        # ── candidates ────────────────────────────────────────────────
        # Joining dates come from the onboarding records, read once rather than per CV.
        onboardings = await get_collection(COLL_ONBOARDING).find(
            {"company_id": company}, {"uk": 1, "joining_date": 1}).to_list(20000)
        joining_by_uk = {o["uk"]: o.get("joining_date")
                         for o in onboardings if o.get("uk")}

        candidates = await get_collection(COLL_CANDIDATES).find(
            {"company_id": company,
             "$or": [{"retention_until": None}, {"retention_until": {"$exists": False}}]}
        ).to_list(50000)
        for row in candidates:
            merged = dict(row)
            # Give the selected branch its anchor before asking for the floor: without
            # joined_at a joiner is measured from their application, which is the shorter
            # UNSELECTED period -- the inversion this backfill exists to correct.
            if not merged.get("joined_at") and joining_by_uk.get(row.get("uk")):
                merged["joined_at"] = joining_by_uk[row["uk"]]
                joined_backfill.append((row["uk"], joining_by_uk[row["uk"]]))
            until = candidate_retention_until(merged, years_map)
            if until:
                planned["candidates"].append((row["uk"], until))

        # ── offers ────────────────────────────────────────────────────
        offer_years = await retention_years_for(company, "offer")
        offers = await get_collection(COLL_OFFERS).find(
            {"company_id": company,
             "$or": [{"retention_until": None}, {"retention_until": {"$exists": False}}]}
        ).to_list(50000)
        for row in offers:
            anchor = row.get("created_at")
            if hasattr(anchor, "strftime"):
                anchor = anchor.strftime("%Y-%m-%d")
            if anchor:
                planned["offers"].append(
                    (row["offer_no"], _add_years(str(anchor)[:10], offer_years)))

        # ── requisitions ──────────────────────────────────────────────
        req_years = await retention_years_for(company, "requisition")
        reqs = await get_collection(COLL_REQUISITIONS).find(
            {"company_id": company,
             "closing_status": {"$ne": ReqClosing.OPEN.value},
             "$or": [{"retention_until": None}, {"retention_until": {"$exists": False}}]}
        ).to_list(50000)
        skipped_open = await get_collection(COLL_REQUISITIONS).count_documents(
            {"company_id": company, "closing_status": ReqClosing.OPEN.value})
        for row in reqs:
            anchor = row.get("closed_at") or row.get("updated_at")
            if hasattr(anchor, "strftime"):
                anchor = anchor.strftime("%Y-%m-%d")
            if anchor:
                planned["requisitions"].append(
                    (row["request_no"], _add_years(str(anchor)[:10], req_years)))

        print()
        print("=" * 72)
        print(f"  retention_until backfill -- company {company}")
        print("=" * 72)
        for name in ("candidates", "offers", "requisitions"):
            print(f"  {name:<14} {len(planned[name])} to stamp")
        print(f"  joined_at      {len(joined_backfill)} to backfill from onboarding")
        if skipped_open:
            print(f"  ({skipped_open} open requisition(s) skipped -- retention runs from "
                  f"closure)")
        print()
        for name in ("candidates", "offers", "requisitions"):
            for identifier, until in planned[name][:10]:
                print(f"    {identifier:<22} -> {until}")
            if len(planned[name]) > 10:
                print(f"    ... and {len(planned[name]) - 10} more {name}")
        print()

        total = sum(len(v) for v in planned.values())
        if not total and not joined_backfill:
            print("Nothing to do -- every record already carries a retention date.")
            return 0
        if not args.apply:
            print("REPORT ONLY -- nothing was written. Re-run with --apply.")
            return 0

        written = 0
        for uk, joined in joined_backfill:
            await get_collection(COLL_CANDIDATES).update_one(
                {"uk": uk, "company_id": company}, {"$set": {"joined_at": joined}})
        for uk, until in planned["candidates"]:
            # The filter repeats the "still empty" condition, so a row stamped by the live
            # code between the read above and this write is not overwritten.
            r = await get_collection(COLL_CANDIDATES).update_one(
                {"uk": uk, "company_id": company,
                 "$or": [{"retention_until": None},
                         {"retention_until": {"$exists": False}}]},
                {"$set": {"retention_until": until}})
            written += int(r.modified_count or 0)
        for offer_no, until in planned["offers"]:
            r = await get_collection(COLL_OFFERS).update_one(
                {"offer_no": offer_no, "company_id": company,
                 "$or": [{"retention_until": None},
                         {"retention_until": {"$exists": False}}]},
                {"$set": {"retention_until": until}})
            written += int(r.modified_count or 0)
        for request_no, until in planned["requisitions"]:
            r = await get_collection(COLL_REQUISITIONS).update_one(
                {"request_no": request_no, "company_id": company,
                 "$or": [{"retention_until": None},
                         {"retention_until": {"$exists": False}}]},
                {"$set": {"retention_until": until}})
            written += int(r.modified_count or 0)

        print(f"Stamped {written} record(s); backfilled {len(joined_backfill)} joined_at.")
        print("Run scripts/hrms_retention_purge.py --company <id> to see what is now "
              "eligible. It proposes only; an MD approves.")
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
