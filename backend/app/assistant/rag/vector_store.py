"""Atlas $vectorSearch helper.

A single place that runs a vector-similarity aggregation against a collection's
Atlas Search index. Returns [] on ANY error (index not built yet, bad filter,
driver issue) so every caller can fall back to keyword search without special
handling.
"""
from __future__ import annotations

from typing import List, Optional

from app.assistant.config import config
from app.db.mongodb import get_collection


async def vector_search(
    collection: str,
    index_name: str,
    query_vector: Optional[List[float]],
    limit: int = 5,
    filter_expr: Optional[dict] = None,
    min_score: float = 0.0,
) -> List[dict]:
    """Return up to `limit` docs most similar to `query_vector`.

    `filter_expr` is an Atlas $vectorSearch pre-filter (must reference fields
    indexed as `filter` type), e.g. {"project_id": {"$in": [...]}}. Each returned
    doc gains a `vector_score` field (cosine similarity in [0,1]).
    """
    if not query_vector:
        return []
    num_candidates = max(limit * max(1, int(config.RAG_NUM_CANDIDATES_FACTOR)), 100)
    search_stage: dict = {
        "index": index_name,
        "path": "embedding",
        "queryVector": query_vector,
        "numCandidates": num_candidates,
        "limit": limit,
    }
    if filter_expr:
        search_stage["filter"] = filter_expr
    pipeline = [
        {"$vectorSearch": search_stage},
        {"$set": {"vector_score": {"$meta": "vectorSearchScore"}}},
    ]
    if min_score and min_score > 0:
        pipeline.append({"$match": {"vector_score": {"$gte": min_score}}})
    try:
        return await get_collection(collection).aggregate(pipeline).to_list(limit)
    except Exception as e:  # noqa: BLE001 — fall back to keyword search
        print(f"[rag] vector_search {collection}/{index_name} failed: {e}")
        return []
