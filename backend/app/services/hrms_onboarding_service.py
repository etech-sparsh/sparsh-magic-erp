"""HRMS > onboarding, and the moment recruitment becomes an employee.

This phase closes the gap both analysis documents named as the single largest hole in the
source system: "Employee Management -- Not found" (BACKEND_ANALYSIS 2). The source could
hire someone and then had nowhere to put them. Everything from Phase 3 onwards has been
building a pipeline whose last step did not exist; this is that step.

-- An employee is created BEFORE they have a login ---------------------------------------
A new hire is not yet a user of the ERP. Their Employee ID is issued on day one, but their
account may be created days later, or never (a factory hire who never signs in still needs
payroll). HRMS therefore mints the employee record with NO `user_id` at all -- the field is
absent rather than null, because a null value is still indexed and the unique index would
then permit exactly one such row. `hrms_employee_profiles.uniq_user` is sparse for this
reason, and the directory composes such a person from the `identity_snapshot` captured at
onboarding, flagged `pending_user_link`.

HRMS still never writes to `staff` or `learners`. The alternative -- having HRMS create a
`learners` login -- would put an HR module in charge of authentication records it does not
own, and would break the invariant asserted in every phase since Phase 1. When the account
does appear, `POST /hrms/employees/{code}/link` attaches it and the user document becomes
the single source of identity from that moment on.

-- The checklist has two kinds of item ---------------------------------------------------
Nine items are human judgements (assets issued, induction done). Three are claims the system
can verify and therefore owns: `employee_id`, `documents_verified` and `bg_cleared`. Letting
a human tick those by hand would let the checklist assert something the data contradicts --
"background cleared" while the verification sits at Flagged. Those three are driven by the
actions that actually achieve them and are refused as manual edits.

-- Only an accepted offer may be onboarded -----------------------------------------------
Onboarding collects PAN, Aadhaar and bank details. Asking a candidate for those before they
have agreed to join gathers sensitive identity data on somebody who may still say no, so the
gate is `Offer Accepted` and nothing earlier (see ONBOARDABLE_STATUSES).
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AADHAAR_RE, AUDIT_EMPLOYEE_ID_ISSUED, AUDIT_ONBOARD_BG, AUDIT_ONBOARD_CHECKLIST,
    AUDIT_ONBOARD_COMPLETED, AUDIT_ONBOARD_DETAILS, AUDIT_ONBOARD_DOCUMENTS,
    AUDIT_ONBOARD_STARTED, AUDIT_ONBOARD_SUBMITTED, AUDIT_ONBOARD_VERIFIED,
    AUDIT_STAGE_CHANGED, CHECKLIST_KEYS, COLL_CANDIDATES, COLL_OFFERS, COLL_ONBOARDING,
    COLL_REQUISITIONS, ENTITY_CANDIDATE, ENTITY_ONBOARDING,
    EMAIL_RE, IFSC_RE, MAX_ONBOARD_DOCUMENTS, MAX_REFERENCES, ONBOARD_SECTIONS,
    ONBOARDABLE_STATUSES, PAN_RE,
    INDUCTION_CHECKLIST, ONBOARD_CANDIDATE_TASKS, REQUISITION_TRACK_INTERNAL,
    ASSIGNMENT_FIELDS, DOC_SATISFYING_STATUSES, SYSTEM_CHECKLIST_KEYS,
    TASKS_ASSIGNED_AT_JOINING, TASK_OWNER_ADMIN, TASK_OWNER_IT,
    TASK_OWNER_MANAGER, task_owner,
    AppStatus, BgVerification, DocStatus, Gender, OfferStatus,
    OnboardStatus, PreOnboardStatus, can_transition, is_iso_date, seed_checklist,
)
from app.services import hrms_employee_service as employees
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_public_guard import (
    INVALID_LINK, clean_text, decode_upload, new_access_code,
)

logger = logging.getLogger(__name__)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    if not actor:
        return "System"
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _progress(checklist: list) -> dict:
    total = len(checklist or [])
    done = sum(1 for item in (checklist or []) if item.get("done"))
    return {"done": done, "total": total,
            "percent": int(round(done * 100 / total)) if total else 0}


async def _get(company_id: str, onb_no: str) -> dict:
    doc = await get_collection(COLL_ONBOARDING).find_one(
        {"onb_no": onb_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Onboarding record not found.")
    return doc


def _assert_open(doc: dict) -> None:
    """Refuse edits once onboarding is Completed.

    A completed onboarding is a record of what happened, not a working document. Re-opening
    it to tick a box would rewrite history; the employee record is the live thing from then
    on and is edited through the employee master.
    """
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail="This onboarding is complete. Update the employee record instead.")


# ─────────────────────────────────────────────────────────────
# Candidate stage movement
# ─────────────────────────────────────────────────────────────
async def _advance_candidate(actor: Optional[dict], company_id: str, uk: str,
                             target: AppStatus) -> None:
    """Move the candidate, but only along a legal edge.

    Deliberately silent when the edge is illegal: onboarding must not fail because the
    candidate was moved by hand in the meantime. The lifecycle graph is the authority and a
    refused move is simply not made, rather than corrupting the stage or aborting the
    onboarding step the operator actually asked for.
    """
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)},
        # `applied_at` / `created_at` come back because the JOINED branch below recomputes
        # the retention floor from the merged record; a status-only projection would leave
        # it computing against a document with no anchor in it.
        {"application_status": 1, "applied_at": 1, "created_at": 1, "joined_at": 1})
    current = (candidate or {}).get("application_status")
    if not current or current == target.value:
        return
    if not can_transition(current, target.value):
        return
    now = datetime.now(timezone.utc)
    updates = {"application_status": target.value, "updated_at": now}

    # ── SOP §13 ── joining is the anchor the SELECTED retention period runs from, and it
    # is written HERE because this is the only place a candidate becomes Joined.
    #
    # `candidate_retention_until` has always preferred `joined_at` over `applied_at` and
    # nothing ever wrote it, so a joiner was silently kept on the one-year unselected floor
    # measured from their application instead of three years from joining -- the retention
    # rule inverted for exactly the people the personnel file is about.
    if target is AppStatus.JOINED:
        from app.services.hrms_candidate_service import (
            _retention_map, candidate_retention_until)
        updates["joined_at"] = now
        merged = {**(candidate or {}), "application_status": target.value,
                  "joined_at": now}
        recomputed = candidate_retention_until(
            merged, await _retention_map(company_id))
        if recomputed:
            updates["retention_until"] = recomputed

    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": updates})
    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                f"{current} -> {target.value}", company_id)


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
async def list_onboardings(actor: dict, company_id: str, *, status: str = None,
                           search: str = None) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if search:
        term = clean_text(search, limit=80)
        if term:
            escaped = re.escape(term)
            query["$or"] = [
                {"candidate_name": {"$regex": escaped, "$options": "i"}},
                {"onb_no": {"$regex": escaped, "$options": "i"}},
                {"employee_id": {"$regex": escaped, "$options": "i"}},
            ]

    rows = await get_collection(COLL_ONBOARDING).find(query).sort("created_at", -1).to_list(500)

    # ── §7.5 Stage 5 ── the board carries the completeness figure, because the question
    # "who is behind?" is asked of the LIST. Everything it needs is fetched in two queries
    # for the whole page rather than two per row.
    from app.services.hrms_config_service import onboarding_doc_types
    catalogue = await onboarding_doc_types(company_id)
    verification_by_uk = await _bulk_verification(
        company_id, [r.get("uk") for r in rows if r.get("uk")])

    out = []
    for row in rows:
        view = _out(row)
        view["checklist"] = _with_owners(view.get("checklist"))
        tasks = _document_tasks(view, catalogue)
        view["document_tasks"] = tasks
        view["completeness"] = _completeness(
            view, tasks, verification_by_uk.get(view.get("uk")) or {})
        view["progress"] = _progress(view.get("checklist"))
        # The access code is a credential. It belongs on the detail view (where HR copies the
        # link) and nowhere else -- a list endpoint is the easiest thing to over-share.
        view.pop("access_code", None)
        # Popped AFTER completeness is computed: the percentage is derived from the
        # submission, but the submission itself is not a list-view concern.
        view.pop("submission", None)
        out.append(view)
    return out


async def _bulk_verification(company_id: str, uks: list) -> dict:
    """`{uk: {checks, outstanding, cleared}}` for a whole page, in two queries.

    A cut-down `verification_state`: the list only needs "is this joiner's verification
    clear", not the individual rows. The detail view still reads the full state.
    """
    if not uks:
        return {}
    try:
        from app.models.hrms import (
            APPROVAL_FIELD, BACKGROUND_CLEARS_OFFER, BackgroundApprovalStatus,
            BackgroundCheckStatus, COLL_BACKGROUND_CHECKS, REQUIRED_BACKGROUND_CHECKS)
    except ImportError:                             # pragma: no cover - defensive
        return {}

    try:
        rows = await get_collection(COLL_BACKGROUND_CHECKS).find(
            {"company_id": str(company_id), "uk": {"$in": uks}}).sort(
            "created_at", 1).to_list(5000)
        people = await get_collection(COLL_CANDIDATES).find(
            {"company_id": str(company_id), "uk": {"$in": uks}},
            {"uk": 1, APPROVAL_FIELD: 1}).to_list(5000)
    except Exception as e:                          # pragma: no cover - defensive
        logger.warning("Bulk verification unavailable: %s", e)
        return {}

    latest = {}
    for row in rows:                                # ascending, so the last write wins
        latest.setdefault(row.get("uk"), {})[row.get("check_type")] = row
    approvals = {p.get("uk"): (p.get(APPROVAL_FIELD) or {}) for p in people}

    required = [t.value for t in REQUIRED_BACKGROUND_CHECKS]
    out = {}
    for uk in set(uks):
        by_type = latest.get(uk, {})
        outstanding, flagged = [], []
        for check_type in required:
            row = by_type.get(check_type)
            if not row:
                outstanding.append(check_type)
            elif row.get("status") == BackgroundCheckStatus.FLAGGED.value:
                flagged.append(check_type)
            elif row.get("status") not in BACKGROUND_CLEARS_OFFER:
                outstanding.append(check_type)
        signed = (approvals.get(uk, {}).get("status")
                  == BackgroundApprovalStatus.APPROVED.value)
        out[uk] = {
            "checks": list(by_type.values()),
            "outstanding": outstanding if by_type else [],
            "flagged": flagged,
            "cleared": bool(by_type) and not outstanding and not flagged and signed,
        }
    return out


def _with_owners(checklist: list) -> list:
    """Resolve each item's owner at read time (§7.5 Stage 8).

    Records created before ownership existed have no `owner` on their items. Filling it in
    here rather than migrating means an old case reads correctly the first time it is
    opened, and the value is written back the next time the case is saved.
    """
    return [{**i, "owner": i.get("owner") or task_owner(i.get("key"))}
            for i in (checklist or [])]


async def get_onboarding(actor: dict, company_id: str, onb_no: str) -> dict:
    doc = _out(await _get(company_id, onb_no))
    doc["checklist"] = _with_owners(doc.get("checklist"))
    doc["progress"] = _progress(doc.get("checklist"))

    # The same joining-document task list the new hire sees, so HR is chasing the same
    # named documents rather than counting files -- and so the activation gate below is
    # judging exactly what the screen is showing.
    from app.services.hrms_config_service import onboarding_doc_types
    catalogue = await onboarding_doc_types(company_id)
    doc["document_tasks"] = _document_tasks(doc, catalogue)

    # ── §7.5 Stage 4 ── the verification file, shown ON the case rather than as a
    # separate process somewhere else. Read live from the check records, so the case can
    # never claim a clearance those records do not support.
    doc["verification"] = await _verification_block(company_id, doc.get("uk"))

    # ── §7.5 Stage 5 ── one number over the five stages above, and the itemised list of
    # what is still missing behind it.
    doc["completeness"] = _completeness(
        doc, doc["document_tasks"], doc["verification"])

    blockers = _id_blockers(doc, doc["document_tasks"])
    doc["can_generate_id"] = blockers == []
    doc["id_blockers"] = blockers
    return doc


async def _verification_block(company_id: str, uk: str) -> dict:
    """The BGV and reference position for one joiner, as the onboarding case shows it.

    Both halves of §7.5 Stage 4 in one shape: the background checks with what is still
    outstanding, and the reference check that cleared them. Defensive because neither is
    load-bearing for the rest of the case -- a verification module that errors should cost
    this screen its verification panel, not the whole record.
    """
    out = {"checks": [], "outstanding": [], "flagged": [], "approval": None,
           "reference": None}
    if not uk:
        return out
    try:
        from app.services.hrms_background_service import verification_state
        state = await verification_state(company_id, uk)
        out.update({
            "checks": state.get("checks") or [],
            "required": state.get("required") or [],
            "outstanding": state.get("outstanding") or [],
            "flagged": state.get("flagged") or [],
            "checks_complete": state.get("checks_complete"),
            "approval": state.get("approval"),
            "cleared": state.get("cleared_for_offer"),
        })
    except Exception as e:                          # pragma: no cover - defensive
        logger.warning("Verification state unavailable for %s: %s", uk, e)
    try:
        from app.services.hrms_reference_service import clearing_reference
        out["reference"] = await clearing_reference(company_id, uk)
    except Exception as e:                          # pragma: no cover - defensive
        logger.warning("Reference state unavailable for %s: %s", uk, e)
    return out


async def onboardable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who have accepted an offer and do not yet have an onboarding."""
    existing = await get_collection(COLL_ONBOARDING).find(
        {"company_id": str(company_id)}, {"uk": 1}).to_list(2000)
    taken = {row.get("uk") for row in existing}

    rows = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id),
         "application_status": {"$in": [s.value for s in ONBOARDABLE_STATUSES]}},
        {"uk": 1, "candidate_name": 1, "can_email": 1, "can_contact": 1,
         "request_no": 1, "application_status": 1}).to_list(500)

    return [{"uk": r["uk"], "candidate_name": r.get("candidate_name"),
             "can_email": r.get("can_email"), "can_contact": r.get("can_contact"),
             "request_no": r.get("request_no"),
             "application_status": r.get("application_status")}
            for r in rows if r.get("uk") not in taken]


# ─────────────────────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────────────────────
async def start_onboarding(actor: dict, company_id: str, payload: dict) -> dict:
    uk = clean_text(payload.get("uk"), limit=40)
    if not uk:
        raise HTTPException(status_code=422, detail="Choose a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    # Duplicate check FIRST. Starting an onboarding moves the candidate to Pre-Onboarding,
    # so a second attempt would otherwise fail the stage gate below and report "they have
    # not accepted an offer" -- true of the stage, but not the reason, and actively
    # misleading to whoever is looking at an accepted offer on their screen.
    if await get_collection(COLL_ONBOARDING).find_one(
            {"uk": uk, "company_id": str(company_id)}):
        raise HTTPException(
            status_code=409, detail="This candidate is already being onboarded.")

    stage = candidate.get("application_status")
    if stage not in {s.value for s in ONBOARDABLE_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail="Onboarding can only be started once the candidate has accepted an offer.")

    # Pull terms from the accepted offer, then the requisition. The offer is the more
    # authoritative source -- it is what the candidate actually agreed to.
    offer = await get_collection(COLL_OFFERS).find_one(
        {"uk": uk, "company_id": str(company_id),
         "status": OfferStatus.ACCEPTED.value})
    req = None
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"], "company_id": str(company_id)})

    joining_date = clean_text(payload.get("joining_date"), limit=10) \
        or (offer or {}).get("joining_date")
    if joining_date and not is_iso_date(joining_date):
        raise HTTPException(
            status_code=422,
            detail="Joining date must be a valid date in YYYY-MM-DD format.")

    year = datetime.now(timezone.utc).year
    onb_no = await next_business_id("onboarding", str(company_id), year)
    now = datetime.now(timezone.utc)

    # The verification file is read HERE, not left to `sync_verification`.
    #
    # On the internal track the offer gate refuses to raise an offer until the background
    # checks are complete and HR has signed them off, and a case is only created once that
    # offer has been ACCEPTED -- so every sync that could have carried the result across
    # already ran, harmlessly, before this record existed. Hardcoding Pending here left the
    # case permanently claiming a clearance had not happened when it had, `update_bg`
    # refused to correct it by hand ("this joiner has a verification file"), and the §11
    # statutory gate could then never be satisfied without waiving a check that had in fact
    # been done. Deriving it makes the new case agree with the records from the first read.
    from app.services.hrms_background_service import verification_state
    try:
        bg_verification = _derive_bg(await verification_state(company_id, uk))
    except Exception as e:                          # pragma: no cover - defensive
        # Opening the case matters more than seeding one derived field. If the checks
        # cannot be read, start at Pending and let `sync_verification` correct it on the
        # next change, which is exactly what it exists for.
        print(f"[WARN] HRMS onboarding could not read the verification file: {e}")
        bg_verification = BgVerification.PENDING.value

    doc = {
        "onb_no": onb_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "candidate_mobile": candidate.get("can_contact"),
        "offer_no": (offer or {}).get("offer_no"),
        "request_no": candidate.get("request_no"),
        "designation": (offer or {}).get("designation") or (req or {}).get("designation_name"),
        "department_id": (req or {}).get("department_id"),
        "designation_id": (req or {}).get("designation_id"),
        "status": OnboardStatus.PRE_ONBOARDING.value,
        "pre_status": PreOnboardStatus.PENDING.value,
        "bg_verification": bg_verification,
        "bg_note": None,
        "access_code": new_access_code(),
        "joining_date": joining_date,
        "reporting_manager_id": clean_text(payload.get("reporting_manager_id"), limit=40)
        or (req or {}).get("assignee_id"),
        "asset_requirements": None,
        "submission": None,
        "documents": [],
        # The track discriminator rides on the onboarding record, as it does on every
        # record that hangs off a requisition (see REQUISITION_TRACK_INTERNAL).
        "requisition_track": REQUISITION_TRACK_INTERNAL,
        "checklist": _set_item(
            seed_checklist(), "bg_cleared",
            bg_verification == BgVerification.CLEARED.value, None, now),
        "employee_id": None,
        "created_at": now,
        "created_by": str(actor.get("_id")) if actor and actor.get("_id") else None,
        "created_by_name": _actor_name(actor),
        "updated_at": now,
    }
    await get_collection(COLL_ONBOARDING).insert_one(dict(doc))

    # Phase 11-R, Item 1: register the pre-onboarding link. Fire-and-forget by contract.
    from app.models.hrms import LinkKind
    from app.services.hrms_link_service import register_link
    await register_link(
        company_id=company_id, kind=LinkKind.ONBOARDING, code=doc["access_code"],
        target_type="onboarding", target_id=onb_no, actor=actor,
        candidate_name=doc.get("candidate_name"), request_no=doc.get("request_no"))

    await _advance_candidate(actor, company_id, uk, AppStatus.PRE_ONBOARDING)
    await audit(actor, AUDIT_ONBOARD_STARTED, ENTITY_ONBOARDING, onb_no,
                doc["candidate_name"], company_id)

    # ── BA Functional Design §7.5 ── "Send Secure Onboarding Portal / Task List".
    #
    # The step straight after "Create Pre-Joiner Case", so it happens here rather than
    # waiting for HR to copy the link off the board -- a candidate who accepted on a Friday
    # should not wait until Monday to learn what we need from them. `send_template` logs a
    # `Failed` row instead of raising when delivery does not work, which is what makes it
    # safe to call from inside the acceptance path.
    portal_sent = await _send_portal_link(company_id, doc)

    await notify_hrms_role(
        company_id, ["HR"], f"Onboarding started: {doc['candidate_name']}",
        (f"{onb_no} is open and the pre-onboarding link has been emailed to them."
         if portal_sent else
         f"{onb_no} is open, but the pre-onboarding link could NOT be emailed. "
         f"Send it from the onboarding board."),
        link="/hrms/onboarding")

    return await get_onboarding(actor, company_id, onb_no)


async def _send_portal_link(company_id: str, doc: dict) -> bool:
    """Email the candidate their secure onboarding link and the list of what we need.

    The task list is what the CANDIDATE has to supply, not the onboarding checklist -- that
    one is HR's own work (issue a laptop, create an email account) and would read as a set of
    instructions to somebody who cannot act on any of it.

    Returns whether it went out, so HR can be told when it did not.
    """
    try:
        from app.services.hrms_comm_service import send_template
        from app.services.tpms_form_link_service import configured_base_url
        base = await configured_base_url()
        result = await send_template(
            None, company_id, doc["uk"], "onboarding_portal",
            variables={
                "portal_link": f"{base}/onboard/{doc['access_code']}",
                "task_list": "\n".join(f"  - {task}" for task in ONBOARD_CANDIDATE_TASKS),
            },
            automatic=True)
        # Only "Sent" counts. "Skipped" means there is no address on the record, which is
        # exactly the case HR needs telling about.
        return (result or {}).get("status") == "Sent"
    except Exception as e:
        # Never the reason a pre-joiner case fails to open: the record, the link and the
        # checklist all exist by this point, and HR is told below that the email did not go.
        logger.warning("Could not email the onboarding portal link for %s: %s",
                       doc.get("onb_no"), e)
        return False


# ─────────────────────────────────────────────────────────────
# HR-side edits
# ─────────────────────────────────────────────────────────────
async def update_details(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    changes = {}
    if "joining_date" in payload:
        value = clean_text(payload.get("joining_date"), limit=10)
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="Joining date must be a valid date in YYYY-MM-DD format.")
        changes["joining_date"] = value or None
    if "reporting_manager_id" in payload:
        changes["reporting_manager_id"] = clean_text(
            payload.get("reporting_manager_id"), limit=40) or None
    if "asset_requirements" in payload:
        changes["asset_requirements"] = clean_text(
            payload.get("asset_requirements"), limit=2000) or None

    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update.")

    changes["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)}, {"$set": changes})
    await audit(actor, AUDIT_ONBOARD_DETAILS, ENTITY_ONBOARDING, onb_no,
                ", ".join(k for k in changes if k != "updated_at"), company_id)
    return await get_onboarding(actor, company_id, onb_no)


async def update_bg(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    """Record the background-verification outcome.

    Also drives the `bg_cleared` checklist item, in BOTH directions: moving away from Cleared
    un-ticks it. A checklist that only ever moves forwards would keep asserting a clearance
    that has since been withdrawn.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    raw = payload.get("bg_verification")
    value = getattr(raw, "value", raw)
    try:
        outcome = BgVerification(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown background-check outcome.")

    # ── §7.5 Stage 4 ── once real verification records exist, they are the answer and this
    # field is derived from them (`sync_verification`). Letting it be typed over as well
    # would put two answers in the record and no way to tell which is current -- the same
    # reason the three system-owned checklist items refuse a manual tick.
    from app.services.hrms_background_service import verification_state
    state = await verification_state(company_id, doc.get("uk"))
    if state.get("checks"):
        raise HTTPException(
            status_code=409,
            detail=("This joiner has a verification file, so their background status "
                    "follows it. Record the check result on the Verification screen and "
                    "this case updates itself."))

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], "bg_cleared",
                          outcome == BgVerification.CLEARED, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"bg_verification": outcome.value,
                  "bg_note": clean_text(payload.get("note"), limit=2000),
                  "checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_BG, ENTITY_ONBOARDING, onb_no, outcome.value, company_id)

    if outcome == BgVerification.FLAGGED:
        await notify_hrms_role(
            company_id, ["HR", "MD"],
            f"Background check flagged: {doc.get('candidate_name')}",
            f"{onb_no} was flagged during background verification. "
            "An Employee ID cannot be issued until this is resolved.",
            kind="warning", link="/hrms/onboarding", email=True)

    return await _refresh(actor, company_id, onb_no)


async def verify_documents(actor: dict, company_id: str, onb_no: str) -> dict:
    """Mark the candidate's KYC documents as checked by a human."""
    doc = await _get(company_id, onb_no)
    _assert_open(doc)
    if doc.get("pre_status") != PreOnboardStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail="There is nothing to verify yet — the candidate has not submitted "
                   "their pre-onboarding form.")

    # This flag is the claim "a human has checked this file". It must not be settable while
    # a mandatory document is still unreviewed, rejected or absent -- that is the same rule
    # the three system-owned checklist items follow: never assert what the data contradicts.
    from app.services.hrms_config_service import onboarding_doc_types
    outstanding = _document_blockers(
        _document_tasks(doc, await onboarding_doc_types(company_id)))
    if outstanding:
        raise HTTPException(status_code=409, detail=" ".join(outstanding))

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], "documents_verified", True, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"pre_status": PreOnboardStatus.VERIFIED.value,
                  "verified_at": now, "verified_by": _actor_name(actor),
                  "checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_VERIFIED, ENTITY_ONBOARDING, onb_no,
                doc.get("candidate_name"), company_id)
    return await _refresh(actor, company_id, onb_no)


def _derive_bg(state: dict) -> str:
    """The onboarding case's background status, READ OFF the real check records.

    §7.5 Stage 4 puts BGV inside the onboarding case rather than beside it, and the only
    way for the case to be inside it is for this value to be derived. It used to be a
    dropdown somebody set by hand, which meant the case could read "Cleared" while the
    checks it refers to sat flagged.
    """
    if state.get("flagged"):
        return BgVerification.FLAGGED.value
    if state.get("cleared_for_offer"):
        return BgVerification.CLEARED.value
    if state.get("checks"):
        return BgVerification.IN_PROGRESS.value
    return BgVerification.PENDING.value


async def sync_verification(company_id: str, uk: str) -> None:
    """Push the current verification result onto this candidate's open onboarding case.

    "Result / Status -> Onboarding Case Updated", the last edge of the §7.5 Stage 4 flow.
    Called by the background-check service whenever a check or a sign-off changes, so the
    case never has to be refreshed by hand and cannot drift from the records.

    Silent when there is no open onboarding: verification also runs BEFORE the offer, long
    before a case exists, and that is not an error.
    """
    coll = get_collection(COLL_ONBOARDING)
    case = await coll.find_one(
        {"company_id": str(company_id), "uk": uk,
         "status": {"$ne": OnboardStatus.COMPLETED.value}})
    if not case:
        return

    from app.services.hrms_background_service import verification_state
    derived = _derive_bg(await verification_state(company_id, uk))
    if derived == case.get("bg_verification"):
        return

    now = datetime.now(timezone.utc)
    checklist = _set_item(case.get("checklist") or [], "bg_cleared",
                          derived == BgVerification.CLEARED.value, None, now)
    await coll.update_one(
        {"onb_no": case["onb_no"], "company_id": str(company_id)},
        {"$set": {"bg_verification": derived, "checklist": checklist, "updated_at": now}})
    await audit(None, AUDIT_ONBOARD_BG, ENTITY_ONBOARDING, case["onb_no"],
                f"{derived} (from the verification file)", company_id)


async def review_document(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    """Record HR's verdict on ONE uploaded document (§7.5 Stage 3).

    Acts on the CURRENT version of that document type. An older version keeps whatever
    verdict it had when it was superseded -- rewriting it would destroy the reason the
    document was replaced, which is the more interesting half of the history.

    A rejection and an exception both need a note. "Rejected" with no reason leaves the new
    hire nothing to act on, and an undertaking that does not say what was accepted, or on
    what basis, is not an undertaking.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    doc_type = clean_text(payload.get("doc_type"), limit=120)
    if not doc_type:
        raise HTTPException(status_code=422, detail="Which document is this verdict for?")

    raw = payload.get("status")
    try:
        status = DocStatus(getattr(raw, "value", raw))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="A document is Pending, Verified, Rejected or Exception.")

    note = clean_text(payload.get("note"), limit=2000)
    if status in (DocStatus.REJECTED, DocStatus.EXCEPTION) and not note:
        raise HTTPException(
            status_code=422,
            detail=("Say why. A rejection has to tell the new hire what to fix, and an "
                    "exception has to record what was accepted and on whose authority."))

    documents = [dict(d) for d in (doc.get("documents") or [])]
    target = _latest_by_type(documents).get(doc_type)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f'No "{doc_type}" has been uploaded for this joiner yet.')

    now = datetime.now(timezone.utc)
    for entry in documents:
        if (entry.get("doc_type") == doc_type
                and int(entry.get("version") or 1) == int(target.get("version") or 1)):
            entry["status"] = status.value
            entry["reviewed_by"] = _actor_name(actor)
            entry["reviewed_at"] = now
            entry["review_note"] = note
            entry["history"] = list(entry.get("history") or []) + [{
                "status": status.value, "note": note,
                "by": _actor_name(actor), "at": now}]
            break

    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"documents": documents, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_DOCUMENTS, ENTITY_ONBOARDING, onb_no,
                f"{doc_type} v{target.get('version') or 1} -> {status.value}"
                + (f" ({note})" if note else ""),
                company_id)
    return await _refresh(actor, company_id, onb_no)


async def add_documents(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    """HR-side KYC upload — for documents handed over in person or by email.

    Separate from the candidate's public submission so HR is never blocked waiting for a
    form the candidate has not filled in.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    uploads = payload.get("documents") or []
    if not uploads:
        raise HTTPException(status_code=422, detail="Attach at least one document.")

    existing = doc.get("documents") or []
    from app.services.hrms_config_service import onboarding_doc_types
    stored = await _store_documents(
        uploads, existing_count=len(existing), source="hr",
        doc_types=await onboarding_doc_types(company_id), existing=existing)

    now = datetime.now(timezone.utc)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"updated_at": now}, "$push": {"documents": {"$each": stored}}})
    await audit(actor, AUDIT_ONBOARD_DOCUMENTS, ENTITY_ONBOARDING, onb_no,
                f"{len(stored)} document(s) added", company_id)
    return await _refresh(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# Checklist
# ─────────────────────────────────────────────────────────────
def _set_item(checklist: list, key: str, done: bool, actor: Optional[dict],
              now: datetime) -> list:
    out = []
    for item in checklist or []:
        item = dict(item)
        if item.get("key") == key:
            item["done"] = bool(done)
            item["done_at"] = now if done else None
            item["done_by"] = _actor_name(actor) if done else None
        out.append(item)
    return out


async def set_checklist(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    key = clean_text(payload.get("key"), limit=60)
    # Validated against THIS record's own checklist, not a global list. The internal track
    # adds Day-1 induction items and the client track does not, so a global allow-list would
    # accept an induction key on a client onboarding and then silently tick nothing --
    # `_set_item` only updates items that are already there.
    own_keys = {item.get("key") for item in (doc.get("checklist") or [])}
    if key not in own_keys:
        if key in CHECKLIST_KEYS or key in {k for k, _ in INDUCTION_CHECKLIST}:
            raise HTTPException(
                status_code=409,
                detail=(f'"{key}" is not on this onboarding\'s checklist. Induction items '
                        f"exist on internal-track onboardings only."))
        raise HTTPException(status_code=422, detail="Unknown checklist item.")
    if key in SYSTEM_CHECKLIST_KEYS:
        # The system owns these three because it can verify them. A hand-tick would let the
        # checklist assert something the data contradicts.
        raise HTTPException(
            status_code=409,
            detail="This item is updated automatically by the system, not by hand.")

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], key, bool(payload.get("done")),
                          actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_CHECKLIST, ENTITY_ONBOARDING, onb_no,
                f"{key} {'done' if payload.get('done') else 'reopened'}", company_id)

    # ── Phase INT-2 (SOP §10) ── issue the induction experience survey the moment the
    # induction is finished, not on a schedule: this is the point the module already knows
    # the joining experience is over, and asking a fortnight later measures memory.
    #
    # Best-effort by contract -- `issue_survey` swallows everything and is idempotent per
    # (instrument, employee), so re-ticking an item never issues a second link and a survey
    # that cannot be minted never fails the checklist update.
    await _issue_induction_survey(actor, company_id, onb_no, checklist, doc)
    return await _refresh(actor, company_id, onb_no)


async def _issue_induction_survey(actor: dict, company_id: str, onb_no: str,
                                  checklist: list, doc: dict) -> None:
    """Fire the induction survey once every induction item is done.

    Keyed on the INDUCTION items alone rather than the whole checklist. The rest of the
    list runs for weeks (assets, buddy, payroll) and the induction experience is over on
    Day 1 -- waiting for the last item would ask somebody about their first day two months
    after it happened.
    """
    induction_items = [i for i in (checklist or []) if i.get("induction")]
    if not induction_items or not all(i.get("done") for i in induction_items):
        return                          # client track, or not finished yet
    if not doc.get("employee_id"):
        # De-duplication keys on the employee code, so there is nothing to key on yet. The
        # next tick after the ID is minted issues it.
        return

    from app.models.hrms import SurveyKind
    from app.services.hrms_survey_service import issue_survey
    await issue_survey(actor, company_id, SurveyKind.INDUCTION,
                       employee_code=doc["employee_id"],
                       request_no=doc.get("request_no"),
                       employee_name=doc.get("candidate_name"))


# ─────────────────────────────────────────────────────────────
# The handover — minting the employee record
# ─────────────────────────────────────────────────────────────
def _document_tasks(doc: dict, catalogue: dict) -> list:
    """The joining-document catalogue with this joiner's progress against it.

    One row per document the company asks for, carrying the current version's verdict. This
    is the single shape the new hire's portal, HR's board and the joining gate all read, so
    the three cannot disagree about what is outstanding.
    """
    latest = _latest_by_type(doc.get("documents") or [])
    rows = []
    for label, required in (catalogue or {}).items():
        current = latest.get(label)
        rows.append({
            "doc_type": label,
            "required": bool(required),
            "uploaded": current is not None,
            "version": int(current.get("version") or 1) if current else 0,
            "status": (current or {}).get("status") or DocStatus.PENDING.value,
            "review_note": (current or {}).get("review_note"),
            "reviewed_by": (current or {}).get("reviewed_by"),
        })
    return rows


def _document_blockers(tasks: list) -> list:
    """Mandatory documents standing between this joiner and activation (§7.5 Stage 3).

    Verified and Exception both satisfy the gate; Exception is exactly the "controlled
    continuation where policy permits" case, and it is signed and noted rather than silent.
    Missing, still Pending and Rejected each read differently because the thing to do about
    them differs: chase, review, and re-collect.
    """
    missing = [t["doc_type"] for t in tasks if t["required"] and not t["uploaded"]]
    unreviewed = [t["doc_type"] for t in tasks
                  if t["required"] and t["uploaded"]
                  and t["status"] == DocStatus.PENDING.value]
    rejected = [t["doc_type"] for t in tasks
                if t["required"] and t["status"] == DocStatus.REJECTED.value]

    blockers = []
    if missing:
        blockers.append("Mandatory documents not received: " + ", ".join(missing) + ".")
    if unreviewed:
        blockers.append("Mandatory documents not yet reviewed: "
                        + ", ".join(unreviewed) + ".")
    if rejected:
        blockers.append("Mandatory documents were rejected and must be replaced: "
                        + ", ".join(rejected) + ".")
    return blockers


def _completeness(doc: dict, doc_tasks: list, verification: dict) -> dict:
    """How far this onboarding has actually got, across the six groups §7.5 Stage 5 names.

    Every mandatory item counts once, so the percentage is "how many of the things we need
    do we have" rather than a weighting somebody tuned. The per-group breakdown matters
    more than the number: "62%" tells HR to chase, `groups` tells them whom to chase and
    for what.

    Statutory details are scored on the SECTION having been answered, not on the three
    numbers being present. A first-time employee has no UAN, no PF account and no ESIC
    number, and scoring them as missing would permanently cap exactly those joiners below
    100% for having done nothing wrong.
    """
    sub = doc.get("submission") or {}
    submitted = bool(doc.get("submitted_at")) or doc.get("pre_status") in (
        PreOnboardStatus.SUBMITTED.value, PreOnboardStatus.VERIFIED.value)

    required_docs = [t for t in doc_tasks if t.get("required")]
    doc_items = [(t["doc_type"], t.get("status") in DOC_SATISFYING_STATUSES)
                 for t in required_docs]

    # BGV counts as one item, and is satisfied when the file is clear OR no check has been
    # raised for this joiner at all -- §7.5 Stage 4 is explicitly "where applicable", and
    # "not applicable" is not "incomplete".
    #
    # Keyed on `checks` alone, deliberately: `verification_state` lists every required type
    # as outstanding the moment it is asked, including for a joiner nobody has raised a
    # check against, so reading `outstanding` here would score every such joiner as failing
    # a step their company never asked for.
    bgv_ok = (not verification.get("checks")) or bool(verification.get("cleared"))

    human_tasks = [i for i in (doc.get("checklist") or [])
                   if i.get("key") not in SYSTEM_CHECKLIST_KEYS]

    groups = [
        {"key": "documents", "label": "Documents", "items": doc_items},
        {"key": "personal", "label": "Personal details", "items": [
            ("PAN or Aadhaar", bool(sub.get("pan") or sub.get("aadhaar"))),
            ("Date of birth", bool(sub.get("date_of_birth"))),
            ("Current address", bool(sub.get("address"))),
            ("Emergency contact", bool(sub.get("emergency_contact_name"))),
        ]},
        {"key": "bank", "label": "Bank details", "items": [
            ("Account number", bool(sub.get("bank_account"))),
            ("IFSC", bool(sub.get("bank_ifsc"))),
        ]},
        {"key": "statutory", "label": "Statutory details", "items": [
            ("Statutory section answered", submitted),
        ]},
        {"key": "bgv", "label": "Background verification", "items": [
            ("Verification cleared", bgv_ok),
        ]},
        {"key": "tasks", "label": "Other mandatory tasks", "items": (
            [("Joining date", bool(doc.get("joining_date")))]
            + [(i.get("label") or i.get("key"), bool(i.get("done"))) for i in human_tasks]
        )},
    ]

    out_groups, missing = [], []
    done_total = total = 0
    for g in groups:
        items = g["items"]
        done = sum(1 for _, ok in items if ok)
        gaps = [label for label, ok in items if not ok]
        done_total += done
        total += len(items)
        missing.extend(f"{g['label']}: {label}" for label in gaps)
        out_groups.append({
            "key": g["key"], "label": g["label"],
            "done": done, "total": len(items),
            "percent": int(round(done * 100 / len(items))) if items else 100,
            "missing": gaps,
        })

    return {
        "percent": int(round(done_total * 100 / total)) if total else 0,
        "done": done_total, "total": total,
        "groups": out_groups,
        "missing": missing,
    }


def _id_blockers(doc: dict, doc_tasks: list = None) -> list:
    """Everything standing between this onboarding and an Employee ID.

    Returned as a list rather than a bool so the UI can say *why* the button is disabled.
    An unexplained disabled control is the most common source of "the system is broken"
    tickets.
    """
    blockers = []
    if doc.get("employee_id"):
        blockers.append("An Employee ID has already been issued.")
    if doc.get("pre_status") != PreOnboardStatus.VERIFIED.value:
        blockers.append("KYC documents have not been verified.")
    if doc.get("bg_verification") == BgVerification.FLAGGED.value:
        blockers.append("Background verification is flagged.")
    if not doc.get("joining_date"):
        blockers.append("A joining date has not been set.")
    # ── §7.5 Stage 6 ── "HR Verifies Joining -> Confirm Actual DOJ -> Generate Employee
    # ID". An ID issued for somebody nobody confirmed had turned up is the one thing this
    # stage exists to prevent.
    if not doc.get("actual_doj"):
        blockers.append("Joining has not been confirmed — record the actual date they "
                        "reported.")
    blockers.extend(_document_blockers(doc_tasks or []))
    return blockers


async def confirm_joining(actor: dict, company_id: str, onb_no: str,
                          payload: dict) -> dict:
    """HR confirming somebody actually reported, and on what date (§7.5 Stage 6).

    The step between "we expected them" and "they are an employee". It is separate from
    issuing the Employee ID because the two answer different questions -- did they turn up,
    and what are they now -- and because a joiner who starts a week late needs the real
    date recorded before payroll and probation are computed from it.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    if doc.get("employee_id"):
        raise HTTPException(
            status_code=409,
            detail="An Employee ID has already been issued for this joiner.")

    actual = clean_text(payload.get("actual_doj"), limit=10)
    if not actual or not is_iso_date(actual):
        raise HTTPException(
            status_code=422,
            detail="Enter the date they actually joined, as YYYY-MM-DD.")
    if actual > datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        raise HTTPException(
            status_code=422,
            detail=("The actual joining date cannot be in the future. Confirm joining on "
                    "or after the day they report."))

    updates = {
        "actual_doj": actual,
        "joining_confirmed_at": datetime.now(timezone.utc),
        "joining_confirmed_by": _actor_name(actor),
        "joining_note": clean_text(payload.get("note"), limit=2000),
    }
    for field in ASSIGNMENT_FIELDS:
        value = payload.get(field)
        value = getattr(value, "value", value)
        if value is not None:
            updates[field] = clean_text(value, limit=140) if isinstance(value, str) else value

    now = updates["joining_confirmed_at"]
    updates["updated_at"] = now

    # ── §7.5 Stage 8 ── "Once joining is confirmed, the system automatically creates
    # onboarding tasks". The items already exist on the case; what happens here is that the
    # IT, Admin and Reporting Manager ones become live work with a date on them, and the
    # people who own them are told. Before this they sat in one undifferentiated list that
    # read as HR's job and that nobody outside HR was ever told about.
    checklist = [
        {**item,
         "owner": item.get("owner") or task_owner(item.get("key")),
         "assigned_at": item.get("assigned_at") or (
             now if (item.get("owner") or task_owner(item.get("key")))
             in TASKS_ASSIGNED_AT_JOINING else None)}
        for item in (doc.get("checklist") or [])
    ]
    updates["checklist"] = checklist

    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_ONBOARD_DETAILS, ENTITY_ONBOARDING, onb_no,
                f"joining confirmed for {actual}", company_id)
    await _notify_joining_tasks(company_id, {**doc, **updates})
    return await _refresh(actor, company_id, onb_no)


async def _notify_joining_tasks(company_id: str, doc: dict) -> None:
    """Tell IT/Admin and the reporting manager what is now theirs (§7.5 Stage 8).

    Best-effort: joining has already been confirmed and the tasks are already assigned on
    the record, so a notification that could not be sent must not undo any of it.

    NOTE: this codebase has no IT or Admin role -- HrmsRole stops at HR/Manager/Finance --
    so those tasks are routed to HR and Admin governance holders rather than to a dedicated
    IT queue. The task itself still names its true owner, so the work is attributable even
    though the routing is approximate.
    """
    name = doc.get("candidate_name") or doc.get("uk")
    joined = doc.get("actual_doj")
    by_owner = {}
    for item in doc.get("checklist") or []:
        owner = item.get("owner")
        if owner in TASKS_ASSIGNED_AT_JOINING and not item.get("done"):
            by_owner.setdefault(owner, []).append(item.get("label"))

    try:
        for owner in (TASK_OWNER_IT, TASK_OWNER_ADMIN):
            tasks = by_owner.get(owner)
            if not tasks:
                continue
            await notify_hrms_role(
                company_id, ["HR", "admin"],
                f"{owner} tasks for {name}",
                f"{name} joined on {joined}. Outstanding {owner} tasks: "
                + "; ".join(tasks) + ".",
                link="/hrms/onboarding")

        manager_tasks = by_owner.get(TASK_OWNER_MANAGER)
        if manager_tasks and doc.get("reporting_manager_id"):
            await notify_user(
                doc["reporting_manager_id"],
                f"Induction tasks for {name}",
                f"{name} joined on {joined}. Your tasks: "
                + "; ".join(manager_tasks) + ".",
                link="/hrms/onboarding")
    except Exception as e:                          # pragma: no cover - defensive
        logger.warning("Stage 8 task notifications not sent for %s: %s",
                       doc.get("onb_no"), e)


async def generate_employee_id(actor: dict, company_id: str, onb_no: str) -> dict:
    """Issue the Employee ID and create the employee record.

    This is the point the pipeline has been heading towards since Phase 3: a candidate stops
    being a candidate. Everything downstream (leave, attendance, payroll, reporting) keys off
    the record created here.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    from app.services.hrms_config_service import onboarding_doc_types
    blockers = _id_blockers(doc, _document_tasks(doc, await onboarding_doc_types(company_id)))
    if blockers:
        raise HTTPException(status_code=409, detail=" ".join(blockers))

    year = datetime.now(timezone.utc).year
    employee_code = await next_business_id("employee", str(company_id), year)
    now = datetime.now(timezone.utc)

    submission = doc.get("submission") or {}
    extra = {field: submission.get(field) for field in (
        "pan", "aadhaar", "date_of_birth", "gender", "address",
        "bank_name", "bank_account", "bank_ifsc",
        "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
    )}

    # Claim the ID on the onboarding FIRST, conditioned on it still being unissued. Two
    # simultaneous clicks then produce one employee, not two: the loser's update matches
    # nothing and it stops before creating a duplicate record.
    claimed = await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id), "employee_id": None},
        {"$set": {"employee_id": employee_code, "employee_created_at": now,
                  "status": OnboardStatus.ONBOARDING.value, "updated_at": now}})
    if getattr(claimed, "modified_count", 0) == 0:
        raise HTTPException(
            status_code=409, detail="An Employee ID has already been issued.")

    try:
        await employees.create_from_onboarding(
            actor, company_id,
            employee_code=employee_code,
            identity={"name": doc.get("candidate_name"),
                      "email": doc.get("candidate_email"),
                      "mobile": doc.get("candidate_mobile")},
            source_uk=doc.get("uk"),
            # The ACTUAL date, not the planned one -- tenure, probation and payroll all
            # run from when somebody really started.
            joined_on=doc.get("actual_doj") or doc.get("joining_date"),
            department_id=doc.get("department_id"),
            designation_id=doc.get("designation_id"),
            assignment={f: doc.get(f) for f in ASSIGNMENT_FIELDS
                        if doc.get(f) is not None},
            extra=extra)
    except Exception:
        # The employee record is the point of the operation. If it could not be written, the
        # claim above is a lie -- release it so the operator can retry rather than leaving an
        # onboarding that believes it produced an employee that does not exist.
        await get_collection(COLL_ONBOARDING).update_one(
            {"onb_no": onb_no, "company_id": str(company_id)},
            {"$set": {"employee_id": None, "employee_created_at": None,
                      "status": OnboardStatus.PRE_ONBOARDING.value, "updated_at": now}})
        raise

    fresh = await _get(company_id, onb_no)
    checklist = _set_item(fresh.get("checklist") or [], "employee_id", True, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"checklist": checklist, "updated_at": now}})

    # An Employee ID means the person has joined.
    await _advance_candidate(actor, company_id, doc.get("uk"), AppStatus.JOINED)

    # ── §7.5 Stage 10 ── open the probation review now, at joining, rather than leaving it
    # to be remembered later. A probation record nobody created is a probation nobody
    # reviews, and `GET /probation/due` is only honest if every joiner is in it.
    #
    # Opened for EVERY joiner, not only the internal track. The track guard that used to
    # be here dated from when a client-track hire was somebody else's payroll; that track
    # is decommissioned, so all the guard did was silently skip probation for any record
    # still carrying the old default.
    #
    # Deliberately best-effort: a probation record is important, but failing the handover
    # over it would strand an employee who HAS been created. The warning is loud enough to
    # act on and the record can be opened by hand.
    try:
        from app.services.hrms_probation_service import open_probation
        await open_probation(actor, company_id, {
            "employee_code": employee_code,
            "request_no": doc.get("request_no"),
            "uk": doc.get("uk"),
            # The ACTUAL joining date. Probation measured from the planned date would end
            # early for anybody who started late -- the one case where the two differ and
            # the difference matters most.
            "started_on": doc.get("actual_doj") or doc.get("joining_date"),
            "reviewer_id": doc.get("reporting_manager_id"),
        }, silent=True)
    except Exception as e:
        print(f"[WARN] HRMS could not open probation for {employee_code}: {e}")

    # ── Phase ORIENT-1 ── §22.3 step 200: "On employee activation, system assigns an
    # onboarding orientation/training plan". Unlike probation above, this runs for BOTH
    # tracks — the BA doc draws no internal/client distinction here, and it is a no-op
    # (returns None) when no matching plan template exists yet, so it costs nothing for a
    # company that has not set one up. Best-effort for the same reason: an Employee ID
    # already issued must not be undone by a plan-assignment failure.
    try:
        from app.services.hrms_orientation_service import assign_on_activation
        await assign_on_activation(
            actor, company_id, employee_code,
            department_id=doc.get("department_id"), designation_id=doc.get("designation_id"))
    except Exception as e:
        print(f"[WARN] HRMS could not assign an orientation plan for {employee_code}: {e}")

    await audit(actor, AUDIT_EMPLOYEE_ID_ISSUED, ENTITY_ONBOARDING, onb_no,
                f"{employee_code} for {doc.get('candidate_name')}", company_id)
    await notify_hrms_role(
        company_id, ["HR", "MD"], f"Employee created: {doc.get('candidate_name')}",
        f"{employee_code} has been issued. They now appear in the employee directory and "
        "can be linked to a login account.",
        kind="success", link="/hrms/employees", email=True)

    return await _refresh(actor, company_id, onb_no)


async def _refresh(actor: dict, company_id: str, onb_no: str) -> dict:
    """Re-read, settle completion, and return the view. Every mutator ends here."""
    doc = await _get(company_id, onb_no)
    checklist = doc.get("checklist") or []

    if (checklist and all(item.get("done") for item in checklist)
            and doc.get("status") != OnboardStatus.COMPLETED.value):
        now = datetime.now(timezone.utc)
        await get_collection(COLL_ONBOARDING).update_one(
            {"onb_no": onb_no, "company_id": str(company_id),
             "status": {"$ne": OnboardStatus.COMPLETED.value}},
            {"$set": {"status": OnboardStatus.COMPLETED.value,
                      "completed_at": now, "updated_at": now}})
        await _advance_candidate(actor, company_id, doc.get("uk"),
                                 AppStatus.EMPLOYEE_CREATED)
        await audit(actor, AUDIT_ONBOARD_COMPLETED, ENTITY_ONBOARDING, onb_no,
                    doc.get("candidate_name"), company_id)
        await notify_hrms_role(
            company_id, ["HR"], f"Onboarding complete: {doc.get('candidate_name')}",
            f"Every step of {onb_no} is done.", kind="success", link="/hrms/onboarding")

    return await get_onboarding(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# Uploads
# ─────────────────────────────────────────────────────────────
def _next_version(existing: list, doc_type: Optional[str]) -> int:
    """The version number a new upload of `doc_type` takes.

    Re-uploading a document does not overwrite the old one -- §7.5 Stage 3 asks for the
    version to be retained, and a replaced document is the evidence for why it was replaced.
    An untyped file has no series to belong to, so it is always v1.
    """
    if not doc_type:
        return 1
    versions = [int(d.get("version") or 1) for d in existing or []
                if d.get("doc_type") == doc_type]
    return (max(versions) + 1) if versions else 1


def _latest_by_type(documents: list) -> dict:
    """The current version of each typed document, keyed by type.

    Superseded versions stay in `documents` but are not what the gate or the UI reads.
    """
    latest = {}
    for d in documents or []:
        doc_type = d.get("doc_type")
        if not doc_type:
            continue
        current = latest.get(doc_type)
        if not current or int(d.get("version") or 1) >= int(current.get("version") or 1):
            latest[doc_type] = d
    return latest


async def _store_documents(uploads: list, *, existing_count: int, source: str,
                           doc_types: dict = None, existing: list = None) -> list:
    """Upload and describe each file.

    `doc_type` is carried through when the caller supplies one, which is what turns a pile
    of files into the answerable "which joining documents are still missing". It is kept
    optional: HR attaching a one-off letter should not have to invent a category, and the
    pre-typed catalogue exists for the tasks the new hire is actually set.
    """
    if existing_count + len(uploads) > MAX_ONBOARD_DOCUMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"A maximum of {MAX_ONBOARD_DOCUMENTS} documents can be attached.")

    stored = []
    for i, upload in enumerate(uploads):
        doc_type = None
        if isinstance(upload, dict):
            doc_type = clean_text(upload.get("doc_type"), limit=120)
            if doc_type and doc_types is not None and doc_type not in doc_types:
                raise HTTPException(
                    status_code=422,
                    detail=f'"{doc_type}" is not one of the joining documents this company '
                           f"asks for.")
        raw, name, mime = decode_upload(upload, label=doc_type or f"Document {i + 1}")
        if not raw:
            continue
        import io
        from app.services.s3_service import upload_file_to_s3_with_key
        try:
            result = upload_file_to_s3_with_key(io.BytesIO(raw), f"onboard_{name}", mime)
        except Exception as e:
            print(f"[WARN] HRMS onboarding upload failed: {e}")
            raise HTTPException(
                status_code=503,
                detail="Your document could not be uploaded right now. Please try again.")
        now = datetime.now(timezone.utc)
        version = _next_version((existing or []) + stored, doc_type)
        stored.append({
            "name": name,
            "doc_type": doc_type,
            "version": version,
            # Every document starts unreviewed. HR moves it from here (§7.5 Stage 3) --
            # nothing arrives pre-verified, including a file HR uploaded themselves, because
            # "somebody attached this" and "somebody checked this" are different claims.
            "status": DocStatus.PENDING.value,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
            "history": [{"status": DocStatus.PENDING.value,
                         "note": f"Uploaded by {'HR' if source == 'hr' else 'the candidate'}"
                                 + (f" (v{version})" if version > 1 else ""),
                         "by": source, "at": now}],
            "key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime,
            "source": source,
            "uploaded_at": now,
        })
    return stored


# ─────────────────────────────────────────────────────────────
# The public pre-onboarding form
# ─────────────────────────────────────────────────────────────
async def get_public_onboarding(code: str) -> dict:
    """What the new hire sees behind their pre-onboarding link.

    Exposes only what they need to recognise the form as genuinely theirs. No company_id, no
    requisition number, no offer terms, no internal status beyond "already submitted".
    """
    doc = await get_collection(COLL_ONBOARDING).find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(
            status_code=410,
            detail="This form is closed. Please contact the HR team if you need to update "
                   "your details.")

    # The upload tasks this company sets, and which of them have already arrived. Sent to
    # the portal so it can show the list as tasks rather than one anonymous file picker.
    from app.services.hrms_config_service import onboarding_doc_types
    catalogue = await onboarding_doc_types(doc.get("company_id"))
    have = {d.get("doc_type") for d in (doc.get("documents") or []) if d.get("doc_type")}

    return {
        "ok": True,
        "already_submitted": doc.get("pre_status") != PreOnboardStatus.PENDING.value,
        "candidate_name": doc.get("candidate_name"),
        "designation": doc.get("designation"),
        "joining_date": doc.get("joining_date"),
        "submitted_at": doc.get("submitted_at"),
        "max_documents": MAX_ONBOARD_DOCUMENTS,
        "max_references": MAX_REFERENCES,
        "sections": [dict(s) for s in ONBOARD_SECTIONS],
        "document_tasks": [
            {"doc_type": label, "required": bool(required), "uploaded": label in have}
            for label, required in catalogue.items()
        ],
    }


def _validate_submission(payload: dict) -> dict:
    """Validate the new hire's details SERVER-SIDE.

    The source enforced PAN-or-Aadhaar in the browser only (BACKEND_ANALYSIS 8), so any
    request that skipped the form put an employee into payroll with no identity document at
    all. Everything below runs regardless of what the client did.
    """
    out = {}

    pan = (payload.get("pan") or "").strip().upper()
    aadhaar = (payload.get("aadhaar") or "").strip()
    if not pan and not aadhaar:
        raise HTTPException(
            status_code=422,
            detail="Provide your PAN or your Aadhaar number — at least one is required.")
    if pan:
        if not PAN_RE.match(pan):
            raise HTTPException(status_code=422, detail="PAN is not valid (e.g. ABCDE1234F).")
        out["pan"] = pan
    if aadhaar:
        aadhaar = aadhaar.replace(" ", "")
        if not AADHAAR_RE.match(aadhaar):
            raise HTTPException(status_code=422, detail="Aadhaar must be 12 digits.")
        out["aadhaar"] = aadhaar

    for field, limit in (("passport", 40), ("driving_license", 40)):
        out[field] = clean_text(payload.get(field), limit=limit)

    dob = clean_text(payload.get("date_of_birth"), limit=10)
    if dob:
        if not is_iso_date(dob):
            raise HTTPException(
                status_code=422,
                detail="Date of birth must be a valid date in YYYY-MM-DD format.")
        if dob >= datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            raise HTTPException(status_code=422, detail="Date of birth must be in the past.")
        out["date_of_birth"] = dob

    gender = payload.get("gender")
    gender = getattr(gender, "value", gender)
    if gender:
        try:
            out["gender"] = Gender(gender).value
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown value for gender.")

    ifsc = (payload.get("bank_ifsc") or "").strip().upper()
    if ifsc:
        if not IFSC_RE.match(ifsc):
            raise HTTPException(
                status_code=422, detail="IFSC code is not valid (e.g. HDFC0001234).")
        out["bank_ifsc"] = ifsc

    account = (payload.get("bank_account") or "").strip()
    if account:
        if not account.isdigit() or not (6 <= len(account) <= 20):
            raise HTTPException(
                status_code=422, detail="Bank account number must be 6-20 digits.")
        out["bank_account"] = account

    # ── §7.5 "Statutory information" ── UAN and ESIC are 12 and 17 digits by definition, so
    # a typo is catchable here rather than at the first payroll run. All three are optional:
    # a first-time employee genuinely has none of them, and demanding one would block the
    # people most likely to be joining their first job.
    for field, digits, label in (("uan", 12, "UAN"), ("esic_number", 17, "ESIC number")):
        raw = (payload.get(field) or "").strip().replace(" ", "")
        if raw:
            if not raw.isdigit() or len(raw) != digits:
                raise HTTPException(
                    status_code=422, detail=f"{label} must be {digits} digits.")
            out[field] = raw

    for field, limit in (("address", 500), ("permanent_address", 500),
                         ("personal_email", 180), ("personal_phone", 30),
                         ("bank_name", 120), ("bank_branch", 140),
                         ("bank_account_name", 140),
                         ("pf_number", 40), ("previous_employer", 140),
                         ("emergency_contact_name", 120),
                         ("emergency_contact_phone", 30),
                         ("emergency_contact_relation", 60),
                         ("asset_requirements", 1000)):
        out[field] = clean_text(payload.get(field), limit=limit)

    email = (out.get("personal_email") or "").strip().lower()
    if email:
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        out["personal_email"] = email

    references = payload.get("references") or []
    if len(references) > MAX_REFERENCES:
        raise HTTPException(
            status_code=422,
            detail=f"A maximum of {MAX_REFERENCES} references can be provided.")
    out["references"] = [
        {"name": clean_text((r or {}).get("name"), limit=120),
         "relation": clean_text((r or {}).get("relation"), limit=80),
         "phone": clean_text((r or {}).get("phone"), limit=30)}
        for r in references
        if isinstance(r, dict) and clean_text(r.get("name"), limit=120)
    ]
    return out


async def submit_public_onboarding(code: str, payload: dict) -> dict:
    """Record the new hire's pre-onboarding submission."""
    doc = await get_collection(COLL_ONBOARDING).find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(status_code=410, detail="This form is closed.")
    if doc.get("pre_status") != PreOnboardStatus.PENDING.value:
        # Re-submitting would overwrite details a human has already verified.
        raise HTTPException(
            status_code=409,
            detail="Your details have already been submitted. Contact the HR team if "
                   "something needs to change.")

    details = _validate_submission(payload)

    from app.services.hrms_config_service import onboarding_doc_types
    catalogue = await onboarding_doc_types(doc.get("company_id"))
    stored = await _store_documents(payload.get("documents") or [],
                                    existing_count=len(doc.get("documents") or []),
                                    source="candidate", doc_types=catalogue,
                                    existing=doc.get("documents") or [])

    # Required documents are checked AFTER the uploads are validated but BEFORE the record
    # is written, so a submission that is refused for a missing document does not leave the
    # ones that did arrive stranded against a form still marked Pending.
    have = {d.get("doc_type") for d in
            (doc.get("documents") or []) + stored if d.get("doc_type")}
    missing = [label for label, required in catalogue.items()
               if required and label not in have]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=("These documents are still needed before you can submit: "
                    + ", ".join(missing) + "."))

    now = datetime.now(timezone.utc)
    # Conditioned on Pending so two rapid submits cannot both write.
    result = await get_collection(COLL_ONBOARDING).update_one(
        {"access_code": code, "pre_status": PreOnboardStatus.PENDING.value},
        {"$set": {"submission": details,
                  "pre_status": PreOnboardStatus.SUBMITTED.value,
                  "submitted_at": now,
                  "asset_requirements": details.get("asset_requirements")
                  or doc.get("asset_requirements"),
                  "updated_at": now},
         "$push": {"documents": {"$each": stored}}})
    if getattr(result, "matched_count", 0) == 0:
        raise HTTPException(
            status_code=409, detail="Your details have already been submitted.")

    company_id = doc.get("company_id")
    await audit(None, AUDIT_ONBOARD_SUBMITTED, ENTITY_ONBOARDING, doc["onb_no"],
                doc.get("candidate_name"), company_id)
    await notify_hrms_role(
        company_id, ["HR"], f"Pre-onboarding submitted: {doc.get('candidate_name')}",
        f"{doc['onb_no']} — their details and {len(stored)} document(s) are ready to verify.",
        link="/hrms/onboarding", email=True)
    if doc.get("created_by"):
        await notify_user(
            doc["created_by"], f"Pre-onboarding submitted: {doc.get('candidate_name')}",
            f"{doc['onb_no']} is ready to verify.", link="/hrms/onboarding")

    return {
        "ok": True,
        "message": "Thank you — your details have been received. The HR team will verify "
                   "them and be in touch before your joining date.",
    }
