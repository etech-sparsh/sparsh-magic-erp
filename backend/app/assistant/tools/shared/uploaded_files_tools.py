"""Shared tool: search_uploaded_files.

Lets the model pull more content from files attached to the CURRENT conversation
when the up-front injected context was truncated (large PDFs, spreadsheets, ZIPs).
Scoped to the conversation's own attachment chunks via the keyword retriever in
app/assistant/files/attachment_store.py — never reaches another user's data.
"""
from __future__ import annotations

from app.assistant.files import attachment_store
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool


@tool(
    name="search_uploaded_files",
    description=(
        "Search the text of files the user uploaded in THIS conversation. Use it "
        "when the attached-file context looks truncated or you need a specific "
        "detail (a number, clause, definition, or section) from a large document, "
        "spreadsheet, audio/video transcript, image OCR text, or archive. In "
        "uploaded-file mode, if this search returns no support for the user's "
        "question, say the answer was not found in the uploaded file(s); do not "
        "answer from general knowledge. Returns matching snippets with metadata."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "query": {"type": "string", "description": "What to look for in the uploaded files"},
        "conversation_id": {
            "type": "string",
            "description": "The current conversation id (provided in context)",
        },
    },
    required=["query", "conversation_id"],
)
async def search_uploaded_files(ctx: UserContext, query: str, conversation_id: str) -> ToolResult:
    chunks = await attachment_store.search_chunks(conversation_id, query, limit=12)
    snippets = [
        {
            "filename": c.get("filename"),
            "content": c.get("content", ""),
            "page_start": c.get("page_start"),
            "page_end": c.get("page_end"),
            "score": c.get("_retrieval_score") or c.get("vector_score"),
        }
        for c in chunks
    ]
    filenames = sorted({c["filename"] for c in snippets if c.get("filename")})
    return ToolResult.ok(
        "search_uploaded_files",
        {"snippets": snippets},
        sources=["uploaded_files"] + filenames,
        count=len(snippets),
        scope_applied=f"conversation:{conversation_id}",
    )
