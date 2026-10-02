"""HRMS > the public-link registry (Phase 11-R, Item 1).

ONE place that knows every candidate-facing link this module has ever issued, what happened
to it, and how to kill it.

-- The problem this solves ----------------------------------------------------------
Four kinds of public link already existed, each minted independently and surfaced ad-hoc:

    apply       hrms_posting_service._mint_code       ->  /apply/<posting_code>
    assessment  hrms_assessment_service              ->  /assess/<access_code>
    offer       hrms_offer_service                   ->  /offer/<access_code>
    onboarding  hrms_onboarding_service              ->  /onboard/<access_code>

Between them there was no registry, no open tracking, no expiry, no revocation and no single
screen to find them. A recruiter who mailed an offer link to the wrong address had no way to
withdraw it.

-- What this module does NOT do ------------------------------------------------------
It does not mint codes and it does not change how any of the four services work. Each still
generates its own credential exactly as before; this records the result. `register_link` is
called immediately after a code is minted, in the same request, and is **fire-and-forget**:
if the registry write fails, the offer still goes out. A bookkeeping failure must never
break a business action -- the same contract hrms_audit_service and hrms_notify_service hold.

-- Revocation is real, not cosmetic --------------------------------------------------
`assert_link_live` in utils/hrms_public_guard.py is called by every public handler before it
does any work, and returns the vague CLOSED_LINK for a revoked or expired link. A registry
that only *displayed* a Revoked chip while the link kept working would be worse than none.

-- Legacy links are never locked out --------------------------------------------------
A code with no registry row reads as Active with an unknown open count. Every link issued
before this phase therefore keeps working, with no migration script. (See §3.2 of the phase
prompt: backfill is not migration.)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_LINK_ISSUED, AUDIT_LINK_REISSUED, AUDIT_LINK_REVOKED, COLL_CANDIDATES,
    COLL_LINKS, COLL_REQUISITIONS, ENTITY_LINK, LINK_PATHS, REISSUABLE_KINDS,
    HrmsRole, LinkKind, LinkStatus, effective_link_status,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _out(doc: dict, today: str = None) -> dict:
    """Project a registry row for the API, with its status computed rather than read."""
    today = today or _today()
    doc = dict(doc)
    doc.pop("_id", None)
    doc["status"] = effective_link_status(doc, today)
    doc["never_opened"] = not int(doc.get("open_count") or 0)
    return doc


# -------------------------------------------------------------
# Write — called by the four owning services
# -------------------------------------------------------------
async def register_link(
    *,
    company_id: str,
    kind,
    code: str,
    target_type: str,
    target_id: str,
    actor: Optional[dict] = None,
    candidate_name: str = None,
    request_no: str = None,
    expires_at: str = None,
) -> Optional[dict]:
    """Record a link that has just been issued. NEVER raises into the caller.

    Returns the registry row, or None when registration failed — the caller ignores the
    result and carries on either way. That is the whole point: an offer must not fail to
    send because a bookkeeping collection was unavailable.

    Idempotent on `code`. Re-registering the same code (a retry, or a service that mints
    once and registers twice) updates the existing row rather than colliding with the
    unique index.
    """
    try:
        kind_value = getattr(kind, "value", kind)
        if kind_value not in {k.value for k in LinkKind}:
            print(f"[WARN] HRMS link registry: unknown kind {kind_value!r}")
            return None
        if not code:
            return None

        coll = get_collection(COLL_LINKS)
        existing = await coll.find_one({"code": code})
        if existing:
            return _out(existing)

        now = datetime.now(timezone.utc)
        year = now.year
        link_id = await next_business_id("link", str(company_id), year)

        doc = {
            "link_id": link_id,
            "company_id": str(company_id),
            "kind": kind_value,
            "code": code,
            "path": LINK_PATHS[LinkKind(kind_value)].format(code=code),
            "target_type": target_type,
            "target_id": str(target_id) if target_id is not None else None,
            "candidate_name": candidate_name,
            # Carried so the MANAGER row-scope narrowing works on this collection with the
            # same rule every other HRMS read surface uses.
            "request_no": request_no,
            "issued_by": str((actor or {}).get("_id") or "") or None,
            "issued_by_name": _actor_name(actor),
            "issued_at": now,
            "status": LinkStatus.ACTIVE.value,
            "expires_at": expires_at or None,
            "open_count": 0,
            "first_opened_at": None,
            "last_opened_at": None,
            "consumed_at": None,
            "revoked_at": None,
            "revoked_by": None,
            "revoke_reason": None,
            "created_at": now,
        }
        await coll.insert_one(dict(doc))
        await audit(actor, AUDIT_LINK_ISSUED, ENTITY_LINK, link_id,
                    f"{kind_value} link for {target_id}", company_id)
        return _out(doc)
    except Exception as e:
        # Deliberately swallowed — see the module docstring.
        print(f"[WARN] HRMS link registration failed ({code}): {e}")
        return None


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "system")


async def record_open(code: str) -> None:
    """Count a view of a public link. Never raises.

    'Opened' means the public GET handler served the page. It is not a read receipt: a link
    forwarded to three colleagues counts three opens, and a preview fetch counts one. The
    Link Manager says so in as many words rather than implying precision it does not have.
    """
    try:
        now = datetime.now(timezone.utc)
        # One atomic round trip: increment the counter and stamp the latest sighting
        # together, so two concurrent opens cannot both read the same count and write it
        # back. This is the same find_one_and_update discipline hrms_id_service uses for
        # business ids, and for the same reason.
        doc = await get_collection(COLL_LINKS).find_one_and_update(
            {"code": code},
            {"$inc": {"open_count": 1}, "$set": {"last_opened_at": now}},
        )
        # The EARLIEST sighting is written once and never overwritten, so "when did they
        # first look at this" survives every later view.
        if doc is not None and not doc.get("first_opened_at"):
            await get_collection(COLL_LINKS).update_one(
                {"code": code}, {"$set": {"first_opened_at": now}})
    except Exception as e:
        print(f"[WARN] HRMS link open tracking failed ({code}): {e}")


async def record_consumed(code: str) -> None:
    """Mark a link's purpose complete — applied, submitted, responded, acknowledged.

    Consumed links stay LIVE (see LIVE_LINK_STATUSES): a candidate who has submitted must
    still be able to reopen the page and see that their submission landed. The status is
    for the operator's benefit, telling "waiting on them" from "done".
    """
    try:
        await get_collection(COLL_LINKS).update_one(
            {"code": code, "status": LinkStatus.ACTIVE.value},
            {"$set": {"status": LinkStatus.CONSUMED.value,
                      "consumed_at": datetime.now(timezone.utc)}})
    except Exception as e:
        print(f"[WARN] HRMS link consume tracking failed ({code}): {e}")


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def _scope_filter(actor: dict, company_id: str) -> dict:
    """MANAGER narrowing, identical in rule and in failure mode to
    hrms_candidate_service._scope_filter: a manager sees links for requisitions they raised,
    and a manager who has raised none matches NOTHING rather than everything."""
    if hrms_role(actor) != HrmsRole.MANAGER:
        return {}
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "created_by": str(actor.get("_id") or "")},
        {"request_no": 1}).to_list(2000)
    return {"request_no": {"$in": [r["request_no"] for r in rows]}}


async def list_links(actor: dict, company_id: str, *, kind: str = None, status: str = None,
                     search: str = None, date_from: str = None, date_to: str = None,
                     limit: int = 200, skip: int = 0) -> dict:
    """The Link Manager's table plus its stat tiles."""
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if kind:
        query["kind"] = kind
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"code": {"$regex": safe, "$options": "i"}},
            {"link_id": {"$regex": safe, "$options": "i"}},
            {"candidate_name": {"$regex": safe, "$options": "i"}},
            {"target_id": {"$regex": safe, "$options": "i"}},
        ]
    if date_from or date_to:
        window = {}
        if date_from:
            window["$gte"] = datetime.strptime(date_from, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        if date_to:
            window["$lte"] = datetime.strptime(date_to, "%Y-%m-%d").replace(
                tzinfo=timezone.utc, hour=23, minute=59, second=59)
        query["issued_at"] = window

    coll = get_collection(COLL_LINKS)
    limit = max(1, min(int(limit or 200), 500))
    rows = await coll.find(query).sort("created_at", -1).skip(
        max(0, int(skip or 0))).limit(limit).to_list(limit)

    today = _today()
    out = [_out(r, today) for r in rows]
    # Status is COMPUTED, so it must be filtered after projection -- a Mongo filter on the
    # stored value would miss every link that expired without anybody rewriting the row.
    if status:
        out = [r for r in out if r["status"] == status]

    return {
        "links": out,
        "total": len(out),
        "limit": limit,
        "skip": skip,
        "stats": {
            "active": sum(1 for r in out if r["status"] == LinkStatus.ACTIVE.value),
            "expired": sum(1 for r in out if r["status"] == LinkStatus.EXPIRED.value),
            "revoked": sum(1 for r in out if r["status"] == LinkStatus.REVOKED.value),
            "consumed": sum(1 for r in out if r["status"] == LinkStatus.CONSUMED.value),
            "never_opened": sum(1 for r in out if r["never_opened"]),
        },
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
    }


async def _require_visible(actor: dict, company_id: str, link_id: str) -> dict:
    query = {"link_id": link_id, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_LINKS).find_one(query)
    if not doc:
        # 404 rather than 403 for an out-of-scope row: a 403 would confirm the id exists.
        raise HTTPException(status_code=404, detail="Link not found.")
    return doc


async def get_link(actor: dict, company_id: str, link_id: str) -> dict:
    doc = await _require_visible(actor, company_id, link_id)
    out = _out(doc)
    # The open history the registry actually holds: counts and first/last sighting. We do
    # NOT store one row per open -- that would be an unbounded, IP-bearing log of a
    # candidate's browsing on a public page, which is more surveillance than the feature
    # needs and more PII than we want to hold.
    out["opens"] = {
        "count": int(doc.get("open_count") or 0),
        "first_opened_at": doc.get("first_opened_at"),
        "last_opened_at": doc.get("last_opened_at"),
    }
    return out


# -------------------------------------------------------------
# Revoke / reissue
# -------------------------------------------------------------
async def revoke(actor: dict, company_id: str, link_id: str, reason: str = None) -> dict:
    """Kill a live link.

    Compare-and-swap on the stored status, so two revoke clicks cannot both land and the
    second gets a clear 409 rather than silently overwriting the first one's reason.
    """
    doc = await _require_visible(actor, company_id, link_id)
    current = effective_link_status(doc, _today())
    if current == LinkStatus.REVOKED.value:
        raise HTTPException(status_code=409, detail="This link is already revoked.")

    now = datetime.now(timezone.utc)
    from app.utils.hrms_public_guard import clean_text
    result = await get_collection(COLL_LINKS).update_one(
        {"link_id": link_id, "company_id": str(company_id),
         "status": {"$ne": LinkStatus.REVOKED.value}},
        {"$set": {"status": LinkStatus.REVOKED.value, "revoked_at": now,
                  "revoked_by": str(actor.get("_id") or ""),
                  "revoked_by_name": _actor_name(actor),
                  "revoke_reason": clean_text(reason, limit=500)}})
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="This link is already revoked.")

    await audit(actor, AUDIT_LINK_REVOKED, ENTITY_LINK, link_id,
                clean_text(reason, limit=500), company_id)
    return await get_link(actor, company_id, link_id)


async def reissue(actor: dict, company_id: str, link_id: str) -> dict:
    """Mint a fresh credential for the same target and revoke the old one.

    DELEGATES to the owning service. The registry must never invent a code the owning
    service has not heard of -- that would produce a link that resolves to nothing, which
    is worse than the dead link it was meant to replace.

    An `apply` link is deliberately NOT reissuable: a posting code is a public identifier
    printed on job boards, and rotating it would break every ad already published. Close the
    posting and publish a new one instead.
    """
    doc = await _require_visible(actor, company_id, link_id)
    kind = doc.get("kind")
    if kind not in {k.value for k in REISSUABLE_KINDS}:
        raise HTTPException(
            status_code=409,
            detail=("An application link cannot be reissued — its code is printed on every "
                    "job board the posting was published to. Close the posting and publish "
                    "a new one instead."))

    from app.utils.hrms_public_guard import new_access_code
    collection_for = {
        LinkKind.ASSESSMENT.value: ("hrms_assessments", "assessment_no"),
        LinkKind.OFFER.value:      ("hrms_offers", "offer_no"),
        LinkKind.ONBOARDING.value: ("hrms_onboarding", "onb_no"),
        LinkKind.APPOINTMENT.value: ("hrms_appointments", "appointment_no"),
    }
    coll_name, id_field = collection_for[kind]
    owner = await get_collection(coll_name).find_one(
        {"access_code": doc.get("code"), "company_id": str(company_id)})
    if not owner:
        raise HTTPException(
            status_code=409,
            detail="The record this link belongs to no longer exists, so it cannot be reissued.")

    fresh = new_access_code()
    await get_collection(coll_name).update_one(
        {"_id": owner["_id"]},
        {"$set": {"access_code": fresh, "updated_at": datetime.now(timezone.utc)}})

    # Old row first, so a failure part-way cannot leave two live links to one record.
    await get_collection(COLL_LINKS).update_one(
        {"link_id": link_id, "company_id": str(company_id)},
        {"$set": {"status": LinkStatus.REVOKED.value,
                  "revoked_at": datetime.now(timezone.utc),
                  "revoked_by": str(actor.get("_id") or ""),
                  "revoked_by_name": _actor_name(actor),
                  "revoke_reason": "Reissued"}})

    new_row = await register_link(
        company_id=company_id, kind=kind, code=fresh,
        target_type=doc.get("target_type"), target_id=owner.get(id_field),
        actor=actor, candidate_name=doc.get("candidate_name"),
        request_no=doc.get("request_no"), expires_at=doc.get("expires_at"))

    await audit(actor, AUDIT_LINK_REISSUED, ENTITY_LINK, link_id,
                f"replaced by {(new_row or {}).get('link_id')}", company_id)
    return {"reissued": True, "old_link_id": link_id, "link": new_row}
