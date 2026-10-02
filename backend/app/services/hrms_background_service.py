"""Background verification, and the gate it puts in front of an offer.

    Background Verification -> HR Approval -> Offer Letter -> Onboarding

-- Why this is not the onboarding `bg_verification` flag ------------------------------------
Onboarding already carries one, and it cannot do this job: onboarding starts AFTER an offer
is accepted, so a check recorded there can only ever confirm a commitment already made. The
requirement is that verification precedes the offer, which needs a record attached to the
CANDIDATE and readable at offer time.

The two are complementary, not duplicates. This one gates the offer; the onboarding flag
stays what it always was -- the pre-joining check on a hire already agreed.

-- Two capabilities, not one -----------------------------------------------------------------
Recording a check and approving the verification are separate capabilities on purpose. The
recruiter who chased the references is not automatically the signature that says the file is
clean, and a company that wants two pairs of eyes can withdraw one grant without touching the
other. HR holds both by default because requirement 8 names HR as the approver.

-- The gate applies to BOTH tracks -----------------------------------------------------------
Internal hires as well as client ones. That is a behaviour change for a flow that was already
live, so it follows the module's rule for every other gate: the only way past it is an
approved exception (`Background Verification Waived`), never a flag on a request body. That
also gives anybody already mid-pipeline when this shipped a documented, attributable route
through, rather than a dead end.

House convention: services validate, gate and audit; routes only check the capability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_BACKGROUND_APPROVED, AUDIT_BACKGROUND_RECORDED, AUDIT_BACKGROUND_REJECTED,
    BACKGROUND_CLEARS_OFFER, COLL_BACKGROUND_CHECKS, COLL_CANDIDATES, ENTITY_CANDIDATE,
    REQUIRED_BACKGROUND_CHECKS, BackgroundApprovalStatus, BackgroundCheckStatus,
    BackgroundCheckType, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id

ENTITY_BACKGROUND = "background check"

# Where the approval lives. On the CANDIDATE rather than on a check, because it is a verdict
# on the whole file: "these checks, together, are sufficient". Putting it on one check would
# make it ambiguous which check the signature covered.
APPROVAL_FIELD = "background_approval"


def _clean(value, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _out(doc: dict) -> dict:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
async def list_checks(actor: dict, company_id: str, *, uk: str = None,
                      status: str = None, limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if uk:
        query["uk"] = uk
    if status:
        if status not in {s.value for s in BackgroundCheckStatus}:
            raise HTTPException(
                status_code=422,
                detail=(f"Status must be one of: "
                        f"{', '.join(s.value for s in BackgroundCheckStatus)}."))
        query["status"] = status
    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_BACKGROUND_CHECKS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return {"checks": [_out(r) for r in rows], "total": len(rows)}


async def get_check(company_id: str, bgv_no: str) -> Optional[dict]:
    return _out(await get_collection(COLL_BACKGROUND_CHECKS).find_one(
        {"bgv_no": bgv_no, "company_id": str(company_id)}))


async def verification_state(company_id: str, uk: str) -> dict:
    """Everything the offer gate and the UI need about one candidate's verification.

    The LATEST check of each type decides, not the first: a check re-run after an
    inconclusive result must be able to clear what the earlier one left open, and the
    alternative -- "any cleared check of this type" -- would let a stale pass paper over a
    later flag.
    """
    rows = await get_collection(COLL_BACKGROUND_CHECKS).find(
        {"company_id": str(company_id), "uk": uk}).sort("created_at", 1).to_list(200)

    latest = {}
    for row in rows:                     # ascending, so the last write of a type wins
        latest[row.get("check_type")] = row

    required = [t.value for t in REQUIRED_BACKGROUND_CHECKS]
    outstanding, flagged = [], []
    for check_type in required:
        row = latest.get(check_type)
        if not row:
            outstanding.append(check_type)
        elif row.get("status") == BackgroundCheckStatus.FLAGGED.value:
            flagged.append(check_type)
        elif row.get("status") not in BACKGROUND_CLEARS_OFFER:
            outstanding.append(check_type)

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)}, {APPROVAL_FIELD: 1, "candidate_name": 1})
    approval = (candidate or {}).get(APPROVAL_FIELD) or {
        "status": BackgroundApprovalStatus.NOT_REQUESTED.value}

    return {
        "uk": uk,
        "candidate_name": (candidate or {}).get("candidate_name"),
        "required": required,
        "checks": [_out(r) for r in rows],
        "latest_by_type": {k: _out(v) for k, v in latest.items()},
        "outstanding": outstanding,
        "flagged": flagged,
        "checks_complete": not outstanding and not flagged,
        "approval": approval,
        # The one question the offer screen actually asks. Kept as a computed field rather
        # than a stored flag so it can never disagree with the rows it is derived from.
        "cleared_for_offer": (not outstanding and not flagged
                              and approval.get("status")
                              == BackgroundApprovalStatus.APPROVED.value),
    }


# ─────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────
async def assert_background_cleared(company_id: str, candidate: dict) -> None:
    """Refuse an offer until verification is complete AND signed off.

    Called before any write on offer creation, so a refusal leaves nothing behind.

    Reads the gate through `approved_exception_for` rather than testing a flag, so the only
    way past it is a record somebody signed -- the same mechanism the reference, telephonic
    and statutory gates use.
    """
    uk = (candidate or {}).get("uk")
    if not uk:
        return

    state = await verification_state(company_id, uk)
    if state["cleared_for_offer"]:
        return

    from app.services.hrms_exception_service import approved_exception_for
    waiver = await approved_exception_for(
        company_id, "background", candidate.get("request_no"), uk)
    if waiver:
        return

    name = candidate.get("candidate_name") or uk
    if state["flagged"]:
        raise HTTPException(
            status_code=409,
            detail=(f"{name}'s background verification is FLAGGED on: "
                    f"{', '.join(state['flagged'])}. An offer cannot be raised on a flagged "
                    f"check. Resolve it, or log an approved Background Verification Waived "
                    f"exception."))
    if state["outstanding"]:
        raise HTTPException(
            status_code=409,
            detail=(f"{name}'s background verification is not complete. Outstanding: "
                    f"{', '.join(state['outstanding'])}. Complete the checks, then have HR "
                    f"approve the verification before raising an offer."))
    # Checks are done; nobody has signed.
    raise HTTPException(
        status_code=409,
        detail=(f"{name}'s checks are complete but the verification has not been approved. "
                f"HR must approve it before an offer can be raised."))


# ─────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────
async def record_check(actor: dict, company_id: str, payload: dict) -> dict:
    """Record one background check against a candidate."""
    uk = _clean(payload.get("uk"), 40)
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    raw_type = getattr(payload.get("check_type"), "value", payload.get("check_type"))
    try:
        check_type = BackgroundCheckType(raw_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Check type must be one of: "
                    f"{', '.join(t.value for t in BackgroundCheckType)}."))

    raw_status = getattr(payload.get("status"), "value", payload.get("status"))
    try:
        status = BackgroundCheckStatus(raw_status or BackgroundCheckStatus.PENDING.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Status must be one of: "
                    f"{', '.join(s.value for s in BackgroundCheckStatus)}."))

    completed_on = _clean(payload.get("completed_on"), 10)
    if completed_on and not is_iso_date(completed_on):
        raise HTTPException(
            status_code=422, detail="The completion date must be a valid YYYY-MM-DD date.")
    findings = _clean(payload.get("findings"), 4000)
    # A conclusion with no evidence behind it is not a check. Demanded on the two outcomes
    # that actually decide something; a Pending row is allowed to be empty because it is a
    # placeholder for work not yet done.
    if status in (BackgroundCheckStatus.CLEARED, BackgroundCheckStatus.FLAGGED) \
            and not findings:
        raise HTTPException(
            status_code=422,
            detail=(f'Record what the {check_type.value.lower()} check found. '
                    f'A "{status.value}" result with nothing behind it cannot be reviewed '
                    f"later."))

    now = datetime.now(timezone.utc)
    bgv_no = await next_business_id("background", str(company_id), now.year)
    doc = {
        "bgv_no": bgv_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "request_no": candidate.get("request_no"),
        "check_type": check_type.value,
        "status": status.value,
        "agency": _clean(payload.get("agency"), 160),
        "reference": _clean(payload.get("reference"), 120),
        "findings": findings,
        "completed_on": completed_on,
        "document_id": _clean(payload.get("document_id"), 40),
        "recorded_by": str((actor or {}).get("_id") or ""),
        "recorded_by_name": _actor_name(actor),
        "created_at": now,
        "updated_at": now,
        # SOP §13: a verification report is personal data about a named person and inherits
        # the candidate's own retention floor rather than a rule of its own.
        "retention_until": candidate.get("retention_until"),
    }
    await get_collection(COLL_BACKGROUND_CHECKS).insert_one(dict(doc))
    await audit(actor, AUDIT_BACKGROUND_RECORDED, ENTITY_BACKGROUND, bgv_no,
                f"{check_type.value}: {status.value} for {candidate.get('candidate_name')}",
                company_id)

    # A new check invalidates an approval given before it. Otherwise a signed-off file could
    # be reopened with a Flagged result and still read as cleared, which is the failure this
    # whole gate exists to prevent.
    await _void_approval_if_signed(actor, company_id, uk, check_type, status)
    # ── §7.5 Stage 4 ── "Result / Status -> Onboarding Case Updated". The onboarding
    # case reads its background status off these records rather than holding its own, so
    # every write here pushes the derived result onto any open case.
    await _sync_case(company_id, uk)
    return await get_check(company_id, bgv_no)


async def _sync_case(company_id: str, uk: str) -> None:
    """Update the candidate's open onboarding case with this verification result.

    Best-effort and late-imported: the check itself is already recorded, and a case that
    could not be updated must not undo it. Silent when the candidate has no open case,
    which is the normal situation for verification run before the offer.
    """
    try:
        from app.services.hrms_onboarding_service import sync_verification
        await sync_verification(company_id, uk)
    except Exception as e:                          # pragma: no cover - defensive
        print(f"[WARN] HRMS onboarding case not synced for {uk}: {e}")


async def _void_approval_if_signed(actor: dict, company_id: str, uk: str,
                                   check_type: BackgroundCheckType,
                                   status: BackgroundCheckStatus) -> None:
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)}, {APPROVAL_FIELD: 1})
    approval = (candidate or {}).get(APPROVAL_FIELD) or {}
    if approval.get("status") != BackgroundApprovalStatus.APPROVED.value:
        return
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {f"{APPROVAL_FIELD}.status": BackgroundApprovalStatus.PENDING.value,
                  f"{APPROVAL_FIELD}.voided_at": datetime.now(timezone.utc),
                  f"{APPROVAL_FIELD}.voided_reason":
                      f"A new {check_type.value} check was recorded ({status.value})."}})
    await audit(actor, AUDIT_BACKGROUND_RECORDED, ENTITY_CANDIDATE, uk,
                f"verification approval withdrawn -- a new {check_type.value} check was "
                f"recorded", company_id)


async def update_check(actor: dict, company_id: str, bgv_no: str, payload: dict) -> dict:
    """Edit a check -- typically to move it from Pending to a result."""
    coll = get_collection(COLL_BACKGROUND_CHECKS)
    current = await coll.find_one({"bgv_no": bgv_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Background check not found.")

    updates = {}
    if payload.get("status") is not None:
        raw = getattr(payload["status"], "value", payload["status"])
        try:
            updates["status"] = BackgroundCheckStatus(raw).value
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Status must be one of: "
                        f"{', '.join(s.value for s in BackgroundCheckStatus)}."))
    for field, limit in (("agency", 160), ("reference", 120), ("findings", 4000),
                         ("document_id", 40)):
        if payload.get(field) is not None:
            updates[field] = _clean(payload[field], limit)
    if payload.get("completed_on") is not None:
        value = _clean(payload["completed_on"], 10)
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="The completion date must be a valid YYYY-MM-DD date.")
        updates["completed_on"] = value
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    # The same rule create applies, checked against the MERGED record so an edit cannot
    # arrive at a conclusion with no evidence by supplying the two halves separately.
    merged = {**current, **updates}
    if merged.get("status") in (BackgroundCheckStatus.CLEARED.value,
                                BackgroundCheckStatus.FLAGGED.value) \
            and not merged.get("findings"):
        raise HTTPException(
            status_code=422,
            detail=f'Record what the check found before marking it "{merged["status"]}".')

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"bgv_no": bgv_no, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_BACKGROUND_RECORDED, ENTITY_BACKGROUND, bgv_no,
                f"updated: {', '.join(sorted(k for k in updates if k != 'updated_at'))}",
                company_id)
    if "status" in updates:
        await _void_approval_if_signed(
            actor, company_id, current["uk"],
            BackgroundCheckType(current["check_type"]),
            BackgroundCheckStatus(updates["status"]))
    # ── §7.5 Stage 4 ── "Result / Status -> Onboarding Case Updated". The onboarding
    # case reads its background status off these records rather than holding its own, so
    # every write here pushes the derived result onto any open case.
    await _sync_case(company_id, current["uk"])
    return await get_check(company_id, bgv_no)


async def decide_verification(actor: dict, company_id: str, uk: str,
                              payload: dict) -> dict:
    """HR's sign-off (or refusal) on a candidate's whole verification file.

    This is the step that unlocks the offer, so it holds the same standard probation
    confirmation and the retention purge do: a typed signature, and a refusal to sign for
    work that is not finished.
    """
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    decision = (payload.get("decision") or "").strip().title()
    if decision not in ("Approved", "Rejected"):
        raise HTTPException(status_code=422,
                            detail="The decision must be Approved or Rejected.")
    signature = _clean(payload.get("signature"), 140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this off. An approval nobody signed is not one.")

    state = await verification_state(company_id, uk)
    if decision == "Approved":
        # Approving an incomplete file would defeat the gate entirely -- the offer check
        # asks for BOTH complete checks and a signature, and this is the half a person
        # controls.
        if state["outstanding"]:
            raise HTTPException(
                status_code=409,
                detail=(f"These checks are still outstanding: "
                        f"{', '.join(state['outstanding'])}. Complete them before "
                        f"approving the verification."))
        if state["flagged"]:
            raise HTTPException(
                status_code=409,
                detail=(f"These checks are flagged: {', '.join(state['flagged'])}. "
                        f"A flagged verification cannot be approved -- resolve the check, "
                        f"or raise a Background Verification Waived exception instead."))

    now = datetime.now(timezone.utc)
    approval = {
        "status": (BackgroundApprovalStatus.APPROVED.value if decision == "Approved"
                   else BackgroundApprovalStatus.REJECTED.value),
        "decided_by": str((actor or {}).get("_id") or ""),
        "decided_by_name": _actor_name(actor),
        "decided_at": now,
        "signature": signature,
        "remarks": _clean(payload.get("remarks"), 2000),
        "checks_at_approval": state["required"],
    }
    # Conditioned on the approval as it was read, so two approvers cannot both sign and
    # leave one signature silently overwritten by the other.
    result = await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id),
         f"{APPROVAL_FIELD}.status": (candidate.get(APPROVAL_FIELD) or {}).get("status")},
        {"$set": {APPROVAL_FIELD: approval, "updated_at": now}})
    if not (result.modified_count or 0):
        raise HTTPException(
            status_code=409,
            detail="Somebody else decided this verification. Reload and try again.")

    await audit(actor,
                AUDIT_BACKGROUND_APPROVED if decision == "Approved"
                else AUDIT_BACKGROUND_REJECTED,
                ENTITY_CANDIDATE, uk,
                f"background verification {decision.lower()} by {_actor_name(actor)}"
                + (f": {approval['remarks']}" if approval.get("remarks") else ""),
                company_id)
    await _notify_decision(company_id, candidate, decision, approval)
    # ── §7.5 Stage 4 ── "Result / Status -> Onboarding Case Updated". The onboarding
    # case reads its background status off these records rather than holding its own, so
    # every write here pushes the derived result onto any open case.
    await _sync_case(company_id, uk)
    return await verification_state(company_id, uk)


async def _notify_decision(company_id: str, candidate: dict, decision: str,
                           approval: dict) -> None:
    """Tell whoever is waiting on this that the offer is unlocked (or is not).

    Late import and best-effort: the decision is already written, and a notification that
    cannot be sent must never undo it.
    """
    try:
        from app.services.hrms_notify_service import notify_hrms_role
        name = candidate.get("candidate_name")
        if decision == "Approved":
            await notify_hrms_role(
                company_id, ["HR"], f"Verification approved: {name}",
                f"{name}'s background verification was approved by "
                f"{approval['decided_by_name']}. An offer can now be raised.",
                kind="success", link="/hrms/background-checks")
        else:
            await notify_hrms_role(
                company_id, ["HR", "MD"], f"Verification REJECTED: {name}",
                f"{name}'s background verification was rejected by "
                f"{approval['decided_by_name']}. "
                + (approval.get("remarks") or "No offer may be raised."),
                kind="warning", link="/hrms/background-checks", email=True)
    except Exception as e:
        print(f"[WARN] HRMS verification notification failed: {e}")


async def pending_verifications(actor: dict, company_id: str) -> dict:
    """The work queue: candidates far enough along to need verification, and where each
    one stands. Selected and Offer-stage candidates only -- verifying somebody nobody has
    chosen yet is work done on spec."""
    from app.models.hrms import AppStatus
    watch = [AppStatus.SELECTED.value, AppStatus.OFFER_GENERATED.value]
    rows = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id), "application_status": {"$in": watch}},
        {"uk": 1, "candidate_name": 1, "request_no": 1, "application_status": 1}
    ).sort("updated_at", -1).to_list(300)

    out = []
    for row in rows:
        state = await verification_state(company_id, row["uk"])
        out.append({
            "uk": row["uk"],
            "candidate_name": row.get("candidate_name"),
            "request_no": row.get("request_no"),
            "application_status": row.get("application_status"),
            "outstanding": state["outstanding"],
            "flagged": state["flagged"],
            "checks_complete": state["checks_complete"],
            "approval_status": (state["approval"] or {}).get("status"),
            "cleared_for_offer": state["cleared_for_offer"],
        })
    return {"candidates": out, "total": len(out)}
