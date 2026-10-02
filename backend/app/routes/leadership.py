"""
TPMS ▸ Leadership Score — API routes (mounted under /api/leadership).

Workflow, following the general TPMS forms pattern:

    Configure questions/weightages  →  Open a 2-month cycle  →  Enrol leaders (L4+)
    →  HR assigns 8 feedback givers →  Email each a unique link  →  Giver submits
    →  Response stored             →  Weighted score calculated →  Result / RRO view

ISOLATION
---------
Every route here reads and writes only the `tpms_leadership_*` collections. No existing
TPMS collection, submission, assignment, mail template or score row is touched, so
Accountability / Ownership / Culture / Implementation Feedback behave exactly as before.

The router-wide `_tpms_company_gate` dependency is the same guard the existing forms
router uses, so a company with TPMS switched off cannot reach any of this.

CONFIDENTIALITY BOUNDARY
------------------------
Exactly two endpoints return feedback-giver identity — `GET .../panel` and
`GET .../assignments` — and both are restricted to HR/staff by `_require_manage`.
Every score endpoint returns aggregates built by `leadership_service.subject_score()`,
which never carries a giver id, a giver name or an individual response. A leader reading
their own score therefore cannot learn who said what, regardless of what the UI does.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse

from app.config.settings import settings

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_DOCUMENTS,
    BriefingCreate, CycleCreate, CycleUpdate, DiscussionAck, DiscussionCreate,
    GiverAssignment, QuestionUpdate,
    ResponseSubmit, SubjectCreate, SubjectMode, WeightageUpdate,
    DEGREE_RELATIONS, DEGREES, LEVELS, LEVEL_LABELS, LEVEL_THEMES,
    panel_size_for,
    RECOMMENDED_PANEL_SIZE, RECOMMENDED_PER_RELATION, RELATIONS, RELATION_LABELS,
    LINK_EXPIRED, LINK_SUBMITTED,
    SCALE_MAX, SCALE_MIN, TOTAL_WEIGHTAGE,
    cycle_label, current_cycle, selectable_cycles,
)
from app.services import leadership_service as svc
from app.services import leadership_link_service as links
from app.services import leadership_wa_service as ls_wa

logger = logging.getLogger(__name__)


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("email") or "")


async def _leadership_company_gate(current_user: dict = Depends(get_current_user)) -> None:
    """Router-wide guard — Leadership Score is part of TPMS and follows its switch.

    There is no separate Leadership toggle: TPMS on means Leadership Score on, TPMS off
    means off. One control for both, so the two can never end up disagreeing.
    """
    from app.utils.leadership_access import ensure_leadership_enabled
    await ensure_leadership_enabled(current_user)


router = APIRouter(prefix="/leadership", tags=["Leadership Score"],
                   dependencies=[Depends(_leadership_company_gate)])

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}


def _role(user: dict) -> str:
    return (user.get("role") or "").lower()


def _is_staff(user: dict) -> bool:
    return _role(user) in STAFF_ROLES


def _is_client(user: dict) -> bool:
    return _role(user) in CLIENT_ROLES


def _governance_role(user: dict) -> str:
    """A client user's governance role. Mirrors forms._user_department so HR resolves to
    the same people here as everywhere else in TPMS."""
    return (user.get("governance_role") or user.get("department") or "").strip().lower()


def _is_hr(user: dict) -> bool:
    """A dedicated HR user: a clientuser carrying the HR governance role.

    'HR should identify feedback givers and it should be only known to HR.'

    A clientadmin is deliberately NOT HR here, even when their governance_role says "hr".
    clientadmin is the company's administrative account — often shared, and always able to
    manage users and companies — so treating it as HR would put the giver panel behind the
    broadest client login rather than a named individual. HR must be a person, not an
    administrative role.
    """
    return _role(user) == "clientuser" and _governance_role(user) == "hr"


def _can_manage(user: dict) -> bool:
    """Who runs the process: internal staff, the client's HR, and the client admin.

    This covers the parts of the flow that do NOT reveal who gives feedback — cycles,
    enrolling leaders, reading scores. Panel access is gated separately below.
    """
    return _is_staff(user) or _is_hr(user) or _role(user) == "clientadmin"


def _can_manage_panel(user: dict) -> bool:
    """Who may see or change WHO gives feedback — HR only, plus internal Sparsh staff.

    Deliberately narrower than `_can_manage`: "HR should identify feedback givers and it
    should be only known to HR." A clientadmin still opens cycles and enrols leaders, but
    must never see a panel — knowing who rates whom is on its own enough to de-anonymise a
    small relation group, which is the whole thing this module has to protect. That holds
    even for a clientadmin flagged governance_role=hr; see `_is_hr`.

    Internal staff (superadmin/admin) keep access because they administer and support the
    module across every client, and hold database access regardless.
    """
    return _is_staff(user) or _is_hr(user)


def _self_id(user: dict) -> str:
    return str(user.get("_id"))


def _company_scope(user: dict, company_id: Optional[str]) -> Optional[str]:
    """Like `_company_for`, but staff may decline to name one and get all companies.

    Only for reads that are meaningful unscoped. Anything that WRITES against a company
    still uses `_company_for`, which refuses rather than guessing.
    """
    if _is_client(user):
        return _company_for(user, company_id)
    if _is_staff(user):
        return str(company_id or "").strip() or None
    raise HTTPException(status_code=403, detail="Not authorized to access Leadership Score")


def _company_for(user: dict, company_id: Optional[str]) -> str:
    """Client-side users are pinned to their own company whatever they pass."""
    if _is_client(user):
        own = str(user.get("company_id") or "")
        if not own:
            raise HTTPException(status_code=400, detail="Your account is not linked to a company")
        return own
    if _is_staff(user):
        cid = str(company_id or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="company_id is required")
        return cid
    raise HTTPException(status_code=403, detail="Not authorized to access Leadership Score")


def _can_manage_template(user: dict) -> bool:
    """Who may WRITE the WhatsApp invitation template: internal staff and the client admin.

    Deliberately narrower than `_can_manage`, which HR passes. The template is the wording
    that goes to employees' personal phones under the company's name, and it is submitted
    to Meta for review against a Business Account shared by every client — so authoring it
    is the company's administrative decision rather than part of running a cycle.

    This gates the WHOLE screen, read included — HR has no use for it. When no approved
    template exists the refusal is reported on the giver's own row in Leaders & Givers,
    which is where HR is already working, so nothing they need is behind this page.
    """
    return _is_staff(user) or _role(user) == "clientadmin"


def _require_template_manage(user: dict) -> None:
    if not _can_manage_template(user):
        raise HTTPException(
            status_code=403,
            detail="Only an administrator can write the WhatsApp invitation template. "
                   "HR sends the invitations but does not author them.")


def _require_manage(user: dict) -> None:
    if not _can_manage(user):
        raise HTTPException(
            status_code=403,
            detail="Only HR or an administrator can manage Leadership Score.")


def _require_panel(user: dict) -> None:
    """Guard for every endpoint that exposes or changes the giver panel."""
    if not _can_manage_panel(user):
        raise HTTPException(
            status_code=403,
            detail="Only HR can view or manage the feedback panel. Feedback givers are "
                   "confidential and are known only to HR.")


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))
@router.get("/config")
async def read_config(current_user: dict = Depends(get_current_user)):
    """Levels, relations, degrees and cycle options — so the UI hardcodes nothing."""
    return {
        "levels": [{"code": lv, "label": LEVEL_LABELS[lv], "theme": LEVEL_THEMES[lv]}
                   for lv in LEVELS],
        "relations": [{"code": r, "label": RELATION_LABELS[r]} for r in RELATIONS],
        # `panel_size` is carried per degree so the UI stops treating 8 as universal:
        # 180° collects from four givers, 360° from eight.
        "degrees": [{"code": d, "relations": DEGREE_RELATIONS[d],
                     "panel_size": panel_size_for(d)} for d in DEGREES],
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "recommended_panel_size": RECOMMENDED_PANEL_SIZE,
        "recommended_per_relation": RECOMMENDED_PER_RELATION,
        "required_total_weightage": TOTAL_WEIGHTAGE,
        "current_cycle": current_cycle(),
        # Upcoming windows first, then the current one, then recent history. A cycle whose
        # window has passed can be created but never dispatched — its links are born
        # expired — so the picker must offer at least one window that can still collect.
        "cycles": [{"code": c, "label": cycle_label(c),
                    "expired": links.cycle_is_expired(c)}
                   for c in selectable_cycles(back=6, ahead=3)],
        "can_manage": _can_manage(current_user),
        # Separate from can_manage: a clientadmin runs cycles and enrolment but must not
        # reach the panel. The UI hides panel controls on this flag; the endpoints enforce
        # it independently, so hiding is presentation, not the control.
        "can_manage_panel": _can_manage_panel(current_user),
        "is_staff": _is_staff(current_user),
    }


@router.get("/questions")
async def list_questions(
    level: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The question master this company is scored on.

    Company-scoped: a company that has edited a level reads its own copy, everyone else
    reads the shared default seeded from the HR document.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return {
        "questions": await svc.get_questions(level, include_inactive, company_id=cid),
        "weightage_summary": await svc.weightage_summary(cid),
    }


@router.patch("/questions/{question_id}")
async def patch_question(question_id: str, payload: QuestionUpdate,
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """Reword a question or restate its options. Level and item_id are immutable — they
    key the stored responses.

    The edit lands on THIS COMPANY's copy of the level, forking it from the shared default
    on first write. Before that, one admin's rewording silently changed the rubric — and
    therefore the scores — for every other client on the platform.
    """
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Only an administrator can edit questions")
    cid = _company_for(current_user, company_id)
    ok = await svc.update_question(question_id, payload.model_dump(exclude_none=True),
                                   company_id=cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"ok": True}


@router.put("/questions/weightages")
async def put_weightages(payload: WeightageUpdate,
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """Set a level's weightage column. Rejected unless it totals exactly 100."""
    if not (_is_staff(current_user) or _is_hr(current_user) or _is_md(current_user)):
        # "All parameters should have weightages to create scoring - HR and MD."
        raise HTTPException(
            status_code=403,
            detail="Only HR, MD or an administrator can edit weightages.")
    cid = _company_for(current_user, company_id)
    try:
        return await svc.set_weightages(
            payload.level, {i.item_id: i.weightage for i in payload.weightages},
            company_id=cid)
    except ValueError as e:
        raise _bad(e)


@router.post("/questions/{level}/restore")
async def restore_questions(level: str, company_id: Optional[str] = Query(None),
                            current_user: dict = Depends(get_current_user)):
    """Re-insert any question from the HR document missing from a level. Insert-only —
    existing rows, their edited text and their weightages are left exactly as they are."""
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Only an administrator can restore questions")
    if str(level).upper() not in LEVELS:
        raise HTTPException(status_code=400, detail=f"level must be one of {', '.join(LEVELS)}")
    return await svc.restore_level_questions(level, company_id=_company_for(current_user, company_id))


# There is no review or sign-off endpoint. The seeded questions and options are the
# single source of truth and are used exactly as they stand — nothing asks HR, the MD or
# anyone else to confirm them, and nothing is held back pending an approval.
def _is_md(user: dict) -> bool:
    """The company's MD. `clientadmin` counts: it is the company's top-authority account
    and already maps to MD rank in auth_controller.client_rank, so the two routes into
    that authority behave the same here."""
    return _role(user) == "clientadmin" or (
        _role(user) == "clientuser" and _governance_role(user) == "md")


# ─────────────────────────────────────────────────────────────
# Cycles — the 2-month assessment window
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# WhatsApp — Leadership's own template, ledger and callbacks
# ─────────────────────────────────────────────────────────────
@router.get("/whatsapp-template")
async def read_wa_template(current_user: dict = Depends(get_current_user)):
    """THE WhatsApp invitation template — one template, every company.

    No company scope: the wording is the same for everyone, and every company-specific
    value in it (who is asking, who they are rating, their link) is a variable filled per
    invitation. The template is wording and a Meta template NAME — it carries no giver
    identity — so it sits behind the manage gate rather than the narrower panel one.
    """
    _require_template_manage(current_user)
    tpl = await ls_wa.get_template()
    tpl["can_edit"] = True
    return tpl


# ─────────────────────────────────────────────────────────────
# Meta delivery callbacks
#
# Meta calls this, so it CANNOT sit on `router` — that router carries a global
# get_current_user dependency and Meta has no session. It gets its own router with no
# dependencies, mounted alongside in main.py, and pays for that openness with a signature
# check on every request.
#
# Delivery state is no longer shown anywhere in the UI; this keeps writing to the ledger so
# a failed send still leaves a record with a reason, which is the only durable answer to
# "why did this person never get their link?".
# ─────────────────────────────────────────────────────────────
public_router = APIRouter(prefix="/leadership", tags=["Leadership Score"])


def _verify_meta_signature(raw: bytes, header: Optional[str]) -> None:
    """Reject anything not signed by Meta with our app secret.

    The HMAC is computed over the RAW request body — re-serialising the parsed JSON would
    change whitespace and key order and never match. Compared with `compare_digest` so the
    comparison cannot be timed to leak the expected value byte by byte.

    With no app secret configured this refuses everything rather than waving traffic
    through: an unauthenticated endpoint that writes to the ledger is worse than a webhook
    that is not wired up yet, because the failure is silent.
    """
    secret = (settings.WHATSAPP_APP_SECRET or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="WHATSAPP_APP_SECRET is not configured, so callbacks cannot be verified.")
    if not header or not header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")

    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header.split("=", 1)[1].strip()):
        raise HTTPException(status_code=401, detail="Signature does not match")


@public_router.get("/whatsapp-status")
async def verify_wa_webhook(request: Request):
    """Meta's one-time subscription handshake.

    Meta GETs the same URL it will later POST to and expects `hub.challenge` echoed back as
    PLAIN TEXT — a JSON-wrapped body fails verification, which is why this returns a
    PlainTextResponse rather than the usual dict.
    """
    params = request.query_params
    expected = (settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    if not expected:
        raise HTTPException(status_code=503,
                            detail="WHATSAPP_WEBHOOK_VERIFY_TOKEN is not configured.")
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == expected:
        return PlainTextResponse(params.get("hub.challenge") or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@public_router.post("/whatsapp-status")
async def record_wa_status(request: Request):
    """Meta delivery callbacks: sent / delivered / read / failed.

    Always answers 200 once the signature checks out, even for payloads it does nothing
    with. Meta retries anything non-2xx with escalating backoff and eventually disables the
    subscription, so a status we do not model must be accepted and ignored rather than
    rejected. Progress only ever moves forward — see leadership_wa_service.apply_status —
    because these callbacks arrive out of order.
    """
    raw = await request.body()
    _verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"))

    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not valid JSON")

    updated = seen = 0
    for entry in (payload.get("entry") or []):
        for change in (entry.get("changes") or []):
            for st in ((change.get("value") or {}).get("statuses") or []):
                seen += 1
                message_id = str(st.get("id") or "").strip()
                status = str(st.get("status") or "").strip().lower()
                if not message_id or not status:
                    continue
                errors = st.get("errors") or []
                reason = None
                if errors:
                    first = errors[0] or {}
                    reason = (first.get("title") or first.get("message")
                              or str(first.get("code") or "")) or None
                if await ls_wa.apply_status(message_id, status, reason):
                    updated += 1

    logger.info("Leadership WhatsApp webhook: %d status update(s) of %d applied", updated, seen)
    return {"received": seen, "updated": updated}


# ─────────────────────────────────────────────────────────────
# Template composer — check / save draft / test
#
# The SAME modal TPMS and Notifications use (components/whatsapp/TemplateComposer), which
# takes its four calls as a prop. Reusing the component means Leadership gets the live
# preview, the Meta validation rules and the payload review for free, while every record it
# writes lands in Leadership's own collection. What is shared is the composer and the Meta
# helpers; no TPMS template row is read or written.
# ─────────────────────────────────────────────────────────────
@router.post("/whatsapp-template/check")
async def check_wa_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Check the message against Meta's rules, without saving or sending anything.

    Meta's review takes hours and a rejection has to be read, corrected and resubmitted, so
    the rules it will apply are worth applying here first.
    """
    _require_template_manage(current_user)
    from app.services.meta_whatsapp_service import validate_template

    body, variables = payload.get("body"), payload.get("variables")
    doc = ls_wa.authored_doc(payload.get("name"), payload.get("language"), body, variables,
                             payload.get("category"))
    # Ours first — an unfillable variable is a clearer complaint than whatever Meta's rules
    # make of the same template.
    errors = ls_wa.validate_variables(body, variables) + validate_template(doc)
    return {"valid": not errors, "errors": errors}


@router.post("/whatsapp-template/draft")
async def save_wa_draft(payload: dict, current_user: dict = Depends(get_current_user)):
    """Save the invitation message as a DRAFT.

    One template for the whole application, so this upserts the single row rather than
    creating any. Category, variable style, header, footer and buttons are all fixed by
    `authored_doc` — a feedback invitation has one shape, and offering those choices would
    be asking questions with only one right answer.

    Saving returns it to DRAFT for EVERY company at once, which is the cost of one shared
    template: nothing sends again until Meta re-approves it.
    """
    _require_template_manage(current_user)
    from app.services.meta_whatsapp_service import validate_template

    body, variables = payload.get("body"), payload.get("variables")
    doc = ls_wa.authored_doc(payload.get("name"), payload.get("language"), body, variables,
                             payload.get("category"))

    # Refused while it can still be fixed. Meta would reject it on review anyway, hours
    # later, with a reason that has to be gone and looked up — and it cannot catch a
    # variable nothing fills, because to Meta that is just a parameter.
    errors = ls_wa.validate_variables(body, variables) + validate_template(doc)
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))

    try:
        return await ls_wa.save_authored_template(doc, current_user)
    except ValueError as e:
        # A name already taken on the WhatsApp Business Account. Recoverable, and the
        # message says how.
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/whatsapp-template/test")
async def test_wa_template(payload: dict, current_user: dict = Depends(get_current_user)):
    """Send the template to one number so it can be read on a real handset.

    Two modes, because WhatsApp allows exactly two things: an APPROVED template goes as the
    real thing, and anything else goes as free-form text — which Meta only delivers if that
    number messaged this business in the last 24 hours. The response says which happened.
    """
    _require_template_manage(current_user)
    from app.services.meta_whatsapp_service import (
        build_sample_send_components, render_preview_text,
    )
    from app.services.notification_service import (
        _normalize_wa_phone, send_whatsapp_notification, send_whatsapp_template,
    )

    phone = _normalize_wa_phone(str(payload.get("phone") or "").strip())
    if not phone:
        raise HTTPException(status_code=400, detail="Enter a valid phone number.")

    doc = ls_wa.authored_doc(payload.get("name"), payload.get("language"),
                             payload.get("body"), payload.get("variables"),
                             payload.get("category"))
    status = str(payload.get("status") or "DRAFT").upper()

    if status == "APPROVED":
        components, _ = build_sample_send_components(doc)
        ok = await send_whatsapp_template(
            phone, doc["name"], doc.get("language") or "en", [],
            None, "leadership_template_test", components)
        return {"ok": bool(ok), "mode": "template",
                "message": ("Sent as the approved template — exactly what recipients receive."
                            if ok else "Meta refused the send. Check the number and the template.")}

    ok = await send_whatsapp_notification(
        phone, render_preview_text(doc), None, "leadership_template_test")
    return {"ok": bool(ok), "mode": "freeform",
            "message": ("Sent as a free-form message, because the template is not approved yet. "
                        "It only arrives if that number messaged this business in the last 24 "
                        "hours." if ok else
                        "Not delivered. An unapproved template can only go as free-form text, "
                        "which needs that number to have messaged this business in the last 24 "
                        "hours.")}


@router.post("/whatsapp-template/submit")
async def submit_wa_template(current_user: dict = Depends(get_current_user)):
    """Send the shared invitation template to Meta for review.

    It enters PENDING and Meta usually answers within minutes to hours. Nothing polls for
    the verdict — the screen's Refresh calls the sync below, which is why approval appears
    when somebody looks rather than on a timer.
    """
    _require_template_manage(current_user)
    try:
        tpl = await ls_wa.submit_template(current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tpl["can_edit"] = True
    tpl["message"] = ("Submitted to Meta. It is PENDING review — refresh to pick up the "
                      "verdict.")
    return tpl


@router.get("/whatsapp-log")
async def read_wa_log(company_id: Optional[str] = Query(None),
                      limit: int = Query(60, ge=1, le=200),
                      current_user: dict = Depends(get_current_user)):
    """Recent WhatsApp send attempts, without panel identity.

    The template is shared but a send is not, so this is still the one company-scoped thing
    on the screen. Staff who name no company see every company's attempts — with the picker
    gone there is nothing for them to name, and one shared template makes "did it send
    anywhere?" the question actually being asked. A client user is pinned to their own.

    Same gate as the rest of this screen — administrators, not HR. The rows carry no giver
    or leader name and only a masked number, so an administrator can see WHY a send failed
    without learning who was asked to rate whom.
    """
    _require_template_manage(current_user)
    return await ls_wa.company_log(_company_scope(current_user, company_id), limit)


@router.post("/whatsapp-template/sync")
async def sync_wa_template(current_user: dict = Depends(get_current_user)):
    """Ask Meta where the shared template stands and mirror the verdict locally.

    Safe to repeat, and safe when Meta is unreachable: an unanswered call leaves the stored
    status alone rather than reading as "your approved template disappeared".
    """
    _require_template_manage(current_user)
    tpl = await ls_wa.sync_template_status()
    tpl["can_edit"] = True
    return tpl


# ─────────────────────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────────────────────
@router.post("/documents")
async def upload_document(file: UploadFile = File(...),
                          cycle: Optional[str] = Query(None),
                          note: Optional[str] = Query(None),
                          company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    """Attach a file to the module, optionally against one cycle.

    Same S3 path every other upload in the project uses, so storage, signing and retention
    behave identically. `cycle` is optional: a rubric or a policy belongs to the module,
    while a signed-off score sheet belongs to one cycle.
    """
    from app.services.s3_service import upload_file_to_s3_with_key

    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        uploaded = upload_file_to_s3_with_key(file.file, file.filename, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not store that file: {e}")

    doc = {
        "company_id": cid,
        "cycle": str(cycle) if cycle else None,
        "name": file.filename,
        "content_type": file.content_type,
        "size": getattr(file, "size", None),
        "key": uploaded["key"],
        "url": uploaded["url"],
        "note": (note or "").strip(),
        "uploaded_by": _display_name(current_user),
        "uploaded_by_id": _self_id(current_user),
        "uploaded_at": datetime.utcnow(),
    }
    res = await get_collection(COLL_LS_DOCUMENTS).insert_one(doc)
    return {**{k: v for k, v in doc.items() if k != "_id"}, "id": str(res.inserted_id)}


@router.get("/documents")
async def list_documents(cycle: Optional[str] = Query(None),
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """This company's documents, newest first. `cycle` narrows to one cycle's own files."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    query = {"company_id": cid}
    if cycle:
        query["cycle"] = str(cycle)
    rows = await get_collection(COLL_LS_DOCUMENTS).find(query).sort("uploaded_at", -1).to_list(500)
    return {"company_id": cid, "documents": [{
        "id": str(r["_id"]),
        "cycle": r.get("cycle"),
        "name": r.get("name"),
        "content_type": r.get("content_type"),
        "size": r.get("size"),
        "url": r.get("url"),
        "note": r.get("note"),
        "uploaded_by": r.get("uploaded_by"),
        "uploaded_at": r.get("uploaded_at"),
    } for r in rows]}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str,
                          company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    """Remove a document, from S3 as well as from the index.

    The company filter is part of the query rather than a check afterwards, so a document
    id from another company simply matches nothing instead of being deleted.
    """
    from app.services.s3_service import delete_file_from_s3

    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        oid = ObjectId(str(document_id))
    except Exception:
        raise HTTPException(status_code=404, detail="No such document")

    doc = await get_collection(COLL_LS_DOCUMENTS).find_one({"_id": oid, "company_id": cid})
    if not doc:
        raise HTTPException(status_code=404, detail="No such document")
    try:
        delete_file_from_s3(doc.get("key"))
    except Exception as e:                                        # pragma: no cover
        # The index row still goes: a file left in the bucket is tidier than a listed
        # document that cannot be opened.
        logger.warning("Leadership document %s left in S3: %s", document_id, e)
    await get_collection(COLL_LS_DOCUMENTS).delete_one({"_id": oid})
    return {"deleted": 1, "name": doc.get("name")}


@router.get("/cycles")
async def list_cycles(company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    cid = _company_for(current_user, company_id)
    return {"company_id": cid, "cycles": await svc.list_cycles(cid)}


@router.post("/cycles")
async def create_cycle(payload: CycleCreate, company_id: Optional[str] = Query(None),
                       current_user: dict = Depends(get_current_user)):
    _require_manage(current_user)
    cid = _company_for(current_user, company_id or payload.company_id)
    try:
        return await svc.create_cycle(cid, payload, current_user)
    except ValueError as e:
        raise _bad(e)


@router.patch("/cycles/{cycle}")
async def patch_cycle(cycle: str, payload: CycleUpdate,
                      company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    """Edit a cycle. Setting status to `closed` freezes its scores into history."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        return await svc.update_cycle(cid, cycle, payload.model_dump(exclude_none=True), current_user)
    except ValueError as e:
        raise _bad(e)


@router.delete("/cycles/{cycle}")
async def delete_cycle(cycle: str, company_id: Optional[str] = Query(None),
                       current_user: dict = Depends(get_current_user)):
    """Delete a cycle opened by mistake, with everything scaffolded under it.

    Refused once ANY feedback has been submitted — responses are anonymous and cannot be
    collected again — and refused for a published cycle, whose scores leaders have already
    been told about. Both refusals come back as 400 with the reason.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        result = await svc.delete_cycle(cid, cycle)
    except ValueError as e:
        raise _bad(e)
    # Audited like every other cycle transition: a deletion is the one action that leaves
    # nothing behind to inspect afterwards, so the trail is the only record it happened.
    await svc.audit(current_user, "cycle.delete",
                    f"Deleted {result['label']} and everything set up under it",
                    company_id=cid, cycle=cycle, removed=result["removed"])
    return result


# ─────────────────────────────────────────────────────────────
# Subjects — the leaders being rated
# ─────────────────────────────────────────────────────────────
@router.get("/people")
async def list_people(company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    """The company roster HR picks leaders and feedback givers from."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return {"people": await svc.list_company_people(cid)}


@router.get("/subjects")
async def list_subjects(cycle: str = Query(...),
                        company_id: Optional[str] = Query(None),
                        current_user: dict = Depends(get_current_user)):
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return {"cycle": cycle, "cycle_label": cycle_label(cycle),
            "subjects": await svc.list_subjects(cid, cycle)}


@router.post("/subjects")
async def add_subject(payload: SubjectCreate, cycle: str = Query(...),
                      company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    """Enrol a leader (L4 and above) into a cycle at their level."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        return await svc.add_subject(cid, cycle, payload.subject_id, payload.level, current_user)
    except ValueError as e:
        raise _bad(e)


@router.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: str, cycle: str = Query(...),
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        return await svc.remove_subject(cid, cycle, subject_id)
    except ValueError as e:
        raise _bad(e)


# ─────────────────────────────────────────────────────────────
# Feedback givers — HR only. This is the confidentiality boundary.
# ─────────────────────────────────────────────────────────────
@router.get("/subjects/{subject_id}/panel")
async def read_panel(subject_id: str, cycle: str = Query(...),
                     company_id: Optional[str] = Query(None),
                     current_user: dict = Depends(get_current_user)):
    """The feedback panel for one leader, with delivery status per member.

    HR/staff ONLY — this is the one place giver identity is exposed. It is never reachable
    by the leader being rated, by their reporting manager, or by the client admin.
    """
    _require_panel(current_user)
    cid = _company_for(current_user, company_id)
    rows = await links.assignments_for_subject(cid, cycle, subject_id)
    # Audited, always. Panel access is the one thing that can undo "ye feedback completely
    # confidential hoga" from the inside, so every read leaves a record of who looked.
    await svc.audit(current_user, "panel.read",
                    f"Viewed the feedback panel for subject {subject_id} in {cycle}",
                    company_id=cid, cycle=cycle, subject_id=subject_id,
                    panel_size=len(rows))
    return {
        "cycle": cycle,
        "subject_id": subject_id,
        "panel": await links.panel_rows(rows),
        # For THIS leader's degree, not the 360° figure — a 180° panel is complete at four.
        "recommended_panel_size": panel_size_for(
            svc.effective_degree(await svc.get_cycle(cid, cycle) or {},
                                 await svc.get_subject(cid, cycle, subject_id) or {})),
    }


@router.put("/subjects/{subject_id}/panel")
async def set_panel(subject_id: str, payload: GiverAssignment, cycle: str = Query(...),
                    company_id: Optional[str] = Query(None),
                    current_user: dict = Depends(get_current_user)):
    """Set the 8 feedback givers and mint each of them a unique link.

    HR/staff ONLY — choosing the panel IS identifying the givers.

    Members already holding a link keep it. Members dropped from the list lose an
    unsubmitted link; anything already submitted is never removed.
    """
    _require_panel(current_user)
    cid = _company_for(current_user, company_id)
    try:
        result = await svc.set_panel(cid, cycle, subject_id, payload.givers, current_user)
    except ValueError as e:
        raise _bad(e)
    await svc.audit(current_user, "panel.set",
                    f"Set the feedback panel for subject {subject_id} in {cycle}",
                    company_id=cid, cycle=cycle, subject_id=subject_id,
                    panel_size=result.get("panel_size"))
    return result


@router.post("/cycles/{cycle}/dispatch")
async def dispatch(cycle: str, subject_id: Optional[str] = Query(None),
                   company_id: Optional[str] = Query(None),
                   current_user: dict = Depends(get_current_user)):
    """Email every pending link for the cycle (or for one leader). Already-submitted
    givers are skipped, so a re-dispatch never nags someone who is done, and anyone mailed
    within the resend cooldown is held back so repeated clicks cannot duplicate mail.

    HR/staff ONLY — dispatch acts directly on the panel, and its result reports how many
    givers are still outstanding, which is panel information.

    Refused outright for a closed or elapsed cycle: 409, enforced here rather than in the
    UI so a stale tab or a direct API call cannot send invitations to a finished cycle.
    """
    _require_panel(current_user)
    cid = _company_for(current_user, company_id)
    try:
        await svc.assert_dispatchable(cid, cycle)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # The panel composition the document specifies — 2 per relation for the degree being
    # collected — is enforced HERE rather than when the panel is saved, so HR can still
    # build a panel over several sittings. It is the mail going out that turns an incomplete
    # panel into a real problem: once a giver has been invited, the score that follows is
    # labelled 360° whatever it was actually built from.
    if subject_id:
        missing = await svc.panel_shortfall(cid, cycle, subject_id)
        if missing:
            raise HTTPException(
                status_code=409,
                detail=("This panel is not complete yet — it still needs "
                        f"{svc.describe_shortfall(missing)}. The document asks for 2 givers per "
                        "relation so no single person's rating decides the score."))
        return await links.dispatch_pending(cid, cycle, subject_id)

    # Cycle-wide: mail the leaders who ARE ready and name the ones who are not. Refusing the
    # whole batch because one panel of eight is unfinished would punish the other seven.
    blocked = await svc.incomplete_panels(cid, cycle)
    result = await links.dispatch_pending(cid, cycle, skip_subjects=list(blocked.keys()))
    if blocked:
        result["skipped_incomplete"] = [
            {"subject_id": sid, "subject_name": info["subject_name"], "needs": info["summary"]}
            for sid, info in blocked.items()
        ]
        result["skipped_incomplete_count"] = len(blocked)
    return result


@router.post("/assignments/{assignment_id}/resend")
async def resend(assignment_id: str, current_user: dict = Depends(get_current_user)):
    """Re-email one giver their existing link. HR/staff ONLY — it names a giver."""
    _require_panel(current_user)
    from bson import ObjectId
    from bson.errors import InvalidId
    from app.db.mongodb import get_collection
    from app.models.leadership import COLL_LS_ASSIGNMENTS
    try:
        doc = await get_collection(COLL_LS_ASSIGNMENTS).find_one({"_id": ObjectId(assignment_id)})
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id")
    if not doc:
        raise HTTPException(status_code=404, detail="Link not found")
    if _is_client(current_user) and str(doc.get("company_id")) != str(current_user.get("company_id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    # A closed or elapsed cycle refuses here too — a resent link would 410 on click.
    try:
        await svc.assert_dispatchable(str(doc.get("company_id")), str(doc.get("cycle")))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # A FIRST invitation must respect the panel rule, exactly as dispatch does.
    #
    # `sent_at` is written only on a real delivery, so its absence means this giver has
    # never actually been invited — sending now is a first invitation wearing a resend
    # button, and it was the one route that could invite an incomplete panel one person
    # at a time. Dispatch refuses that (409) precisely because the score that follows is
    # labelled 360° whatever it was really built from.
    #
    # A giver who HAS been delivered to keeps the escape hatch unconditionally: chasing
    # someone already invited must never be blocked by a panel that changed afterwards,
    # or a non-submitter could be stranded with no way to reach them.
    if not doc.get("sent_at"):
        missing = await svc.panel_shortfall(
            str(doc.get("company_id")), str(doc.get("cycle")), str(doc.get("subject_id")))
        if missing:
            raise HTTPException(
                status_code=409,
                detail=("This panel is not complete yet — it still needs "
                        f"{svc.describe_shortfall(missing)}. The document asks for 2 givers "
                        "per relation so no single person's rating decides the score."))

    # Deliberately NOT cooldown-checked: this is a single, explicit, per-person action —
    # the escape hatch that keeps "resend if needed" available while the bulk button waits.
    result = await links.send_assignment_whatsapp(doc)
    if not result.get("ok"):
        # 422 for a missing number: that is a fixable data problem on the person's record,
        # not a server fault, and telling the two apart is what stops HR retrying forever
        # against a row that can never send.
        code = 422 if result.get("status") == "unreachable" else 502
        raise HTTPException(status_code=code, detail=result.get("error") or "Send failed")
    return result


@router.get("/assignments")
async def list_assignments(cycle: Optional[str] = Query(None),
                           company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    """Leadership form-link log. HR/staff only — every row carries giver identity."""
    _require_panel(current_user)
    cid = _company_for(current_user, company_id)
    from app.db.mongodb import get_collection
    from app.models.leadership import COLL_LS_ASSIGNMENTS
    query: dict = {"company_id": cid}
    if cycle:
        query["cycle"] = cycle
    docs = await get_collection(COLL_LS_ASSIGNMENTS).find(query).sort("created_at", -1).to_list(2000)
    # The log spans cycles, so their windows are resolved in one query rather than one per
    # row — every Expired here means the same thing it means on the panel.
    cycles = await links.cycles_for(docs)
    return {"assignments": [{
        **links.panel_row(d, None, cycles.get(links.cycle_key(d))),
        "cycle": d.get("cycle"),
        "cycle_label": cycle_label(d.get("cycle") or ""),
        "subject_id": d.get("subject_id"),
        "subject_name": d.get("subject_name"),
        "subject_level": d.get("subject_level"),
    } for d in docs]}


# ─────────────────────────────────────────────────────────────
# The giver's form — opened by token at /lf/<token>
#
# Two independent checks must both pass, exactly as the existing assigned-form route
# does it: the token must resolve to a live assignment, AND the signed-in user must BE
# that assignment's giver. A forwarded link is therefore useless to anyone else.
# ─────────────────────────────────────────────────────────────
async def _assignment_for(token: str, current_user: dict, *, must_be_open: bool) -> dict:
    doc = await links.resolve_token(token)
    if not doc:
        raise HTTPException(status_code=404, detail="This feedback link is not valid.")
    if str(doc.get("giver_id")) != _self_id(current_user):
        raise HTTPException(
            status_code=403,
            detail="This feedback form was assigned to a different user. Please sign in with "
                   "the account the link was sent to.")
    if must_be_open:
        # The cycle drives both tests, so a link cannot read as live while the window it
        # belongs to has shut. Fetched once and passed down rather than looked up twice.
        cyc = await svc.get_cycle(doc.get("company_id"), doc.get("cycle")) or {}
        state = links.effective_status(doc, None, cyc)
        if state == LINK_SUBMITTED:
            raise HTTPException(status_code=409, detail="This feedback has already been submitted.")
        if state == LINK_EXPIRED:
            raise HTTPException(status_code=410, detail="This feedback link has expired.")
        # Said separately from expiry because "not open yet" is not "too late" — a giver
        # who arrives early has to be told to come back, not that their link is dead.
        # Checked at submit as well as at read, so a page left open across the closing
        # moment cannot post through it.
        await _assert_window_open(doc, cyc)
    return doc


async def _assert_window_open(doc: dict, cyc: Optional[dict] = None) -> None:
    """Refuse a submission outside the cycle's configured Open/Close window.

    `pending` and `closed` get different codes and different words on purpose — "not yet"
    and "no longer" are opposite problems for the person holding the link, and one of them
    means come back later.
    """
    if cyc is None:
        cyc = await svc.get_cycle(doc.get("company_id"), doc.get("cycle")) or {}
    state = links.window_state(cyc)
    if state == links.WINDOW_OPEN:
        return
    opens, closes = links.survey_window(cyc)
    if state == links.WINDOW_PENDING:
        raise HTTPException(
            status_code=403,
            detail=("This feedback window has not opened yet"
                    + (f" — it opens on {opens.strftime('%d %b %Y, %H:%M UTC')}." if opens else ".")))
    raise HTTPException(
        status_code=410,
        detail=("This feedback window has closed"
                + (f" — it closed on {closes.strftime('%d %b %Y, %H:%M UTC')}." if closes else ".")))


@router.get("/assigned/{token}")
async def assigned_form(token: str, current_user: dict = Depends(get_current_user)):
    """The one feedback form this token was issued for. Marks it Opened on first view.

    Returns the subject's NAME and LEVEL only — never the rest of the panel, and never
    anyone else's answers.
    """
    doc = await _assignment_for(token, current_user, must_be_open=False)

    # The window is reported alongside the link's own status so the page can say "opens on
    # the 5th" rather than a bare refusal — and so a giver who arrives early knows to come
    # back rather than assuming their link is broken. It also DECIDES that status: a link
    # is expired when its cycle's window has shut, not when a stamp written on the day it
    # was created happens to have passed.
    cyc = await svc.get_cycle(doc.get("company_id"), doc.get("cycle")) or {}
    state = links.effective_status(doc, None, cyc)
    window = links.window_state(cyc)
    opens_at, closes_at = links.survey_window(cyc)

    head = {
        "state": state,
        "window": window,
        "window_opens_at": opens_at,
        "window_closes_at": closes_at,
        "cycle": doc.get("cycle"),
        "cycle_label": cycle_label(doc.get("cycle") or ""),
        "subject_name": doc.get("subject_name"),
        "subject_designation": doc.get("subject_designation"),
        "level": doc.get("subject_level"),
        "level_label": LEVEL_LABELS.get(doc.get("subject_level") or "", ""),
        "level_theme": LEVEL_THEMES.get(doc.get("subject_level") or "", ""),
        "company_name": doc.get("company_name"),
        "submitted_at": doc.get("submitted_at"),
        "expires_at": doc.get("expires_at"),
    }
    if state in (LINK_SUBMITTED, LINK_EXPIRED):
        return head
    # Outside the window there is nothing to fill in, so the questions are not sent and the
    # link is NOT marked opened — arriving early must not consume the "unopened" state HR
    # chases on.
    if window != links.WINDOW_OPEN:
        return {**head, "state": window}

    await links.mark_opened(doc)
    questions = await svc.get_questions(doc.get("subject_level"),
                                        company_id=doc.get("company_id"))
    return {
        **head,
        "state": "open",
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        # Weightage is deliberately NOT sent to the giver — it must not influence how
        # they answer.
        "questions": [{
            "item_id": q["item_id"],
            "title": q.get("title", ""),
            "prompt": q.get("prompt", ""),
            "options": [{"option_id": o["option_id"], "label": o.get("label", "")}
                        for o in (q.get("options") or [])],
        } for q in questions],
    }


@router.post("/assigned/{token}/submit")
async def submit_response(token: str, payload: ResponseSubmit,
                          current_user: dict = Depends(get_current_user)):
    """Record this giver's feedback and close their link.

    Deliberately does NOT call `tpms_notify_service.notify_form_submission` — that mails a
    per-employee scorecard, which would breach the anonymity this module guarantees.
    """
    doc = await _assignment_for(token, current_user, must_be_open=True)

    # Claim the invitation FIRST, atomically. This is what lets the response carry no
    # rater identity at all: uniqueness lives on the invitation, not on a `giver_id`
    # stamped into the answers. Two concurrent submits cannot both win the claim, so only
    # one response is ever written.
    if not await links.claim_for_submission(doc):
        raise HTTPException(status_code=409,
                            detail="This feedback has already been submitted.")
    try:
        result = await svc.record_response(doc, payload.answers)
    except ValueError as e:
        # Give the link back — the giver has to be able to correct and resubmit.
        await links.release_claim(doc)
        raise _bad(e)
    except Exception:
        await links.release_claim(doc)
        raise
    return {"ok": True, **result}


# ─────────────────────────────────────────────────────────────
# Results — aggregates only, never an identity
# ─────────────────────────────────────────────────────────────
async def _may_view_subject(user: dict, company_id: str, subject_id: str) -> bool:
    """Who may read one leader's score: HR/staff, that leader, and their reporting
    manager ('Their respective reporting Manager should discuss the score with each
    leader during RRO')."""
    if _can_manage(user):
        return True
    if _self_id(user) == str(subject_id):
        return True
    from app.db.mongodb import get_collection
    from app.models.leadership import COLL_LS_SUBJECTS
    row = await get_collection(COLL_LS_SUBJECTS).find_one(
        {"company_id": str(company_id), "subject_id": str(subject_id)})
    return bool(row and str(row.get("reporting_manager") or "") == _self_id(user))


@router.get("/scores")
async def read_scores(cycle: str = Query(...),
                      company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    """Leadership Scores for a cycle.

    HR/staff see every enrolled leader plus the relation breakdown. Anyone else sees only
    the leaders they are entitled to — themselves and their direct reports.
    """
    cid = _company_for(current_user, company_id)
    manage = _can_manage(current_user)
    # Anyone who is not running the module sees nothing until the cycle is PUBLISHED —
    # the leader being rated and their reporting manager alike. Without this a subject
    # could poll their own score during collection and difference it after each
    # submission, which recovers one named person's rating whatever the group
    # suppression does.
    result = await svc.cycle_scores(cid, cycle, include_relations=manage,
                                    for_leader=not manage)

    if not manage:
        allowed = []
        for row in result["rows"]:
            if await _may_view_subject(current_user, cid, row["subject_id"]):
                allowed.append(row)
        scored = [r for r in allowed if r.get("leadership_score") is not None]
        result["rows"] = allowed
        result["summary"] = {
            "leaders": len(allowed),
            "scored": len(scored),
            "average_score": round(sum(r["leadership_score"] for r in scored) / len(scored), 2)
            if scored else None,
            "highest": max((r["leadership_score"] for r in scored), default=None),
            "lowest": min((r["leadership_score"] for r in scored), default=None),
        }
    return result


@router.get("/scores/{subject_id}")
async def read_subject_score(subject_id: str, cycle: str = Query(...),
                             company_id: Optional[str] = Query(None),
                             current_user: dict = Depends(get_current_user)):
    """One leader's parameter-wise result — the RRO discussion view.

    The payload is built by `subject_score()` and contains no giver id, no giver name and
    no individual response. The relation breakdown is added for HR/staff only.
    """
    cid = _company_for(current_user, company_id)
    if not await _may_view_subject(current_user, cid, subject_id):
        raise HTTPException(status_code=403, detail="You are not authorized to view this score")
    manage = _can_manage(current_user)
    try:
        score = await svc.subject_score(cid, cycle, subject_id,
                                        include_relations=manage,
                                        for_leader=not manage)
    except ValueError as e:
        raise _bad(e)
    # The trend is gated the same way, or the current cycle's number would arrive through
    # the history while the score itself was still withheld.
    return {**score,
            "history": await svc.subject_history(cid, subject_id,
                                                 published_only=not manage)}


@router.get("/my-feedback")
async def my_feedback(current_user: dict = Depends(get_current_user)):
    """The feedback forms this user still owes — their own pending links.

    Scoped strictly to the caller, so it reveals nothing about anyone else's panel.
    """
    from app.db.mongodb import get_collection
    from app.models.leadership import COLL_LS_ASSIGNMENTS
    rows = await get_collection(COLL_LS_ASSIGNMENTS).find(
        {"giver_id": _self_id(current_user)}).sort("created_at", -1).to_list(200)
    cycles = await links.cycles_for(rows)
    return {"forms": [{
        "cycle": r.get("cycle"),
        "cycle_label": cycle_label(r.get("cycle") or ""),
        "subject_name": r.get("subject_name"),
        "level_label": LEVEL_LABELS.get(r.get("subject_level") or "", ""),
        "status": links.effective_status(r, None, cycles.get(links.cycle_key(r))),
        "link": r.get("link"),
        # The date the giver is actually held to: HR's Close date when there is one, the
        # cycle's own closing month when there is not. Reporting the stored stamp here
        # would print a deadline the form does not enforce.
        "expires_at": (links.survey_window(cycles.get(links.cycle_key(r)))[1]
                       if cycles.get(links.cycle_key(r)) else r.get("expires_at")),
    } for r in rows]}


# ─────────────────────────────────────────────────────────────
# Eligibility — "Applicable from L4 (Asst Managers) and above"
# ─────────────────────────────────────────────────────────────
@router.get("/eligible")
async def list_eligible(company_id: Optional[str] = Query(None),
                        current_user: dict = Depends(get_current_user)):
    """Who can be enrolled, and who is missing a Leadership level.

    `unlevelled` is the half that matters: people who look senior by designation but carry
    no `leadership_level`. Listing them is what stops a leader being silently left out of
    a cycle — the level is never guessed from the free-text designation.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return await svc.list_eligible_people(cid)


# ─────────────────────────────────────────────────────────────
# Close → compute → publish
# ─────────────────────────────────────────────────────────────
@router.get("/cycles/{cycle}/quorum")
async def read_quorum(cycle: str, company_id: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    """Who is short of quorum, so HR can extend the window instead of publishing a thin
    score. Counts only — never which raters replied."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return await svc.quorum_report(cid, cycle)


@router.post("/cycles/{cycle}/compute")
async def compute_cycle(cycle: str, company_id: Optional[str] = Query(None),
                        current_user: dict = Depends(get_current_user)):
    """Freeze this cycle's scores. Nothing gates this but the cycle's own state machine —
    the rubric is used exactly as seeded and needs no approval."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        result = await svc.update_cycle(cid, cycle, {"status": "computed"}, current_user)
    except ValueError as e:
        raise _bad(e)
    await svc.audit(current_user, "cycle.compute", f"Computed and froze scores for {cycle}",
                    company_id=cid, cycle=cycle)
    return result


@router.post("/cycles/{cycle}/publish")
async def publish_cycle(cycle: str, company_id: Optional[str] = Query(None),
                        current_user: dict = Depends(get_current_user)):
    """Release the scores to leaders and their reporting managers.

    Until this runs, a leader sees nothing at all. Without the step they could watch their
    own number move during collection and difference it after each submission, which
    recovers one named person's rating however the group breakdown is suppressed.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        result = await svc.update_cycle(cid, cycle, {"status": "published"}, current_user)
    except ValueError as e:
        raise _bad(e)
    await svc.audit(current_user, "cycle.publish", f"Published {cycle} to leaders",
                    company_id=cid, cycle=cycle)
    try:
        from app.services import leadership_notify_service as notify
        await notify.notify_published(cid, cycle)
    except Exception as e:                                       # pragma: no cover
        # A notification failure must not leave the cycle half-published.
        import logging
        logging.getLogger(__name__).warning("Leadership publish notice failed: %s", e)
    return result


# ─────────────────────────────────────────────────────────────
# RRO discussion and action plan
# ─────────────────────────────────────────────────────────────
@router.get("/subjects/{subject_id}/discussion")
async def read_discussion(subject_id: str, cycle: str = Query(...),
                          company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    """The RRO record for one leader. Visible to HR, the leader, and their manager."""
    cid = _company_for(current_user, company_id)
    if not await _may_view_subject(current_user, cid, subject_id):
        raise HTTPException(status_code=403, detail="You are not authorized to view this")
    return await svc.get_discussion(cid, cycle, subject_id) or {}


@router.post("/subjects/{subject_id}/discussion")
async def log_discussion(subject_id: str, payload: DiscussionCreate,
                         cycle: str = Query(...),
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """Log the RRO conversation and the action plan that came out of it.

    "Their respective reporting Manager should discuss the score with each leader during
    RRO" — so the reporting manager, or HR. Not the leader themselves.
    """
    cid = _company_for(current_user, company_id)
    if not await _may_view_subject(current_user, cid, subject_id):
        raise HTTPException(status_code=403, detail="You are not authorized to do this")
    if _self_id(current_user) == str(subject_id) and not _can_manage(current_user):
        raise HTTPException(
            status_code=403,
            detail="Your reporting manager logs this discussion, not you. You can "
                   "acknowledge it once it is recorded.")
    try:
        return await svc.log_discussion(cid, cycle, subject_id, payload, current_user)
    except ValueError as e:
        raise _bad(e)


@router.patch("/subjects/{subject_id}/discussion/acknowledge")
async def acknowledge_discussion(subject_id: str, payload: DiscussionAck,
                                 cycle: str = Query(...),
                                 company_id: Optional[str] = Query(None),
                                 current_user: dict = Depends(get_current_user)):
    """The leader confirming the conversation happened. Only they can do this."""
    cid = _company_for(current_user, company_id)
    try:
        return await svc.acknowledge_discussion(cid, cycle, subject_id, current_user,
                                                payload.comment or "")
    except ValueError as e:
        raise _bad(e)


@router.get("/cycles/{cycle}/discussions/pending")
async def pending_discussions(cycle: str, company_id: Optional[str] = Query(None),
                              current_user: dict = Depends(get_current_user)):
    """Leaders whose RRO conversation has not been logged yet."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return {"pending": await svc.pending_discussions(cid, cycle)}


# ─────────────────────────────────────────────────────────────
# Briefing tracker
# ─────────────────────────────────────────────────────────────
@router.get("/cycles/{cycle}/briefings")
async def read_briefings(cycle: str, company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """Who has been briefed, and who is still outstanding."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return await svc.briefing_status(cid, cycle)


@router.post("/cycles/{cycle}/briefings")
async def record_briefing(cycle: str, payload: BriefingCreate,
                          company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    """Record that one person has had their briefing."""
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        return await svc.record_briefing(cid, cycle, payload.user_id, payload.type,
                                         payload.conducted_by or "", current_user,
                                         payload.notes or "")
    except ValueError as e:
        raise _bad(e)


# ─────────────────────────────────────────────────────────────
# Organisation roll-up
# ─────────────────────────────────────────────────────────────
@router.get("/dashboard")
async def read_dashboard(cycle: Optional[str] = Query(None),
                         company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    """Distribution, by level and by department — the MD's view.

    Built from frozen scores only, so it can never disagree with the cards leaders were
    shown, and carries no rater information of any kind.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    return await svc.dashboard(cid, cycle)


@router.patch("/subjects/{subject_id}/mode")
async def set_subject_mode(subject_id: str, payload: SubjectMode,
                           cycle: str = Query(...),
                           company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    """Put one leader on a different degree from the rest of their cycle.

    A leader with no direct reports cannot be a 360° subject; without this their panel can
    never be completed and they are held out of every dispatch with nothing to explain it.
    """
    _require_manage(current_user)
    cid = _company_for(current_user, company_id)
    try:
        return await svc.set_subject_mode(cid, cycle, subject_id, payload.mode_override)
    except ValueError as e:
        raise _bad(e)
