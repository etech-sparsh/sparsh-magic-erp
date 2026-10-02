from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.routes import auth, user, company, batch, quarter, session_template, calendar_events, settings, gpt, dashboard, notification, media, media_ai, media_chunk, tasks, holiday, group, task_meta, reports, orm, orm_sheet, orm_requests, forms, tpms, leadership, irm, meta_templates, notify_templates, hrms, hrms_public, local_files
from app.assistant.router import router as assistant_router

from app.services.reminder_scheduler import start_reminder_scheduler
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    try:
        await connect_to_mongo()
        # Start the background scheduler
        asyncio.create_task(start_reminder_scheduler())
    except Exception as e:
        print(f"CRITICAL: Application started but background tasks failed: {e}")
    yield
    # Shutdown logic
    await close_mongo_connection()

app = FastAPI(title="Business Coaching ERP", lifespan=lifespan)

# Global exception handlers for standard JSON responses on errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": origin if origin else "*"}
    )

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(user.router, prefix="/api")
app.include_router(company.router, prefix="/api")
app.include_router(batch.router, prefix="/api")
app.include_router(quarter.router, prefix="/api")
app.include_router(session_template.router, prefix="/api")
app.include_router(calendar_events.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(gpt.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(holiday.router, prefix="/api")
app.include_router(group.router, prefix="/api")
app.include_router(task_meta.router, prefix="/api")
app.include_router(notification.router, prefix="/api")
app.include_router(orm.router, prefix="/api")
app.include_router(orm_sheet.router, prefix="/api")
app.include_router(orm_requests.router, prefix="/api")
app.include_router(forms.router, prefix="/api")
app.include_router(tpms.router, prefix="/api")
app.include_router(hrms.router, prefix="/api")
# PUBLIC (unauthenticated) HRMS routes - candidate-facing. See routes/hrms_public.py for
# the rules that apply to anything mounted here.
app.include_router(hrms_public.router, prefix="/api")
# TPMS ▸ Leadership Score. Additive: owns its own tpms_leadership_* collections and does
# not alter any existing TPMS route or stored data.
app.include_router(leadership.router, prefix="/api")
# Meta's delivery callbacks. A SECOND router because leadership.router requires a signed-in
# user on every route and Meta has no session; this one is public and verifies Meta's
# X-Hub-Signature-256 on each request instead.
app.include_router(leadership.public_router, prefix="/api")
app.include_router(irm.router, prefix="/api")
# The WhatsApp template library, module-neutral. Also mounted inside the TPMS router, so
# /api/tpms/meta-templates and /api/meta-templates are the same handlers over the same
# collection — TPMS and Task Management share one WhatsApp Business Account.
app.include_router(meta_templates.router, prefix="/api")
app.include_router(notify_templates.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(media_ai.router, prefix="/api")
app.include_router(media_chunk.router, prefix="/api")
# TEMPORARY: serves files written by the local upload fallback while S3 is unreachable.
# Inert unless LOCAL_UPLOAD_FALLBACK is on and `local/` keys exist. Remove this line, the
# route and services/local_upload_store.py once the migration script reports nothing left.
app.include_router(local_files.router, prefix="/api")
app.include_router(assistant_router, prefix="/api")

@app.get("/")
async def root():
    return {"status": "success", "message": "Business Coaching ERP API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
