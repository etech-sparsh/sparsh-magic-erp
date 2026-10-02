"""HRMS > candidate communications (Annexure C, candidate experience).

Four commitments both SOPs make to applicants, and until this phase none of them had an
implementation:

    acknowledge every application            -> fires automatically on public intake
    keep candidates updated at each stage    -> a manual send, from a template
    communicate rejections                   -> fires automatically on the reject action
    a written offer summary before the offer -> a manual send, warned about at send time

-- ONE MAIL PATH ----------------------------------------------------------------------------
Everything goes out through `hrms_notify_service`. There is deliberately no second delivery
stack: the source HRMS had its own `hrms_email_outbox` plus its own SMTP wiring, and that
module's docstring already explains at length why this one does not. What is new here is the
TEMPLATE and the LOG, not the transport.

-- The log is append-only ---------------------------------------------------------------------
`hrms_comm_log` is written and never updated. "We told them on the 4th" is a fact about the
past; a mutable send record is a record you cannot rely on in the one conversation it exists
for. The only thing that ever touches a written row again is the retention purge, which
REDACTS the body and keeps the spine.

-- Automatic sends never break the thing that triggered them ------------------------------------
`fire_event` swallows every error, exactly as `audit()` and `notify_user()` do. An
acknowledgement email that cannot be sent must not fail somebody's job application. A send
that could not happen is recorded as `Skipped` with the reason, which is more useful than
either an exception or silence.

-- Seed scripts patch this out --------------------------------------------------------------
Same rule, same reason as `notify_user`: a shared database means real colleagues (and real
candidates) would otherwise be emailed about invented ones. `send_template` and `fire_event`
are the two entry points to patch.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_COMM_SENT, AUDIT_COMM_TEMPLATE_UPDATED, AUTO_COMM_EVENTS, COLL_CANDIDATES,
    MANUAL_COMM_TEMPLATES,
    COLL_COMM_LOG, COLL_COMM_TEMPLATES, COLL_OFFERS, COLL_REQUISITIONS,
    CONSENT_TEMPLATES, DEFAULT_COMM_TEMPLATES, ENTITY_CANDIDATE, ENTITY_COMM,
    RETENTION_YEARS, CommChannel, CommStatus, render_comm_body,  # noqa: F401
)
from app.services.hrms_audit_service import audit
from app.services.hrms_config_service import retention_years_for
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "system")


def _add_years(iso_date: str, years: int) -> str:
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


# =============================================================
# Templates
# =============================================================
async def list_templates(company_id: str, *, include_inactive: bool = False) -> list:
    """The company's templates, seeding the defaults on first read.

    Seeded on READ rather than by a migration, exactly as document types are: a company
    created later gets the same starting point without anybody remembering to run something,
    and a company that has edited its copy is never overwritten.

    The two CONSENT templates are seeded alongside the six message ones. They are not
    messages -- they are the equal-opportunity and data-use wording the public application
    form renders (SOP §11) -- and they live here for one specific reason: legal must be able
    to change that wording without a deploy.
    """
    coll = get_collection(COLL_COMM_TEMPLATES)
    if not await coll.count_documents({"company_id": str(company_id)}):
        await _seed_templates(company_id)

    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await coll.find(query).sort("key", 1).to_list(200)
    # Classified HERE, from the tables that decide it, so the screen cannot drift from the
    # wiring -- it did once, labelling interview_scheduled "manual" after it went automatic.
    automatic = set(AUTO_COMM_EVENTS.values())
    consent = {t[0] for t in CONSENT_TEMPLATES}
    return [{**_out(r),
             "automatic": r.get("key") in automatic,
             "manual": r.get("key") in MANUAL_COMM_TEMPLATES,
             "consent": r.get("key") in consent}
            for r in rows]


async def _seed_templates(company_id: str) -> None:
    now = datetime.now(timezone.utc)
    docs = [{
        "company_id": str(company_id),
        "key": key,
        "channel": channel.value,
        "subject": subject,
        "body": body,
        "variables": list(variables),
        "active": True,
        "seeded": True,      # so an operator can tell defaults from their own edits
        "created_at": now,
    } for key, channel, subject, body, variables
        in list(DEFAULT_COMM_TEMPLATES) + list(CONSENT_TEMPLATES)]
    try:
        await get_collection(COLL_COMM_TEMPLATES).insert_many(docs)
    except Exception as e:
        # A concurrent first read may have seeded already; the unique index makes that safe
        # to ignore rather than a reason to fail the caller's list.
        print(f"[WARN] HRMS comm-template seeding skipped for {company_id}: {e}")


async def get_template(company_id: str, key: str) -> Optional[dict]:
    """One template by key, seeding the defaults if this company is missing them.

    Two cases, and the second used to be missed. A company with NO templates gets the whole
    set. A company that was seeded before a new default shipped has templates but not this
    one -- seeding only on an empty collection left that company permanently without it, so
    every later addition to DEFAULT_COMM_TEMPLATES would silently never reach any existing
    company. The single-key backfill below is what makes adding a default safe.
    """
    coll = get_collection(COLL_COMM_TEMPLATES)
    doc = await coll.find_one({"company_id": str(company_id), "key": key})
    if not doc:
        if not await coll.count_documents({"company_id": str(company_id)}):
            await _seed_templates(company_id)
        else:
            await _seed_one(company_id, key)
        doc = await coll.find_one({"company_id": str(company_id), "key": key})
    return _out(doc) if doc else None


async def _seed_one(company_id: str, key: str) -> None:
    """Backfill a single default this company never received. No-op for an unknown key."""
    match = next((t for t in list(DEFAULT_COMM_TEMPLATES) + list(CONSENT_TEMPLATES)
                  if t[0] == key), None)
    if not match:
        return
    key, channel, subject, body, variables = match
    try:
        await get_collection(COLL_COMM_TEMPLATES).insert_one({
            "company_id": str(company_id), "key": key, "channel": channel.value,
            "subject": subject, "body": body, "variables": list(variables),
            "active": True, "seeded": True,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        # A concurrent read may have inserted it already; the unique index makes that safe.
        print(f"[WARN] HRMS comm-template backfill skipped for {company_id}/{key}: {e}")


async def update_template(actor: dict, company_id: str, key: str, payload: dict) -> dict:
    """Edit a template's wording, channel or active flag.

    The KEY is immutable and there is no create/delete: the six messages and the two consent
    statements are the ones the code fires, and a template nothing sends is a document, not
    a template. Editing the WORDING is the whole point -- especially of the consent
    statements, which is why this capability is separate from `comm.write`.
    """
    coll = get_collection(COLL_COMM_TEMPLATES)
    await list_templates(company_id, include_inactive=True)     # seed on first touch
    current = await coll.find_one({"company_id": str(company_id), "key": key})
    if not current:
        raise HTTPException(
            status_code=404,
            detail=(f"There is no '{key}' template. The templates are the ones this module "
                    f"sends; a new one would have nothing firing it."))

    updates = {}
    if payload.get("subject") is not None:
        subject = clean_text(payload["subject"], limit=200)
        if not subject:
            raise HTTPException(status_code=422, detail="A message needs a subject.")
        updates["subject"] = subject
    if payload.get("body") is not None:
        body = clean_text(payload["body"], limit=20000)
        if not body:
            raise HTTPException(status_code=422, detail="A message needs a body.")
        updates["body"] = body
    if payload.get("channel") is not None:
        raw = getattr(payload["channel"], "value", payload["channel"])
        try:
            updates["channel"] = CommChannel(raw).value
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Channel must be one of: "
                       f"{', '.join(c.value for c in CommChannel)}.")
    if payload.get("active") is not None:
        updates["active"] = bool(payload["active"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    updates["seeded"] = False       # it is the operator's copy now
    await coll.update_one({"company_id": str(company_id), "key": key}, {"$set": updates})
    await audit(actor, AUDIT_COMM_TEMPLATE_UPDATED, ENTITY_COMM, key,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_template(company_id, key)


# =============================================================
# The log
# =============================================================
async def list_log(actor: dict, company_id: str, *, uk: str = None,
                   request_no: str = None, template_key: str = None,
                   limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if uk:
        query["candidate_uk"] = uk
    if request_no:
        query["request_no"] = request_no
    if template_key:
        query["template_key"] = template_key
    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_COMM_LOG).find(query).sort(
        "sent_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {"communications": out, "total": len(out),
            "sent": sum(1 for r in out if r.get("status") == CommStatus.SENT.value)}


async def was_sent(company_id: str, uk: str, template_key: str) -> bool:
    """Whether a given message has ever gone to this candidate.

    Used by the internal offer send, which WARNS (never blocks) when no offer summary has
    gone out. A `Skipped` row does not count: the point of the warning is whether the
    candidate was actually told.
    """
    row = await get_collection(COLL_COMM_LOG).find_one({
        "company_id": str(company_id), "candidate_uk": uk,
        "template_key": template_key, "status": CommStatus.SENT.value})
    return bool(row)


# =============================================================
# Sending
# =============================================================
async def _derive_variables(company_id: str, candidate: dict) -> dict:
    """Everything the module can work out for itself.

    DERIVED, not accepted. A caller may add a covering note; it may not supply the CTC, the
    designation or the joining date, because a sender who can type those into a template can
    quote a candidate a salary the record does not hold.
    """
    req = {}
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"],
             "company_id": str(company_id)}) or {}
    # The LATEST offer, read through the cursor form rather than `find_one(sort=...)`. Both
    # work against Mongo; only this one is the shape every other read in the module uses.
    latest = await get_collection(COLL_OFFERS).find(
        {"company_id": str(company_id), "uk": candidate.get("uk")}).sort(
        "created_at", -1).limit(1).to_list(1)
    offer = latest[0] if latest else {}

    ctc = offer.get("ctc")
    return {
        "candidate_name": candidate.get("candidate_name"),
        "designation": (offer.get("designation") or req.get("designation_name")
                        or "the role"),
        "reference": candidate.get("uk"),
        "company": offer.get("company_name") or "",
        "stage": candidate.get("application_status"),
        "ctc": (f"{float(ctc):,.0f}" if ctc is not None else ""),
        "joining_date": offer.get("joining_date") or "",
        "location": offer.get("location") or req.get("work_location") or "",
        "note": "",
    }


async def send_template(actor: Optional[dict], company_id: str, uk: str,
                        template_key: str, *, variables: dict = None,
                        automatic: bool = False) -> dict:
    """Render one template and send it to one candidate, logging the result.

    Never raises for a delivery problem -- a failed send is a logged `Failed` row, because
    the caller is usually completing a business action (an application, a rejection) that
    must not be rolled back by an email. It DOES raise for a caller error: an unknown
    template or an unknown candidate is a bug, and a bug that silently logs "Skipped" is a
    bug nobody finds.
    """
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    template = await get_template(company_id, template_key)
    if not template:
        raise HTTPException(
            status_code=422, detail=f"There is no '{template_key}' template.")

    now = datetime.now(timezone.utc)
    row = {
        "company_id": str(company_id),
        "candidate_uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "request_no": candidate.get("request_no"),
        "template_key": template_key,
        "channel": template.get("channel"),
        "automatic": bool(automatic),
        "sent_at": now,
        "sent_by": str((actor or {}).get("_id") or "") or None,
        "sent_by_name": _actor_name(actor) if actor else "system",
        "recipient": candidate.get("can_email"),
        # SOP §13: a message about an application is part of that application's record, so
        # it inherits the candidate's own retention floor rather than a rule of its own.
        "retention_until": _add_years(
            now.strftime("%Y-%m-%d"),
            await retention_years_for(company_id, "candidate_unselected")),
        "created_at": now,
    }

    if not template.get("active"):
        row.update({"status": CommStatus.SKIPPED.value,
                    "reason": "The template is switched off for this company."})
        await _write_log(row)
        return _out(row)
    if not candidate.get("can_email"):
        row.update({"status": CommStatus.SKIPPED.value,
                    "reason": "No email address on the candidate record."})
        await _write_log(row)
        return _out(row)

    values = await _derive_variables(company_id, candidate)
    # Caller-supplied values fill the gaps the module cannot derive (a covering note, a
    # named stage) and never overwrite the derived facts.
    for key, value in (variables or {}).items():
        if key in values and values[key]:
            continue
        values[key] = clean_text(value, limit=2000) or ""

    row["subject"] = render_comm_body(template.get("subject") or "", values)
    row["body"] = render_comm_body(template.get("body") or "", values)

    try:
        from app.services.hrms_notify_service import notify_user
        # In-app AND email where the candidate is a user of the ERP; for an external
        # applicant only the email lands, which is the common case and is fine -- the
        # notify adapter swallows the in-app miss rather than failing the send.
        await notify_user(
            candidate.get("candidate_user_id") or "",
            row["subject"], row["body"],
            email=(template.get("channel") == CommChannel.EMAIL.value))
        row["status"] = CommStatus.SENT.value
    except Exception as e:                          # pragma: no cover - defensive
        row["status"] = CommStatus.FAILED.value
        row["reason"] = str(e)[:500]

    await _write_log(row)
    if row["status"] == CommStatus.SENT.value:
        await audit(actor, AUDIT_COMM_SENT, ENTITY_CANDIDATE, uk,
                    f"{template_key} ({row['channel']})", company_id)
    return _out(row)


async def _write_log(row: dict) -> None:
    """Append one row. Never raises -- a logging failure must not undo a sent message."""
    try:
        await get_collection(COLL_COMM_LOG).insert_one(dict(row))
    except Exception as e:
        print(f"[WARN] HRMS comm log write failed ({row.get('template_key')}): {e}")


async def fire_event(actor: Optional[dict], company_id: str, uk: str,
                     event: str, *, variables: dict = None) -> None:
    """Send whatever template an automatic event maps to. Swallows everything.

    The mapping is `AUTO_COMM_EVENTS`, declared as data so the wiring is readable in one
    place rather than inferred from the call sites. An event with no mapping does nothing,
    which is what lets a caller announce an event before anybody has decided to write to
    candidates about it.

    This is the function seed scripts patch out, alongside `notify_user`.
    """
    template_key = AUTO_COMM_EVENTS.get(event)
    if not template_key:
        return None
    try:
        # Returned so a caller can SAY what happened ("the candidate has been emailed" is a
        # claim, and a claim nobody checked is how a warning becomes a lie) -- while the
        # never-raise contract below is untouched.
        return await send_template(actor, company_id, uk, template_key,
                                   variables=variables, automatic=True)
    except Exception as e:
        # Deliberately swallowed. An acknowledgement that cannot be sent must never fail
        # somebody's job application, and a rejection email must never fail the rejection.
        print(f"[WARN] HRMS auto-communication '{event}' failed for {uk}: {e}")
        return None
