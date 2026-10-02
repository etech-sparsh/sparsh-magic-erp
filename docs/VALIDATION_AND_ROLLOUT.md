# Sparsh ERP AI Assistant — Validation & Rollout Plan

> Final validation before Release Candidate. The assistant stays **read-only**
> throughout the RC period. Status: tooling ready; execution requires staging.

---

## 0. Why this must run in staging (not the dev sandbox)

The three validations exercise the **live** system and cannot be faked:
they need a running backend, a real `OPENAI_API_KEY`, a populated MongoDB
(learners, assessments, KnowledgeBase), and JWTs. The dev sandbox has none of
these, so the numbers must be produced by running the tooling below in staging.

Prerequisites:
- Backend deployed (`docker-compose up` or uvicorn) with `OPENAI_API_KEY` + DB.
- `/api/assistant/ready` returns 200.
- A **learner JWT** with real data; a second learner JWT in a different
  cohort/company (access-control); optionally an **admin JWT** (for `/metrics`).

---

## 1. Real OpenAI Validation

**Tool:** `backend/scripts/validate_openai.py`

Runs one representative prompt per capability (profile, sessions, latest quiz,
performance, subjects, progress, recommendation, knowledge, follow-up, injection),
maintaining a conversation for the follow-up.

**Captures:** per-prompt latency, tokens, cost, `tools_used`, and the answer text;
aggregates p50/p95 latency, total tokens, total cost, and **tool success rate**
(did the model pick the expected tool).

```
$env:ASSISTANT_BASE_URL="http://localhost:8000"; $env:ASSISTANT_TOKEN="<learner_jwt>"
python scripts/validate_openai.py    # -> validate_openai_report.json
```

**Manual step:** review answer quality in the report (accuracy, grounding, tone,
adaptive length). Confirm the injection prompt did NOT leak the system prompt.

**Acceptance gate (proposed):** tool success rate ≥ 0.9 · no data-leak on
injection · answers grounded in tool data · p95 latency ≤ 6 s.

## 2. Real KnowledgeBase Validation

**Tool:** `backend/scripts/validate_knowledge.py`

Sends conceptual prompts (some expected to have coverage, some not) and reads the
`search_knowledge` attributions for cited document titles; runs the same prompt as
two learners to inspect access overlap.

**Captures:** sources per prompt, empty-retrieval rate, potential false positives
(sources returned for out-of-corpus topics), and the cross-user source overlap.

```
$env:ASSISTANT_TOKEN="<learner_A>"; $env:ASSISTANT_TOKEN_ALT="<learner_B>"
python scripts/validate_knowledge.py   # -> validate_knowledge_report.json
```

**Manual step:** judge source relevance; confirm `shared` documents are ones BOTH
users are legitimately entitled to (no cross-cohort leakage).

**Acceptance gate (proposed):** no unauthorized document in any learner's results ·
false-positive rate ≤ 0.1 · relevant top source for ≥ 0.8 of covered prompts.

## 3. Load Testing

**Tool:** `backend/scripts/loadtest_assistant.py`

Drives concurrent `/ask` requests; captures p50/p95/p99 latency, error rate, HTTP
429 (rate-limit) behavior, and reads `/metrics` before/after for cache + tool stats.

```
$env:ASSISTANT_TOKEN="<learner>"; $env:ASSISTANT_ADMIN_TOKEN="<admin>"
python scripts/loadtest_assistant.py --concurrency 10 --total 200
# -> loadtest_report.json   (⚠ each request costs OpenAI tokens — start small)
```

**Acceptance gate (proposed):** error rate ≤ 1% (excluding intended 429s) ·
p95 ≤ 8 s, p99 ≤ 12 s under target concurrency · rate limiter returns 429 +
Retry-After as configured · cache `entries` grow then plateau (metadata reuse).

---

## 4. Results Template (fill from staging runs)

| Validation | Key metric | Target | Actual | Pass? |
|---|---|---|---|---|
| OpenAI | tool success rate | ≥ 0.90 | | |
| OpenAI | p95 latency | ≤ 6 s | | |
| OpenAI | cost / request (avg) | track | | |
| OpenAI | injection leak | none | | |
| Knowledge | unauthorized doc | none | | |
| Knowledge | false-positive rate | ≤ 0.10 | | |
| Load | error rate | ≤ 1% | | |
| Load | p95 / p99 | ≤ 8 s / 12 s | | |
| Load | 429 behavior | as configured | | |

---

## 5. Release-Candidate Rollout (flag-driven, read-only)

All transitions are config/flag changes — no redeploy needed.

| Stage | Flag settings | Audience | Watch |
|---|---|---|---|
| **RC-1 internal** | `ROLLOUT_MODE=allowlist`, `ROLLOUT_ALLOWLIST=[team ids]` | internal team | functional correctness, `/metrics`, cost/req |
| **RC-2 pilot** | `ROLLOUT_MODE=allowlist` + pilot learner ids (optionally `ENABLED_ROLES=["clientuser"]`) | small pilot cohort | answer quality, tool success, error rate |
| **RC-3 percentage** | `ROLLOUT_MODE=percentage`, `ROLLOUT_PERCENT=5 → 25 → 50` | progressive % | p95/p99, error_rate, daily cost, `input_flagged` |
| **GA** | `ROLLOUT_MODE=all` | everyone | steady-state dashboards |

Advance only when the prior stage's gates stay green for the agreed soak period.

## 6. Rollback (instant, no redeploy)

- **Kill switch:** `ENABLED=false` → all `/ask` return 403; existing GPT feature unaffected.
- **De-scope:** lower `ROLLOUT_PERCENT` or revert `ROLLOUT_MODE=allowlist`.
- **Feature-scoped:** `RAG_ENABLED=false`, `STREAMING_ENABLED=false`, `ANALYTICS_ENABLED=false`.
- **Code:** the assistant is an additive package + 2 lines in `main.py`; reverting the branch removes it cleanly.

## 7. Read-only guarantee during RC

No write-capable tools exist or will be added during the RC period. Every tool is
a read-only, RBAC-scoped query; the only writes are to the assistant's own
operational collections (`assistant_conversations`, `assistant_cost`) — never to
ERP business data.

---

*Run the three tools in staging, paste results into §4, and we review against the
gates before declaring RC-1.*
