"""Client Hiring, step 2b -- the job posting, and the applications that arrive against it.

An approved Position Scorecard is a benchmark. It is not an advert, and nobody can apply
to it. This module is what turns one into the other: Sparsh writes the posting against the
agreed scorecard, publishes it, and applications arrive as ordinary client candidates
against the same requisition the scorecard belongs to.

-- Why a separate collection from the internal track -------------------------------
`hrms_job_postings` is Sparsh Magic's own recruitment. This is a client's vacancy,
advertised on their behalf. Same idea, different tenant, different audience, and a single
collection serving both would put a client's advert one query mistake away from Sparsh's
own -- the exact failure the whole client track exists to make impossible.

-- Why applications become ordinary candidates -------------------------------------
An applicant IS a candidate; the posting is only how they arrived. So a submission creates
a normal `hrms_client_candidates` row at SOURCED, stamped with the posting it came from,
and the existing chain (screen -> telephonic -> shortlist -> share -> the client's verdict)
carries it from there unchanged. A parallel "application" lifecycle would be a second
pipeline for the same person, and the two would drift.

-- The public surface --------------------------------------------------------------
`get_public_client_posting` and `submit_client_application` are reached WITHOUT
authentication, so every field they touch is untrusted and the validation here is the only
validation there is. They are the one place in this module that does not take an actor.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CANDIDATE_ADDED,
    COLL_CLIENT_CANDIDATES, COLL_CLIENT_POSTINGS, COLL_CLIENT_REQUISITIONS,
    CLIENT_POSTING_EDITABLE, CLIENT_POSTING_TRANSITIONS,
    Cap, ClientCandidateStatus, ClientPostingStatus,
    ENTITY_CLIENT_CANDIDATE,
)
from app.services.hrms_id_service import next_business_id
from app.services.hrms_audit_service import audit
from app.utils.hrms_access import can
from app.utils.hrms_public_guard import clean_text

# The audit vocabulary for this stage. Named here rather than in the model because no other
# module writes them, and a constant nobody shares is a constant in the wrong place.
ENTITY_CLIENT_POSTING = "client_posting"
AUDIT_POSTING_CREATED = "client_posting.created"
AUDIT_POSTING_UPDATED = "client_posting.updated"
AUDIT_POSTING_MOVED = "client_posting.moved"
AUDIT_APPLICATION_RECEIVED = "client_posting.application_received"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+][0-9\s\-()]{6,}$")

INVALID_LINK = "This application link is not valid."
CLOSED_LINK = "This vacancy is no longer accepting applications."


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


# The public code alphabet. Deliberately the SAME shape the internal track uses
# (`^[A-Z]{2}-[A-Z0-9]{6}$`) so `validate_posting_code` can guard this surface too -- that
# validator is what makes NoSQL operator injection structurally impossible on a route
# anyone on the internet can reach, and a second format would need a second guard.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0, no I/1


def _mint_code() -> str:
    """A public application code. Unguessable, because it IS the authorization."""
    return "CJ-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


async def _require_approved_scorecard(company_id: str, cr_no: str) -> dict:
    """A posting hangs off a requisition whose scorecard the CLIENT has approved.

    Advertising a role before the benchmark is agreed produces applicants measured against
    nothing -- and the client, who has not yet said what "good" means here, is the one who
    ends up reading them.
    """
    from app.services.hrms_client_scorecard_service import assert_sourcing_allowed
    req = await get_collection(COLL_CLIENT_REQUISITIONS).find_one(
        {"cr_no": cr_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    await assert_sourcing_allowed(company_id, cr_no)
    return req


async def _application_counts(codes: list) -> dict:
    """How many people applied to each posting. One query, not one per row."""
    if not codes:
        return {}
    rows = await get_collection(COLL_CLIENT_CANDIDATES).find(
        {"posting_code": {"$in": codes}}, {"posting_code": 1}).to_list(5000)
    out: dict = {}
    for r in rows:
        code = r.get("posting_code")
        if code:
            out[code] = out.get(code, 0) + 1
    return out


# ─────────────────────────────────────────────────────────────
# Reading
# ─────────────────────────────────────────────────────────────
async def list_client_postings(actor: dict, company_id: Optional[str], *,
                               cr_no: str = None, status: str = None,
                               limit: int = 100) -> dict:
    """Postings for one client engagement.

    Sparsh-side only -- the client agreed the benchmark and reads the candidates, but the
    advert and its public link are Sparsh's to manage. There is therefore no client view
    to whitelist here, which is why this module has none.
    """
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    if cr_no:
        query["cr_no"] = cr_no
    if status:
        query["status"] = status

    rows = await get_collection(COLL_CLIENT_POSTINGS).find(query).sort(
        "created_at", -1).to_list(limit)
    counts = await _application_counts([r.get("posting_code") for r in rows])
    out = []
    for r in rows:
        doc = _out(r)
        doc["applications"] = counts.get(doc.get("posting_code"), 0)
        out.append(doc)
    return {
        "client_postings": out,
        "total": len(out),
        "published": sum(1 for r in out
                         if r.get("status") == ClientPostingStatus.PUBLISHED.value),
        # What the board counts as "Sparsh's move": a draft nobody has opened yet.
        "unpublished": sum(1 for r in out
                           if r.get("status") == ClientPostingStatus.DRAFT.value),
    }


async def get_client_posting(actor: dict, company_id: str, code: str) -> dict:
    doc = await get_collection(COLL_CLIENT_POSTINGS).find_one(
        {"posting_no": code, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Job posting not found.")
    out = _out(doc)
    counts = await _application_counts([out.get("posting_code")])
    out["applications"] = counts.get(out.get("posting_code"), 0)
    return out


async def list_applications(actor: dict, company_id: str, *, posting_no: str = None,
                            cr_no: str = None, limit: int = 200) -> dict:
    """Everyone who applied, against a posting or a requisition.

    Deliberately reads the CANDIDATE collection rather than an applications table: an
    applicant is a candidate who arrived a particular way, and giving them their own table
    would mean two records for one person from the moment HR first screens them.
    """
    query: dict = {"company_id": str(company_id)}
    if posting_no:
        posting = await get_client_posting(actor, company_id, posting_no)
        query["posting_code"] = posting.get("posting_code")
    elif cr_no:
        query["cr_no"] = cr_no
        query["posting_code"] = {"$ne": None}
    else:
        query["posting_code"] = {"$ne": None}

    rows = await get_collection(COLL_CLIENT_CANDIDATES).find(query).sort(
        "created_at", -1).to_list(limit)
    return {"client_applications": [_out(r) for r in rows], "total": len(rows)}


# ─────────────────────────────────────────────────────────────
# Writing
# ─────────────────────────────────────────────────────────────
async def create_client_posting(actor: dict, company_id: str, payload: dict) -> dict:
    """Draft a posting against a requisition whose scorecard the client has approved."""
    if not can(actor, Cap.CLIENT_POSTING_WRITE):
        raise HTTPException(
            status_code=403,
            detail=f"Creating a job posting needs {Cap.CLIENT_POSTING_WRITE.value}.")

    cr_no = clean_text(payload.get("cr_no"), limit=40)
    if not cr_no:
        raise HTTPException(status_code=422, detail="Name the requisition to advertise.")
    req = await _require_approved_scorecard(company_id, cr_no)

    title = clean_text(payload.get("title"), limit=200) or req.get("role_title")
    if not title:
        raise HTTPException(status_code=422, detail="The posting needs a title.")

    now = datetime.now(timezone.utc)
    posting_no = await next_business_id("client_posting", str(company_id), now.year)
    doc = {
        "posting_no": posting_no,
        "posting_code": _mint_code(),
        "company_id": str(company_id),
        "cr_no": cr_no,
        "title": title,
        "summary": clean_text(payload.get("summary"), limit=8000),
        "responsibilities": clean_text(payload.get("responsibilities"), limit=8000),
        "requirements": clean_text(payload.get("requirements"), limit=8000),
        "location": clean_text(payload.get("location"), limit=180),
        "employment_type": req.get("employment_type"),
        # The salary band is the CLIENT's to disclose. Defaults to hidden, because a range
        # they agreed with Sparsh is not automatically a range they want advertised.
        "show_salary": bool(payload.get("show_salary")),
        "salary_range_min": req.get("salary_range_min"),
        "salary_range_max": req.get("salary_range_max"),
        "status": ClientPostingStatus.DRAFT.value,
        "published_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by_name": (actor or {}).get("full_name"),
    }
    await get_collection(COLL_CLIENT_POSTINGS).insert_one(dict(doc))
    await audit(actor, AUDIT_POSTING_CREATED, ENTITY_CLIENT_POSTING, posting_no,
                f"{title} against {cr_no}", company_id)
    return await get_client_posting(actor, company_id, posting_no)


async def update_client_posting(actor: dict, company_id: str, code: str,
                                payload: dict) -> dict:
    """Edit a DRAFT. A published posting is what applicants were shown."""
    if not can(actor, Cap.CLIENT_POSTING_WRITE):
        raise HTTPException(
            status_code=403,
            detail=f"Editing a job posting needs {Cap.CLIENT_POSTING_WRITE.value}.")
    current = await get_client_posting(actor, company_id, code)
    if current.get("status") not in CLIENT_POSTING_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=(f'{code} is "{current.get("status")}". Editing a posting people have '
                    f"already answered would rewrite the advert they applied to."))

    updates: dict = {}
    for field, limit in (("title", 200), ("summary", 8000), ("responsibilities", 8000),
                         ("requirements", 8000), ("location", 180)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    if payload.get("show_salary") is not None:
        updates["show_salary"] = bool(payload["show_salary"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CLIENT_POSTINGS).update_one(
        {"posting_no": code, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_POSTING_UPDATED, ENTITY_CLIENT_POSTING, code,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client_posting(actor, company_id, code)


async def act_on_client_posting(actor: dict, company_id: str, code: str,
                                action: str, payload: dict = None) -> dict:
    """Move along CLIENT_POSTING_TRANSITIONS."""
    payload = payload or {}
    spec = CLIENT_POSTING_TRANSITIONS.get(action)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail="Action must be one of: " + ", ".join(CLIENT_POSTING_TRANSITIONS) + ".")
    expected_from, target, cap_name, needs_remarks = spec
    capability = getattr(Cap, cap_name)
    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail=f'"{action}" needs {capability.value}, which your role does not hold.')

    current = await get_client_posting(actor, company_id, code)
    if current.get("status") != expected_from.value:
        raise HTTPException(
            status_code=409,
            detail=f'{code} is "{current.get("status")}", so "{action}" does not apply.')

    remarks = clean_text(payload.get("remarks"), limit=4000)
    if needs_remarks and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say why this vacancy is closing. Somebody will ask.")

    if action == "publish":
        # A posting with nothing in it is a link to an empty page. The benchmark is agreed
        # by now, so there is no excuse for an advert that does not describe the job.
        missing = [label for field, label in (("summary", "a summary"),
                                              ("responsibilities", "the responsibilities"),
                                              ("requirements", "the requirements"))
                   if not current.get(field)]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=("A published vacancy is what an applicant reads. Still needed: "
                        + ", ".join(missing) + "."))
        # Re-checked at publish, not only at create: the client can send a scorecard back
        # between drafting the advert and opening it.
        await _require_approved_scorecard(company_id, current["cr_no"])

    now = datetime.now(timezone.utc)
    updates: dict = {"status": target.value, "updated_at": now}
    if action == "publish":
        updates["published_at"] = now
    if action == "close":
        updates["closed_at"] = now
        updates["closed_reason"] = remarks

    await get_collection(COLL_CLIENT_POSTINGS).update_one(
        {"posting_no": code, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_POSTING_MOVED, ENTITY_CLIENT_POSTING, code,
                f"{action}: {current.get('status')} -> {target.value}"
                + (f" ({remarks})" if remarks else ""), company_id)
    return await get_client_posting(actor, company_id, code)


# ─────────────────────────────────────────────────────────────
# The public surface -- NO authenticated caller, so nothing is trusted
# ─────────────────────────────────────────────────────────────
async def get_public_client_posting(code: str) -> dict:
    """The advert behind a public application link.

    Returns only what an applicant should read. Not the requisition, not the company id,
    not the internal numbering -- an application link is handed to strangers, and what it
    exposes is what a stranger learns about the client's hiring.
    """
    doc = await get_collection(COLL_CLIENT_POSTINGS).find_one({"posting_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc.get("status") != ClientPostingStatus.PUBLISHED.value:
        raise HTTPException(status_code=410, detail=CLOSED_LINK)
    out = {
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "responsibilities": doc.get("responsibilities"),
        "requirements": doc.get("requirements"),
        "location": doc.get("location"),
        "employment_type": doc.get("employment_type"),
    }
    if doc.get("show_salary"):
        out["salary_range_min"] = doc.get("salary_range_min")
        out["salary_range_max"] = doc.get("salary_range_max")
    return out


async def submit_client_application(code: str, payload: dict) -> dict:
    """Receive a public application and create the candidate it describes.

    There is no authenticated caller, so every value here is untrusted and this is the only
    validation that will happen. The candidate is created at SOURCED -- the same starting
    point a recruiter-entered candidate gets -- so one pipeline serves both.
    """
    posting = await get_collection(COLL_CLIENT_POSTINGS).find_one({"posting_code": code})
    if not posting:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if posting.get("status") != ClientPostingStatus.PUBLISHED.value:
        raise HTTPException(status_code=410, detail=CLOSED_LINK)

    name = clean_text(payload.get("candidate_name"), limit=140)
    email = clean_text(payload.get("email"), limit=180)
    phone = clean_text(payload.get("phone"), limit=30)
    if not name:
        raise HTTPException(status_code=422, detail="Please enter your full name.")
    if not email or not EMAIL_RE.match(email):
        raise HTTPException(status_code=422,
                            detail="Please enter a valid email address.")
    if not phone or not PHONE_RE.match(phone):
        raise HTTPException(status_code=422,
                            detail="Please enter a valid phone number.")
    if not clean_text(payload.get("cv_reference"), limit=500):
        raise HTTPException(status_code=422,
                            detail="Please attach or link your CV.")
    if not payload.get("declaration"):
        raise HTTPException(
            status_code=422,
            detail="Please confirm that the information provided is accurate.")

    company_id = posting["company_id"]
    # One application per person per posting. A duplicate is almost always a double-submit,
    # and two rows for one person splits their history in half.
    existing = await get_collection(COLL_CLIENT_CANDIDATES).find_one(
        {"company_id": company_id, "posting_code": code, "email": email})
    if existing:
        return {"ccn_no": existing["ccn_no"], "already_applied": True}

    now = datetime.now(timezone.utc)
    ccn_no = await next_business_id("client_candidate", str(company_id), now.year)
    doc = {
        "ccn_no": ccn_no,
        "company_id": company_id,
        "cr_no": posting["cr_no"],
        "posting_code": code,
        "posting_no": posting.get("posting_no"),
        "applied_at": now,
        "candidate_name": name,
        "email": email,
        "phone": phone,
        "source": "Job posting",
        "cv_reference": clean_text(payload.get("cv_reference"), limit=500),
        "current_employer": clean_text(payload.get("current_employer"), limit=180),
        "notice_period": clean_text(payload.get("notice_period"), limit=60),
        "tfs_score": None, "competency_score": None, "pi_score": None,
        "average_score": None, "score_band": None,
        "status": ClientCandidateStatus.SOURCED.value,
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_CLIENT_CANDIDATES).insert_one(dict(doc))
    # No actor: the applicant is not a user of this system.
    await audit(None, AUDIT_CLIENT_CANDIDATE_ADDED, ENTITY_CLIENT_CANDIDATE, ccn_no,
                f"applied to {posting.get('posting_no')}", company_id)
    await audit(None, AUDIT_APPLICATION_RECEIVED, ENTITY_CLIENT_POSTING,
                posting.get("posting_no"), f"{name} applied", company_id)
    return {"ccn_no": ccn_no, "already_applied": False}


async def posting_open_for(company_id: str, cr_no: str) -> Optional[dict]:
    """The published posting for a requisition, if there is one. Used by the board."""
    doc = await get_collection(COLL_CLIENT_POSTINGS).find_one(
        {"company_id": str(company_id), "cr_no": cr_no,
         "status": ClientPostingStatus.PUBLISHED.value})
    return _out(doc) if doc else None
