"""Platform-data tools: session templates, media library, notifications,
activity logs. These widen the assistant's database link so questions about
platform records beyond the learner/admin core (sessions, scores, batches...)
are answerable too — each with the same server-side RBAC scoping.
"""
from __future__ import annotations

import re
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.config import config
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.security.pii import redact
from app.assistant.tools.registry import tool
from app.db.mongodb import get_collection


def _safe_regex(text: str) -> dict:
    """Case-insensitive Mongo regex from user text, metacharacters escaped."""
    return {"$regex": re.escape(text.strip()), "$options": "i"}


def _clamp(value, default: int, maximum: int) -> int:
    """Forgiving limit coercion: a hallucinated non-numeric value falls back to
    the default instead of failing the whole tool call."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n or default, maximum))


@tool(
    name="get_session_templates",
    description=(
        "List the reusable session templates (coaching session blueprints): title, "
        "topic, description, and how many tasks and assessments each contains. Use "
        "for 'what session templates exist', 'which template covers X', 'how many "
        "quizzes does template Y have'. Staff only — templates contain assessment "
        "answer keys, so they are never exposed to learners (and this tool returns "
        "only summaries, never the questions or answers)."
    ),
    allowed_roles=["AD", "SA"],
    parameters={
        "name": {"type": "string", "description": "Optional title/topic keyword filter"},
        "limit": {"type": "integer", "description": "Max templates to return (default 20, max 50)"},
    },
)
async def get_session_templates(ctx: UserContext, name: Optional[str] = None, limit: int = 20) -> ToolResult:
    limit = _clamp(limit, 20, 50)
    query: dict = {}
    if name and name.strip():
        rx = _safe_regex(name)
        query = {"$or": [{"title": rx}, {"topic": rx}]}

    docs = (
        await get_collection("session_templates")
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    items = []
    for d in docs:
        tasks = d.get("tasks") or []
        assessments = d.get("assessments") or []
        task_titles = []
        for t in tasks[:10]:
            title = t if isinstance(t, str) else (t.get("title") or t.get("name")) if isinstance(t, dict) else None
            if title:
                task_titles.append(str(title)[:80])
        items.append({
            "title": d.get("title"),
            "topic": d.get("topic"),
            "description": (d.get("description") or "")[:200],
            "task_count": len(tasks),
            "task_titles": task_titles,
            "assessment_count": len(assessments),
            "assessments": [
                {
                    "question_count": len(a.get("questions") or []),
                    "passing_score": a.get("passing_score"),
                }
                for a in assessments if isinstance(a, dict)
            ],
        })

    return ToolResult.ok(
        "get_session_templates",
        {"templates": items, "total_returned": len(items)},
        sources=["session_templates"],
        count=len(items),
        scope_applied="staff:org-wide",
    )


def _content_excerpt(text: str, query: str, width: int = 600) -> str:
    """A window of a file's extracted text AROUND the first query-term match,
    so the model can answer from what's actually inside the file."""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for term in re.findall(r"[a-z0-9]+", (query or "").lower()):
        if len(term) > 3:
            pos = low.find(term)
            if pos != -1:
                break
    if pos <= width // 4:
        return text[:width]
    start = max(0, pos - width // 3)
    tail = "..." if start + width < len(text) else ""
    return "..." + text[start:start + width] + tail


async def _media_vector_search(query: str, media_type: Optional[str], limit: int):
    """Semantic search over media_chunks → enriched file items (best chunk per
    file, in vector-rank order). Returns None if vectors are unavailable, or []
    if nothing relevant matched — both → keyword fallback."""
    try:
        from app.assistant.rag.embeddings import embed_query
        from app.assistant.rag.vector_store import vector_search

        vec = await embed_query(query)
        if not vec:
            return None
        filt = {"media_type": media_type.strip().lower()} if media_type and media_type.strip() else None
        # Floor weak "nearest neighbour" hits so a pure listing query ("what PDFs
        # do we have") falls through to the keyword/metadata path instead.
        chunks = await vector_search(
            config.MEDIA_CHUNK_COLLECTION, config.MEDIA_VECTOR_INDEX, vec,
            limit * 4, filter_expr=filt, min_score=0.20,
        )
        if not chunks:
            return []

        best: dict = {}
        for c in chunks:  # vector results are score-desc; keep first (best) per file
            mid = c.get("media_id")
            if mid and mid not in best:
                best[mid] = c
        ordered_ids = list(best.keys())[:limit]

        oids = []
        for m in ordered_ids:
            try:
                oids.append(ObjectId(m))
            except (InvalidId, TypeError):
                pass
        docs = await get_collection("media_library").find({"_id": {"$in": oids}}).to_list(len(oids))
        by_id = {str(d["_id"]): d for d in docs}

        items = []
        for mid in ordered_ids:  # preserve vector ranking
            d = by_id.get(mid)
            c = best[mid]
            base = d or {"name": c.get("name"), "file_name": c.get("file_name"),
                         "media_type": c.get("media_type")}
            items.append({
                "name": base.get("name"),
                "media_type": base.get("media_type"),
                "file_name": base.get("file_name"),
                "size_bytes": base.get("size"),
                "folder": base.get("folder"),
                "tags": base.get("tags") or [],
                "uploaded_at": base.get("created_at"),
                "content_excerpt": (c.get("content") or "")[:600],
                "match_score": round(float(c.get("vector_score") or 0.0), 3),
            })
        return items
    except Exception as e:  # noqa: BLE001
        print(f"[rag] search_media_library vector path failed: {e}")
        return None


@tool(
    name="search_media_library",
    description=(
        "Search the shared Media Library — by file name, tag, type, AND by the "
        "TEXT INSIDE each file: document text (PDF/Word/Excel) and the speech "
        "transcript of audio/video. Returns matching files with a content excerpt, "
        "so you can ANSWER questions about what a file says, not just whether it "
        "exists. Use for 'is there a video about X', 'what PDFs do we have', 'what "
        "does the <file> say about Y', 'which recording talks about Z', 'summarize "
        "the <file>'. For the full file, tell the user to open the Media Library "
        "page."
    ),
    # Staff-only: the Media Library is a staff resource (sidebar gated to
    # superadmin/admin/coach/staff), and full file CONTENTS are now exposed —
    # learners must not read them via chat.
    allowed_roles=["AD", "SA"],
    parameters={
        "query": {"type": "string", "description": "Keyword(s) to search names, tags, and file contents for"},
        "media_type": {
            "type": "string",
            "description": "Optional filter: video, audio, pdf, document, image, or other",
        },
        "limit": {"type": "integer", "description": "Max files to return (default 20, max 50)"},
    },
)
async def search_media_library(
    ctx: UserContext, query: Optional[str] = None, media_type: Optional[str] = None, limit: int = 20
) -> ToolResult:
    limit = _clamp(limit, 20, 50)

    # Vector-first when there's a content query; falls back to keyword below.
    if query and query.strip():
        vec_items = await _media_vector_search(query, media_type, limit)
        if vec_items:
            return ToolResult.ok(
                "search_media_library",
                {"files": vec_items, "total_returned": len(vec_items)},
                sources=["media_library"],
                count=len(vec_items),
                scope_applied="shared-library",
            )

    mongo_q: dict = {}
    if media_type and media_type.strip():
        mongo_q["media_type"] = media_type.strip().lower()
    if query and query.strip():
        rx = _safe_regex(query)
        # Content_text included → questions about what's INSIDE files match here.
        mongo_q["$or"] = [{"name": rx}, {"file_name": rx}, {"tags": rx},
                          {"description": rx}, {"content_text": rx}]

    docs = (
        await get_collection("media_library")
        .find(mongo_q)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    items = []
    for d in docs:
        item = {
            "name": d.get("name"),
            "media_type": d.get("media_type"),
            "file_name": d.get("file_name"),
            "size_bytes": d.get("size"),
            "folder": d.get("folder"),
            "tags": d.get("tags") or [],
            "uploaded_at": d.get("created_at"),
        }
        if d.get("content_status"):
            item["content_status"] = d.get("content_status")
        excerpt = _content_excerpt(d.get("content_text") or "", query or "")
        if excerpt:
            item["content_excerpt"] = excerpt
        items.append(item)

    return ToolResult.ok(
        "search_media_library",
        {"files": items, "total_returned": len(items)},
        sources=["media_library"],
        count=len(items),
        scope_applied="shared-library",
    )


@tool(
    name="get_my_notifications",
    description=(
        "Return the caller's own in-app notifications: unread count and the most "
        "recent items (title, message, type, read/unread, date). Use for 'any new "
        "notifications', 'what did I miss', 'do I have unread alerts'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "only_unread": {"type": "boolean", "description": "Return only unread notifications"},
        "limit": {"type": "integer", "description": "Max notifications to return (default 10, max 30)"},
    },
)
async def get_my_notifications(ctx: UserContext, only_unread: bool = False, limit: int = 10) -> ToolResult:
    limit = _clamp(limit, 10, 30)
    col = get_collection("in_app_notifications")

    base = {"user_id": ctx.user_id}
    unread_count = await col.count_documents({**base, "is_read": False})

    q = {**base, "is_read": False} if only_unread else base
    docs = await col.find(q).sort("created_at", -1).limit(limit).to_list(limit)
    items = [
        {
            "title": d.get("title"),
            "message": (d.get("message") or "")[:300],
            "type": d.get("type"),
            "is_read": bool(d.get("is_read")),
            "created_at": d.get("created_at"),
        }
        for d in docs
    ]

    return ToolResult.ok(
        "get_my_notifications",
        {"unread_count": unread_count, "notifications": items},
        sources=["in_app_notifications"],
        count=len(items),
        scope_applied=f"personal:{ctx.user_id}",
    )


@tool(
    name="get_activity_logs",
    description=(
        "Return recent platform activity / audit-log entries (who did what, in "
        "which module, when). Superadmin only. Use for 'what happened recently', "
        "'recent activity in the Users module', 'who changed X'."
    ),
    allowed_roles=["SA"],
    parameters={
        "module": {"type": "string", "description": "Optional module filter, e.g. Users, Companies, Calendar"},
        "limit": {"type": "integer", "description": "Max entries to return (default 20, max 50)"},
    },
)
async def get_activity_logs(ctx: UserContext, module: Optional[str] = None, limit: int = 20) -> ToolResult:
    limit = _clamp(limit, 20, 50)
    q: dict = {}
    if module and module.strip():
        q["module"] = _safe_regex(module)

    docs = (
        await get_collection("activity_logs")
        .find(q)
        .sort("timestamp", -1)
        .limit(limit)
        .to_list(limit)
    )
    # PII stance: names and actions, never contact details. The user_email field
    # is omitted AND the free-text details are redact()ed — log writers embed
    # emails in the details string (e.g. "OTP generated for <email>").
    items = [
        {
            "user_name": d.get("user_name"),
            "action": d.get("action"),
            "module": d.get("module"),
            "details": redact(str(d.get("details") or ""))[:200],
            "timestamp": d.get("timestamp"),
        }
        for d in docs
    ]

    return ToolResult.ok(
        "get_activity_logs",
        {"entries": items, "total_returned": len(items)},
        sources=["activity_logs"],
        count=len(items),
        scope_applied="superadmin:org-wide",
    )
