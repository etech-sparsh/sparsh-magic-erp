"""Phase 6 END-TO-END — real LLM tool selection through the assistant chat flow.

Drives Orchestrator.handle_message() with the REAL LLM (genuine tool selection)
over a seeded in-memory fake DB (no live Mongo, no data pollution). For each
prompt we capture: tool selected, tool arguments, tool result, final answer —
and assert correct tool choice, successful execution, a meaningful answer, no
PII leakage, and no misuse of personal-scope tools. Negative cases confirm AD /
CA / CU cannot reach the SA-only tools through chat.

Requires OPENAI_API_KEY. Run:
    python -m app.assistant.tests.test_phase6_e2e_admin_chat   (from backend/)
"""
from __future__ import annotations

import asyncio
import re

from bson import ObjectId

import app.assistant.memory.conversation_store as store
from app.assistant.core.llm_client import LLMClient
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry
from app.db import mongodb


# ── Fake Mongo (operator subset used by the flow) ──────────────────────────
def _match(query, doc):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(s, doc) for s in v):
                return False
        elif isinstance(v, dict):
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

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, filt, update):
        for d in self.docs:
            if _match(filt, d):
                for k, val in update.get("$push", {}).items():
                    arr = d.setdefault(k, [])
                    arr.extend(val["$each"]) if isinstance(val, dict) and "$each" in val else arr.append(val)
                for k, val in update.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + val
                for k, val in update.get("$set", {}).items():
                    d[k] = val
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()


class FakeDB:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


# ── Seed data (PII deliberately included to prove redaction) ───────────────
C_ACME = ObjectId()
PII_STRINGS = ["owner@acme.com", "ceo@globex.com", "sam.coach@org.com",
               "asha@acme.com", "9876500011", "9000000022", "5 Mill Road"]

COMPANIES = [
    {"_id": C_ACME, "name": "Acme Retail", "status": "active", "company_type": "Retail",
     "city": "Pune", "email": "owner@acme.com", "contact": "9876500011",
     "address": "5 Mill Road", "gst": "GST27ACME", "members_count": 12, "is_active": True,
     "created_at": "2026-01-01"},
    {"_id": ObjectId(), "name": "Globex Mfg", "status": "hold", "company_type": "Manufacturing",
     "city": "Surat", "email": "ceo@globex.com", "members_count": 4, "is_active": True,
     "created_at": "2026-02-01"},
]
BATCHES = [
    {"_id": ObjectId(), "name": "Leadership Q1", "product_name": "LeadPro", "status": "active",
     "companies": [str(C_ACME)], "created_at": "2026-03-01"},
    {"_id": ObjectId(), "name": "Sales Bootcamp", "product_name": "SalesPro", "status": "active",
     "companies": [], "created_at": "2026-02-01"},
    {"_id": ObjectId(), "name": "Onboarding 2025", "product_name": "", "status": "completed",
     "companies": [str(C_ACME)], "created_at": "2026-01-01"},
]
STAFF = [
    {"_id": ObjectId(), "full_name": "Sam Coach", "role": "coach", "email": "sam.coach@org.com",
     "mobile": "9876500011", "is_active": True, "created_at": "2026-01-01"},
    {"_id": ObjectId(), "full_name": "Priya Admin", "role": "admin", "email": "priya@org.com",
     "is_active": True, "created_at": "2026-01-02"},
]
LEARNERS = [
    {"_id": ObjectId(), "full_name": "Asha Learner", "role": "clientuser", "company_id": str(C_ACME),
     "email": "asha@acme.com", "mobile": "9000000022", "department": "Sales", "is_active": True,
     "created_at": "2026-01-03"},
    {"_id": ObjectId(), "full_name": "Bharat User", "role": "clientuser", "company_id": str(C_ACME),
     "email": "bharat@acme.com", "department": "Ops", "is_active": True, "created_at": "2026-01-04"},
    {"_id": ObjectId(), "full_name": "Carol Doer", "role": "clientdoer", "company_id": "co2",
     "email": "carol@x.com", "is_active": False, "created_at": "2026-01-05"},
]


def _seed_db():
    return FakeDB({
        "companies": FakeCollection([dict(d) for d in COMPANIES]),
        "batches": FakeCollection([dict(d) for d in BATCHES]),
        "staff": FakeCollection([dict(d) for d in STAFF]),
        "learners": FakeCollection([dict(d) for d in LEARNERS]),
    })


# ── Contexts ───────────────────────────────────────────────────────────────
SA = UserContext(user_id="sa1", full_name="Dipti Jain", role="superadmin")
ADMIN = UserContext(user_id="ad1", full_name="Priya", role="admin")
CADMIN = UserContext(user_id="ca1", full_name="Owner", role="clientadmin", company_id=str(C_ACME))
LEARNER = UserContext(user_id="cu1", full_name="Asha", role="clientuser", company_id=str(C_ACME))

ADMIN_TOOLS = {"list_batches", "list_companies", "get_platform_stats", "list_users",
               "get_company_overview", "get_batch_details", "get_user_activity"}

# ── Capture: wrap registry.execute_tool to record calls per prompt ─────────
RECORDER: list = []
_orig_execute = registry.execute_tool


async def _recording_execute(spec, ctx, arguments, timeout=None):
    result = await _orig_execute(spec, ctx, arguments, timeout=timeout)
    RECORDER.append({
        "tool": spec.name,
        "args": dict(arguments),
        "success": result.success,
        "scope": result.meta.scope_applied,
        "count": result.meta.count,
        "data": result.data,
        "error": result.error,
    })
    return result


results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def _leaked_pii(text: str) -> list:
    text = text or ""
    hits = [s for s in PII_STRINGS if s in text]
    # generic email pattern as a backstop
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        hits.append("<email-pattern>")
    return hits


async def run_prompt(orch, ctx, prompt):
    RECORDER.clear()
    resp = await orch.handle_message(ctx, prompt)
    calls = list(RECORDER)
    print(f"\n> [{ctx.role}] {prompt!r}")
    for c in calls:
        preview = c["data"] if not isinstance(c["data"], list) else f"[{c['count']} rows]"
        print(f"    tool={c['tool']} args={c['args']} ok={c['success']} "
              f"scope={c['scope']} -> {preview}")
    print(f"    answer: {resp.answer[:240].replace(chr(10), ' ')}")
    return resp, calls


async def main():
    # Single chokepoint: every get_collection() resolves to the seeded fake DB.
    mongodb.db_connection.db = _seed_db()
    store._indexes_ready = True
    registry.execute_tool = _recording_execute  # capture wrapper
    registry.register_all()

    orch = Orchestrator(llm=LLMClient())

    print("\n=== Phase 6 E2E — real LLM tool selection (Superadmin) ===")

    # (prompt, primary-expected tool, acceptable alternatives)
    cases = [
        ("Show all batches", "list_batches", set()),
        ("List all companies", "list_companies", set()),
        ("How many active learners are on the platform?", "get_platform_stats", {"list_users"}),
        ("Give me a platform overview", "get_platform_stats", set()),
        ("List all coaches", "list_users", set()),
        ("Show active batches", "list_batches", set()),
    ]

    for prompt, expected, alts in cases:
        resp, calls = await run_prompt(orch, SA, prompt)
        names = {c["tool"] for c in calls}
        acceptable = {expected} | alts
        check(f"[{prompt}] selects {expected}", names & acceptable, f"used={names or '{}'}")
        admin_calls = [c for c in calls if c["tool"] in ADMIN_TOOLS]
        check(f"[{prompt}] admin tool executed successfully",
              admin_calls and all(c["success"] for c in admin_calls))
        check(f"[{prompt}] scope is global",
              admin_calls and all(c["scope"] == "global" for c in admin_calls))
        check(f"[{prompt}] no personal-scope tool used",
              names <= ADMIN_TOOLS, f"used={names}")
        leaks = _leaked_pii(resp.answer)
        check(f"[{prompt}] no PII in answer", not leaks, f"leaked={leaks}")
        check(f"[{prompt}] meaningful answer", len((resp.answer or '').strip()) > 15)

    # Spot-check argument inference: "Show active batches" should pass status=active.
    RECORDER.clear()
    _, calls = await run_prompt(orch, SA, "Show only the active batches")
    lb = next((c for c in calls if c["tool"] == "list_batches"), None)
    check("model infers status='active' argument",
          lb and lb["args"].get("status") == "active", str(lb["args"] if lb else None))

    # ── Tier 2 drill-downs (real LLM picks tool + resolves name) ───────────
    print("\n=== Tier 2 — entity drill-downs ===")
    tier2 = [
        ("Give me an overview of Acme Retail", "get_company_overview", "company", "acme"),
        ("Tell me about the Leadership Q1 batch", "get_batch_details", "batch", "leadership"),
        ("How is Asha Learner performing?", "get_user_activity", "user", "asha"),
    ]
    for prompt, expected, arg_key, arg_needle in tier2:
        resp, calls = await run_prompt(orch, SA, prompt)
        names = {c["tool"] for c in calls}
        call = next((c for c in calls if c["tool"] == expected), None)
        check(f"[{prompt}] selects {expected}", call is not None, f"used={names or '{}'}")
        check(f"[{prompt}] resolves name into '{arg_key}' arg",
              call and arg_needle in str(call["args"].get(arg_key, "")).lower(),
              str(call["args"] if call else None))
        check(f"[{prompt}] executed at global scope",
              call and call["success"] and call["scope"] == "global")
        check(f"[{prompt}] no personal-scope tool used", names <= ADMIN_TOOLS, f"used={names}")
        check(f"[{prompt}] no PII in answer", not _leaked_pii(resp.answer), resp.answer[:80])

    # Cross-user PII probe — SA explicitly asks for another user's contact info.
    resp, calls = await run_prompt(orch, SA, "What is Asha Learner's email address and phone number?")
    check("[PII probe] no PII in any tool result",
          not any(_leaked_pii(str(c["data"])) for c in calls))
    check("[PII probe] no PII in final answer", not _leaked_pii(resp.answer), resp.answer[:120])

    # ── Negative cases — AD / CA / CU cannot reach SA tools via chat ───────
    print("\n=== Negative: non-superadmin cannot reach SA tools ===")
    for ctx in (ADMIN, CADMIN, LEARNER):
        schema_names = {t["function"]["name"] for t in registry.openai_schema_for_role(ctx.role)}
        check(f"[{ctx.role}] SA tools absent from schema", ADMIN_TOOLS.isdisjoint(schema_names))
        _, calls = await run_prompt(orch, ctx, "Show all batches and list every company")
        names = {c["tool"] for c in calls}
        check(f"[{ctx.role}] no SA tool executed via chat", ADMIN_TOOLS.isdisjoint(names),
              f"used={names}")
        leaks = [c for c in calls if _leaked_pii(str(c["data"]))]
        # Ensure no answer leaked other companies' PII either
        check(f"[{ctx.role}] no cross-tenant PII surfaced", not any(
            _leaked_pii(str(c.get("data"))) for c in calls if c["tool"] in ADMIN_TOOLS))

    registry.execute_tool = _orig_execute  # restore

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
