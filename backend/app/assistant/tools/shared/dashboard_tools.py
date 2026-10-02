"""Dashboard tool: get_dashboard_stats — available to all roles."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.security.rbac import normalize_role, ROLE_SA, ROLE_AD
from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS


_STAFF_ROLES = {ROLE_SA, ROLE_AD, "CO"}  # superadmin, admin, coach


@tool(
    name="get_dashboard_stats",
    description=(
        "Return the current user's dashboard summary: KPIs (registered entities, "
        "active batches, total learners, session velocity in the last 30 days, "
        "attendance rate), the 14-day operational pulse (sessions completed per day), "
        "and the session-type breakdown (Strategic / Technical / Operational / Other). "
        "The dashboard screen labels these 'Executive Overview', 'System Pulse', "
        "'Coaching Mix', and 'Operational Timeline' — use this tool whenever the "
        "user mentions ANY of those names, or asks 'what does my dashboard show', "
        "'how many active batches', 'show me the session trend', 'what is the "
        "coaching/session mix', 'what is my attendance rate', or any question "
        "about overall platform metrics and activity."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_dashboard_stats(ctx: UserContext) -> ToolResult:
    role = normalize_role(ctx.role)
    is_staff = role in _STAFF_ROLES
    company_id = ctx.company_id

    companies_col = get_collection("companies")
    batches_col = get_collection("batches")
    learners_col = get_collection("learners")
    session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]

    # --- KPIs ---
    if is_staff:
        registered_entities = await companies_col.count_documents({})
        active_batches = await batches_col.count_documents({"status": "active"})
        strategic_learners = await learners_col.count_documents({})
    else:
        registered_entities = 1
        active_batches = await batches_col.count_documents(
            {"status": "active", "company_id": company_id}
        )
        strategic_learners = await learners_col.count_documents({"company_id": company_id})

    # --- Session velocity (last 30 days) ---
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    session_velocity = 0
    for col_name in session_cols:
        # Sessions only — exclude type=="task" so completed to-dos don't inflate the count
        # (mirrors the Session Mix exclusion below; keeps Calendar and Task stats independent).
        query: dict = {"status": "completed", "start": {"$gte": thirty_days_ago}, "type": {"$ne": "task"}}
        if not is_staff:
            query["company_id"] = company_id
        session_velocity += await get_collection(col_name).count_documents(query)

    # --- Operational pulse (last 14 days) ---
    today = datetime.utcnow().date()
    pulse_data = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        count = 0
        for col_name in session_cols:
            q: dict = {"start": {"$regex": f"^{day.isoformat()}"}, "status": "completed", "type": {"$ne": "task"}}
            if not is_staff:
                q["company_id"] = company_id
            count += await get_collection(col_name).count_documents(q)
        pulse_data.append({"date": day.strftime("%d %b"), "sessions_completed": count})

    # --- Session mix ---
    # Personal to-do entries (type=="task") are NOT coaching sessions and would
    # otherwise swamp the "Other" bucket, making the mix meaningless. Exclude them
    # so the Coaching Mix reflects real session types only.
    mix_counts = {"Strategic": 0, "Technical": 0, "Operational": 0, "Other": 0}
    for col_name in session_cols:
        q2: dict = {} if is_staff else {"company_id": company_id}
        async for session in get_collection(col_name).find(q2, {"session_type": 1, "type": 1}):
            if session.get("type") == "task":
                continue
            s_type = session.get("session_type") or ""
            if any(kw in s_type for kw in ["Direct", "Strategy", "CEO"]):
                mix_counts["Strategic"] += 1
            elif any(kw in s_type for kw in ["Review", "Module", "Session"]):
                mix_counts["Technical"] += 1
            elif any(kw in s_type for kw in ["Support", "Check"]):
                mix_counts["Operational"] += 1
            else:
                mix_counts["Other"] += 1

    # --- Attendance rate (company users only) ---
    attendance_rate = None
    if not is_staff:
        attendance_col = get_collection("attendance")
        company_learners = await learners_col.find(
            {"company_id": company_id}, {"_id": 1}
        ).to_list(1000)
        learner_ids = [str(l["_id"]) for l in company_learners]
        if learner_ids:
            total = await attendance_col.count_documents({"user_id": {"$in": learner_ids}})
            present = await attendance_col.count_documents(
                {"user_id": {"$in": learner_ids}, "status": "present"}
            )
            if total > 0:
                attendance_rate = round((present / total) * 100)

    scope = "org-wide" if is_staff else f"company:{company_id}"
    data = {
        "kpis": {
            "registered_entities": registered_entities,
            "active_batches": active_batches,
            "total_learners": strategic_learners,
            "session_velocity_30d": session_velocity,
            **({"attendance_rate_pct": attendance_rate} if attendance_rate is not None else {}),
        },
        "operational_pulse_14d": pulse_data,
        "session_mix": {k: v for k, v in mix_counts.items() if v > 0},
    }

    return ToolResult.ok(
        "get_dashboard_stats",
        data,
        sources=["companies", "batches", "learners", "calendar_events", "attendance"],
        scope_applied=scope,
    )
