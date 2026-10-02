"""HRMS ▸ notification adapter.

A thin, fire-and-forget facade over the ERP's existing notification_service. It exists so
HRMS code has ONE call shape for "tell these people about this", and so we never build a
second delivery stack.

**Deliberately not building an outbox.** The source HRMS had its own `hrms_email_outbox`
plus its own SMTP wiring. This ERP already has in-app notifications, email, WhatsApp,
templates and a delivery log in notification_service.py — reimplementing that would be
duplicated, unmaintained and inconsistent with every other module.

**Closing the source's sharpest documented gap.** In the source, leave apply/approve/reject
sent nothing at all: "an employee applies and is approved or rejected with no notification,
no email and no audit row — the decision is invisible until they revisit the page"
(BACKEND_ANALYSIS §10, §14, Risk #14). Every HRMS state transition from Phase 3 onward
routes through this adapter, so that gap cannot reopen.

Contract: nothing here raises into the caller. A notification failure must never roll back
or block the business write that triggered it.
"""
from typing import List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.services.notification_service import (
    create_in_app_notification,
    send_email_notification,
)

# In-app notification kinds accepted by the existing bell UI.
KIND_INFO    = "info"
KIND_SUCCESS = "success"
KIND_WARNING = "warning"
KIND_ERROR   = "error"


async def _resolve_user(user_id: str) -> Optional[dict]:
    """Find a user in either identity collection. Returns None rather than raising."""
    if not user_id:
        return None
    try:
        oid = ObjectId(str(user_id))
    except Exception:
        return None
    for coll in ("staff", "learners"):
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc
    return None


async def notify_user(
    user_id: str,
    title: str,
    message: str,
    kind: str = KIND_INFO,
    link: Optional[str] = None,
    email: bool = False,
) -> None:
    """Notify one user in-app, and optionally by email. Never raises.

    `link` is stored in the notification meta so the bell can deep-link into the HRMS
    screen the notification is about.
    """
    try:
        meta = {"module": "hrms"}
        if link:
            meta["link"] = link
        await create_in_app_notification(
            user_id=str(user_id), title=title, message=message, type=kind, meta=meta
        )
    except Exception as e:
        print(f"[WARN] HRMS in-app notify failed for {user_id}: {e}")

    if not email:
        return
    try:
        user = await _resolve_user(user_id)
        address = (user or {}).get("email")
        if address:
            await send_email_notification(
                to_email=address,
                subject=title,
                message=message,
                user_id=str(user_id),
                slug="hrms",
                meta={"module": "hrms"},
            )
    except Exception as e:
        print(f"[WARN] HRMS email notify failed for {user_id}: {e}")


async def notify_users(
    user_ids: List[str],
    title: str,
    message: str,
    kind: str = KIND_INFO,
    link: Optional[str] = None,
    email: bool = False,
) -> None:
    """Notify several users. De-duplicates ids and skips falsy entries, so callers can
    pass an assembled recipient list without pre-cleaning it."""
    seen = set()
    for uid in user_ids or []:
        key = str(uid or "")
        if not key or key in seen:
            continue
        seen.add(key)
        await notify_user(key, title, message, kind=kind, link=link, email=email)


async def notify_hrms_role(
    company_id: str,
    governance_roles: List[str],
    title: str,
    message: str,
    kind: str = KIND_INFO,
    link: Optional[str] = None,
    email: bool = False,
    exclude_user_ids: Optional[List[str]] = None,
) -> None:
    """Notify everyone in a company holding one of the given governance roles.

    Used for role-targeted routing the recruitment workflow needs from Phase 3 — e.g.
    "a requisition was raised, tell this company's HR". `clientadmin` is always included
    when "MD" is requested, since it is the company's top authority (matching how
    hrms_access.hrms_role maps it).
    """
    if not company_id or not governance_roles:
        return
    try:
        wanted = {r.strip().upper() for r in governance_roles if r}
        query = {"company_id": str(company_id), "governance_role": {"$in": list(wanted)}}
        if "MD" in wanted:
            query = {
                "company_id": str(company_id),
                "$or": [
                    {"governance_role": {"$in": list(wanted)}},
                    {"role": "clientadmin"},
                ],
            }
        rows = await get_collection("learners").find(query, {"_id": 1}).to_list(500)
        # `exclude_user_ids` exists for the caller that has ALREADY addressed somebody
        # directly and is now broadcasting to their role: without it, an HR drafter told
        # "your scorecard was sent back" by name is told again by the HR fan-out --
        # two bells and two mails for one event.
        skip = {str(u) for u in (exclude_user_ids or []) if u}
        await notify_users(
            [str(r["_id"]) for r in rows if str(r["_id"]) not in skip],
            title, message, kind=kind, link=link, email=email
        )
    except Exception as e:
        print(f"[WARN] HRMS role notify failed for company {company_id}: {e}")
