"""Assistant API routes (Phase 4 — production hardening).

Endpoints:
  GET  /assistant/health                   liveness (no dependencies)
  GET  /assistant/ready                    readiness (DB + key + flags)
  GET  /assistant/metrics                  operational metrics (admin only)
  POST /assistant/ask                      JSON or SSE stream
  GET  /assistant/conversations            list (owner-scoped)
  GET  /assistant/conversations/{id}       history (owner-scoped)
  DELETE /assistant/conversations/{id}     delete (owner-scoped)

Cross-cutting: correlation IDs, feature-flag gating, per-user rate limiting.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
    Request, Response, UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse

from app.assistant import flags, ratelimit
from app.assistant.caching import cache
from app.assistant.config import config
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.dependencies import get_user_context
from app.assistant.export import build_conversation_pdf, ist_now
from app.assistant.files import attachment_store, service as attachment_service
from app.assistant.files.service import ValidationError
from app.assistant.files.storage import LocalStorage
from app.assistant.memory import conversation_store
from app.assistant.observability import correlation
from app.assistant.observability.metrics import metrics
from app.assistant.schemas.chat import AskRequest, ExportPdfRequest
from app.assistant.schemas.context import UserContext
from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role
from app.assistant.utils.exceptions import AssistantError
from app.config.settings import settings
from app.db.mongodb import db_connection

router = APIRouter(prefix="/assistant", tags=["assistant"])

_orchestrator = Orchestrator()


# ── Operational ───────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    """Liveness — cheap, no dependencies."""
    return {"status": "ok", "enabled": config.ENABLED, "phase": "4"}


@router.get("/ready")
async def ready():
    """Readiness — checks dependencies needed to actually serve requests."""
    db_ok = db_connection.db is not None
    key_ok = bool(settings.OPENAI_API_KEY)
    ok = db_ok and key_ok and config.ENABLED
    payload = {
        "ready": ok,
        "checks": {"database": db_ok, "openai_key": key_ok, "enabled": config.ENABLED},
        "flags": flags.snapshot(),
    }
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/metrics")
async def get_metrics(ctx: UserContext = Depends(get_user_context)):
    """Operational metrics — staff/admin only."""
    if normalize_role(ctx.role) not in (ROLE_SA, ROLE_AD):
        raise HTTPException(status_code=403, detail="Not authorized")
    return {
        "metrics": metrics.snapshot(),
        "caches": {
            "metadata": cache.metadata_cache.stats(),
            "analytics": cache.analytics_cache.stats(),
            "knowledge": cache.knowledge_cache.stats(),
        },
        "flags": flags.snapshot(),
    }


# ── Chat ──────────────────────────────────────────────────────────────────
@router.post("/ask", response_model=None)
async def ask(req: AskRequest, request: Request, response: Response,
              ctx: UserContext = Depends(get_user_context)):
    cid = correlation.begin_request(request.headers.get("X-Request-ID"))

    enabled, reason = flags.is_enabled_for(ctx)
    if not enabled:
        raise HTTPException(status_code=403, detail=f"Assistant not available: {reason}")

    if config.RATE_LIMIT_ENABLED:
        allowed, retry_after = ratelimit.limiter.check(ctx.user_id)
        if not allowed:
            metrics.rate_limited += 1
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(retry_after), "X-Request-ID": cid},
            )

    if req.stream and config.STREAMING_ENABLED:
        return StreamingResponse(
            _orchestrator.stream_message(
                ctx, req.message, req.conversation_id,
                edit_from_index=req.edit_from_index, attachment_ids=req.attachment_ids,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": cid},
        )

    response.headers["X-Request-ID"] = cid
    try:
        return await _orchestrator.handle_message(
            ctx, req.message, req.conversation_id,
            edit_from_index=req.edit_from_index, attachment_ids=req.attachment_ids,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Conversation management (owner-scoped) ─────────────────────────────────
@router.get("/conversations")
async def list_conversations(ctx: UserContext = Depends(get_user_context)):
    items = await conversation_store.list_for_user(ctx)
    return {"conversations": [i.model_dump() for i in items]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        convo = await conversation_store.load_or_create(ctx, conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return convo.model_dump()


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        await conversation_store.delete_conversation(ctx, conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.post("/conversations/{conversation_id}/export-pdf")
async def export_conversation_pdf(
    conversation_id: str,
    payload: Optional[ExportPdfRequest] = None,
    ctx: UserContext = Depends(get_user_context),
):
    """Render the (owner-scoped) conversation to a downloadable PDF.

    Returns a `application/pdf` body with a Content-Disposition attachment so the
    browser saves it as `chat-conversation-YYYY-MM-DD.pdf`. The PDF is built from
    the conversation as-is; the export request/response turn is then persisted
    (tagged `export_kind="pdf"`) so it survives a page reload. The core chat flow
    is untouched.
    """
    try:
        convo = await conversation_store.load_or_create(ctx, conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        pdf_bytes = build_conversation_pdf(convo)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not generate the PDF.")

    # Persist the export turn (best-effort — a logging failure must not block the
    # download the user is waiting on).
    try:
        user_msg = (payload.user_message if payload else None) or "Export this chat as PDF"
        await conversation_store.append_export_turn(
            convo,
            user_msg=user_msg.strip(),
            assistant_msg="Here's your conversation exported as a PDF.",
            export_kind="pdf",
        )
    except Exception:
        pass

    filename = f"chat-conversation-{ist_now():%Y-%m-%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ── Multi-modal attachments (owner-scoped) ─────────────────────────────────
def _ensure_attachments_enabled() -> None:
    if not config.ATTACHMENTS_ENABLED:
        raise HTTPException(status_code=403, detail="File uploads are disabled")


@router.post("/attachments")
async def upload_attachment(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    ctx: UserContext = Depends(get_user_context),
):
    """Upload a single file. Returns immediately with status=processing; poll
    GET /assistant/attachments/{id} until status=completed."""
    _ensure_attachments_enabled()
    try:
        out = await attachment_service.save_and_dispatch(ctx, file, conversation_id, background_tasks)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return out.model_dump()


@router.post("/attachments/batch")
async def upload_attachments(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    conversation_id: Optional[str] = Form(None),
    ctx: UserContext = Depends(get_user_context),
):
    """Upload multiple files in one request (per-message multi-upload)."""
    _ensure_attachments_enabled()
    if len(files) > config.MAX_FILES_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Up to {config.MAX_FILES_PER_MESSAGE} files per message.",
        )
    results, errors = [], []
    for f in files:
        try:
            out = await attachment_service.save_and_dispatch(ctx, f, conversation_id, background_tasks)
            results.append(out.model_dump())
        except ValidationError as exc:
            errors.append({"filename": f.filename, "error": str(exc)})
    return {"attachments": results, "errors": errors}


@router.get("/attachments/{attachment_id}")
async def get_attachment(attachment_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        doc = await attachment_store.get_for_user(ctx, attachment_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    out = await attachment_service.to_out(ctx, doc)
    return out.model_dump()


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        doc = await attachment_store.delete_for_user(ctx, attachment_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    # Best-effort purge of the stored file.
    ref = doc.get("storage_ref")
    if ref:
        try:
            from app.assistant.files.storage import get_storage
            await get_storage().delete(ref)
        except Exception:
            pass
    return {"deleted": True}


@router.post("/attachments/{attachment_id}/analyze")
async def analyze_attachment(
    attachment_id: str,
    background_tasks: BackgroundTasks,
    ctx: UserContext = Depends(get_user_context),
):
    """Re-run extraction/summary for an attachment (e.g. after a transient failure)."""
    _ensure_attachments_enabled()
    try:
        await attachment_service.reanalyze(ctx, attachment_id, background_tasks)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "processing"}


@router.get("/conversations/{conversation_id}/files")
async def list_conversation_files(conversation_id: str, ctx: UserContext = Depends(get_user_context)):
    docs = await attachment_store.list_for_conversation(ctx, conversation_id)
    out = [(await attachment_service.to_out(ctx, d)).model_dump() for d in docs]
    return {"files": out}


@router.get("/files/local/{ref:path}")
async def download_local_file(ref: str, ctx: UserContext = Depends(get_user_context)):
    """Serve a locally-stored attachment (development storage backend only).

    Owner-scoped: the requested storage ref must belong to an attachment owned
    by the caller, so users can't read each other's files by guessing paths."""
    from app.db.mongodb import get_collection

    owned = await get_collection(config.ATTACHMENT_COLLECTION).find_one(
        {"storage_ref": ref, "uploaded_by": ctx.user_id}
    )
    if not owned:
        raise HTTPException(status_code=404, detail="File not found")
    path = LocalStorage().local_path(ref)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=owned.get("filename"))
