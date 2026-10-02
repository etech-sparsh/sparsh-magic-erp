"""Shared knowledge tool: search_knowledge (RAG bridge)."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import knowledge_service
from app.assistant.tools.registry import tool


@tool(
    name="search_knowledge",
    description=(
        "Search the knowledge base / learning materials — the content of EVERY "
        "file uploaded to Support Engine projects: PDFs, Word/Excel documents, "
        "and the transcripts of uploaded audio/video recordings. Use for "
        "conceptual questions ('what is X', 'explain Y') AND for questions about "
        "uploaded files of any type ('summarize the audio in project X', 'what "
        "does the recording say about Z', 'what's in the uploaded PDF'). Returns "
        "cited document snippets. NOT for the user's personal records."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={"query": {"type": "string", "description": "What to look up in the knowledge base"}},
    required=["query"],
)
async def search_knowledge(ctx: UserContext, query: str) -> ToolResult:
    retrieval = await knowledge_service.search(ctx, query)
    data = retrieval.model_dump()

    # Attribution: KnowledgeBase + the cited document titles flow into sources.
    titles = sorted({s["title"] for s in data["sources"] if s.get("title")})
    return ToolResult.ok(
        "search_knowledge",
        data,
        sources=["KnowledgeBase"] + titles,
        count=len(data["sources"]),
        scope_applied=f"knowledge:{normalize_scope(ctx)}",
    )


def normalize_scope(ctx: UserContext) -> str:
    from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role

    return "all" if normalize_role(ctx.role) in (ROLE_SA, ROLE_AD) else f"projects_of:{ctx.user_id}"
