"""Phase 1 verification harness — no live DB or OpenAI required.

Validates the full agent loop with a scripted fake LLM and in-memory collections:
  * user question -> tool selection -> live data retrieval -> conversational answer
  * per-tool timeout
  * tool error isolation
  * scope enforcement (role filtering + caller-bound queries / cross-user denial)

Run:  python -m app.assistant.tests.test_phase1_agent_loop   (from backend/)
"""
from __future__ import annotations

import asyncio
import json
import time

import app.assistant.services.assessment_service as assessment_service
import app.assistant.tools.student.profile_tools as profile_tools
import app.assistant.tools.student.session_tools as session_tools
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools import registry


# ── Fake Mongo ────────────────────────────────────────────────────────────
def _match(query: dict, doc: dict) -> bool:
    for key, val in query.items():
        if key == "$or":
            if not any(_match(sub, doc) for sub in val):
                return False
        elif isinstance(val, dict):
            field = doc.get(key)
            for op, opv in val.items():
                if op == "$gte" and not (field is not None and field >= opv):
                    return False
                if op == "$lte" and not (field is not None and field <= opv):
                    return False
        else:
            field = doc.get(key)
            if isinstance(field, list):
                if val not in field:
                    return False
            elif field != val:
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


class _Collection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query):
        return _Cursor([d for d in self._docs if _match(query, d)])

    async def find_one(self, query):
        for d in self._docs:
            if _match(query, d):
                return d
        return None


def _fake_get_collection(mapping):
    return lambda name: _Collection(mapping.get(name, []))


# ── Fake LLM (scripted tool-calling) ──────────────────────────────────────
class _Fn:
    def __init__(self, name, args):
        self.name = name
        self.arguments = json.dumps(args)


class _Call:
    def __init__(self, i, name, args):
        self.id = f"call_{i}"
        self.type = "function"
        self.function = _Fn(name, args)


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def complete(self, messages, tools=None, max_tokens=None, meter=None, **kw):
        step = self.script[self.calls]
        self.calls += 1
        if "final" in step:
            return _Msg(content=step["final"])
        calls = [_Call(i, t["tool"], t.get("args", {})) for i, t in enumerate(step["tools"])]
        return _Msg(content=None, tool_calls=calls)

    async def utility_complete(self, prompt, max_tokens=120, meter=None):
        # Phase 1 scope: no rewrite/title content needed — return empty so the
        # query rewriter falls back to the original message and titles default.
        return ""


# ── Fixtures ──────────────────────────────────────────────────────────────
LEARNER_A = UserContext(user_id="A1", full_name="Asha", role="clientuser", company_id="C1", batch_ids=["B1"])

USERS = {
    "A1": {"_id": "A1", "full_name": "Asha", "email": "asha@acme.com", "role": "clientuser",
           "company_id": "C1", "batch_ids": ["B1"], "department": "Implementor",
           "password": "SECRET_HASH"},  # must never surface
}
SESSIONS = {
    "LEARNER_CALENDER": [
        {"_id": "S1", "title": "OOP Basics", "type": "event", "start": "2026-06-10T10:00",
         "status": "schedule", "assigned_member_ids": ["A1"], "batch_id": "B1"},
        {"_id": "S2", "title": "Data Structures", "type": "event", "start": "2026-06-20T10:00",
         "status": "schedule", "assigned_member_ids": ["A1"], "batch_id": "B1"},
        {"_id": "S3", "title": "Someone Else", "type": "event", "start": "2026-06-12T10:00",
         "status": "schedule", "assigned_member_ids": ["B2"], "batch_id": "B9"},  # not Asha
    ],
}
ASSESSMENTS = {
    "LearnerAssessments": [
        {"_id": "Q1", "user_id": "A1", "quiz_title": "OOP Quiz", "score": 6, "total_marks": 10,
         "percentage": 60.0, "passed": True, "submitted_at": "2026-05-01T09:00"},
        {"_id": "Q2", "user_id": "A1", "quiz_title": "OOP Quiz Retake", "score": 9, "total_marks": 10,
         "percentage": 90.0, "passed": True, "submitted_at": "2026-06-01T09:00"},  # latest
        {"_id": "Q9", "user_id": "B2", "quiz_title": "Other user", "score": 10, "total_marks": 10,
         "percentage": 100.0, "passed": True, "submitted_at": "2026-06-02T09:00"},  # not Asha
    ],
}


def _install_fakes():
    session_tools.get_collection = _fake_get_collection(SESSIONS)
    assessment_service.get_collection = _fake_get_collection(ASSESSMENTS)

    async def _fake_find_user_by_id(uid):
        return USERS.get(uid)

    profile_tools.find_user_by_id = _fake_find_user_by_id

    # The orchestrator now persists turns (Phase 2). Point the conversation store
    # at an in-memory collection so the agent-loop checks run without a real DB.
    import app.assistant.memory.conversation_store as store
    from app.assistant.tests.test_phase2_memory_streaming import FakeCollection

    shared_col = FakeCollection()
    store.get_collection = lambda name: shared_col
    store._indexes_ready = True


# ── Checks ────────────────────────────────────────────────────────────────
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


async def main():
    _install_fakes()
    print("\n=== Phase 1 Agent Loop Verification ===\n")

    # 1) Scope: role filtering
    print("Scope / role filtering:")
    learner_tools = {t.name for t in registry.tools_for_role("clientuser")}
    check("learner has the 3 Phase-1 tools",
          {"get_my_profile", "get_my_sessions", "get_latest_quiz_result"} <= learner_tools)
    sa_tools = {t.name for t in registry.tools_for_role("superadmin")}
    check("staff/superadmin now get self-scoped read tools", "get_my_profile" in sa_tools)

    # 2) End-to-end: profile
    print("\nE2E get_my_profile:")
    t = time.perf_counter()
    orch = Orchestrator(llm=FakeLLM([
        {"tools": [{"tool": "get_my_profile"}]},
        {"final": "You're Asha, a learner in batch B1 (Implementor)."},
    ]))
    resp = await orch.handle_message(LEARNER_A, "show my profile")
    dt = (time.perf_counter() - t) * 1000
    check("answer returned", bool(resp.answer))
    check("tool used", resp.meta["tools_used"] == ["get_my_profile"])
    check("source attributed", "staff/learners" in resp.sources)
    print(f"      latency: {dt:.2f} ms | answer: {resp.answer!r}")

    # PII guard — verify the password never reaches the model payload
    raw = await profile_tools.get_my_profile(LEARNER_A)
    check("PII stripped (no password in tool data)", "password" not in raw.data)
    check("scope_applied personal", raw.meta.scope_applied == "personal:A1")

    # 3) End-to-end: sessions with date range
    print("\nE2E get_my_sessions (date range):")
    t = time.perf_counter()
    orch = Orchestrator(llm=FakeLLM([
        {"tools": [{"tool": "get_my_sessions", "args": {"from_date": "2026-06-01", "to_date": "2026-06-15"}}]},
        {"final": "You have 1 session in that window: OOP Basics on Jun 10."},
    ]))
    resp = await orch.handle_message(LEARNER_A, "what sessions do I have in early June?")
    dt = (time.perf_counter() - t) * 1000
    sess = await session_tools.get_my_sessions(LEARNER_A, from_date="2026-06-01", to_date="2026-06-15")
    titles = [s["title"] for s in sess.data]
    check("only caller's sessions in range", titles == ["OOP Basics"], f"got {titles}")
    check("other user's session excluded", "Someone Else" not in titles)
    print(f"      latency: {dt:.2f} ms | answer: {resp.answer!r}")

    # 4) End-to-end: latest quiz (defensive dual-collection + newest-first)
    print("\nE2E get_latest_quiz_result:")
    t = time.perf_counter()
    orch = Orchestrator(llm=FakeLLM([
        {"tools": [{"tool": "get_latest_quiz_result"}]},
        {"final": "Your latest quiz was 'OOP Quiz Retake' — 90% (passed)."},
    ]))
    resp = await orch.handle_message(LEARNER_A, "how did I do on my last quiz?")
    dt = (time.perf_counter() - t) * 1000
    latest = await assessment_service.get_latest_result(LEARNER_A, "A1")
    check("newest result returned", latest["quiz_title"] == "OOP Quiz Retake", latest["quiz_title"])
    print(f"      latency: {dt:.2f} ms | answer: {resp.answer!r}")

    # 5) Cross-user denial (the security keystone)
    print("\nSecurity — cross-user isolation:")
    a_results = await assessment_service.get_results_for_user(LEARNER_A, "A1")
    check("learner A only gets A's results", all(r["user_id"] == "A1" for r in a_results),
          f"{[r['_id'] for r in a_results]}")

    # 6) Protection: timeout
    print("\nProtection — per-tool timeout:")

    @registry.tool(name="_slow_tool", description="x", allowed_roles=["CU"], parameters={})
    async def _slow(ctx):
        await asyncio.sleep(0.3)
        return ToolResult.ok("_slow_tool", "done")

    t = time.perf_counter()
    r = await registry.execute_tool(registry.get_tool("_slow_tool"), LEARNER_A, {}, timeout=0.05)
    dt = (time.perf_counter() - t) * 1000
    check("slow tool returns failure (not hang)", not r.success and "timed out" in (r.error or ""))
    check("timeout enforced ~promptly (<150ms)", dt < 150, f"{dt:.1f} ms")

    # 7) Protection: error isolation
    print("\nProtection — error isolation:")

    @registry.tool(name="_boom_tool", description="x", allowed_roles=["CU"], parameters={})
    async def _boom(ctx):
        raise RuntimeError("kaboom")

    r = await registry.execute_tool(registry.get_tool("_boom_tool"), LEARNER_A, {})
    check("raising tool isolated to ToolResult.fail", not r.success and "kaboom" in (r.error or ""))

    # role re-check at execution layer: a learner-only tool must reject staff.
    @registry.tool(name="_cu_only", description="x", allowed_roles=["CU"], parameters={})
    async def _cu_only(ctx):
        return ToolResult.ok("_cu_only", "ok")

    r = await registry.execute_tool(registry.get_tool("_cu_only"),
                                    UserContext(user_id="x", role="superadmin"), {})
    check("execution-layer role re-check blocks disallowed role", not r.success)

    # ── Summary ──
    passed = sum(1 for _, c, _ in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
