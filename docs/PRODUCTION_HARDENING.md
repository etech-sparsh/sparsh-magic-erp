# Sparsh ERP AI Assistant — Production Hardening (Phase 4)

> Operational readiness review. Status: ✅ implemented & verified (read-only assistant).

---

## 1. Operational Architecture

```
                    ┌──────────────── Request edge (router) ────────────────┐
HTTP POST /ask ──▶  │ correlation.begin_request(X-Request-ID | new)          │
                    │ flags.is_enabled_for(ctx)         → 403 if gated off   │
                    │ ratelimit.limiter.check(user_id)  → 429 if exceeded    │
                    └───────────────────────┬───────────────────────────────┘
                                            │ cid in contextvar
                    ┌───────────────────────▼───────────────────────────────┐
                    │ Orchestrator                                           │
                    │  guardrails.screen_input → reinforce note + metric     │
                    │  context window + query rewrite                        │
                    │  tool loop → registry.execute_tool                     │
                    │     ├─ timeout + error isolation                        │
                    │     ├─ metrics.record_tool (latency/success/timeout)   │
                    │     └─ log_event(cid, tool, ms)                         │
                    │  guardrails.validate_output                            │
                    │  persist turn + attribution                            │
                    │  cost.record_cost → assistant_cost                     │
                    │  metrics.record_request                                │
                    └───────────────────────┬───────────────────────────────┘
                          caches: metadata / analytics / knowledge (TTL)
                                            │
       Observability:  correlation · structured logs · metrics · cost
       Ops endpoints:  /health (liveness) · /ready (deps) · /metrics (admin)
```

Everything is **read-only** — no write-capable tools introduced.

## 2. Metrics Catalog

| Metric | Type | Source | Exposed at |
|---|---|---|---|
| `requests.count` / `errors` / `error_rate` | counter/derived | `metrics.record_request` | `/metrics` |
| `requests.avg_ms` | gauge | request timing | `/metrics` |
| `tools.<name>.calls/success/failure` | counter | `execute_tool` | `/metrics` |
| `tools.<name>.timeouts` | counter | `execute_tool` (timeout path) | `/metrics` |
| `tools.<name>.avg_ms / max_ms` | gauge | per-tool timing | `/metrics` |
| `tools.<name>.success_rate` | derived | success/calls | `/metrics` |
| `rate_limited` | counter | 429 path | `/metrics` |
| `input_flagged` | counter | guardrails input | `/metrics` |
| token usage (`prompt/completion/total`, `by_model`) | per request | `UsageMeter` | response `meta.usage` |
| cost (`total_usd`, `by_model`) | per request | `cost.estimate_cost` | response `meta.cost` + `assistant_cost` |
| `correlation_id` | id | `correlation` | response `meta` + `X-Request-ID` header + every log line |

Structured log events: `tool_executed`, `request_complete`, `input_flagged`, `output_flagged`, `cost_record_failed` — all carry `cid`.

## 3. Rate-Limit Policy

| Aspect | Value |
|---|---|
| Algorithm | Sliding window |
| Key | `user_id` |
| Default | **30 requests / 60s** (`RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW`) |
| Exceeded | HTTP **429** + `Retry-After` header; `rate_limited` metric++ |
| Toggle | `RATE_LIMIT_ENABLED` |
| Scope note | In-process; for multi-worker, back with Redis (same `check()` interface) |

## 4. Cache Policy

| Cache | Contents | TTL | Invalidation |
|---|---|---|---|
| `metadata_cache` | accessible knowledge project ids | **300s** | TTL; `clear_all()` on deploy |
| `analytics_cache` | analytics results (reserved) | **60s** | TTL (short — data changes on new submissions) |
| `knowledge_cache` | knowledge retrieval (reserved) | **120s** | TTL |

In-process TTL + FIFO eviction (max 2000 entries), behind a swappable interface (Redis-ready). Caches hold **non-authoritative, scope-keyed** data only; cache keys include `user_id`/scope so no cross-user bleed.

## 5. Feature-Flag Matrix

| Flag | Default | Effect |
|---|---|---|
| `ENABLED` | true | Master switch (→ 403 when off) |
| `STREAMING_ENABLED` | true | SSE vs JSON for `stream:true` |
| `RAG_ENABLED` | true | knowledge tool availability (gate hook) |
| `ANALYTICS_ENABLED` | true | analytics tool availability (gate hook) |
| `GUARDRAILS_ENABLED` | true | input/output screening |
| `RATE_LIMIT_ENABLED` | true | per-user limiter |
| `ROLLOUT_MODE` | `all` | `all` \| `allowlist` \| `percentage` |
| `ROLLOUT_ALLOWLIST` | [] | user_ids/emails (allowlist mode) |
| `ROLLOUT_PERCENT` | 100 | deterministic hash bucket (percentage mode) |
| `ENABLED_ROLES` | [] (all) | restrict to specific roles |
| `COST_REPORTING_ENABLED` | true | persist cost to `assistant_cost` |

## 6. Failure-Mode Analysis

| Failure | Behavior | Result |
|---|---|---|
| Tool throws | caught → `ToolResult.fail`, loop continues | graceful, isolated |
| Tool hangs | `asyncio.wait_for` timeout → fail + `timeouts` metric | no request hang |
| LLM error | propagates; request marked error in metrics | 500 to client; logged with cid |
| DB down | `/ready` 503; conversation ops raise; cost record best-effort skip | degraded, surfaced |
| OpenAI key missing | `/ready` 503 | blocked from serving |
| Cost write fails | `cost_record_failed` logged; request still returns | never breaks answers |
| Prompt injection | detected → reinforce + scope still enforced | no data exposure |
| Rate flood | 429 + Retry-After | back-pressure |
| Cache stale | bounded by TTL; scope-keyed | minor recall lag, no leak |
| Iteration runaway | `MAX_TOOL_ITERATIONS` cap | bounded cost/latency |

## 7. Rollout Plan & Rollback

**Rollout (progressive):**
1. **Deploy dark** — `ENABLED=true`, `ROLLOUT_MODE=allowlist` (team only). Verify `/ready`, run a few real queries, watch `/metrics` + `assistant_cost`.
2. **Canary** — `ROLLOUT_MODE=percentage`, `ROLLOUT_PERCENT=5` (optionally `ENABLED_ROLES=["clientuser"]`). Monitor error_rate, tool success_rate, p-latency, cost/req.
3. **Ramp** — 5 → 25 → 50 → 100% as metrics stay green.
4. **GA** — `ROLLOUT_MODE=all`.

**Guardrail thresholds to watch:** request `error_rate`, tool `success_rate`, `avg_ms`, `rate_limited` rate, daily `assistant_cost` sum, `input_flagged` spikes.

**Rollback (instant, no redeploy needed):**
- Kill switch: `ENABLED=false` → all requests 403, existing GPT feature unaffected.
- Partial: drop `ROLLOUT_PERCENT` or revert to `allowlist`.
- Feature-scoped: `STREAMING_ENABLED=false`, `RAG_ENABLED=false`, etc.
- Code rollback: the assistant is an additive package + 2 lines in `main.py`; reverting the branch removes it cleanly with zero impact on existing routes.

## 8. Operational Readiness Checklist

- [x] Liveness (`/health`) + readiness (`/ready`) endpoints
- [x] Correlation IDs across the full stack (header → logs → response)
- [x] Per-tool latency/success/timeout metrics + request rollups (`/metrics`)
- [x] Per-model token accounting + persistent cost reporting (`assistant_cost`)
- [x] Caching (metadata/analytics/knowledge) with TTLs
- [x] Per-user rate limiting (429 + Retry-After)
- [x] Feature flags + progressive rollout + kill switch
- [x] Guardrails (injection screening, output validation) + PII redaction helper
- [x] Read-only guarantee maintained (no write tools)
- [ ] Live validation with real key + populated data (pre-GA)
- [ ] Redis-backed limiter/cache for multi-worker (scale-out follow-up)

*End of production-hardening review.*
