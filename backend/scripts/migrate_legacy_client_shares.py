"""Convert the legacy embedded `client_share` into `hrms_candidate_shares` rows.

-- What the old model was, and why it had to change -------------------------------------------
Before Phase 12 a CV shared with a client was recorded as ONE sub-document on the candidate:

    candidate.client_share = {shared_at, shared_by, shared_by_name, status, remarks, ...}

One sub-document means one client, ever. It also never stored WHICH client -- there was no
need, because a candidate could only be shared with the client on their requisition.

Phase 12 replaced it with a row per (candidate, client), so the same CV can go to several
clients and each carries its own status. The new CV-sharing board reads that collection, which
leaves the old records invisible: the history exists, and nothing shows it.

This script moves them across.

-- Where the client id comes from ---------------------------------------------------------------
The one piece the old model never held. It is taken from the candidate's REQUISITION, which is
where it always implicitly was -- an agency requisition names the client it is being filled
for. A candidate whose requisition names no client cannot be migrated and is reported rather
than guessed at; inventing a client for somebody's CV is exactly the kind of repair that is
worse than the gap.

-- Status mapping -------------------------------------------------------------------------------
    Pending      -> CV Shared      (the client has it; no verdict yet)
    Shortlisted  -> Shortlisted
    Rejected     -> Rejected
    On Hold      -> Under Review   (they have it and have not decided; the new model has no
                                    parked state, and Under Review is the honest reading)

-- Idempotent, and non-destructive ---------------------------------------------------------------
A candidate that already has a share row for that client is skipped, so a second run changes
nothing. The old `client_share` sub-document is LEFT IN PLACE: the analytics service still
reads it for historical figures, and deleting the source of a migration on the same pass is how
you discover the mapping was wrong with nothing to go back to. Removing it is a later, separate
decision.

Every migrated row carries `migrated_from: "client_share"` so what this script created is
identifiable for ever -- and reversible.

Usage (from backend/):
    python scripts/migrate_legacy_client_shares.py --company <company_id>
    python scripts/migrate_legacy_client_shares.py --company <company_id> --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Old ClientShareStatus -> new ShareStatus. Declared as data so the mapping is reviewable
# without reading the loop that applies it.
STATUS_MAP = {
    "Pending":     "CV Shared",
    "Shortlisted": "Shortlisted",
    "Rejected":    "Rejected",
    "On Hold":     "Under Review",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate legacy client_share sub-documents into candidate share rows.")
    parser.add_argument("--company", required=True,
                        help="The company to migrate. REQUIRED -- no all-tenants mode.")
    parser.add_argument("--apply", action="store_true",
                        help="WRITE the share rows. Without this the script only reports.")
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.models.hrms import (
        AUDIT_SHARE_CREATED, COLL_CANDIDATE_SHARES, COLL_CANDIDATES, COLL_REQUISITIONS,
        ShareStatus,
    )
    from app.services.hrms_id_service import next_business_id
    from app.services.hrms_share_service import build_snapshot

    company = str(args.company)
    await connect_to_mongo()
    try:
        candidates = await get_collection(COLL_CANDIDATES).find(
            {"company_id": company,
             "client_share.shared_at": {"$exists": True}}).to_list(5000)
        if not candidates:
            print("Nothing to migrate: no candidate carries a legacy client_share.")
            return 0

        # Requisitions read once, not per candidate.
        request_nos = sorted({c["request_no"] for c in candidates if c.get("request_no")})
        reqs = await get_collection(COLL_REQUISITIONS).find(
            {"company_id": company, "request_no": {"$in": request_nos}},
            {"request_no": 1, "client_id": 1, "client_name": 1}).to_list(5000)
        by_req = {r["request_no"]: r for r in reqs}

        existing = await get_collection(COLL_CANDIDATE_SHARES).find(
            {"company_id": company}, {"uk": 1, "client_id": 1}).to_list(20000)
        already = {(e["uk"], e["client_id"]) for e in existing}

        planned, skipped, orphaned = [], [], []
        for cand in candidates:
            share = cand.get("client_share") or {}
            req = by_req.get(cand.get("request_no") or "")
            client_id = (req or {}).get("client_id")
            if not client_id:
                orphaned.append((cand["uk"], cand.get("request_no") or "(none)"))
                continue
            if (cand["uk"], str(client_id)) in already:
                skipped.append(cand["uk"])
                continue
            old_status = share.get("status") or "Pending"
            planned.append({
                "candidate": cand,
                "share": share,
                "client_id": str(client_id),
                "client_name": (req or {}).get("client_name"),
                "old_status": old_status,
                "new_status": STATUS_MAP.get(old_status, ShareStatus.CV_SHARED.value),
            })

        print()
        print("=" * 72)
        print(f"  Legacy client_share migration -- company {company}")
        print("=" * 72)
        print(f"  candidates carrying a legacy share : {len(candidates)}")
        print(f"  to migrate                         : {len(planned)}")
        if skipped:
            print(f"  already migrated (skipped)         : {len(skipped)}")
        if orphaned:
            print(f"  CANNOT migrate (no client named)   : {len(orphaned)}")
        print()
        if planned:
            counts = {}
            for p in planned:
                key = f'{p["old_status"]} -> {p["new_status"]}'
                counts[key] = counts.get(key, 0) + 1
            print("  status mapping:")
            for key in sorted(counts):
                print(f"      {key:34} {counts[key]}")
            no_cv = sum(1 for p in planned
                        if not (p["candidate"].get("resume") or {}).get("key"))
            if no_cv:
                print(f"\n  {no_cv} of these have no CV on file. Migrated anyway -- the share")
                print("  HAPPENED, and dropping the record because the document is missing")
                print("  would lose the history this migration exists to preserve.")
            print()
            for p in planned[:12]:
                print(f'      {p["candidate"]["uk"]:12} -> {str(p["client_name"])[:32]:34}'
                      f' {p["new_status"]}')
            if len(planned) > 12:
                print(f"      ... and {len(planned) - 12} more")
        for uk, rn in orphaned[:10]:
            print(f"      ORPHAN {uk} (requisition {rn} names no client)")
        print()

        if not planned:
            print("Nothing to do.")
            return 0
        if not args.apply:
            print("REPORT ONLY -- nothing was written. Re-run with --apply.")
            return 0

        written = 0
        shares = get_collection(COLL_CANDIDATE_SHARES)
        for p in planned:
            cand, share = p["candidate"], p["share"]
            shared_at = share.get("shared_at")
            year = getattr(shared_at, "year", None) or 2026
            share_no = await next_business_id("share", company, year)

            # The history the new model expects, rebuilt from what the old one recorded: the
            # share itself, and the verdict if one came back. Two entries, not one, so the
            # migrated row reads like a row that was always here.
            history = [{
                "status": ShareStatus.CV_SHARED.value,
                "at": shared_at,
                "by": share.get("shared_by"),
                "by_name": share.get("shared_by_name"),
                "remarks": share.get("remarks"),
            }]
            if p["new_status"] != ShareStatus.CV_SHARED.value:
                history.append({
                    "status": p["new_status"],
                    "at": share.get("responded_at") or shared_at,
                    "by": share.get("recorded_by") or share.get("shared_by"),
                    "by_name": share.get("shared_by_name"),
                    "remarks": share.get("remarks"),
                })

            doc = {
                "share_no": share_no,
                "company_id": company,
                "uk": cand["uk"],
                "candidate_name": cand.get("candidate_name"),
                "client_id": p["client_id"],
                "client_name": p["client_name"],
                "request_no": cand.get("request_no"),
                "status": p["new_status"],
                # Built by the SAME function new shares use, so a migrated row and a fresh
                # one expose exactly the same fields to a client. Contact withheld, matching
                # the default -- the old model never recorded a decision to disclose it.
                "snapshot": build_snapshot(cand, include_contact=False),
                "include_contact": False,
                "note": share.get("remarks"),
                "shared_at": shared_at,
                "shared_by": share.get("shared_by"),
                "shared_by_name": share.get("shared_by_name"),
                "responded_at": share.get("responded_at"),
                "history": history,
                "created_at": shared_at,
                "updated_at": shared_at,
                # The provenance stamp. Anything this script created stays identifiable, so
                # the migration can be audited or undone without guessing.
                "migrated_from": "client_share",
            }
            try:
                await shares.insert_one(doc)
                written += 1
            except Exception as e:
                print(f'      FAILED {cand["uk"]}: {e}')

        # One audit row for the migration as a whole. Not one per record: this was a single
        # operator decision, and 22 rows saying the same thing would bury the fact.
        from app.services.hrms_audit_service import audit
        await audit(None, AUDIT_SHARE_CREATED, "candidate share", "migration",
                    f"{written} legacy client_share record(s) migrated to "
                    f"hrms_candidate_shares", company)

        print(f"Migrated {written} share(s).")
        print("The legacy client_share sub-documents were left in place -- analytics still")
        print("reads them, and removing the source on the same pass is how a bad mapping")
        print("becomes unrecoverable. Verify the CV-sharing board, then decide separately.")
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
