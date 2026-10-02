"""
TPMS ▸ core API routes (everything except the forms sub-module, which lives in
app/routes/forms.py and is unchanged).

Mounted under /api/tpms.

  GET  /tpms/activities                       activity catalogue (14 rows)
  GET  /tpms/departments                      client-side departments doers are grouped by
  GET  /tpms/reminder-rules                   default reminder rules applied on save
  POST /tpms/schedules/check-conflict         once-per-month duplicate warning
  POST /tpms/schedules                        create (expands recurrence + reminders + tracker)
  GET  /tpms/schedules                        month feed for the calendar grid
  POST /tpms/schedules/{id}/learner-done      doer claims completion
  POST /tpms/schedules/{id}/confirm           staff confirms — the only path to Completed
  POST /tpms/schedules/{id}/reschedule-request
  GET  /tpms/reschedule-requests
  POST /tpms/reschedule-requests/{id}/decide

Behaviour is ported from `copy_of calender/code.js`; see app/services/tpms_schedule_service.py
and tpms_lifecycle_service.py for the ported rules.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from typing import Optional
import io
import logging

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.tpms import (
    COLL_ACTIVITIES, COLL_REMINDER_RULES, COLL_SUCCESS_MEASURES, TPMS_DEPARTMENTS,
    COLL_DEPARTMENTS, COLL_REMINDER_LOGS, COLL_MAIL_TEMPLATES, COLL_WHATSAPP_TEMPLATES,
    COLL_META_TEMPLATES, TPMS_EVENT_KIND, REQUEST_PENDING, STATUS_SCHEDULED, is_md_like,
    META_STATUS_APPROVED,
)
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime
from app.services.tpms_score_service import run_daily as run_score_daily, save_manual_score
from app.services.tpms_schedule_service import (
    CAL_COLLECTIONS, check_schedule_conflict, create_schedule,
    delete_schedule, update_schedule,
)
from app.services.tpms_client_export_service import (
    ExportNotPermitted, build_client_report, export_client_workbook,
)
from app.services.tpms_upload_service import list_task_uploads, upload_task_file
from app.services.tpms_dashboard_service import (
    get_analytics, get_employee_activity, get_escalation_dashboard, get_hod_dashboard,
    get_implementation_tracker, get_learner_dashboard, get_logs_report,
    get_review_reports, get_staff_dashboard,
)
from app.services.tpms_lifecycle_service import (
    confirm_completion, decide_reschedule_request, list_reschedule_requests,
    mark_learner_done, request_reschedule,
)

async def _tpms_company_gate(current_user: dict = Depends(get_current_user)) -> None:
    """Router-wide guard: a client-side user whose company has TPMS switched off is refused
    on EVERY endpoint here, so the module cannot be reached by URL. Internal staff pass —
    they administer TPMS across clients, and the data layer already hides disabled companies
    from what they see."""
    from app.utils.tpms_access import ensure_tpms_enabled
    await ensure_tpms_enabled(current_user)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tpms", tags=["TPMS"], dependencies=[Depends(_tpms_company_gate)])

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}


def _can_read(user: dict) -> bool:
    """Any authenticated TPMS audience may read master data — internal staff (who all
    reach the SMOps panel) and client-side users alike. Mirrors the frontend's
    canAccessTpms() in features/tpms/access.js."""
    return bool(user)


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/activities")
async def list_activities(
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """The activity catalogue — the module's backbone. Each row carries the scope
    (company/hod), whether proof upload is required, the frequency string that drives
    the duplicate check, and how its score is produced (manual/form/auto)."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    query = {} if include_inactive else {"active": {"$ne": False}}
    docs = await get_collection(COLL_ACTIVITIES).find(query).to_list(200)
    docs.sort(key=lambda a: (a.get("name") or "").lower())
    return {"activities": [_serialize(d) for d in docs]}


_VALID_SCOPES = {"company", "hod"}
_VALID_SCORE_MODES = {"manual", "form", "auto"}


def _display(u: dict) -> str:
    return (u.get("full_name")
            or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
            or u.get("name") or u.get("email") or "")


@router.get("/calendar-filters")
async def calendar_filters(current_user: dict = Depends(get_current_user)):
    """Master lists that populate the Client-wise Calendar dropdowns dynamically (independent
    of how sparse the current month is): all companies, all HODs, all OMs/SMOps."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    role = (current_user.get("role") or "").lower()
    own_company = str(current_user.get("company_id") or "")

    # Companies (client-side users see only their own).
    cq = {"is_active": {"$ne": False}}
    companies = await get_collection("companies").find(cq).to_list(2000)
    comp = [{"id": str(c["_id"]), "name": c.get("name") or ""} for c in companies]
    if role in CLIENT_ROLES and own_company:
        comp = [c for c in comp if c["id"] == own_company]
    comp.sort(key=lambda c: (c["name"] or "").lower())

    # HODs — client users whose governance role (or department) is HOD.
    hq = {"$or": [{"governance_role": {"$regex": "^hod$", "$options": "i"}},
                  {"department": {"$regex": "^hod$", "$options": "i"}}]}
    if role in CLIENT_ROLES and own_company:
        hq = {"$and": [hq, {"company_id": own_company}]}
    hod_docs = await get_collection("learners").find(hq).to_list(3000)
    hods = [{"id": str(h["_id"]), "name": _display(h), "company_id": str(h.get("company_id") or "")}
            for h in hod_docs]
    hods.sort(key=lambda h: (h["name"] or "").lower())

    # OMs = all internal staff (business decision). The calendar filters events by whether a
    # selected OM's id appears in the activity's staff_ids (the assigned SMOps), so any staff
    # member is a valid filter. Consistent with the Admin Dashboard's OM list (also all staff).
    oms = []
    for s in await get_collection("staff").find({"is_active": {"$ne": False}}).to_list(500):
        oms.append({"id": str(s["_id"]), "name": _display(s)})
    oms.sort(key=lambda o: (o["name"] or "").lower())

    return {"companies": comp, "hods": hods, "oms": oms}


@router.post("/activities")
async def create_activity(payload: dict, current_user: dict = Depends(get_current_user)):
    """H4 — admin adds a new activity to the catalogue (previously a code change). Upserts on
    name so it is idempotent; never hard-deletes."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage activities.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Activity name is required")
    scope = str(payload.get("scope") or "company").lower()
    score_mode = str(payload.get("score_mode") or "manual").lower()
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail="scope must be 'company' or 'hod'")
    if score_mode not in _VALID_SCORE_MODES:
        raise HTTPException(status_code=400, detail="score_mode must be manual/form/auto")
    doc = {
        "name": name,
        "short": str(payload.get("short") or name)[:24],
        "frequency": str(payload.get("frequency") or "once in a month"),
        "scope": scope,
        "upload_required": bool(payload.get("upload_required")),
        "score_mode": score_mode,
        "active": True,
    }
    await get_collection(COLL_ACTIVITIES).update_one({"name": name}, {"$set": doc}, upsert=True)
    return {"ok": True, "name": name}


@router.patch("/activities/{activity_id}")
async def update_activity(activity_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """H4 — edit an activity's fields or retire it (active:false). Delete is a soft-deactivate;
    catalogue rows are never hard-deleted so historical schedules/scores stay intact."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage activities.")
    try:
        oid = ObjectId(activity_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid activity id")
    updates = {}
    for f in ("short", "frequency"):
        if f in payload:
            updates[f] = str(payload[f])
    if "scope" in payload:
        s = str(payload["scope"]).lower()
        if s not in _VALID_SCOPES:
            raise HTTPException(status_code=400, detail="scope must be 'company' or 'hod'")
        updates["scope"] = s
    if "score_mode" in payload:
        m = str(payload["score_mode"]).lower()
        if m not in _VALID_SCORE_MODES:
            raise HTTPException(status_code=400, detail="score_mode must be manual/form/auto")
        updates["score_mode"] = m
    if "upload_required" in payload:
        updates["upload_required"] = bool(payload["upload_required"])
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await get_collection(COLL_ACTIVITIES).update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Activity not found")
    return {"ok": True}


@router.get("/reminder-logs")
async def list_reminder_logs(
    event_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
):
    """H10 — per-reminder send ledger (recipient + channel + status + error). Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    query = {}
    if event_id:
        query["event_id"] = event_id
    total = await get_collection(COLL_REMINDER_LOGS).count_documents(query)
    docs = await (get_collection(COLL_REMINDER_LOGS).find(query)
                  .sort("sent_at", -1).skip(skip).limit(limit).to_list(limit))
    return {"total": total, "skip": skip, "limit": limit, "logs": [_serialize(d) for d in docs]}


@router.get("/departments")
async def list_departments(
    company_id: Optional[str] = Query(None, description="Include this company's custom departments too"),
    current_user: dict = Depends(get_current_user),
):
    """H5 — department master. Returns the governance roles plus any custom departments
    (global, or scoped to the given company). Falls back to the built-in list if the master
    collection is empty (older deployments before seeding)."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    if (current_user.get("role") or "").lower() in CLIENT_ROLES:
        company_id = str(current_user.get("company_id") or "")
    query = {"active": {"$ne": False}, "$or": [{"company_id": None}]}
    if company_id:
        query["$or"].append({"company_id": company_id})
    docs = await get_collection(COLL_DEPARTMENTS).find(query).to_list(500)
    if not docs:
        # Fallback for a not-yet-seeded deployment.
        return {"departments": list(TPMS_DEPARTMENTS),
                "items": [{"name": d, "is_governance_role": True} for d in TPMS_DEPARTMENTS]}
    docs.sort(key=lambda d: (not d.get("is_governance_role"), (d.get("name") or "").lower()))
    return {"departments": [d["name"] for d in docs], "items": [_serialize(d) for d in docs]}


@router.post("/departments")
async def create_department(payload: dict, current_user: dict = Depends(get_current_user)):
    """H5 — admin adds a custom department (e.g. Sales, Ops, Finance). Governance roles are
    seeded, not created here. `company_id` optional (null = global)."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage departments.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Department name is required")
    company_id = str(payload.get("company_id") or "").strip() or None
    doc = {
        "name": name,
        "code": name.lower().replace(" ", "_"),
        "is_governance_role": False,
        "company_id": company_id,
        "active": True,
    }
    try:
        res = await get_collection(COLL_DEPARTMENTS).update_one(
            {"name": name, "company_id": company_id}, {"$set": doc}, upsert=True)
    except Exception:
        raise HTTPException(status_code=409, detail="Department already exists")
    return {"ok": True, "name": name, "upserted": bool(res.upserted_id)}


@router.patch("/departments/{dept_id}")
async def update_department(dept_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """H5 — rename or (soft) deactivate a custom department. Governance roles cannot be
    edited/removed. Data is never hard-deleted — set active:false to retire one."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage departments.")
    try:
        oid = ObjectId(dept_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid department id")
    existing = await get_collection(COLL_DEPARTMENTS).find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Department not found")
    if existing.get("is_governance_role"):
        raise HTTPException(status_code=400, detail="Governance roles cannot be edited.")
    updates = {}
    if "name" in payload and str(payload["name"]).strip():
        updates["name"] = str(payload["name"]).strip()
        updates["code"] = updates["name"].lower().replace(" ", "_")
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await get_collection(COLL_DEPARTMENTS).update_one({"_id": oid}, {"$set": updates})
    return {"ok": True}


@router.get("/reminder-rules")
async def list_reminder_rules(
    activity: Optional[str] = Query(None, description="Filter to rules for this activity"),
    current_user: dict = Depends(get_current_user),
):
    """Default reminder rules. A rule with activity '*' applies to every activity;
    a named rule applies only to that one. (autoRemindersFromRules_, code.js:3690)"""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    query = {"active": {"$ne": False}}
    if activity:
        query["$or"] = [{"activity": "*"}, {"activity": activity}]
    docs = await get_collection(COLL_REMINDER_RULES).find(query).to_list(200)
    return {"rules": [_serialize(d) for d in docs]}


# ─── M12 — admin CRUD for reminder rules + mail templates (was DB-only) ───
@router.post("/reminder-rules")
async def create_reminder_rule(payload: dict, current_user: dict = Depends(get_current_user)):
    """Admin adds/updates a default reminder rule. `activity='*'` applies to all activities."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage reminder rules.")
    doc = {
        "activity": str(payload.get("activity") or "*"),
        "stage": str(payload.get("stage") or "reminder"),
        "offset_value": int(payload.get("offset_value") or 1),
        "offset_unit": str(payload.get("offset_unit") or "days"),
        "offset_dir": str(payload.get("offset_dir") or "before"),
        "channel": str(payload.get("channel") or "email"),
        "active": True,
    }
    if doc["offset_value"] < 1:
        raise HTTPException(status_code=400, detail="offset_value must be ≥ 1")
    res = await get_collection(COLL_REMINDER_RULES).insert_one(doc)
    return {"ok": True, "id": str(res.inserted_id)}


@router.patch("/reminder-rules/{rule_id}")
async def update_reminder_rule(rule_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Edit a reminder rule or retire it (active:false)."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage reminder rules.")
    try:
        oid = ObjectId(rule_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid rule id")
    allowed = {"activity", "stage", "offset_value", "offset_unit", "offset_dir", "channel", "active"}
    updates = {k: payload[k] for k in allowed if k in payload}
    if "offset_value" in updates and int(updates["offset_value"]) < 1:
        raise HTTPException(status_code=400, detail="offset_value must be ≥ 1")
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await get_collection(COLL_REMINDER_RULES).update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.get("/mail-templates")
async def list_mail_templates(
    activity: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Mail templates (activity × side × event). Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    query = {}
    if activity:
        query["activity"] = activity
    docs = await get_collection(COLL_MAIL_TEMPLATES).find(query).to_list(500)
    docs.sort(key=lambda d: (d.get("activity") or "", d.get("event") or "", d.get("side") or ""))
    return {"templates": [_serialize(d) for d in docs]}


@router.post("/mail-templates")
async def upsert_mail_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Create/update a mail template, keyed (activity, side, event). Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage templates.")
    activity = str(payload.get("activity") or "").strip()
    side = str(payload.get("side") or "").strip().lower()
    event = str(payload.get("event") or "").strip().lower()
    if not (activity and side in {"staff", "company"} and event):
        raise HTTPException(status_code=400, detail="activity, side (staff|company) and event are required")
    doc = {
        "activity": activity, "side": side, "event": event,
        "subject": str(payload.get("subject") or ""),
        "body_html": str(payload.get("body_html") or ""),
        "active": bool(payload.get("active", True)),
        "source": "admin_edit",
    }
    await get_collection(COLL_MAIL_TEMPLATES).update_one(
        {"activity": activity, "side": side, "event": event}, {"$set": doc}, upsert=True)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════
# WhatsApp template library (/tpms/meta-templates/*)
#
# Moved to routes/meta_templates.py and mounted here unchanged, because Task Management ▸
# Templates wires its notifications to the same WhatsApp Business Account and therefore the
# same library. Mounting rather than re-implementing keeps every /tpms/meta-templates path
# exactly where it was for the TPMS admin screen.
# ═════════════════════════════════════════════════════════════
from app.routes import meta_templates as _meta_templates  # noqa: E402

router.include_router(_meta_templates.router)


@router.get("/whatsapp-templates")
async def list_whatsapp_templates(
    activity: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """WhatsApp templates (activity × side × event). Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    query = {}
    if activity:
        query["activity"] = activity
    docs = await get_collection(COLL_WHATSAPP_TEMPLATES).find(query).to_list(500)
    docs.sort(key=lambda d: (d.get("activity") or "", d.get("event") or "", d.get("side") or ""))
    return {"templates": [_serialize(d) for d in docs]}


async def _assert_meta_approved(name: str, language: str) -> str:
    """Only a Meta-APPROVED template may be wired to a TPMS notification.

    Checked against the local library first (the fast, normal path) and, when the name is not
    APPROVED there, against the WABA itself — templates approved directly in WhatsApp Manager
    before this screen existed are legitimate and must keep working.

    Returns a note when the check could not be completed. Meta being unreachable must not stop
    an admin editing notification wiring, so that case is allowed through and reported rather
    than treated as a rejection."""
    from app.services.meta_whatsapp_service import approved_template_names, is_configured

    local = await get_collection(COLL_META_TEMPLATES).find_one({"name": name})
    if local and str(local.get("status") or "").upper() == META_STATUS_APPROVED:
        return ""
    if not is_configured():
        return ("WhatsApp template management is not configured, so approval could not be "
                "verified. Saved anyway.")
    remote = await approved_template_names()
    if remote is None:
        return "Meta could not be reached, so approval could not be verified. Saved anyway."
    if name in remote:
        return ""

    if local:
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' is {str(local.get('status') or 'DRAFT').upper()} at Meta. Only "
                   "approved templates can be used for TPMS WhatsApp notifications.")
    raise HTTPException(
        status_code=400,
        detail=f"'{name}' is not an approved WhatsApp template on this business account. "
               "Create it under WhatsApp Templates and submit it for approval first.")


@router.post("/whatsapp-templates")
async def upsert_whatsapp_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Create/update a WhatsApp notification, keyed (activity, side, event). Admin only.

    Points the notification at a Meta-APPROVED template and maps its parameters: `variables`
    fills the body's {{1}}, {{2}}, … in order, `header_variables` the text header's variable,
    and `button_variables` any variable URL button. Each entry is a data field (a build_map
    key) — see GET /whatsapp-variables for the fields you can map.

    An unapproved template is refused here rather than at send time, where the failure would be
    a silent per-recipient error in the logs."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage templates.")
    activity = str(payload.get("activity") or "").strip()
    side = str(payload.get("side") or "").strip().lower()
    event = str(payload.get("event") or "").strip().lower()
    # Lowercased because Meta template names are lowercase-only (validate_template's
    # ^[a-z0-9_]+$). Stored as typed, "Accountability" would pass nothing at Meta and fail the
    # approval check below even though "accountability" is approved.
    meta_name = str(payload.get("meta_template_name") or payload.get("name") or "").strip().lower()
    if not (activity and side in {"staff", "company"} and event and meta_name):
        raise HTTPException(status_code=400,
                            detail="activity, side (staff|company), event and meta_template_name are required")

    def _field_list(key):
        raw = payload.get(key) or []
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail=f"{key} must be a list of field names")
        return [str(v).strip() for v in raw if str(v).strip()]

    def _button_map(raw):
        """[{index, field}] — `index` is the button's real position in the template. Meta
        addresses button parameters positionally, and a variable URL button is rarely the
        first button, so the position among *variable* buttons is not the same number."""
        if raw in (None, ""):
            return []
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail="button_variables must be a list")
        out = []
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                field, index = str(item.get("field") or "").strip(), item.get("index", i)
            else:
                field, index = str(item).strip(), i
            if not field:
                continue
            try:
                index = int(index)
            except (TypeError, ValueError):
                index = i
            out.append({"index": index, "field": field})
        return out

    variables = _field_list("variables")
    language = str(payload.get("language") or "en").strip() or "en"
    note = await _assert_meta_approved(meta_name, language)

    doc = {
        "activity": activity, "side": side, "event": event,
        "meta_template_name": meta_name, "name": meta_name,
        "language": language,
        "variables": variables,
        "header_variables": _field_list("header_variables"),
        "button_variables": _button_map(payload.get("button_variables")),
        "active": bool(payload.get("active", True)),
        "source": "admin_edit", "updated_at": datetime.utcnow(),
    }
    await get_collection(COLL_WHATSAPP_TEMPLATES).update_one(
        {"activity": activity, "side": side, "event": event}, {"$set": doc}, upsert=True)
    return {"ok": True, "note": note or None}


# The data fields a WhatsApp template's {{1}}, {{2}}, … parameters can map to. These are exactly
# the keys build_map produces, so a mapped field is guaranteed to resolve at send time.
_WHATSAPP_VARIABLE_FIELDS = [
    "Title", "Activity", "Calendar_Type", "Company_Name", "Event_Date", "Event_Time",
    "Status", "Departments", "Comment", "Recipient_Name",
    "Form_Link", "Form_Link_2", "Form_Links",
]


@router.get("/whatsapp-variables")
async def whatsapp_variable_catalog(current_user: dict = Depends(get_current_user)):
    """Fields available to map to a WhatsApp template's positional parameters. Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    return {"fields": _WHATSAPP_VARIABLE_FIELDS}


@router.post("/whatsapp-templates/test")
async def test_whatsapp_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Send a smoke-test of one WhatsApp template to a phone number. Admin only. Each mapped
    variable is filled with a visible [Field] placeholder so the layout can be eyeballed."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    phone = str(payload.get("phone") or "").strip()
    template_id = str(payload.get("template_id") or "").strip()
    if not phone or not template_id:
        raise HTTPException(status_code=400, detail="phone and template_id are required")
    try:
        tpl = await get_collection(COLL_WHATSAPP_TEMPLATES).find_one({"_id": ObjectId(template_id)})
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid template id")
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    from app.services.tpms_notify_service import normalize_phone
    from app.services.notification_service import send_whatsapp_template
    params = [f"[{v}]" for v in (tpl.get("variables") or [])]
    ok = await send_whatsapp_template(
        normalize_phone(phone),
        tpl.get("meta_template_name") or tpl.get("name"),
        tpl.get("language") or "en", params, slug="tpms_whatsapp_test")
    return {"ok": bool(ok)}


# Both channels resolve their template with an `active: {"$ne": False}` filter at send time
# (tpms_notify_service.get_template / get_whatsapp_template), so flipping this flag is all
# that is needed to stop a notification — the surrounding business logic is untouched and
# still runs to completion.
_TEMPLATE_COLLECTIONS = {"email": COLL_MAIL_TEMPLATES, "whatsapp": COLL_WHATSAPP_TEMPLATES}


@router.patch("/{channel}-templates/{template_id}/status")
async def update_template_status(
    channel: str,
    template_id: str,
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Activate / deactivate one notification template. Admin / Super Admin only.

    `channel` is 'mail' or 'whatsapp'. Only the flag is written — subject, body and the
    (activity, side, event) key are left exactly as they are, so toggling can never alter
    the template's content.
    """
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only Admin / Super Admin can change notification status.",
        )
    coll_name = _TEMPLATE_COLLECTIONS.get("email" if channel == "mail" else channel)
    if not coll_name:
        raise HTTPException(status_code=404, detail=f"Unknown template channel '{channel}'")
    if "active" not in payload:
        raise HTTPException(status_code=400, detail="`active` is required")
    try:
        oid = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid template id")

    active = bool(payload["active"])
    res = await get_collection(coll_name).update_one(
        {"_id": oid}, {"$set": {"active": active, "updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True, "active": active}


@router.post("/schedules/check-conflict")
async def schedules_check_conflict(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Advisory duplicate warning, called before saving a new schedule.

    Only "once"-type activities are checked ("3-4 in month" and "multiple times" are
    exempt). Company-scoped activities clash on company+month; HOD-scoped ones clash
    only when a selected doer already has that activity this month. Cancelled
    occurrences never block. The UI may proceed regardless via "Schedule Anyway".
    """
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users can only ever ask about their own company.
    if (current_user.get("role") or "").lower() in CLIENT_ROLES:
        payload = {**payload, "company_id": str(current_user.get("company_id") or "")}

    return await check_schedule_conflict(payload)


@router.post("/schedules")
async def create_tpms_schedule(payload: dict, current_user: dict = Depends(get_current_user)):
    """Schedule an activity. Expands the recurrence into N events sharing one batch id,
    attaches the catalogue's default reminders plus any custom ones, and writes the
    Activity_Tracker rows the Success-Measure engine reads.

    Write scoping (saveSchedule, code.js:808): Admin → any company · internal SMOps →
    only companies they own · client-side users → only their own company.
    """
    if (current_user.get("role") or "").lower() in CLIENT_ROLES:
        payload = {**payload, "company_id": str(current_user.get("company_id") or "")}
    return await create_schedule(current_user, payload)


@router.get("/schedules")
async def list_tpms_schedules(
    year: int = Query(..., ge=1970, le=2999),
    month: int = Query(..., ge=1, le=12, description="1-12"),
    company_id: Optional[str] = Query(None),
    activity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Month feed for the calendar grid (getEvents, code.js:486).

    `mine` marks events the caller created — the Apps Script pins those with 📌 and lets
    a Learner edit their own even when they otherwise couldn't.
    """
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    query = {"kind": TPMS_EVENT_KIND}
    # Client-side users only ever see their own company.
    role = (current_user.get("role") or "").lower()
    is_client = role in CLIENT_ROLES
    if is_client:
        query["company_id"] = str(current_user.get("company_id") or "")
    elif company_id:
        query["company_id"] = company_id

    # Spec §3 — a Learner who is neither MD nor client-admin is additionally scoped to
    # activities they are a DOER on, or that they CREATED ("isDoer OR mine"). MD and
    # client-admin oversee the whole company, so they skip this narrowing.
    oversees_company = role == "clientadmin" or is_md_like(current_user)
    self_scoped = is_client and not oversees_company
    if activity:
        query["activity"] = activity
    if status:
        query["tpms_status"] = status

    # `start` is an ISO string, so a prefix range selects the month.
    start_prefix = f"{year:04d}-{month:02d}"
    query["start"] = {"$regex": f"^{start_prefix}"}

    uid = str(current_user.get("_id"))
    events = []
    for coll in CAL_COLLECTIONS:
        for e in await get_collection(coll).find(query).to_list(2000):
            is_doer = uid in {str(m) for m in (e.get("assigned_member_ids") or [])}
            mine = str(e.get("user_id") or "") == uid
            if self_scoped and not (is_doer or mine):
                continue
            start = str(e.get("start") or "")
            events.append({
                "id": str(e["_id"]),
                "title": e.get("title") or "",
                "date": start[:10],
                "time": start[11:16],
                "activity": e.get("activity") or "",
                "company_id": e.get("company_id") or "",
                "company": e.get("company_name") or "",
                "status": e.get("tpms_status") or STATUS_SCHEDULED,
                "departments": e.get("assigned_departments") or [],
                "member_ids": e.get("assigned_member_ids") or [],
                "staff_ids": e.get("coach_ids") or [],
                "comment": e.get("additional_details") or "",
                "reschedule_count": e.get("reschedule_count") or 0,
                "learner_done": bool(e.get("learner_done")),
                "completed_at": e.get("completed_at"),
                "upload_required": bool((e.get("activity_meta") or {}).get("upload_required")),
                "reminder_count": len(e.get("reminders") or []),
                "mine": mine,
                "is_doer": is_doer,
                "scheduled_by": e.get("scheduled_by_side") or "",       # M1 — internal | client
                "scheduled_by_name": e.get("scheduled_by_name") or "",
            })
    events.sort(key=lambda x: (x["date"], x["time"]))
    return {"events": events}


# ─────────────────────────────────────────────────────────────
# Lifecycle — two-step completion + reschedule workflow
# ─────────────────────────────────────────────────────────────
@router.post("/schedules/{event_id}/learner-done")
async def schedules_learner_done(event_id: str, current_user: dict = Depends(get_current_user)):
    """The doer claims completion. This does NOT complete the activity — internal staff
    must confirm (see /confirm). Resets the escalation ladder meanwhile."""
    return await mark_learner_done(current_user, event_id)


@router.post("/schedules/{event_id}/confirm")
async def schedules_confirm(event_id: str, current_user: dict = Depends(get_current_user)):
    """Internal staff confirm — the only transition to Completed. Closes the linked
    follow-up and records the learner/staff delay split."""
    return await confirm_completion(current_user, event_id)


@router.post("/schedules/{event_id}/reschedule-request")
async def schedules_reschedule_request(
    event_id: str, payload: dict, current_user: dict = Depends(get_current_user),
):
    """Doer asks to move the activity. Must be raised ≥12h before it starts."""
    return await request_reschedule(
        current_user, event_id,
        str(payload.get("new_date") or ""),
        payload.get("new_time"),
        str(payload.get("reason") or ""),
    )


@router.get("/reschedule-requests")
async def reschedule_requests(
    status: str = Query(REQUEST_PENDING),
    current_user: dict = Depends(get_current_user),
):
    return {"requests": await list_reschedule_requests(current_user, status)}


@router.post("/reschedule-requests/{request_id}/decide")
async def reschedule_decide(
    request_id: str, payload: dict, current_user: dict = Depends(get_current_user),
):
    """Approve → moves the activity, flags it Rescheduled, bumps the counter and re-arms
    its reminders. Reject → records the decision and note only."""
    return await decide_reschedule_request(
        current_user, request_id,
        bool(payload.get("approve")),
        str(payload.get("note") or ""),
    )


@router.patch("/schedules/{event_id}")
async def update_tpms_schedule(
    event_id: str, payload: dict, current_user: dict = Depends(get_current_user),
):
    """Edit one occurrence. Changing the date or time automatically flips the status to
    Rescheduled, bumps the counter and re-arms the reminders."""
    return await update_schedule(current_user, event_id, payload)


@router.delete("/schedules/{event_id}")
async def delete_tpms_schedule(event_id: str, current_user: dict = Depends(get_current_user)):
    """Admin-only. Removes the occurrence and everything derived from it (tracker rows,
    action items, escalations, pending reschedule requests)."""
    return await delete_schedule(current_user, event_id)


# ─────────────────────────────────────────────────────────────
# Task uploads (proof-of-work for `upload_required` activities)
# ─────────────────────────────────────────────────────────────
@router.get("/schedules/{event_id}/uploads")
async def schedule_uploads(event_id: str, current_user: dict = Depends(get_current_user)):
    return {"uploads": await list_task_uploads(current_user, event_id=event_id)}


@router.post("/schedules/{event_id}/uploads")
async def schedule_upload(
    event_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Attach proof to an activity. Max 25 MB, stored in S3; the persistent key is saved
    and a fresh signed URL is minted on every read."""
    return await upload_task_file(current_user, event_id, file)


@router.get("/uploads")
async def company_uploads(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="'YYYY-MM'"),
    current_user: dict = Depends(get_current_user),
):
    """All proof files for a company + month — the Implementation Tracker's upload panel."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return {"uploads": await list_task_uploads(current_user, company_id=company_id, period=period)}


# ─────────────────────────────────────────────────────────────
# Success measures
# ─────────────────────────────────────────────────────────────
@router.get("/success-measures")
async def success_measures(
    period: str = Query(..., description="'YYYY-MM'"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The scorecard: Implementation %, Score % and Achievement % per activity."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    if (current_user.get("role") or "").lower() in CLIENT_ROLES:
        company_id = str(current_user.get("company_id") or "")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    rows = await get_collection(COLL_SUCCESS_MEASURES).find(
        {"company_id": company_id, "period": period}
    ).to_list(2000)
    rows.sort(key=lambda r: (r.get("scope") != "company", (r.get("activity") or "").lower()))
    return {"period": period, "company_id": company_id,
            "measures": [_serialize(r) for r in rows]}


@router.post("/manual-scores")
async def manual_scores_save(payload: dict, current_user: dict = Depends(get_current_user)):
    """Enter a manual score for one of the 10 manually-scored activities. `scope` is
    'company' or 'hod'; HOD-scoped entries are averaged across HODs by the sync.

    Restricted to Admin / Super Admin (H12): scoring is a governance-authority action, so
    general SMOps/staff can no longer enter scores directly."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can enter scores.")
    return await save_manual_score(current_user, payload)


# ─────────────────────────────────────────────────────────────
# Dashboards
# ─────────────────────────────────────────────────────────────
def _scope(period: Optional[str], company_id: Optional[str], om_id: Optional[str]) -> dict:
    return {"period": period, "company_id": company_id, "om_id": om_id}


@router.get("/dashboards/analytics")
async def dashboard_analytics(
    period: Optional[str] = Query(None, description="'YYYY-MM'; defaults to this month"),
    company_id: Optional[str] = Query(None),
    om_id: Optional[str] = Query(None),
    scheduled_by: Optional[str] = Query(None, description="internal | client — OM-Clients grid filter"),
    current_user: dict = Depends(get_current_user),
):
    """Admin overview — KPI cards, the client health matrix, OM league table, top-delayed
    clients, the OM-Clients activity-status grid and the open action-item feed.
    Role-scoped: SMOps see only their own companies, clients only themselves."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_analytics(
        current_user, {**_scope(period, company_id, om_id), "scheduled_by": scheduled_by})


@router.get("/dashboards/staff")
async def dashboard_staff(
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    om_id: Optional[str] = Query(None),
    scheduled_by: Optional[str] = Query(None, description="internal | client — activity-grid filter"),
    current_user: dict = Depends(get_current_user),
):
    """OM / SMOps view — my clients, the activity grid and open follow-ups."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_staff_dashboard(
        current_user, {**_scope(period, company_id, om_id), "scheduled_by": scheduled_by})


@router.get("/dashboards/client")
async def dashboard_client(
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None, description="Staff only — target company"),
    current_user: dict = Depends(get_current_user),
):
    """Client view — operational KPIs plus the Success-Measure scorecard for the month."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_learner_dashboard(current_user, _scope(period, company_id, None))


@router.get("/dashboards/escalations")
async def dashboard_escalations(
    company_id: Optional[str] = Query(None),
    om_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Active + resolved escalations with the L1/L2/L3 counts.

    ⚠ Levels here come from Engine B (T+5 HOD / T+7 HR / T+10 MD). The mails recipients
    actually receive come from Engine A on a D+1/D+2/D+3 cadence. Both are ported from
    the source, which runs both — see tpms_escalation_service for the full note.
    """
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_escalation_dashboard(current_user, _scope(None, company_id, om_id))


@router.get("/dashboards/hod")
async def dashboard_hod(
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    member_id: Optional[str] = Query(None, description="HOD to report on"),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(get_current_user),
):
    """One HOD's activity scorecard, occurrence tracker, alerts and open follow-ups.
    A date-range (from/to) overrides `period` for the This-Month/Last-Month/Quarter/Custom
    presets; grouping stays per-month so a multi-month range shows one column per month."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    scope = _scope(period, company_id, None)
    scope.update({"member_id": member_id, "date_from": date_from, "date_to": date_to})
    return await get_hod_dashboard(current_user, scope)


@router.get("/dashboards/employee-activity")
async def dashboard_employee_activity(
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    member_id: Optional[str] = Query(None),
    designation: Optional[str] = Query(None),
    scheduled_by: Optional[str] = Query(None, description="internal | client"),
    current_user: dict = Depends(get_current_user),
):
    """Per-employee task completion across the company, with a per-activity breakdown."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    scope = _scope(period, company_id, None)
    scope.update({"member_id": member_id, "designation": designation,
                  "scheduled_by": scheduled_by})
    return await get_employee_activity(current_user, scope)


@router.get("/dashboards/implementation")
async def dashboard_implementation(
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    om_id: Optional[str] = Query(None, description="Narrow to the companies this OM owns"),
    current_user: dict = Depends(get_current_user),
):
    """Implementation Tracker — Success-Measure scorecard, manual-score entry, proof
    uploads and the client × activity matrix. Pick a single company to see its detail."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_implementation_tracker(current_user, _scope(period, company_id, om_id))


@router.get("/reports/logs")
async def reports_logs(
    channel: str = Query("email", description="email | whatsapp"),
    status: Optional[str] = Query(None),
    side: Optional[str] = Query(None, description="staff | company"),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=3000),
    current_user: dict = Depends(get_current_user),
):
    """Delivery logs with KPI counts and a per-day sparkline. Paginated server-side —
    the Apps Script truncated to the latest 3000 rows client-side."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    return await get_logs_report(current_user, channel, {
        "status": status, "side": side, "from": date_from, "to": date_to,
        "skip": skip, "limit": limit,
    })


@router.get("/reports/reviews")
async def reports_reviews(
    source: str = Query("accountability", description="form type"),
    period: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    respondent_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Submitted rating matrices / checklists per respondent, plus the monthly trend."""
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_review_reports(current_user, source, {
        "period": period, "company_id": company_id, "respondent_id": respondent_id,
    })


@router.post("/success-measures/sync")
async def success_measures_sync(
    period: Optional[str] = Query(None, description="'YYYY-MM'; defaults to this month"),
    current_user: dict = Depends(get_current_user),
):
    """One-click recalculate of everything the dashboards read — the ERP equivalent of running
    the Apps Script syncAutoFeed + seedSuccessMeasures + syncSuccessMeasures triggers together.
    Also runs daily in the scheduler."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.tpms_escalation_service import sync_auto_feed
    auto = await sync_auto_feed()            # create/close Action_Items + refresh Escalations
    scores = await run_score_daily(period)   # seed + recompute Success_Measures
    return {"ok": True, "auto_feed": auto, "scores": scores}


@router.post("/success-measures/dedupe")
async def success_measures_dedupe(current_user: dict = Depends(get_current_user)):
    """Collapse duplicate success-measure rows to the latest per key. Admin-only, one-off."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.tpms_score_service import dedupe_success_measures
    return await dedupe_success_measures()


# GET /form-mail-logs used to live here, backing the TPMS ▸ Form Mail Logs admin page. Both were
# removed. The rows it read still exist and are still maintained — tpms_form_assignments is what
# makes each mailed link resolvable, single-use and expiring — they simply have no viewer. The
# delivery outcome of a form mail is still recorded in the `notifications` collection like every
# other send, so the Logs Report remains the place to check whether a mail went out.


# ─────────────────────────────────────────────────────────────
# TPMS ▸ Export / Import (Calendar toolbar)
#
# Admin-only. The workbook is a full TPMS backup: it contains live form-link tokens and
# respondent email addresses, so it must never be reachable by a client-side user.
# ─────────────────────────────────────────────────────────────
@router.get("/export/client")
async def export_client_report(
    company_id: str = Query(..., description="The client to report on"),
    period: Optional[str] = Query(None, description="'YYYY-MM'; defaults to this month"),
    date_from: Optional[str] = Query(None, alias="from", description="YYYY-MM-DD; overrides period"),
    date_to: Optional[str] = Query(None, alias="to", description="YYYY-MM-DD; equal to `from` for a single day"),
    all_time: bool = Query(False, description="Ignore the window; export the full history"),
    current_user: dict = Depends(get_current_user),
):
    """One client's TPMS record as an Excel / Google Sheets workbook, for a chosen window.

    Window: the selected `period` month by default, an explicit `from`/`to` range (set both
    to the same date for one day), or `all_time=true` for the client's whole history. Every
    detail sheet is cut to it. The Summary always describes `period`, mirroring the Client
    View, and the cover states both. Read-only.

    Scoped like every other TPMS read: get_learner_dashboard refuses a company the caller
    may not see, so a client user can only ever export themselves.
    """
    from fastapi.responses import StreamingResponse

    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        report = await build_client_report(
            current_user, company_id, period,
            date_from=date_from, date_to=date_to, all_time=all_time)
    except ExportNotPermitted as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    content = export_client_workbook(report)
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "-"
                   for ch in str(report.get("company") or "client")).strip() or "client"
    # Name the file after what it actually contains, so downloads of the same client for
    # different windows don't collide in the download folder.
    if all_time:
        stamp = "all-time"
    elif date_from or date_to:
        stamp = f"{date_from or 'start'} to {date_to or 'today'}"
    else:
        stamp = str(report.get("period") or "")
    filename = f"TPMS {safe} {stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Access-Control-Expose-Headers": "Content-Disposition"},
    )


@router.get("/export")
async def export_tpms(current_user: dict = Depends(get_current_user)):
    """Download the whole of TPMS as one .xlsx workbook, a sheet per collection."""
    from fastapi.responses import StreamingResponse
    from app.services.tpms_backup_service import export_workbook

    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only an admin may export TPMS data.")

    content, counts = await export_workbook()
    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="tpms-export-{stamp}.xlsx"',
                 # Row counts travel in a header so the UI can report what was exported without
                 # having to parse the workbook it just downloaded.
                 "X-Tpms-Export-Rows": str(sum(counts.values())),
                 "Access-Control-Expose-Headers": "Content-Disposition, X-Tpms-Export-Rows"},
    )


@router.post("/import")
async def import_tpms(file: UploadFile = File(...),
                      current_user: dict = Depends(get_current_user)):
    """Load an exported workbook back in. Two paths, by sheet:

    • `Schedules` — a row with a BLANK Schedule ID is replayed through create_schedule, exactly
      as if it had been entered in the Schedule modal: recurrence expanded, reminders attached,
      tracker rows written, schedule mail sent and per-assignee form links minted. Rows that
      already carry an ID are skipped, so re-importing the file you exported creates nothing.
    • every other sheet — add-only; a row whose _id already exists is skipped.

    Non-destructive by design: nothing is updated and nothing is deleted, so re-running an
    import is harmless and a stale file cannot roll back live data.
    """
    from app.services.tpms_backup_service import import_workbook

    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only an admin may import TPMS data.")
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Please upload the .xlsx workbook produced by Export.")

    try:
        # The importer schedules AS the caller — create_schedule needs a real user for its
        # write-scoping check and for the "scheduled by" dimension it stamps on each occurrence.
        report = await import_workbook(await file.read(), current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TPMS import failed: {e}")
        raise HTTPException(status_code=400, detail=f"Could not read that workbook: {e}")

    return report
