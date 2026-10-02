"""Adaptive response shaping (length/format based on query type). Phase 3."""
from __future__ import annotations


def shape(answer: str, original_query: str) -> str:
    """Post-process the model answer for adaptive verbosity/markdown. Phase 3."""
    raise NotImplementedError("response_formatter.shape — Phase 3")
