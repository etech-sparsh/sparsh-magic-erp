"""Auto-title generation and rolling conversation summarization.

Both use the cheap utility model via the injected LLM client. Kept free of direct
OpenAI imports so the orchestrator can pass a fake client in tests.
"""
from __future__ import annotations

from typing import Optional

from app.assistant.config import config
from app.assistant.schemas.conversation import Conversation


async def generate_title(llm, conversation: Conversation, meter=None) -> str:
    """Short (≤6 word) title from the first user message."""
    first_user = next((m.content for m in conversation.messages if m.role == "user"), "")
    if not first_user:
        return "New conversation"
    prompt = (
        "Generate a concise conversation title (max 6 words, no quotes, no trailing "
        f"punctuation) for this first user message:\n\n{first_user}"
    )
    title = await llm.utility_complete(prompt, max_tokens=20, meter=meter)
    title = title.strip().strip('"').strip()
    return title[:60] or "New conversation"


async def roll_summary(llm, conversation: Conversation, meter=None) -> Optional[str]:
    """Fold messages older than the window into an updated rolling summary.

    Returns the new summary text (caller persists it), or None if nothing to do.
    """
    overflow = conversation.messages[: -config.MAX_WINDOW_MESSAGES]
    if not overflow:
        return None

    transcript = "\n".join(f"{m.role}: {m.content}" for m in overflow)
    base = f"Existing summary:\n{conversation.summary}\n\n" if conversation.summary else ""
    prompt = (
        f"{base}Update the running summary to incorporate these earlier messages. "
        f"Keep it to 2-4 sentences, preserving key facts and the user's goals:\n\n{transcript}"
    )
    return await llm.utility_complete(prompt, max_tokens=200, meter=meter)
