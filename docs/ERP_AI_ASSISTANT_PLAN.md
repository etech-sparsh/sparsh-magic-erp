# Sparsh LMS/ERP AI Assistant — Locked Architecture Document

> **Status:** ✅ LOCKED (v1.0) — approved for Phase 0 scaffolding
> **Scope:** Production-ready, agentic, tool-calling AI Assistant for the Sparsh LMS/ERP.
> **Owner:** AI / Backend team
> **This document is the implementation contract.** The Tool Catalog (§9) is binding.

---

## 1. Goal

Build a ChatGPT-level conversational assistant for LMS/ERP workflows that:

- understands user intent naturally (LLM-native NLU — **no** keyword/intent-classifier chatbot)
- understands context and follow-up conversations
- dynamically fetches **live** ERP data via tools (not stale RAG snapshots)
- answers analytical questions (performance, progress), not just raw lookups
- gives personalized recommendations ("what should I study today?")
- supports both **knowledge** ("what is polymorphism?") and **live data** ("my OOP quiz score?")
- adapts response length to the query
- is secure, scalable, and maintainable

## 2. Architecture Decision

**Agentic Tool-Calling (function-calling) architecture.** The LLM is the NLU engine; it can only
call pre-defined, read-only, RBAC-scoped tools. The LLM never touches the database directly.

Rejected: RAG-over-live-data (stale, poor at counts/aggregations, hard to scope per-user) and
traditional NLU pipelines (the "keyword chatbot" we are replacing).

This assistant is **separate** from the existing document-RAG "GPT Projects" feature; that feature
is exposed here as one tool (`search_knowledge`) so a single assistant answers both kinds of question.

---

## 3. High-Level Architecture

```
FRONTEND (features/assistant/) — streaming chat, suggested prompts
        │ POST /api/assistant/ask  (SSE) · JWT
ROUTER → UserContext dependency (auth-derived scope)
        │ ctx = {user_id, role, tag, company_id, batch_ids, course_ids, permissions}
ORCHESTRATOR
  ① Guardrails.input()   → prompt-injection screen
  ② ContextManager       → history window + rolling summary
  ③ QueryRewriter        → resolve "last exam" / "am I doing well?" / follow-ups
  ④ PromptBuilder        → persona + ctx + verbosity rules
  ⑤ LLM tool-loop        → role-filtered ToolRegistry (scope from ctx)
                           student/ · teacher/ · admin/ · shared/
                           analytics & recommendation tools → Analytics Engine
  ⑥ ResponseFormatter + Guardrails.output() (PII / leak check)
  ⑦ ConversationStore.persist + Summarizer (auto-title / rolling summary)
        │
  LLMClient · Analytics Engine · Audit Log
```

**Security keystone:** data scope derives **only** from the JWT-built `UserContext` (server-side),
never from LLM-emitted arguments. A successful prompt injection still cannot widen data scope.

---

## 4. Backend Folder Structure (`backend/app/assistant/`)

```
assistant/
├── router.py                  # FastAPI routes (thin controller)
├── config.py                  # model names, token limits, feature flags
├── dependencies.py            # get_user_context() → UserContext
│
├── schemas/
│   ├── chat.py                # AskRequest, AskResponse, ChatMessage
│   ├── conversation.py        # Conversation, ConversationSummary
│   ├── context.py             # UserContext
│   └── analytics.py           # performance / recommendation response shapes
│
├── core/
│   ├── orchestrator.py        # main agent loop (the conductor)
│   ├── llm_client.py          # provider abstraction (OpenAI today, swappable)
│   ├── query_rewriter.py      # normalize/expand/coref-resolve user query
│   ├── prompt_builder.py      # persona + RBAC context + verbosity rules
│   ├── context_manager.py     # history windowing + rolling summarization
│   └── response_formatter.py  # adaptive length / markdown shaping
│
├── tools/
│   ├── registry.py            # registers tools, filters by role, exports schema
│   ├── base.py                # BaseTool + RBAC guard
│   ├── student/   profile · batch · course · session · attendance ·
│   │              performance · progress · assignment · recommendation · notification
│   ├── teacher/   batch · cohort_analytics · roster · grading
│   ├── admin/     company · user · org_analytics · activity
│   └── shared/    knowledge (RAG bridge) · calendar · lookup
│
├── analytics/                 # pure functions, no LLM (testable, auditable)
│   ├── performance.py         # score aggregation, trends, strengths/weaknesses
│   ├── progress.py            # completion %, course progress
│   └── recommender.py         # ranked study-plan generation
│
├── services/
│   ├── assignment_service.py  # ENCAPSULATES assignment retrieval (task events +
│   │                          # session_templates.tasks) — swappable for a future
│   │                          # standalone assignments module (V1 decision #2)
│   └── assessment_service.py  # reads LearnerAssessments + legacy LearnerAsessments
│
├── memory/
│   ├── conversation_store.py  # Mongo persistence (assistant_conversations)
│   ├── summarizer.py          # auto-title + rolling summary
│   └── long_term_memory.py    # durable user facts (optional, Phase 4)
│
├── security/
│   ├── rbac.py                # role → scope resolution (incl. custom roles)
│   ├── scope.py               # ScopeFilter (injects scope into every query)
│   ├── guardrails.py          # prompt-injection + output validation
│   └── pii.py                 # PII redaction / field whitelisting
│
└── utils/
    ├── serializers.py         # Mongo doc → clean whitelisted dict
    ├── audit.py               # audit logging (reuses activity_logs)
    └── exceptions.py
```

### Frontend (`frontend/src/features/assistant/`)

```
features/assistant/
├── AssistantWidget.jsx        # floating launcher + window container
├── context/AssistantContext.jsx
├── hooks/      useAssistant.js · useConversation.js
├── components/ ChatWindow · MessageList · MessageBubble · ChatInput ·
│              TypingIndicator · SuggestedPrompts
└── services/   assistantApi.js   # built on existing services/api.js
```

Mounted once in `App.jsx`, floats on every authenticated page.

---

## 5. Core Components

| Component | Responsibility |
|---|---|
| `dependencies.get_user_context` | Build `UserContext` from JWT each request; tools derive scope from it (LLM passes no IDs) |
| `core/query_rewriter` | Cheap `gpt-4o-mini` pass: normalize vague queries, resolve pronouns/follow-ups; skipped when query already explicit |
| `core/orchestrator` | Agent loop: guardrails → context → rewrite → prompt → tool-calling loop (max iterations) → format → persist |
| `core/llm_client` | Provider abstraction: retries, timeouts, streaming, token counting; cheap model for summaries/rewrites |
| `tools/registry` | Auto-collects `@tool`s, **filters exposed tools by role**, exports OpenAI schema |
| `analytics/*` | Pure-function insight engine consumed by analytics/recommendation tools |
| `core/response_formatter` | Verbosity rules (counts → 1 line; "explain/analyze" → structured) + `max_tokens` hints |
| `security/*` | Scope enforcement, guardrails, PII, audit |
| `memory/*` | Conversation persistence, auto-title, rolling summary, optional long-term memory |

---

## 6. Validated Data Model

### Critical realities (tools MUST respect)
1. **Users in two collections:** `staff` and `learners` (no unified `users`). Use `find_user_by_id()`.
2. **Sessions in three collections:** `STAFF_CALENDER`, `LEARNER_CALENDER`, `calendar_events`. Use `find_event_across_collections()` / `CALENDAR_COLLECTIONS`.
3. **Assessment results in `LearnerAssessments` + legacy typo `LearnerAsessments`** — query both.
4. **No `course`/`subject` entity** — hierarchy is `batches → quarters`; subject is derived (V1 decision #1).
5. **No `assignments` collection** — assignments = `type:"task"` calendar events + `session_templates.tasks[]` (V1 decision #2, behind `assignment_service`).

### Entity → Collection summary
| Entity | Collection(s) | Key fields |
|---|---|---|
| Students | `learners` | email, full_name, role, tag, company_id, batch_ids[], permissions{} |
| Staff | `staff` | email, full_name, role, permissions{} |
| Batches | `batches` | name, product_name, status, companies[], dates |
| Courses/Phases | `quarters` | name, batch_id, status, dates |
| Sessions | `STAFF_CALENDER`/`LEARNER_CALENDER`/`calendar_events` | title, type, start, status, batch_id, quarter_id, assigned_member_ids[], attendance{} |
| Session/Quiz templates | `session_templates` | title, topic, tasks[], assessments[] (questions, marks, passing_score) |
| Assessment results | `LearnerAssessments` (+ `LearnerAsessments`) | user_id, company_id, session_id, quiz_title, percentage, passed, responses[], submitted_at |
| Attendance | `attendance` | user_id, session_id, status(present/absent), date, type |
| Learnings | `learnings` | user_id, module_name, progress, status, date |
| Company progress | `company_session_progress` | company/session completion |
| Notifications | `in_app_notifications` / `notifications` / `notification_templates` | user_id, content, status, channel, sent_at |
| Roles & permissions | `roles` + embedded `permissions{}` | module, actions[], scope |
| Knowledge (RAG) | `KnowledgeBase` | project_id, content chunks |
| Activity / audit | `activity_logs` | user_id, action, module, timestamp |

---

## 7. Locked V1 Decisions

1. **Subject Derivation — APPROVED.** Derive subject from `quiz_title`, session `topic`/`title`, or `quarter` name. *Note: a dedicated `Subject` entity may be introduced in a future version if subject-level analytics becomes a core requirement.*
2. **Assignments — APPROVED.** Assignments = `type:"task"` calendar events + `session_templates.tasks[]`. **Retrieval encapsulated behind `services/assignment_service.py`** so the implementation can be swapped if a standalone assignments module is introduced.
3. **Legacy collections / bugs — APPROVED defensive handling.**
   - Tools read **both** `LearnerAssessments` and `LearnerAsessments`.
   - Tools resolve users via `find_user_by_id()` patterns, **never** a direct `users` collection.

---

## 8. RBAC Scope Rules

| Role | Scope | Enforced filter (from `UserContext`, server-side) |
|---|---|---|
| `superadmin` | Global | none |
| `admin` (staff/coach) | Coaching-wide | broad read; mutations blocked (assistant is read-only) |
| `clientadmin` | Company | `company_id == ctx.company_id` |
| `clientuser` (learner) | Personal | `user_id == ctx.user_id` for results/attendance/learnings; `batch_ids`/`company_id` for sessions/batches/knowledge |
| `custom` | Per `roles` doc | resolve module/action/scope from `roles` via `check_permission` pattern |

**Hard rule:** scope values come from `UserContext` only — never from LLM arguments.

---

## 9. Tool Catalog (IMPLEMENTATION CONTRACT)

Roles: `SA`=superadmin, `AD`=admin/staff/coach, `CA`=clientadmin, `CU`=clientuser(learner).
All tools are **read-only**. Company/personal scope auto-applied from `UserContext`.

### Student domain (`tools/student/`)
| Tool | Allowed Roles | Data Sources | Purpose |
|---|---|---|---|
| `get_my_profile` | CU, CA | `learners` | Return caller's profile (whitelisted fields) |
| `get_my_batches` | CU, CA | `learners`, `batches` | Batches the caller belongs to |
| `get_my_courses` | CU, CA | `quarters` | Courses/phases under caller's batches |
| `get_course_progress` | CU, CA | `quarters`, `company_session_progress`, `learnings` | Completion % per course |
| `get_my_sessions` | CU, CA | `STAFF_CALENDER`,`LEARNER_CALENDER`,`calendar_events` | Sessions in a date range |
| `get_upcoming_sessions` | CU, CA | calendar collections | Next sessions/exams |
| `get_session_details` | CU, CA | calendar collections | Details of one session (if caller assigned) |
| `get_my_attendance` | CU, CA | `attendance` | Caller's attendance records |
| `get_attendance_summary` | CU, CA | `attendance` | Monthly present/absent summary + rate |
| `get_latest_quiz_result` | CU, CA | `LearnerAssessments`(+legacy) | Most recent quiz/test result |
| `get_my_assessment_results` | CU, CA | `LearnerAssessments`(+legacy) | List/history of results |
| `get_subject_wise_scores` | CU, CA | `LearnerAssessments` | Scores grouped by derived subject |
| `analyze_student_performance` | CU, CA | `LearnerAssessments`, `attendance` → Analytics Engine | Analytical performance insight (trend, strengths/weaknesses) |
| `get_learning_progress` | CU, CA | `learnings`, `LearnerAssessments`, `quarters` → Analytics Engine | Overall learning progress |
| `get_pending_assignments` | CU, CA | `assignment_service` (task events + `session_templates.tasks`) | Pending assignments/tasks by due date |
| `recommend_study_plan` | CU, CA | composite → `recommender` | Personalized "what to study today" |
| `get_my_notifications` | CU, CA | `in_app_notifications` | Caller's notifications / unread count |

### Teacher domain (`tools/teacher/`)
| Tool | Allowed Roles | Data Sources | Purpose |
|---|---|---|---|
| `get_batches` | AD, CA | `batches` | List batches (CA scoped to company) |
| `get_batch_learners` | AD, CA | `learners`, `batches` | Learners in a batch |
| `get_cohort_performance` | AD, CA | `LearnerAssessments` → Analytics Engine | Batch/cohort performance analytics |
| `get_session_roster` | AD | calendar collections, `learners` | Assignees + attendance for a session |
| `get_pending_grading` | AD | `LearnerAssessments` | Descriptive answers awaiting review |

### Admin domain (`tools/admin/`)
| Tool | Allowed Roles | Data Sources | Purpose |
|---|---|---|---|
| `get_company_overview` | SA, AD, CA | `companies`, `learners`, `batches`, `company_session_progress` | Company summary (CA scoped to own company) |
| `list_company_learners` | SA, AD, CA | `learners` | Learners in a company |
| `count_entities` | SA, AD | `batches`/`companies`/`learners` | Counts & aggregations ("how many active batches") |
| `get_org_analytics` | SA, AD | multiple → Analytics Engine | Org-wide KPIs |
| `get_activity_logs` | SA, AD | `activity_logs` | Recent activity / audit lookups |

### Shared domain (`tools/shared/`)
| Tool | Allowed Roles | Data Sources | Purpose |
|---|---|---|---|
| `search_knowledge` | SA, AD, CA, CU | `KnowledgeBase` (existing RAG) | Conceptual Q&A from knowledge base |
| `get_calendar` | SA, AD, CA, CU | calendar collections | Generic calendar view (scoped) |
| `lookup_entity` | SA, AD | batches/companies/quarters | Generic name→record resolver for staff |

---

## 10. Security & Guardrails (defense in depth)

1. **Prompt-injection protection** (`guardrails.input`): instruction hierarchy; retrieved docs/tool outputs sandboxed as untrusted; heuristic screening.
2. **Scope enforcement** (the real guarantee): every query filtered by `UserContext` server-side.
3. **PII protection** (`pii` + `serializers` whitelisting): never serialize password hashes, tokens, or other users' contact info; redact on output.
4. **Output validation** (`guardrails.output`): structural + leak detection before returning.
5. **Audit logging** (`utils/audit`): log request, rewritten query, tool calls, answer → `activity_logs`.

---

## 11. Conversation Enhancements

- Auto-generated conversation titles (cheap model, after first exchange)
- Conversation summaries stored on the conversation doc
- Rolling long-term memory via summarization of older turns
- Optional durable user-fact memory injected into the prompt (Phase 4)

---

## 12. Technical Debt / Cleanup Notes

> Tracked here; tools handle defensively in V1, cleanup scheduled separately.

- **TD-1: `LearnerAssessments` consolidation.** Legacy typo collection `LearnerAsessments` (single `s`) still holds records. Plan a one-time migration to merge into `LearnerAssessments`, then remove dual-read logic from `assessment_service` and existing routes (`user.py`, `calendar_events.py`, `company.py`).
- **TD-2: Attendance sync `users`-collection reference.** `calendar_events.py` (~L439/L463) queries a non-existent unified `users` collection during attendance email sync; users actually live in `staff`/`learners`. Replace with `find_user_by_id()`. AI tools already avoid this path.
- **TD-3 (future):** dedicated `Subject` entity if subject-level analytics becomes core (see decision #1).
- **TD-4 (future):** standalone assignments module; swap `assignment_service` implementation (see decision #2).
- **TD-5 (future):** upgrade `KnowledgeBase` retrieval from keyword-regex to vector embeddings.

---

## 13. Roadmap

| Phase | Deliverable | Folds in |
|---|---|---|
| **0 — Scaffold** | Folder structure, config, schemas, `UserContext` dependency, role-filtered registry, `assignment_service`/`assessment_service` stubs | Context injection, tool org |
| **1 — MVP** | Orchestrator loop + 3 student tools (`get_my_sessions`, `get_latest_quiz_result`, `get_my_attendance`) + endpoint + basic widget (learner-only) | Live data fetch |
| **2 — Memory & Rewriter** | ConversationStore, context windowing, QueryRewriter, streaming, auto-titles | Query rewriting, conversation enhancements |
| **3 — Analytics & Recommendations** | Analytics Engine, performance/progress/subject tools, recommendation engine, `search_knowledge` hybrid | Analytics, recommendations, hybrid |
| **4 — Hardening** | Guardrails (injection/PII/output), audit logging, caching, rate limit, embeddings RAG upgrade, tests, long-term memory | Security, scale |

---

## 14. Dependencies

Existing: `openai==1.61.1` (supports tool-calling + streaming), Motor/Mongo, FastAPI, React/Vite,
`react-markdown` (rendering). Optional additions: `tiktoken` (token counting), `tenacity` (retries).
No new database or vector store required for V1.

---

*End of locked architecture document v1.0.*
