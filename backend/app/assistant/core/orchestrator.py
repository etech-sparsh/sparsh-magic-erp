"""The agent loop — the conductor.

Phase 2 flow:

    load/create conversation (owner-scoped)
      → build context window (rolling summary + recent turns)
      → query rewrite (resolve follow-ups / vague queries, when needed)
      → build system prompt
      → expose only role-permitted tools
      → tool-calling loop (timeout + error isolation per tool)
      → final answer  [non-streamed: returned | streamed: SSE token events]
      → persist turn; auto-title first exchange; roll summary when long

Two entry points share the same tool resolution:
  * handle_message()  — non-streaming, returns AskResponse
  * stream_message()  — async generator of SSE event strings
"""
from __future__ import annotations

import json
import time
import traceback
from typing import AsyncIterator, List, Optional, Tuple

from app.assistant.config import config
from app.assistant.core import context_manager, query_rewriter
from app.assistant.core.llm_client import LLMClient, UsageMeter
from app.assistant.core.prompt_builder import build_system_prompt
from app.assistant.memory import conversation_store, summarizer
from app.assistant.observability import cost
from app.assistant.observability.correlation import get_correlation_id
from app.assistant.observability.logging import log_event
from app.assistant.observability.metrics import metrics
from app.assistant.schemas.chat import AskResponse
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.conversation import Conversation
from app.assistant.security import guardrails
from app.assistant.tools import registry


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class Orchestrator:
    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()
        registry.register_all()  # idempotent

    # ── Shared setup ──────────────────────────────────────────────────────
    async def _prepare(
        self, ctx: UserContext, message: str, conversation_id: Optional[str], meter: UsageMeter,
        edit_from_index: Optional[int] = None, attachment_ids: Optional[List[str]] = None,
    ) -> Tuple[Conversation, List[dict], List[dict], str, list]:
        convo = await conversation_store.load_or_create(ctx, conversation_id)
        # Edit-and-resend: drop the edited turn and everything after it before
        # building context, so stale history isn't replayed to the model.
        if edit_from_index is not None:
            await conversation_store.truncate_messages(convo, edit_from_index)
        window = context_manager.build_window(convo)

        messages = [{"role": "system", "content": build_system_prompt(ctx)}]

        # Input guardrail: detect (don't hard-block) likely prompt injection.
        if config.GUARDRAILS_ENABLED:
            screen = guardrails.screen_input(message)
            if screen["flagged"]:
                metrics.input_flagged += 1
                log_event("input_flagged", reason=screen["reason"], user=ctx.user_id)
                messages.append(guardrails.reinforcement_note())

        messages.extend(window)

        has_attachments = bool(config.ATTACHMENTS_ENABLED and attachment_ids)

        # An attachments-only turn (empty/whitespace message) defaults to a
        # summary request. We skip the query rewriter entirely here: with no
        # message it would otherwise hallucinate a question and derail the
        # answer instead of describing the uploaded file.
        if not (message or "").strip() and has_attachments:
            effective = config.DEFAULT_ATTACHMENT_PROMPT
        else:
            recent = "\n".join(
                f"{m.role}: {m.content}" for m in convo.messages[-4:]
            )
            rw = await query_rewriter.rewrite(
                self.llm, message, convo.summary or "", recent, meter=meter
            )
            effective = rw["rewritten_query"]

        # Multi-modal: fold uploaded-file content into this turn. Text is appended
        # to the (rewritten) query; images become vision blocks. No attachments →
        # the message stays a plain string, exactly as before.
        attach_metas: list = []
        if has_attachments:
            from app.assistant.files import service as attachment_service
            attach = await attachment_service.build_attachment_context(
                ctx, attachment_ids, convo.id, query=effective
            )
            attach_metas = attach["metas"]
            user_text = effective + (attach["text_block"] or "")
            if attach["images"]:
                content = [{"type": "text", "text": user_text}]
                for img in attach["images"]:
                    content.append({"type": "image_url",
                                    "image_url": {"url": img, "detail": "auto"}})
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "user", "content": user_text})
        else:
            # Make files uploaded earlier in THIS conversation available on later
            # turns (the composer tray clears after each send) WITHOUT letting them
            # bleed into unrelated questions. The file text goes in a system message
            # framed as optional reference: used only when the question is about the
            # document; ignored for platform questions (dashboard, scores, sessions,
            # batches, Support Engine modules), which use the structured tools.
            from app.assistant.files import attachment_store
            from app.assistant.files import service as attachment_service
            prior = await attachment_store.list_for_conversation(ctx, convo.id) if convo.id else []
            ref_images = []
            for d in prior:
                for img in (d.get("images") or []):
                    if len(ref_images) < config.MAX_IMAGES_PER_TURN:
                        ref_images.append(img)
            # Retrieval-first for large prior files; full text for small ones.
            ref_parts = await attachment_service.gather_reference_parts(prior, convo.id, effective)
            if ref_parts:
                messages.append({
                    "role": "system",
                    "content": (
                        "The user uploaded the file(s) below earlier in THIS "
                        "conversation. Their text is an APPROVED source — use it to "
                        "answer any question about the document or its contents, "
                        "including questions phrased as 'my ...' that refer to what is "
                        "in the file (e.g. the person's internships, skills, projects, "
                        "education, experience). Do NOT say you can't access it. "
                        "ONLY ignore this file and use the platform tools instead when "
                        "the question is about live platform data: the dashboard, quiz "
                        "scores, sessions, batches, attendance, or Support Engine "
                        "modules.\n\n" + "\n\n".join(ref_parts)
                    ),
                })
            if prior:
                messages.append({
                    "role": "system",
                    "content": (
                        "UPLOADED-FILE PRIORITY MODE is active because the user "
                        "uploaded file(s) in THIS conversation. This mode does NOT "
                        "narrow what you may answer — Sparsh platform questions stay "
                        "FULLY answerable, exactly as in a chat with no file. Resolve "
                        "each question in this exact order, stopping at the first step "
                        "that applies:\n"
                        "(1) UPLOADED FILE FIRST — if the question is about the "
                        "uploaded file, answer from its text, images, transcripts, "
                        "and search_uploaded_files results. If the excerpts are not "
                        "enough, call search_uploaded_files before saying it is not "
                        "found.\n"
                        "(2) SPARSH PLATFORM SECOND — if the question is about the "
                        "Sparsh platform/system (the dashboard, registered entities, "
                        "platform metrics, batches, companies, users, sessions, "
                        "attendance, scores, Support Engine, other modules, or how "
                        "the platform works), ANSWER IT using the structured data "
                        "tools and the App Guide — just as you would with no file "
                        "attached. A document being present NEVER makes a Sparsh "
                        "question 'out of context', and you must NOT tell the user "
                        "you can only answer from the document. NEVER refuse a Sparsh "
                        "question just because it is not in the uploaded file.\n"
                        "(3) OUT OF CONTEXT LAST — only if the question is about "
                        "NEITHER the uploaded file NOR the Sparsh platform (e.g. "
                        "general world knowledge or unrelated trivia), reply with the "
                        "standard short out-of-context message.\n"
                        "Never answer from general knowledge, training knowledge, or "
                        "assumptions."
                    ),
                })
            if ref_images:
                content = [{"type": "text", "text": effective}]
                for img in ref_images:
                    content.append({"type": "image_url", "image_url": {"url": img, "detail": "auto"}})
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "user", "content": effective})

        return convo, messages, registry.openai_schema_for_role(ctx.role), effective, attach_metas

    async def _run_tools(self, ctx, spec_calls, messages, sources, tools_used, attributions) -> None:
        """Execute a batch of tool calls and append their results to the transcript."""
        for call in spec_calls:
            name = call["name"]
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            spec = registry.get_tool(name)
            if spec is None:
                payload = {"success": False, "error": "Unknown tool"}
                attributions.append({"tool": name, "sources": [], "scope_applied": None,
                                     "success": False, "count": None})
            else:
                result = await registry.execute_tool(spec, ctx, args)
                tools_used.append(name)
                if result.meta.sources:
                    sources.update(result.meta.sources)
                attributions.append({
                    "tool": result.meta.tool,
                    "sources": result.meta.sources,
                    "scope_applied": result.meta.scope_applied,
                    "success": result.success,
                    "count": result.meta.count,
                })
                payload = result.for_llm()
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id") or name, "content": json.dumps(payload, default=str)}
            )

    async def _persist(self, convo, user_msg, answer, meter, attributions=None, attachments=None) -> None:
        await conversation_store.append_turn(
            convo, user_msg, answer, attributions=attributions, attachments=attachments
        )
        # Reload-light: reflect the two new messages locally for title/summary decisions.
        convo.messages.append(_quick_msg("user", user_msg))
        convo.messages.append(_quick_msg("assistant", answer))

        if not convo.title:
            title = await summarizer.generate_title(self.llm, convo, meter=meter)
            await conversation_store.set_title(convo, title)
            convo.title = title

        if context_manager.needs_summary(convo):
            new_summary = await summarizer.roll_summary(self.llm, convo, meter=meter)
            if new_summary:
                await conversation_store.set_summary(
                    convo, new_summary, len(convo.messages) - config.MAX_WINDOW_MESSAGES
                )

    # ── Non-streaming ─────────────────────────────────────────────────────
    async def handle_message(
        self, ctx: UserContext, message: str, conversation_id: Optional[str] = None,
        edit_from_index: Optional[int] = None, attachment_ids: Optional[List[str]] = None,
    ) -> AskResponse:
        cid = get_correlation_id()
        started = time.perf_counter()
        meter = UsageMeter()
        errored = False
        convo, messages, tool_schema, _, attach_metas = await self._prepare(
            ctx, message, conversation_id, meter,
            edit_from_index=edit_from_index, attachment_ids=attachment_ids,
        )

        sources: set = set()
        tools_used: List[str] = []
        attributions: List[dict] = []
        answer = ""

        for _ in range(config.MAX_TOOL_ITERATIONS):
            ai_msg = await self.llm.complete(messages, tools=tool_schema or None, meter=meter)
            tool_calls = getattr(ai_msg, "tool_calls", None)
            if not tool_calls:
                answer = ai_msg.content or ""
                break
            messages.append(_assistant_tool_msg(ai_msg.content, tool_calls))
            await self._run_tools(
                ctx,
                [_call_dict(c) for c in tool_calls],
                messages,
                sources,
                tools_used,
                attributions,
            )
        else:
            errored = True
            answer = (
                "I wasn't able to finish answering that within the allowed steps. "
                "Could you rephrase or narrow the question?"
            )

        if config.GUARDRAILS_ENABLED:
            vo = guardrails.validate_output(answer)
            if not vo["ok"]:
                log_event("output_flagged", issues=vo["issues"], user=ctx.user_id)

        await self._persist(convo, message, answer, meter, attributions=attributions,
                            attachments=attach_metas)
        cost_estimate = await cost.record_cost(cid, ctx.user_id, meter)

        duration_ms = (time.perf_counter() - started) * 1000
        metrics.record_request(duration_ms, error=errored)
        log_event("request_complete", user=ctx.user_id, ms=round(duration_ms, 2),
                  tools=tools_used, cost_usd=cost_estimate["total_usd"])

        return AskResponse(
            conversation_id=convo.id,
            answer=answer,
            sources=sorted(sources),
            meta={
                "phase": "4",
                "correlation_id": cid,
                "tools_used": tools_used,
                "attributions": attributions,
                "usage": meter.as_dict(),
                "cost": cost_estimate,
                "latency_ms": round(duration_ms, 2),
                "title": convo.title,
            },
        )

    # ── Streaming (SSE) ───────────────────────────────────────────────────
    async def stream_message(
        self, ctx: UserContext, message: str, conversation_id: Optional[str] = None,
        edit_from_index: Optional[int] = None, attachment_ids: Optional[List[str]] = None,
    ) -> AsyncIterator[str]:
        cid = get_correlation_id()
        started = time.perf_counter()
        meter = UsageMeter()
        try:
            convo, messages, tool_schema, _, attach_metas = await self._prepare(
                ctx, message, conversation_id, meter,
                edit_from_index=edit_from_index, attachment_ids=attachment_ids,
            )
            yield _sse("meta", {"conversation_id": convo.id, "correlation_id": cid})

            sources: set = set()
            tools_used: List[str] = []
            attributions: List[dict] = []
            answer_parts: List[str] = []

            for _ in range(config.MAX_TOOL_ITERATIONS):
                tool_calls = None
                streamed_any = False
                async for event, payload in self.llm.complete_stream(
                    messages, tools=tool_schema or None, meter=meter
                ):
                    if event == "content" and payload:
                        streamed_any = True
                        answer_parts.append(payload)
                        yield _sse("token", {"text": payload})
                    elif event == "tool_calls":
                        tool_calls = payload

                if tool_calls and not streamed_any:
                    messages.append(_assistant_tool_msg(None, tool_calls, from_stream=True))
                    for tc in tool_calls:
                        yield _sse("tool", {"name": tc.get("name")})
                    await self._run_tools(ctx, tool_calls, messages, sources, tools_used, attributions)
                    continue
                break  # produced the final answer

            answer = "".join(answer_parts)
            if config.GUARDRAILS_ENABLED:
                vo = guardrails.validate_output(answer)
                if not vo["ok"]:
                    log_event("output_flagged", issues=vo["issues"], user=ctx.user_id)

            await self._persist(convo, message, answer, meter, attributions=attributions,
                                attachments=attach_metas)
            cost_estimate = await cost.record_cost(cid, ctx.user_id, meter)

            duration_ms = (time.perf_counter() - started) * 1000
            metrics.record_request(duration_ms, error=False)
            log_event("request_complete", user=ctx.user_id, ms=round(duration_ms, 2),
                      tools=tools_used, cost_usd=cost_estimate["total_usd"], streamed=True)

            yield _sse(
                "done",
                {
                    "conversation_id": convo.id,
                    "correlation_id": cid,
                    "sources": sorted(sources),
                    "tools_used": tools_used,
                    "attributions": attributions,
                    "usage": meter.as_dict(),
                    "cost": cost_estimate,
                    "latency_ms": round(duration_ms, 2),
                    "title": convo.title,
                },
            )
        except Exception as exc:
            # A streamed turn that blows up otherwise just severs the SSE
            # connection, which the UI shows as an opaque "something went wrong".
            # Log the full traceback server-side AND surface the real error in the
            # chat so failures are diagnosable instead of silent.
            tb = traceback.format_exc()
            print(f"[ASSISTANT STREAM ERROR] cid={cid} {type(exc).__name__}: {exc}\n{tb}")
            log_event("stream_error", user=ctx.user_id, error=f"{type(exc).__name__}: {exc}")
            metrics.record_request((time.perf_counter() - started) * 1000, error=True)
            yield _sse("token", {"text": f"\n\n⚠️ Assistant error: {type(exc).__name__}: {exc}"})
            yield _sse(
                "done",
                {
                    "conversation_id": conversation_id or "",
                    "correlation_id": cid,
                    "sources": [],
                    "tools_used": [],
                    "attributions": [],
                    "usage": meter.as_dict(),
                    "cost": {"total_usd": 0.0, "by_model": {}},
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "title": None,
                },
            )


# ── small helpers ─────────────────────────────────────────────────────────
def _call_dict(call) -> dict:
    return {
        "id": call.id,
        "name": call.function.name,
        "arguments": call.function.arguments,
    }


def _assistant_tool_msg(content, tool_calls, from_stream: bool = False) -> dict:
    if from_stream:
        items = [
            {"id": c.get("id") or c.get("name"), "type": "function",
             "function": {"name": c.get("name"), "arguments": c.get("arguments") or "{}"}}
            for c in tool_calls
        ]
    else:
        items = [
            {"id": c.id, "type": "function",
             "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in tool_calls
        ]
    return {"role": "assistant", "content": content, "tool_calls": items}


class _QuickMsg:
    __slots__ = ("role", "content")

    def __init__(self, role, content):
        self.role = role
        self.content = content


def _quick_msg(role, content) -> _QuickMsg:
    return _QuickMsg(role, content)
