"""
Create (or reset) a login account directly in Mongo, for when the database has no user
yet and therefore nobody can call POST /api/auth/register — staff roles are gated behind
an existing superadmin.

Writes ONE document into `staff` (superadmin/admin/coach/staff) or `learners` (everything
else), matching exactly what routes/auth.register builds: bcrypt hash in `password`,
`tag`, `full_name`, `created_at`, plus the permission block from models/user.UserBase so
the RBAC checks and GET /users/me behave the same as a UI-created user. No other document
or collection is read or modified.

Re-running for an email that already exists updates only that account's password/role/
is_active (opt in with --force), so it doubles as a password reset.

Usage (from backend/):
    python -m scripts.create_login_user --email admin@sparsh.local --password 'Admin@123'
    python -m scripts.create_login_user --email x@y.com --password 'p' --role clientadmin \
        --company-id 665f... --first-name X --last-name Y
    python -m scripts.create_login_user --email admin@sparsh.local --password 'New@123' --force
    python -m scripts.create_login_user --list
"""
import argparse
import asyncio
import sys
from datetime import datetime

from app.controllers.auth_controller import get_password_hash
from app.config.settings import settings
from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
from app.models.user import UserBase

STAFF_ROLES = {"superadmin", "admin", "coach", "staff"}


def collection_for(role: str) -> str:
    return "staff" if role in STAFF_ROLES else "learners"


async def list_users():
    for coll in ("staff", "learners"):
        rows = await get_collection(coll).find(
            {}, {"email": 1, "role": 1, "is_active": 1, "full_name": 1, "company_id": 1}
        ).to_list(length=500)
        print(f"\n{coll}: {len(rows)} account(s)")
        for r in rows:
            print(f"  {r.get('email'):40s} role={r.get('role'):12s} "
                  f"active={r.get('is_active')} company={r.get('company_id')}")


async def upsert_user(args):
    role = args.role.lower().strip()
    email = args.email.lower().strip()
    coll_name = collection_for(role)

    # An email must be unique across BOTH collections: /auth/token searches staff first and
    # would never reach a same-email learner.
    for other in ("staff", "learners"):
        existing = await get_collection(other).find_one({"email": email})
        if not existing:
            continue
        if not args.force:
            print(f"[SKIP] {email} already exists in `{other}` "
                  f"(role={existing.get('role')}). Re-run with --force to reset it.")
            return 1
        await get_collection(other).update_one(
            {"_id": existing["_id"]},
            {"$set": {"password": get_password_hash(args.password),
                      "role": role,
                      "is_active": True}},
        )
        print(f"[OK] Reset password for {email} in `{other}` (role={role}, active=True)")
        return 0

    first = args.first_name or email.split("@")[0].title()
    doc = UserBase(
        email=email,
        first_name=first,
        last_name=args.last_name,
        role=role,
        company_id=args.company_id,
        is_active=True,
    ).model_dump()
    doc["password"] = get_password_hash(args.password)
    doc["tag"] = "staff" if role in STAFF_ROLES else "learner"
    doc["full_name"] = f"{first} {args.last_name or ''}".strip()
    doc["created_at"] = datetime.utcnow()

    result = await get_collection(coll_name).insert_one(doc)
    print(f"[OK] Created {email} in `{coll_name}` (role={role}, _id={result.inserted_id})")
    return 0


async def main():
    p = argparse.ArgumentParser(description="Create or reset a Sparsh login account.")
    p.add_argument("--email")
    p.add_argument("--password")
    p.add_argument("--role", default="superadmin",
                   help="superadmin | admin | coach | staff | clientadmin | clientuser")
    p.add_argument("--company-id", default=None,
                   help="required for clientadmin/clientuser to scope their data")
    p.add_argument("--first-name", default=None)
    p.add_argument("--last-name", default=None)
    p.add_argument("--force", action="store_true",
                   help="reset the password/role if the email already exists")
    p.add_argument("--list", action="store_true", help="list existing accounts and exit")
    args = p.parse_args()

    await connect_to_mongo()
    try:
        from app.db.mongodb import db_connection
        if db_connection.db is None:
            print("[FAILED] No database connection — check MONGODB_URI in backend/.env")
            return 2
        print(f"[DB] {settings.DATABASE_NAME}")

        if args.list:
            await list_users()
            return 0
        if not args.email or not args.password:
            p.error("--email and --password are required (or use --list)")
        return await upsert_user(args)
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
