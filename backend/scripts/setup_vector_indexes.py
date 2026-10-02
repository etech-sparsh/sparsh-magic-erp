"""Create the Atlas Search VECTOR indexes the RAG retrieval needs.

Run once (and after any embedding-dimension change):
    cd backend && python -m scripts.setup_vector_indexes

Requires an Atlas cluster (M10+ for vector search, or a free/shared tier that
has Search enabled). Idempotent: skips an index that already exists. Index
builds are asynchronous — they take a minute or two to become queryable; until
then retrieval transparently falls back to keyword search.

Each index defines `embedding` as the vector field plus the FILTER fields the
retrieval pre-filters on (RBAC scoping happens inside the vector query).
"""
import sys

import certifi
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from app.assistant.config import config
from app.config.settings import settings

DIMS = config.EMBED_DIMS

INDEXES = [
    # (collection, index_name, [filter field paths])
    ("KnowledgeBase", config.KNOWLEDGE_VECTOR_INDEX, ["project_id"]),
    (config.ATTACHMENT_CHUNK_COLLECTION, config.ATTACHMENT_VECTOR_INDEX, ["conversation_id"]),
    (config.MEDIA_CHUNK_COLLECTION, config.MEDIA_VECTOR_INDEX, ["media_type"]),
]


def _definition(filter_fields):
    fields = [{"type": "vector", "path": "embedding", "numDimensions": DIMS, "similarity": "cosine"}]
    fields += [{"type": "filter", "path": f} for f in filter_fields]
    return {"fields": fields}


def main() -> int:
    # Longer selection timeout so a flaky/electing node doesn't immediately fail
    # the whole run; retryable reads/writes ride through brief blips.
    client = MongoClient(settings.MONGODB_URI, tlsCAFile=certifi.where(),
                         serverSelectionTimeoutMS=60000, retryWrites=True)
    db = client[settings.DATABASE_NAME]
    rc = 0
    for coll_name, index_name, filters in INDEXES:
        coll = db[coll_name]
        try:
            existing = {ix["name"] for ix in coll.list_search_indexes()}
        except Exception as e:
            print(f"! {coll_name}: cannot list search indexes ({e}). "
                  f"Vector search may be unavailable on this tier.")
            rc = 1
            continue
        if index_name in existing:
            print(f"= {coll_name}.{index_name} already exists — skipping.")
            continue
        model = SearchIndexModel(definition=_definition(filters), name=index_name, type="vectorSearch")
        try:
            coll.create_search_index(model)
            print(f"+ {coll_name}.{index_name} created (filters: {filters}). "
                  f"Build is async — queryable in ~1-2 min.")
        except Exception as e:
            print(f"! {coll_name}.{index_name} failed: {e}")
            rc = 1
    client.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
