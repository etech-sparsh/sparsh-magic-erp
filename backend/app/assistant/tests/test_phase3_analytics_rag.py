"""Phase 3 verification harness — no live DB or OpenAI required.

Covers: deterministic analytics, subject derivation, recommendations, RAG
retrieval flow + scope filtering, source attribution, tool-attribution
persistence, and security for hybrid data + knowledge.

Run:  python -m app.assistant.tests.test_phase3_analytics_rag   (from backend/)
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from bson import ObjectId

import app.assistant.memory.conversation_store as store
import app.assistant.services.assessment_service as assessment_service
import app.assistant.services.knowledge_service as knowledge_service
import app.assistant.tools.student.recommendation_tools as recommendation_tools
from app.assistant.analytics import performance, recommender
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.schemas.analytics import PerformanceSummary
from app.assistant.schemas.context import UserContext
from app.assistant.tools.student import performance_tools


# ── Fake Mongo (full operator support) ────────────────────────────────────
def _match(query, doc):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(s, doc) for s in v):
                return False
        elif k == "$and":
            if not all(_match(s, doc) for s in v):
                return False
        elif isinstance(v, dict):
            field = doc.get(k)
            for op, opv in v.items():
                if op == "$gte" and not (field is not None and field >= opv):
                    return False
                elif op == "$lte" and not (field is not None and field <= opv):
                    return False
                elif op == "$in":
                    if isinstance(field, list):
                        if not any(x in opv for x in field):
                            return False
                    elif field not in opv:
                        return False
                elif op == "$regex":
                    flags = re.I if "i" in v.get("$options", "") else 0
                    if field is None or not re.search(opv, str(field), flags):
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

    def find(self, query):
        return _Cursor([d for d in self.docs if _match(query, d)])

    async def find_one(self, query):
        return next((d for d in self.docs if _match(query, d)), None)

    async def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = ObjectId()
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


# ── Fixtures ──────────────────────────────────────────────────────────────
OID_B1 = ObjectId()
USER_A = UserContext(user_id="A1", full_name="Asha", role="clientuser", batch_ids=[str(OID_B1)])
USER_C = UserContext(user_id="C9", full_name="Cy", role="clientuser")          # no batches/perms
STAFF = UserContext(user_id="S1", full_name="Sam", role="admin")

ASSESSMENTS = [
    {"_id": "q1", "user_id": "A1", "quiz_title": "OOP Quiz", "percentage": 40.0, "passed": False, "submitted_at": "2026-01-01"},
    {"_id": "q2", "user_id": "A1", "quiz_title": "OOP Quiz Retake", "percentage": 50.0, "passed": False, "submitted_at": "2026-02-01"},
    {"_id": "q3", "user_id": "A1", "quiz_title": "Databases Test", "percentage": 90.0, "passed": True, "submitted_at": "2026-03-01"},
    {"_id": "q4", "user_id": "A1", "quiz_title": "Databases Exam", "percentage": 95.0, "passed": True, "submitted_at": "2026-04-01"},
    {"_id": "q9", "user_id": "B2", "quiz_title": "Networking", "percentage": 100.0, "passed": True, "submitted_at": "2026-05-01"},
]
BATCHES = [{"_id": OID_B1, "name": "Batch 1", "companies": [], "gpt_projects": [{"id": "P1"}]}]
PERMS = [{"entity_id": "A1", "entity_type": "user", "project_id": "P2"}]
KB = [
    {"_id": ObjectId(), "project_id": "P1", "filename": "OOP_Notes.pdf", "file_id": "f1",
     "content": "Polymorphism is the ability of an object to take many forms."},
    {"_id": ObjectId(), "project_id": "P2", "filename": "DB_Notes.pdf", "file_id": "f2",
     "content": "Normalization reduces redundancy. Related to polymorphism in modeling."},
    {"_id": ObjectId(), "project_id": "P9", "filename": "Secret.pdf", "file_id": "f9",
     "content": "Confidential polymorphism notes for another cohort."},
]


def _resolver():
    cols = {
        "LearnerAssessments": FakeCollection([d for d in ASSESSMENTS]),
        "LearnerAsessments": FakeCollection([]),
        "batches": FakeCollection([d for d in BATCHES]),
        "gpt_permissions": FakeCollection([d for d in PERMS]),
        "KnowledgeBase": FakeCollection([d for d in KB]),
        "learnings": FakeCollection([]),
        "quarters": FakeCollection([]),
        "STAFF_CALENDER": FakeCollection([]),
        "LEARNER_CALENDER": FakeCollection([
            {"_id": "s1", "title": "DB Lecture", "type": "event", "start": "2026-12-01",
             "status": "schedule", "assigned_member_ids": ["A1"]},
        ]),
        "calendar_events": FakeCollection([]),
    }
    return lambda name: cols.setdefault(name, FakeCollection())


# ── Fake LLM (for attribution persistence path) ───────────────────────────
class _Fn:
    def __init__(self, n, a):
        self.name = n; self.arguments = json.dumps(a)


class _Call:
    def __init__(self, i, n, a):
        self.id = f"c{i}"; self.function = _Fn(n, a)


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content; self.tool_calls = tool_calls


class FakeLLM:
    def __init__(self, script):
        self.s = list(script); self.i = 0

    async def complete(self, messages, tools=None, max_tokens=None, meter=None):
        step = self.s[self.i]; self.i += 1
        if "final" in step:
            return _Msg(content=step["final"])
        return _Msg(tool_calls=[_Call(j, t["tool"], t.get("args", {})) for j, t in enumerate(step["tools"])])

    async def utility_complete(self, prompt, max_tokens=120, meter=None):
        return ""


results = []


def check(name, cond, extra=""):
    results.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


async def main():
    resolver = _resolver()
    assessment_service.get_collection = resolver
    knowledge_service.get_collection = resolver
    recommendation_tools.get_collection = resolver
    store.get_collection = resolver
    store._indexes_ready = True

    print("\n=== Phase 3 Analytics + RAG Verification ===\n")

    # 1) Deterministic analytics
    print("Analytics determinism + correctness:")
    a_only = [d for d in ASSESSMENTS if d["user_id"] == "A1"]
    s1 = performance.analyze(a_only)
    s2 = performance.analyze(a_only)
    check("analyze is deterministic", s1.model_dump() == s2.model_dump())
    check("average computed", s1.average_percentage == 68.8, str(s1.average_percentage))
    check("trend = improving", s1.trend == "improving", s1.trend)
    subs = {x.subject: x.average_percentage for x in performance.subject_scores(a_only)}
    check("subject derivation groups OOP/Databases", subs == {"Databases": 92.5, "OOP": 45.0}, str(subs))
    check("weak subject = OOP", [w.subject for w in s1.weak_subjects] == ["OOP"])
    check("strong subject = Databases", [w.subject for w in s1.strong_subjects] == ["Databases"])

    # 2) Recommendations
    print("\nRecommendations:")
    plan = recommender.build_study_plan("A1", s1, upcoming_sessions=[{"title": "DB Lecture", "start": "2026-12-01"}])
    titles = [r.title for r in plan.recommendations]
    check("weak subject ranked first", titles[0] == "Revise OOP", titles[0])
    check("upcoming session included", any("Prepare for: DB Lecture" in t for t in titles))
    empty_plan = recommender.build_study_plan("A1", PerformanceSummary())
    check("graceful fallback when no signals", empty_plan.recommendations[0].title == "Keep up the good work")

    # 3) RAG retrieval flow + scope filtering
    print("\nRAG retrieval + scope:")
    retr = await knowledge_service.search(USER_A, "what is polymorphism")
    got = sorted(s.title for s in retr.sources)
    check("learner retrieves only accessible projects", got == ["DB_Notes.pdf", "OOP_Notes.pdf"], str(got))
    check("other cohort's doc excluded", all(s.metadata.get("project_id") != "P9" for s in retr.sources))
    check("retrieval method tagged", retr.retrieval_method == "keyword")
    check("snippets present + bounded", all(0 < len(s.snippet) <= 500 for s in retr.sources))

    empty = await knowledge_service.search(USER_C, "polymorphism")
    check("user with no access gets nothing (no leak)", empty.sources == [])

    staff = await knowledge_service.search(STAFF, "polymorphism")
    check("staff (unrestricted) can see all incl P9", any(s.metadata.get("project_id") == "P9" for s in staff.sources))

    # 4) Source attribution from the tool
    print("\nSource attribution:")
    kb_result = await performance_tools.analyze_student_performance(USER_A, period="all")
    check("analytics tool attributes LearnerAssessments",
          "LearnerAssessments" in kb_result.meta.sources)
    from app.assistant.tools.shared.knowledge_tools import search_knowledge
    sk = await search_knowledge(USER_A, query="polymorphism")
    check("knowledge tool cites document titles",
          "KnowledgeBase" in sk.meta.sources and "OOP_Notes.pdf" in sk.meta.sources, str(sk.meta.sources))

    # 5) Tool-attribution PERSISTENCE (end-to-end via orchestrator)
    print("\nTool-attribution persistence:")
    orch = Orchestrator(llm=FakeLLM([
        {"tools": [{"tool": "analyze_student_performance", "args": {"period": "all"}}]},
        {"final": "Your average is 68.8%, trending up."},
    ]))
    resp = await orch.handle_message(USER_A, "how am I doing?")
    attribs = resp.meta["attributions"]
    check("attribution returned in response",
          attribs and attribs[0]["tool"] == "analyze_student_performance")
    saved = await resolver(store.COLL).find_one({"_id": ObjectId(resp.conversation_id)})
    assistant_msg = next(m for m in saved["messages"] if m["role"] == "assistant")
    check("attribution persisted on assistant turn",
          assistant_msg.get("attributions") and assistant_msg["attributions"][0]["tool"] == "analyze_student_performance")

    # 6) Security — hybrid data + knowledge stay caller-scoped
    print("\nSecurity (hybrid):")
    a_results = await assessment_service.get_results_for_user(USER_A, "A1")
    check("analytics only over caller's assessments (B2 excluded)",
          all(r["user_id"] == "A1" for r in a_results) and len(a_results) == 4)
    check("knowledge scope respects ownership (C9 empty, A1 limited)",
          empty.sources == [] and all(s.metadata.get("project_id") in {"P1", "P2"} for s in retr.sources))

    # 7) Latency / cost note (analytics are pure — no extra LLM)
    print("\nLatency (pure analytics compute):")
    t = time.perf_counter()
    for _ in range(1000):
        performance.analyze(a_only)
    dt = (time.perf_counter() - t) / 1000 * 1000
    check("analyze() sub-millisecond", dt < 1.0, f"{dt:.4f} ms/call")

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
