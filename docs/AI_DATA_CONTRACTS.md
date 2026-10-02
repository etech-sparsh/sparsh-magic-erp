# AI Assistant Data Contracts — Sparsh ERP

> Cross-cutting contracts introduced before Phase 3. Binding for analytics,
> recommendations, and knowledge retrieval. Status: ✅ locked.

---

## 1. Tool Attribution (per assistant turn)

Every assistant turn records which tools produced the data behind it, so answers
are auditable and the UI can show provenance ("based on your LearnerAssessments").

**Schema** (`schemas/chat.py :: ToolAttribution`), persisted on the assistant
message in `assistant_conversations.messages[].attributions`:

```jsonc
{
  "tool":          "get_latest_quiz_result",
  "sources":       ["LearnerAssessments", "LearnerAsessments"],
  "scope_applied": "personal:A1",
  "success":       true,
  "count":         1
}
```

- Collected by the orchestrator from each executed `ToolResult.meta`.
- Returned live in `AskResponse.meta.attributions` and the streaming `done` event.
- Persisted with the turn (see CONVERSATION_PERSISTENCE_CONTRACT.md §2).

## 2. RAG Source Contract

All knowledge-retrieval tools return sources in one shape, independent of the
retrieval method (keyword today; vector later — TD-5).

**Schema** (`schemas/rag.py`):

```jsonc
// RagRetrieval
{
  "query": "what is polymorphism",
  "retrieval_method": "keyword",            // keyword | vector | hybrid
  "sources": [
    {
      "source_id":   "665f...",             // chunk _id
      "title":       "OOP_Notes.pdf",       // document name (for citation)
      "snippet":     "Polymorphism is ...", // truncated retrieved text
      "score":       null,                   // relevance (null for keyword)
      "document_id": "file_123",            // parent file id
      "collection":  "KnowledgeBase",
      "metadata":    { "project_id": "proj_9" }
    }
  ]
}
```

Rules:
- The tool's `ToolResult.meta.sources` includes `"KnowledgeBase"` + cited document titles, so attribution flows automatically.
- Snippets are truncated (≤500 chars) before entering the prompt.
- Retrieval is **scope-filtered**: a user only retrieves from knowledge projects they may access (see Phase 3 security review).

## 3. Deterministic Analytics Output Schema

Every analytics tool returns an `AnalyticsResult`. **Deterministic** means: fixed
structure, pure-function computation (no LLM), stable ordering, and identical
output for identical input. The LLM only narrates the result — it never computes it.

**Schema** (`schemas/analytics.py :: AnalyticsResult`):

```jsonc
{
  "analysis":   "performance",              // performance | progress | subject_scores
  "summary":    "Average 75.0% across 2 quizzes; trend improving.",  // templated, non-LLM
  "metrics": [
    { "key": "average_percentage", "label": "Average score", "value": 75.0, "unit": "%" },
    { "key": "quizzes_taken",      "label": "Quizzes taken",  "value": 2 },
    { "key": "trend",              "label": "Trend",          "value": "improving" }
  ],
  "breakdown":  [ { "subject": "OOP", "average_percentage": 75.0, "attempts": 2 } ],
  "period":     "recent",
  "generated_for": "A1",
  "computed_at": "2026-06-05T10:00:00Z"     // metadata only (not part of determinism)
}
```

Contract for analytics tools:
- Computation lives in `assistant/analytics/{performance,progress,recommender}.py` (pure functions).
- `summary` is string-templated from the metrics, not model-generated.
- `breakdown` rows are sorted deterministically (e.g. subjects by descending average, then name).
- Recommendations use the separate `StudyPlan` schema (ranked, deterministic).

*End of contracts.*
