"""HRMS > new-hire experience surveys (internal recruitment track, SOP §10).

Two of the SOP's eight KPIs were unbuildable without capture:

    "New-hire satisfaction / induction feedback score"

The induction checklist has an `induction_feedback` key, but a tick is not a score. Averaging
ticks into a number would invent data, which is why the KPI honestly reported "not captured"
until now. This module captures the number.

-- PSEUDONYMOUS TO THE REPORTING LAYER, and that is a hard rule ------------------------------
`employee_code` is stored for exactly ONE purpose: stopping the same person answering twice
(the unique index on (company_id, srv_no, employee_code) is what actually enforces it).

Everything the reporting layer can see is an AVERAGE, and `aggregate` refuses to return a
figure at all below SURVEY_MIN_RESPONSES. There is deliberately no endpoint that returns
response rows, no filter that narrows a breakdown to one person, and no join back to the
employee record.

This is not decoration. A satisfaction survey a manager can de-anonymise measures how much
people trust the survey, not how their induction went -- and the first time somebody works
out who wrote the low score, the instrument is finished for good.

-- Delivered through the EXISTING public-link registry ---------------------------------------
`LinkKind.SURVEY` and `/survey/{code}`, defended by `hrms_public_guard` with the same
fixed-window, DB-backed limits every other public surface uses. Nothing here invents a second
credential mechanism, so revocation, expiry and open-tracking work on a survey link for free.

-- Issued by an EVENT, not a schedule ---------------------------------------------------------
The induction survey fires when the induction checklist completes; the probation one when
probation is confirmed. Both are moments the module already knows about, so there is no
scheduler and nothing to run nightly.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SURVEY_ISSUED, AUDIT_SURVEY_SUBMITTED, COLL_EMPLOYEE_PROFILES, COLL_SURVEYS,
    COLL_SURVEY_RESPONSES, DEFAULT_SURVEYS, ENTITY_SURVEY, RETENTION_YEARS,
    SURVEY_MIN_RESPONSES, SURVEY_SCORE_MAX, SURVEY_SCORE_MIN, SURVEY_SUPPRESSED,
    LinkKind, SurveyKind,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_config_service import retention_years_for
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import INVALID_LINK, clean_text, new_access_code


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _add_years(iso_date: str, years: int) -> str:
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


# =============================================================
# Instruments
# =============================================================
async def list_surveys(company_id: str, *, include_inactive: bool = False) -> list:
    """The company's instruments, seeding the two defaults on first read.

    Seeded on READ, exactly as document types and communication templates are.
    """
    coll = get_collection(COLL_SURVEYS)
    if not await coll.count_documents({"company_id": str(company_id)}):
        await _seed_surveys(company_id)
    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await coll.find(query).sort("kind", 1).to_list(50)
    return [_out(r) for r in rows]


async def _seed_surveys(company_id: str) -> None:
    now = datetime.now(timezone.utc)
    for kind, title, intro, questions in DEFAULT_SURVEYS:
        try:
            srv_no = await next_business_id("survey", str(company_id), now.year)
            await get_collection(COLL_SURVEYS).insert_one({
                "srv_no": srv_no,
                "company_id": str(company_id),
                "kind": kind.value,
                "title": title,
                "intro": intro,
                "questions": [{"key": key, "prompt": prompt} for key, prompt in questions],
                "active": True,
                "seeded": True,
                "created_at": now,
            })
        except Exception as e:
            print(f"[WARN] HRMS survey seeding skipped for {company_id}/{kind}: {e}")


async def survey_for_kind(company_id: str, kind) -> Optional[dict]:
    kind_value = getattr(kind, "value", kind)
    await list_surveys(company_id)          # seeds on first touch
    doc = await get_collection(COLL_SURVEYS).find_one(
        {"company_id": str(company_id), "kind": kind_value, "active": True})
    return _out(doc) if doc else None


# =============================================================
# Issuing
# =============================================================
async def issue_survey(actor: Optional[dict], company_id: str, kind, *,
                       employee_code: str, request_no: str = None,
                       employee_name: str = None) -> Optional[dict]:
    """Mint a survey link for one person. Never raises into the caller.

    Called from the two moments the module already knows about -- the induction checklist
    completing and probation being confirmed -- so it must not be able to fail either of
    them. A survey that could not be issued is a missing data point; a rolled-back probation
    confirmation is somebody's employment.

    IDEMPOTENT per (instrument, employee): re-running the induction completion does not
    issue a second link, because two live links to one instrument means two responses from
    one person, which the aggregate would then count twice.
    """
    try:
        survey = await survey_for_kind(company_id, kind)
        if not survey:
            return None

        responses = get_collection(COLL_SURVEY_RESPONSES)
        existing = await responses.find_one({
            "company_id": str(company_id), "srv_no": survey["srv_no"],
            "employee_code": employee_code})
        if existing:
            return _out(existing)

        now = datetime.now(timezone.utc)
        srp_no = await next_business_id("survey_response", str(company_id), now.year)
        code = new_access_code()
        row = {
            "srp_no": srp_no,
            "company_id": str(company_id),
            "srv_no": survey["srv_no"],
            "kind": survey["kind"],
            "access_code": code,
            # Stored for DE-DUPLICATION ONLY. Nothing in the reporting path reads it, and
            # `aggregate` never returns a row -- see the module docstring.
            "employee_code": employee_code,
            "request_no": request_no,
            "issued_at": now,
            "submitted_at": None,
            "scores": {},
            "average": None,
            "comment": None,
            # SOP §13. A survey response belongs to the employment record it is about.
            "retention_until": _add_years(
                now.strftime("%Y-%m-%d"),
                await retention_years_for(company_id, "probation")),
            "created_at": now,
        }
        await responses.insert_one(dict(row))

        from app.services.hrms_link_service import register_link
        await register_link(
            company_id=company_id, kind=LinkKind.SURVEY, code=code,
            target_type="survey_response", target_id=srp_no, actor=actor,
            candidate_name=employee_name, request_no=request_no)

        await audit(actor, AUDIT_SURVEY_ISSUED, ENTITY_SURVEY, srp_no,
                    f'{survey["kind"]} survey issued', company_id)
        return _out(row)
    except Exception as e:
        # Deliberately swallowed -- see the docstring.
        print(f"[WARN] HRMS survey issue failed ({employee_code}): {e}")
        return None


# =============================================================
# The public surface
# =============================================================
async def get_public_survey(code: str) -> dict:
    """The questionnaire behind a link.

    Returns the questions and NOTHING about the person: no employee code, no name, no
    requisition. The respondent already knows who they are, and a page that echoes their
    identity back is a page that can be screenshotted next to their answers.
    """
    row = await get_collection(COLL_SURVEY_RESPONSES).find_one({"access_code": code})
    if not row:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    survey = await get_collection(COLL_SURVEYS).find_one(
        {"srv_no": row.get("srv_no"), "company_id": row.get("company_id")})
    if not survey:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    return {
        "ok": True,
        "already_submitted": bool(row.get("submitted_at")),
        "title": survey.get("title"),
        "intro": survey.get("intro"),
        "questions": survey.get("questions") or [],
        "scale": {"min": SURVEY_SCORE_MIN, "max": SURVEY_SCORE_MAX,
                  "labels": {str(SURVEY_SCORE_MIN): "Strongly disagree",
                             str(SURVEY_SCORE_MAX): "Strongly agree"}},
        "anonymity_note": (
            "Your answers are reported as averages across everyone who joined in the same "
            f"period, and never shown for fewer than {SURVEY_MIN_RESPONSES} people. Nobody "
            "sees your individual response."),
    }


async def submit_public_survey(code: str, payload: dict) -> dict:
    """Record one submission. Entirely untrusted input.

    Once submitted, a response is FINAL. Re-opening it would mean a live link that can
    rewrite an average after somebody has read it, and the honest way to change an answer is
    to be asked again next time.
    """
    coll = get_collection(COLL_SURVEY_RESPONSES)
    row = await coll.find_one({"access_code": code})
    if not row:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if row.get("submitted_at"):
        raise HTTPException(
            status_code=409, detail="You have already answered this survey. Thank you.")

    survey = await get_collection(COLL_SURVEYS).find_one(
        {"srv_no": row.get("srv_no"), "company_id": row.get("company_id")})
    if not survey:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    keys = [q["key"] for q in (survey.get("questions") or [])]
    raw = payload.get("scores") or {}
    scores = {}
    for key in keys:
        if key not in raw:
            raise HTTPException(
                status_code=422,
                detail="Please answer every question before submitting.")
        try:
            value = int(raw[key])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="Each answer is a number from 1 to 5.")
        if value < SURVEY_SCORE_MIN or value > SURVEY_SCORE_MAX:
            raise HTTPException(
                status_code=422,
                detail=f"Each answer is a number from {SURVEY_SCORE_MIN} to "
                       f"{SURVEY_SCORE_MAX}.")
        scores[key] = value

    now = datetime.now(timezone.utc)
    average = round(sum(scores.values()) / len(scores), 2) if scores else None
    result = await coll.update_one(
        {"access_code": code, "submitted_at": None},
        {"$set": {"scores": scores, "average": average,
                  "comment": clean_text(payload.get("comment"), limit=4000),
                  "submitted_at": now, "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="You have already answered this survey. Thank you.")

    # Audited against the RESPONSE id, never the employee: the audit trail is readable by
    # anybody with `audit.read`, and an entry saying "EMP-2026-014 submitted their induction
    # survey" beside a timestamp is most of the way to de-anonymising it.
    await audit(None, AUDIT_SURVEY_SUBMITTED, ENTITY_SURVEY, row.get("srp_no"),
                f'{survey.get("kind")} response recorded', row.get("company_id"))

    return {"ok": True,
            "message": "Thank you — your answers have been recorded anonymously."}


# =============================================================
# Reporting — averages only, and only above the threshold
# =============================================================
async def aggregate(company_id: str, *, kind=None, request_nos=None,
                    date_from: str = None, date_to: str = None) -> dict:
    """Mean scores across submitted responses.

    Returns SCORES, never rows. Below SURVEY_MIN_RESPONSES it returns no figure at all and
    says why -- suppressing the number rather than rounding it, because a rounded average of
    two people is still two people's answers.

    The per-question breakdown is suppressed by the SAME threshold as the overall mean. A
    caller who could see question-level averages for three respondents could reconstruct
    most of an individual response from them, so the two stand or fall together.
    """
    query = {"company_id": str(company_id), "submitted_at": {"$ne": None}}
    if kind:
        query["kind"] = getattr(kind, "value", kind)
    if request_nos is not None:
        # Fails CLOSED like every other scoped read: an empty list matches nothing.
        query["request_no"] = {"$in": list(request_nos)}
    if date_from or date_to:
        window = {}
        if date_from:
            window["$gte"] = datetime.strptime(date_from, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        if date_to:
            window["$lte"] = datetime.strptime(date_to, "%Y-%m-%d").replace(
                tzinfo=timezone.utc, hour=23, minute=59, second=59)
        query["submitted_at"] = window

    rows = await get_collection(COLL_SURVEY_RESPONSES).find(query).to_list(20000)
    n = len(rows)
    if n < SURVEY_MIN_RESPONSES:
        return {
            "kind": getattr(kind, "value", kind),
            "responses": n,
            "min_responses": SURVEY_MIN_RESPONSES,
            "suppressed": True,
            "average": None,
            "by_question": [],
            "reason": SURVEY_SUPPRESSED,
        }

    averages = [r["average"] for r in rows if r.get("average") is not None]
    overall = round(sum(averages) / len(averages), 2) if averages else None

    per_question = {}
    for r in rows:
        for key, value in (r.get("scores") or {}).items():
            per_question.setdefault(key, []).append(value)
    by_question = [
        {"key": key, "average": round(sum(values) / len(values), 2),
         "responses": len(values)}
        for key, values in sorted(per_question.items())
    ]

    return {
        "kind": getattr(kind, "value", kind),
        "responses": n,
        "min_responses": SURVEY_MIN_RESPONSES,
        "suppressed": False,
        "average": overall,
        "scale_max": SURVEY_SCORE_MAX,
        "by_question": by_question,
        "reason": None,
    }


async def issue_rate(company_id: str, *, request_nos=None) -> dict:
    """How many issued surveys came back. Counts only -- no identities, no rows.

    Reported alongside the average because a 4.8 from two of forty people is a different
    fact from a 4.8 from thirty-five, and the KPI would otherwise present them identically.
    """
    query = {"company_id": str(company_id)}
    if request_nos is not None:
        query["request_no"] = {"$in": list(request_nos)}
    rows = await get_collection(COLL_SURVEY_RESPONSES).find(
        query, {"submitted_at": 1, "kind": 1}).to_list(20000)
    issued = len(rows)
    returned = sum(1 for r in rows if r.get("submitted_at"))
    return {"issued": issued, "returned": returned,
            "response_rate": (round(returned * 100.0 / issued, 1) if issued else None)}
