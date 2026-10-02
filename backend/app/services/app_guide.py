"""Curated 'how to use Sparsh' guide — the single source of truth that both
chatbots (the floating Assistant widget and the Support Engine project chat) use
to answer questions ABOUT the application itself (features, navigation, how-to).

This is intentionally a dependency-free leaf module (no internal imports) so it
can be imported from both ``app.assistant.core.prompt_builder`` and
``app.services.gpt_service`` without creating an import cycle.

It is NOT live data — it describes how the platform works. Live records (a user's
scores, sessions, attendance, counts, etc.) are still fetched through the
assistant's RBAC-scoped tools, never from this text.
"""
from __future__ import annotations

# Keep this concise: it is injected into every assistant/system prompt, so token
# cost matters. Update it whenever a user-facing feature or its location changes.
APP_GUIDE = """# Sparsh — Application Guide (how the platform works)

Sparsh is a business-coaching LMS/ERP. It runs coaching programmes and tracks
learner progress. The core hierarchy is: **Companies** (client organisations) are
grouped into **Batches** (cohorts/programmes), which are split into **Quarters**
(phases). Coaching happens in **Sessions** (scheduled on the Calendar), often built
from reusable **Session Templates** that carry **Tasks** and **Assessments**
(quizzes — multiple-choice and descriptive).

## Roles (who can do what)
- **Superadmin / Admin / Coach (staff):** run the coaching business — manage
  companies, batches, quarters, session templates, schedule sessions, mark
  attendance, manage staff, media and Support Engine projects.
- **Client Admin:** manages their own company's team and views their training.
- **Learner (Client User):** follows their training roadmap, attends sessions,
  takes quizzes, tracks their own progress, and uses the Support Engine.

## Main areas (left sidebar)
- **Dashboard** — key stats and recent activity. On screen it shows the
  "Executive Overview" (KPI cards: registered entities, active batches, strategic
  learners, session velocity), the "System Pulse" (14-day completion trend chart),
  the "Coaching Mix" (session-type distribution), and the "Operational Timeline"
  (upcoming events).
- **Companies** — create/manage client organisations; staff can bulk-import members
  from an Excel template.
- **Batches** — create cohorts and add companies to them; batches contain quarters.
- **Session Templates** — reusable blueprints holding tasks and quiz questions.
- **Calendar / Sessions** — schedule sessions and tasks (one-off or recurring), set
  reminders, mark attendance, and attach learning content/resources.
- **Training Roadmap (Company Portal)** — the learner view: batches → quarters →
  sessions, showing what is locked, in progress, or completed.
- **My Reports / My Progress** — a learner's quiz results, attendance, and progress.
- **User Management** — staff accounts, roles, and permissions (staff only).
- **Team** — a client admin managing their own company's members.
- **Media Library** — upload and organise videos, audio, PDFs and documents (large
  files upload in resumable chunks); includes an AI file assistant.
- **Support Engine (GPT Projects)** — AI projects backed by uploaded knowledge
  documents. A learner gets access to a project when the linked
  batch/quarter/session is completed, or when an admin grants access manually.
- **Settings** — notification email/WhatsApp templates and the backdate policy.
- **Profile** — account details and change password.
- **Notifications** — the bell icon (top bar) shows in-app alerts.

## Common how-to
- **Create a batch (staff):** Sidebar → Batches → "Create / New Batch", then add
  companies to it and create quarters inside the batch.
- **Schedule a session (staff/coach):** Sidebar → Calendar → create an event; pick a
  session template, assignees, a repeat option, and reminders.
- **Mark attendance (coach):** open the session and set each attendee present/absent.
- **Take a quiz (learner):** open the session that has the assessment and start it;
  quizzes open in a locked full-screen player; results appear in My Reports.
- **Check my scores / attendance (learner):** Sidebar → My Reports (or My Progress).
- **Use the Support Engine (learner):** Sidebar → Support Engine; open an unlocked
  project to chat with it. A locked project shows why it is locked (which
  batch/quarter/session must be completed first).
- **Add knowledge to a Support Engine project (staff):** Support Engine → edit the
  project → upload knowledge files (PDF, Word, Excel, audio/video).
- **Grant Support Engine access (admin):** Support Engine → Access Control → Grant
  Access to a specific member or a whole company.
- **Upload media (staff):** Sidebar → Media Library → upload (drag-and-drop; large
  files resume automatically).
- **Reset a password:** on the Login page use "Forgot password" (an OTP is emailed),
  or change it from Profile when signed in.
- **This assistant:** ask about your own records (sessions, scores, attendance,
  progress), search the uploaded knowledge base, or ask how to use Sparsh."""


def build_app_guide(role: str | None = None) -> str:
    """Return the app guide, with a short audience note tailored to the role.

    The guide content is the same for everyone (it is documentation, not data);
    the note just steers the model toward the how-to that matters for this user.
    """
    role_l = (role or "").strip().lower()
    if role_l in ("superadmin", "admin", "coach", "staff"):
        focus = (
            "This user is coaching staff — focus how-to answers on managing "
            "companies, batches, quarters, sessions, templates, media and Support "
            "Engine projects."
        )
    elif role_l == "clientadmin":
        focus = (
            "This user is a client admin — focus on managing their own company's "
            "team and viewing their training; creating batches/templates is done by "
            "coaching staff, not by them."
        )
    else:
        focus = (
            "This user is a learner — focus on their training roadmap, sessions, "
            "quizzes, progress and the Support Engine; management features are "
            "handled by their coach/admin."
        )
    return f"{APP_GUIDE}\n\n_Audience note: {focus}_"
