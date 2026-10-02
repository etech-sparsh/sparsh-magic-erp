"""Standard RAG source contract.

Every knowledge-retrieval tool (now `search_knowledge`, later vector retrieval)
returns sources in this shape so the model can cite them uniformly and the UI can
render consistent citations regardless of the underlying retrieval method.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RagSource(BaseModel):
    source_id: str                       # chunk id (stringified _id)
    title: Optional[str] = None          # document/file name for citation
    snippet: str = ""                    # retrieved text (truncated for prompt safety)
    score: Optional[float] = None        # relevance score; None for keyword retrieval
    document_id: Optional[str] = None    # parent file/document id
    collection: str = "KnowledgeBase"    # origin collection
    metadata: Dict = Field(default_factory=dict)


class RagRetrieval(BaseModel):
    query: str
    sources: List[RagSource] = Field(default_factory=list)
    retrieval_method: str = "keyword"    # keyword | vector | hybrid
