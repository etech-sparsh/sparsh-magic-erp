"""Give every client company an engagement, and its own people access to it.

-- What this unblocks --------------------------------------------------------------------
A client contact could not open HRMS at all. Their own company has the module switched off
-- correctly, because they do not run a hiring pipeline; Sparsh runs one FOR them -- so the
entry gate refused them, and there was no engagement to admit them through instead.

This creates the missing half: one engagement per client organisation, with that company's
own people as members. After it runs, a client's HR signs in and sees their job requests and
the CVs shared with them, and nothing else.

-- Who becomes a member, and why it is not everybody -----------------------------------------
Every member of an engagement can see every CV Sparsh shares with that client, and a CV is
somebody's personal data. So the default is the people who take part in a hiring
conversation -- MD, HR and HOD -- rather than every user on the account.

On this database that is the difference between roughly 30 people and 265. `--roles` changes
the set and `--all-users` includes everyone, but the narrow default is the one to run first:
adding a person later is a click, and un-disclosing a CV is not.

-- Report first ------------------------------------------------------------------------------
No flags prints exactly what would be created, per company, and writes nothing. `--apply`
writes. Re-running is safe: an existing engagement is reused and members are added with
$addToSet, so nobody is duplicated and nobody already there is disturbed.

Usage (from backend/):
    python scripts/seed_client_engagements.py
    python scripts/seed_client_engagements.py --apply
    python scripts/seed_client_engagements.py --apply --roles MD,HR,HOD,IMPLEMENTOR
    python scripts/seed_client_engagements.py --company <client_id> --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The governance roles that take part in reviewing candidates. Everyone else on a client's
# account is a colleague, not a hiring contact, and a CV is not theirs to read by default.
DEFAULT_ROLES = ("MD", "HR", "HOD")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create client engagements and add each client's own contacts.")
    p.add_argument("--apply", action="store_true",
                   help="WRITE. Without this the script only reports.")
    p.add_argument("--roles", default=",".join(DEFAULT_ROLES),
                   help=f"Governance roles to include (default: {','.join(DEFAULT_ROLES)}).")
    p.add_argument("--all-users", action="store_true",
                   help="Include EVERY user of each client company, whatever their role. "
                        "Read the count in the report before using this.")
    p.add_argument("--company", default=None,
                   help="Only this one client company id. Useful for a pilot.")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    roles = {r.strip().upper() for r in args.roles.split(",") if r.strip()}

    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.models.hrms import COLL_CLIENT_ENGAGEMENTS, EngagementStatus
    from app.services.hrms_client_service import (
        add_engagement_member, create_engagement,
    )

    await connect_to_mongo()
    try:
        companies = await get_collection("companies").find(
            {}, {"name": 1, "hrms_enabled": 1, "is_active": 1}).to_list(500)
        tenants = [c for c in companies if c.get("hrms_enabled") is True]
        if not tenants:
            print("No company has HRMS enabled, so there is no tenant to engage FROM.")
            return 2
        if len(tenants) > 1:
            print("More than one company has HRMS enabled; this script assumes one tenant:")
            for t in tenants:
                print(f"   {t['_id']}  {t.get('name')}")
            return 2
        tenant = tenants[0]
        tenant_id = str(tenant["_id"])

        clients = [c for c in companies if str(c["_id"]) != tenant_id]
        if args.company:
            clients = [c for c in clients if str(c["_id"]) == str(args.company)]
            if not clients:
                print(f"No client company with id {args.company}.")
                return 2

        learners = await get_collection("learners").find(
            {}, {"full_name": 1, "email": 1, "company_id": 1, "governance_role": 1,
                 "is_active": 1}).to_list(5000)
        by_company = {}
        for u in learners:
            by_company.setdefault(str(u.get("company_id") or ""), []).append(u)

        existing = {str(e.get("client_id")): e for e in
                    await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
                        {"company_id": tenant_id}).to_list(5000)}

        print()
        print("=" * 76)
        print(f"  Client engagements -- tenant: {tenant.get('name')}")
        print("=" * 76)
        print(f"  client companies      : {len(clients)}")
        print(f"  membership rule       : "
              f"{'EVERY user' if args.all_users else 'roles ' + ', '.join(sorted(roles))}")
        print()

        plan, skipped_empty, total_members = [], [], 0
        for c in clients:
            cid = str(c["_id"])
            people = by_company.get(cid, [])
            people = [u for u in people if u.get("is_active") is not False]
            if not args.all_users:
                people = [u for u in people
                          if (u.get("governance_role") or "").strip().upper() in roles]
            if not people:
                skipped_empty.append(c.get("name"))
                continue
            already = set((existing.get(cid) or {}).get("member_user_ids") or [])
            to_add = [u for u in people if str(u["_id"]) not in already]
            plan.append({"client": c, "people": people, "to_add": to_add,
                         "engagement": existing.get(cid)})
            total_members += len(to_add)

        for item in plan:
            c, people, to_add = item["client"], item["people"], item["to_add"]
            state = ("exists" if item["engagement"] else "NEW")
            print(f"  {str(c.get('name'))[:38]:40} engagement={state:6} "
                  f"members +{len(to_add)}/{len(people)}")
            for u in to_add[:4]:
                print(f"       + {str(u.get('full_name') or u.get('email'))[:30]:32}"
                      f" {u.get('governance_role') or '-'}")
            if len(to_add) > 4:
                print(f"       + ... and {len(to_add) - 4} more")

        print()
        print(f"  engagements to create : "
              f"{sum(1 for i in plan if not i['engagement'])}")
        print(f"  members to add        : {total_members}")
        if skipped_empty:
            print(f"  skipped, nobody matched the rule: {len(skipped_empty)}")
            for name in skipped_empty[:6]:
                print(f"       - {name}")
            if len(skipped_empty) > 6:
                print(f"       - ... and {len(skipped_empty) - 6} more")
            print("    (they have users, but none with a hiring role. Use --roles or "
                  "--all-users\n     if their contacts are recorded differently.)")
        print()

        if not plan:
            print("Nothing to do.")
            return 0
        if not args.apply:
            print("REPORT ONLY -- nothing was written. Re-run with --apply.")
            return 0

        # A system actor: this is a provisioning run, not a person's decision, and the audit
        # rows should say so rather than attributing it to whoever happened to run it.
        actor = {"_id": None, "full_name": "provisioning script"}
        created = added = failed = 0
        for item in plan:
            c = item["client"]
            cid = str(c["_id"])
            engagement = item["engagement"]
            if not engagement:
                try:
                    out = await create_engagement(actor, tenant_id, {
                        "client_id": cid,
                        "notes": "Created by seed_client_engagements.py so this client's "
                                 "own contacts can sign in to HRMS."})
                    engagement_id = out.get("engagement_id") or out.get("engagement", {}).get(
                        "engagement_id")
                    created += 1
                except Exception as e:
                    print(f"  FAILED to engage {c.get('name')}: {e}")
                    failed += 1
                    continue
            else:
                engagement_id = engagement.get("engagement_id")

            for u in item["to_add"]:
                try:
                    await add_engagement_member(actor, tenant_id, engagement_id,
                                                str(u["_id"]))
                    added += 1
                except Exception as e:
                    print(f"  FAILED to add {u.get('full_name')} "
                          f"to {c.get('name')}: {e}")
                    failed += 1

        print(f"Created {created} engagement(s); added {added} member(s).")
        if failed:
            print(f"{failed} operation(s) failed -- see above.")
        print()
        print("Those users can now sign in and reach HRMS as client contacts. They will see")
        print("their own job requests and the CVs shared with them, and nothing else.")
        return 0 if not failed else 1
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
