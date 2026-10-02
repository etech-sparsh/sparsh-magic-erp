"""LLM provider abstraction.

Wraps the OpenAI client behind a stable interface so models/providers can be
swapped. The SDK is imported lazily so the module/router can be imported in
environments without `openai` or an API key (e.g. the fake-LLM test harness).

Three call shapes:
  * complete()         — primary model, tool-calling (non-streamed planning)
  * complete_stream()  — primary model, streamed; yields normalized events
  * utility_complete() — cheap model, single-turn (titles, summaries, rewrites)

Token usage is accumulated into a caller-supplied UsageMeter so accounting is
per-request and concurrency-safe (no shared mutable state on the client).
"""
from __future__ import annotations

from typing import AsyncIterator, List, Optional, Tuple

from app.assistant.config import config
from app.config.settings import settings


class UsageMeter:
    """Per-request token accounting."""

    def __init__(self):
        self.prompt = 0
        self.completion = 0
        self.total = 0
        self.calls = 0
        self.by_model: dict = {}

    def add(self, usage, model: str = None) -> None:
        if not usage:
            return
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        t = getattr(usage, "total_tokens", 0) or 0
        self.prompt += p
        self.completion += c
        self.total += t
        self.calls += 1
        if model:
            m = self.by_model.setdefault(model, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
            m["prompt"] += p
            m["completion"] += c
            m["total"] += t
            m["calls"] += 1

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt,
            "completion_tokens": self.completion,
            "total_tokens": self.total,
            "llm_calls": self.calls,
            "by_model": self.by_model,
        }


class LLMClient:
    def __init__(self, model: Optional[str] = None):
        self.model = model or config.PRIMARY_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy import

            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    # ── Primary (non-streamed) ────────────────────────────────────────────
    async def complete(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        max_tokens: Optional[int] = None,
        meter: Optional[UsageMeter] = None,
    ):
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        if meter is not None:
            meter.add(getattr(response, "usage", None), model=self.model)
        return response.choices[0].message

    # ── Primary (streamed) ────────────────────────────────────────────────
    async def complete_stream(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        max_tokens: Optional[int] = None,
        meter: Optional[UsageMeter] = None,
    ) -> AsyncIterator[Tuple[str, object]]:
        """Yield normalized events: ("content", str), ("tool_calls", list), ("usage", obj).

        Partial OpenAI tool-call deltas are accumulated by index and emitted once
        as a single consolidated ("tool_calls", [...]) event, so the orchestrator
        stays simple.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        stream = await self.client.chat.completions.create(**kwargs)
        tool_acc: dict = {}

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                if meter is not None:
                    meter.add(usage, model=self.model)
                yield ("usage", usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                yield ("content", delta.content)
            for tc in getattr(delta, "tool_calls", None) or []:
                slot = tool_acc.setdefault(tc.index, {"id": None, "name": None, "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments

        if tool_acc:
            yield ("tool_calls", [tool_acc[i] for i in sorted(tool_acc)])

    # ── Utility (cheap model) ─────────────────────────────────────────────
    async def utility_complete(
        self,
        prompt: str,
        max_tokens: int = 120,
        meter: Optional[UsageMeter] = None,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=config.UTILITY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        if meter is not None:
            meter.add(getattr(response, "usage", None), model=config.UTILITY_MODEL)
        return (response.choices[0].message.content or "").strip()

    async def summarize(self, text: str, meter: Optional[UsageMeter] = None) -> str:
        return await self.utility_complete(
            f"Summarize the following conversation so far in 2-3 sentences, "
            f"keeping key facts and the user's intent:\n\n{text}",
            max_tokens=180,
            meter=meter,
        )
