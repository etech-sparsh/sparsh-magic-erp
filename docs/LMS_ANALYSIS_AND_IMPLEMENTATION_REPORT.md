# LMS Development — Analysis & Implementation Report (Blueprint)

**Project:** Sparsh 2.0 — Business Coaching ERP
**Prepared:** 2026-07-01
**Status:** Analysis & design only — **no code written, no existing files modified**
**Purpose:** Blueprint for building a Learning Management System (LMS) module that integrates with the existing application while preserving its architecture, coding standards, APIs, and UI.

> ⚠️ Scope note: This document is a plan. Every recommendation is grounded in the current codebase with `file:line` references. Nothing here has been implemented.

---

## Executive Summary

Sparsh 2.0 is a **FastAPI (async) + MongoDB (Motor)** backend and a **React 19 + Vite + Tailwind v4** frontend, deployed via Docker Compose to EC2. It is a coaching/training ERP that **already contains ~70% of LMS primitives**:

| LMS Concept | Already exists as | Where |
|---|---|---|
| Course container | **Batch** → **Quarter** hierarchy | `models/batch.py`, `models/quarter.py` |
| Lessons / sessions | **Calendar events** (`type="event"`) + **Session Templates** | `models/calendar_event.py`, `models/session_template.py` |
| Quiz / assessment engine | **AssessmentTemplate** (MCQ auto-grade + descriptive manual-grade) | `models/session_template.py`, `routes/calendar_events.py` submit/marks endpoints |
| Video / PDF content | **Media Library** (S3, multipart upload) + session resources | `routes/media.py`, `routes/media_chunk.py` |
| Progress tracking | Per-resource **view / watch-time / completion** analytics | `routes/calendar_events.py` resource tracking endpoints |
| Attendance | **attendance** collection + endpoints | `routes/calendar_events.py` |
| Enrollment | **Company → Batch** membership | `routes/batch.py` |
| Notifications | In-app + Email (SMTP) + WhatsApp (Meta) + reminders | `services/notification_service.py`, `services/reminder_scheduler.py` |
| Roles & permissions | JWT + dual RBAC (embedded dict + `roles` collection) | `controllers/auth_controller.py`, `models/rbac.py` |
| AI tutor / RAG | Assistant subsystem with vector search | `app/assistant/` |

**Genuine gaps the LMS must add:** a first-class **Course/Module/Lesson catalog** (self-paced, not just calendar-scheduled), **structured enrollment & progress per learner per course**, **certificates**, **discussion/comments**, **bookmarks/notes**, **course-level reporting**, and an **instructor authoring workflow**.

**Recommended strategy:** Build the LMS as a **new bounded module** (`app/lms/` on the backend, `features/lms/` + `pages/lms/` on the frontend) that **reuses** existing infrastructure (auth, RBAC, Media Library, S3, notifications, assessment engine, UI components) rather than duplicating it. New MongoDB collections are namespaced with an `lms_` prefix to avoid collisions with the current data model.

**Estimated effort:** ~**14–20 developer-weeks** for a production-ready v1 (detailed breakdown in §Roadmap).

---

# PART 1 — EXISTING PROJECT ANALYSIS

## 1. Project Architecture

### 1.1 Repository / folder structure

```
sparsh2.0/
├── backend/                  # FastAPI + MongoDB (Motor async)
│   ├── main.py               # App bootstrap, lifespan, CORS, router registration
│   ├── app/
│   │   ├── config/settings.py    # pydantic-settings, .env loading
│   │   ├── db/mongodb.py         # Motor client singleton, get_collection()
│   │   ├── models/               # 14 Pydantic model files
│   │   ├── routes/               # 16 API routers
│   │   ├── controllers/          # auth_controller.py (JWT, deps)
│   │   ├── services/             # S3, notifications, reminders, OCR, transcription…
│   │   ├── utils/
│   │   └── assistant/            # Large AI subsystem (RAG, tools, memory, export…)
│   ├── scripts/                  # Migrations, backfills, vector index setup
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 # React 19 + Vite + Tailwind v4
│   ├── src/
│   │   ├── App.jsx               # Router + provider stack
│   │   ├── pages/                # 32 page components
│   │   ├── components/{common,layout,tasks,calendar}/
│   │   ├── context/              # Auth, Theme, Notification, Upload
│   │   ├── store/slices/         # Redux (auth only, underused)
│   │   ├── services/             # axios instance + API modules
│   │   └── features/assistant/   # AI chat widget
│   ├── nginx.conf                # SPA + /api reverse proxy
│   └── Dockerfile                # Multi-stage build → nginx:alpine
├── docs/                     # Planning docs (this file lives here)
├── docker-compose.yml        # backend (internal) + frontend (:8082)
└── .github/workflows/        # ci.yml (lint+build), deploy.yml (SSH→EC2)
```

### 1.2 Backend architecture

- **Framework:** FastAPI `0.115.6`, Uvicorn `0.34.0`. App created at `main.py:26` with a `lifespan` context (`main.py:13-24`) that connects Mongo, starts the reminder scheduler, and creates a TTL index on `password_resets`.
- **Async everywhere:** Motor `AsyncIOMotorClient` (`db/mongodb.py`); no blocking DB I/O. (Exception: SMTP send is synchronous — see §Performance.)
- **Layering:** `routes/` (HTTP) → inline logic + `services/` (integrations) → `db/` (collections). Controllers are thin (only `auth_controller.py`). Business logic largely lives in route handlers.
- **Router registration:** All 16 routers mounted under `/api` (`main.py:48-63`).

### 1.3 Frontend architecture

- **React 19.2** + **Vite 8** + **react-router-dom 7**. Entry `main.jsx` → `App.jsx`.
- **Provider stack** (`App.jsx:108-126`): `Router → AuthProvider → ThemeProvider → NotificationProvider → UploadProvider → routes`. A global `AssistantWidget` and `NotificationModal` render app-wide.
- **State:** Primarily **React Context** (Auth/Theme/Notification/Upload). Redux Toolkit is configured (`store/slices/authSlice.js`) but **underused** — `AuthContext` is the real source of truth. No RTK Query, no async thunks.
- **Styling:** Tailwind CSS v4 via `@tailwindcss/vite` (no `tailwind.config.js`); design tokens are CSS custom properties in `src/index.css`.

### 1.4 API structure

- REST, JSON, all under `/api`. **~70+ endpoints** across 16 routers.
- Convention: Pydantic request/response models; `_id` aliased to `id` in responses; `HTTPException` for errors; `Depends(get_current_user)` for auth.
- Routers: `auth, user, company, batch, quarter, session_template, calendar_events, tasks, gpt, notification, media, media_ai, media_chunk, settings, dashboard, assistant`.

### 1.5 Database design (MongoDB — document store)

- **Driver:** Motor (async). DB name from `DATABASE_NAME` (default `sparsh_erp`), Atlas with TLS + certifi.
- **Relationships are by reference (string ids), not joins.** Some data embedded (e.g., session template tasks/assessments, reminders, permissions).
- **Notable dual-collection design:**
  - Users split into **`staff`** (superadmin/admin/coach/staff) and **`learners`** (clientadmin/clientuser). Auth looks up staff first, then learners (`auth_controller.py:48-52`).
  - Calendar items split into **`STAFF_CALENDER`** and **`LEARNER_CALENDER`** (plus a `calendar_events` fallback), routed by assignee type.
- **~20 collections** in use: `staff, learners, companies, batches, quarters, STAFF_CALENDER, LEARNER_CALENDER, session_templates, gpt_projects, gpt_conversations, gpt_permissions, password_resets(TTL), activity_logs, in_app_notifications, notification_templates, notifications, media_library, media_chunks, roles, attendance, assistant_conversations, assistant_cost`.
- **Indexes:** Only one created in code — the `password_resets` TTL index (`db/mongodb.py:32-33`). **Most query fields are unindexed** (see §Performance / §Security).

### 1.6 Authentication flow

1. `POST /api/auth/token` (OAuth2 password form) → verify bcrypt password → issue **JWT** (`auth_controller.py:21-29`).
2. **HS256**, secret from `settings.SECRET_KEY`, TTL `ACCESS_TOKEN_EXPIRE_MINUTES` (default **1440 min / 24h**). **No refresh token.**
3. Token claims: `sub` (email), `role`, `_id`, `company_id`, `permissions` (embedded CRUD dict), plus profile fields (`auth.py:262-277`).
4. `get_current_user` decodes the JWT and **re-fetches the user from DB every request** (`auth_controller.py:31-56`) — deactivations take effect immediately for DB checks, but the token itself is not revocable until expiry.
5. **Frontend:** stores token in `localStorage['token']`, decodes with `jwt-decode`, sets axios `Authorization` header, fetches `/users/me` to hydrate the profile (`context/AuthContext.jsx`). On expiry (`exp*1000 < now`) it logs out. **No silent refresh; 401s are not auto-handled** (403s dispatch an `app-error` event).

### 1.7 Authorization & RBAC

Two enforcement layers plus scoping, defined in `auth_controller.py:63-96`:

- **`check_role([roles])`** — coarse role gate.
- **`check_permission(module, action)`** — superadmin bypass; otherwise looks up the `roles` collection and matches `module`+`action`.
- **Inline checks** — many routes read the user's **embedded `permissions` dict** directly, e.g. `permissions["users"]["read"]` (`user.py:19-24`).
- **Company isolation** — `clientadmin` restricted to own `company_id` (`company.py:145-147`).

**Roles:** `superadmin, admin, clientadmin, clientuser, custom` (+ `coach`, `staff` in the staff collection). **Scopes** (`rbac.py`): `global > coaching > company > personal`.

> ⚠️ **Dual permission model** (embedded dict vs. `roles` collection) can drift. The LMS should pick the embedded-dict path for UI gating and the `check_permission` path for API gating, consistently.

### 1.8 State management (frontend)

- **Auth/Theme/Notification/Upload** via Context. **Redux** holds only auth mirror state and is largely unused. No global server-cache layer (each page fetches via axios in `useEffect`).

### 1.9 Routing

- All app routes wrapped in `<PrivateRoute>` (`components/common/PrivateRoute.jsx`), which renders the Sidebar + Navbar shell (or bare via `hideLayout`). Public: `/login`, `/forgot-password`. **No `React.lazy` code-splitting** — every page is eagerly imported in `App.jsx`.

### 1.10 Environment configuration

- **Backend:** `pydantic-settings` + `dotenv` (`config/settings.py`), `.env` with ~29 keys (Mongo, JWT, SMTP, WhatsApp/Meta, OpenAI, AWS S3, FFmpeg, Google). **`.env` is committed to git** (critical — see §Security).
- **Frontend:** single `VITE_API_BASE_URL=/api`; dev proxies `/api → :8000` (`vite.config.js`), prod via nginx.

### 1.11 Build & deployment

- **Backend image:** `python:3.11-slim` + ffmpeg; `uvicorn --proxy-headers`.
- **Frontend image:** multi-stage `node:20-alpine` build → `nginx:alpine` serving `dist/`.
- **Compose:** backend internal (`expose 8000`), frontend published `8082:80`, custom bridge network (DNS by service name).
- **nginx:** gzip, SPA fallback, `/api/` reverse proxy with X-Forwarded headers, `client_max_body_size 5120M`, 3600s timeouts (large media uploads).
- **CI/CD:** `ci.yml` = frontend lint (non-blocking) + `docker compose build`. `deploy.yml` = push to `main` → SSH to EC2 → `git reset --hard` → `docker-compose up --build`. **No tests, no approval gate, no rollback.**

---

## 2. UI / UX Analysis

### 2.1 Design system & tokens (`src/index.css`)

- **Theming:** CSS custom properties, dark mode via `[data-theme='dark']` on `<html>`; toggled through `ThemeContext` and persisted to `localStorage['theme']`.
- **Brand / primary:** `--btn-primary: #4f46e5` (indigo), `--color-primary: #6366f1`.
- **Semantic (light):** `--bg-main #f8fafc`, `--bg-card #ffffff`, `--text-main #0f172a`, `--text-muted #64748b`, `--border #e2e8f0`.
- **Accents:** green `#22c55e`, orange `#f97316`, red `#ef4444`, yellow `#eab308`, indigo `#6366f1` — each with matching `-bg`/`-border` tokens and dark-mode variants.
- **Sidebar / input / status / avatar** tokens all defined (e.g., `--avatar-bg` indigo→purple gradient).
- **Typography:** Inter, 13px base, headings weight 800, letter-spacing −0.02em.
- **Radii/shadows/transition:** `--radius-{sm..2xl}`, `--shadow-{sm,md}`, `--transition: all 0.2s cubic-bezier(...)`.

### 2.2 Layout

- **Sidebar** (`components/layout/Sidebar.jsx`): **config-driven, role-filtered** nav. `links[]` entries carry `{name, path, icon, roles[], permissionKey?, submodules?}`. Collapsible (240px↔72px) with framer-motion spring; hover tooltips when collapsed; supports **submodules** (Task Management already uses this). **This is the single insertion point for LMS nav.**
- **Navbar** (`components/layout/Navbar.jsx`): sticky `h-14`, search, **theme toggle**, notification bell + drawer, superadmin settings link, user dropdown (profile/sign-out).
- **Shell** (`PrivateRoute.jsx`): `flex` sidebar + spacer + `<Navbar/>` + `<main>` with `max-w-[1600px]` container.

### 2.3 Reusable component inventory (reuse for LMS)

| Component | File | API / notes |
|---|---|---|
| **Button** | `common/Button.jsx` (+`.css`) | `variant: primary\|secondary\|danger`, `type`, `onClick`, `className` |
| **Modal** | `common/Modal.jsx` (+`.css`) | `isOpen`, `onClose`, `title`; blurred overlay, max-w 34rem |
| **NotificationModal / toast** | `common/NotificationModal.jsx` | auto-renders from `NotificationContext`; success/error, auto-dismiss 4s |
| **PrivateRoute** | `common/PrivateRoute.jsx` | route guard + layout shell; `hideLayout` for fullscreen |
| **NotificationDrawer** | `layout/NotificationDrawer.jsx` | slide-in panel, type icons, mark/clear |
| **StatusSummaryCards** | `tasks/StatusSummaryCards.jsx` | `cardOrder`, `summary`, `activeKey`, `onSelect` — reuse for course/enrollment KPI cards |
| **TaskListView** | `tasks/TaskListView.jsx` | filter tabs, sort, list/table toggle, bulk actions, search — **template for CourseList/EnrollmentList** |
| **TaskFormModal** | `tasks/TaskFormModal.jsx` | rich create/edit form pattern (multi-select assignees, dates) |
| **statusConfig** | `tasks/statusConfig.js` | centralized status/priority config — **model for `lmsStatusConfig.js`** |
| **IconicInput** (pattern) | `pages/CompanyManagement.jsx:17-32` | labeled input w/ icon + focus ring — reusable form field pattern |

- **Tables:** No generic `<Table>` component — tables are built inline (`<table>` + Tailwind), often with a grid/table view toggle. The LMS can either follow the inline pattern or (better) extract a shared `DataTable` (see Recommendations).
- **Charts:** `recharts` (Area/Bar/Pie) on the Dashboard, themed with accent tokens — reuse for course analytics.
- **Icons:** `lucide-react` (large set; `BookOpen, Library, GraduationCap, Award, Video, FileText…` all available).
- **Animation:** `framer-motion` (AnimatePresence for modals/drawers/sidebar).
- **Mobile:** Tailwind `sm/md/lg/xl`; sidebar becomes an overlay on mobile; forms go full-width.
- **Markdown:** `react-markdown` + `remark-gfm` with `@tailwindcss/typography` `.prose` styles (reuse for lesson content / rich text).

### 2.4 Pages (32) — relevant patterns to mirror

`Dashboard, CompanyManagement/Details, UserManagement/Details, TeamManagement, BatchManagement/Details, QuarterDetails, SessionTemplateManagement/Details, SessionDetails, ContentViewer, AssessmentPlayer, CompanyPortal, MemberDashboard, LearnerSessions, MyReports, MediaLibrary, CalendarPage, Task* (6), SettingsPage, ProfilePage, Gpt* (4)`. **`AssessmentPlayer` (fullscreen quiz), `ContentViewer` (resource viewer), and `MediaLibrary` are directly reusable/extendable for the LMS.**

---

## 3. Backend Analysis

### 3.1 Models (14 files) — entity inventory

Users (`user.py`, split staff/learners), Companies (`company.py`), Batches (`batch.py`), Quarters (`quarter.py`), Calendar Events/Tasks (`calendar_event.py` — dual-type, workflow status, reminders, soft-delete), Session Templates (`session_template.py` — embeds `TaskTemplate` + `AssessmentTemplate` + `AssessmentQuestion`), Notifications/Templates/Logs (`notification.py`), Media (`media.py`), GPT projects/conversations (`gpt.py`), RBAC (`rbac.py`), Activity logs (`activity_log.py`), System settings (`system_settings.py`), Auth DTOs (`auth.py`).

**Key reuse target — the assessment engine already exists:**
- `AssessmentTemplate{ title, passing_score(70), shuffle_questions, questions_to_show, questions[] }`
- `AssessmentQuestion{ question_text, type: MCQ|Descriptive, options[], correct_option_index, expected_answer, marks }`
- Submit + auto-grade + manual-grade endpoints (below).

### 3.2 API endpoints (by router) — condensed

- **auth:** `token, register, forgot/reset-password, change-password, request-admin-otp, admin/update-member`.
- **user:** list, `me`, get, update, delete, status, `activity`, `me/reports`, analytics.
- **company:** CRUD, status, `users` (list/bulk/CSV import/template), `training-path`, session task toggle, analytics.
- **batch:** CRUD, status, add/remove company, list companies, merge, shift company.
- **quarter:** CRUD, analytics.
- **session_template:** CRUD, add tasks, add assessments.
- **calendar_events (richest):** create/update/list/get, conflict validation, attendance, **upload-content / upload-resource / add-from-media**, resource **signed URL / view / watch-time / analytics / chat**, complete, learner-upload, track-join, **assessment submit / get submission / grade marks**.
- **tasks:** dashboard, list (scoped), status, soft-delete, restore.
- **gpt:** projects CRUD, permissions grant/list/revoke, knowledge upload, chat sessions/respond/history/attachments/rethink.
- **notification:** list, unread-count, read, mark-all-read, delete.
- **media:** upload, list, get (re-signs URL), delete. **media_chunk:** start/upload/complete/abort. **media_ai:** AI chat over library.
- **settings:** backdate control, notification templates CRUD, initialize-templates.
- **dashboard:** stats (KPIs, 14-day pulse, session mix).
- **assistant:** health/ready/metrics, `ask` (SSE stream or JSON), conversations CRUD, export-pdf, attachments.

### 3.3 Services / infrastructure

- **File upload / S3** (`services/s3_service.py`): S3-only, UUID-prefixed keys, **presigned URLs (1h)** re-generated on read, full **multipart** (start/upload/complete/abort). Extension+MIME allowlist validation (`routes/media.py:85-116`).
- **Notifications** (`services/notification_service.py`): in-app (`in_app_notifications`) + **Email (SMTP/Gmail)** + **WhatsApp (Meta Cloud API)**, slug-based templates with company→staff→default scoping and `{{var}}` rendering; delivery logged to `notifications`. **No WebSocket for notifications — clients poll.** (SSE exists **only** for assistant chat.)
- **Reminders** (`services/reminder_scheduler.py`): asyncio background loop, **60s poll**, fires email/WhatsApp for embedded event/task `reminders[]`.
- **Audit** (`services/activity_log_service.py`): fire-and-forget inserts to `activity_logs`; covers auth/calendar/tasks/users; **unbounded, no retention.**
- **Assistant** (`app/assistant/`): OpenAI (`gpt-4o`/`gpt-4o-mini`), **Atlas `$vectorSearch`** with `text-embedding-3-small` (kb/attachment/media indices), keyword fallback, tool-calling, per-user rate limit (30/60s), correlation IDs, cost tracking.
- **Media AI** (`media_index_service`, `transcription_service`, `ocr_service`): transcription (Whisper + Google fallback), OCR (Tesseract→GPT-4o-mini vision), chunk+embed into `media_chunks` for semantic search.

### 3.4 Validation

Pydantic v2 across all models (`EmailStr`, enums, typed fields, defaults, `_id` alias). Global 500 handler in `main.py:29-36` (echoes CORS header). Per-route `HTTPException` with standard status codes.

---

## 4. Performance Analysis

| Area | Finding | Location |
|---|---|---|
| **Pagination** | **None cursor/skip-limit.** Routes fetch whole sets: users `.to_list(1000)`×2, batches `.to_list(200)`, gpt `.to_list(500)`. | `user.py:30-31`, `batch.py:46`, `gpt.py:59` |
| **Indexes** | Only `password_resets` TTL. Missing on `staff.email`, `learners.email`, `*.company_id`, `*.batch_id`, `activity_logs.user_id`, etc. | `db/mongodb.py:32-33` |
| **N+1 / in-memory work** | staff+learners fetched separately then merged; batch company counts computed in Python. | `user.py`, `batch.py:46-49` |
| **Caching** | In-process `TTLCache` (metadata 300s / analytics 60s / knowledge 120s), FIFO, max 2000, **per-worker only** (not shared). | `assistant/caching/cache.py` |
| **Blocking I/O** | **SMTP send is synchronous** inside async context — can stall the event loop under load. | `notification_service.py:266-288` |
| **Frontend bundle** | **No `React.lazy`/code-splitting**; heavy deps (recharts, 6× fullcalendar, framer-motion) all eager. | `App.jsx`, `vite.config.js` |
| **Lists** | No virtualization/infinite scroll; large lists render all rows. | `TaskListView.jsx`, `MediaLibrary.jsx` |
| **Static assets** | nginx caches hashed assets 1y `immutable`; gzip on. | `nginx.conf` |
| **Real-time** | SSE streaming for assistant chat only; no WebSocket. | `assistant/router.py` |

## 5. Security Analysis

| Area | Finding | Severity |
|---|---|---|
| **Secrets in VCS** | `backend/.env` (Mongo, OpenAI, AWS, SMTP, WhatsApp) appears committed / not git-ignored. | 🔴 Critical |
| **Password hashing** | bcrypt via passlib — **secure**. | ✅ |
| **JWT** | HS256, 24h, **no refresh, no revocation list**; deactivations rely on per-request DB fetch. | 🟠 Medium |
| **Login brute force** | **No rate limit** on `/auth/token`. | 🟠 Medium |
| **CORS** | `allow_origins=["*"]` + `allow_credentials=True`. Mitigated in prod by same-origin nginx + JWT-in-header (not cookies), but should be restricted. | 🟠 Medium |
| **S3 CORS** | `update_cors.py` sets `AllowedOrigins:['*']`, PUT/POST allowed — ensure bucket is **not** public-read; rely on signed URLs. | 🟠 Medium |
| **NoSQL injection** | Low — all input via Pydantic; `ObjectId()` coercion; no raw query building. | ✅ |
| **XSS** | `react-markdown` escapes HTML; no `dangerouslySetInnerHTML` found; links `rel="noopener noreferrer"`. | ✅ |
| **CSRF** | JWT in `Authorization` header (not cookies) → not CSRF-prone. | ✅ |
| **File upload** | Extension allowlist authoritative + MIME advisory; UUID keys (no path traversal). | ✅ |
| **Error leakage** | Global handler returns `str(exc)` to client. | 🟡 Low |
| **Register endpoint** | `POST /auth/register` allows self-signup as learner when unauthenticated. | 🟡 Low (verify intent) |

---

# PART 2 — LMS BLUEPRINT

> Design principle: **reuse, don't duplicate.** New LMS entities reference existing users/companies/media/assessments. New collections are prefixed `lms_`. New APIs live under `/api/lms/...`. New UI lives under `/lms/...` and `features/lms/`. Existing auth, RBAC, S3, notifications, and the assessment engine are reused as-is.

## 6. Module Structure

| # | Module | Build vs. Reuse | Notes |
|---|---|---|---|
| 1 | **LMS Dashboard** | New (reuse StatusSummaryCards + recharts) | Role-aware: learner vs. instructor vs. admin |
| 2 | **Courses** | New (`lms_courses`) | Self-paced catalog; optionally link to a Batch/Quarter |
| 3 | **Categories** | New (`lms_categories`) | Tagging/taxonomy |
| 4 | **Modules/Chapters** | New (`lms_modules`) | Ordered sections within a course |
| 5 | **Lessons** | New (`lms_lessons`) | Content unit: video/pdf/text/quiz/assignment |
| 6 | **Video/Document mgmt** | **Reuse Media Library** | Reference `media_library` `_id`; reuse multipart upload + tracking |
| 7 | **Quizzes** | **Reuse AssessmentTemplate engine** | Attach existing assessment to a lesson |
| 8 | **Assignments** | New (`lms_assignments`, `lms_submissions`) | Reuse S3 upload + manual grading pattern |
| 9 | **Certificates** | New (`lms_certificates`) | Generate PDF via **reportlab** (already a dep) |
| 10 | **Enrollment** | New (`lms_enrollments`) | Learner↔course; supports company/batch bulk enroll |
| 11 | **Progress tracking** | New (`lms_progress`) + reuse resource watch-time | Per-lesson completion; course % |
| 12 | **Discussion / Comments** | New (`lms_discussions`) | Per-course threads + per-lesson comments |
| 13 | **Announcements** | **Reuse notifications** | Course-scoped announcement → in-app/email/WhatsApp |
| 14 | **Reports / Analytics** | New (reuse dashboard patterns) | Course completion, quiz scores, engagement |
| 15 | **Instructor authoring** | New UI (reuse forms/modals) | Course builder |
| 16 | **Calendar integration** | **Reuse calendar_events** | Live sessions, deadlines surface on existing calendar |
| 17 | **Bookmarks / Notes** | New (`lms_bookmarks`, `lms_notes`) | Learner personal layer |
| 18 | **Settings** | **Reuse settings** | LMS defaults (passing score, certificate template) |

## 7. User Roles & Permission Matrix

Reuse existing roles; add a new permission **module key `lms`** (and optional sub-keys) to both the embedded `permissions` dict and the `roles` collection. Add an **`instructor`** capability (either a new role or a flag on staff; recommended: reuse `coach`/`admin` as instructors to avoid a new role).

| Capability | superadmin | admin | coach/instructor | clientadmin | clientuser (learner) |
|---|---|---|---|---|---|
| Manage LMS settings | ✅ | ✅ | — | — | — |
| Create/edit/delete course | ✅ | ✅ | ✅ (own) | — | — |
| Publish course | ✅ | ✅ | ✅ (own) | — | — |
| Author lessons/quizzes | ✅ | ✅ | ✅ (own) | — | — |
| Enroll learners | ✅ | ✅ | ✅ (own courses) | ✅ (own company) | — |
| View all courses/catalog | ✅ | ✅ | ✅ | ✅ (assigned) | ✅ (enrolled/assigned) |
| Take lessons/quizzes | — | — | — | — | ✅ |
| Submit assignments | — | — | — | — | ✅ |
| Grade assignments/descriptive | ✅ | ✅ | ✅ (own) | — | — |
| View course reports | ✅ (all) | ✅ (all) | ✅ (own) | ✅ (own company) | own progress only |
| Issue/revoke certificate | ✅ | ✅ | ✅ (own) | — | auto-earned |
| Moderate discussion | ✅ | ✅ | ✅ (own) | ✅ (own company) | post/reply |

**Enforcement:** API via `check_permission("lms", action)`; UI via `user.permissions.lms.read` in the Sidebar config (same pattern as existing modules). Company/course scoping mirrors `company.py:145-147`.

## 8. Database Design (MongoDB)

> Document store — "PK" = `_id` (ObjectId), "FK" = referenced string id. All timestamps UTC. Add compound indexes as noted.

### 8.1 Collections

**`lms_courses`**
```
_id, title, slug, description, summary, category_ids[], tags[],
cover_media_id → media_library, level(beginner|intermediate|advanced),
instructor_ids[] → staff, status(draft|published|archived),
visibility(public|company|batch|manual), company_ids[], batch_ids[],
estimated_minutes, passing_criteria{ require_all_lessons, min_quiz_avg },
certificate_enabled(bool), certificate_template_id → lms_cert_templates,
created_by → staff, created_at, updated_at, published_at
```
Indexes: `slug`(unique), `status`, `instructor_ids`, `company_ids`, `batch_ids`, text index on `title,description`.

**`lms_categories`**: `_id, name, slug, parent_id?, order`. Index: `slug`(unique), `parent_id`.

**`lms_modules`** (chapters/sections): `_id, course_id → lms_courses, title, description, order, created_at`. Index: `course_id+order`.

**`lms_lessons`**:
```
_id, course_id, module_id → lms_modules, title, order,
type(video|document|text|quiz|assignment|scorm?), 
content{ media_id? → media_library, body_markdown?, 
         assessment_id? → (embedded AssessmentTemplate or new lms_quizzes),
         assignment_id? → lms_assignments },
duration_seconds, is_preview(bool), created_at, updated_at
```
Indexes: `course_id+module_id+order`, `type`.

**`lms_enrollments`**:
```
_id, course_id, user_id → learners/staff, enrolled_by, source(manual|company|batch|self),
status(active|completed|dropped|expired), progress_percent, 
started_at, completed_at, due_date?, last_activity_at, created_at
```
Indexes: `course_id+user_id`(unique), `user_id+status`, `course_id+status`.

**`lms_progress`** (per lesson):
```
_id, enrollment_id → lms_enrollments, course_id, user_id, lesson_id → lms_lessons,
status(not_started|in_progress|completed), watch_seconds, last_position_seconds,
score?, attempts?, completed_at, updated_at
```
Indexes: `enrollment_id+lesson_id`(unique), `user_id+course_id`.

**`lms_quiz_attempts`** (reuse assessment scoring shape):
```
_id, lesson_id, course_id, user_id, assessment_id, answers[], 
auto_score, manual_score, total_marks, passed(bool), 
graded_by?, graded_at, submitted_at
```
Indexes: `user_id+lesson_id`, `course_id`. (Mirror existing submit/grade logic in `calendar_events.py`.)

**`lms_assignments`**: `_id, course_id, lesson_id, title, instructions_markdown, max_marks, due_date, allow_files(bool), allowed_types[]`. 
**`lms_submissions`**: `_id, assignment_id, course_id, user_id, files[]{media_id,name}, text, status(submitted|graded|returned), marks?, feedback?, graded_by?, submitted_at, graded_at`. Indexes: `assignment_id+user_id`, `status`.

**`lms_certificates`**: `_id, course_id, user_id, enrollment_id, serial_no(unique), issued_at, revoked(bool), pdf_media_id → media_library, template_id`. Index: `serial_no`(unique), `user_id`.
**`lms_cert_templates`**: `_id, name, html_or_layout, fields[]`.

**`lms_discussions`**: `_id, course_id, lesson_id?, parent_id?(threading), user_id, body_markdown, is_pinned, is_resolved, created_at, edited_at, deleted_at?`. Indexes: `course_id+created_at`, `parent_id`.

**`lms_bookmarks`** / **`lms_notes`**: `_id, user_id, course_id, lesson_id, timestamp_seconds?, body?, created_at`. Index: `user_id+course_id`.

**Reused as-is:** `media_library`, `media_chunks`, `staff`, `learners`, `companies`, `batches`, `quarters`, `notifications`, `notification_templates`, `activity_logs`, `roles`, `calendar_events`.

### 8.2 Logical ER (reference relationships)

```
companies ──< lms_courses.company_ids                 (visibility scoping)
batches   ──< lms_courses.batch_ids
staff (instructor) ──< lms_courses.instructor_ids
lms_categories ──< lms_courses.category_ids

lms_courses 1──* lms_modules 1──* lms_lessons
lms_lessons *──1 media_library            (video/pdf content)
lms_lessons *──1 AssessmentTemplate/lms_quizzes   (quiz lessons)
lms_lessons *──1 lms_assignments

learners/staff *──* lms_courses  via  lms_enrollments
lms_enrollments 1──* lms_progress (per lesson)
lms_enrollments 1──* lms_quiz_attempts
lms_assignments 1──* lms_submissions
lms_enrollments 1──0..1 lms_certificates
lms_courses 1──* lms_discussions
users 1──* lms_bookmarks / lms_notes
```

### 8.3 Index & migration plan

- Create the indexes above in a startup routine or a `scripts/setup_lms_indexes.py` (mirror `scripts/setup_vector_indexes.py`).
- **Also add the currently-missing core indexes** (`staff.email`, `learners.email` unique) while touching the DB layer — the LMS will hammer user lookups.
- Optional: add `lms_lessons`/`lms_courses` to the assistant vector pipeline for AI course search (reuse `media_index_service` pattern).

## 9. API Design (`/api/lms/...`)

Conventions inherited: Pydantic models, `Depends(get_current_user)` + `check_permission("lms", action)`, `_id`→`id`, `HTTPException`, skip/limit pagination (**introduce here as the standard**), activity logging.

**Courses**
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/lms/courses` | lms:create | Create course (draft) |
| GET | `/api/lms/courses?status&category&search&skip&limit` | lms:read | List/catalog (scoped by role/company/enrollment) |
| GET | `/api/lms/courses/{id}` | lms:read | Course detail (+modules/lessons for authorized) |
| PUT | `/api/lms/courses/{id}` | lms:update (own) | Edit |
| PATCH | `/api/lms/courses/{id}/status` | lms:update | Publish/archive |
| DELETE | `/api/lms/courses/{id}` | lms:delete | Soft delete |

**Modules & Lessons**
| POST/PUT/DELETE | `/api/lms/courses/{id}/modules[/{mid}]` | lms:update | Manage sections |
| POST/PUT/DELETE | `/api/lms/lessons[/{lid}]` | lms:update | Manage lessons; reorder via `order` |
| POST | `/api/lms/lessons/{lid}/attach-media` | lms:update | Link `media_library` item |
| POST | `/api/lms/lessons/{lid}/quiz` | lms:update | Attach/define assessment |

**Enrollment**
| POST | `/api/lms/courses/{id}/enroll` | lms:read (self) / lms:assign | Self or bulk enroll |
| POST | `/api/lms/courses/{id}/enroll/bulk` | lms:assign | By company/batch/user list |
| GET | `/api/lms/enrollments?user_id&course_id&status` | scoped | List |
| PATCH | `/api/lms/enrollments/{id}/status` | lms:assign | Drop/complete |

**Progress & Player**
| POST | `/api/lms/lessons/{lid}/progress` | learner | Update watch-time/position/complete (reuse resource watch-time pattern) |
| GET | `/api/lms/courses/{id}/progress` | learner/instructor | My/aggregate progress |
| POST | `/api/lms/lessons/{lid}/quiz/submit` | learner | Submit → auto-grade MCQ (reuse existing logic) |
| PATCH | `/api/lms/quiz-attempts/{id}/grade` | instructor | Grade descriptive |

**Assignments**
| POST | `/api/lms/lessons/{lid}/assignment/submit` (multipart) | learner | Upload via S3 |
| PATCH | `/api/lms/submissions/{id}/grade` | instructor | Marks + feedback |

**Certificates**
| POST | `/api/lms/courses/{id}/certificate/issue` | system/instructor | Generate PDF (reportlab) → store in `media_library` |
| GET | `/api/lms/certificates/{serial}` | public/verify | Verify certificate |

**Discussion / Announcements**
| POST/GET/DELETE | `/api/lms/courses/{id}/discussions[/{did}]` | scoped | Threads/comments |
| POST | `/api/lms/courses/{id}/announce` | instructor | Fan-out via notification_service |

**Reports**
| GET | `/api/lms/courses/{id}/analytics` | instructor/admin | Completion, avg score, engagement |
| GET | `/api/lms/reports/learner/{uid}` | scoped | Per-learner transcript |

**Standard responses:** `{ items, total, skip, limit }` for lists; `{ id, ... }` for entities; validation via Pydantic; errors `400/401/403/404/409`; every mutating call writes `activity_logs`.

## 10. UI Pages (`/lms/...`, lazy-loaded)

| Route | Page | Reuses |
|---|---|---|
| `/lms` | LMS Dashboard (role-aware) | StatusSummaryCards, recharts |
| `/lms/courses` | Course catalog (grid/table) | TaskListView pattern, Card pattern |
| `/lms/courses/new`, `/lms/courses/:id/edit` | Course builder | Modal, forms, drag-order |
| `/lms/courses/:id` | Course detail / syllabus | Cards, Tabs |
| `/lms/courses/:id/learn/:lessonId` | **Lesson player** | ContentViewer, media player, `.prose` markdown |
| `/lms/courses/:id/quiz/:lessonId` | Quiz player | **AssessmentPlayer** (`hideLayout`) |
| `/lms/assignments/:id` | Assignment submit/grade | UploadContext, Modal |
| `/lms/my-learning` | Learner dashboard (enrolled + progress) | StatusSummaryCards |
| `/lms/instructor` | Instructor dashboard | recharts, tables |
| `/lms/courses/:id/reports` | Course reports | recharts |
| `/lms/certificates` | My certificates | PdfDownloadCard pattern |
| `/lms/settings` | LMS settings | SettingsPage pattern |

**Sidebar:** add an `lms` group with submodules to `Sidebar.jsx links[]` (`roles + permissionKey:'lms'`). **State:** new `services/lmsApi.js` (reuse the axios instance) + a `features/lms/` folder with hooks (`useCourses`, `useEnrollment`, `useLessonPlayer`) following the assistant-feature structure. **Introduce `React.lazy` for LMS routes** to avoid growing the eager bundle.

## 11. Features (mapping to reuse)

Course mgmt, video/PDF upload (**Media Library + multipart**), notes/bookmarks (new), assignments (S3 + manual grade), **quiz engine + question bank (reuse AssessmentTemplate)**, progress & completion (new + watch-time reuse), certificates (**reportlab**), search/filter/sort/pagination (standardize skip/limit), notifications/email/WhatsApp (**reuse notification_service**), calendar deadlines (**reuse calendar_events**), comments/discussion (new), attendance for live sessions (reuse), analytics/reports (reuse dashboard), audit logs (**reuse activity_logs**), role permissions (**reuse RBAC + `lms` module**), activity timeline (reuse), S3 storage (reuse), AI course assistant/RAG (optional, reuse assistant vector pipeline).

## 12. Integration Plan (non-breaking)

- **APIs:** additive only, namespaced `/api/lms/*`; register one `lms.router` in `main.py` alongside the others. No existing endpoint changes.
- **Database:** new `lms_*` collections only; reference existing ids. No schema changes to current collections. (Adding indexes is safe/additive.)
- **Auth:** reuse `get_current_user` / `check_permission`; add `lms` permission key with a **safe default of `read:false`** so nothing is exposed until granted. Backfill the key on existing users via a small idempotent migration (mirror `migrate_templates.py`).
- **UI:** add routes + a Sidebar group; reuse all shared components, contexts, and tokens. No changes to existing pages.
- **Media/S3/Notifications:** consumed as libraries — zero changes.
- **Feature flag:** gate the Sidebar entry + routes behind an env/setting (e.g., `LMS_ENABLED`) for staged rollout, matching the assistant's feature-flag style.

## 13. Risks & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| **Secrets already in git** (`.env`) | Credential compromise | Rotate all keys; git-ignore `.env`; add `.env.example`. Do this **before** LMS launch. |
| **No pagination standard** — LMS will 10× row counts | Slow list APIs, memory | Ship LMS with skip/limit from day 1; retrofit `total` counts. |
| **Missing DB indexes** | Query latency at scale | Add LMS indexes + core `email` indexes in one migration. |
| **Dual RBAC drift** (embedded dict vs `roles`) | Inconsistent access | Standardize: UI reads embedded dict, API uses `check_permission`; keep both in sync in the `lms` migration. |
| **Synchronous SMTP** | Event-loop stalls on bulk course emails | Send LMS announcements via `run_in_executor` / background tasks; consider a queue. |
| **No code-splitting** | Bundle bloat (video player, charts) | `React.lazy` all LMS routes; lazy-load player/recharts. |
| **In-process cache only** | Inconsistent across workers | Fine for v1 single-instance; plan Redis if horizontally scaled. |
| **Large media uploads** | Timeouts, cost | Reuse existing multipart + 3600s nginx timeouts; enforce per-type size caps. |
| **Deploy has no tests/rollback** | Regressions reach prod | Add LMS unit/integration tests to CI; consider a staging compose + image tags for rollback. |
| **Dual user collections** (staff/learners) | Enrollment must resolve both | Enrollment helper that looks up staff→learners (reuse auth pattern). |

## 14. Development Roadmap (phased)

| Phase | Scope | Est. |
|---|---|---|
| **0. Foundations** | `lms` permission key + migration; `lms_*` collections + indexes; `lms.router` skeleton; Sidebar group + lazy routes; `lmsApi.js`; feature flag | 1–1.5 wk |
| **1. Course & content model** | Courses/Modules/Lessons CRUD; instructor course builder UI; attach Media Library items | 2–3 wk |
| **2. Enrollment & catalog** | Enrollment (self/company/batch/bulk); catalog + course detail pages; visibility scoping | 1.5–2 wk |
| **3. Lesson player & progress** | Player (video/pdf/markdown); progress + watch-time; resume position | 2 wk |
| **4. Quizzes** | Attach AssessmentTemplate to lessons; quiz player (reuse AssessmentPlayer); auto/manual grading | 1.5–2 wk |
| **5. Assignments** | Submit (S3) + grade + feedback | 1 wk |
| **6. Certificates** | reportlab PDF generation + verification page | 1 wk |
| **7. Discussion & announcements** | Threads/comments; course announcements via notifications | 1.5 wk |
| **8. Reports & dashboards** | Learner/instructor/admin dashboards + course analytics (recharts) | 1.5–2 wk |
| **9. Hardening** | Pagination everywhere, indexes verified, rate limits, security fixes, load test | 1–1.5 wk |
| **10. Testing & rollout** | Unit/integration tests, CI gates, staged flag rollout, docs | 1.5 wk |

**Total ≈ 14–20 developer-weeks** for v1 (single full-stack dev; less with parallelization).

## 15. Estimated Development Effort (summary)

- **Backend:** ~7–9 wk (models, ~40 endpoints, grading reuse, certificates, reports).
- **Frontend:** ~6–8 wk (course builder, player, dashboards, catalog, lazy-loading).
- **Cross-cutting:** ~1.5–2.5 wk (migrations, indexes, tests, CI, rollout).
- **Team of 2 (1 BE + 1 FE):** ~8–11 calendar weeks.

## 16. Deliverables & Recommendations

**This report delivers:** Executive summary, current-project analysis (architecture, UI/UX, backend, performance, security), LMS architecture, module breakdown, DB design, API design, UI plan, security/performance plans, integration strategy, roadmap, effort estimate, and risks.

**Top recommendations before LMS build starts:**
1. 🔴 **Rotate secrets & git-ignore `.env`** (independent of LMS; do immediately).
2. **Adopt skip/limit pagination + a shared `DataTable`** component as the LMS standard, and backfill the missing `email`/scope **indexes**.
3. **Reuse the assessment engine, Media Library, S3, notifications, and RBAC** — do not rebuild them.
4. **Namespace everything** (`app/lms/`, `features/lms/`, `/api/lms`, `lms_*` collections, `lms` permission key) and ship behind a **feature flag** for safe, non-breaking rollout.
5. **Introduce `React.lazy`** for LMS routes to protect bundle size.
6. Add **LMS tests to CI** and a lightweight **rollback** story (image tags/staging) given the current push-to-main deploy.

---

*End of report. No code was written and no existing project files were modified in producing this analysis.*
