"""Conversation context windowing.

Builds the bounded message window sent to the LLM: the rolling summary (if any)
followed by the last `MAX_WINDOW_MESSAGES` user/assistant turns. Tool/system
messages from history are not replayed.
"""
from __future__ import annotations

from typing import List

from app.assistant.config import config
from app.assistant.schemas.conversation import Conversation


def build_window(conversation: Conversation) -> List[dict]:
    """Return prior-turn messages (summary + recent) for prompt assembly."""
    window: List[dict] = []

    if conversation.summary:
        window.append(
            {
                "role": "system",
                "content": f"Summary of the earlier conversation:\n{conversation.summary}",
            }
        )

    recent = conversation.messages[-config.MAX_WINDOW_MESSAGES:]
    for msg in recent:
        if msg.role in ("user", "assistant"):
            window.append({"role": msg.role, "content": msg.content})

    return window


def needs_summary(conversation: Conversation) -> bool:
    """True when the transcript has grown past the summarization trigger."""
    return len(conversation.messages) > config.SUMMARY_TRIGGER
