# Conversation Persistence Contract — Sparsh ERP AI Assistant

> Defines how assistant conversations are stored, owned, indexed, and retrieved.
> Binding for Phase 2 (memory, windowing, summaries, titles). Status: ✅ locked.

---

## 1. Collection

`assistant_conversations` (created lazily by MongoDB on first insert — no migration).

## 2. Document Schema

```jsonc
{
  "_id":          ObjectId,        // conversation id (server-generated)
  "user_id":      "string",        // OWNER — from UserContext.user_id, immutable
  "role":         "string",        // owner's role at creation (audit/context only)
  "title":        "string|null",   // auto-generated after first exchange
  "summary":      "string|null",   // rolling summary of older turns
  "summary_upto": 0,               // # of messages already folded into `summary`
  "messages": [                    // full, ordered transcript (never truncated on disk)
    {
      "role":      "user|assistant",
      "content":   "string",
      "timestamp": ISODate,
      "tool_calls": [ ... ],       // optional, retained for transparency
      "attributions": [            // assistant turns only — tool provenance
        { "tool": "get_latest_quiz_result", "sources": ["LearnerAssessments"],
          "scope_applied": "personal:A1", "success": true, "count": 1 }
      ]
    }
  ],
  "message_count": 0,              // denormalized len(messages) for cheap windowing
  "created_at":  ISODate,
  "updated_at":  ISODate           // bumped on every turn; drives list ordering
}
```

Notes:
- Tool/`system` messages are **not** persisted in `messages`; only user/assistant turns are. Tool results are transient to a single agent run.
- The on-disk transcript is the source of truth; summarization never deletes messages, it only advances `summary_upto` and updates `summary`.

## 3. Ownership Model

- **Single-owner.** `user_id` is set once from the authenticated `UserContext` and is never client-settable or mutable.
- **Every read and write is filtered by `user_id`.** All queries use `{ "_id": <oid>, "user_id": ctx.user_id }`. A conversation id alone is never sufficient — possession of an id does not grant access.
- **No sharing** between users in Phase 2 (no org/admin visibility into another user's chats). Admin/audit access, if ever needed, is a separate, explicitly-scoped feature.
- **Failure mode:** a lookup that doesn't match owner returns "not found" (not "forbidden") — we do not reveal that an id exists for another user.

## 4. Indexing Strategy

| Index | Purpose |
|---|---|
| `{ user_id: 1, updated_at: -1 }` | List a user's conversations, newest first (primary access path) |
| `_id` (default) + `user_id` filter | Ownership-checked single fetch (`find_one({_id, user_id})`) |

Indexes are ensured lazily on first store use (idempotent `ensure_indexes()`), so no change to app startup is required. (Future: a TTL index could expire stale conversations — not enabled in Phase 2.)

## 5. Retrieval Rules

- **`load_or_create(ctx, conversation_id)`**
  - `conversation_id` provided → `find_one({_id, user_id})`; if absent → raise *not found* (never silently create a different conversation).
  - `conversation_id` omitted → create a new owned conversation.
- **`list_for_user(ctx)`** → `find({user_id}).sort(updated_at desc).limit(50)` → `ConversationSummary[]` (id, title, updated_at) only — never full transcripts in the list view.
- **`get_history(ctx, id)`** → ownership-checked full conversation.
- **`delete_conversation(ctx, id)`** → `delete_one({_id, user_id})`; 0 deleted → *not found*.

## 6. Context Windowing & Summarization

- The model receives, per turn: the **rolling summary** (if any) + the **last `MAX_WINDOW_MESSAGES`** user/assistant messages — not the whole transcript.
- When `message_count` exceeds `SUMMARY_TRIGGER`, messages older than the window are folded into `summary` (cheap utility model) and `summary_upto` advances.
- This bounds prompt size and cost while preserving long-conversation continuity.

Config (in `assistant/config.py`): `MAX_WINDOW_MESSAGES`, `SUMMARY_TRIGGER`, `CONVERSATION_COLLECTION`.

## 7. Privacy / Security Summary

- Owner-scoped queries everywhere (keystone).
- Sensitive fields never enter `messages` (tool serializers already whitelist).
- Conversation content is user data — treated as confidential; not logged verbatim outside the collection.

*End of contract.*
