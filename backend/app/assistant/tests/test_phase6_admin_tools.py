"""Phase 6 verification — Superadmin (SA) org-wide Tier-1 tools.

Covers: SA-only RBAC gating (registry exposure + execution), org-wide (unscoped)
queries, PII redaction (emails/phones/auth metadata never returned), and the
role-aware system prompt.

Run:  python -m app.assistant.tests.test_phase6_admin_tools   (from backend/)
"""
from __future__ import annotations

import asyncio

from bson import ObjectId

import app.assistant.tools.admin.org_tools as org_tools
from app.assistant.core.prompt_builder import build_system_prompt
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry


# ── Minimal fake Mongo (find/sort/to_list + count_documents) ───────────────
def _match(query, doc):
    for k, v in query.items():
        field = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and field == v["$ne"]:
                return False
        elif field != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return list(self._docs[:n])


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None):
        return _Cursor([d for d in self.docs if _match(query or {}, d)])

    async def count_documents(self, query):
        return len([d for d in self.docs if _match(query, d)])


C1 = ObjectId()
COMPANIES = [
    {"_id": C1, "name": "Acme", "status": "active", "company_type": "Retail",
     "city": "Pune", "email": "owner@acme.com", "gst": "GST123", "is_active": True},
    {"_id": ObjectId(), "name": "Globex", "status": "hold",
     "email": "ceo@globex.com", "address": "5 Mill Rd", "is_active": True},
]
BATCHES = [
    {"_id": ObjectId(), "name": "Batch A", "status": "active", "companies": [str(C1)], "created_at": "2026-01-01"},
    {"_id": ObjectId(), "name": "Batch B", "status": "completed", "companies": [], "created_at": "2026-02-01"},
]
STAFF = [
    {"_id": ObjectId(), "full_name": "Coach Sam", "role": "coach", "email": "sam@x.com",
     "mobile": "9876543210", "is_active": True},
]
LEARNERS = [
    {"_id": ObjectId(), "full_name": "Asha", "role": "clientuser", "company_id": str(C1),
     "email": "asha@acme.com", "mobile": "9000000000", "department": "Sales", "is_active": True},
    {"_id": ObjectId(), "full_name": "Bharat", "role": "clientadmin", "company_id": "other",
     "email": "b@x.com", "is_active": False},
]


def _resolver():
    cols = {
        "companies": FakeCollection([dict(d) for d in COMPANIES]),
        "batches": FakeCollection([dict(d) for d in BATCHES]),
        "staff": FakeCollection([dict(d) for d in STAFF]),
        "learners": FakeCollection([dict(d) for d in LEARNERS]),
    }
    return lambda name: cols.setdefault(name, FakeCollection())


SA = UserContext(user_id="sa1", full_name="Dipti", role="superadmin")
ADMIN = UserContext(user_id="ad1", full_name="Coach", role="admin")
LEARNER = UserContext(user_id="cu1", full_name="Asha", role="clientuser", company_id=str(C1))

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def _no_pii(rows) -> bool:
    banned = {"email", "mobile", "phone", "contact", "address", "gst", "permissions"}
    return all(banned.isdisjoint(r.keys()) for r in rows)


async def main():
    org_tools.get_collection = _resolver()
    registry.register_all()
    print("\n=== Phase 6 Admin (SA) Tools Verification ===\n")

    # 1) RBAC — registry exposure
    print("RBAC gating:")
    sa_tools = {t.name for t in registry.tools_for_role("superadmin")}
    ad_tools = {t.name for t in registry.tools_for_role("admin")}
    cu_tools = {t.name for t in registry.tools_for_role("clientuser")}
    admin_names = {"list_batches", "list_companies", "get_platform_stats", "list_users"}
    check("SA sees all 4 admin tools", admin_names <= sa_tools)
    check("AD sees none of the admin tools", admin_names.isdisjoint(ad_tools))
    check("CU sees none of the admin tools", admin_names.isdisjoint(cu_tools))

    # 2) RBAC — execution gate (defense-in-depth) blocks non-SA even if invoked
    spec = registry.get_tool("list_companies")
    blocked = await registry.execute_tool(spec, ADMIN, {})
    check("AD execution of admin tool is denied", not blocked.success, blocked.error or "")

    # 3) list_batches — org-wide + filter
    print("\nOrg-wide reads:")
    rb = await org_tools.list_batches(SA)
    check("list_batches returns all batches", rb.meta.count == 2)
    check("company_count computed", any(b.get("company_count") == 1 for b in rb.data))
    check("scope is global", rb.meta.scope_applied == "global")
    rb_active = await org_tools.list_batches(SA, status="active")
    check("status filter works", rb_active.meta.count == 1 and rb_active.data[0]["name"] == "Batch A")

    # 4) list_companies — PII stripped
    rc = await org_tools.list_companies(SA)
    check("list_companies returns all companies", rc.meta.count == 2)
    check("company emails/address/gst stripped", _no_pii(rc.data))

    # 5) get_platform_stats — counts
    rs = await org_tools.get_platform_stats(SA)
    check("platform stats counts", rs.data["total_companies"] == 2
          and rs.data["active_batches"] == 1 and rs.data["total_learners"] == 2
          and rs.data["total_staff"] == 1)

    # 6) list_users — union, PII stripped, filters
    print("\nUser listing + PII:")
    ru = await org_tools.list_users(SA)
    check("list_users unions staff + learners", ru.meta.count == 3)
    check("user emails/phones stripped", _no_pii(ru.data))
    ru_role = await org_tools.list_users(SA, role="coach")
    check("role filter works", ru_role.meta.count == 1 and ru_role.data[0]["full_name"] == "Coach Sam")
    ru_co = await org_tools.list_users(SA, company_id=str(C1))
    check("company filter excludes staff + other companies",
          ru_co.meta.count == 1 and ru_co.data[0]["full_name"] == "Asha")
    ru_active = await org_tools.list_users(SA, active_only=True)
    check("active_only excludes inactive learner", all(u.get("is_active") is not False for u in ru_active.data))

    # 7) Role-aware system prompt
    print("\nRole-aware prompt:")
    sa_prompt = build_system_prompt(SA)
    cu_prompt = build_system_prompt(LEARNER)
    check("SA prompt grants org-wide tools", "organization-wide admin tools" in sa_prompt)
    check("SA prompt forbids PII exposure", "withheld" in sa_prompt)
    check("CU prompt keeps own-data privacy clause",
          "only access the current user's own data" in cu_prompt)
    check("CU prompt has no admin grant", "organization-wide admin tools" not in cu_prompt)

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
