"""Knowledge retrieval service (RAG bridge).

Bridges the existing `KnowledgeBase` collection (populated by the GPT Projects
feature) behind the standard RAG source contract. Retrieval is keyword-based for
now (TD-5: vector upgrade later) and ALWAYS scope-filtered to the knowledge
projects the caller may access.

Accessible-project resolution (conservative, safe subset of gpt.py logic):
  * staff/admin/superadmin → all projects (None == unrestricted)
  * learner/clientadmin    → projects linked to their batches (+ company) and
                             projects explicitly granted via gpt_permissions
Session/quarter-linked unlocks from gpt.py are intentionally NOT included yet;
being more restrictive only reduces recall, never leaks. (See TD-6.)
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.caching import cache
from app.assistant.config import config
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.rag import RagRetrieval, RagSource
from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role
from app.db.mongodb import get_collection

KNOWLEDGE_COLLECTION = "KnowledgeBase"
SNIPPET_MAX = 500
VECTOR_SNIPPET_MAX = 1400  # vector returns the relevant chunk — keep more of it


def _maybe_oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_accessible_project_ids(ctx: UserContext) -> Optional[Set[str]]:
    """Return the set of knowledge project ids the caller may read.

    None means unrestricted (staff/admin). An empty set means no access.
    """
    if normalize_role(ctx.role) in (ROLE_SA, ROLE_AD):
        return None

    # Metadata cache: accessible projects change rarely (batch/permission edits).
    cache_key = f"accessible:{ctx.user_id}:{ctx.company_id}:{','.join(sorted(ctx.batch_ids))}"
    cached = cache.metadata_cache.get(cache_key)
    if cached is not None:
        return cached

    ids: Set[str] = set()

    # Projects linked to the user's batches (and their company's batches).
    batch_or = []
    oids = [o for o in (_maybe_oid(b) for b in ctx.batch_ids) if o]
    if oids:
        batch_or.append({"_id": {"$in": oids}})
    if ctx.company_id:
        batch_or.append({"companies": ctx.company_id})
    if batch_or:
        batches = await get_collection("batches").find({"$or": batch_or}).to_list(200)
        for b in batches:
            if b.get("gpt_project_id"):
                ids.add(str(b["gpt_project_id"]))
            for p in b.get("gpt_projects", []):
                if p.get("id"):
                    ids.add(str(p["id"]))

    # Explicit grants.
    perm_or = [{"entity_id": ctx.user_id, "entity_type": "user"}]
    if ctx.company_id:
        perm_or.append({"entity_id": ctx.company_id, "entity_type": "company"})
    perms = await get_collection("gpt_permissions").find({"$or": perm_or}).to_list(200)
    for p in perms:
        if p.get("project_id"):
            ids.add(str(p["project_id"]))

    cache.metadata_cache.set(cache_key, ids)
    return ids


# Common words that add noise (not signal) to a content regex. Kept short on
# purpose — over-filtering only hurts recall.
_STOPWORDS = {
    "what", "when", "where", "which", "whom", "whose", "that", "this", "with",
    "from", "your", "you", "the", "and", "for", "are", "was", "were", "how",
    "does", "did", "can", "could", "would", "should", "about", "into", "tell",
    "give", "show", "explain", "please", "have", "has", "any", "some", "want",
}


def _keywords(query: str) -> List[str]:
    """Content keywords from a query.

    Keeps 3-char tokens so acronyms (OOP, ROI, KPI) survive, but drops common
    stopwords so a question like "what is OOP" searches for "oop", not "what".
    """
    return [
        k
        for k in re.split(r"\W+", query.lower())
        if len(k) >= 3 and k not in _STOPWORDS
    ]


def _match_snippet(content: str, keywords: List[str], width: int = SNIPPET_MAX) -> str:
    """A window of the chunk AROUND the first keyword match.

    The previous snippet was always the chunk's first 500 chars — when the
    match sat deeper in a ~4k-char chunk the model never saw the matching
    text, which is exactly why file questions got vague answers."""
    if not content:
        return ""
    low = content.lower()
    pos = -1
    for k in keywords:
        pos = low.find(k)
        if pos != -1:
            break
    if pos <= width // 4:  # match near the start (or none) — head is fine
        return content[:width]
    start = max(0, pos - width // 3)
    tail = "..." if start + width < len(content) else ""
    return "..." + content[start:start + width] + tail


def _rank(chunks: List[dict], keywords: List[str]) -> List[tuple]:
    """Score candidates by how many DISTINCT query terms they contain.

    Filename hits weigh extra ('what's in the procurement file?') — the file's
    name often carries the strongest signal the content lacks."""
    scored = []
    for c in chunks:
        content_l = (c.get("content") or "").lower()
        fname_l = (c.get("filename") or "").lower()
        content_hits = sum(1 for k in keywords if k in content_l)
        fname_hits = sum(1 for k in keywords if k in fname_l)
        scored.append((content_hits * 2 + fname_hits * 3, c))
    scored.sort(key=lambda t: -t[0])
    return scored


async def _vector_search(query: str, accessible: Optional[Set[str]], limit: int) -> List[RagSource]:
    """Semantic retrieval over KnowledgeBase, scoped to accessible projects.

    Returns [] when vectors are unavailable or nothing matches, so the caller
    falls back to keyword search. RBAC is enforced INSIDE the vector query via
    an Atlas pre-filter on project_id — never relaxed."""
    from app.assistant.rag.embeddings import embed_query
    from app.assistant.rag.vector_store import vector_search

    vec = await embed_query(query)
    if not vec:
        return []
    filt = {"project_id": {"$in": list(accessible)}} if accessible is not None else None
    docs = await vector_search(
        KNOWLEDGE_COLLECTION, config.KNOWLEDGE_VECTOR_INDEX, vec, limit,
        filter_expr=filt, min_score=config.RAG_MIN_SCORE,
    )
    return [
        RagSource(
            source_id=str(c.get("_id")),
            title=c.get("filename"),
            snippet=(c.get("content") or "")[:VECTOR_SNIPPET_MAX],
            score=round(float(c.get("vector_score") or 0.0), 4),
            document_id=c.get("file_id"),
            collection=KNOWLEDGE_COLLECTION,
            metadata={"project_id": c.get("project_id")},
        )
        for c in docs
    ]


async def search(ctx: UserContext, query: str, limit: int = 5) -> RagRetrieval:
    accessible = await get_accessible_project_ids(ctx)

    mongo: dict = {}
    if accessible is not None:
        if not accessible:
            return RagRetrieval(query=query, sources=[], retrieval_method="keyword")
        mongo["project_id"] = {"$in": list(accessible)}

    # Vector-first (semantic); falls back to keyword on any miss/error.
    vec_sources = await _vector_search(query, accessible, limit)
    if vec_sources:
        return RagRetrieval(query=query, sources=vec_sources, retrieval_method="vector")

    col = get_collection(KNOWLEDGE_COLLECTION)
    keywords = _keywords(query)

    scored: List[tuple] = []
    if keywords:
        rx = {"$regex": "|".join(re.escape(k) for k in keywords), "$options": "i"}
        # Candidate pool, then rank client-side: "first N matching any keyword"
        # returned whichever file was uploaded first, not the relevant one.
        # The pool is generous because it also fills in upload order — too small
        # and later-uploaded files never reach the ranking stage at all.
        pool = max(limit * 20, 100)
        candidates = await col.find(
            {**mongo, "$or": [{"content": rx}, {"filename": rx}]}
        ).limit(pool).to_list(pool)
        scored = _rank(candidates, keywords)

    if not scored:
        # No keyword hit (e.g. "summarize the project files") — surface the
        # scope's leading chunks instead of returning nothing.
        fallback = await col.find(mongo).limit(limit).to_list(limit)
        scored = [(0, c) for c in fallback]

    top = scored[:limit]
    sources = [
        RagSource(
            source_id=str(c.get("_id")),
            title=c.get("filename"),
            snippet=_match_snippet(c.get("content") or "", keywords),
            score=float(s),
            document_id=c.get("file_id"),
            collection=KNOWLEDGE_COLLECTION,
            metadata={"project_id": c.get("project_id")},
        )
        for s, c in top
    ]
    return RagRetrieval(query=query, sources=sources, retrieval_method="keyword+rank")
