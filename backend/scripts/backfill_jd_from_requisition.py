"""Fill in JD fields that were never carried over from their requisition.

-- What went wrong ------------------------------------------------------------------------
A requisition is raised together with its JD, and the two carry the same facts under
different names: `experience_required` / `experience`, `qualification` / `qualifications`,
`essential_skills` / `skills`, `offering_ctc` / `ctc`, `work_location` / `location`, plus
`employment_type` on both.

The raise form asked for those facts once, on the requisition, and never bound an input to
the JD half -- so every JD was stored with them empty, and `employment_type` took the
JD model's own default of Full-time regardless of what the requisition said. Only the
public advert papered over it, by falling back to the requisition on four of the six
fields; the JD library, the requisition drawer and the printable forms read the stored
document and showed blanks.

Requisitions raised from now on inherit at creation
(`hrms_requisition_service._seed_jd_from_requisition`). This script is for the ones already
in the database.

-- What it does ---------------------------------------------------------------------------
For each JD, reads its requisition and fills ONLY the fields the JD has left blank, using
exactly the same mapping the service now applies. A JD that was given its own wording keeps
every word of it: a non-empty field is never touched.

`employment_type` is the one field that needs care, because the old default means a stored
"Full-time" may be either a real choice or the default nobody set. `--employment-type`
turns on realigning it to the requisition, and it is OFF by default: on a database where
somebody did deliberately publish a full-time JD against a contract requisition, silently
flipping it would be the wrong call. Run without the flag first and read the counts.

-- --dry-run is the DEFAULT ----------------------------------------------------------------
No flags prints what would change and writes nothing. `--apply` is what writes.

-- --company is REQUIRED --------------------------------------------------------------------
Same rule the retention script follows: no all-tenants mode, so this cannot be pointed at
every company by accident.

Approved JDs ARE included. An approved JD is frozen against editing because its wording was
signed off; restoring facts that were only ever missing through a form defect is not a
rewording, and leaving a published advert blank helps nobody. `--pending-only` restricts the
run to JDs still awaiting approval if you would rather stage it that way.

Usage (from backend/):
    python scripts/backfill_jd_from_requisition.py --company <company_id>
    python scripts/backfill_jd_from_requisition.py --company <company_id> --apply
    python scripts/backfill_jd_from_requisition.py --company <company_id> --apply --employment-type
    python scripts/backfill_jd_from_requisition.py --company <company_id> --pending-only
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Run from backend/ or from anywhere: the package root is this file's grandparent.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill JD fields from the requisition they were raised with.")
    parser.add_argument(
        "--company", required=True,
        help="The company to backfill. REQUIRED -- there is deliberately no all-companies "
             "mode.")
    parser.add_argument(
        "--apply", action="store_true",
        help="WRITE the changes. Without this the script prints what it would do and "
             "writes nothing.")
    parser.add_argument(
        "--employment-type", action="store_true",
        help="Also realign employment_type to the requisition. Off by default because the "
             "old JD default was Full-time, so a stored Full-time cannot be told apart "
             "from a deliberate one.")
    parser.add_argument(
        "--pending-only", action="store_true",
        help="Only touch JDs that are not yet Approved.")
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.models.hrms import COLL_JOB_DESCRIPTIONS, COLL_REQUISITIONS, JdStatus
    from app.services.hrms_requisition_service import (
        JD_FROM_REQUISITION, _jd_ctc_from,
    )

    await connect_to_mongo()
    try:
        query = {"company_id": str(args.company)}
        if args.pending_only:
            query["status"] = {"$ne": JdStatus.APPROVED.value}

        jds = await get_collection(COLL_JOB_DESCRIPTIONS).find(query).to_list(10000)
        if not jds:
            print(f"No job descriptions found for company {args.company}.")
            return 0

        # One read for every requisition referenced, rather than one per JD.
        request_nos = sorted({j["request_no"] for j in jds if j.get("request_no")})
        reqs = await get_collection(COLL_REQUISITIONS).find(
            {"request_no": {"$in": request_nos}, "company_id": str(args.company)}
        ).to_list(10000)
        by_no = {r["request_no"]: r for r in reqs}

        # employment_type is handled separately from the plain text fields, because it is
        # the only one whose blank looked like a real value.
        text_map = [(jd_f, req_f) for jd_f, req_f in JD_FROM_REQUISITION
                    if jd_f != "employment_type"]

        planned, filled_counts, orphans = [], {}, 0
        for jd in jds:
            req = by_no.get(jd.get("request_no"))
            if not req:
                orphans += 1
                continue

            updates = {}
            for jd_field, req_field in text_map:
                if jd.get(jd_field):
                    continue
                inherited = req.get(req_field)
                if inherited not in (None, ""):
                    updates[jd_field] = getattr(inherited, "value", inherited)
            if not jd.get("ctc"):
                ctc = _jd_ctc_from(req)
                if ctc:
                    updates["ctc"] = ctc
            if args.employment_type:
                wanted = req.get("employment_type")
                if wanted and jd.get("employment_type") != wanted:
                    updates["employment_type"] = wanted

            if updates:
                planned.append((jd["jd_no"], jd.get("status"), updates))
                for key in updates:
                    filled_counts[key] = filled_counts.get(key, 0) + 1

        print()
        print("=" * 72)
        print(f"  JD backfill from requisition — company {args.company}")
        print("=" * 72)
        print(f"  job descriptions scanned : {len(jds)}")
        print(f"  needing a backfill       : {len(planned)}")
        if orphans:
            print(f"  skipped (no requisition) : {orphans}")
        print()
        if filled_counts:
            print("  fields to fill:")
            for key in sorted(filled_counts):
                print(f"      {key:<16} {filled_counts[key]}")
            print()

        shown = planned[:20]
        for jd_no, status, updates in shown:
            print(f'  {jd_no}  ({status})  <- {", ".join(sorted(updates))}')
        if len(planned) > len(shown):
            print(f"      ... and {len(planned) - len(shown)} more")
        print()

        if not planned:
            print("Nothing to do.")
            return 0

        if not args.apply:
            print("DRY RUN — nothing was written. Re-run with --apply to write these.")
            if not args.employment_type:
                print("Note: employment_type was NOT considered. Add --employment-type to "
                      "realign it to the requisition as well.")
            return 0

        written = 0
        for jd_no, _status, updates in planned:
            result = await get_collection(COLL_JOB_DESCRIPTIONS).update_one(
                {"jd_no": jd_no, "company_id": str(args.company)}, {"$set": updates})
            written += int(result.modified_count or 0)
        print(f"Wrote {written} job description(s).")
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
