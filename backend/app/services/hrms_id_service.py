"""HRMS ▸ atomic business-id generation.

The source HRMS computed sequential ids (`HR-REQ-2026-001`, `CAN-001`, …) by scanning
existing rows for the highest suffix. That races: two concurrent creates read the same
max and mint the same id (BACKEND_ANALYSIS Risk #12). Under a unique index the loser
gets a 500; without one you get duplicates.

Here a single `find_one_and_update` with `$inc` + `upsert` does the allocation atomically
in the database. Mongo guarantees the increment is serialised per document, so two
concurrent callers always receive different numbers.

Sequences are scoped per company (and per year where the format is year-scoped) — see
`counter_key` in models/hrms.py for why: a client must not be able to infer another
client's hiring volume from gaps in their own numbering.
"""
from typing import Optional

from pymongo import ReturnDocument

from app.db.mongodb import get_collection
from app.models.hrms import COLL_COUNTERS, counter_key, format_business_id


async def next_sequence(kind: str, company_id: str, year: Optional[int] = None) -> int:
    """Atomically allocate and return the next sequence number for a scope.

    Raises ValueError for an unknown `kind` or a missing `year` on a year-scoped kind —
    both are programming errors and should fail loudly rather than mint a wrong id.
    """
    if not company_id:
        raise ValueError("company_id is required to allocate a business id")

    key = counter_key(kind, company_id, year)
    doc = await get_collection(COLL_COUNTERS).find_one_and_update(
        {"_id": key},
        {
            "$inc": {"seq": 1},
            # Recorded for operability: which company/kind/year a counter belongs to,
            # without having to parse the composite _id.
            "$setOnInsert": {"scope": kind, "company_id": str(company_id), "year": year},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


async def next_business_id(kind: str, company_id: str, year: Optional[int] = None) -> str:
    """Allocate the next sequence and render it as a business id.

    e.g. next_business_id("requisition", company_id, 2026) -> "HR-REQ-2026-001"
    """
    seq = await next_sequence(kind, company_id, year)
    return format_business_id(kind, seq, year)


async def peek_sequence(kind: str, company_id: str, year: Optional[int] = None) -> int:
    """Current value of a counter WITHOUT consuming one. Read-only.

    For diagnostics and tests only — never use this to derive an id, since the value can
    change between the peek and the write. Returns 0 when the counter does not exist yet.
    """
    key = counter_key(kind, company_id, year)
    doc = await get_collection(COLL_COUNTERS).find_one({"_id": key})
    return int(doc["seq"]) if doc and "seq" in doc else 0
