"""Live verification of the superadmin Media Library tool (real LLM, fake DB).

Proves:
  * TEST 1 — a superadmin asking about the media library gets it via
    `list_media_library` and sees real items.
  * TEST 2 — counting questions ("how many videos") are answerable.
  * TEST 3 — the tool is NOT exposed to non-superadmin roles (registry gate).

Uses the real OpenAI-backed LLMClient but fakes storage, so it never touches the
production Atlas DB.

Run:  python -m app.assistant.tests.verify_media_library   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import app.assistant.files.attachment_store as astore
import app.assistant.memory.conversation_store as cstore
import app.assistant.tools.admin.media_tools as media_tools
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry
from app.assistant.tests.test_phase2_memory_streaming import FakeCollection

SA = UserContext(user_id="SA1", full_name="Root", role="superadmin")

MEDIA = [
    {"media_type": "video", "name": "Leadership Basics", "description": "Coaching intro video",
     "file_name": "lead.mp4", "folder": "/coaching", "tags": ["leadership"], "size": 52428800,
     "created_at": datetime(2026, 5, 1)},
    {"media_type": "video", "name": "Sales Playbook", "description": "Sales walkthrough",
     "file_name": "sales.mp4", "folder": "/sales", "tags": ["sales"], "size": 73400320,
     "created_at": datetime(2026, 5, 3)},
    {"media_type": "pdf", "name": "Onboarding Guide", "description": "New client onboarding",
     "file_name": "onboard.pdf", "folder": "/docs", "tags": ["onboarding"], "size": 1048576,
     "created_at": datetime(2026, 5, 5)},
    {"media_type": "document", "name": "Policy Handbook", "description": "Internal policies",
     "file_name": "policy.docx", "folder": "/docs", "tags": ["policy"], "size": 524288,
     "created_at": datetime(2026, 5, 6)},
]


class MediaFake:
    """Minimal media_library fake: find/sort/to_list + aggregate(group by type)."""
    def __init__(self, docs):
        self.docs = docs

    def _match(self, query, d):
        for k, v in query.items():
            if k == "$or":
                if not any(self._match(sub, d) for sub in v):
                    return False
            elif isinstance(v, dict) and "$regex" in v:
                import re
                fld = d.get(k)
                hay = " ".join(fld) if isinstance(fld, list) else str(fld or "")
                if not re.search(v["$regex"], hay, re.IGNORECASE):
                    return False
            elif d.get(k) != v:
                return False
        return True

    def find(self, query):
        docs = [d for d in self.docs if self._match(query, d)]

        class _C:
            def __init__(s, docs):
                s.docs = docs

            def sort(s, key, direction=1):
                s.docs.sort(key=lambda d: d.get(key) or 0, reverse=(direction == -1))
                return s

            async def to_list(s, n):
                return list(s.docs[:n])

        return _C(docs)

    def aggregate(self, pipeline):
        async def gen():
            counts = {}
            for d in self.docs:
                mt = d.get("media_type") or "other"
                counts[mt] = counts.get(mt, 0) + 1
            for k, v in counts.items():
                yield {"_id": k, "n": v}
        return gen()


async def main():
    cfake = FakeCollection()
    cstore.get_collection = lambda name: cfake
    cstore._indexes_ready = True
    # No attachments in these chats — return an empty collection so the
    # follow-up file-reference path is a no-op (production has a live DB here).
    astore.get_collection = lambda name: FakeCollection()
    astore._indexes_ready = True
    media_tools.get_collection = lambda name: MediaFake(MEDIA)

    orch = Orchestrator()  # REAL LLM

    print("\n=== TEST 1 — SA: 'what's in the media library?' ===")
    r1 = await orch.handle_message(SA, "what's in the media library?")
    print("tools_used:", r1.meta.get("tools_used"))
    print("ANSWER:\n", r1.answer)
    t1 = "list_media_library" in (r1.meta.get("tools_used") or []) and \
         any(name.lower() in r1.answer.lower() for name in ["Leadership", "Sales", "Onboarding", "Policy"])
    print(f"[{'PASS' if t1 else 'FAIL'}] media library listed via the tool")

    print("\n=== TEST 2 — SA: 'how many videos are in the media library?' ===")
    r2 = await orch.handle_message(SA, "how many videos are in the media library?")
    print("tools_used:", r2.meta.get("tools_used"))
    print("ANSWER:\n", r2.answer)
    t2 = "list_media_library" in (r2.meta.get("tools_used") or []) and "2" in r2.answer
    print(f"[{'PASS' if t2 else 'FAIL'}] correct video count (2)")

    print("\n=== TEST 3 — role gating (registry) ===")
    cu = {t.name for t in registry.tools_for_role("clientuser")}
    ad = {t.name for t in registry.tools_for_role("admin")}
    sa = {t.name for t in registry.tools_for_role("superadmin")}
    t3 = ("list_media_library" in sa and "list_media_library" not in cu
          and "list_media_library" not in ad)
    print(f"SA has it: {'list_media_library' in sa} | clientuser: {'list_media_library' in cu} | admin: {'list_media_library' in ad}")
    print(f"[{'PASS' if t3 else 'FAIL'}] superadmin-only")

    print("\n=== RESULT ===")
    print("1 (listed):       ", "PASS" if t1 else "FAIL")
    print("2 (count):        ", "PASS" if t2 else "FAIL")
    print("3 (SA-only gate): ", "PASS" if t3 else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
