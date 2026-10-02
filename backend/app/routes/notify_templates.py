"""
Notification Templates — the wiring API for every slug-keyed notification.

The central Notification Templates module manages Delegation, Checklist, Calendar events,
Sessions & attendance, reminders, To-Do and account mail through this router. TPMS
(/tpms/mail-templates, /tpms/whatsapp-templates) and Leadership Score (/leadership/whatsapp-
template) keep their own stores and endpoints; the module embeds their existing screens.

Storage is deliberately the EXISTING `notification_templates` collection, the same one
`notification_service.fetch_template` has always read. Nothing is migrated and nothing is
duplicated: this is an editor over the same rows, so a template configured here is the one
that actually sends.

  slug            "<trigger>_email" | "<trigger>_whatsapp"   (unchanged)
  scope           "staff" | "company"                        (unchanged)
  body / subject  the email content                          (unchanged)
  meta_template_name / meta_lang / meta_params                (unchanged)
  meta_header_params / meta_button_params                    header and button slots

WHO MAY DO WHAT: notification templates are managed by Super Admin and Admin only — every
endpoint here, including Active / Inactive, test sends and the reminder schedule. The legacy
/settings/templates endpoints over the same rows apply the same rule.

The WhatsApp template LIBRARY is not served here: it lives on the WhatsApp Business Account and
is shared with TPMS, so it is mounted once at /meta-templates (routes/meta_templates.py).
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.notify_modules import (
    NOTIFY_MODULES,
    SEND_BUILTIN_FALLBACK,
    module_for_slug,
    module_triggers,
    module_variables,
    trigger_variables,
)
from app.models.tpms import COLL_META_TEMPLATES, META_STATUS_APPROVED

router = APIRouter(prefix="/notify-templates", tags=["Notification Templates"])

COLLECTION = "notification_templates"
CHANNELS = ("email", "whatsapp")
SCOPES = ("staff", "company")

# Notification templates are an Admin / Super Admin job, everywhere.
STAFF_ROLES = {"superadmin", "admin"}


def _admin(current_user: dict) -> None:
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403,
                            detail="Only Admin / Super Admin can manage notification templates.")


def _oid(template_id: str) -> ObjectId:
    try:
        return ObjectId(template_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid template id")


def _serialize(doc: dict) -> dict:
    out = dict(doc)
    out["_id"] = str(doc.get("_id"))
    out["module"] = module_for_slug(doc.get("slug"))
    return out


def _field_list(payload: dict, key: str) -> list:
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail=f"{key} must be a list of field names")
    return [str(v).strip() for v in raw if str(v).strip()]


def _button_map(raw) -> list:
    """[{index, field}] — `index` is the button's real position in the approved template.

    Meta addresses button parameters positionally, and a variable URL button is rarely the
    first button, so the position among *variable* buttons is not the same number. Mirrors the
    TPMS wiring endpoint so both modules store the identical shape and the shared send-time
    component builder can read either.
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="meta_button_params must be a list")
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


# ─────────────────────────────────────────────────────────────
# Catalogue — what the screen renders before anything is configured
# ─────────────────────────────────────────────────────────────
@router.get("/modules")
async def list_modules(current_user: dict = Depends(get_current_user)):
    """Every module, its triggers and the placeholders each may map, plus Meta health.

    Each trigger also says whether its sending code falls back to a BUILT-IN message when no
    template exists (`builtin`), so the screen can say "sends the standard email" rather than
    "sends nothing" — read from notification_service.DEFAULT_TEMPLATES, never altered.
    """
    _admin(current_user)
    from app.services.meta_whatsapp_service import config_status
    from app.services.notification_service import DEFAULT_TEMPLATES

    def _with_builtin(mod: dict, trigger: dict) -> dict:
        fallback = mod.get("send_rule") == SEND_BUILTIN_FALLBACK
        return {
            **trigger,
            "builtin": {ch: fallback and f"{trigger['slug']}_{ch}" in DEFAULT_TEMPLATES
                        for ch in CHANNELS},
        }

    return {
        "modules": [
            {
                "key": key,
                "label": mod["label"],
                "description": mod["description"],
                "send_rule": mod.get("send_rule"),
                "staff_only": bool(mod.get("staff_only")),
                "triggers": [_with_builtin(mod, t) for t in module_triggers(key)],
                "variables": module_variables(key),
            }
            for key, mod in NOTIFY_MODULES.items()
        ],
        "meta": config_status(),
        # Only Admin / Super Admin reach this point, and they may do everything.
        "access": {
            "company_id": None, "is_admin": True,
            "can_create": True, "can_update": True, "can_delete": True, "can_toggle": True,
        },
    }


# ─────────────────────────────────────────────────────────────
# Wiring rows
# ─────────────────────────────────────────────────────────────
@router.get("")
async def list_notify_templates(
    module: Optional[str] = Query(None, description="any registered module key; omit for all"),
    channel: Optional[str] = Query(None, description="email | whatsapp"),
    scope: str = Query("staff", description="staff | company"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Configured templates, one row per (trigger × channel).

    Returns only rows whose slug is a REGISTERED trigger, so the screen never offers a template
    no sending code reads.
    """
    _admin(current_user)
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail="scope must be 'staff' or 'company'")
    if channel and channel not in CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'whatsapp'")

    query: dict = {"scope": scope}
    query["company_id"] = str(company_id) if (scope == "company" and company_id) else None
    docs = await get_collection(COLLECTION).find(query).to_list(1000)

    rows = []
    for d in docs:
        slug = str(d.get("slug") or "")
        owner = module_for_slug(slug)
        if not owner or (module and owner != module):
            continue
        if channel and not slug.endswith(f"_{channel}"):
            continue
        rows.append(_serialize(d))
    rows.sort(key=lambda r: (str(r.get("slug") or "")))
    return {"templates": rows}


@router.post("")
async def upsert_notify_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Create or update one trigger's template on one channel. Admin only.

    Keyed (slug, scope, company_id) — the same key `fetch_template` resolves on — so saving is
    an upsert and creating and editing hit one endpoint.

    `is_active` is deliberately NOT writable here: status changes only through the status
    endpoint below.
    """
    _admin(current_user)

    trigger = str(payload.get("trigger") or "").strip()
    channel = str(payload.get("channel") or "").strip().lower()
    scope = str(payload.get("scope") or "staff").strip().lower()
    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'whatsapp'")
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail="scope must be 'staff' or 'company'")
    if not module_for_slug(trigger):
        raise HTTPException(status_code=400,
                            detail=f"'{trigger}' is not a registered notification trigger.")

    company_id = str(payload.get("company_id") or "") or None
    if scope == "company" and not company_id:
        raise HTTPException(status_code=400, detail="company_id is required for a company template")
    if scope == "staff":
        company_id = None

    slug = f"{trigger}_{channel}"
    doc = {
        "slug": slug,
        "name": str(payload.get("name") or trigger.replace("_", " ").title()),
        "channel": channel,
        "scope": scope,
        "company_id": company_id,
        "body": str(payload.get("body") or ""),
        "updated_at": datetime.utcnow(),
        "updated_by": str(current_user.get("_id") or ""),
    }

    note = ""
    if channel == "email":
        doc["subject"] = str(payload.get("subject") or "")
    else:
        # A WhatsApp row may point at a Meta-approved template (business-initiated) or carry
        # only free-form text, which Meta delivers solely inside the 24h service window. Both
        # are legitimate, so an empty name is allowed — but a name that is not approved is not,
        # for the same reason TPMS refuses it: the failure would otherwise be a silent
        # per-recipient error at send time.
        meta_name = str(payload.get("meta_template_name") or "").strip().lower()
        note = await _assert_meta_approved(meta_name) if meta_name else ""
        doc.update({
            "meta_template_name": meta_name or None,
            "meta_lang": str(payload.get("meta_lang") or "en").strip() or "en",
            "meta_params": _field_list(payload, "meta_params"),
            "meta_header_params": _field_list(payload, "meta_header_params"),
            "meta_button_params": _button_map(payload.get("meta_button_params")),
        })

    col = get_collection(COLLECTION)
    key = {"slug": slug, "scope": scope, "company_id": company_id}
    existing = await col.find_one(key)
    if existing:
        await col.update_one({"_id": existing["_id"]}, {"$set": doc})
        return {"ok": True, "_id": str(existing["_id"]), "note": note or None}

    doc.update({"created_at": datetime.utcnow(),
                "created_by": str(current_user.get("_id") or ""),
                "is_active": True})
    result = await col.insert_one(doc)
    return {"ok": True, "_id": str(result.inserted_id), "note": note or None}


async def _assert_meta_approved(name: str) -> str:
    """Only a Meta-APPROVED template may be wired to a notification.

    Checked against the local library first (the fast, normal path) and, when the name is not
    APPROVED there, against the WABA itself — templates approved directly in WhatsApp Manager
    before this screen existed are legitimate and must keep working.

    Returns a note when the check could not be completed. Meta being unreachable must not stop
    an admin editing wiring, so that case is allowed through and reported rather than treated
    as a rejection. (Same contract as the TPMS wiring endpoint.)
    """
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
                   "approved templates can be used for WhatsApp notifications.")
    raise HTTPException(
        status_code=400,
        detail=f"'{name}' is not an approved WhatsApp template on this business account. "
               "Create it under Meta Templates and submit it for approval first.")


@router.patch("/{template_id}/status")
async def set_notify_template_status(template_id: str, payload: dict,
                                     current_user: dict = Depends(get_current_user)):
    """Activate / deactivate one template. Admin only.

    An inactive template sends NOTHING — it never falls through to a lower-precedence row or to
    a built-in default (see notification_service.fetch_template). That is what makes this the
    off switch for a single trigger on a single channel.
    """
    _admin(current_user)
    if "is_active" not in payload:
        raise HTTPException(status_code=400, detail="is_active is required")
    is_active = bool(payload.get("is_active"))
    res = await get_collection(COLLECTION).update_one(
        {"_id": _oid(template_id)},
        {"$set": {"is_active": is_active, "updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True, "is_active": is_active}


@router.delete("/{template_id}")
async def delete_notify_template(template_id: str, current_user: dict = Depends(get_current_user)):
    """Remove a configured template. Admin only.

    The trigger itself does not go away — it simply stops sending on that channel (or goes back
    to its built-in message, where it has one) until a template is configured for it again.
    """
    _admin(current_user)
    res = await get_collection(COLLECTION).delete_one({"_id": _oid(template_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# Reminder schedule — when the daily nudge sweep runs
# ─────────────────────────────────────────────────────────────
@router.get("/schedule")
async def get_reminder_schedule(current_user: dict = Depends(get_current_user)):
    """When the time-driven reminders go out, and whether today's run has already happened."""
    _admin(current_user)
    from app.services.task_nudge_service import (
        BACKFILL_FLAG, SETTINGS_COLLECTION, get_send_time, IST,
    )

    hour, minute = await get_send_time()
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    backfill = await get_collection(SETTINGS_COLLECTION).find_one({"key": BACKFILL_FLAG})
    return {
        "hour": hour,
        "minute": minute,
        "timezone": "IST",
        "now_ist": now_ist.strftime("%H:%M"),
        # Which triggers this schedule actually governs — the click-driven ones send instantly
        # and are unaffected, and saying so stops the setting reading as a global mail delay.
        "governs": ["task_due_reminder_daily", "task_due_reminder_weekly", "task_overdue",
                    "task_verification_pending_reminder"],
        "overdue_backlog_absorbed": bool(backfill),
        "overdue_backlog_count": (backfill or {}).get("tasks_stamped"),
    }


@router.put("/schedule")
async def set_reminder_schedule(payload: dict, current_user: dict = Depends(get_current_user)):
    """Move the daily reminder sweep to a different IST time. Admin only.

    Takes effect on the next tick — the scheduler reads the stored time every minute rather
    than caching it at start-up, so there is nothing to restart.
    """
    _admin(current_user)
    from app.services.task_nudge_service import set_send_time

    try:
        hour, minute = await set_send_time(payload.get("hour"), payload.get("minute") or 0,
                                           actor=str(current_user.get("_id") or ""))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e) or "Invalid time")
    return {"ok": True, "hour": hour, "minute": minute, "timezone": "IST"}


@router.post("/schedule/run-now")
async def run_reminder_sweep_now(current_user: dict = Depends(get_current_user)):
    """Run today's reminder sweep immediately instead of waiting for the scheduled time.

    Safe to press twice: every cadence stamps the date it fired, so a second run the same day
    raises nothing. It cannot be used to re-send a reminder somebody has already had.
    """
    _admin(current_user)
    from app.services.task_nudge_service import sweep_task_nudges

    counts = await sweep_task_nudges()
    total = sum(counts.values())
    return {
        "ok": True, "counts": counts, "total": total,
        "note": ("Nothing was due — every cadence had already fired today." if not total
                 else f"Raised {total} reminder(s). Only triggers with an Active template "
                      "were emailed or messaged."),
    }


@router.post("/test")
async def test_notify_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Send one configured trigger to a phone number, using its real wiring. Admin only.

    Distinct from the library's own test (which proves a DEFINITION renders): this proves the
    WIRING — that the mapped data fields land in the right {{n}} slots — using sample values for
    the placeholders, so a mis-ordered mapping is caught here rather than by a recipient.
    """
    _admin(current_user)
    from app.services.notification_service import send_whatsapp_template
    from app.services.tpms_notify_service import normalize_phone
    from app.services.whatsapp_components import build_send_components, resolve_params

    phone = normalize_phone(str(payload.get("phone") or "").strip())
    if not phone:
        raise HTTPException(status_code=400, detail="Enter a valid phone number.")

    trigger = str(payload.get("trigger") or "").strip()
    if not module_for_slug(trigger):
        raise HTTPException(status_code=400,
                            detail=f"'{trigger}' is not a registered notification trigger.")

    scope = str(payload.get("scope") or "staff").strip().lower()
    company_id = str(payload.get("company_id") or "") or None
    doc = await get_collection(COLLECTION).find_one({
        "slug": f"{trigger}_whatsapp", "scope": scope,
        "company_id": company_id if scope == "company" else None})
    if not doc:
        raise HTTPException(status_code=404,
                            detail="This trigger has no WhatsApp template configured yet.")
    meta_name = doc.get("meta_template_name")
    if not meta_name:
        raise HTTPException(
            status_code=400,
            detail="This trigger is not pointed at a Meta template, so there is nothing to "
                   "test — free-form text only reaches a number inside Meta's 24h window.")

    # Sample values: whatever the caller supplied, then the placeholder's own name for anything
    # left over, so every slot is visibly filled and a wrong ORDER is obvious on the handset.
    supplied = payload.get("sample") or {}
    context = {v: str(supplied.get(v) or v.replace("_", " ").title())
               for v in trigger_variables(trigger)}

    params = resolve_params(doc.get("meta_params"), context)
    components = build_send_components(
        params,
        header_keys=doc.get("meta_header_params"),
        button_keys=doc.get("meta_button_params"),
        mapping=context,
    )
    ok = await send_whatsapp_template(
        phone, meta_name, doc.get("meta_lang") or "en", params,
        user_id=str(current_user.get("_id") or "") or None,
        slug=f"{trigger}_whatsapp_test", components=components)
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="WhatsApp did not accept the message. Check WHATSAPP_PHONE_NUMBER_ID is set "
                   "and the number is on WhatsApp — the delivery log has the exact error.")
    return {"ok": True, "sent_to": phone, "params": params}
