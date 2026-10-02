"""Query rewriting layer.

Normalizes vague/elliptical queries and resolves follow-up references using the
conversation summary, before tool selection. A cheap heuristic decides whether a
rewrite is even needed, so explicit questions skip the extra LLM call.

Returns: {"rewritten_query": str, "intent_hint": str | None, "rewritten": bool}
"""
from __future__ import annotations

# Pronouns / ellipsis markers that suggest the query depends on prior context.
_FOLLOWUP_MARKERS = {
    "it", "that", "this", "those", "these", "them", "they", "he", "she",
    "there", "then", "same", "one", "ones", "another", "more",
}

# Words that make a short message self-contained and org-wide ("show all
# batches", "list every company", "platform overview"). When present without a
# follow-up marker, the message is a complete command — NOT an ellipsis — so it
# must never be rewritten with scope borrowed from the previous turn (that was
# turning "show all batches" into "show all batches for <prev company>").
_GLOBALIZERS = {
    "all", "every", "everyone", "everything", "list", "total", "overall",
    "platform", "entire", "whole",
}

# Greetings / gratitude / sign-offs. A message that is ONLY these is a social
# turn, not a question: it must pass through untouched so the main model can
# greet/acknowledge instead of the rewriter inventing a question from context
# (which is what replayed the previous answer for "hi").
_SOCIAL_WORDS = {
    "hi", "hii", "hello", "helo", "hey", "heya", "yo", "hiya", "greetings",
    "morning", "afternoon", "evening", "namaste", "hola",
    "thanks", "thank", "thankyou", "thx", "thnx", "ty", "cheers",
    "bye", "goodbye", "ok", "okay", "cool", "great", "nice", "welcome",
}


def _tokens(message: str) -> list:
    """Lower-cased word tokens with surrounding punctuation/quotes stripped."""
    return [w.strip("?.,!\"'`-/()").lower() for w in (message or "").split()]


def is_social(message: str) -> bool:
    """True when the WHOLE message is just greeting/gratitude/sign-off words
    (e.g. 'hi', 'thanks!', '"Hi" / "Hello"'). Mixed messages like 'hi, how do I
    create a batch?' are NOT social — they carry a real question."""
    toks = [t for t in _tokens(message) if t]
    return bool(toks) and all(t in _SOCIAL_WORDS for t in toks)


def _needs_rewrite(message: str) -> bool:
    words = [w for w in _tokens(message) if w]
    if not words:
        return False
    if is_social(message):                    # greeting/thanks → never rewrite
        return False
    if any(w in _FOLLOWUP_MARKERS for w in words):  # genuine reference → resolve
        return True
    if any(w in _GLOBALIZERS for w in words):  # self-contained global command → leave
        return False
    return len(words) <= 4                     # very short & elliptical → likely needs context


async def rewrite(
    llm,
    message: str,
    conversation_summary: str = "",
    recent_context: str = "",
    meter=None,
) -> dict:
    """Resolve the message into a self-contained query when needed."""
    if not _needs_rewrite(message):
        return {"rewritten_query": message, "intent_hint": None, "rewritten": False}

    context = "\n".join(p for p in (conversation_summary, recent_context) if p)
    if not context.strip():
        # First message of a conversation: there is nothing to resolve against,
        # and rewriting without context derails it (e.g. "hi" was being turned
        # into "What would you like to discuss?", which the main model then
        # treated as the user's actual question). Pass it through unchanged so
        # direct first-attempt questions are answered as asked.
        return {"rewritten_query": message, "intent_hint": None, "rewritten": False}

    prompt = (
        "Rewrite the user's latest message into a single self-contained question, "
        "resolving ONLY pronouns or references that clearly point at something in "
        "the conversation context (it, that, this, them, the same one). "
        "Do NOT add any company name, person, batch, filter, or scope that the "
        "user did not mention in THIS message — e.g. if the latest message is "
        "'show all batches', return 'show all batches', never 'show all batches "
        "for <some company discussed earlier>'. "
        "If the message is already self-contained, a greeting, or the context "
        "does not clarify it, return the message exactly as it is. "
        "Return ONLY the rewritten question, nothing else.\n\n"
        f"Conversation context:\n{context}\n\n"
        f"Latest message: {message}"
    )
    rewritten = await llm.utility_complete(prompt, max_tokens=80, meter=meter)
    rewritten = (rewritten or "").strip() or message
    return {"rewritten_query": rewritten, "intent_hint": None, "rewritten": rewritten != message}
