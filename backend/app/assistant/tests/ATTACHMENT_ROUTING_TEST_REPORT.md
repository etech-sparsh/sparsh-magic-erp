# Test Report — Chatbot File Attachment & Routing

**Date:** 2026-06-09
**Component:** Sparsh Assistant (chatbot) — multi-modal attachments + tool routing
**Test harness:** `app/assistant/tests/verify_attachment_routing.py`
**Method:** Real OpenAI-backed LLM + fake in-memory storage (production Atlas DB never touched)

---

## 1. Summary

| Area | Status |
|---|---|
| PDF text extraction (text PDFs) | ✅ Working |
| PDF extraction (scanned/image PDFs) | ✅ Fixed (PyMuPDF installed) |
| Empty-extraction "no files attached" misfire | ✅ Fixed (file always acknowledged) |
| File remembered on follow-up turns | ✅ Fixed (content re-injected) |
| File content bleeding into platform questions | ✅ Fixed (subordinate framing) |
| **Overall routing verification (4/4 scenarios)** | ✅ **PASS** |

---

## 2. Issues found & fixed

1. **PyMuPDF (`fitz`) missing from runtime** — pinned in `requirements.txt` but not installed in the active interpreter. Scanned/image PDFs produced empty text *and* empty images, so the model received nothing and replied "no files attached." → **Installed `PyMuPDF==1.24.10`.**

2. **Silent omission of unreadable files** — `build_attachment_context` appended nothing when a completed file had no extractable text. → **Now always names the file with an honest reason** (scanned image / empty / password-protected).

3. **File forgotten on follow-up turns** — the composer clears the attachment tray after each send, so follow-ups carried no file IDs and only the original message was persisted. The first relied-upon fix (telling the model it *could* search) was too fragile; the model didn't search. → **Follow-up turns now re-inject the file's text directly** from `list_for_conversation`.

4. **File content bleeding into unrelated questions** — re-injecting on every turn caused résumé content to leak into dashboard/module questions (e.g. "PSC" returned "School Pandhurna MPBSE" from the résumé). → **File is now injected as a subordinate reference**: used for questions about the document, explicitly ignored for platform data (dashboard, scores, sessions, batches, Support Engine modules).

---

## 3. Test methodology

- Seeded a fake conversation that already had a résumé (`1bhumika.pdf`) uploaded and linked.
- The prior assistant turn was deliberately generic, so any résumé specifics in an answer could **only** have come from the file reference injected by the code under test (clean isolation).
- Drove the **real** orchestrator + **real** LLM with four follow-up questions.
- Asserted on details that only appear if the model truly read the file (e.g. the company name "Afame"), and on the absence of résumé terms for platform questions (no bleed).

> Note: in TEST B and D the answers report a "connection issue" because the fake harness has no DB for those tools. The property under test is the **routing** (correct tool selected) and **no bleed** — both verified. In the live app those tools return real data.

---

## 4. Results — 4/4 PASS

| # | Question | Expected route | tools_used | Verdict |
|---|---|---|---|---|
| A | "tell me about my internships" | The file | `[]` (answered from injected reference) | ✅ PASS |
| B | "what does my dashboard show?" | `get_dashboard_stats` | `['get_dashboard_stats']` | ✅ PASS |
| C | "what are my technical skills?" | The file | `[]` (answered from injected reference) | ✅ PASS |
| D | "tell me about the Position Score Card" | `get_support_engine_status` | `['get_support_engine_status']` | ✅ PASS |

### Captured answers

**A — file question → answered from file**
> Your internship experience includes:
> - **Python Developer Intern at Afame Technologies, Indore** (May 2024 – June 2024)
>   - Developed Python backend modules.
>   - Worked on Django views, URL routing, and database operations.
>   - Performed CRUD operations using SQL and Django ORM.
>   - Collaborated on automation and data processing tasks.

**B — dashboard question → routed to dashboard tool, no résumé bleed**
> I wasn't able to access your dashboard data due to a connection issue. Please try again later…

**C — skills question → answered from file**
> Your technical skills include: Python, HTML, CSS, Django, MySQL, SQLite, Git, GitHub, PyCharm.

**D — module question → routed to Support Engine tool, no résumé bleed**
> I'm currently unable to access the details about the Position Score Card due to a connection issue…

(Verdict checks: A requires "afame"; C requires "django"; B and D require the absence of résumé terms such as afame / bhumika / pandhurna / cgpa.)

---

## 5. Files changed

| File | Change |
|---|---|
| `app/assistant/files/service.py` | Backfill chunks on link; acknowledge unreadable files |
| `app/assistant/files/attachment_store.py` | `ensure_chunks_for_conversation`, `conversation_has_attachments` |
| `app/assistant/core/orchestrator.py` | Re-inject prior-turn files as a subordinate reference on follow-ups |
| `app/assistant/core/prompt_builder.py` | Support Engine routing + bullet-point formatting guidance |
| `requirements` (runtime) | Installed `PyMuPDF==1.24.10` |

---

## 6. Reproduce

```bash
cd backend
venv/Scripts/python.exe -m app.assistant.tests.verify_attachment_routing
```

Expected tail:

```
=== RESULT ===
A (file usable):       PASS
B (no dashboard bleed): PASS
C (file usable):       PASS
D (no module bleed):   PASS
```

> The harness calls the real OpenAI API (small token cost). It uses fake in-memory
> storage and does not touch the production database.
