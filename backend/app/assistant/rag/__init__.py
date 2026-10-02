"""Semantic (vector) retrieval layer for the assistant.

`embeddings` turns text into vectors (OpenAI); `vector_store` runs Atlas
$vectorSearch. Both degrade gracefully — on any failure the retrieval callers
fall back to the existing keyword search, so RAG is strictly additive.
"""
