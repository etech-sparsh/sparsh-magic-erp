"""Phase 2 verification harness — no live DB or OpenAI required.

Covers: conversation persistence + ownership, context windowing, rolling
summaries, auto-titles, query rewriting, and SSE streaming (with TTFT / total
latency / token-usage metrics).

Run:  python -m app.assistant.tests.test_phase2_memory_streaming   (from backend/)
"""
from __future__ import annotations

import asyncio
import json
import time

from bson import ObjectId

import app.assistant.memory.conversation_store as store
import app.assistant.tools.student.profile_tools as profile_tools
from app.assistant.core import context_manager, query_rewriter
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.memory import summarizer
from app.assistant.schemas.chat import ChatMessage
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.conversation import Conversation


# ── Fake Mongo (operators: $push/$each, $inc, $set) ───────────────────────
def _match(query, doc):
    for k, v in query.items():
        if isinstance(v, dict) and any(op.startswith("$") for op in v):
            field = doc.get(k)
            for op, opv in v.items():
                if op == "$gte" and not (field is not None and field >= opv):
                    return False
                if op == "$lte" and not (field is not None and field <= opv):
                    return False
        else:
            if doc.get(k) != v:
                return False
    return True


class _Res:
    def __init__(self, n=0, _id=None):
        self.deleted_count = n
        self.modified_count = n
        self.inserted_id = _id


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return list(self._docs[:n])


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def create_index(self, *a, **k):
        return "idx"

    async def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = ObjectId()
        self.docs.append(doc)
        return _Res(_id=doc["_id"])

    async def find_one(self, query):
        return next((d for d in self.docs if _match(query, d)), None)

    def find(self, query):
        return _Cursor([d for d in self.docs if _match(query, d)])

    async def update_one(self, filt, update):
        for d in self.docs:
            if _match(filt, d):
                for k, v in update.get("$push", {}).items():
                    arr = d.setdefault(k, [])
                    arr.extend(v["$each"]) if isinstance(v, dict) and "$each" in v else arr.append(v)
                for k, v in update.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + v
                for k, v in update.get("$set", {}).items():
                    d[k] = v
                return _Res(1)
        return _Res(0)

    async def delete_one(self, filt):
        for i, d in enumerate(self.docs):
            if _match(filt, d):
                del self.docs[i]
                return _Res(1)
        return _Res(0)


# ── Fake LLM ──────────────────────────────────────────────────────────────
class FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _Fn:
    def __init__(self, name, args):
        self.name = name
        self.arguments = json.dumps(args)


class _Call:
    def __init__(self, i, name, args):
        self.id = f"call_{i}"
        self.function = _Fn(name, args)


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


def _utility(prompt: str) -> str:
    if "Rewrite the user's latest message" in prompt:
        return "What sessions do I have scheduled?"
    if "conversation title" in prompt:
        return "My Profile Chat"
    if "running summary" in prompt or "Summarize the following conversation" in prompt:
        return "User asked about their profile and sessions."
    return ""


class FakeLLM:
    def __init__(self, complete_script=None, stream_script=None):
        self.cs = list(complete_script or [])
        self.ss = list(stream_script or [])
        self.ci = self.si = 0

    async def complete(self, messages, tools=None, max_tokens=None, meter=None):
        step = self.cs[self.ci]; self.ci += 1
        if meter:
            meter.add(FakeUsage(50, 20))
        if "final" in step:
            return _Msg(content=step["final"])
        return _Msg(tool_calls=[_Call(i, t["tool"], t.get("args", {})) for i, t in enumerate(step["tools"])])

    async def utility_complete(self, prompt, max_tokens=120, meter=None):
        if meter:
            meter.add(FakeUsage(20, 10))
        return _utility(prompt)

    async def summarize(self, text, meter=None):
        return await self.utility_complete("Summarize the following conversation " + text, meter=meter)

    async def complete_stream(self, messages, tools=None, max_tokens=None, meter=None):
        step = self.ss[self.si]; self.si += 1
        if "tools" in step:
            yield ("tool_calls", [
                {"id": f"c{i}", "name": t["tool"], "arguments": json.dumps(t.get("args", {}))}
                for i, t in enumerate(step["tools"])
            ])
        else:
            for tok in step["tokens"]:
                await asyncio.sleep(step.get("delay", 0.01))
                yield ("content", tok)
        if meter:
            meter.add(FakeUsage(60, 30))
        yield ("usage", FakeUsage(60, 30))


# ── Fixtures / checks ─────────────────────────────────────────────────────
USER_A = UserContext(user_id="A1", full_name="Asha", role="clientuser", company_id="C1")
USER_B = UserContext(user_id="B2", full_name="Ben", role="clientuser", company_id="C1")
USERS = {"A1": {"_id": "A1", "full_name": "Asha", "email": "a@x.com", "role": "clientuser", "password": "H"}}

results = []


def check(name, cond, extra=""):
    results.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def _parse_sse(events):
    out = []
    for raw in events:
        lines = raw.strip().split("\n")
        ev = lines[0].split("event: ", 1)[1]
        data = json.loads(lines[1].split("data: ", 1)[1])
        out.append((ev, data))
    return out


async def main():
    fake = FakeCollection()
    store.get_collection = lambda name: fake
    store._indexes_ready = False

    async def _find_user(uid):
        return USERS.get(uid)
    profile_tools.find_user_by_id = _find_user

    print("\n=== Phase 2 Memory + Streaming Verification ===\n")

    # 1) Query rewriter heuristics
    print("Query rewriter:")
    check("explicit query skips rewrite",
          (await query_rewriter.rewrite(FakeLLM(), "How did I perform in the last exam overall"))["rewritten"] is False)
    fu = await query_rewriter.rewrite(FakeLLM(), "and that one?", "talking about sessions")
    check("follow-up gets rewritten", fu["rewritten"] and "sessions" in fu["rewritten_query"].lower(),
          fu["rewritten_query"])

    # 2) Non-streaming: persistence + auto-title + usage
    print("\nNon-streaming persistence:")
    orch = Orchestrator(llm=FakeLLM(complete_script=[
        {"tools": [{"tool": "get_my_profile"}]},
        {"final": "You're Asha, a learner."},
    ]))
    resp = await orch.handle_message(USER_A, "show my profile")
    cid = resp.conversation_id
    check("conversation created + answer", bool(cid) and resp.answer == "You're Asha, a learner.")
    check("auto-title set", resp.meta["title"] == "My Profile Chat", str(resp.meta.get("title")))
    check("token usage tracked", resp.meta["usage"]["total_tokens"] > 0, str(resp.meta["usage"]))
    stored = await fake.find_one({"_id": ObjectId(cid)})
    check("turn persisted (2 messages)", stored["message_count"] == 2)
    check("owner recorded", stored["user_id"] == "A1")

    # 3) Follow-up in the SAME conversation (rewrite path + history grows)
    orch2 = Orchestrator(llm=FakeLLM(complete_script=[
        {"tools": [{"tool": "get_my_profile"}]},
        {"final": "Here are your sessions."},
    ]))
    resp2 = await orch2.handle_message(USER_A, "and mine?", conversation_id=cid)
    stored = await fake.find_one({"_id": ObjectId(cid)})
    check("same conversation reused", resp2.conversation_id == cid)
    check("history grew to 4 messages", stored["message_count"] == 4)

    # 3b) Edit-and-resend: truncates stored history before regenerating.
    print("\nEdit & resend:")
    orch_edit = Orchestrator(llm=FakeLLM(complete_script=[
        {"final": "Hi there!"},
    ]))
    # Edit the 2nd user turn (index 2): drop it + its answer, then resend.
    resp_edit = await orch_edit.handle_message(
        USER_A, "hello", conversation_id=cid, edit_from_index=2
    )
    stored = await fake.find_one({"_id": ObjectId(cid)})
    check("edit reused same conversation", resp_edit.conversation_id == cid)
    check("history truncated then re-appended (4 msgs)", stored["message_count"] == 4)
    check("edited user message replaced old", stored["messages"][2]["content"] == "hello")
    check("answer reflects edited prompt", stored["messages"][3]["content"] == "Hi there!")
    check("turn before the edit preserved", stored["messages"][0]["content"] == "show my profile")

    # 4) Context windowing
    print("\nContext windowing:")
    convo = Conversation(
        id=str(ObjectId()), user_id="A1", summary="Earlier: profile discussed.",
        messages=[ChatMessage(role=("user" if i % 2 == 0 else "assistant"), content=f"m{i}") for i in range(20)],
    )
    window = context_manager.build_window(convo)
    check("summary injected first", window[0]["role"] == "system" and "Earlier" in window[0]["content"])
    check("window capped to last 10 msgs", len(window) == 11)  # 1 summary + 10
    check("needs_summary true past trigger", context_manager.needs_summary(convo))

    # 5) Summarizer
    print("\nSummarizer:")
    title = await summarizer.generate_title(FakeLLM(), convo)
    check("title generated", title == "My Profile Chat", title)
    rolled = await summarizer.roll_summary(FakeLLM(), convo)
    check("rolling summary produced", bool(rolled))

    # 6) Streaming (SSE) + metrics
    print("\nStreaming (SSE):")
    orch3 = Orchestrator(llm=FakeLLM(stream_script=[
        {"tools": [{"tool": "get_my_profile"}]},
        {"tokens": ["You ", "are ", "Asha, ", "a ", "learner."], "delay": 0.02},
    ]))
    events = []
    t0 = time.perf_counter()
    ttft = None
    async for chunk in orch3.stream_message(USER_A, "show my profile"):
        events.append(chunk)
        if ttft is None and "event: token" in chunk:
            ttft = (time.perf_counter() - t0) * 1000
    total = (time.perf_counter() - t0) * 1000
    parsed = _parse_sse(events)
    kinds = [e for e, _ in parsed]
    answer = "".join(d["text"] for e, d in parsed if e == "token")
    done = next(d for e, d in parsed if e == "done")

    check("meta event first", kinds[0] == "meta")
    check("tool event emitted", "tool" in kinds)
    check("token events streamed", kinds.count("token") == 5)
    check("done event last", kinds[-1] == "done")
    check("streamed answer assembled", answer == "You are Asha, a learner.", answer)
    check("done carries usage", done["usage"]["total_tokens"] > 0)
    new_cid = done["conversation_id"]
    saved = await fake.find_one({"_id": ObjectId(new_cid)})
    check("streamed turn persisted", saved and saved["message_count"] == 2)
    print(f"      TTFT: {ttft:.1f} ms | total: {total:.1f} ms | tokens: {done['usage']}")

    # 7) SECURITY — conversation ownership
    print("\nSecurity — conversation ownership:")
    denied = False
    try:
        await store.load_or_create(USER_B, cid)   # B accessing A's conversation
    except Exception:
        denied = True
    check("cross-user load denied", denied)
    b_list = await store.list_for_user(USER_B)
    check("cross-user list excludes A's convo", all(c.id != cid for c in b_list))
    del_denied = False
    try:
        await store.delete_conversation(USER_B, cid)
    except Exception:
        del_denied = True
    check("cross-user delete denied", del_denied)
    a_list = await store.list_for_user(USER_A)
    check("owner sees own conversations", any(c.id == cid for c in a_list))

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
