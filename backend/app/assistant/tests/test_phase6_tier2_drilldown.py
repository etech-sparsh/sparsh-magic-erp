"""Phase 6 Tier 2 — Superadmin drill-down tools (direct, no LLM).

Covers name-or-id resolution (exact/substring/by-id/ambiguous/none),
get_company_overview, get_batch_details, get_user_activity, the active/inactive
learner split in get_platform_stats, SA-only RBAC, and PII redaction.

Run:  python -m app.assistant.tests.test_phase6_tier2_drilldown   (from backend/)
"""
from __future__ import annotations

import asyncio

from bson import ObjectId

import app.assistant.tools.admin.drilldown_tools as dd
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry
from app.assistant.tools.admin import org_tools
from app.db import mongodb


# ── Fake Mongo (subset: find/find_one/count/sort/limit/to_list, $in/$ne) ───
def _match(query, doc):
    for k, v in query.items():
        if isinstance(v, dict):
            field = doc.get(k)
            if "$ne" in v and field == v["$ne"]:
                return False
            if "$in" in v and field not in v["$in"]:
                return False
        else:
            field = doc.get(k)
            if isinstance(field, list):
                if v not in field:
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

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, n):
        return list(self._docs[:n])


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []

    async def create_index(self, *a, **k):
        return "idx"

    def find(self, query=None):
        return _Cursor([d for d in self.docs if _match(query or {}, d)])

    async def find_one(self, query):
        return next((d for d in self.docs if _match(query, d)), None)

    async def count_documents(self, query):
        return len([d for d in self.docs if _match(query, d)])


class FakeDB:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


# ── Seed ────────────────────────────────────────────────────────────────--
ACME = ObjectId()
GLOBEX = ObjectId()
U_ASHA = ObjectId()
U_BHARAT = ObjectId()
U_CAROL = ObjectId()
B_LEAD = ObjectId()

COMPANIES = [
    {"_id": ACME, "name": "Acme Retail", "status": "active", "company_type": "Retail",
     "city": "Pune", "email": "owner@acme.com", "contact": "9876500011",
     "members_count": 3, "is_active": True},
    {"_id": GLOBEX, "name": "Globex Mfg", "status": "hold", "email": "ceo@globex.com",
     "is_active": True},
]
BATCHES = [
    {"_id": B_LEAD, "name": "Leadership Q1", "product_name": "LeadPro", "status": "active",
     "companies": [str(ACME), str(GLOBEX)], "created_at": "2026-03-01"},
    # Two batches sharing a word to test ambiguity:
    {"_id": ObjectId(), "name": "Sales North", "status": "active", "companies": [], "created_at": "2026-02-01"},
    {"_id": ObjectId(), "name": "Sales South", "status": "active", "companies": [], "created_at": "2026-01-01"},
]
QUARTERS = [
    {"_id": ObjectId(), "name": "Q1 Foundations", "batch_id": str(B_LEAD), "status": "active"},
    {"_id": ObjectId(), "name": "Q2 Advanced", "batch_id": str(B_LEAD), "status": "paused"},
]
LEARNERS = [
    {"_id": U_ASHA, "full_name": "Asha Sharma", "role": "clientuser", "company_id": str(ACME),
     "email": "asha@acme.com", "mobile": "9000000022", "department": "Sales", "is_active": True},
    {"_id": U_BHARAT, "full_name": "Bharat Verma", "role": "clientuser", "company_id": str(ACME),
     "email": "bharat@acme.com", "department": "Sales", "is_active": True},
    {"_id": U_CAROL, "full_name": "Carol Doe", "role": "clientuser", "company_id": str(ACME),
     "email": "carol@acme.com", "department": "Ops", "is_active": False},
]
STAFF = [
    {"_id": ObjectId(), "full_name": "Sam Coach", "role": "coach", "email": "sam@org.com",
     "mobile": "9999999999", "is_active": True},
]
ASSESSMENTS = [
    {"_id": ObjectId(), "user_id": str(U_ASHA), "company_id": str(ACME), "quiz_title": "OOP Quiz",
     "percentage": 90.0, "passed": True, "submitted_at": "2026-02-01"},
    {"_id": ObjectId(), "user_id": str(U_ASHA), "company_id": str(ACME), "quiz_title": "OOP Quiz 2",
     "percentage": 95.0, "passed": True, "submitted_at": "2026-03-01"},
    {"_id": ObjectId(), "user_id": str(U_BHARAT), "company_id": str(ACME), "quiz_title": "OOP Quiz",
     "percentage": 40.0, "passed": False, "submitted_at": "2026-02-01"},
]
ATTENDANCE = [
    {"_id": ObjectId(), "user_id": str(U_ASHA), "status": "present"},
    {"_id": ObjectId(), "user_id": str(U_ASHA), "status": "absent"},
    {"_id": ObjectId(), "user_id": str(U_BHARAT), "status": "present"},
    {"_id": ObjectId(), "user_id": str(U_BHARAT), "status": "present"},
]

PII_STRINGS = ["owner@acme.com", "ceo@globex.com", "asha@acme.com", "bharat@acme.com",
               "carol@acme.com", "sam@org.com", "9000000022", "9876500011", "9999999999"]


def _seed():
    return FakeDB({
        "companies": FakeCollection([dict(d) for d in COMPANIES]),
        "batches": FakeCollection([dict(d) for d in BATCHES]),
        "quarters": FakeCollection([dict(d) for d in QUARTERS]),
        "learners": FakeCollection([dict(d) for d in LEARNERS]),
        "staff": FakeCollection([dict(d) for d in STAFF]),
        "LearnerAssessments": FakeCollection([dict(d) for d in ASSESSMENTS]),
        "LearnerAsessments": FakeCollection([]),
        "attendance": FakeCollection([dict(d) for d in ATTENDANCE]),
        "STAFF_CALENDER": FakeCollection([{"_id": ObjectId(), "batch_id": str(B_LEAD)}]),
        "LEARNER_CALENDER": FakeCollection([
            {"_id": ObjectId(), "batch_id": str(B_LEAD)},
            {"_id": ObjectId(), "batch_id": str(B_LEAD)},
        ]),
        "calendar_events": FakeCollection([]),
    })


SA = UserContext(user_id="sa1", full_name="Dipti", role="superadmin")

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def _no_pii(blob: str) -> bool:
    return not any(s in blob for s in PII_STRINGS)


async def main():
    mongodb.db_connection.db = _seed()
    registry.register_all()
    print("\n=== Phase 6 Tier 2 — Drill-down tools ===\n")

    # 1) RBAC registration
    print("RBAC:")
    sa = {t.name for t in registry.tools_for_role("superadmin")}
    ad = {t.name for t in registry.tools_for_role("admin")}
    t2 = {"get_company_overview", "get_batch_details", "get_user_activity"}
    check("SA sees all Tier-2 tools", t2 <= sa)
    check("AD sees no Tier-2 tools", t2.isdisjoint(ad))

    # 2) Name resolution variants
    print("\nName resolution:")
    st, doc, _, _ = await dd._resolve(["companies"], "acme")          # substring + case-insensitive
    check("resolve by partial/ci name", st == "ok" and doc["_id"] == ACME)
    st, doc, _, _ = await dd._resolve(["companies"], str(GLOBEX))     # by id
    check("resolve by id", st == "ok" and doc["_id"] == GLOBEX)
    st, _, _, cand = await dd._resolve(["batches"], "Sales")          # two matches
    check("ambiguous returns candidates", st == "ambiguous" and len(cand) == 2)
    st, _, _, _ = await dd._resolve(["companies"], "Nonexistent")
    check("none when no match", st == "none")

    # 3) get_company_overview
    print("\nget_company_overview:")
    r = await dd.get_company_overview(SA, "Acme")
    d = r.data
    check("resolves and returns company", d["company"]["name"] == "Acme Retail")
    check("batch count + names", d["batches"]["count"] == 1 and "Leadership Q1" in d["batches"]["names"])
    check("learner active/inactive split", d["learners"]["total"] == 3
          and d["learners"]["active"] == 2 and d["learners"]["inactive"] == 1)
    check("department breakdown", d["learners"]["by_department"] == {"Sales": 2, "Ops": 1})
    check("avg score computed", d["performance"]["average_score"] == 75.0,
          str(d["performance"]["average_score"]))
    check("top performer ranked by name", d["performance"]["top_performers"][0]["name"] == "Asha Sharma"
          and d["performance"]["top_performers"][0]["avg_score"] == 92.5)
    check("attendance rate", d["attendance_rate_percent"] == 75)
    check("scope global", r.meta.scope_applied == "global")
    check("no PII in company overview", _no_pii(str(d)))

    # ambiguity surfaced through the tool
    r_amb = await dd.get_company_overview(SA, "Sales")  # not a company -> none
    check("company overview: unknown -> resolved false", r_amb.data.get("resolved") is False)

    # 4) get_batch_details
    print("\nget_batch_details:")
    rb = await dd.get_batch_details(SA, "Leadership Q1")
    db_ = rb.data
    check("batch resolved", db_["batch"]["name"] == "Leadership Q1")
    check("companies in batch (names)", db_["companies"]["count"] == 2
          and set(db_["companies"]["names"]) == {"Acme Retail", "Globex Mfg"})
    check("quarters listed", [q["name"] for q in db_["quarters"]] == ["Q1 Foundations", "Q2 Advanced"])
    check("session count across calendars", db_["session_count"] == 3, str(db_["session_count"]))
    check("no PII in batch details", _no_pii(str(db_)))
    rb_amb = await dd.get_batch_details(SA, "Sales")
    check("batch details: ambiguous -> candidates", rb_amb.data.get("resolved") is False
          and len(rb_amb.data.get("candidates", [])) == 2)

    # 5) get_user_activity
    print("\nget_user_activity:")
    ru = await dd.get_user_activity(SA, "Asha Sharma")
    du = ru.data
    check("user resolved (profile basics)", du["profile"]["full_name"] == "Asha Sharma"
          and du["profile"]["role"] == "clientuser")
    check("performance summary", du["performance"]["average_score"] == 92.5
          and du["performance"]["quizzes_taken"] == 2 and du["performance"]["quizzes_passed"] == 2
          and du["performance"]["trend"] in {"improving", "flat", "declining"})
    check("attendance summary", du["attendance"]["records"] == 2
          and du["attendance"]["present"] == 1 and du["attendance"]["attendance_rate_percent"] == 50)
    check("staff lookup works too", (await dd.get_user_activity(SA, "Sam Coach")).data["profile"]["role"] == "coach")
    check("no PII in user activity", _no_pii(str(du)))

    # 6) platform stats active/inactive split
    print("\nget_platform_stats split:")
    rs = await org_tools.get_platform_stats(SA)
    check("active/inactive learners split", rs.data["total_learners"] == 3
          and rs.data["active_learners"] == 2 and rs.data["inactive_learners"] == 1)

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
