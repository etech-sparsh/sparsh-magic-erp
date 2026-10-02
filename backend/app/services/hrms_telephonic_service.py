"""HRMS ▸ telephonic screening (internal recruitment track).

SOP step 5: "Brief telephonic interview by HR", sitting between CV screening (step 4) and
the panel interview (step 6). Annexure B makes HR **Responsible** and everybody else
Informed, which is why `telephonic.write` belongs to HR alone.

-- What the call is FOR ---------------------------------------------------------------------
Not a shortened panel interview. It establishes the four things that make a panel interview
worth booking at all -- can this person communicate, do they understand the role they applied
for, do they want it, and are the practical facts (notice period, expectation, location)
compatible with the vacancy. A candidate who wants twice the approved band is better found
in ten minutes on the phone than in an hour of three people's time.

-- Facts and judgements are stored separately ------------------------------------------------
`notice_period_days`, `expected_ctc`, `current_location` and `availability` are what the
candidate SAID. The four rated dimensions are what the caller THOUGHT. Collapsing them would
let a rating stand in for a fact, and "seemed available soon" is not a date anybody can plan
a joining around.

The expectation captured here is deliberately NOT compared against the approved salary band.
That comparison belongs at the offer, where `assert_within_band` already makes it and where
exceeding the band has an approval path. A phone screen that refused candidates on a stated
figure would filter people out before anybody had negotiated with them.

-- "Recorded" is not the same as "passed" ----------------------------------------------------
A `No Answer` screen is a real record of a real attempt, and it is not a clearance. That is
the same distinction `REFERENCE_CLEARS_OFFER` draws for "Unable to Verify", for the same
reason: work happened, nothing was decided. It moves the candidate nowhere.

-- Several calls per candidate ---------------------------------------------------------------
Deliberately not unique on (company, candidate). The first call gets cut off, the candidate
asks to be rung back that evening, and the second one is the useful one. The gate asks
whether ANY screen passed, so a No Answer followed by a Passed is a real and answerable
sequence -- and the record keeps both attempts, which is what shows how much chasing a hire
actually took.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_TELEPHONIC_RECORDED, AUDIT_TELEPHONIC_UPDATED, AppStatus, COLL_CANDIDATES,
    COLL_INTERVIEWS, COLL_REQUISITIONS, COLL_TELEPHONIC, ENTITY_TELEPHONIC, RETENTION_YEARS,
    REQUISITION_TRACK_INTERNAL, TELEPHONIC_CLEARS_INTERVIEW, TELEPHONIC_CRITERIA,
    TELEPHONIC_RATING_MAX, TELEPHONIC_RATING_MIN, TELEPHONIC_STATUS_FOR_OUTCOME,
    TelephonicOutcome, can_transition, is_iso_date, score_band,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text

MAX_DURATION_MINUTES = 180


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _retention_until(screened_on: str, years: int = None) -> str:
    """SOP §13: an unselected candidate's records are kept for one year.

    A phone screen follows the CANDIDATE, not the employee — a record of a call is not worth
    keeping for three years about somebody who never joined. If they ARE hired, the joining
    date is what extends the candidate's own retention, and this record travels with it.

    NOTHING IS PURGED HERE. The date is computed and stored; `hrms_purge_service` proposes
    and only an approved batch redacts.
    """
    try:
        year, month, day = (int(p) for p in (screened_on or _today()).split("-"))
    except (ValueError, AttributeError):
        year, month, day = (int(p) for p in _today().split("-"))
    if month == 2 and day == 29:
        day = 28
    keep = RETENTION_YEARS["telephonic"] if years is None else int(years)
    return f"{year + keep:04d}-{month:02d}-{day:02d}"


def _rating(value, *, label: str) -> Optional[float]:
    """One 1-5 rating, or None if not given. Refuses anything outside the scale.

    Clamping silently would record a 7 as a 5 and make a scorecard nobody could reproduce
    from the numbers they typed.
    """
    if value is None or value == "":
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail=f"{label} must be a number between "
                                   f"{TELEPHONIC_RATING_MIN} and {TELEPHONIC_RATING_MAX}.")
    if not TELEPHONIC_RATING_MIN <= rating <= TELEPHONIC_RATING_MAX:
        raise HTTPException(status_code=422,
                            detail=f"{label} must be between {TELEPHONIC_RATING_MIN} and "
                                   f"{TELEPHONIC_RATING_MAX}. Got {rating:g}.")
    return round(rating, 2)


def weighted_score(doc: dict) -> Optional[float]:
    """The weighted 1-5 score across whichever dimensions were rated.

    Re-normalised over the dimensions actually present, so a screen where the caller rated
    three of four is scored out of those three rather than being penalised for a blank. A
    missing rating is missing information, not a zero — treating it as a zero would drag an
    otherwise strong candidate under the bar for a field somebody forgot.

    Returns None when nothing was rated: no score at all is honest, and 0.0 is not.
    """
    total_weight = 0.0
    total = 0.0
    for key, _label, weight in TELEPHONIC_CRITERIA:
        value = doc.get(key)
        if value is None:
            continue
        total += float(value) * weight
        total_weight += weight
    if not total_weight:
        return None
    return round(total / total_weight, 2)


def _validate(payload: dict, *, partial: bool) -> dict:
    out = {}

    if not partial or payload.get("screened_on") is not None:
        screened_on = payload.get("screened_on") or _today()
        if not is_iso_date(screened_on):
            raise HTTPException(
                status_code=422,
                detail="The screening date must be a valid date in YYYY-MM-DD format.")
        if screened_on > _today():
            raise HTTPException(
                status_code=422,
                detail="A telephonic screening cannot be dated in the future.")
        out["screened_on"] = screened_on

    if not partial or payload.get("duration_minutes") is not None:
        raw = payload.get("duration_minutes")
        if raw in (None, ""):
            out["duration_minutes"] = None
        else:
            try:
                minutes = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422,
                                    detail="Call duration must be a whole number of minutes.")
            if not 0 < minutes <= MAX_DURATION_MINUTES:
                raise HTTPException(
                    status_code=422,
                    detail=(f"Call duration must be between 1 and {MAX_DURATION_MINUTES} "
                            f"minutes. A longer conversation is a panel interview, and "
                            f"belongs on an interview record where the panel is named."))
            out["duration_minutes"] = minutes

    if not partial or payload.get("notice_period_days") is not None:
        raw = payload.get("notice_period_days")
        if raw in (None, ""):
            out["notice_period_days"] = None
        else:
            try:
                days = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422,
                                    detail="Notice period must be a whole number of days.")
            if days < 0:
                raise HTTPException(status_code=422,
                                    detail="Notice period cannot be negative.")
            out["notice_period_days"] = days

    if not partial or payload.get("expected_ctc") is not None:
        raw = payload.get("expected_ctc")
        if raw in (None, ""):
            out["expected_ctc"] = None
        else:
            try:
                ctc = float(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422,
                                    detail="Expected CTC must be a number.")
            if ctc < 0:
                raise HTTPException(status_code=422,
                                    detail="Expected CTC cannot be negative.")
            out["expected_ctc"] = round(ctc, 2)

    for field, limit in (("current_location", 160), ("availability", 200),
                         ("comments", 2000)):
        if not partial or payload.get(field) is not None:
            out[field] = clean_text(payload.get(field), limit=limit)

    for key, label, _weight in TELEPHONIC_CRITERIA:
        if not partial or payload.get(key) is not None:
            out[key] = _rating(payload.get(key), label=label)

    if not partial or payload.get("outcome") is not None:
        raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
        try:
            outcome = TelephonicOutcome(raw or TelephonicOutcome.PASSED.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Outcome must be one of: "
                        f"{', '.join(o.value for o in TelephonicOutcome)}."))
        out["outcome"] = outcome.value
        # A rejection with no note cannot be acted on by whoever reads it next, and is
        # exactly the record a candidate is entitled to an explanation from.
        if outcome is TelephonicOutcome.REJECTED:
            note = clean_text(payload.get("comments"), limit=2000) or out.get("comments")
            if not note:
                raise HTTPException(
                    status_code=422,
                    detail="Record why the call did not pass. A rejection with no note "
                           "cannot be explained to the candidate or reviewed later.")

    return out


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_screenings(actor: dict, company_id: str, *, uk: str = None,
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
    rows = await get_collection(COLL_TELEPHONIC).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "telephonic_screenings": out,
        "total": len(out),
        # The count that changes what somebody does today: calls attempted but not concluded.
        "awaiting_retry": sum(1 for r in out
                              if r.get("outcome") == TelephonicOutcome.NO_ANSWER.value),
    }


async def get_screening(company_id: str, tel_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_TELEPHONIC).find_one(
        {"tel_no": tel_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def clearing_screening(company_id: str, uk: str) -> Optional[dict]:
    """The screen that CLEARS this candidate for an interview, if there is one.

    Reads TELEPHONIC_CLEARS_INTERVIEW rather than testing a literal outcome, so widening
    what counts as a clearance stays a one-line change to the model.
    """
    rows = await get_collection(COLL_TELEPHONIC).find(
        {"company_id": str(company_id), "uk": uk}).to_list(50)
    for row in rows:
        if row.get("outcome") in TELEPHONIC_CLEARS_INTERVIEW:
            return _out(row)
    return None


async def assert_telephonic_cleared(company_id: str, candidate: dict, req: dict) -> None:
    """The interview gate. Internal track only; silent on the client track.

    SOP step 5 puts the telephonic screen before the panel interview (step 6). This is what
    makes that ordering real rather than advisory.

    Raises 409 unless the candidate has a passing screen OR an approved exception waives it.
    There is deliberately no override parameter — an approved, attributable record is the
    only thing that may bypass a control on this track.

    Why a gate at all, when Annexure C chose "warn, never block" for interview windows: a
    window is a scheduling convenience and blocking one would push an urgent booking
    off-system. A skipped screening stage is a deviation from the process the SOP describes,
    and the SOP already names the mechanism for those — the exception log.
    """
    track = (req or {}).get("requisition_track")
    if track != REQUISITION_TRACK_INTERNAL:
        return

    uk = candidate.get("uk")
    if await clearing_screening(company_id, uk):
        return

    # A candidate already being interviewed is not gated retroactively. The SOP puts the call
    # before THE PANEL, so this guards entry into interviewing rather than every round --
    # and without it, shipping this phase would strand every internal candidate already
    # mid-pipeline behind a call nobody could go back in time to make.
    if await get_collection(COLL_INTERVIEWS).count_documents(
            {"company_id": str(company_id), "uk": uk}):
        return

    from app.services.hrms_exception_service import approved_exception_for
    waiver = await approved_exception_for(
        company_id, "telephonic", (req or {}).get("request_no"), uk)
    if waiver:
        return

    rows = await get_collection(COLL_TELEPHONIC).find(
        {"company_id": str(company_id), "uk": uk}).to_list(50)
    name = candidate.get("candidate_name") or uk
    if rows:
        outcomes = ", ".join(sorted({r.get("outcome") or "?" for r in rows}))
        detail = (f"{name} has {len(rows)} telephonic screening(s) on record ({outcomes}), "
                  f"none of which passed. Record a passing screen, or log an approved "
                  f"exception to waive it.")
    else:
        detail = (f"No telephonic screening has been recorded for {name}. On internal roles "
                  f"the brief telephonic interview comes before the panel (SOP step 5), so "
                  f"three people's time is only booked once the call has been made. Record "
                  f"one, or log an approved exception to waive it.")
    raise HTTPException(status_code=409, detail=detail)


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def _advance_candidate(actor: dict, company_id: str, candidate: dict,
                             outcome: str) -> Optional[str]:
    """Move the candidate to the status this outcome implies, if it implies one.

    Goes through `can_transition` like every other stage move in the module: this service
    PROPOSES a target and the graph decides. An illegal move leaves the candidate where they
    are rather than corrupting the pipeline — a phone screen recorded against somebody who
    has already been interviewed is a data-entry mistake, and losing the interview stage to
    it would be worse than the mistake.
    """
    target = TELEPHONIC_STATUS_FOR_OUTCOME.get(outcome)
    if target is None:
        return None
    current = candidate.get("application_status")
    if current == target.value:
        return None
    if not can_transition(current, target):
        return None
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": candidate.get("uk"), "company_id": str(company_id)},
        {"$set": {"application_status": target.value,
                  "status_updated_at": datetime.now(timezone.utc)}})
    return target.value


async def create_screening(actor: dict, company_id: str, payload: dict) -> dict:
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    clean = _validate(payload, partial=False)
    year = datetime.now(timezone.utc).year
    tel_no = await next_business_id("telephonic", str(company_id), year)
    now = datetime.now(timezone.utc)

    # ── Phase INT-5 ── one settings read, used for BOTH the retention floor and the band.
    from app.services.hrms_config_service import config_for, retention_years_for, score_bands_for
    config = await config_for(company_id)
    score = weighted_score(clean)
    doc = {
        "tel_no": tel_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        # Carried so the single analytics scope filter reaches this collection too.
        "request_no": candidate.get("request_no"),
        "screened_by": str((actor or {}).get("_id") or ""),
        "screened_by_name": (actor or {}).get("full_name") or (actor or {}).get("email"),
        "score": score,
        # Surfaced, never auto-applied -- the same rule the position scorecard follows. A
        # rubric that silently rejects people is one nobody will trust or correct.
        "band": score_band(score, await score_bands_for(config)),
        "retention_until": _retention_until(
            clean.get("screened_on"),
            await retention_years_for(config, "telephonic")),
        "created_at": now,
        **clean,
    }
    await get_collection(COLL_TELEPHONIC).insert_one(dict(doc))

    moved_to = await _advance_candidate(actor, company_id, candidate, clean["outcome"])
    doc["candidate_moved_to"] = moved_to

    await audit(actor, AUDIT_TELEPHONIC_RECORDED, ENTITY_TELEPHONIC, tel_no,
                f'{clean["outcome"]} for {uk}'
                + (f" (score {score})" if score is not None else "")
                + (f", candidate -> {moved_to}" if moved_to else ""),
                company_id)
    return _out(doc)


async def update_screening(actor: dict, company_id: str, tel_no: str,
                           payload: dict) -> dict:
    coll = get_collection(COLL_TELEPHONIC)
    current = await coll.find_one({"tel_no": tel_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Telephonic screening not found.")

    # Cross-field rules are checked against the MERGED record, so flipping the outcome to
    # Rejected in an edit demands a note exactly as it does on creation.
    # Read BEFORE the write. `current` must not be consulted afterwards: whether it is still
    # the pre-update state depends on whether the driver handed back a copy or a live
    # reference, and a status move that works on one and silently does nothing on the other
    # is the worst kind of bug to own.
    previous_outcome = current.get("outcome")

    merged = {**current, **{k: v for k, v in (payload or {}).items() if v is not None}}
    clean = _validate({**merged, **(payload or {})}, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    from app.services.hrms_config_service import config_for, retention_years_for, score_bands_for
    config = await config_for(company_id)
    if "screened_on" in clean:
        clean["retention_until"] = _retention_until(
            clean["screened_on"], await retention_years_for(config, "telephonic"))
    # Recomputed from the merged record, so editing one rating rescores the whole screen
    # rather than leaving a score that no longer matches the numbers beside it.
    rescored = {**merged, **clean}
    clean["score"] = weighted_score(rescored)
    clean["band"] = score_band(clean["score"], await score_bands_for(config))
    clean["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"tel_no": tel_no, "company_id": str(company_id)},
                          {"$set": clean})

    moved_to = None
    if "outcome" in clean and clean["outcome"] != previous_outcome:
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": merged.get("uk"), "company_id": str(company_id)})
        if candidate:
            moved_to = await _advance_candidate(actor, company_id, candidate,
                                                clean["outcome"])

    await audit(actor, AUDIT_TELEPHONIC_UPDATED, ENTITY_TELEPHONIC, tel_no,
                ", ".join(sorted(k for k in clean if k != "updated_at"))
                + (f", candidate -> {moved_to}" if moved_to else ""),
                company_id)
    result = await get_screening(company_id, tel_no)
    if result is not None:
        result["candidate_moved_to"] = moved_to
    return result


async def screenable_candidates(actor: dict, company_id: str) -> list:
    """Internal-track candidates a phone screen is the next step for.

    Shortlisted and not yet screened. Deliberately internal-track only: the client track has
    no telephonic step in its process, and offering the action there would invite somebody to
    record one and then wonder why nothing gated on it.
    """
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id),
         "requisition_track": REQUISITION_TRACK_INTERNAL},
        {"request_no": 1, "designation_name": 1}).to_list(2000)
    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    designation = {r["request_no"]: r.get("designation_name") for r in reqs}
    if not request_nos:
        return []

    candidates = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id),
         # Fails CLOSED in the same way every other scoped read here does: an empty list is
         # an `$in: []`, matching nothing rather than everything.
         "request_no": {"$in": request_nos},
         "application_status": {"$in": [AppStatus.SHORTLISTED.value,
                                        AppStatus.UNDER_REVIEW.value]}},
        {"uk": 1, "candidate_name": 1, "request_no": 1, "application_status": 1,
         "can_contact": 1}).to_list(2000)

    out = []
    for c in candidates:
        rows = await get_collection(COLL_TELEPHONIC).find(
            {"company_id": str(company_id), "uk": c["uk"]}).to_list(50)
        if any(r.get("outcome") in TELEPHONIC_CLEARS_INTERVIEW for r in rows):
            continue
        out.append({
            "uk": c["uk"],
            "candidate_name": c.get("candidate_name"),
            "request_no": c.get("request_no"),
            "designation_name": designation.get(c.get("request_no")),
            "application_status": c.get("application_status"),
            "contact": c.get("can_contact"),
            "attempts": len(rows),
        })
    out.sort(key=lambda r: (-r["attempts"], r.get("candidate_name") or ""))
    return out
