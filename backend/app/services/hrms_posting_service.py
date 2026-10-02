"""HRMS > job postings + public application intake.

Publishes an APPROVED job description as ONE posting, and receives the applications that
come back.

-- One posting, one link ------------------------------------------------------------
A posting used to be created once per job board: publishing to LinkedIn + Naukri + Career
Page made three rows, three codes and three streams to reconcile, and the candidate's
`source` was inferred from whichever link they clicked. That inference was wrong the moment
a link was forwarded, and it made the operator maintain a link per channel forever.

Now a JD produces a SINGLE application link. Paste it into LinkedIn, Naukri, a WhatsApp
group, anywhere -- and the form itself asks the applicant where they found the role. The
answer is what fills `source`, so the channel is reported by the person who actually knows
it. See hrms_referral_service.

A posting still chooses its destination:

  auto     -> the built-in public form at /apply/<posting_code>; applications enter the
              pipeline automatically.
  external -> the poster's own URL (a job board listing, a Google Form, ...). Applications
              made there NEVER reach this pipeline -- nothing writes them back. The UI says
              so explicitly rather than implying tracking it cannot do.

-- Application count is computed, never stored -------------------------------------
A stored counter drifts the moment a candidate is deleted, merged or moved. It is derived
from `hrms_candidates` on read, which cannot disagree with reality.
"""
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_APPLICATION, AUDIT_POSTING_CREATED, AUDIT_POSTING_DELETED,
    AUDIT_POSTING_EXEC_APPROVED, AUDIT_POSTING_PUBLISHED, AUDIT_POSTING_UPDATED,
    COLL_CANDIDATES, COLL_JOB_DESCRIPTIONS, COLL_JOB_POSTINGS, COLL_POSITION_SCORECARDS,
    COLL_REQUISITIONS,
    EMAIL_RE, ENTITY_CANDIDATE_APPLICATION, ENTITY_POSTING, MAX_CERTIFICATES, PHONE_RE,
    POSTING_CODE_RE, AppStatus, ApplyLinkMode, JdStatus, LiveStatus, RecruitmentChannel,
    REQUISITION_TRACK_INTERNAL, ScorecardStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_public_guard import (
    CLOSED_LINK, INVALID_LINK, clean_text, decode_upload, safe_filename,
)

# Every posting code now shares one prefix. It used to encode the platform, which stopped
# meaning anything the moment a posting stopped having one -- and the pattern
# POSTING_CODE_RE enforces is unchanged, so codes minted before this still resolve.
_CODE_PREFIX = "JB"
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _mint_code() -> str:
    """Generate a posting code.

    `secrets` is used rather than `random` even though a posting code is a public
    identifier, not a secret: the source generated every id and access token with
    `Math.random()` (BACKEND_ANALYSIS Risk #12), and keeping one habit avoids the mistake of
    reaching for the weak generator when the value DOES need to be unguessable -- as the
    Phase 6/8/9 access codes will.
    """
    import secrets
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"{_CODE_PREFIX}-{body}"


async def _unique_code(preferred: str = None) -> str:
    """Resolve a posting code, honouring a client-previewed one when it is safe to.

    The UI shows the applicant link WHILE the form is being filled in, so the code the user
    copies must be the code that gets stored. A supplied code is accepted only if it matches
    the public pattern and is unused; otherwise the server mints its own and the client
    re-reads it from the response.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    if preferred:
        candidate = preferred.strip().upper()
        if POSTING_CODE_RE.match(candidate):
            if not await coll.find_one({"posting_code": candidate}):
                return candidate
    for _ in range(12):
        candidate = _mint_code()
        if not await coll.find_one({"posting_code": candidate}):
            return candidate
    raise HTTPException(
        status_code=500,
        detail="Could not allocate a unique posting code. Please try again.")


async def _application_counts(codes: list) -> dict:
    """Applications per posting code, in one aggregation rather than N queries."""
    if not codes:
        return {}
    rows = await get_collection(COLL_CANDIDATES).aggregate([
        {"$match": {"posting_code": {"$in": codes}}},
        {"$group": {"_id": "$posting_code", "n": {"$sum": 1}}},
    ]).to_list(len(codes) + 10)
    return {r["_id"]: r["n"] for r in rows}


def _effective_status(doc: dict, today: str) -> str:
    """A posting past its expiry reads as Expired without needing a nightly job.

    The source computed expiry at read time too; the alternative is a scheduler this ERP
    does not have. The stored value is left alone so an operator can see what was set.
    """
    expiry = doc.get("expiry_date")
    if (doc.get("live_status") == LiveStatus.LIVE.value and expiry and expiry < today):
        return LiveStatus.EXPIRED.value
    return doc.get("live_status")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -------------------------------------------------------------
# Authenticated side
# -------------------------------------------------------------
async def list_postings(actor: dict, company_id: str, *, jd_no: str = None,
                        live_status: str = None, search: str = None,
                        limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if jd_no:
        query["jd_no"] = jd_no
    if live_status:
        query["live_status"] = live_status
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"posting_code": {"$regex": safe, "$options": "i"}},
            {"title": {"$regex": safe, "$options": "i"}},
            {"jd_no": {"$regex": safe, "$options": "i"}},
        ]

    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_JOB_POSTINGS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)

    counts = await _application_counts([r["posting_code"] for r in rows])
    today = _today()
    out = []
    for r in rows:
        item = _out(r)
        item["live_status"] = _effective_status(r, today)
        item["application_count"] = counts.get(r["posting_code"], 0)
        out.append(item)

    live = sum(1 for r in out if r["live_status"] == LiveStatus.LIVE.value)
    return {
        "postings": out,
        "total": len(out),
        "stats": {
            "live": live,
            "applications": sum(counts.values()),
            "postings": len(out),
        },
    }


async def create_posting(actor: dict, company_id: str, payload: dict) -> dict:
    """Draft a job posting against an approved JD.

    Internal Recruitment SOP -- Step 4: creation is now its own step, separate from
    publishing (`publish_posting`) -- a posting opens as a Draft (or, if it names Executive
    Search among its channels, Pending Management Approval) rather than going live
    immediately. Selecting channels happens here, at creation, not as an afterthought.
    """
    jd_no = (payload.get("jd_no") or "").strip()
    if not jd_no:
        raise HTTPException(status_code=422, detail="Select a job description to publish.")

    jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one(
        {"jd_no": jd_no, "company_id": str(company_id)})
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found.")
    if jd.get("status") != JdStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'Only an approved job description can be published. {jd_no} is '
                    f'"{jd.get("status")}" - it must clear HR review and MD approval first.'))

    req = None
    if jd.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": jd["request_no"], "company_id": str(company_id)})
        # ── Internal track ── the mandatory budget gate (SOP §11). A JD reaches APPROVED
        # only at the END of either chain, so in practice this is belt and braces -- but
        # publishing is the primary act of sourcing, and the gate that guards it should be
        # asserted where the act happens rather than inferred from the state of a different
        # document.
        if req:
            from app.services.hrms_requisition_service import assert_sourcing_allowed
            assert_sourcing_allowed(req)

        # Made EXPLICIT rather than left to the fact that JD.status can only reach Approved
        # via the requisition's own scorecard-approve transition (Step 3 makes that gate
        # true architecturally already) -- Step 4's own spec names it as a precondition in
        # its own right, and a reader of this function should be able to see the rule here
        # rather than trace it through a different service.
        if req and req.get("requisition_track") == REQUISITION_TRACK_INTERNAL:
            scorecard = await get_collection(COLL_POSITION_SCORECARDS).find_one(
                {"request_no": jd["request_no"], "company_id": str(company_id)})
            if not scorecard or scorecard.get("status") != ScorecardStatus.APPROVED.value:
                raise HTTPException(
                    status_code=409,
                    detail=("The Position Scorecard for this requisition must be approved "
                            "before a job posting can be created."))

    raw_channels = payload.get("channels") or []
    channels = []
    for c in raw_channels:
        value = getattr(c, "value", c)
        try:
            channels.append(RecruitmentChannel(value).value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f'"{value}" is not a recognised recruitment channel. Choose from: '
                        f"{', '.join(ch.value for ch in RecruitmentChannel)}."))
    if not channels:
        raise HTTPException(
            status_code=422, detail="Select at least one recruitment channel.")
    channels = sorted(set(channels))
    needs_exec_approval = RecruitmentChannel.EXECUTIVE_SEARCH.value in channels

    expiry = payload.get("expiry_date")
    if expiry:
        if not is_iso_date(expiry):
            raise HTTPException(
                status_code=422, detail="Expiry date must be a valid date in YYYY-MM-DD format.")
        if expiry < _today():
            raise HTTPException(status_code=422, detail="Expiry date cannot be in the past.")

    mode = getattr(payload.get("apply_link_mode"), "value", payload.get("apply_link_mode")) \
        or ApplyLinkMode.AUTO.value
    external = (payload.get("external_url") or "").strip()
    if mode == ApplyLinkMode.EXTERNAL.value:
        if not external:
            raise HTTPException(
                status_code=422,
                detail="Enter the application link, or switch it to the generated form.")
        if not external.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="The application link must start with http:// or https://.")
    else:
        external = None

    now = datetime.now(timezone.utc)
    code = await _unique_code(payload.get("code"))
    opening_status = (LiveStatus.PENDING_APPROVAL.value if needs_exec_approval
                       else LiveStatus.DRAFT.value)
    doc = {
        "posting_code": code,
        "company_id": str(company_id),
        "jd_no": jd_no,
        "request_no": jd.get("request_no"),
        "title": jd.get("title"),
        "apply_link_mode": mode,
        "external_url": external,
        "channels": channels,
        "live_status": opening_status,
        "expiry_date": expiry or None,
        "notes": clean_text(payload.get("notes")),
        "requires_assessment": bool(payload.get("requires_assessment")),
        "posted_by": str(actor.get("_id") or ""),
        # Set only once the posting actually goes live (see publish_posting) -- a Draft
        # has not been "posted" anywhere yet, so a date here would be a fiction.
        "posting_date": None,
        "published_by": None, "published_at": None,
        "exec_search_approved_by": None, "exec_search_approved_at": None,
        "created_at": now,
    }

    await get_collection(COLL_JOB_POSTINGS).insert_one(dict(doc))
    # Keyed to the POSTING code, not the JD: `get_posting_history` reads the audit trail by
    # entity_id, and a creation row filed under the JD would be missing from the posting's
    # own history -- the one place it most obviously belongs.
    await audit(actor, AUDIT_POSTING_CREATED, ENTITY_POSTING, code,
                f"{jd_no} · {', '.join(channels)}", company_id)
    return {"posting": _out(doc), "created": 1}


async def publish_posting(actor: dict, company_id: str, code: str) -> dict:
    """Go live -- Step 4's own third moment, distinct from drafting and channel selection.

    An Executive Search posting cannot reach here until Management has cleared
    `approve_exec_search`; every other posting moves straight from Draft.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")

    status = current.get("live_status")
    if status == LiveStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail=("This posting names Executive Search and needs Management's approval "
                    "before it can be published."))
    if status != LiveStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail=f'Only a Draft posting can be published. This one is "{status}".')

    # One JD, one live link. Publishing the same JD twice used to be how an operator got a
    # second channel; channels are now selected on ONE posting, so a second live posting is
    # simply a second thing to keep alive and reconcile. The message names the existing code
    # so the operator can go and copy it rather than guess why they were refused.
    # Every Live-stored row is examined, not just the first: a JD can carry a row whose date
    # has passed (stored Live, effectively Expired) ALONGSIDE a genuinely live one, and
    # picking one arbitrarily would let a second link through whenever the expired row came
    # back first.
    today = _today()
    existing = await get_collection(COLL_JOB_POSTINGS).find(
        {"jd_no": current["jd_no"], "company_id": str(company_id),
         "live_status": LiveStatus.LIVE.value}).to_list(50)
    live = next((p for p in existing
                 if _effective_status(p, today) == LiveStatus.LIVE.value), None)
    if live and live["posting_code"] != code:
        raise HTTPException(
            status_code=409,
            detail=(f"{current['jd_no']} is already published as {live['posting_code']}. "
                    f"Share that link, or close it before publishing a new one."))

    now = datetime.now(timezone.utc)
    updates = {
        "live_status": LiveStatus.LIVE.value,
        "posting_date": now.strftime("%Y-%m-%d"),
        "published_by": str(actor.get("_id") or ""),
        "published_at": now,
    }
    await coll.update_one({"posting_code": code, "company_id": str(company_id)},
                          {"$set": updates})

    # Phase 11-R, Item 1: register the AUTO posting's apply link, now that it is actually
    # public. An EXTERNAL posting is deliberately NOT registered -- it sends the applicant to
    # a job board or a Google Form, and nothing ever writes those applications back into this
    # pipeline (see ApplyLinkMode.EXTERNAL), so there is no open to count and no submission to
    # consume. Registering one would put a row in the Link Manager promising tracking that
    # cannot exist -- the same honesty the posting UI already applies.
    if current.get("apply_link_mode") == ApplyLinkMode.AUTO.value:
        from app.models.hrms import LinkKind
        from app.services.hrms_link_service import register_link
        await register_link(
            company_id=company_id, kind=LinkKind.APPLY, code=code,
            target_type="posting", target_id=code, actor=actor,
            candidate_name=None, request_no=current.get("request_no"),
            expires_at=current.get("expiry_date"))

    await audit(actor, AUDIT_POSTING_PUBLISHED, ENTITY_POSTING, code,
                current.get("jd_no"), company_id)
    doc = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    item = _out(doc)
    item["application_count"] = (await _application_counts([code])).get(code, 0)
    return item


async def approve_exec_search(actor: dict, company_id: str, code: str,
                              remarks: str = None) -> dict:
    """Management clears an Executive Search posting so it can be published.

    Moves it to Draft rather than straight to Live: publishing itself is still `publish_posting`
    -- one action per moment, the same discipline the rest of Step 4 follows.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")
    if current.get("live_status") != LiveStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail=(f'Only a posting "Pending Management Approval" can be cleared this way. '
                    f'This one is "{current.get("live_status")}".'))

    now = datetime.now(timezone.utc)
    await coll.update_one(
        {"posting_code": code, "company_id": str(company_id)},
        {"$set": {"live_status": LiveStatus.DRAFT.value,
                  "exec_search_approved_by": str(actor.get("_id") or ""),
                  "exec_search_approved_at": now}})
    await audit(actor, AUDIT_POSTING_EXEC_APPROVED, ENTITY_POSTING, code,
                clean_text(remarks) or None, company_id)
    doc = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    return _out(doc)


async def get_posting(actor: dict, company_id: str, code: str) -> dict:
    """One posting, with the approved JD's content joined on for HR's own preview --
    everything Step 4 says must be "auto-fetched" onto the posting screen, read live from
    the JD/requisition rather than copied, so an edit to either is reflected immediately."""
    doc = await get_collection(COLL_JOB_POSTINGS).find_one(
        {"posting_code": code, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Posting not found.")

    item = _out(doc)
    item["live_status"] = _effective_status(doc, _today())
    item["application_count"] = (await _application_counts([code])).get(code, 0)

    jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one(
        {"jd_no": doc.get("jd_no"), "company_id": str(company_id)})
    req = None
    if jd and jd.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": jd["request_no"], "company_id": str(company_id)})
    if jd:
        item["jd_details"] = {
            "job_title": jd.get("title") or (req or {}).get("designation_name"),
            "department": (req or {}).get("department_name"),
            "reporting_to": (req or {}).get("reporting_manager_name"),
            "job_summary": jd.get("job_summary"),
            "responsibilities": jd.get("responsibilities"),
            "required_skills": jd.get("skills"),
            "experience": jd.get("experience"),
            "qualifications": jd.get("qualifications"),
            "location": jd.get("location"),
            "key_competencies": jd.get("key_competencies"),
            "culture_fit": jd.get("culture_fit"),
            "additional_requirements": jd.get("additional_requirements"),
        }
    return item


async def get_posting_history(actor: dict, company_id: str, code: str) -> dict:
    """The posting's own history, reconstructed from the audit trail rather than a second,
    parallel array that could drift from what the audit log already proves happened."""
    if not await get_collection(COLL_JOB_POSTINGS).find_one(
            {"posting_code": code, "company_id": str(company_id)}):
        raise HTTPException(status_code=404, detail="Posting not found.")
    from app.services.hrms_audit_service import read_audit
    rows = await read_audit(company_id=str(company_id), entity=ENTITY_POSTING,
                            entity_id=code, limit=200)
    rows = list(reversed(rows))  # read_audit is newest-first; a history reads oldest-first
    return {"posting_code": code, "history": [
        {"action": r.get("action"), "actor_name": r.get("actor_name"),
         "at": r.get("created_at"), "detail": r.get("detail")}
        for r in rows
    ]}


async def update_posting(actor: dict, company_id: str, code: str, payload: dict) -> dict:
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")

    updates = {}
    if payload.get("live_status") is not None:
        new_status = getattr(payload["live_status"], "value", payload["live_status"])
        # Going live for the FIRST time is `publish_posting`'s own job -- it re-checks the
        # "one live posting per JD" rule and stamps posting_date/published_by, neither of
        # which this generic update does. Resuming an already-published posting (Paused ->
        # Live) has no such precondition to re-check, so that toggle stays here.
        if (new_status == LiveStatus.LIVE.value
                and current.get("live_status") in (LiveStatus.DRAFT.value,
                                                    LiveStatus.PENDING_APPROVAL.value)):
            raise HTTPException(
                status_code=409,
                detail='Use "Publish" to take a posting live, not this field.')
        updates["live_status"] = new_status
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"])
    if payload.get("requires_assessment") is not None:
        updates["requires_assessment"] = bool(payload["requires_assessment"])
    if payload.get("channels") is not None:
        # Channels are chosen before publishing (SOP Step 4); once a posting is live, its
        # advertised channels are what candidates have already been sourced against, so
        # changing them here would rewrite history rather than correct a draft.
        if current.get("live_status") not in (LiveStatus.DRAFT.value, LiveStatus.PENDING_APPROVAL.value):
            raise HTTPException(
                status_code=409,
                detail="Channels can only be changed while the posting is still a Draft.")
        raw_channels = payload["channels"] or []
        channels = []
        for c in raw_channels:
            value = getattr(c, "value", c)
            try:
                channels.append(RecruitmentChannel(value).value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=(f'"{value}" is not a recognised recruitment channel. Choose from: '
                            f"{', '.join(ch.value for ch in RecruitmentChannel)}."))
        if not channels:
            raise HTTPException(
                status_code=422, detail="Select at least one recruitment channel.")
        channels = sorted(set(channels))
        updates["channels"] = channels
        # Selecting Executive Search after the fact routes it into the same Management gate
        # a posting created with it already goes through; DEselecting it, while still
        # pending, clears the block since nothing needs Management's approval any more.
        needs_exec = RecruitmentChannel.EXECUTIVE_SEARCH.value in channels
        if needs_exec and current.get("live_status") == LiveStatus.DRAFT.value:
            updates["live_status"] = LiveStatus.PENDING_APPROVAL.value
        elif not needs_exec and current.get("live_status") == LiveStatus.PENDING_APPROVAL.value:
            updates["live_status"] = LiveStatus.DRAFT.value
    if payload.get("expiry_date") is not None:
        expiry = payload["expiry_date"]
        if expiry and not is_iso_date(expiry):
            raise HTTPException(status_code=422, detail="Expiry date must be YYYY-MM-DD.")
        updates["expiry_date"] = expiry or None

    mode = payload.get("apply_link_mode")
    if mode is not None:
        mode = getattr(mode, "value", mode)
        updates["apply_link_mode"] = mode
        if mode == ApplyLinkMode.EXTERNAL.value:
            external = (payload.get("external_url") or current.get("external_url") or "").strip()
            if not external.lower().startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=422,
                    detail="An external application link must start with http:// or https://.")
            updates["external_url"] = external
        else:
            updates["external_url"] = None
    elif payload.get("external_url") is not None:
        external = (payload["external_url"] or "").strip()
        if external and not external.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="An external application link must start with http:// or https://.")
        updates["external_url"] = external or None

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"posting_code": code, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_POSTING_UPDATED, ENTITY_POSTING, code,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    doc = await coll.find_one({"posting_code": code})
    item = _out(doc)
    item["application_count"] = (await _application_counts([code])).get(code, 0)
    return item


async def delete_posting(actor: dict, company_id: str, code: str) -> dict:
    """Remove a posting. Applications already received are KEPT.

    Deleting the channel must not delete the people who came through it -- candidates
    outlive the ad, and Phase 5 onward depend on them.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")

    await coll.delete_one({"posting_code": code, "company_id": str(company_id)})
    await audit(actor, AUDIT_POSTING_DELETED, ENTITY_POSTING, code,
                current.get("jd_no"), company_id)
    return {"deleted": True, "posting_code": code,
            "applications_kept": (await _application_counts([code])).get(code, 0)}


# -------------------------------------------------------------
# Public side (NO authentication -- treat every input as hostile)
# -------------------------------------------------------------
def _ctc_from_requisition(req: dict) -> Optional[str]:
    """The requisition's numeric CTC as advert text, for a JD stored before JDs inherited
    it. Same money convention as the rest of the module: grouped digits, no symbol."""
    value = req.get("offering_ctc")
    if value is None or value == "":
        return None
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return None


async def get_public_posting(code: str) -> dict:
    """The job ad behind a public link.

    Returns only what a candidate needs to decide whether to apply. Internal fields --
    company_id, requisition number, who posted it, the assessment flag -- are deliberately
    NOT exposed: this response is world-readable.
    """
    posting = await get_collection(COLL_JOB_POSTINGS).find_one({"posting_code": code})
    if not posting:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    status = _effective_status(posting, _today())
    if status != LiveStatus.LIVE.value:
        # 410 Gone: the link was valid but this position is finished. Distinguishable from a
        # bogus code (404) for the applicant's benefit; neither reveals anything internal.
        raise HTTPException(status_code=410, detail=CLOSED_LINK)

    if posting.get("apply_link_mode") == ApplyLinkMode.EXTERNAL.value:
        return {"ok": True, "external": True, "external_url": posting.get("external_url"),
                "title": posting.get("title")}

    jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one({"jd_no": posting.get("jd_no")}) or {}
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": posting.get("request_no")}) or {}

    return {
        "ok": True,
        "external": False,
        "posting_code": posting["posting_code"],
        "title": jd.get("title") or posting.get("title"),
        "posting_date": posting.get("posting_date"),
        "expiry_date": posting.get("expiry_date"),
        "department": req.get("department_name"),
        "designation": req.get("designation_name"),
        # A JD raised today inherits all of these from its requisition, so `jd.get(...)`
        # answers on its own. The fallbacks stay for JDs raised BEFORE that inheritance
        # existed, which were stored with these fields empty -- see
        # scripts/backfill_jd_from_requisition.py for filling them in permanently.
        "employment_type": jd.get("employment_type") or req.get("employment_type"),
        "location": jd.get("location") or req.get("work_location"),
        "experience": jd.get("experience") or req.get("experience_required"),
        "qualifications": jd.get("qualifications") or req.get("qualification"),
        "responsibilities": jd.get("responsibilities"),
        "skills": jd.get("skills") or req.get("essential_skills"),
        "benefits": jd.get("benefits"),
        "ctc": jd.get("ctc") or _ctc_from_requisition(req),
        "vacancies": req.get("vacancy"),
        # ── Phase INT-2 (SOP §11) ── the equal-opportunity and data-use statements the form
        # must show, and the optional talent-pool consent.
        #
        # Sent as CONTENT rather than as a flag, because the wording lives in
        # hrms_comm_templates precisely so legal can change it without a deploy -- a form
        # that hard-coded the text would need one every time.
        #
        # Internal track only. A client-track applicant is agreeing to the CLIENT's terms,
        # not ours, and asserting ours over their hiring would be claiming something we are
        # not party to.
        "acknowledgements": await _acknowledgements(posting, req),
    }


async def _acknowledgements(posting: dict, req: dict) -> list:
    """The tick-boxes the public form must render for this posting.

    Empty on the client track and on any posting whose requisition cannot be resolved, so
    the form is byte-for-byte what it always was there.

    Never raises: a template lookup that fails must not take down a live job ad. It falls
    back to no acknowledgements, which means the SERVER-side check is then the one that
    refuses the application -- loudly, rather than silently accepting an un-acknowledged one.
    """
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return []
    try:
        from app.models.hrms import CONSENT_TEMPLATES
        from app.services.hrms_comm_service import get_template

        wanted = [
            ("eeo_ack", "consent_equal_opportunity", True),
            ("data_use_ack", "consent_data_use", True),
            # The talent-pool consent is OPTIONAL and off by default. It is the only way
            # into the pool, and an opt-out default would make "consent" a formality.
            ("consent_to_retain", None, False),
        ]
        seeded = {key: (subject, body)
                  for key, _channel, subject, body, _vars in CONSENT_TEMPLATES}

        out = []
        for field, template_key, required in wanted:
            if template_key is None:
                out.append({
                    "field": field, "required": False,
                    "heading": "Keeping your details for future roles",
                    "statement": ("Tick this if you are happy for us to keep your "
                                  "application on file and contact you about other roles. "
                                  "You can ask us to remove it at any time, and we will "
                                  "not keep it beyond our published retention period."),
                })
                continue
            template = await get_template(posting.get("company_id"), template_key)
            heading, statement = seeded.get(template_key, ("", ""))
            out.append({
                "field": field,
                "required": required,
                "heading": (template or {}).get("subject") or heading,
                "statement": (template or {}).get("body") or statement,
            })
        return out
    except Exception as e:
        print(f"[WARN] HRMS acknowledgements unavailable for "
              f"{posting.get('posting_code')}: {e}")
        return []


async def _store_upload(upload, label: str, prefix: str) -> Optional[dict]:
    """Validate, decode and store one candidate file.

    Returns `{name, key}` -- the S3 KEY, not a URL. Signed URLs expire in an hour, so
    persisting one would leave dead links in every candidate record; the key is permanent
    and a fresh URL is generated on demand.
    """
    if upload is None:
        return None
    raw, name, mime = decode_upload(upload, label=label)
    if not raw:
        return None

    import io
    from app.services.s3_service import upload_file_to_s3_with_key
    try:
        result = upload_file_to_s3_with_key(io.BytesIO(raw), f"{prefix}_{name}", mime)
    except Exception as e:
        print(f"[WARN] HRMS public upload failed ({label}): {e}")
        raise HTTPException(
            status_code=503,
            detail=f"{label} could not be uploaded right now. Please try again.")
    return {"name": name, "key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime}


async def submit_application(code: str, payload: dict) -> dict:
    """Receive a public application and create a candidate.

    Every field is untrusted. Validation here is the ONLY validation -- there is no
    authenticated caller to have checked anything first.
    """
    posting = await get_collection(COLL_JOB_POSTINGS).find_one({"posting_code": code})
    if not posting:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if _effective_status(posting, _today()) != LiveStatus.LIVE.value:
        raise HTTPException(status_code=410, detail=CLOSED_LINK)
    if posting.get("apply_link_mode") == ApplyLinkMode.EXTERNAL.value:
        raise HTTPException(
            status_code=409,
            detail="Applications for this listing are handled on the original job board.")

    name = clean_text(payload.get("candidate_name"), limit=140)
    email = clean_text(payload.get("can_email"), limit=180)
    phone = clean_text(payload.get("can_contact"), limit=30)

    if not name:
        raise HTTPException(status_code=422, detail="Please enter your full name.")
    if not email or not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    if not phone or not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Please enter a valid phone number.")
    if not payload.get("declaration"):
        raise HTTPException(
            status_code=422,
            detail="Please confirm that the information provided is accurate.")
    if not payload.get("resume"):
        raise HTTPException(status_code=422, detail="Please attach your resume.")

    certificates = payload.get("certificates") or []
    if len(certificates) > MAX_CERTIFICATES:
        raise HTTPException(
            status_code=422,
            detail=f"You can attach at most {MAX_CERTIFICATES} certificates.")

    email = email.lower()
    company_id = posting.get("company_id")

    # The discovery / referral block. Validated BEFORE any upload is stored, so a rejected
    # claim never costs storage -- the same ordering the existing validation already follows.
    #
    # "Where did you find this job" is MANDATORY on the public form, and it is the whole
    # reason a posting needs only ONE link: the channel comes from the applicant rather than
    # from which of several links they clicked, and it is what `source` is set to below.
    # Enforced here rather than in resolve_referral, because the manual add-candidate path
    # has no applicant to ask.
    if not payload.get("referral_source"):
        raise HTTPException(
            status_code=422, detail="Please tell us where you found this job.")

    # ── Phase INT-2 (SOP §11) ── the equal-opportunity and data-use acknowledgements.
    #
    # Required on the INTERNAL track, where Sparsh Magic is the employer and the commitments
    # are its own. A client-track application is unchanged: the client's own privacy and
    # equal-opportunity terms govern their hiring, and asking an applicant to accept ours
    # would be asserting something we are not party to.
    #
    # Checked BEFORE any upload is stored, alongside the referral validation, so a rejected
    # form never costs storage.
    req_for_track = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": posting.get("request_no")}) or {}
    is_internal = req_for_track.get("requisition_track") == REQUISITION_TRACK_INTERNAL
    if is_internal:
        if not payload.get("eeo_ack"):
            raise HTTPException(
                status_code=422,
                detail="Please confirm you have read our equal-opportunity statement.")
        if not payload.get("data_use_ack"):
            raise HTTPException(
                status_code=422,
                detail="Please confirm you have read how we will use your information.")

    from app.services.hrms_referral_service import resolve_referral
    referral = await resolve_referral(payload, company_id)

    # Server-side duplicate detection. The source flagged duplicates in the browser only
    # (BACKEND_ANALYSIS 8), so a re-submission created a second candidate record. Re-applying
    # to the SAME posting is idempotent from the applicant's point of view -- they get the
    # same friendly acknowledgement rather than an error that invites a retry loop.
    existing = await get_collection(COLL_CANDIDATES).find_one({
        "company_id": company_id, "posting_code": code,
        "$or": [{"can_email": email}, {"can_contact": phone}],
    })
    if existing:
        return {"ok": True, "duplicate": True, "reference": existing.get("uk"),
                "message": "You have already applied for this position."}

    # Uploads happen only after validation passes, so a rejected form never costs storage.
    resume = await _store_upload(payload.get("resume"), "Resume", "resume")
    photo = await _store_upload(payload.get("photo"), "Photo", "photo")
    certs = []
    for i, cert in enumerate(certificates):
        stored = await _store_upload(cert, f"Certificate {i + 1}", "cert")
        if stored:
            certs.append(stored)

    year = datetime.now(timezone.utc).year
    uk = await next_business_id("candidate", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "uk": uk,
        "company_id": company_id,
        "posting_code": code,
        "jd_no": posting.get("jd_no"),
        "request_no": posting.get("request_no"),
        # The role applied FOR, denormalised so the Applicant Pool can list and filter by
        # position without joining every candidate back to its requisition on every read.
        # Distinct from `current_designation`, which is the job the applicant holds today.
        "applied_position": (req_for_track.get("designation_name")
                             or posting.get("title")),
        "department_name": req_for_track.get("department_name"),
        "candidate_name": name,
        "can_email": email,
        "can_contact": phone,
        # Overwritten by `referral` below, which always carries a `source` for a public
        # application because the form makes the question mandatory. The fallback exists
        # only so the field is never absent.
        "source": None,
        "application_status": AppStatus.APPLIED.value,
        # Copied from the posting at apply time so a later change to the posting cannot
        # retroactively alter the rules an existing applicant is judged by.
        "requires_assessment": bool(posting.get("requires_assessment")),
        "current_location": clean_text(payload.get("current_location"), limit=120),
        "total_experience": clean_text(payload.get("total_experience"), limit=60),
        "qualification": clean_text(payload.get("qualification"), limit=180),
        "current_company": clean_text(payload.get("current_company"), limit=140),
        "current_designation": clean_text(payload.get("current_designation"), limit=140),
        "current_ctc": clean_text(payload.get("current_ctc"), limit=40),
        "expected_ctc": clean_text(payload.get("expected_ctc"), limit=40),
        "notice_period": clean_text(payload.get("notice_period"), limit=60),
        "linkedin": clean_text(payload.get("linkedin"), limit=300),
        "portfolio": clean_text(payload.get("portfolio"), limit=300),
        "cover_note": clean_text(payload.get("cover_note"), limit=4000),
        "resume": resume,
        "photo": photo,
        "certificates": certs,
        # ── Phase INT-2 (SOP §11) ── stamped WITH A TIMESTAMP, not just as a boolean. An
        # acknowledgement with no time on it cannot be tied to the wording that was shown,
        # and the wording is editable (it lives in hrms_comm_templates so legal can change
        # it without a deploy) -- so "they agreed" is only meaningful with "when".
        "eeo_ack": bool(payload.get("eeo_ack")),
        "eeo_ack_at": now if payload.get("eeo_ack") else None,
        "data_use_ack": bool(payload.get("data_use_ack")),
        "data_use_ack_at": now if payload.get("data_use_ack") else None,
        # ── Phase INT-2 (Annexure C) ── consent to be kept for future roles, captured on
        # the form. This is the ONLY way into the talent pool; there is no path that opts
        # somebody in because a recruiter liked their CV.
        "consent_to_retain": bool(payload.get("consent_to_retain")),
        "consent_to_retain_at": now if payload.get("consent_to_retain") else None,
        # The accuracy declaration is what makes a later misrepresentation actionable, so
        # it is kept with its timestamp rather than discarded once validated.
        "declaration": True,
        "declaration_at": now,
        "talent_pool": False,
        "applied_at": now,
        "created_at": now,
    }
    # SOP §13, same rule as a hand-added CV: the disposal floor is stamped at creation.
    # This is the highest-volume way a CV enters the system, so a missing stamp here is the
    # difference between the retention policy applying to most candidates and to almost
    # none of them.
    from app.services.hrms_candidate_service import (
        _retention_map, candidate_retention_until)
    doc["retention_until"] = candidate_retention_until(
        doc, await _retention_map(company_id))
    # Applied AFTER the base document, and this is what sets `source`: the channel the
    # applicant named, or "Referral" when they declared one -- a referral that arrived
    # through a LinkedIn post is a referral, and filing it under LinkedIn would overstate
    # that channel.
    doc.update(referral)
    await get_collection(COLL_CANDIDATES).insert_one(dict(doc))

    channel = doc.get("source") or "the application form"
    await audit(None, AUDIT_APPLICATION, ENTITY_CANDIDATE_APPLICATION, uk,
                f"{name} applied via {channel} ({code})", company_id)

    title = posting.get("title") or "a role"
    await notify_hrms_role(
        company_id, ["HR"], f"New application for {title}",
        f"{name} applied via {channel}.",
        link="/hrms/candidates", email=False)

    # Also tell the requisition's assigned recruiter -- they own this pipeline, and a
    # role-wide notification alone lets everyone assume someone else is handling it.
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": posting.get("request_no")}) or {}
    if req.get("assignee_id"):
        await notify_user(req["assignee_id"], f"New application for {title}",
                          f"{name} applied via {channel}.",
                          link="/hrms/candidates")

    # Phase 11-R, Item 5: tell the referring employee their referral landed. In-app only.
    if doc.get("referrer_user_id"):
        from app.services.hrms_referral_service import notify_referrer
        await notify_referrer(
            doc, "Your referral has applied",
            f"{name}, whom you referred, has applied for {title}.")

    # ── Phase INT-2 (Annexure C) ── acknowledge every application. The SOP promises this
    # to every applicant, and until this phase nothing did it. Fire-and-forget by contract:
    # an acknowledgement that cannot be sent must never fail somebody's job application, so
    # `fire_event` swallows everything and logs a Skipped row instead.
    from app.services.hrms_comm_service import fire_event
    await fire_event(None, company_id, uk, "application_received")

    return {"ok": True, "duplicate": False, "reference": uk,
            "message": "Your application has been submitted."}
