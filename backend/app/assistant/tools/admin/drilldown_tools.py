"""Superadmin (SA) drill-down tools — Tier 2.

Builds on Tier 1 (org_tools) with entity-level views:
  * get_company_overview — a single company's batches, people, performance
  * get_batch_details    — a single batch's companies, quarters, sessions
  * get_user_activity    — any user's performance + attendance (cross-user, SA)

All are `allowed_roles=["SA"]`. Two enablers/safeties:
  * **Name-or-id input** — a superadmin chats "Acme", not an ObjectId. Every
    tool resolves a name OR id via `_resolve`; on ambiguity it returns candidate
    names (no PII) so the model can ask which one.
  * **No PII** — people are surfaced by name/role/department only, via
    serialize_public; emails, phones and auth metadata never appear. Metrics are
    computed in Python from find() (no $aggregate) so behaviour is deterministic
    and testable.
"""
from __future__ import annotations

from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.analytics import performance
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import assessment_service
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize_public
from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

_SESSION_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

_COMPANY_FIELDS = ["name", "domain", "company_type", "city", "state", "country",
                   "members_count", "status", "is_active", "created_at"]
_BATCH_FIELDS = ["name", "product_name", "description", "status",
                 "start_date", "target_end_date", "created_at"]
_QUARTER_FIELDS = ["name", "status", "description", "start_date", "target_end_date"]
_USER_FIELDS = ["full_name", "role", "tag", "company_id", "designation",
                "department", "is_active", "session_type", "created_at"]


def _oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def _resolve(collections: List[str], query: str, name_field: str = "name"):
    """Resolve a name-or-id query against one or more collections.

    Returns (status, doc, source, candidates):
      * ("ok", doc, source, [])          — single match (by id, or unique name)
      * ("none", None, None, [])         — nothing matched
      * ("ambiguous", None, None, names) — several name matches; `names` is a
        list of {"id","name"} for the model to disambiguate (no PII).
    Matching is exact (case-insensitive) first, then substring, so "Acme" finds
    "Acme Retail" without colliding with an exact hit.
    """
    oid = _oid(query)
    needle = (query or "").strip().lower()

    exact: list = []
    partial: list = []
    for source in collections:
        docs = await get_collection(source).find({}).to_list(2000)
        for d in docs:
            if oid is not None and d.get("_id") == oid:
                return "ok", d, source, []
            name = str(d.get(name_field) or "").strip().lower()
            if not needle:
                continue
            if name == needle:
                exact.append((d, source))
            elif needle in name:
                partial.append((d, source))

    hits = exact or partial
    if not hits:
        return "none", None, None, []
    if len(hits) == 1:
        d, source = hits[0]
        return "ok", d, source, []
    candidates = [{"id": str(d["_id"]), "name": d.get(name_field)} for d, _ in hits[:10]]
    return "ambiguous", None, None, candidates


def _clarify(toolname: str, query: str, candidates: list) -> ToolResult:
    return ToolResult.ok(
        toolname,
        {"resolved": False, "query": query, "candidates": candidates,
         "hint": "Multiple matches — ask the user which one they mean."},
        scope_applied="global",
    )


def _not_found(toolname: str, query: str, kind: str) -> ToolResult:
    return ToolResult.ok(
        toolname,
        {"resolved": False, "query": query, "candidates": [],
         "hint": f"No {kind} found matching '{query}'."},
        scope_applied="global",
    )


# ── get_company_overview ───────────────────────────────────────────────────
@tool(
    name="get_company_overview",
    description=(
        "Deep-dive on ONE company by name or id: its batches, learner count "
        "(active/inactive), department breakdown, average assessment score, top "
        "performers (by name), and attendance rate. Superadmin only. Use for "
        "'how is Acme doing', 'show me <company> overview', 'performance of "
        "<company>'. Contact details are not exposed."
    ),
    allowed_roles=["SA"],
    parameters={
        "company": {"type": "string", "description": "Company name or id."},
    },
    required=["company"],
)
async def get_company_overview(ctx: UserContext, company: str) -> ToolResult:
    status, doc, _, candidates = await _resolve(["companies"], company)
    if status == "ambiguous":
        return _clarify("get_company_overview", company, candidates)
    if status == "none":
        return _not_found("get_company_overview", company, "company")

    company_id = str(doc["_id"])

    batches = await get_collection("batches").find({"companies": company_id}).to_list(200)
    learners = await get_collection("learners").find({"company_id": company_id}).to_list(2000)
    learner_ids = [str(l["_id"]) for l in learners]
    inactive = sum(1 for l in learners if l.get("is_active") is False)

    # Department breakdown (Python rollup; no $aggregate).
    dept_counts: dict = {}
    for l in learners:
        dept = l.get("department") or "Unspecified"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    # Assessment performance for the whole company.
    assessments = await get_collection("LearnerAssessments").find(
        {"company_id": company_id}
    ).to_list(5000)
    pcts = [a.get("percentage") for a in assessments if isinstance(a.get("percentage"), (int, float))]
    avg_score = round(sum(pcts) / len(pcts), 1) if pcts else None

    # Top performers by mean percentage (names only — no email/PII).
    per_user: dict = {}
    for a in assessments:
        uid = a.get("user_id")
        p = a.get("percentage")
        if uid and isinstance(p, (int, float)):
            per_user.setdefault(uid, []).append(p)
    name_by_id = {str(l["_id"]): l.get("full_name") for l in learners}
    ranked = sorted(
        ({"name": name_by_id.get(uid, "Unknown"), "avg_score": round(sum(v) / len(v), 1)}
         for uid, v in per_user.items()),
        key=lambda r: r["avg_score"], reverse=True,
    )[:5]

    # Attendance rate across the company's learners.
    attendance_rate = None
    if learner_ids:
        att = await get_collection("attendance").find(
            {"user_id": {"$in": learner_ids}}
        ).to_list(10000)
        if att:
            present = sum(1 for r in att if r.get("status") == "present")
            attendance_rate = round(present / len(att) * 100)

    data = {
        "company": serialize_public(doc, _COMPANY_FIELDS),
        "batches": {
            "count": len(batches),
            "names": [b.get("name") for b in batches],
        },
        "learners": {
            "total": len(learners),
            "active": len(learners) - inactive,
            "inactive": inactive,
            "by_department": dept_counts,
        },
        "performance": {
            "average_score": avg_score,
            "assessments_recorded": len(assessments),
            "top_performers": ranked,
        },
        "attendance_rate_percent": attendance_rate,
    }
    return ToolResult.ok(
        "get_company_overview",
        data,
        sources=["companies", "batches", "learners", "LearnerAssessments", "attendance"],
        scope_applied="global",
    )


# ── get_batch_details ────────────────────────────────────────────────────--
@tool(
    name="get_batch_details",
    description=(
        "Deep-dive on ONE batch by name or id: its status/product, the companies "
        "enrolled, the quarters/modules within it, and how many sessions it has. "
        "Superadmin only. Use for 'tell me about the <batch> batch', 'which "
        "companies are in <batch>', 'what modules does <batch> have'."
    ),
    allowed_roles=["SA"],
    parameters={
        "batch": {"type": "string", "description": "Batch name or id."},
    },
    required=["batch"],
)
async def get_batch_details(ctx: UserContext, batch: str) -> ToolResult:
    status, doc, _, candidates = await _resolve(["batches"], batch)
    if status == "ambiguous":
        return _clarify("get_batch_details", batch, candidates)
    if status == "none":
        return _not_found("get_batch_details", batch, "batch")

    batch_id = str(doc["_id"])
    company_ids = doc.get("companies", [])

    # Companies enrolled (names only).
    companies = []
    oids = [o for o in (_oid(c) for c in company_ids) if o]
    if oids:
        companies = await get_collection("companies").find({"_id": {"$in": oids}}).to_list(500)

    # Quarters/modules in this batch.
    quarters = await get_collection("quarters").find({"batch_id": batch_id}).to_list(200)

    # Session count across the calendar collections.
    session_count = 0
    for col in _SESSION_COLLECTIONS:
        session_count += await get_collection(col).count_documents({"batch_id": batch_id})

    data = {
        "batch": serialize_public(doc, _BATCH_FIELDS),
        "companies": {
            "count": len(company_ids),
            "names": [c.get("name") for c in companies],
        },
        "quarters": [serialize_public(q, _QUARTER_FIELDS) for q in quarters],
        "session_count": session_count,
    }
    return ToolResult.ok(
        "get_batch_details",
        data,
        sources=["batches", "companies", "quarters"],
        scope_applied="global",
    )


# ── get_user_activity ──────────────────────────────────────────────────────
@tool(
    name="get_user_activity",
    description=(
        "Deep-dive on ONE user by name or id (staff or learner): their profile "
        "basics, assessment performance summary (average, trend, pass rate, weak/"
        "strong subjects) and attendance. Superadmin only — this returns another "
        "person's records. Use for 'how is <name> performing', 'show <name>'s "
        "attendance/scores'. Emails and phone numbers are not exposed."
    ),
    allowed_roles=["SA"],
    parameters={
        "user": {"type": "string", "description": "User's full name or id."},
    },
    required=["user"],
)
async def get_user_activity(ctx: UserContext, user: str) -> ToolResult:
    status, doc, source, candidates = await _resolve(["staff", "learners"], user, name_field="full_name")
    if status == "ambiguous":
        return _clarify("get_user_activity", user, candidates)
    if status == "none":
        return _not_found("get_user_activity", user, "user")

    user_id = str(doc["_id"])

    # Assessment performance (reuse the shared service + deterministic analyzer).
    assessments = await assessment_service.get_results_for_user(ctx, user_id)
    summary = performance.analyze(assessments)

    # Attendance summary.
    att = await get_collection("attendance").find({"user_id": user_id}).to_list(2000)
    present = sum(1 for r in att if r.get("status") == "present")
    attendance = {
        "records": len(att),
        "present": present,
        "absent": len(att) - present,
        "attendance_rate_percent": round(present / len(att) * 100) if att else None,
    }

    data = {
        "profile": serialize_public(doc, _USER_FIELDS),
        "performance": {
            "average_score": summary.average_percentage,
            "trend": summary.trend,
            "quizzes_taken": summary.quizzes_taken,
            "quizzes_passed": summary.quizzes_passed,
            "weak_subjects": [s.subject for s in summary.weak_subjects],
            "strong_subjects": [s.subject for s in summary.strong_subjects],
        },
        "attendance": attendance,
    }
    return ToolResult.ok(
        "get_user_activity",
        data,
        sources=[source, "LearnerAssessments", "attendance"],
        scope_applied="global",
    )
