"""
WhatsApp template library — author in the CRM, submit to Meta, track approval.

These rows are template *definitions* living on the WhatsApp Business Account, not
per-notification wiring. Two modules point at them:

  • TPMS ▸ Templates      — wiring keyed (activity × side × event), in tpms_whatsapp_templates
  • Task Management ▸ Templates — wiring keyed by trigger slug, in notification_templates

Both send through the same WhatsApp Business Account, so they share ONE library: a template
approved for a task reminder is the same object as one approved for a TPMS reminder, and
maintaining two copies of this Graph-API plumbing would only let them drift.

The router carries no prefix of its own so it can be mounted twice — once at /meta-templates
for the module-neutral callers, and once inside the TPMS router, which preserves the
/tpms/meta-templates paths the TPMS admin screen has always used.

Lifecycle: DRAFT ─submit→ PENDING ─Meta review→ APPROVED | REJECTED ─correct→ PENDING …
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.tpms import (
    COLL_META_TEMPLATES,
    COLL_WHATSAPP_TEMPLATES,
    META_BUTTON_TYPES,
    META_CATEGORIES,
    META_CATEGORY_UTILITY,
    META_EDITABLE_STATUSES,
    META_HEADER_FORMATS,
    META_HEADER_NONE,
    META_STATUS_APPROVED,
    META_STATUS_DRAFT,
    META_STATUS_PENDING,
    META_VAR_NUMBERED,
    META_VAR_STYLES,
)

# Only Admin / Super Admin manage the template library, in either module.
STAFF_ROLES = {"superadmin", "admin"}

router = APIRouter(tags=["WhatsApp Template Library"])


def _serialize(doc: dict) -> dict:
    """Mongo doc → JSON-safe dict (matches the TPMS router's own serializer)."""
    out = dict(doc)
    out["_id"] = str(doc.get("_id"))
    return out


# ═════════════════════════════════════════════════════════════
# WhatsApp template library — author in TPMS, submit to Meta, track approval.
#
# These rows are template *definitions* living on the WhatsApp Business Account. The
# activity × side × event rows below (`/whatsapp-templates`) are the notification *wiring*
# and may only point at a template Meta has APPROVED.
#
# Lifecycle: DRAFT ─submit→ PENDING ─Meta review→ APPROVED | REJECTED ─correct→ PENDING …
# ═════════════════════════════════════════════════════════════
def _meta_admin(current_user: dict) -> None:
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403,
                            detail="Only Admin / Super Admin can manage WhatsApp templates.")


def _meta_oid(template_id: str) -> ObjectId:
    try:
        return ObjectId(template_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid template id")


def _clean_buttons(raw) -> list:
    """Normalise the button list to the stored shape, dropping anything unrecognised rather
    than letting a malformed row reach the payload builder."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="buttons must be a list")
    out = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        btype = str(b.get("type") or "").strip().upper()
        if btype not in META_BUTTON_TYPES:
            continue
        out.append({
            "type": btype,
            "text": str(b.get("text") or "").strip(),
            "url": str(b.get("url") or "").strip() or None,
            "url_example": str(b.get("url_example") or "").strip() or None,
            "phone_number": str(b.get("phone_number") or "").strip() or None,
        })
    return out


def _meta_template_doc(payload: dict) -> dict:
    """Payload → the authored definition we store. Validation proper lives in
    meta_whatsapp_service.validate_template so the same rules serve save, check and submit."""
    name = str(payload.get("name") or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")

    category = str(payload.get("category") or META_CATEGORY_UTILITY).strip().upper()
    if category not in META_CATEGORIES:
        raise HTTPException(status_code=400,
                            detail=f"category must be one of {', '.join(META_CATEGORIES)}")

    header_format = str(payload.get("header_format") or META_HEADER_NONE).strip().upper()
    if header_format not in META_HEADER_FORMATS:
        raise HTTPException(status_code=400,
                            detail=f"header_format must be one of {', '.join(META_HEADER_FORMATS)}")

    style = str(payload.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    if style not in META_VAR_STYLES:
        raise HTTPException(status_code=400,
                            detail=f"variable_style must be one of {', '.join(META_VAR_STYLES)}")

    def _examples(key):
        raw = payload.get(key) or []
        return [str(v) for v in raw] if isinstance(raw, list) else []

    minutes = payload.get("code_expiration_minutes")
    if minutes in ("", None):
        minutes = None
    else:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="code_expiration_minutes must be a number")

    return {
        "name": name,
        "language": str(payload.get("language") or "en").strip() or "en",
        "category": category,
        "variable_style": style,
        "header_format": header_format,
        "header_text": str(payload.get("header_text") or "").strip() or None,
        "header_examples": _examples("header_examples"),
        "header_handle": str(payload.get("header_handle") or "").strip() or None,
        "header_media_url": str(payload.get("header_media_url") or "").strip() or None,
        "body": str(payload.get("body") or ""),
        "body_examples": _examples("body_examples"),
        "footer": str(payload.get("footer") or "").strip() or None,
        "buttons": _clean_buttons(payload.get("buttons")),
        "add_security_recommendation": bool(payload.get("add_security_recommendation", True)),
        "code_expiration_minutes": minutes,
    }


@router.get("/meta-templates")
async def list_meta_templates(
    status: Optional[str] = Query(None, description="DRAFT | PENDING | APPROVED | REJECTED"),
    current_user: dict = Depends(get_current_user),
):
    """The WhatsApp template library with each row's Meta approval status. Admin only."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import config_status

    query = {}
    if status:
        query["status"] = status.strip().upper()
    docs = await get_collection(COLL_META_TEMPLATES).find(query).to_list(500)
    docs.sort(key=lambda d: (d.get("name") or "").lower())
    return {"templates": [_serialize(d) for d in docs], "meta": config_status()}


@router.get("/meta-templates/approved")
async def list_approved_meta_templates(current_user: dict = Depends(get_current_user)):
    """Only APPROVED templates — the set a TPMS WhatsApp notification may be wired to.

    Each row carries the parameter slots the template declares, so the notification-mapping
    screen can ask for exactly the right number of fields instead of guessing."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import extract_variables, ordered_body_variables

    docs = await get_collection(COLL_META_TEMPLATES).find(
        {"status": META_STATUS_APPROVED}).to_list(500)
    docs.sort(key=lambda d: (d.get("name") or "").lower())

    out = []
    for d in docs:
        style = d.get("variable_style") or META_VAR_NUMBERED
        body_vars = ordered_body_variables(d.get("body") or "", style)
        header_vars = (extract_variables(d.get("header_text") or "")
                       if (d.get("header_format") or META_HEADER_NONE) == "TEXT" else [])
        url_buttons = [
            {"index": i, "text": b.get("text") or "", "url": b.get("url") or ""}
            for i, b in enumerate(d.get("buttons") or [])
            if str(b.get("type") or "").upper() == "URL" and extract_variables(b.get("url") or "")
        ]
        out.append({
            "_id": str(d["_id"]),
            "name": d.get("name"),
            "language": d.get("language") or "en",
            "category": d.get("meta_category") or d.get("category"),
            "variable_style": style,
            "body": d.get("body") or "",
            "header_format": d.get("header_format") or META_HEADER_NONE,
            "body_variables": body_vars,
            "header_variables": header_vars,
            "url_buttons": url_buttons,
        })
    return {"templates": out}


@router.post("/meta-templates")
async def save_meta_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Create or update a template definition. Admin only.

    Editing is allowed only while DRAFT or REJECTED — once a template is PENDING or APPROVED
    the definition belongs to Meta, and changing it locally would leave the CRM describing
    something different from what actually gets sent."""
    _meta_admin(current_user)
    doc = _meta_template_doc(payload)
    coll = get_collection(COLL_META_TEMPLATES)
    now = datetime.utcnow()
    template_id = str(payload.get("_id") or payload.get("id") or "").strip()

    if template_id:
        oid = _meta_oid(template_id)
        existing = await coll.find_one({"_id": oid})
        if not existing:
            raise HTTPException(status_code=404, detail="Template not found")
        status = str(existing.get("status") or META_STATUS_DRAFT).upper()
        if status not in META_EDITABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"This template is {status} at Meta and can no longer be edited. "
                       "Create a new template (or a new version under a different name) instead.")
        clash = await coll.find_one({"name": doc["name"], "language": doc["language"],
                                     "_id": {"$ne": oid}})
        if clash:
            raise HTTPException(status_code=409,
                                detail=f"A '{doc['language']}' template named "
                                       f"'{doc['name']}' already exists.")
        # A corrected rejection goes back to DRAFT — it has not been re-reviewed yet.
        doc.update({"updated_at": now, "status": META_STATUS_DRAFT, "rejected_reason": None})
        await coll.update_one({"_id": oid}, {"$set": doc})
        return {"ok": True, "_id": template_id, "status": META_STATUS_DRAFT}

    if await coll.find_one({"name": doc["name"], "language": doc["language"]}):
        raise HTTPException(status_code=409,
                            detail=f"A '{doc['language']}' template named "
                                   f"'{doc['name']}' already exists.")
    doc.update({
        "status": META_STATUS_DRAFT, "meta_template_id": None, "rejected_reason": None,
        "created_at": now, "updated_at": now,
        "created_by": current_user.get("email") or str(current_user.get("_id") or ""),
    })
    result = await coll.insert_one(doc)
    return {"ok": True, "_id": str(result.inserted_id), "status": META_STATUS_DRAFT}


@router.post("/meta-templates/check")
async def check_meta_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Validate a template and return the exact JSON that would be sent to Meta.

    This is the modal's "Check payload" step — submitting is irreversible, so the payload is
    reviewable first. No Graph call is made and nothing is stored."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import build_create_payload, validate_template

    doc = _meta_template_doc(payload)
    errors = validate_template(doc)
    return {"valid": not errors, "errors": errors, "payload": build_create_payload(doc)}


@router.post("/meta-templates/{template_id}/submit")
async def submit_meta_template(template_id: str, current_user: dict = Depends(get_current_user)):
    """Submit a template to Meta for review. Admin only.

    Irreversible: Meta assigns the template an id and it enters PENDING. A rejection comes back
    with a reason, and the template returns to an editable state so it can be corrected and
    resubmitted."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import (
        MetaTemplateError, create_message_template, edit_message_template, resolve_header_handle,
        validate_template,
    )

    coll = get_collection(COLL_META_TEMPLATES)
    oid = _meta_oid(template_id)
    doc = await coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")

    status = str(doc.get("status") or META_STATUS_DRAFT).upper()
    if status not in META_EDITABLE_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"Template is already {status} at Meta — nothing to submit.")

    errors = validate_template(doc)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    now = datetime.utcnow()
    existing_id = str(doc.get("meta_template_id") or "").strip()
    try:
        handle = await resolve_header_handle(doc)
        if handle and handle != doc.get("header_handle"):
            doc["header_handle"] = handle
            await coll.update_one({"_id": oid}, {"$set": {"header_handle": handle}})
        # A REJECTED template still occupies its name on the WABA, and Meta answers a second
        # create for that name with 2388024 "Content in this language already exists". The only
        # way to act on a rejection is to correct the template Meta already holds, which keeps
        # its id and puts it back into review. A DRAFT has no id yet, so it is created.
        result = (await edit_message_template(existing_id, doc) if existing_id
                  else await create_message_template(doc))
    except MetaTemplateError as e:
        # The definition is untouched and still editable — record why the attempt failed so the
        # admin sees it on the row rather than only in a toast that disappears.
        await coll.update_one({"_id": oid},
                              {"$set": {"last_submit_error": e.message, "updated_at": now}})
        raise HTTPException(status_code=400, detail=e.message)

    meta_status = str(result.get("status") or META_STATUS_PENDING).upper()
    await coll.update_one({"_id": oid}, {"$set": {
        "status": meta_status,
        "meta_template_id": str(result.get("id") or "") or None,
        "meta_category": str(result.get("category") or "").upper() or None,
        "rejected_reason": None, "last_submit_error": None,
        "submitted_at": now, "updated_at": now, "synced_at": now,
        "submitted_by": current_user.get("email") or str(current_user.get("_id") or ""),
    }})
    return {"ok": True, "status": meta_status, "meta_template_id": result.get("id")}


@router.post("/meta-templates/test")
async def test_meta_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Send this template to one phone number so it can be read on a real handset. Admin only.

    Takes the template straight from the composer, so it works on a template that has not been
    saved yet. Two modes, because WhatsApp allows exactly two things:

      · APPROVED  — sent as the real template message, exactly as recipients will get it.
      · anything else — Meta refuses to deliver an unapproved template, so the same copy goes
        as a free-form message instead. That only lands if the number messaged this business
        in the last 24 hours (Meta's customer-service window), which the response spells out.
    """
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import (
        build_sample_send_components, render_preview_text,
    )
    from app.services.notification_service import (
        send_whatsapp_notification, send_whatsapp_template,
    )
    from app.services.tpms_notify_service import normalize_phone

    phone = normalize_phone(str(payload.get("phone") or "").strip())
    if not phone:
        raise HTTPException(status_code=400, detail="Enter a valid phone number.")

    # The *structure* comes from the stored row when one is named — its status decides the mode,
    # and a saved definition must not be talked out of sync by whatever the form holds. The
    # *sample values* come from the form regardless: they are not part of the definition Meta
    # owns, they are only what fills the {{n}} slots in this test.
    template_id = str(payload.get("template_id") or "").strip()
    form = payload.get("template") or {}
    stored = None
    if template_id:
        stored = await get_collection(COLL_META_TEMPLATES).find_one({"_id": _meta_oid(template_id)})

    def _samples(key):
        raw = form.get(key)
        return [str(v) for v in raw] if isinstance(raw, list) else None

    if stored:
        doc = dict(stored)
        for key in ("header_examples", "body_examples"):
            values = _samples(key)
            if values is not None:
                doc[key] = values
    else:
        doc = _meta_template_doc(form)
    if not str(doc.get("body") or "").strip() and doc.get("category") != "AUTHENTICATION":
        raise HTTPException(status_code=400, detail="Write the body before sending a test.")

    approved = bool(stored) and str(stored.get("status") or "").upper() == META_STATUS_APPROVED

    # Remember the values tested with, so reopening the template does not lose them. Only the
    # example arrays are written — never the definition, which stays exactly as Meta has it.
    if stored:
        samples = {k: doc[k] for k in ("header_examples", "body_examples")
                   if _samples(k) is not None}
        if samples:
            await get_collection(COLL_META_TEMPLATES).update_one(
                {"_id": stored["_id"]}, {"$set": samples})

    if approved:
        components, params = build_sample_send_components(doc)
        ok = await send_whatsapp_template(
            phone, doc.get("name"), doc.get("language") or "en", params,
            user_id=str(current_user.get("_id") or "") or None,
            slug="tpms_meta_template_test", components=components)
        note = "Sent as the approved template — this is exactly what recipients receive."
    else:
        ok = await send_whatsapp_notification(
            phone, render_preview_text(doc),
            user_id=str(current_user.get("_id") or "") or None,
            slug="tpms_meta_template_preview")
        note = ("This template is not approved yet, so the text was sent as a normal message "
                "instead — buttons and formatting will only appear once Meta approves it. "
                "Free-form messages reach a number only within 24 hours of it messaging you.")

    if not ok:
        raise HTTPException(
            status_code=502,
            detail=("WhatsApp did not accept the message. Check WHATSAPP_PHONE_NUMBER_ID is set "
                    "and the number is on WhatsApp"
                    + ("" if approved else "; an unapproved template can only be previewed "
                       "within 24 hours of that number messaging you")
                    + ". The delivery log has the exact error."))
    return {"ok": True, "sent_to": phone, "mode": "template" if approved else "preview",
            "note": note}


@router.post("/meta-templates/sync")
async def sync_meta_templates(current_user: dict = Depends(get_current_user)):
    """Pull the current approval status of every template from Meta. Admin only.

    Meta reviews asynchronously and does not call back, so this is how PENDING becomes
    APPROVED or REJECTED (with its reason). Templates approved directly in WhatsApp Manager
    that we have never seen are imported as read-only library rows, so the notification screen
    can offer them too."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import MetaTemplateError, fetch_templates

    try:
        rows = await fetch_templates()
    except MetaTemplateError as e:
        raise HTTPException(status_code=502, detail=e.message)

    coll = get_collection(COLL_META_TEMPLATES)
    now = datetime.utcnow()
    updated = imported = 0
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        language = str(row.get("language") or "en").strip()
        remote = {
            "status": str(row.get("status") or "").strip().upper() or META_STATUS_PENDING,
            "meta_template_id": str(row.get("id") or "") or None,
            "meta_category": str(row.get("category") or "").strip().upper() or None,
            "rejected_reason": row.get("rejected_reason") or None,
            "quality_score": ((row.get("quality_score") or {}).get("score")
                              if isinstance(row.get("quality_score"), dict)
                              else row.get("quality_score")),
            "synced_at": now, "updated_at": now,
        }
        existing = await coll.find_one({"name": name, "language": language})
        if existing:
            await coll.update_one({"_id": existing["_id"]}, {"$set": remote})
            updated += 1
        else:
            # Approved outside the CRM — record it so it is selectable, flagged as not authored
            # here (there is no local definition to edit or resubmit).
            await coll.insert_one({
                "name": name, "language": language,
                "category": remote["meta_category"] or META_CATEGORY_UTILITY,
                "variable_style": META_VAR_NUMBERED,
                "header_format": META_HEADER_NONE, "body": _body_of(row),
                "body_examples": [], "buttons": [], "source": "meta_import",
                "created_at": now, **remote,
            })
            imported += 1
    return {"ok": True, "updated": updated, "imported": imported, "total": len(rows)}


def _body_of(row: dict) -> str:
    """The BODY text out of a template Meta returned, so an imported row still shows its copy
    (and its {{n}} slots) in the library."""
    for component in (row.get("components") or []):
        if str((component or {}).get("type") or "").upper() == "BODY":
            return str(component.get("text") or "")
    return ""


@router.delete("/meta-templates/{template_id}")
async def delete_meta_template(template_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a template. Admin only.

    Refused while ANY notification is still wired to it — deleting it at Meta would make those
    notifications start failing silently at send time. Both wiring tables are checked: TPMS's
    activity×side×event rows and Task Management's per-trigger rows. Checking only one would
    let a template the other module depends on be deleted out from under it."""
    _meta_admin(current_user)
    from app.services.meta_whatsapp_service import MetaTemplateError, delete_message_template

    coll = get_collection(COLL_META_TEMPLATES)
    oid = _meta_oid(template_id)
    doc = await coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")

    name = doc.get("name")
    users = []
    for u in await get_collection(COLL_WHATSAPP_TEMPLATES).find(
            {"meta_template_name": name}).to_list(20):
        users.append(f"TPMS {u.get('activity') or '*'}/{u.get('side')}/{u.get('event')}")
    for u in await get_collection("notification_templates").find(
            {"meta_template_name": name}).to_list(20):
        users.append(f"Notification {u.get('slug') or '?'}")
    if users:
        where = ", ".join(users[:5])
        raise HTTPException(
            status_code=409,
            detail=f"'{name}' is still used by {len(users)} notification(s): "
                   f"{where}. Point them at another template first.")

    if doc.get("meta_template_id"):
        try:
            await delete_message_template(doc.get("name"), doc.get("meta_template_id"))
        except MetaTemplateError as e:
            raise HTTPException(status_code=400, detail=e.message)
    await coll.delete_one({"_id": oid})
    return {"ok": True}
