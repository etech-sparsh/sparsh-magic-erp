"""HRMS > assessments with dual review.

A pre-interview test, signed off by TWO people: HR, and the hiring manager who raised the
requisition. Both must pass for the candidate to reach interviews.

-- Why two reviewers -----------------------------------------------------------------
"HR liked them, the hiring manager did not" is exactly the disagreement worth surfacing
BEFORE an interview panel is booked. One signature hides it; two force it into the open.

The manager is resolved from the requisition's `created_by` -- the module's documented
design intent is that whoever raises a requisition becomes its hiring manager (Phase 3).

-- When there is only one reviewer ---------------------------------------------------
If the candidate has no requisition, or its raiser cannot be resolved, HR decides alone.
Requiring a second signature that nobody can give would strand the candidate forever, which
is a worse failure than a single sign-off.

-- The scoring hint is advisory, never decisive ---------------------------------------
`recommendation_for()` turns a score into Recommended / Borderline / Not Recommended so a
reviewer does not do arithmetic. It never sets the outcome. Both humans still choose.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    ASSESSABLE_STATUSES, AUDIT_ASSESSMENT_OPENED, AUDIT_ASSESSMENT_RESOLVED,
    AUDIT_ASSESSMENT_REVIEWED, AUDIT_ASSESSMENT_SENT, AUDIT_ASSESSMENT_SUBMITTED,
    AUDIT_STAGE_CHANGED, COLL_ASSESSMENTS, COLL_CANDIDATES, COLL_REQUISITIONS,
    ENTITY_ASSESSMENT, ENTITY_CANDIDATE, MAX_ASSESSMENT_ATTACHMENTS, SLOT_HR, SLOT_MANAGER,
    AppStatus, AssessmentStatus, Decision, HrmsRole, LinkKind, can_transition, is_iso_date,
    recommendation_for,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_access import hrms_role
from app.utils.hrms_public_guard import (
    CLOSED_LINK, INVALID_LINK, clean_text, decode_upload, new_access_code,
)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


async def _manager_id_for(company_id: str, request_no: Optional[str]) -> Optional[str]:
    """The hiring manager for an assessment: the raiser of its requisition."""
    if not request_no:
        return None
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)}, {"created_by": 1})
    return (req or {}).get("created_by") or None


def _slot_for(actor: dict, doc: dict) -> str:
    """Which reviewer slot this actor fills.

    The requisition raiser always fills the MANAGER slot -- even if they are also HR --
    because their opinion is being sought as the hiring manager. Everyone else fills the HR
    slot. This is what makes "both must agree" meaningful rather than one person signing
    twice.
    """
    actor_id = str(actor.get("_id") or "")
    if actor_id and actor_id == str(doc.get("manager_id") or ""):
        return SLOT_MANAGER
    return SLOT_HR


def _decisions_of(doc: dict) -> tuple:
    return doc.get("hr_decision") or None, doc.get("manager_decision") or None


def _is_resolved(doc: dict) -> bool:
    """Both required slots filled? The manager slot is only required when one exists."""
    hr, mgr = _decisions_of(doc)
    if not hr:
        return False
    return bool(mgr) if doc.get("manager_id") else True


def _outcome_of(doc: dict) -> Optional[str]:
    """Pass only when every filled slot passed. Either Fail decides it."""
    if not _is_resolved(doc):
        return None
    hr, mgr = _decisions_of(doc)
    decisions = [d for d in (hr, mgr) if d]
    return (Decision.PASS.value if all(d == Decision.PASS.value for d in decisions)
            else Decision.FAIL.value)


# -------------------------------------------------------------
# Authenticated side
# -------------------------------------------------------------
async def list_assessments(actor: dict, company_id: str, *, status: str = None,
                           uk: str = None, mine: bool = False, limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if uk:
        query["uk"] = uk

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_ASSESSMENTS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)

    actor_id = str(actor.get("_id") or "")
    out = []
    for r in rows:
        item = _out(r)
        # The access code is a credential. It is returned only while it is still usable, so
        # a Reviewed assessment cannot leak a working link into a screenshot or an export.
        if item.get("status") in (AssessmentStatus.COMPLETED.value,
                                  AssessmentStatus.REVIEWED.value):
            item.pop("access_code", None)
        slot = _slot_for(actor, r)
        item["my_slot"] = slot
        item["my_decision"] = r.get(f"{slot}_decision") or None
        item["awaiting_me"] = (
            r.get("status") == AssessmentStatus.COMPLETED.value and not item["my_decision"])
        item["lifecycle"] = _lifecycle(r)
        out.append(item)

    if mine:
        out = [a for a in out if a["awaiting_me"]]

    return {
        "assessments": out,
        "total": len(out),
        "stats": {
            "awaiting_candidate": sum(1 for a in out if a["status"] in (
                AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value)),
            "to_review": sum(1 for a in out if a["awaiting_me"]),
            "passed": sum(1 for a in out if a["lifecycle"] == "Passed"),
            "failed": sum(1 for a in out if a["lifecycle"] == "Failed"),
        },
    }


def _lifecycle(doc: dict) -> str:
    """The label HR reads, derived from status + both decisions."""
    status = doc.get("status")
    if status == AssessmentStatus.SENT.value:
        return "Assigned"
    if status == AssessmentStatus.OPENED.value:
        return "In Progress"
    if status == AssessmentStatus.COMPLETED.value:
        return "Submitted"
    outcome = _outcome_of(doc)
    return "Passed" if outcome == Decision.PASS.value else "Failed"


async def send_assessment(actor: dict, company_id: str, payload: dict) -> dict:
    """Issue an assessment to a candidate."""
    uk = (payload.get("uk") or "").strip()
    title = clean_text(payload.get("title"), limit=200)
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")
    if not title:
        raise HTTPException(status_code=422, detail="A title is required.")

    # `or 100` would be wrong here: 0 is falsy, so a deliberate zero would silently become
    # 100 and skip the validation below. Default only when the field is genuinely absent.
    raw_max = payload.get("max_score")
    try:
        max_score = float(100 if raw_max is None else raw_max)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Max score must be a number.")
    if max_score <= 0:
        raise HTTPException(status_code=422, detail="Max score must be greater than zero.")

    link = (payload.get("link") or "").strip()
    if link and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="The external test link must start with http:// or https://.")

    due = payload.get("due_date")
    if due and not is_iso_date(due):
        raise HTTPException(status_code=422, detail="Due date must be YYYY-MM-DD.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    status = candidate.get("application_status")
    if status not in {s.value for s in ASSESSABLE_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} is at "{status}". An assessment can '
                    f'only be sent to a candidate at the assessment stage.'))

    coll = get_collection(COLL_ASSESSMENTS)
    existing = await coll.find_one({
        "uk": uk, "company_id": str(company_id),
        "status": {"$in": [AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value,
                           AssessmentStatus.COMPLETED.value]},
    })
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{candidate.get("candidate_name")} already has an open assessment '
                    f'({existing["assessment_no"]}).'))

    year = datetime.now(timezone.utc).year
    assessment_no = await next_business_id("assessment", str(company_id), year)
    now = datetime.now(timezone.utc)
    request_no = candidate.get("request_no")

    doc = {
        "assessment_no": assessment_no,
        "access_code": new_access_code(),
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "request_no": request_no,
        # Resolved and STORED at send time, not looked up at review time: if the requisition
        # is later edited or deleted, the reviewer roster for an in-flight assessment must
        # not silently change under the people already reviewing it.
        "manager_id": await _manager_id_for(company_id, request_no),
        "title": title,
        "instructions": clean_text(payload.get("instructions"), limit=8000),
        "link": link or None,
        "max_score": max_score,
        "due_date": due or None,
        "status": AssessmentStatus.SENT.value,
        "hr_decision": None, "hr_decision_by": None, "hr_decision_at": None,
        "manager_decision": None, "manager_decision_by": None, "manager_decision_at": None,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
    }
    await coll.insert_one(dict(doc))

    # Phase 11-R, Item 1: record the link in the registry, in the same request, immediately
    # after the code is issued. Fire-and-forget by contract -- register_link never raises,
    # so a registry problem can never stop an assessment going out.
    from app.services.hrms_link_service import register_link
    await register_link(
        company_id=company_id, kind=LinkKind.ASSESSMENT, code=doc["access_code"],
        target_type="candidate", target_id=assessment_no, actor=actor,
        candidate_name=doc.get("candidate_name"), request_no=request_no,
        expires_at=due or None)

    # Move the candidate into the assessment stage if the graph allows it from here.
    if can_transition(status, AppStatus.ASSESSMENT_PENDING.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": uk, "company_id": str(company_id)},
            {"$set": {"application_status": AppStatus.ASSESSMENT_PENDING.value,
                      "updated_at": now}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{status} -> {AppStatus.ASSESSMENT_PENDING.value}", company_id)

    await audit(actor, AUDIT_ASSESSMENT_SENT, ENTITY_ASSESSMENT, assessment_no,
                f"{title} sent to {candidate.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_ASSESSMENT_SENT, ENTITY_CANDIDATE, uk,
                f"{assessment_no}: {title}", company_id)
    return _out(doc)


async def review_assessment(actor: dict, company_id: str, assessment_no: str,
                            payload: dict) -> dict:
    """Record one reviewer's Pass/Fail, and resolve the outcome once both have decided."""
    coll = get_collection(COLL_ASSESSMENTS)
    doc = await coll.find_one({"assessment_no": assessment_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Assessment not found.")

    if doc["status"] in (AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value):
        raise HTTPException(
            status_code=409,
            detail="This assessment has not been submitted yet — there is nothing to review.")
    if doc["status"] == AssessmentStatus.REVIEWED.value:
        raise HTTPException(
            status_code=409, detail="This assessment has already been fully reviewed.")

    raw = getattr(payload.get("decision"), "value", payload.get("decision"))
    try:
        decision = Decision(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Decision must be Pass or Fail.")

    score = payload.get("score")
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Score must be a number.")
        if score < 0 or score > float(doc.get("max_score") or 100):
            raise HTTPException(
                status_code=422,
                detail=f"Score must be between 0 and {doc.get('max_score')}.")

    slot = _slot_for(actor, doc)
    now = datetime.now(timezone.utc)
    updates = {
        f"{slot}_decision": decision.value,
        f"{slot}_decision_by": str(actor.get("_id") or ""),
        f"{slot}_decision_by_name": _actor_name(actor),
        f"{slot}_decision_at": now,
        f"{slot}_remarks": clean_text(payload.get("remarks"), limit=4000),
        "updated_at": now,
    }
    if score is not None:
        updates["score"] = score
        updates["recommendation"] = recommendation_for(score, doc.get("max_score"))

    # Compare-and-swap on the slot: two reviewers clicking at once must not overwrite each
    # other, and a second click by the same reviewer must not silently re-decide.
    result = await coll.update_one(
        {"assessment_no": assessment_no, "company_id": str(company_id),
         f"{slot}_decision": None},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="That decision has already been recorded for this reviewer.")

    await audit(actor, AUDIT_ASSESSMENT_REVIEWED, ENTITY_ASSESSMENT, assessment_no,
                f"{slot} decision: {decision.value}", company_id)

    fresh = await coll.find_one({"assessment_no": assessment_no})
    if _is_resolved(fresh):
        await _resolve(actor, company_id, fresh)
    else:
        # Nudge whoever still owes a decision, rather than leaving the submission parked.
        pending_slot = SLOT_MANAGER if slot == SLOT_HR else SLOT_HR
        if pending_slot == SLOT_MANAGER and fresh.get("manager_id"):
            await notify_user(
                fresh["manager_id"],
                f"Assessment {assessment_no} needs your decision",
                f"{_actor_name(actor)} has reviewed {fresh.get('candidate_name')}. "
                f"Yours is the remaining decision.",
                link="/hrms/assessments", email=True)
        elif pending_slot == SLOT_HR:
            await notify_hrms_role(
                company_id, ["HR"],
                f"Assessment {assessment_no} needs an HR decision",
                f"The hiring manager has reviewed {fresh.get('candidate_name')}.",
                link="/hrms/assessments")

    final = await coll.find_one({"assessment_no": assessment_no})
    out = _out(final)
    out.pop("access_code", None)
    out["lifecycle"] = _lifecycle(final)
    return out


async def _resolve(actor: dict, company_id: str, doc: dict) -> None:
    """Both slots decided: close the assessment and move the candidate."""
    outcome = _outcome_of(doc)
    now = datetime.now(timezone.utc)
    target = (AppStatus.ASSESSMENT_PASSED if outcome == Decision.PASS.value
              else AppStatus.ASSESSMENT_FAILED)

    await get_collection(COLL_ASSESSMENTS).update_one(
        {"assessment_no": doc["assessment_no"]},
        {"$set": {"status": AssessmentStatus.REVIEWED.value, "outcome": outcome,
                  "resolved_at": now}})

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": doc["uk"], "company_id": str(company_id)})
    current = (candidate or {}).get("application_status")
    if current and can_transition(current, target.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": doc["uk"], "company_id": str(company_id)},
            {"$set": {"application_status": target.value, "updated_at": now}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, doc["uk"],
                    f"{current} -> {target.value}", company_id)

    await audit(actor, AUDIT_ASSESSMENT_RESOLVED, ENTITY_ASSESSMENT, doc["assessment_no"],
                f"outcome: {outcome}", company_id)
    await audit(actor, AUDIT_ASSESSMENT_RESOLVED, ENTITY_CANDIDATE, doc["uk"],
                f"{doc['assessment_no']} {outcome}", company_id)

    # Both reviewers hear the result -- the one who decided first would otherwise never
    # learn what the outcome was.
    message = (f"{doc.get('candidate_name')} {'passed' if outcome == Decision.PASS.value else 'did not pass'} "
               f"the assessment.")
    await notify_hrms_role(company_id, ["HR"], f"Assessment {doc['assessment_no']}: {outcome}",
                           message, link="/hrms/assessments")
    if doc.get("manager_id"):
        await notify_user(doc["manager_id"], f"Assessment {doc['assessment_no']}: {outcome}",
                          message, link="/hrms/assessments")


async def assessable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who may be sent an assessment.

    Filtered to those whose role REQUIRES one and who are at the assessment stage, so the
    picker cannot offer somebody the API will refuse. Roles without an assessment
    requirement go screening -> interviews directly and never appear here.
    """
    rows = await get_collection(COLL_CANDIDATES).find({
        "company_id": str(company_id),
        "requires_assessment": True,
        "application_status": {"$in": [s.value for s in ASSESSABLE_STATUSES]},
    }).sort("created_at", -1).to_list(500)

    open_uks = {
        a["uk"] for a in await get_collection(COLL_ASSESSMENTS).find(
            {"company_id": str(company_id),
             "status": {"$in": [AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value,
                                AssessmentStatus.COMPLETED.value]}},
            {"uk": 1}).to_list(500)
    }
    return [
        {"uk": r["uk"], "candidate_name": r.get("candidate_name"),
         "application_status": r.get("application_status"), "request_no": r.get("request_no")}
        for r in rows if r["uk"] not in open_uks
    ]


# -------------------------------------------------------------
# Public side (NO authentication -- every input is hostile)
# -------------------------------------------------------------
async def get_public_assessment(code: str) -> dict:
    """The assessment behind a candidate's link. Marks it Opened on first view."""
    coll = get_collection(COLL_ASSESSMENTS)
    doc = await coll.find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    if doc["status"] in (AssessmentStatus.COMPLETED.value, AssessmentStatus.REVIEWED.value):
        # Not an error: a candidate revisiting their own link should see a calm "already
        # submitted" screen, not a failure.
        return {"ok": True, "already_done": True, "title": doc.get("title"),
                "candidate_name": doc.get("candidate_name")}

    if doc["status"] == AssessmentStatus.SENT.value:
        # First open. Conditioned on the current status so a refresh cannot rewrite
        # opened_at and lose the real first-view time.
        now = datetime.now(timezone.utc)
        updated = await coll.update_one(
            {"access_code": code, "status": AssessmentStatus.SENT.value},
            {"$set": {"status": AssessmentStatus.OPENED.value, "opened_at": now}})
        if updated.modified_count:
            await audit(None, AUDIT_ASSESSMENT_OPENED, ENTITY_ASSESSMENT,
                        doc["assessment_no"], "candidate opened the assessment",
                        doc.get("company_id"))

    return {
        "ok": True,
        "already_done": False,
        "assessment_no": doc["assessment_no"],
        "title": doc.get("title"),
        "instructions": doc.get("instructions"),
        "link": doc.get("link"),
        "max_score": doc.get("max_score"),
        "due_date": doc.get("due_date"),
        "candidate_name": doc.get("candidate_name"),
    }


async def submit_public_assessment(code: str, payload: dict) -> dict:
    """Receive a candidate's submission."""
    coll = get_collection(COLL_ASSESSMENTS)
    doc = await coll.find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc["status"] in (AssessmentStatus.COMPLETED.value, AssessmentStatus.REVIEWED.value):
        raise HTTPException(
            status_code=409, detail="You have already submitted this assessment.")
    if doc["status"] not in (AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value):
        raise HTTPException(status_code=410, detail=CLOSED_LINK)

    response = clean_text(payload.get("response"), limit=20000)
    attachments = payload.get("attachments") or []
    if len(attachments) > MAX_ASSESSMENT_ATTACHMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"You can attach at most {MAX_ASSESSMENT_ATTACHMENTS} files.")
    if not response and not attachments:
        raise HTTPException(
            status_code=422,
            detail="Add your response, or attach at least one file.")

    stored = []
    for i, upload in enumerate(attachments):
        raw, name, mime = decode_upload(upload, label=f"Attachment {i + 1}")
        if not raw:
            continue
        import io
        from app.services.s3_service import upload_file_to_s3_with_key
        try:
            result = upload_file_to_s3_with_key(io.BytesIO(raw), f"assess_{name}", mime)
        except Exception as e:
            print(f"[WARN] HRMS assessment upload failed: {e}")
            raise HTTPException(
                status_code=503,
                detail="Your attachment could not be uploaded right now. Please try again.")
        stored.append({"name": name, "key": result.get("key") if isinstance(result, dict) else None,
                       "mime_type": mime})

    now = datetime.now(timezone.utc)
    # Conditioned on a still-open status so two rapid submits cannot both write.
    updated = await coll.update_one(
        {"access_code": code,
         "status": {"$in": [AssessmentStatus.SENT.value, AssessmentStatus.OPENED.value]}},
        {"$set": {"status": AssessmentStatus.COMPLETED.value, "response": response,
                  "attachments": stored, "submitted_at": now}})
    if updated.modified_count == 0:
        raise HTTPException(
            status_code=409, detail="You have already submitted this assessment.")

    company_id = doc.get("company_id")
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": doc["uk"], "company_id": company_id})
    current = (candidate or {}).get("application_status")
    if current and can_transition(current, AppStatus.ASSESSMENT_COMPLETED.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": doc["uk"], "company_id": company_id},
            {"$set": {"application_status": AppStatus.ASSESSMENT_COMPLETED.value,
                      "updated_at": now}})
        await audit(None, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, doc["uk"],
                    f"{current} -> {AppStatus.ASSESSMENT_COMPLETED.value}", company_id)

    await audit(None, AUDIT_ASSESSMENT_SUBMITTED, ENTITY_ASSESSMENT, doc["assessment_no"],
                "candidate submitted", company_id)
    await audit(None, AUDIT_ASSESSMENT_SUBMITTED, ENTITY_CANDIDATE, doc["uk"],
                f"{doc['assessment_no']} submitted", company_id)

    # Both reviewers are told there is something waiting.
    await notify_hrms_role(
        company_id, ["HR"], f"Assessment submitted: {doc.get('candidate_name')}",
        f"{doc.get('candidate_name')} submitted {doc.get('title')}. It is ready for review.",
        link="/hrms/assessments")
    if doc.get("manager_id"):
        await notify_user(
            doc["manager_id"], f"Assessment submitted: {doc.get('candidate_name')}",
            f"{doc.get('candidate_name')} submitted {doc.get('title')}. Your review is needed.",
            link="/hrms/assessments")

    return {"ok": True, "message": "Your assessment has been submitted."}
