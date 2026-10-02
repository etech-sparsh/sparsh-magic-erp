"""HRMS > appointment letters and the public acknowledgement page (Phase 11-R, Item 3).

The document issued AFTER an offer is accepted, confirming joining terms.

-- Why this is not extra statuses on hrms_offers --------------------------------------
Confirmed with the business (PHASE_11R_REPORT §Decisions): the offer and the appointment
letter are two documents with two lifecycles. The offer PROPOSES terms and is accepted or
declined; the appointment letter CONFIRMS joining and is acknowledged. Folding them into one
row would mean a single `status` column trying to describe two artifacts at once -- exactly
the "two sources of truth in one field" problem Phase 5 removed from candidates, and it
would make "Accepted" ambiguous the moment a letter was also outstanding.

-- The candidate has ONE stage; the artifact has its own state machine -----------------
`AppStatus.APPOINTMENT_LETTER_SENT` is the candidate's pipeline stage. Generated / Sent /
Pending Acknowledgement / Acknowledged / Cancelled live on the LETTER. They are deliberately
not conflated: a candidate does not move backwards because a letter was reissued, and a
letter's acknowledgement is not a pipeline stage.

-- Optional by construction -------------------------------------------------------------
FORWARD_TRANSITIONS keeps the direct `Offer Accepted -> Pre-Onboarding` edge alongside the
new one, so a company that does not issue appointment letters is unaffected by this file
existing. ONBOARDABLE_STATUSES accepts both.

-- One letter per candidate --------------------------------------------------------------
Enforced by a unique index on `uk`, not just by a check here. Two appointment letters for
one person is a contradiction rather than a workflow; a wrong one is CANCELLED and the
record of it survives.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_APPOINTMENT_ACK, AUDIT_APPOINTMENT_CANCELLED, AUDIT_APPOINTMENT_EDITED,
    AUDIT_APPOINTMENT_GENERATED, AUDIT_APPOINTMENT_OPENED, AUDIT_APPOINTMENT_SENT,
    AUDIT_STAGE_CHANGED, COLL_APPOINTMENTS, COLL_CANDIDATES, COLL_EMPLOYEE_PROFILES,
    COLL_OFFERS,
    COLL_REQUISITIONS, DEFAULT_APPOINTMENT_BODY, EDITABLE_APPOINTMENT_STATUSES,
    ENTITY_APPOINTMENT, ENTITY_CANDIDATE, AppStatus, AppointmentStatus, Cap, HrmsRole,
    LinkKind, OfferStatus, can_transition, is_iso_date, render_appointment_body,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_config_service import employment_documents
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_public_guard import INVALID_LINK, clean_text, new_access_code

# The candidate stages an appointment letter may be raised from. The rule is "has already
# accepted an offer" -- Offer Accepted itself, and Pre-Onboarding, which is strictly LATER
# in the same forward chain and therefore implies it too. (Onboarding now opens
# automatically the instant an offer is accepted -- BA Functional Design §7.5 -- so a
# candidate no longer rests at Offer Accepted for any length of time; without
# Pre-Onboarding here, an appointment letter could never legally be issued at all.)
APPOINTABLE_STATUSES = {AppStatus.OFFER_ACCEPTED, AppStatus.PRE_ONBOARDING}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _out(doc: dict, *, include_ctc: bool = True) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    if not include_ctc:
        # Omitted, not nulled -- a viewer must not be able to confuse "you may not see this"
        # with "no salary was stated". Same rule Phase 8 applies to an offer's CTC.
        doc.pop("ctc", None)
        for entry in doc.get("history") or []:
            entry.pop("ctc", None)
    return doc


def _validate_money(value, *, label: str = "CTC") -> Optional[float]:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail=f"{label} must be greater than zero.")
    if amount > 1_000_000_000:
        raise HTTPException(status_code=422, detail=f"{label} is implausibly large.")
    return amount


def _validate_joining(value: str) -> str:
    if not value:
        raise HTTPException(status_code=422, detail="A joining date is required.")
    if not is_iso_date(value):
        raise HTTPException(
            status_code=422, detail="Joining date must be a valid date in YYYY-MM-DD format.")
    return value


# -------------------------------------------------------------
# Scoping
# -------------------------------------------------------------
async def _own_source_uk(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("source_uk")


async def _scope_filter(actor: dict, company_id: str) -> dict:
    """MANAGER narrowing — identical rule and identical fail-closed behaviour to
    hrms_candidate_service._scope_filter.

    An EMPLOYEE caller (self-service "download my Appointment Letter" from their own
    profile) is scoped to the ONE letter raised against their own hiring record — resolved
    via the `source_uk` an employee profile is stamped with at onboarding (Phase 9). Fails
    CLOSED, the same PIP/Letters/ATT-1 pattern: no linked candidate record, no letter."""
    role = hrms_role(actor)
    if role == HrmsRole.EMPLOYEE:
        own_uk = await _own_source_uk(actor, company_id)
        return {"uk": own_uk or "__none__"}
    if role != HrmsRole.MANAGER:
        return {}
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "created_by": str(actor.get("_id") or "")},
        {"request_no": 1}).to_list(2000)
    return {"request_no": {"$in": [r["request_no"] for r in rows]}}


async def _require_visible(actor: dict, company_id: str, appointment_no: str) -> dict:
    query = {"appointment_no": appointment_no, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_APPOINTMENTS).find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Appointment letter not found.")
    return doc


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_appointments(actor: dict, company_id: str, *, status: str = None,
                            uk: str = None, search: str = None, limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if uk:
        query["uk"] = uk
    # Scope is applied LAST and therefore wins over a caller-supplied `uk` — an EMPLOYEE
    # caller's self-scope (see _scope_filter) must narrow to their own record even if the
    # request also passed a `uk` (HR viewing a DIFFERENT employee's profile passes one too;
    # for an EMPLOYEE-role viewer that value is untrusted input, not a grant).
    query.update(await _scope_filter(actor, company_id))
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"appointment_no": {"$regex": safe, "$options": "i"}},
            {"candidate_name": {"$regex": safe, "$options": "i"}},
            {"designation": {"$regex": safe, "$options": "i"}},
        ]

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_APPOINTMENTS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)

    show_ctc = can(actor, Cap.EMPLOYEE_SALARY_READ)
    out = []
    for r in rows:
        item = _out(r, include_ctc=show_ctc)
        # The access code is a live credential — returned only while the link still works.
        if item.get("status") not in (AppointmentStatus.SENT.value,
                                      AppointmentStatus.PENDING_ACK.value):
            item.pop("access_code", None)
        out.append(item)

    return {
        "appointments": out,
        "total": len(out),
        "ctc_visible": show_ctc,
        "stats": {
            "generated": sum(1 for a in out if a["status"] == AppointmentStatus.GENERATED.value),
            "sent": sum(1 for a in out if a["status"] == AppointmentStatus.SENT.value),
            "pending_ack": sum(1 for a in out
                               if a["status"] == AppointmentStatus.PENDING_ACK.value),
            "acknowledged": sum(1 for a in out
                                if a["status"] == AppointmentStatus.ACKNOWLEDGED.value),
            "cancelled": sum(1 for a in out if a["status"] == AppointmentStatus.CANCELLED.value),
        },
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
    }


async def get_appointment(actor: dict, company_id: str, appointment_no: str) -> dict:
    doc = await _require_visible(actor, company_id, appointment_no)
    return _out(doc, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def eligible_candidates(actor: dict, company_id: str) -> list:
    """Candidates who may be issued an appointment letter.

    Offer Accepted, and without a live letter already. Cancelled letters do not block a
    fresh one -- cancelling is exactly how a wrong letter is corrected.
    """
    query = {"company_id": str(company_id),
             "application_status": {"$in": [s.value for s in APPOINTABLE_STATUSES]}}
    query.update(await _scope_filter(actor, company_id))
    rows = await get_collection(COLL_CANDIDATES).find(query).sort(
        "updated_at", -1).to_list(500)

    taken = {
        a["uk"] for a in await get_collection(COLL_APPOINTMENTS).find(
            {"company_id": str(company_id),
             "status": {"$ne": AppointmentStatus.CANCELLED.value}},
            {"uk": 1}).to_list(500)
    }

    out = []
    for r in rows:
        if r["uk"] in taken:
            continue
        offer = await get_collection(COLL_OFFERS).find_one(
            {"uk": r["uk"], "company_id": str(company_id),
             "status": OfferStatus.ACCEPTED.value})
        out.append({
            "uk": r["uk"],
            "candidate_name": r.get("candidate_name"),
            "request_no": r.get("request_no"),
            "offer_no": (offer or {}).get("offer_no"),
            "suggested_joining_date": (offer or {}).get("joining_date"),
            "suggested_designation": (offer or {}).get("designation"),
            "suggested_ctc": (offer or {}).get("ctc"),
        })
    return out


# -------------------------------------------------------------
# Generate / edit
# -------------------------------------------------------------
async def create_appointment(actor: dict, company_id: str, payload: dict) -> dict:
    """Draft an appointment letter for a candidate who has accepted their offer.

    Defaults every term from the ACCEPTED OFFER rather than asking the operator to retype
    them: the letter confirms what was agreed, so re-entering the figures by hand is a way
    to introduce a discrepancy between two documents that must say the same thing.
    """
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if candidate.get("application_status") not in {s.value for s in APPOINTABLE_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} is at '
                    f'"{candidate.get("application_status")}". An appointment letter can '
                    f'only be issued once the candidate has accepted their offer.'))

    existing = await get_collection(COLL_APPOINTMENTS).find_one({
        "company_id": str(company_id), "uk": uk,
        "status": {"$ne": AppointmentStatus.CANCELLED.value}})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} already has an appointment letter '
                    f'({existing["appointment_no"]}, {existing["status"]}).'))

    offer = await get_collection(COLL_OFFERS).find_one(
        {"uk": uk, "company_id": str(company_id), "status": OfferStatus.ACCEPTED.value}) or {}
    req = {}
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"], "company_id": str(company_id)}) or {}

    joining = _validate_joining(payload.get("joining_date") or offer.get("joining_date"))
    ctc = _validate_money(payload.get("ctc") if payload.get("ctc") is not None
                          else offer.get("ctc"))
    designation = (clean_text(payload.get("designation"), limit=140)
                   or offer.get("designation") or req.get("designation_name") or "the role")

    year = datetime.now(timezone.utc).year
    appointment_no = await next_business_id("appointment", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "appointment_no": appointment_no,
        "access_code": new_access_code(),
        "company_id": str(company_id),
        "uk": uk,
        "request_no": candidate.get("request_no"),
        "offer_no": offer.get("offer_no"),
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "designation": designation,
        "department": (clean_text(payload.get("department"), limit=140)
                       or req.get("department_name")),
        "company_name": (clean_text(payload.get("company_name"), limit=140)
                         or offer.get("company_name") or ""),
        "location": (clean_text(payload.get("location"), limit=160)
                     or offer.get("location") or req.get("work_location")),
        "ctc": ctc,
        "joining_date": joining,
        "content": clean_text(payload.get("content"), limit=20000) or DEFAULT_APPOINTMENT_BODY,
        "status": AppointmentStatus.GENERATED.value,
        "version": 1,
        "history": [],
        "signature": clean_text(payload.get("signature"), limit=120),
        "generated_by": str(actor.get("_id") or ""),
        "generated_by_name": _actor_name(actor),
        "generated_at": now,
        "sent_by": None, "sent_at": None,
        "acknowledged_at": None, "acknowledgement_signature": None,
        # §7.5 Stage 7 -- the employment documents signed alongside the letter. Snapshotted
        # at generation rather than read live, so changing the company catalogue later
        # cannot retroactively add an obligation to a letter already in somebody's hands.
        "document_acks": [
            {"doc": label, "required": bool(required),
             "acknowledged_at": None, "signature": None}
            for label, required in (await employment_documents(company_id)).items()
        ],
        "created_at": now,
    }
    await get_collection(COLL_APPOINTMENTS).insert_one(dict(doc))

    await audit(actor, AUDIT_APPOINTMENT_GENERATED, ENTITY_APPOINTMENT, appointment_no,
                f"{designation} for {candidate.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_APPOINTMENT_GENERATED, ENTITY_CANDIDATE, uk,
                appointment_no, company_id)

    return _out(doc, include_ctc=can(actor, Cap.EMPLOYEE_SALARY_READ))


async def update_appointment(actor: dict, company_id: str, appointment_no: str,
                             payload: dict) -> dict:
    """Edit a GENERATED letter. Archives the previous body and bumps the version.

    Refused once sent, for the same reason an offer is: the document the candidate is
    reading must not change underneath them.
    """
    current = await _require_visible(actor, company_id, appointment_no)
    if current["status"] not in {s.value for s in EDITABLE_APPOINTMENT_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail=(f'This appointment letter is "{current["status"]}" and can no longer be '
                    f'edited. Cancel it and generate a new one if the terms have changed.'))

    updates = {}
    if payload.get("joining_date") is not None:
        updates["joining_date"] = _validate_joining(payload["joining_date"])
    if payload.get("ctc") is not None:
        updates["ctc"] = _validate_money(payload["ctc"])
    for field, limit in (("designation", 140), ("department", 140), ("company_name", 140),
                         ("location", 160), ("signature", 120)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("content") is not None:
        body = clean_text(payload["content"], limit=20000)
        if not body:
            raise HTTPException(
                status_code=422, detail="The appointment letter cannot be empty.")
        updates["content"] = body

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    now = datetime.now(timezone.utc)
    history = list(current.get("history") or [])
    history.append({
        "version": current.get("version", 1),
        "content": current.get("content"),
        "ctc": current.get("ctc"),
        "joining_date": current.get("joining_date"),
        "edited_at": now,
        "edited_by": _actor_name(actor),
    })
    updates["history"] = history
    updates["version"] = int(current.get("version", 1)) + 1
    updates["updated_at"] = now

    await get_collection(COLL_APPOINTMENTS).update_one(
        {"appointment_no": appointment_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_APPOINTMENT_EDITED, ENTITY_APPOINTMENT, appointment_no,
                f"v{updates['version']}: " + ", ".join(
                    sorted(k for k in updates
                           if k not in ("history", "version", "updated_at"))),
                company_id)
    return await get_appointment(actor, company_id, appointment_no)


# -------------------------------------------------------------
# Send / cancel
# -------------------------------------------------------------
async def send_appointment(actor: dict, company_id: str, appointment_no: str,
                           payload: dict) -> dict:
    """Issue the letter to the candidate.

    Four things happen, in this order, and the order is deliberate:
      1. compare-and-swap the letter to Sent (two clicks cannot both land),
      2. move the candidate to `Appointment Letter Sent` if the graph allows it,
      3. register the public link (Item 1),
      4. file the letter as a document on the candidate (Item 2).
    Steps 3 and 4 are bookkeeping and never raise into the caller, so neither can undo a
    letter that has already gone out.
    """
    current = await _require_visible(actor, company_id, appointment_no)
    if current["status"] != AppointmentStatus.GENERATED.value:
        raise HTTPException(
            status_code=409,
            detail=f'This appointment letter is already "{current["status"]}".')

    signature = clean_text(payload.get("signature"), limit=120) or current.get("signature")
    if not signature:
        # The letter confirms an employment commitment; it must be attributable.
        raise HTTPException(
            status_code=422,
            detail="Type the authorised signatory's name to send this appointment letter.")

    now = datetime.now(timezone.utc)
    result = await get_collection(COLL_APPOINTMENTS).update_one(
        {"appointment_no": appointment_no, "company_id": str(company_id),
         "status": AppointmentStatus.GENERATED.value},
        {"$set": {"status": AppointmentStatus.SENT.value, "signature": signature,
                  "sent_at": now, "sent_by": str(actor.get("_id") or ""),
                  "sent_by_name": _actor_name(actor), "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="This appointment letter has already been sent.")

    # -- the candidate's pipeline stage --
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": current["uk"], "company_id": str(company_id)})
    if candidate:
        was = candidate.get("application_status")
        if can_transition(was, AppStatus.APPOINTMENT_LETTER_SENT.value):
            await get_collection(COLL_CANDIDATES).update_one(
                {"uk": current["uk"], "company_id": str(company_id)},
                {"$set": {"application_status": AppStatus.APPOINTMENT_LETTER_SENT.value,
                          "updated_at": now}})
            await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, current["uk"],
                        f"{was} -> {AppStatus.APPOINTMENT_LETTER_SENT.value}", company_id)

    # -- Item 1: the registry --
    from app.services.hrms_link_service import register_link
    await register_link(
        company_id=company_id, kind=LinkKind.APPOINTMENT, code=current["access_code"],
        target_type="candidate", target_id=appointment_no, actor=actor,
        candidate_name=current.get("candidate_name"), request_no=current.get("request_no"))

    # -- Item 2: file the letter against the candidate --
    # This is the proof that Items 2 and 3 are one system rather than two: the appointment
    # letter appears in the Document Center like any other paper, without anybody uploading
    # it by hand.
    await _file_letter_document(actor, company_id, current, status_verified=False)

    await audit(actor, AUDIT_APPOINTMENT_SENT, ENTITY_APPOINTMENT, appointment_no,
                f"sent to {current.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_APPOINTMENT_SENT, ENTITY_CANDIDATE, current["uk"],
                appointment_no, company_id)

    await notify_hrms_role(
        company_id, ["HR"], f"Appointment letter sent: {current.get('candidate_name')}",
        f"{appointment_no} has been issued, joining {current.get('joining_date')}.",
        kind="success", link="/hrms/appointments")

    return await get_appointment(actor, company_id, appointment_no)


async def cancel_appointment(actor: dict, company_id: str, appointment_no: str,
                             payload: dict) -> dict:
    """Withdraw an appointment letter.

    Marked Cancelled, never deleted: an issued letter is part of the hiring record. An
    ACKNOWLEDGED letter cannot be cancelled -- the candidate has already acted on it, and
    retracting it silently would rewrite a record they relied on.
    """
    current = await _require_visible(actor, company_id, appointment_no)
    if current["status"] == AppointmentStatus.ACKNOWLEDGED.value:
        raise HTTPException(
            status_code=409,
            detail=("This letter has already been acknowledged by the candidate and cannot "
                    "be cancelled. Raise the change with them directly."))
    if current["status"] == AppointmentStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This letter is already cancelled.")

    now = datetime.now(timezone.utc)
    reason = clean_text(payload.get("reason"), limit=2000)
    await get_collection(COLL_APPOINTMENTS).update_one(
        {"appointment_no": appointment_no, "company_id": str(company_id)},
        {"$set": {"status": AppointmentStatus.CANCELLED.value, "cancelled_at": now,
                  "cancel_reason": reason, "updated_at": now}})

    # Kill the public link too — a cancelled letter that still opens is not cancelled.
    try:
        from app.models.hrms import COLL_LINKS, LinkStatus
        await get_collection(COLL_LINKS).update_one(
            {"code": current.get("access_code")},
            {"$set": {"status": LinkStatus.REVOKED.value, "revoked_at": now,
                      "revoked_by": str(actor.get("_id") or ""),
                      "revoke_reason": "Appointment letter cancelled"}})
    except Exception as e:
        print(f"[WARN] HRMS appointment link revoke failed ({appointment_no}): {e}")

    await audit(actor, AUDIT_APPOINTMENT_CANCELLED, ENTITY_APPOINTMENT, appointment_no,
                reason, company_id)
    return {"cancelled": True, "appointment_no": appointment_no}


async def _file_letter_document(actor, company_id: str, appointment: dict,
                                *, status_verified: bool) -> None:
    """File the appointment letter in the document register. Never raises.

    The letter has no uploaded FILE — it is rendered from `content` on demand — so the
    document row carries the appointment number as its reference and `source: "system"`.
    Fabricating an S3 object for a document the system generates would be storage with no
    purpose and a second copy to drift.
    """
    try:
        from app.services.hrms_document_service import file_system_document
        await file_system_document(
            actor, company_id,
            owner_type="candidate",
            owner_id=appointment.get("uk"),
            owner_name=appointment.get("candidate_name"),
            type_name="Appointment Letter",
            reference=appointment.get("appointment_no"),
            request_no=appointment.get("request_no"),
            verified=status_verified,
        )
    except Exception as e:
        print(f"[WARN] HRMS appointment document filing failed "
              f"({appointment.get('appointment_no')}): {e}")


# -------------------------------------------------------------
# Public side (NO authentication)
# -------------------------------------------------------------
async def get_public_appointment(code: str) -> dict:
    """The appointment letter behind a candidate's link."""
    doc = await get_collection(COLL_APPOINTMENTS).find_one({"access_code": code})
    # A GENERATED letter is invisible: it has not been issued, so as far as the world is
    # concerned it does not exist. Same opaque 404 as an unknown code.
    if not doc or doc["status"] == AppointmentStatus.GENERATED.value:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc["status"] == AppointmentStatus.CANCELLED.value:
        raise HTTPException(
            status_code=410,
            detail="This appointment letter has been withdrawn. Please contact the HR team.")

    # First sight moves Sent -> Pending Acknowledgement, which is how HR tells "not opened"
    # from "opened and not signed". Conditional on the current status so a re-read by an
    # already-acknowledged candidate cannot walk the letter backwards.
    if doc["status"] == AppointmentStatus.SENT.value:
        now = datetime.now(timezone.utc)
        await get_collection(COLL_APPOINTMENTS).update_one(
            {"access_code": code, "status": AppointmentStatus.SENT.value},
            {"$set": {"status": AppointmentStatus.PENDING_ACK.value,
                      "first_opened_at": now, "updated_at": now}})
        await audit(None, AUDIT_APPOINTMENT_OPENED, ENTITY_APPOINTMENT,
                    doc["appointment_no"], doc.get("candidate_name"), doc.get("company_id"))
        doc = await get_collection(COLL_APPOINTMENTS).find_one({"access_code": code})

    body = render_appointment_body(
        doc.get("content") or "",
        designation=doc.get("designation"), company=doc.get("company_name"),
        ctc=f"{doc.get('ctc'):,.0f}" if doc.get("ctc") is not None else "",
        joining_date=doc.get("joining_date"), location=doc.get("location"))

    # Only what the candidate needs. No company_id, no requisition number, no internal ids.
    return {
        "ok": True,
        "already_acknowledged": doc["status"] == AppointmentStatus.ACKNOWLEDGED.value,
        "status": doc["status"],
        "appointment_no": doc["appointment_no"],
        "candidate_name": doc.get("candidate_name"),
        "designation": doc.get("designation"),
        "department": doc.get("department"),
        "company_name": doc.get("company_name"),
        "location": doc.get("location"),
        "ctc": doc.get("ctc"),
        "joining_date": doc.get("joining_date"),
        "content": body,
        "signature": doc.get("signature"),
        "sent_at": doc.get("sent_at"),
        "acknowledged_at": doc.get("acknowledged_at"),
        # §7.5 Stage 7 -- NDA, Code of Conduct and the required policies, each signed in
        # its own right. Sent so the page can walk the joiner through them in order rather
        # than asking for one signature that silently stands for five documents.
        "documents": [
            {"doc": d.get("doc"), "required": bool(d.get("required")),
             "acknowledged_at": d.get("acknowledged_at")}
            for d in (doc.get("document_acks") or [])
        ],
    }


async def _tick_policy_ack(company_id: str, uk: str) -> None:
    """Mark "Policies acknowledged" on the joiner's open onboarding case.

    Driven by the acknowledgement itself for the same reason `bg_cleared` and
    `documents_verified` are: a checklist must not assert something the data does not
    support, and the reverse -- a signed policy nobody ticked -- is just as wrong.
    """
    from app.models.hrms import COLL_ONBOARDING, OnboardStatus
    coll = get_collection(COLL_ONBOARDING)
    case = await coll.find_one({"company_id": str(company_id), "uk": uk,
                                "status": {"$ne": OnboardStatus.COMPLETED.value}})
    if not case:
        return
    now = datetime.now(timezone.utc)
    checklist = [
        {**i, "done": True, "done_at": now, "done_by": "Signed by the employee"}
        if i.get("key") == "policy_ack" else i
        for i in (case.get("checklist") or [])
    ]
    await coll.update_one({"onb_no": case["onb_no"], "company_id": str(company_id)},
                          {"$set": {"checklist": checklist, "updated_at": now}})


async def acknowledge_appointment(code: str, payload: dict) -> dict:
    """Record the candidate's acknowledgement.

    A typed signature is required and the write is a compare-and-swap on the two states an
    unacknowledged live letter can be in, so a double submit answers 409 rather than
    overwriting the first signature.
    """
    doc = await get_collection(COLL_APPOINTMENTS).find_one({"access_code": code})
    if not doc or doc["status"] == AppointmentStatus.GENERATED.value:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc["status"] == AppointmentStatus.ACKNOWLEDGED.value:
        raise HTTPException(
            status_code=409, detail="You have already acknowledged this letter.")
    if doc["status"] == AppointmentStatus.CANCELLED.value:
        raise HTTPException(
            status_code=410,
            detail="This appointment letter has been withdrawn. Please contact the HR team.")

    signature = clean_text(payload.get("signature"), limit=120)
    if not signature:
        raise HTTPException(
            status_code=422, detail="Type your full name to acknowledge this letter.")

    # §7.5 Stage 7 -- "Appointment Letter -> NDA -> Code of Conduct -> Policy
    # Acknowledgement -> Completion". The letter is only acknowledged once each required
    # document has been, so one signature cannot silently stand for all of them.
    agreed = {clean_text(d, limit=140) for d in (payload.get("documents") or [])
              if clean_text(d, limit=140)}
    catalogue = doc.get("document_acks") or []
    outstanding = [d["doc"] for d in catalogue
                   if d.get("required") and not d.get("acknowledged_at")
                   and d["doc"] not in agreed]
    if outstanding:
        raise HTTPException(
            status_code=422,
            detail=("Please read and accept each document before signing: "
                    + ", ".join(outstanding) + "."))

    now = datetime.now(timezone.utc)
    acks = [
        {**d,
         "acknowledged_at": d.get("acknowledged_at") or (now if d["doc"] in agreed else None),
         "signature": d.get("signature") or (signature if d["doc"] in agreed else None)}
        for d in catalogue
    ]
    result = await get_collection(COLL_APPOINTMENTS).update_one(
        {"access_code": code,
         "status": {"$in": [AppointmentStatus.SENT.value,
                            AppointmentStatus.PENDING_ACK.value]}},
        {"$set": {"status": AppointmentStatus.ACKNOWLEDGED.value,
                  "acknowledged_at": now,
                  "document_acks": acks,
                  "acknowledgement_signature": signature,
                  "acknowledgement_note": clean_text(payload.get("note"), limit=2000),
                  "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="You have already acknowledged this letter.")

    company_id = doc.get("company_id")
    await audit(None, AUDIT_APPOINTMENT_ACK, ENTITY_APPOINTMENT, doc["appointment_no"],
                doc.get("candidate_name"), company_id)
    await audit(None, AUDIT_APPOINTMENT_ACK, ENTITY_CANDIDATE, doc["uk"],
                doc["appointment_no"], company_id)

    # Item 2: the filed document is now proven — mark it Verified.
    fresh = await get_collection(COLL_APPOINTMENTS).find_one({"access_code": code})
    await _file_letter_document(None, company_id, fresh or doc, status_verified=True)

    # §7.5 Stage 7 -- the joiner has now signed the policies, so the onboarding
    # checklist item that claims exactly that follows the act rather than waiting for HR
    # to remember to tick it. Best-effort: the signature is already recorded, and a
    # checklist that could not be updated must not undo it.
    try:
        await _tick_policy_ack(company_id, doc["uk"])
    except Exception as e:                          # pragma: no cover - defensive
        print(f"[WARN] policy_ack not ticked for {doc.get('uk')}: {e}")

    await notify_hrms_role(
        company_id, ["HR"],
        f"Appointment letter acknowledged: {doc.get('candidate_name')}",
        f"{doc['appointment_no']} was acknowledged. They are due to join "
        f"{doc.get('joining_date')}.",
        kind="success", link="/hrms/appointments", email=True)
    if doc.get("generated_by"):
        await notify_user(
            doc["generated_by"],
            f"Appointment letter acknowledged: {doc.get('candidate_name')}",
            f"{doc['appointment_no']} was acknowledged.", link="/hrms/appointments")

    return {
        "ok": True,
        "status": AppointmentStatus.ACKNOWLEDGED.value,
        "message": ("Thank you — your acknowledgement has been recorded. The HR team will "
                    "be in touch about your joining formalities."),
    }
