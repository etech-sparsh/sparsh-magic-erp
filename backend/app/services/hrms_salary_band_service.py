"""HRMS > the standing salary-band master (internal recruitment track, Annexure C).

"Pre-define standard salary bands per role/grade with Finance annually, so individual
requisitions don't need a fresh budget discussion each time."

-- THE MASTER IS A CONVENIENCE. IT IS NEVER AN AUTHORITY. -----------------------------------
This is the one property that matters, and it is worth stating before anything else.

  * The BUDGET GATE reads this table and PRE-FILLS the band on the requisition.
  * The OFFER CHECK (`hrms_offer_service.assert_within_band`) reads the band STAMPED ON THE
    REQUISITION, and never this table.

Those two facts together are the whole design. A band edited in April must not retroactively
legalise an offer approved in March, and it must not retroactively criminalise one either.
The requisition carries what was authorised for it; the master carries what Finance currently
recommends. Collapsing the two would make every historical approval mean whatever the table
says today, which is the opposite of what an approval is for.

-- An override is allowed, and is stamped ---------------------------------------------------
The approver may type a different figure. That is not a hole -- Finance's standing band
cannot know about a scarce skill or a counter-offer. What the module insists on is that the
deviation is visible: `band_source` records `master` or `manual`, and a manual figure
requires a reason. "Why is this role's band different from the standard?" then has an answer
on the record rather than in somebody's memory.

-- Superseding rather than editing -----------------------------------------------------------
Changing a live band's figures marks the old one Superseded and writes a new row. A band is
a decision Finance took on a date; editing the numbers in place would rewrite what was agreed
last year, and the requisitions approved against it would cite a figure nobody ever set.

-- Who owns it -------------------------------------------------------------------------------
`salary_band.write` is Finance and the MD. HR reads. Annexure C makes this an annual Finance
agreement, so HR rewriting a band would make that agreement a suggestion.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SALARY_BAND_CREATED, AUDIT_SALARY_BAND_SUPERSEDED, AUDIT_SALARY_BAND_UPDATED,
    BAND_SOURCE_MANUAL, BAND_SOURCE_MASTER, COLL_DEPARTMENTS, COLL_DESIGNATIONS,
    COLL_SALARY_BANDS, ENTITY_SALARY_BAND, SalaryBandStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text

MAX_BAND_AMOUNT = 1_000_000_000


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
            or actor.get("email") or "Unknown")


def _validate_amount(value, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if amount < 0:
        raise HTTPException(status_code=422, detail=f"{label} cannot be negative.")
    if amount > MAX_BAND_AMOUNT:
        raise HTTPException(status_code=422, detail=f"{label} is implausibly large.")
    return amount


async def _resolve_position(company_id: str, department_id: str,
                            designation_id: str) -> tuple:
    """Check both masters exist and return their names for denormalisation.

    References, not free text -- the same rule requisitions follow, and for the same reason:
    a band filed against a department spelled two ways is two bands.
    """
    names = []
    for value, coll, label in ((department_id, COLL_DEPARTMENTS, "department"),
                               (designation_id, COLL_DESIGNATIONS, "designation")):
        if not value:
            raise HTTPException(status_code=422, detail=f"Choose a {label}.")
        try:
            oid = ObjectId(str(value))
        except (InvalidId, TypeError):
            raise HTTPException(status_code=422, detail=f"Invalid {label}.")
        row = await get_collection(coll).find_one(
            {"_id": oid, "company_id": str(company_id)}, {"name": 1})
        if not row:
            raise HTTPException(
                status_code=422, detail=f"That {label} does not exist for this company.")
        names.append(row.get("name"))
    return names[0], names[1]


def _grade_key(grade) -> Optional[str]:
    """Normalise a grade label so 'L3' and 'l3 ' are the same grade.

    Grades are a company's own vocabulary, so they stay free text -- but "the same grade"
    has to mean the same thing to the uniqueness check and to the pre-fill lookup, or a
    typo becomes a second active band nobody notices.
    """
    cleaned = clean_text(grade, limit=40)
    return cleaned.strip().upper() if cleaned else None


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_salary_bands(actor: dict, company_id: str, *, department_id: str = None,
                            designation_id: str = None, status: str = None,
                            limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if department_id:
        query["department_id"] = str(department_id)
    if designation_id:
        query["designation_id"] = str(designation_id)
    if status:
        query["status"] = status
    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_SALARY_BANDS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "salary_bands": out,
        "total": len(out),
        "active": sum(1 for r in out if r.get("status") == SalaryBandStatus.ACTIVE.value),
    }


async def get_salary_band(company_id: str, band_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_SALARY_BANDS).find_one(
        {"band_no": band_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def active_band_for(company_id: str, department_id: str, designation_id: str,
                          grade: str = None, *, on_date: str = None) -> Optional[dict]:
    """The band in force for a position on a date, or None.

    Matched on (department, designation, grade). A band recorded WITHOUT a grade is the
    position's default and answers a lookup that names one -- so a company that does not use
    grades is not obliged to invent them, and one that does still gets an answer for a grade
    nobody has banded yet. An exact grade match always wins over the default.

    Effective dates are honoured: a band that starts next quarter does not pre-fill today's
    approval, and one that ended last year does not either.
    """
    on_date = on_date or _today()
    rows = await get_collection(COLL_SALARY_BANDS).find({
        "company_id": str(company_id),
        "department_id": str(department_id),
        "designation_id": str(designation_id),
        "status": SalaryBandStatus.ACTIVE.value,
    }).to_list(100)

    wanted = _grade_key(grade)
    live = []
    for row in rows:
        start = row.get("effective_from")
        end = row.get("effective_to")
        if start and str(start) > on_date:
            continue
        if end and str(end) < on_date:
            continue
        live.append(row)

    exact = [r for r in live if _grade_key(r.get("grade")) == wanted] if wanted else []
    default = [r for r in live if not _grade_key(r.get("grade"))]
    # Most recently effective first, so a band published this year beats last year's if
    # both are somehow still active.
    chosen = sorted(exact or default,
                    key=lambda r: str(r.get("effective_from") or ""), reverse=True)
    return _out(chosen[0]) if chosen else None


async def prefill_for_requisition(company_id: str, req: dict) -> Optional[dict]:
    """The band the budget gate should pre-fill for this requisition, or None.

    Returned as a SUGGESTION, in the shape the approval body expects, so the UI can put the
    numbers in the boxes and the approver can still change them. Nothing here writes.
    """
    if not req:
        return None
    band = await active_band_for(
        company_id, req.get("department_id"), req.get("designation_id"),
        req.get("grade"))
    if not band:
        return None
    return {
        "band_no": band.get("band_no"),
        "approved_salary_band_min": band.get("min"),
        "approved_salary_band_max": band.get("max"),
        "currency": band.get("currency"),
        "grade": band.get("grade"),
        "source": BAND_SOURCE_MASTER,
        "hint": (f'Standing band for {band.get("designation_name")} '
                 f'({band.get("department_name")})'
                 + (f' grade {band.get("grade")}' if band.get("grade") else "")
                 + f', approved {band.get("approved_at_date") or band.get("effective_from")}. '
                 f"You may override it; an override needs a reason."),
    }


def resolve_band_decision(prefill: Optional[dict], payload: dict) -> dict:
    """Decide what the budget gate should stamp, and where the figures came from.

    Pure -- no DB, no clock -- so the rule is testable on its own and the requisition service
    stays a caller rather than a second place the rule lives.

    Three cases:
      * no standing band exists          -> manual, and no reason is demanded (there was
                                            nothing to deviate FROM)
      * the figures match the standing band -> `master`
      * they differ                      -> `manual`, and a reason is REQUIRED

    The reason requirement is the entire point of the field. An override with no explanation
    is indistinguishable from a typo, and the one thing an auditor asks about a
    non-standard band is why.
    """
    try:
        band_min = float(payload.get("approved_salary_band_min"))
        band_max = float(payload.get("approved_salary_band_max"))
    except (TypeError, ValueError):
        # The caller validates the figures themselves; this function only classifies them.
        return {"band_source": BAND_SOURCE_MANUAL, "band_no": None,
                "override_reason_required": False}

    if not prefill:
        return {"band_source": BAND_SOURCE_MANUAL, "band_no": None,
                "override_reason_required": False}

    matches = (float(prefill.get("approved_salary_band_min")) == band_min
               and float(prefill.get("approved_salary_band_max")) == band_max)
    if matches:
        return {"band_source": BAND_SOURCE_MASTER,
                "band_no": prefill.get("band_no"),
                "override_reason_required": False}
    return {"band_source": BAND_SOURCE_MANUAL,
            "band_no": prefill.get("band_no"),
            "override_reason_required": True,
            "standing_min": prefill.get("approved_salary_band_min"),
            "standing_max": prefill.get("approved_salary_band_max")}


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def create_salary_band(actor: dict, company_id: str, payload: dict) -> dict:
    """Publish a band for a position. An existing active band for it is SUPERSEDED."""
    department_id = str(payload.get("department_id") or "")
    designation_id = str(payload.get("designation_id") or "")
    department_name, designation_name = await _resolve_position(
        company_id, department_id, designation_id)

    band_min = _validate_amount(payload.get("min"), "The band minimum")
    band_max = _validate_amount(payload.get("max"), "The band maximum")
    if band_min > band_max:
        raise HTTPException(
            status_code=422,
            detail="The minimum of the band cannot exceed its maximum.")

    effective_from = payload.get("effective_from") or _today()
    if not is_iso_date(effective_from):
        raise HTTPException(
            status_code=422, detail="Effective-from must be a valid YYYY-MM-DD date.")
    effective_to = payload.get("effective_to")
    if effective_to:
        if not is_iso_date(effective_to):
            raise HTTPException(
                status_code=422, detail="Effective-to must be a valid YYYY-MM-DD date.")
        if effective_to < effective_from:
            raise HTTPException(
                status_code=422, detail="A band cannot end before it starts.")

    grade = clean_text(payload.get("grade"), limit=40)
    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_SALARY_BANDS)

    # Supersede the band this one replaces, rather than leaving two active for one position.
    # Two live answers to "what does this role pay" is the ambiguity the master exists to end.
    superseded = []
    for row in await coll.find({
            "company_id": str(company_id), "department_id": department_id,
            "designation_id": designation_id,
            "status": SalaryBandStatus.ACTIVE.value}).to_list(100):
        if _grade_key(row.get("grade")) != _grade_key(grade):
            continue
        await coll.update_one(
            {"_id": row["_id"]},
            {"$set": {"status": SalaryBandStatus.SUPERSEDED.value,
                      "superseded_at": now,
                      "superseded_by": str(actor.get("_id") or ""),
                      "updated_at": now}})
        superseded.append(row.get("band_no"))

    band_no = await next_business_id("salary_band", str(company_id), now.year)
    doc = {
        "band_no": band_no,
        "company_id": str(company_id),
        "department_id": department_id,
        "department_name": department_name,
        "designation_id": designation_id,
        "designation_name": designation_name,
        "grade": grade,
        "min": band_min,
        "max": band_max,
        "currency": (clean_text(payload.get("currency"), limit=8) or "INR").upper(),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": SalaryBandStatus.ACTIVE.value,
        # WHO agreed it, recorded on the row rather than inferred from the audit trail --
        # Annexure C makes this an annual agreement with Finance, and "who signed off this
        # year's bands" is the first question anybody asks of the table.
        "approved_by": str(actor.get("_id") or ""),
        "approved_by_name": _actor_name(actor),
        "approved_at": now,
        "approved_at_date": now.strftime("%Y-%m-%d"),
        "supersedes": superseded,
        "notes": clean_text(payload.get("notes"), limit=2000),
        "created_at": now,
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_SALARY_BAND_CREATED, ENTITY_SALARY_BAND, band_no,
                f"{designation_name} ({department_name})"
                + (f" grade {grade}" if grade else "")
                + f": {band_min:,.0f}-{band_max:,.0f}", company_id)
    for old in superseded:
        await audit(actor, AUDIT_SALARY_BAND_SUPERSEDED, ENTITY_SALARY_BAND, old,
                    f"replaced by {band_no}", company_id)
    return _out(doc)


async def update_salary_band(actor: dict, company_id: str, band_no: str,
                             payload: dict) -> dict:
    """Edit a band's descriptive fields, or retire it.

    The FIGURES are deliberately not editable here. A band is a decision Finance took on a
    date; changing the numbers in place would rewrite what was agreed and leave every
    requisition approved against it citing a figure nobody ever set. Publish a new band
    instead -- `create_salary_band` supersedes the old one and records the succession.
    """
    coll = get_collection(COLL_SALARY_BANDS)
    current = await coll.find_one({"band_no": band_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Salary band not found.")

    if payload.get("min") is not None or payload.get("max") is not None:
        raise HTTPException(
            status_code=409,
            detail=(f"{band_no}'s figures cannot be edited. Publish a new band for this "
                    f"position -- the old one is superseded automatically, and the "
                    f"requisitions approved against it keep citing what was actually "
                    f"agreed."))

    updates = {}
    if payload.get("grade") is not None:
        updates["grade"] = clean_text(payload["grade"], limit=40)
    if payload.get("currency") is not None:
        updates["currency"] = (clean_text(payload["currency"], limit=8) or "INR").upper()
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)
    for field in ("effective_from", "effective_to"):
        if payload.get(field) is not None:
            value = payload[field]
            if value and not is_iso_date(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field.replace('_', '-')} must be a valid YYYY-MM-DD date.")
            updates[field] = value or None
    if payload.get("status") is not None:
        raw = getattr(payload["status"], "value", payload["status"])
        try:
            status = SalaryBandStatus(raw)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Status must be one of: "
                        f"{', '.join(s.value for s in SalaryBandStatus)}."))
        updates["status"] = status.value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"band_no": band_no, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_SALARY_BAND_UPDATED, ENTITY_SALARY_BAND, band_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_salary_band(company_id, band_no)
