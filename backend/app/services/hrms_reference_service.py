"""HRMS > reference checks (internal recruitment track).

Somebody who has worked with this person, asked before the offer goes out.

-- Why it is MANDATORY here and optional on the client track -------------------------------
SOP §6: "Reference check completed before offer for ALL roles (not limited to managerial+,
since Sparsh Magic bears the direct employment risk internally)."

That sentence is the whole design. On the client track the client employs the person and
carries the risk of a bad hire; the agency's job is to route the CV. Here Sparsh Magic
employs them, so the check is a control on its own exposure rather than a service to
somebody else -- and a control you can skip when busy is not one.

-- "Completed" is not the same as "cleared" -------------------------------------------------
An `Unable to Verify` reference is finished WORK. The referee was called, the call happened,
the outcome was recorded. It is not a CLEARANCE: nobody vouched for the candidate. So it does
not open the offer gate. Proceeding anyway is allowed, but it takes a logged exception --
which is exactly the trail SOP §12 asks for, and exactly what "we couldn't verify but hired
them anyway" should leave behind.

-- Several referees per candidate -------------------------------------------------------
Deliberately not unique on (company, candidate): asking two referees is normal, and the
second one is often the useful one. The gate asks whether ANY reference clears, so a negative
first call followed by a positive second is a real and answerable situation -- the record
keeps both.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_REFERENCE_RECORDED, AUDIT_REFERENCE_UPDATED, COLL_CANDIDATES,
    COLL_REFERENCE_CHECKS, COLL_REQUISITIONS, ENTITY_REFERENCE, PHONE_RE,
    REFERENCE_CLEARS_OFFER, RETENTION_YEARS, ReferenceMode, ReferenceOutcome,
    REQUISITION_TRACK_INTERNAL, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_config_service import retention_years_for
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _retention_until(checked_on: str, years: int = None) -> str:
    """SOP §13: reference reports are kept for employment + 3 years.

    Employment end is unknowable at the time of the check, so the date stored here is the
    FLOOR -- three years from the check itself. It is recomputed against the leaving date if
    and when there is one. Storing a floor beats storing nothing: a record with no retention
    date is one nobody can defend keeping or deleting.

    NOTHING IS EVER PURGED BY THIS MODULE. The date is computed, stored and reported on.
    """
    try:
        year, month, day = (int(p) for p in (checked_on or _today()).split("-"))
    except (ValueError, AttributeError):
        year, month, day = (int(p) for p in _today().split("-"))
    # 29 February plus N years is not a date in a common year; the 28th is the honest floor.
    if month == 2 and day == 29:
        day = 28
    keep = RETENTION_YEARS["reference"] if years is None else int(years)
    return f"{year + keep:04d}-{month:02d}-{day:02d}"


def _validate(payload: dict, *, partial: bool) -> dict:
    out = {}

    if not partial or payload.get("referee_name") is not None:
        name = clean_text(payload.get("referee_name"), limit=140)
        if not name:
            raise HTTPException(
                status_code=422,
                detail="Record who the reference was taken from. An anonymous reference "
                       "check is not a check.")
        out["referee_name"] = name

    for field, limit in (("referee_designation", 140), ("referee_organisation", 160),
                         ("relationship", 120), ("responses", 5000), ("remarks", 2000)):
        if not partial or payload.get(field) is not None:
            out[field] = clean_text(payload.get(field), limit=limit)

    if not partial or payload.get("referee_contact") is not None:
        contact = clean_text(payload.get("referee_contact"), limit=180)
        # A contact may be a phone number OR an email, so only an obviously-malformed phone
        # is refused. Being strict here would block "priya@acme.com, ext 4021".
        if contact and contact.replace(" ", "").isdigit() and not PHONE_RE.match(contact):
            raise HTTPException(
                status_code=422, detail="Enter a valid contact number for the referee.")
        out["referee_contact"] = contact

    if not partial or payload.get("mode") is not None:
        raw = getattr(payload.get("mode"), "value", payload.get("mode"))
        try:
            out["mode"] = ReferenceMode(raw or ReferenceMode.PHONE.value).value
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Mode must be one of: {', '.join(m.value for m in ReferenceMode)}.")

    if not partial or payload.get("outcome") is not None:
        raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
        try:
            outcome = ReferenceOutcome(raw or ReferenceOutcome.POSITIVE.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Outcome must be one of: "
                        f"{', '.join(o.value for o in ReferenceOutcome)}."))
        out["outcome"] = outcome.value
        # A negative or unverifiable reference is a finding, and a finding with no note is
        # not actionable by whoever reads it next.
        if outcome is not ReferenceOutcome.POSITIVE:
            note = clean_text(payload.get("remarks"), limit=2000) or out.get("remarks")
            if not note:
                raise HTTPException(
                    status_code=422,
                    detail=(f'Record what was said. A "{outcome.value}" reference with no '
                            f"note cannot be acted on."))

    if not partial or payload.get("checked_on") is not None:
        checked_on = payload.get("checked_on") or _today()
        if not is_iso_date(checked_on):
            raise HTTPException(
                status_code=422,
                detail="The check date must be a valid date in YYYY-MM-DD format.")
        if checked_on > _today():
            raise HTTPException(
                status_code=422, detail="A reference check cannot be dated in the future.")
        out["checked_on"] = checked_on

    return out


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_reference_checks(actor: dict, company_id: str, *, uk: str = None,
                                request_no: str = None, outcome: str = None,
                                limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if uk:
        query["uk"] = uk
    if request_no:
        query["request_no"] = request_no
    if outcome:
        query["outcome"] = outcome
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_REFERENCE_CHECKS).find(query).sort(
        "created_at", -1).to_list(limit)
    return {"reference_checks": [_out(r) for r in rows], "total": len(rows)}


async def get_reference_check(company_id: str, ref_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_REFERENCE_CHECKS).find_one(
        {"ref_no": ref_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def clearing_reference(company_id: str, uk: str) -> Optional[dict]:
    """The reference that CLEARS this candidate for an offer, if there is one.

    Reads REFERENCE_CLEARS_OFFER rather than testing for a literal outcome, so widening what
    counts as a clearance is a one-line change to the model and not a hunt through services.
    """
    rows = await get_collection(COLL_REFERENCE_CHECKS).find(
        {"company_id": str(company_id), "uk": uk}).to_list(50)
    for row in rows:
        if row.get("outcome") in REFERENCE_CLEARS_OFFER:
            return _out(row)
    return None


async def assert_reference_cleared(company_id: str, candidate: dict, req: dict) -> None:
    """The offer gate. Internal track only; silent on the client track.

    Raises 409 unless the candidate has a clearing reference OR an approved exception waives
    it. There is deliberately no override parameter -- see hrms_exception_service for why.
    """
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return

    uk = candidate.get("uk")
    if await clearing_reference(company_id, uk):
        return

    from app.services.hrms_exception_service import approved_exception_for
    waiver = await approved_exception_for(
        company_id, "reference_check", req.get("request_no"), uk)
    if waiver:
        return

    rows = await get_collection(COLL_REFERENCE_CHECKS).find(
        {"company_id": str(company_id), "uk": uk}).to_list(50)
    if rows:
        outcomes = ", ".join(sorted({r.get("outcome") or "?" for r in rows}))
        detail = (f'{candidate.get("candidate_name")} has {len(rows)} reference check(s) '
                  f"on record ({outcomes}), none of which is a clearance. Record a "
                  f"positive reference, or log an approved exception to waive it.")
    else:
        detail = (f'No reference check has been completed for '
                  f'{candidate.get("candidate_name")}. On internal roles the reference '
                  f"check is required before an offer -- Sparsh Magic carries the "
                  f"employment risk directly. Log an approved exception to waive it.")
    raise HTTPException(status_code=409, detail=detail)


async def _notify_if_not_cleared(company_id: str, doc: dict) -> None:
    """Warn HR when a recorded reference is not a clearance (Phase INT-9, spec §38).

    A Positive reference is silent: the recorder is HR and the gate opens without
    ceremony. A Negative or Unable-to-Verify one is what makes an offer REFUSE later, and
    that refusal should never be the first anybody else on the HR team hears of it.
    In-app only -- it is a heads-up about work already recorded, not a decision awaited.
    """
    if (doc or {}).get("outcome") in REFERENCE_CLEARS_OFFER:
        return
    # INTERNAL track only, resolved the way the offer gate resolves it (an absent track
    # reads as client). A reference on a client-track candidate is legal and OPTIONAL --
    # no internal offer gate applies to them, and the waiver this message recommends
    # would be refused outright by raise_exception. Warning HR about a consequence that
    # does not exist, with a remedy the system rejects, is worse than silence.
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": (doc or {}).get("request_no"), "company_id": str(company_id)},
        {"requisition_track": 1})
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return
    from app.services.hrms_notify_service import notify_hrms_role
    name = doc.get("candidate_name") or doc.get("uk")
    await notify_hrms_role(
        company_id, ["HR"],
        f'Reference for {name} did not clear',
        f'{doc.get("ref_no")} was recorded as "{doc.get("outcome")}". An internal offer '
        f"for {name} will need a positive reference from another referee, or an approved "
        f'"Reference Check Waived" exception.',
        kind="warning", link="/hrms/reference-checks", email=False)


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def create_reference_check(actor: dict, company_id: str, payload: dict) -> dict:
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    clean = _validate(payload, partial=False)
    year = datetime.now(timezone.utc).year
    ref_no = await next_business_id("reference", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "ref_no": ref_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        # Carried so the single analytics scope filter reaches this collection too.
        "request_no": candidate.get("request_no"),
        "conducted_by": str(actor.get("_id") or ""),
        "conducted_by_name": actor.get("full_name") or actor.get("email"),
        "retention_until": _retention_until(
            clean.get("checked_on"),
            await retention_years_for(company_id, "reference")),
        "created_at": now,
        **clean,
    }
    await get_collection(COLL_REFERENCE_CHECKS).insert_one(dict(doc))
    await audit(actor, AUDIT_REFERENCE_RECORDED, ENTITY_REFERENCE, ref_no,
                f'{clean.get("outcome")} for {uk} from {clean.get("referee_name")}',
                company_id)
    await _notify_if_not_cleared(company_id, doc)
    return _out(doc)


async def update_reference_check(actor: dict, company_id: str, ref_no: str,
                                 payload: dict) -> dict:
    coll = get_collection(COLL_REFERENCE_CHECKS)
    current = await coll.find_one({"ref_no": ref_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Reference check not found.")

    # Read BEFORE the write, for the same reason the telephonic service does.
    previous_outcome = current.get("outcome")

    # Cross-field rules are checked against the MERGED record: flipping the outcome to
    # Negative in an edit must demand a note just as it does on creation.
    merged = {**current, **{k: v for k, v in (payload or {}).items() if v is not None}}
    clean = _validate({**merged, **payload}, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    if "checked_on" in clean:
        clean["retention_until"] = _retention_until(
            clean["checked_on"], await retention_years_for(company_id, "reference"))
    clean["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"ref_no": ref_no, "company_id": str(company_id)},
                          {"$set": clean})
    await audit(actor, AUDIT_REFERENCE_UPDATED, ENTITY_REFERENCE, ref_no,
                ", ".join(sorted(k for k in clean if k != "updated_at")), company_id)

    # ── Phase INT-9 ── fired only when the OUTCOME moved to a non-clearing one, so
    # editing remarks on an already-negative reference does not nag anybody twice.
    # `previous_outcome` was captured before the write -- see the telephonic service for
    # why reading `current` afterwards is the wrong side of the driver's copy semantics.
    if ("outcome" in clean and clean["outcome"] != previous_outcome):
        await _notify_if_not_cleared(company_id, {**current, **clean})
    return await get_reference_check(company_id, ref_no)
