"""
C8 — populate the new `governance_role` field on TPMS users.

The `department` field on client users is OVERLOADED: for most it holds a real org department
(Sales, IT, Accounts…), but for governance users it holds the escalation/form role
(HOD / MD / HR / IMPLEMENTOR). This migration lifts ONLY the governance-role values into a
dedicated `governance_role` field so escalation routing and form-audience gating can key on it,
leaving `department` free to hold the real org department.

Rules:
  • Non-destructive: only $set `governance_role`; `department` is never changed.
  • Selective: only users whose `department` (case-insensitive) is a governance role get a
    `governance_role`; org-department users are left as-is (they have no governance role).
  • Idempotent: users that already have a non-empty `governance_role` are skipped.

Usage (from backend/):
    python -m scripts.migrate_governance_role --dry-run   # preview
    python -m scripts.migrate_governance_role             # apply
"""
import asyncio
import sys

from app.db.mongodb import connect_to_mongo, get_collection

# department value (lowercased) → canonical governance role.
GOVERNANCE = {"hod": "HOD", "md": "MD", "hr": "HR", "implementor": "IMPLEMENTOR"}
COLLECTIONS = ["learners", "staff"]


async def main(dry_run: bool):
    await connect_to_mongo()
    grand = 0
    for coll_name in COLLECTIONS:
        coll = get_collection(coll_name)
        docs = await coll.find({}, {"department": 1, "governance_role": 1}).to_list(10000)
        to_set = []
        for d in docs:
            if (d.get("governance_role") or "").strip():
                continue  # already migrated
            dept = (d.get("department") or "").strip().lower()
            role = GOVERNANCE.get(dept)
            if role:
                to_set.append((d["_id"], role))
        print(f"{coll_name}: {len(to_set)} user(s) to set governance_role "
              f"(of {len(docs)}); {sum(1 for x in docs if (x.get('governance_role') or '').strip())} already set")
        if not dry_run:
            for _id, role in to_set:
                await coll.update_one({"_id": _id}, {"$set": {"governance_role": role}})
        grand += len(to_set)

    if dry_run:
        print(f"\n[DRY-RUN] Would set governance_role on {grand} user(s). Nothing written.")
    else:
        print(f"\n[OK] Set governance_role on {grand} user(s). `department` untouched.")


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv))
