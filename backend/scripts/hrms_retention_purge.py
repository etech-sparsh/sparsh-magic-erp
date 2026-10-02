"""Propose a record-retention purge for one company (HRMS, SOP §13).

`retention_until` has been stamped on HRMS records since the internal recruitment track
shipped, and nothing has ever deleted. This script is the first half of the job that does.

Since Phase INT-3 it is no longer the ONLY thing that proposes: `hrms_scheduler_service`
runs the same proposal weekly, so a company that never runs this script still sees eligible
records surface. This remains the ad-hoc path -- run it to look, on a date you choose,
without waiting for the sweep.

Neither path executes. Both stop at a proposal, and the automatic one is deliberately
gated the same way: no batch is written when nothing is eligible, and none is written while
an earlier batch is still awaiting a decision.

-- What this script does, and does not do -----------------------------------------------
It PROPOSES. It builds the list of records whose retention period has expired and writes it
to `hrms_purge_batches` as a batch awaiting approval. It never deletes, never redacts and
never touches a candidate record.

Execution happens elsewhere and by a person:

    POST /api/hrms/purge-batches/{batch_no}/approve

which requires the `retention.purge` capability (the MD alone) and a typed signature -- the
same standard probation confirmation holds, because both destroy or end something.

-- --dry-run is the DEFAULT ---------------------------------------------------------------
Running this with no flags prints the proposal and writes nothing at all, not even the
batch. You have to ask for a batch with `--propose`. That ordering is the point: looking
should be free, and the first thing anybody does with a purge tool is look.

-- --company is REQUIRED -------------------------------------------------------------------
There is no "all companies" mode and there will not be one. Retention is a decision each
business takes with its own auditors, and a script that could sweep every tenant in one
invocation is a script that will eventually be run that way by accident.

-- What is never proposed ------------------------------------------------------------------
  * anything with no `retention_until` -- an absent date means nobody computed one, which is
    a gap to investigate rather than a licence to delete;
  * anything attached to an OPEN requisition;
  * anything belonging to somebody still employed;
  * anything already purged.

-- Redaction, not deletion -------------------------------------------------------------------
When the batch is executed it CLEARS the personal fields and keeps the id, stamping
`purged_at` and the batch number. Every HRMS record is referenced by at least an audit row,
and an audit trail full of dangling references proves nothing. The stamp is what lets a
later reader tell "we purged this, under this approval" from "we lost this".

Usage (from backend/):
    python scripts/hrms_retention_purge.py --company <company_id>              # dry run
    python scripts/hrms_retention_purge.py --company <company_id> --propose    # write it
    python scripts/hrms_retention_purge.py --company <company_id> --as-of 2026-01-01
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
        description="Propose an HRMS record-retention purge (SOP section 13).")
    parser.add_argument(
        "--company", required=True,
        help="The company to evaluate. REQUIRED -- there is deliberately no all-companies "
             "mode; retention is a decision each business takes with its own auditors.")
    parser.add_argument(
        "--as-of", default=None, metavar="YYYY-MM-DD",
        help="Evaluate retention as at this date instead of today. Useful for checking "
             "what a purge run next quarter would cover.")
    parser.add_argument(
        "--propose", action="store_true",
        help="WRITE the proposal to hrms_purge_batches so it can be approved. Without this "
             "the script prints what it found and writes nothing.")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help=argparse.SUPPRESS)      # the default; --propose is what turns it off
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    from app.db.mongodb import connect_to_mongo, close_mongo_connection
    from app.models.hrms import is_iso_date
    from app.services import hrms_purge_service as purge

    if args.as_of and not is_iso_date(args.as_of):
        print(f"ERROR: --as-of must be a valid YYYY-MM-DD date (got {args.as_of!r}).")
        return 2

    await connect_to_mongo()
    try:
        # `dry_run` is the inverse of `--propose`, so the DEFAULT of this script is the safe
        # one and the destructive-adjacent path has to be asked for by name.
        dry_run = not args.propose
        result = await purge.propose(
            None, args.company, as_of=args.as_of, dry_run=dry_run)

        print()
        print("=" * 72)
        print(f"  HRMS retention purge proposal — company {args.company}")
        print("=" * 72)
        print(result["summary"])
        print()

        for group in result["groups"]:
            if not group["count"]:
                continue
            print(f'  {group["collection"]}  ({group["count"]} record(s), '
                  f'{group["mode"]})')
            # The first twenty ids, so the operator can eyeball the shape without a wall of
            # text. The written batch holds every one of them.
            shown = group["ids"][:20]
            for identifier in shown:
                print(f"      {identifier}")
            if len(group["ids"]) > len(shown):
                print(f'      ... and {len(group["ids"]) - len(shown)} more')
            print()

        if dry_run:
            print("DRY RUN — nothing was written. Re-run with --propose to record this "
                  "batch for approval.")
        else:
            print(f'Batch {result["batch_no"]} recorded, awaiting approval.')
            print()
            print("  Nothing has been deleted or redacted. To carry it out, somebody "
                  "holding")
            print("  `retention.purge` (the MD) must approve it with a typed signature:")
            print()
            print(f'      POST /api/hrms/purge-batches/{result["batch_no"]}/approve')
            print()
            print("  That call redacts the personal fields and keeps the ids and the audit")
            print("  trail. It is not reversible.")
        print()
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
