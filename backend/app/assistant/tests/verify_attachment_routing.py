"""Live verification of follow-up attachment routing (real LLM, fake in-memory DB).

Proves the fix for two competing failure modes on follow-up turns of a chat that
has an uploaded file:
  * TEST A — a question ABOUT the file is answered FROM the file.
  * TEST B — a platform/dashboard question is NOT answered from the file (no bleed).

Uses the real OpenAI-backed LLMClient but fakes conversation + attachment storage,
so it never touches the production Atlas DB.

Run:  python -m app.assistant.tests.verify_attachment_routing   (from backend/)
"""
from __future__ import annotations

import asyncio

from bson import ObjectId

import app.assistant.files.attachment_store as astore
import app.assistant.memory.conversation_store as cstore
import app.assistant.tools.student.profile_tools as profile_tools
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.schemas.context import UserContext
from app.assistant.tests.test_phase2_memory_streaming import FakeCollection

# Résumé text the file would have extracted to (condensed).
RESUME = """Bhumika Girhare — Resume
Education: B.Tech in Computer Science Engineering (2023-2026), CGPA 7.3.
Internships:
- Python Developer Intern at Afame Technologies, Indore (May 2024 – June 2024).
  Developed Python backend modules; worked on Django views, URL routing and
  database operations; performed CRUD using SQL & Django ORM; collaborated on
  automation and data processing.
Projects: Student Result Management System; Expense Tracker Web Application.
Technical Skills: Python, HTML, CSS, Django, MySQL, SQLite, Git, GitHub, PyCharm.
Certifications: Python for Data Science (Coursera); HackerRank Basic Python.
"""

USER = UserContext(user_id="A1", full_name="Asha", role="clientuser",
                   company_id="C1", batch_ids=["B1"])


async def main():
    convo_oid = ObjectId()

    # ── Fake conversation store: one existing chat whose first turn uploaded a
    # file. The prior assistant turn is intentionally generic so the résumé
    # specifics can ONLY come from the injected file reference (clean isolation).
    cfake = FakeCollection()
    cfake.docs.append({
        "_id": convo_oid, "user_id": "A1", "role": "clientuser",
        "title": "Resume chat", "summary": None, "summary_upto": 0,
        "messages": [
            {"role": "user", "content": "summarize this"},
            {"role": "assistant", "content": "I've summarised the document you uploaded."},
        ],
        "message_count": 2,
    })
    cstore.get_collection = lambda name: cfake
    cstore._indexes_ready = True

    # ── Fake attachment store: the résumé, completed + linked to the chat.
    afake = FakeCollection()
    afake.docs.append({
        "_id": ObjectId(), "uploaded_by": "A1", "conversation_id": str(convo_oid),
        "filename": "1bhumika.pdf", "kind": "document", "status": "completed",
        "extracted_text": RESUME, "images": [], "summary": "Résumé of Bhumika Girhare",
    })
    astore.get_collection = lambda name: afake
    astore._indexes_ready = True

    async def _find_user(uid):
        return {"_id": "A1", "full_name": "Asha", "role": "clientuser",
                "company_id": "C1", "batch_ids": ["B1"]}
    profile_tools.find_user_by_id = _find_user

    orch = Orchestrator()  # REAL LLM
    cid = str(convo_oid)

    print("\n=== TEST A — file follow-up: 'tell me about my internships' ===")
    a = await orch.handle_message(USER, "tell me about my internships", conversation_id=cid)
    print("tools_used:", a.meta.get("tools_used"))
    print("ANSWER:\n", a.answer)
    # Require a detail that only appears IF the model actually read the file
    # ("Afame" is the company name — not derivable from the question).
    a_ok = "afame" in a.answer.lower()
    print(f"[{'PASS' if a_ok else 'FAIL'}] file question answered from the file")

    print("\n=== TEST B — platform question: 'what does my dashboard show?' ===")
    b = await orch.handle_message(USER, "what does my dashboard show?", conversation_id=cid)
    print("tools_used:", b.meta.get("tools_used"))
    print("ANSWER:\n", b.answer)
    bleed_terms = ["bhumika", "afame", "internship", "intern ", "cgpa", "résumé", "resume"]
    bleed = any(k in b.answer.lower() for k in bleed_terms)
    print(f"[{'PASS' if not bleed else 'FAIL'}] dashboard question did NOT bleed the résumé")

    print("\n=== TEST C — another file question: 'what are my technical skills?' ===")
    c = await orch.handle_message(USER, "what are my technical skills?", conversation_id=cid)
    print("tools_used:", c.meta.get("tools_used"))
    print("ANSWER:\n", c.answer)
    c_ok = "django" in c.answer.lower()  # only in the file
    print(f"[{'PASS' if c_ok else 'FAIL'}] skills answered from the file")

    print("\n=== TEST D — module question: 'tell me about the Position Score Card' ===")
    d = await orch.handle_message(USER, "tell me about the Position Score Card", conversation_id=cid)
    print("tools_used:", d.meta.get("tools_used"))
    print("ANSWER:\n", d.answer)
    # The original bug: PSC wrongly pulled 'School Pandhurna MPBSE' from the résumé.
    d_bleed = any(k in d.answer.lower() for k in ["afame", "bhumika", "pandhurna", "django", "cgpa"])
    print(f"[{'PASS' if not d_bleed else 'FAIL'}] module question did NOT bleed the résumé")

    print("\n=== RESULT ===")
    print("A (file usable):    ", "PASS" if a_ok else "FAIL")
    print("B (no dashboard bleed):", "PASS" if not bleed else "FAIL")
    print("C (file usable):    ", "PASS" if c_ok else "FAIL")
    print("D (no module bleed):", "PASS" if not d_bleed else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
