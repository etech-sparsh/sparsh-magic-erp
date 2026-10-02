"""
TPMS ▸ Forms sub-module — API routes.

Endpoints (all mounted under /api):
  GET  /forms/definitions                         list all form definitions
  GET  /forms/{form_type}/definition              one form's criteria/scale
  GET  /forms/members                             candidate team members to rate
  POST /forms/{form_type}/submissions             save a submission
  GET  /forms/{form_type}/submissions             list submissions (filterable)
  GET  /forms/submissions/{submission_id}         fetch one submission

Data is stored atomically per (company, period, hod, member, criterion) so that
future Success Measure calculations can aggregate freely. No Success Measure
computation is performed here — this module only captures and serves the data.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.forms import (
    AUDIENCE_DEPARTMENT,
    FORM_DEFINITIONS,
    FORM_COLLECTIONS,
    ACTIVITY_CATALOGUE,
    ACTIVITY_FORM_MAP,
    submission_collection,
    get_definition,
    criteria_codes,
    form_kind,
    form_audience,
    form_min_level,
    eligible_by_level,
    user_level,
    user_level_number,
    question_map,
    RatingSubmissionCreate,
    FeedbackSubmissionCreate,
    SCALE_MIN,
    SCALE_MAX,
    KIND_RATING_MATRIX,
    KIND_YESNO_CHECKLIST,
    QUESTION_COLLECTION,
    definition_items,
)
from app.models.tpms import period_parts, period_tokens, TPMS_EVENT_KIND

async def _tpms_company_gate(current_user: dict = Depends(get_current_user)) -> None:
    """Router-wide guard — see the twin in routes/tpms.py. The TPMS forms module is part of
    TPMS, so a company with TPMS switched off cannot open, submit or read any of it."""
    from app.utils.tpms_access import ensure_tpms_enabled
    await ensure_tpms_enabled(current_user)


router = APIRouter(prefix="/forms", tags=["TPMS Forms"],
                   dependencies=[Depends(_tpms_company_gate)])

# Each form is stored in its own collection ("table") — see FORM_COLLECTIONS in
# app.models.forms. Resolve the collection for a form_type via submission_collection().

# Internal staff (the /tpms/admin panel) may submit on behalf of anyone.
STAFF_ROLES = {"superadmin", "admin"}
# Client-side users fill TPMS forms for themselves (HODs rate their team; everyone
# submits Culture + Implementation Feedback). Their writes are self-scoped below.
CLIENT_ROLES = {"clientadmin", "clientuser"}


def _is_staff(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES


def _is_client(user: dict) -> bool:
    return user.get("role") in CLIENT_ROLES


def _self_id(user: dict) -> str:
    """The identity a client-side user submits under. Standardised to the Mongo _id
    (also used to exclude self from the team roster and to scope reads/writes)."""
    return str(user.get("_id"))


def _can_write(user: dict) -> bool:
    if _is_staff(user):
        return True
    if _is_client(user):
        return True
    # Also honour the granular permission flag if present.
    return bool(user.get("permissions", {}).get("forms", {}).get("create"))


def _can_read(user: dict) -> bool:
    if _is_staff(user) or _is_client(user):
        return True
    # Not open-by-default: any other role (e.g. SMOps `staff`, who read reviews via the
    # scoped review-report route instead) needs an explicit grant. Closes the previous
    # default-True that let a non-client caller list submissions across every company.
    return bool(user.get("permissions", {}).get("forms", {}).get("read", False))


def _user_department(user: dict) -> str:
    # C8 — form audience is a governance ROLE (hod/md). Prefer an explicit `governance_role`
    # so `department` can hold the real org department; fall back for un-migrated users.
    return (user.get("governance_role") or user.get("department") or "").strip().lower()


def _is_hod(user: dict) -> bool:
    return _user_department(user) == "hod"


async def _has_explicit_assignment(company_id: str, respondent_id: str,
                                   form_type: str, period: str) -> bool:
    """Was this person deliberately put on this form's schedule for this period?

    Scheduling a form lets an admin pick the doers by hand, and that choice already overrides
    the audience rule on the way OUT: tpms_form_link_service.eligible_respondents mails the
    exact people chosen, whatever role they hold. This is the same question asked on the way
    back IN, so the two halves agree.
    """
    if not (company_id and respondent_id and form_type and period):
        return False
    from app.services.tpms_form_link_service import ASSIGNMENT_COLLECTION
    found = await get_collection(ASSIGNMENT_COLLECTION).find_one({
        "form_type": form_type,
        "company_id": str(company_id),
        "respondent_id": str(respondent_id),
        "period": period,
    })
    return bool(found)


async def _enforce_client_scope(user: dict, company_id: str, respondent_id: str,
                                form_type: str, period: str = "") -> None:
    """Defence-in-depth for client-side submissions. Staff bypass all of this.
    A client user may only write:
      • within their own company, and
      • under their own identity (as the HOD/MD/respondent),
      • and department-gated forms only from the matching department
        ('hod' → Accountability/Ownership/Culture, 'md' → Implementation Feedback),
        UNLESS they were explicitly scheduled to fill this one.
    """
    if _is_staff(user):
        return
    if not _is_client(user):
        # Only staff (bypass) and clients (scoped below) may write forms. Any other role —
        # even one holding the granular create flag — is rejected rather than being allowed
        # an unscoped, arbitrary-company submission.
        raise HTTPException(status_code=403, detail="Not authorized to submit forms.")
    if company_id != (user.get("company_id") or ""):
        raise HTTPException(status_code=403, detail="You can only submit forms for your own company.")
    if respondent_id != _self_id(user):
        raise HTTPException(status_code=403, detail="You can only submit your own form.")
    required_dept = AUDIENCE_DEPARTMENT.get(form_audience(form_type))
    if required_dept and _user_department(user) != required_dept:
        # An explicit schedule beats the audience rule. The doer picker lets an admin send
        # Culture/Ownership/Accountability to an MD (or HR, or an implementor), and the mail
        # goes out and the link opens — but this check knew nothing about that choice, so the
        # form was filled in and then refused at Save. Whoever was actually scheduled to fill
        # it may submit it; everyone else still needs the matching role.
        if not await _has_explicit_assignment(company_id, respondent_id, form_type, period):
            raise HTTPException(
                status_code=403,
                detail=f"Only a{'n' if required_dept == 'hod' else ''} {required_dept.upper()} can submit this form.",
            )


def _require_form_type(form_type: str) -> dict:
    definition = get_definition(form_type)
    if not definition:
        raise HTTPException(status_code=404, detail=f"Unknown form type '{form_type}'")
    return definition


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


def _user_display_name(user: dict) -> str:
    return (
        user.get("full_name")
        or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
        or user.get("name")
        or user.get("email")
        or "Unknown"
    )


# ─────────────────────────────────────────────────────────────
# Form definitions (criteria registry)
# ─────────────────────────────────────────────────────────────
# ─── M10 — question master (editable question TEXT; item ids never change) ───
async def _seed_questions_if_empty():
    coll = get_collection(QUESTION_COLLECTION)
    if await coll.count_documents({}) > 0:
        return
    rows = []
    for ft, d in FORM_DEFINITIONS.items():
        rows.extend(definition_items(ft, d))
    if rows:
        try:
            await coll.insert_many(rows)
        except Exception:
            pass


async def _effective_definition(form_type: str, definition: dict) -> dict:
    """Overlay the master's edited text onto a form definition (same item ids/order)."""
    docs = await get_collection(QUESTION_COLLECTION).find(
        {"form_type": form_type, "active": {"$ne": False}}
    ).sort("order", 1).to_list(200)
    if not docs:
        return definition
    d = dict(definition)
    if definition.get("kind") == KIND_RATING_MATRIX:
        d["criteria"] = [{"code": x["item_id"], "title": x.get("title", ""),
                          "prompt": x.get("prompt", "")} for x in docs]
    else:
        d["questions"] = [{"id": x["item_id"], "title": x.get("title", ""),
                           "desc": x.get("desc", "")} for x in docs]
    return d


async def _effective_criteria_codes(form_type: str) -> list:
    """Live criterion codes for a rating form (question master overlaid), so add/remove of
    criteria takes effect for submission validation. Falls back to the hard-coded list."""
    await _seed_questions_if_empty()
    d = await _effective_definition(form_type, get_definition(form_type) or {})
    return [c["code"] for c in d.get("criteria", [])]


async def _effective_question_map(form_type: str) -> dict:
    """Live question map for a checklist form (question master overlaid)."""
    await _seed_questions_if_empty()
    d = await _effective_definition(form_type, get_definition(form_type) or {})
    return {str(q["id"]): q for q in d.get("questions", [])}


@router.get("/definitions")
async def list_definitions(current_user: dict = Depends(get_current_user)):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    await _seed_questions_if_empty()
    out = []
    for ft, d in FORM_DEFINITIONS.items():
        out.append(await _effective_definition(ft, d))
    return {"definitions": out}


# ─── Schedule-driven "My Forms" — the forms this user must fill, by period + status ───
_FORM_TYPE_ORDER = ["accountability", "ownership", "culture", "implementation_feedback"]


@router.get("/my-forms")
async def my_forms(current_user: dict = Depends(get_current_user)):
    """The connected form flow: for the logged-in respondent (HOD/MD), list the forms they
    must fill — one entry per (form × period) derived from the SCHEDULED form-activities for
    their company (plus the current period), each with submission status. Replaces the flat
    Forms menu with a contextual, schedule-driven task list."""
    if not _is_client(current_user):
        return {"forms": []}  # forms are filled by client-side HOD/MD respondents
    company_id = str(current_user.get("company_id") or "")
    uid = str(current_user.get("_id") or "")
    dept = _user_department(current_user)  # governance role (hod/md), governance_role-aware

    # Which forms can this respondent fill: the ones their governance role owns, plus any they
    # were explicitly scheduled for. This list is meant to be schedule-driven, but it was built
    # from the role alone — so a form handed to an MD (or HR, or an implementor) through the
    # doer picker never appeared here, and the only way in was the emailed link. The mailing
    # side and the submit check both honour an explicit choice; this now agrees with them.
    assigned_types = set()
    if company_id:
        from app.services.tpms_form_link_service import ASSIGNMENT_COLLECTION
        assigned_types = set(await get_collection(ASSIGNMENT_COLLECTION).distinct(
            "form_type", {"company_id": company_id, "respondent_id": uid}))
    eligible = [ft for ft in _FORM_TYPE_ORDER
                if AUDIENCE_DEPARTMENT.get(form_audience(ft)) == dept or ft in assigned_types]
    if not eligible or not company_id:
        return {"forms": []}

    # form_type → the activity that feeds it.
    rev: dict = {}
    for activity, forms in ACTIVITY_FORM_MAP.items():
        for f in forms:
            rev.setdefault(f, activity)

    now = datetime.utcnow()
    current_period = f"{now.year:04d}-{now.month:02d}"

    out = []
    for ft in eligible:
        activity = rev.get(ft)
        if not activity:
            continue
        # Periods where this form-activity was scheduled for the company (+ the current month).
        periods = {current_period}
        for coll in _CAL_COLLECTIONS:
            for e in await get_collection(coll).find(
                {"company_id": company_id, "activity": activity}
            ).to_list(500):
                dt = _parse_dt(e.get("start"))
                if dt:
                    periods.add(f"{dt.year:04d}-{dt.month:02d}")
        # This respondent's existing submissions (match hod_id / md_id).
        my_sub_periods = set()
        for s in await get_collection(submission_collection(ft)).find(
            {"company_id": company_id}
        ).to_list(3000):
            if str(s.get("hod_id") or s.get("md_id") or "") == uid:
                my_sub_periods.add(str(s.get("period") or ""))
        for period in sorted(periods, reverse=True):
            tokens = set(period_tokens(period)) | {period}
            out.append({
                "form_type": ft,
                "title": FORM_DEFINITIONS[ft]["title"],
                "activity": activity,
                "period": period,
                "status": "submitted" if (tokens & my_sub_periods) else "pending",
            })
    return {"forms": out}


@router.get("/questions")
async def list_questions(
    form_type: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """M10 — the editable question master (Admin)."""
    if (current_user.get("role") or "").lower() not in {"superadmin", "admin"}:
        raise HTTPException(status_code=403, detail="Admin only")
    await _seed_questions_if_empty()
    query = {}
    if form_type:
        query["form_type"] = form_type
    docs = await get_collection(QUESTION_COLLECTION).find(query).sort([("form_type", 1), ("order", 1)]).to_list(500)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"questions": docs}


@router.post("/questions")
async def create_question(payload: dict, current_user: dict = Depends(get_current_user)):
    """M10 (add) — append a new criterion/question to a form. The pooled scoring formula is
    robust to the number of items, and submission validation now reads this master, so adds
    take effect immediately. `item_id` must be unique within the form; auto-generated if omitted."""
    if (current_user.get("role") or "").lower() not in {"superadmin", "admin"}:
        raise HTTPException(status_code=403, detail="Admin only")
    await _seed_questions_if_empty()
    form_type = str(payload.get("form_type") or "").strip()
    definition = FORM_DEFINITIONS.get(form_type)
    if not definition:
        raise HTTPException(status_code=400, detail="Unknown form_type")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    kind = definition.get("kind")
    coll = get_collection(QUESTION_COLLECTION)
    existing = await coll.find({"form_type": form_type}).to_list(500)
    item_id = str(payload.get("item_id") or "").strip()
    if not item_id:
        prefix = "Q" if kind == KIND_YESNO_CHECKLIST else (form_type[:1].upper() or "X")
        item_id = f"{prefix}{len(existing) + 1}"
    if any(str(e.get("item_id")) == item_id for e in existing):
        raise HTTPException(status_code=409, detail=f"Item id '{item_id}' already exists for this form")
    doc = {
        "form_type": form_type, "kind": kind, "item_id": item_id,
        "title": title,
        "prompt": str(payload.get("prompt") or "") if kind == KIND_RATING_MATRIX else "",
        "desc": str(payload.get("desc") or "") if kind == KIND_YESNO_CHECKLIST else "",
        "order": max([int(e.get("order") or 0) for e in existing], default=-1) + 1,
        "active": True,
    }
    await coll.insert_one(doc)
    return {"ok": True, "item_id": item_id}


@router.patch("/questions/{question_id}")
async def update_question(question_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """M10 — reword a question/criterion (text only). Item ids are immutable so scoring and
    submission validation are unaffected."""
    if (current_user.get("role") or "").lower() not in {"superadmin", "admin"}:
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        oid = ObjectId(question_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid question id")
    updates = {k: str(payload[k]) for k in ("title", "prompt", "desc") if k in payload}
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await get_collection(QUESTION_COLLECTION).update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"ok": True}



# ─────────────────────────────────────────────────────────────
# Reporting hierarchy — who a rater may actually rate.
#
# The rating forms ask an HOD to score THEIR OWN TEAM, so the roster is the set of users whose
# `reporting_manager` points at that HOD. It used to fall back to the entire company roster
# whenever that produced nothing, which is what put every employee — the MD included — on a
# form headed "rate each of your team members".
#
# The fallback is gone. An unmapped reporting line is a data gap to close in Company Users, and
# a form that quietly lists people the rater does not manage is worse than one that says the
# team is not mapped yet: the ratings it collects are meaningless and cannot be told apart from
# real ones afterwards.
# ─────────────────────────────────────────────────────────────
async def _manager_identities(manager_id: str) -> List[str]:
    """Every value a subordinate's `reporting_manager` might legitimately hold for this manager.

    Normally it is the manager's `_id` as a string — that is what the picker in Company Users
    stores. The bulk user upload, however, writes whatever the spreadsheet's "Reporting Manager"
    column said when it cannot resolve it to a user (routes/company.py), so an email or an
    employee code can be sitting there instead. Matching all of them means an existing, correct
    mapping is honoured whichever way it was entered, and only a genuinely absent one reads as
    "no team".
    """
    keys = {str(manager_id).strip()}
    doc = None
    try:
        oid = ObjectId(str(manager_id))
        doc = (await get_collection("learners").find_one({"_id": oid})
               or await get_collection("staff").find_one({"_id": oid}))
    except (InvalidId, TypeError):
        doc = None
    for field in ("email", "employee_id", "emp_id", "emp_code"):
        value = (doc or {}).get(field)
        if value is not None and str(value).strip():
            keys.add(str(value).strip())
    return [k for k in keys if k]


async def _reporting_team(company_id: str, manager_id: str) -> List[dict]:
    """This manager's direct reports in this company, across both user collections.

    `staff` is searched as well as `learners` because an internal user can sit under a client
    manager; reading only `learners` silently dropped them from the roster.
    """
    if not manager_id or not company_id:
        return []
    query = {
        "company_id": str(company_id),
        "is_active": {"$ne": False},
        "reporting_manager": {"$in": await _manager_identities(manager_id)},
    }
    team = await get_collection("learners").find(query).to_list(1000)
    team += await get_collection("staff").find(query).to_list(1000)
    # A self-referential mapping would otherwise ask someone to rate themselves.
    return [u for u in team if str(u.get("_id")) != str(manager_id)]


# ─────────────────────────────────────────────────────────────
# Candidate members to rate (sourced from existing users)
# ─────────────────────────────────────────────────────────────
@router.get("/members")
async def list_members(
    company_id: str = Query(..., description="Company to load team members for"),
    hod_id: Optional[str] = Query(None, description="Exclude this HOD from the member list"),
    form_type: Optional[str] = Query(None, description="Form type being generated/filled"),
    current_user: dict = Depends(get_current_user),
):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    # Client-side users may only load their own company's roster.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    # An HOD rates only their own reporting subordinates — never the whole company (see
    # _reporting_team). Without an HOD there is no team to resolve, so the roster is empty
    # rather than "everybody".
    team = await _reporting_team(company_id, hod_id) if hod_id else []
    team_size = len(team)
    pool = team

    # Level gate (Ownership → L4 and above). The threshold comes from the form registry, so it
    # is the same number the assigned-link roster, the submit validation and the UI use.
    min_level = form_min_level(form_type or "")
    pool = eligible_by_level(pool, form_type or "")

    members = []
    for u in pool:
        uid = str(u["_id"])
        emp = u.get("employee_id") or u.get("emp_id") or u.get("emp_code")
        if hod_id and hod_id in (uid, emp):
            continue
        members.append({
            "member_id": uid,
            "employee_id": emp,
            "member_name": _user_display_name(u),
            "designation": u.get("designation"),
            "department": u.get("department"),
            "role": u.get("role"),
            "level": user_level(u),
        })
    members.sort(key=lambda m: (m.get("member_name") or "").lower())
    # `min_level` and `team_size` are echoed back so the form can say WHY a roster is short
    # rather than just rendering fewer rows (or an empty table) with no explanation:
    # team_size 0 means no reporting line is mapped, while team_size > 0 with no members means
    # the team exists but nobody in it meets the form's level gate.
    return {"members": members, "scoped_to_team": True, "min_level": min_level,
            "team_size": team_size}


# ─────────────────────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────────────────────
def _matrix_key(form_type: str, company_id: str, period: str, hod_id: str) -> dict:
    return {"form_type": form_type, "company_id": company_id, "period": period, "hod_id": hod_id}


@router.get("/{form_type}/ratings")
async def get_ratings(
    form_type: str,
    company_id: str = Query(...),
    period: str = Query(...),
    hod_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Existing ratings for (company, period, HOD) so the UI can lock saved cells."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_RATING_MATRIX:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a rating form")
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are scoped to their own company + identity.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        hod_id = _self_id(current_user)

    doc = await get_collection(submission_collection(form_type)).find_one(
        _matrix_key(form_type, company_id.strip(), period.strip(), hod_id.strip())
    )
    ratings = (doc or {}).get("ratings", {})           # { code: { member_id: {rating, ...} } }
    count = sum(len(v) for v in ratings.values())
    return {
        "submitted": count > 0,
        "submitted_on": (doc or {}).get("created_at"),
        "ratings": ratings,
        "count": count,
    }


@router.post("/{form_type}/ratings")
async def submit_ratings(
    form_type: str,
    payload: RatingSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Cell-level partial submit: append only (criterion × member) cells not already saved."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_RATING_MATRIX:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a rating form; use the feedback endpoint")
    if not _can_write(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to submit forms")
    if not definition.get("available"):
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not yet available for submission")

    valid_codes = set(await _effective_criteria_codes(form_type))  # live master (add/remove)
    if not valid_codes:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' has no criteria configured")

    # Client-side users submit for themselves in their own company — the payload's
    # company_id/hod_id are ignored in favour of the authenticated identity.
    company_id = payload.company_id
    hod_id = payload.hod_id
    hod_name = payload.hod_name
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        hod_id = _self_id(current_user)
        hod_name = _user_display_name(current_user)
    await _enforce_client_scope(current_user, company_id, hod_id, form_type, payload.period)

    # Valid members = the company's own roster (staff + learners). Criteria are validated
    # against the live master above; members must be validated too so a client can't inject
    # an arbitrary person into their company's ratings.
    # A level-restricted form (Ownership → L4 and above) narrows this set too: the rule has to
    # hold on the WRITE path, or a stale page left open before someone's level changed could
    # still file ratings for a member the form no longer covers.
    min_level = form_min_level(form_type)
    valid_members: set = set()
    for coll_name in ("staff", "learners"):
        for u in await get_collection(coll_name).find(
                {"company_id": company_id, "is_active": {"$ne": False}},
                {"_id": 1, "employee_id": 1, "level": 1, "leadership_level": 1}).to_list(2000):
            if min_level and user_level_number(u) < min_level:
                continue
            valid_members.add(str(u["_id"]))
            if u.get("employee_id"):
                valid_members.add(str(u["employee_id"]))

    key = _matrix_key(form_type, company_id, payload.period, hod_id)
    existing = await get_collection(submission_collection(form_type)).find_one(key)
    saved = (existing or {}).get("ratings", {})

    now = datetime.utcnow()
    who = str(current_user.get("_id"))
    who_name = _user_display_name(current_user)

    set_fields: Dict[str, dict] = {}
    added = 0
    for cell in payload.ratings:
        if cell.criterion_code not in valid_codes:
            raise HTTPException(status_code=400, detail=f"Unknown criterion '{cell.criterion_code}'")
        if valid_members and str(cell.member_id) not in valid_members:
            detail = (f"'{cell.member_name}' is not rated on this form — it covers L{min_level} "
                      f"and above only. Refresh the form to load the current team list."
                      ) if min_level else f"Unknown member '{cell.member_id}'"
            raise HTTPException(status_code=400, detail=detail)
        # Skip a cell that's already on file (append-only, no duplicates).
        if saved.get(cell.criterion_code, {}).get(cell.member_id) is not None:
            continue
        set_fields[f"ratings.{cell.criterion_code}.{cell.member_id}"] = {
            "rating": cell.rating,
            "member_name": cell.member_name,
            "designation": cell.designation,
            "employee_id": cell.employee_id,
            "criterion": cell.criterion_code,
            "rated_at": now,
            "rated_by": who,
            "rated_by_name": who_name,
        }
        added += 1

    if not added:
        raise HTTPException(
            status_code=400,
            detail="Nothing new to save — the selected cells were already submitted.",
        )

    set_fields["updated_at"] = now
    set_fields["hod_name"] = hod_name
    await get_collection(submission_collection(form_type)).update_one(
        key,
        {
            "$set": set_fields,
            "$setOnInsert": {
                **key,
                "kind": KIND_RATING_MATRIX,
                "criteria_codes": list(valid_codes),
                "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
                "created_at": now,
                "created_by": who,
                "created_by_name": who_name,
            },
        },
        upsert=True,
    )

    total_saved = sum(len(v) for v in saved.values()) + added

    # H3 — form-submission mails (HOD summary + per-employee scorecards). Gated by the TPMS
    # notification switch, so this is a no-op while notifications are off.
    try:
        from app.services.tpms_notify_service import notify_form_submission
        await notify_form_submission(
            form_type=form_type, title=definition["title"],
            company_id=company_id, period=payload.period,
            respondent_id=hod_id, respondent_name=hod_name or "",
            ratings=[c.model_dump() for c in payload.ratings],
        )
    except Exception as _e:
        pass  # mail must never fail the submission

    return {
        "message": f"{definition['title']}: {added} rating(s) saved",
        "count": added,
        "total_saved": total_saved,
    }


# ─────────────────────────────────────────────────────────────
# yesno_checklist (Implementation Feedback) — partial submission
# ─────────────────────────────────────────────────────────────
def _feedback_key(form_type: str, company_id: str, period: str, md_id: str) -> dict:
    return {"form_type": form_type, "company_id": company_id, "period": period, "md_id": md_id}


@router.get("/{form_type}/feedback")
async def get_feedback(
    form_type: str,
    company_id: str = Query(...),
    period: str = Query(...),
    md_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Existing answers for (company, period, MD) so the UI can lock what's already saved."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_YESNO_CHECKLIST:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a feedback form")
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are scoped to their own company + identity.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        md_id = _self_id(current_user)

    doc = await get_collection(submission_collection(form_type)).find_one(
        _feedback_key(form_type, company_id.strip(), period.strip(), md_id.strip())
    )
    answers = (doc or {}).get("answers", {})
    return {
        "submitted": bool(answers),
        "submitted_on": (doc or {}).get("created_at"),
        "answers": answers,          # { question_id: {question, checked, remark, ...} }
        "count": len(answers),
    }


@router.post("/{form_type}/feedback")
async def submit_feedback(
    form_type: str,
    payload: FeedbackSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Slot-by-slot submit: append only questions not already saved for this (company, period, MD)."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_YESNO_CHECKLIST:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a feedback form")
    if not _can_write(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to submit forms")
    if not definition.get("available"):
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not yet available for submission")

    qmap = await _effective_question_map(form_type)  # live master (add/remove)
    if not qmap:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' has no questions configured")

    # Client-side users submit their own response in their own company.
    company_id = payload.company_id
    md_id = payload.md_id
    md_name = payload.md_name
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        md_id = _self_id(current_user)
        md_name = _user_display_name(current_user)
    await _enforce_client_scope(current_user, company_id, md_id, form_type, payload.period)

    key = _feedback_key(form_type, company_id, payload.period, md_id)
    existing = await get_collection(submission_collection(form_type)).find_one(key)
    already = set((existing or {}).get("answers", {}).keys())

    now = datetime.utcnow()
    who = str(current_user.get("_id"))
    who_name = _user_display_name(current_user)

    new_answers: Dict[str, dict] = {}
    skipped_unknown, skipped_existing = [], []
    for a in payload.answers:
        qid = a.question_id
        if qid not in qmap:
            skipped_unknown.append(qid)
            continue
        if qid in already:
            skipped_existing.append(qid)
            continue
        # Only persist a slot that was actually answered (ticked) or has a remark.
        if not a.checked and not (a.remark or "").strip():
            continue
        new_answers[qid] = {
            "question": a.question or qmap[qid].get("title", ""),
            "checked": bool(a.checked),
            "answer": "Yes" if a.checked else "No",
            "remark": (a.remark or "").strip(),
            "answered_at": now,
            "answered_by": who,
            "answered_by_name": who_name,
        }

    if not new_answers:
        raise HTTPException(
            status_code=400,
            detail="Nothing new to save — tick a box or add a remark on an unanswered question.",
        )

    set_fields = {f"answers.{qid}": val for qid, val in new_answers.items()}
    set_fields["updated_at"] = now
    set_fields["md_name"] = md_name

    await get_collection(submission_collection(form_type)).update_one(
        key,
        {
            "$set": set_fields,
            "$setOnInsert": {
                **key,
                "kind": KIND_YESNO_CHECKLIST,
                "created_at": now,
                "created_by": who,
                "created_by_name": who_name,
            },
        },
        upsert=True,
    )

    # H3 — MD summary mail (feedback has no per-employee scorecards). Gated → no-op while off.
    try:
        from app.services.tpms_notify_service import notify_form_submission
        await notify_form_submission(
            form_type=form_type, title=definition["title"],
            company_id=company_id, period=payload.period,
            respondent_id=md_id, respondent_name=md_name or "",
            ratings=None,
        )
    except Exception as _e:
        pass

    return {
        "message": f"{definition['title']}: {len(new_answers)} answer(s) saved",
        "count": len(new_answers),
        "skipped_already_saved": skipped_existing,
        "total_saved": len(already) + len(new_answers),
        "total_questions": len(qmap),
    }


@router.get("/{form_type}/submissions")
async def list_submissions(
    form_type: str,
    company_id: Optional[str] = None,
    period: Optional[str] = None,
    hod_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    _require_form_type(form_type)
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    query: dict = {"form_type": form_type}
    if _is_client(current_user):
        # A client may only list their own submissions in their own company.
        query["company_id"] = current_user.get("company_id") or ""
        if form_kind(form_type) == KIND_YESNO_CHECKLIST:
            query["md_id"] = _self_id(current_user)
        else:
            query["hod_id"] = _self_id(current_user)
        if period:
            query["period"] = period
    else:
        if company_id:
            query["company_id"] = company_id
        if period:
            query["period"] = period
        if hod_id:
            query["hod_id"] = hod_id

    cursor = get_collection(submission_collection(form_type)).find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=limit)
    return {"submissions": [_serialize(d) for d in docs]}


@router.get("/submissions/{submission_id}")
async def get_submission(submission_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        oid = ObjectId(submission_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid submission id")

    # Submissions live in one collection per form — search each until found.
    doc = None
    for coll_name in FORM_COLLECTIONS.values():
        doc = await get_collection(coll_name).find_one({"_id": oid})
        if doc:
            break
    if not doc:
        raise HTTPException(status_code=404, detail="Submission not found")

    # A client may only fetch their own submission.
    if _is_client(current_user):
        if doc.get("company_id") != (current_user.get("company_id") or ""):
            raise HTTPException(status_code=403, detail="Not authorized")
        respondent = doc.get("md_id") if doc.get("kind") == KIND_YESNO_CHECKLIST else doc.get("hod_id")
        if respondent != _self_id(current_user):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {"submission": _serialize(doc)}


# ─────────────────────────────────────────────────────────────
# Client dashboard — Success-Measure scorecard for one company + month.
#
# Data sources (all scoped to the client's own company):
#   • Scheduled activities → calendar events carrying an `activity` label (created by
#     the Schedule Calendar modal). These drive Planned / Completed / Actual Impl %.
#   • TPMS form submissions → the Accountability/Ownership/Culture/Implementation tables
#     drive Actual Score % for the three form-backed activities.
# Success Measure math is deliberately simple and transparent (documented inline) — it
# aggregates only the data that exists; everything else renders as "no data" (— / 0%).
# ─────────────────────────────────────────────────────────────
_CAL_COLLECTIONS = ["STAFF_CALENDER", "LEARNER_CALENDER", "calendar_events"]


def _month_parts(month: str):
    """Accept 'YYYY-MM' and return (year, month_num, [period tokens forms may use]).
    Delegates to the shared TPMS period helpers so there is exactly one definition of
    how a period is spelled across the module."""
    try:
        year, month_num = period_parts(month)
        return year, month_num, period_tokens(month)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="month must be 'YYYY-MM'")


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _activity_score_pct(activity: str, company_id: str, tokens: list):
    """Delegates to the Success-Measure engine so the whole module reports ONE number.

    This previously averaged each source form's percentage separately. The Apps Script
    pools sum/count across all of an activity's forms and divides once — which differs
    whenever the forms carry different numbers of ratings (partial submission makes that
    the norm). See tpms_score_service.activity_score_pct.
    """
    from app.services.tpms_score_service import activity_score_pct
    return await activity_score_pct(activity, company_id, tokens=tokens)


def _status_for(achievement, has_data):
    """Spec §7 band — ≥100 Met · 50–99 Partial · <50 Not Met. Delegates to the single
    definition in app.models.tpms so this page can't drift from the TPMS dashboards."""
    from app.models.tpms import achievement_status
    return achievement_status(achievement, has_data)


@router.get("/dashboard")
async def client_dashboard(
    month: str = Query(..., description="Month to report on, 'YYYY-MM'"),
    company_id: Optional[str] = Query(None, description="Staff only — target company"),
    current_user: dict = Depends(get_current_user),
):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are locked to their own company; staff may pass company_id.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    year, month_num, period_tokens = _month_parts(month)

    # Company name.
    company = None
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        company = None
    company_name = (company or {}).get("name") or company_id
    om_name = (company or {}).get("owner")

    # Scheduled activities for this company + month (events carrying an `activity`).
    # Scoped to TPMS activities by the `kind` discriminator, as every other TPMS aggregation
    # is (see _load_events). Without it any calendar event that merely carries an `activity`
    # field counts toward this company's Planned total, inflating it with non-TPMS work.
    scheduled = []
    for coll in _CAL_COLLECTIONS:
        docs = await get_collection(coll).find(
            {"company_id": company_id, "kind": TPMS_EVENT_KIND,
             "activity": {"$nin": [None, ""]}}
        ).to_list(3000)
        scheduled.extend(docs)
    month_events = []
    for e in scheduled:
        dt = _parse_dt(e.get("start"))
        if dt and dt.year == year and dt.month == month_num:
            month_events.append(e)

    by_activity: dict = {}
    for e in month_events:
        by_activity.setdefault(e.get("activity"), []).append(e)

    # The activity list this page reports on. Two sources, unioned:
    #   1. the LIVE catalogue — admins add activities at runtime (H4), so a hardcoded list
    #      goes stale the moment one is created;
    #   2. every activity name actually present in this month's events.
    # Without (2), an occurrence whose activity is not in the catalogue still counts toward
    # Planned but has no scorecard row — the "Planned says 12, the table shows 11" mismatch.
    # ACTIVITY_CATALOGUE remains the fallback if the collection is empty or unreachable.
    try:
        live = await get_collection("tpms_activities").find(
            {"active": {"$ne": False}}).to_list(200)
        activity_names = [a["name"] for a in live if a.get("name")]
    except Exception:
        activity_names = []
    if not activity_names:
        activity_names = list(ACTIVITY_CATALOGUE)
    for name in by_activity:
        if name and name not in activity_names:
            activity_names.append(name)

    # Build the scorecard over the full activity catalogue.
    scorecard = []
    met = partial = not_met = 0
    score_values = []
    for activity in activity_names:
        evs = by_activity.get(activity, [])
        planned = len(evs)
        completed = len([e for e in evs if e.get("status") == "completed"])
        actual_impl = round(completed / planned * 100) if planned else None
        actual_score = await _activity_score_pct(activity, company_id, period_tokens)

        vals = [v for v in (actual_impl, actual_score) if v is not None]
        has_data = bool(vals)
        achievement = round(sum(vals) / len(vals)) if vals else 0
        status = _status_for(achievement, has_data)

        if status == "Met":
            met += 1
        elif status == "Partial":
            partial += 1
        else:
            not_met += 1
        if actual_score is not None:
            score_values.append(actual_score)

        scorecard.append({
            "activity": activity,
            "impl_target_pct": 100,
            "actual_impl_pct": actual_impl,
            "score_target_pct": 100,
            "actual_score_pct": actual_score,
            "achievement_pct": achievement,
            "progress_pct": achievement,
            "status": status,
            "planned": planned,
            "completed": completed,
        })

    # Month-level summary cards (across all scheduled activities).
    total_planned = len(month_events)
    total_completed = len([e for e in month_events if e.get("status") == "completed"])
    completion_pct = round(total_completed / total_planned * 100) if total_planned else 0

    delays = []
    for e in month_events:
        if e.get("status") != "completed":
            continue
        start_dt = _parse_dt(e.get("start"))
        done_dt = _parse_dt(e.get("completed_at") or e.get("updated_at"))
        if start_dt and done_dt:
            delays.append(max(0, (done_dt.date() - start_dt.date()).days))
    avg_delay = round(sum(delays) / len(delays), 1) if delays else 0

    overall_status = "On Track" if completion_pct >= 80 else ("At Risk" if completion_pct >= 50 else "Critical")
    avg_score = round(sum(score_values) / len(score_values)) if score_values else 0

    # M4 — client × activity status grid for the Client Dashboard. One row (this company);
    # a cell per scheduled activity with done/total and a representative status.
    grid_cells: dict = {}
    for activity in activity_names:
        evs = by_activity.get(activity, [])
        if not evs:
            continue
        planned = len(evs)
        completed = len([e for e in evs if e.get("status") == "completed"])
        statuses = [str(e.get("tpms_status") or e.get("status") or "").lower() for e in evs]
        if any("laps" in s for s in statuses):
            st = "Lapsed"
        elif planned and completed == planned:
            st = "Completed"
        elif any("reschedul" in s for s in statuses):
            st = "Rescheduled"
        else:
            st = "Scheduled"
        grid_cells[activity] = {"done": completed, "total": planned, "status": st}
    activities_out = [{"full": a, "short": a} for a in activity_names]
    clients_grid_out = [{"company": company_name, "company_id": company_id,
                         "done": total_completed, "cells": grid_cells}]

    # Open follow-ups for this company. Deliberately NOT filtered to `month`: an action item
    # is outstanding work, and hiding one raised in an earlier month is exactly the wrong
    # behaviour for a "what still needs closing" panel. The rows carry their own target date.
    from app.services.tpms_dashboard_service import list_open_actions
    pending_actions = await list_open_actions([company_id])

    return {
        "activities": activities_out,
        "clients_grid": clients_grid_out,
        "pending_actions": pending_actions,
        "company": {
            "id": company_id,
            "name": company_name,
            "om_name": om_name,
            "completion_pct": completion_pct,
            "status": overall_status,
        },
        "month": month,
        "cards": {
            "planned": total_planned,
            "completed": total_completed,
            "completion_pct": completion_pct,
            "avg_delay_days": avg_delay,
        },
        "scorecard": scorecard,
        "stats": {
            "met": met,
            "partial": partial,
            "not_met": not_met,
            "total_activities": len(activity_names),
            "avg_score_pct": avg_score,
            "target_score_pct": 100,
        },
    }


# ─────────────────────────────────────────────────────────────
# Assigned-form access by token (TPMS ▸ mailed form links)
#
# These sit on the AUTHENTICATED router deliberately: the recipient signs in first, and the
# token then selects which form to render. Two independent checks must both pass —
#
#   1. the token must resolve to a live assignment (not unknown, expired or already submitted);
#   2. the signed-in user must BE that assignment's respondent.
#
# So a forwarded link is useless to anyone else: they can authenticate as themselves and still
# be refused, because the assignment names someone other than them. Conversely the token alone
# grants nothing without a session. Neither the form, the period, the company nor the
# respondent can be named by the client — all four come from the stored assignment.
# ─────────────────────────────────────────────────────────────
async def _assignment_for(token: str, current_user: dict, *, must_be_open: bool) -> dict:
    """Resolve `token` for `current_user`, or raise the reason it cannot be used.

    Expired / already-submitted links get their own status codes so the page can explain what
    happened rather than showing a generic failure — the two mean very different things to the
    person holding the link.
    """
    from app.services.tpms_form_link_service import (
        resolve_token, effective_status, STATUS_EXPIRED, STATUS_SUBMITTED,
    )
    doc = await resolve_token(token)
    if not doc:
        raise HTTPException(status_code=404, detail="This form link is not valid.")

    # Identity gate: the link is tied to one person, and being logged in is not enough.
    if str(doc.get("respondent_id")) != _self_id(current_user):
        raise HTTPException(
            status_code=403,
            detail="This form was assigned to a different user. Please sign in with the account the link was sent to.",
        )

    if must_be_open:
        state = effective_status(doc)
        if state == STATUS_SUBMITTED:
            raise HTTPException(status_code=409, detail="This form has already been submitted.")
        if state == STATUS_EXPIRED:
            raise HTTPException(status_code=410, detail="This form link has expired.")
    return doc


@router.get("/assigned/{token}")
async def assigned_form(token: str, current_user: dict = Depends(get_current_user)):
    """The one form this token was issued for, ready to render. Marks it Opened on first view.

    Returns exactly ONE form definition — the client cannot ask for another, which is what
    removes any need for a form picker.
    """
    from app.services.tpms_form_link_service import (
        effective_status, mark_opened, STATUS_EXPIRED, STATUS_SUBMITTED,
    )
    doc = await _assignment_for(token, current_user, must_be_open=False)

    state = effective_status(doc)
    head = {
        "state": state,
        "form_type": doc.get("form_type"),
        "form_title": doc.get("form_title"),
        "period": doc.get("period"),
        "company_name": doc.get("company_name"),
        "respondent_name": doc.get("respondent_name"),
        "submitted_at": doc.get("submitted_at"),
        "expires_at": doc.get("expires_at"),
    }
    # A closed link returns the reason and nothing else — no questions, no roster.
    if state in (STATUS_SUBMITTED, STATUS_EXPIRED):
        return head

    await mark_opened(doc)

    form_type = doc["form_type"]
    definition = await _effective_definition(form_type, _require_form_type(form_type))
    payload = {**head, "state": "open", "definition": definition}

    # A rating matrix needs the people being rated; the Yes/No checklist does not.
    if definition.get("kind") == KIND_RATING_MATRIX:
        hod_id = str(doc.get("respondent_id"))
        # Same rule as the authenticated members endpoint, from the same helper: this
        # respondent's reporting subordinates and nobody else.
        team = await _reporting_team(str(doc.get("company_id")), hod_id)
        pool = team

        # Same level gate as the authenticated roster endpoint, from the same registry value.
        # Resolved on every open, so a level corrected after the link was mailed takes effect
        # on the next visit — the assignment stores no member list to go stale.
        pool = eligible_by_level(pool, form_type)

        members = []
        for u in pool:
            uid = str(u["_id"])
            if uid == hod_id:
                continue  # an HOD never rates themselves
            members.append({
                "member_id": uid,
                "employee_id": u.get("employee_id") or u.get("emp_id") or u.get("emp_code"),
                "member_name": _user_display_name(u),
                "designation": u.get("designation"),
                "department": u.get("department"),
                "level": user_level(u),
            })
        members.sort(key=lambda m: (m.get("member_name") or "").lower())
        payload["members"] = members
        payload["scoped_to_team"] = True
        payload["min_level"] = form_min_level(form_type)
        payload["team_size"] = len(team)

    return payload


@router.post("/assigned/{token}/submitted")
async def mark_assigned_form_submitted(token: str, current_user: dict = Depends(get_current_user)):
    """Flag this token's assignment as completed.

    The form itself is filled and saved through the ordinary authenticated endpoints — the
    restored React forms post to /forms/{form_type}/ratings and /feedback exactly as they always
    have, so there is only ONE submission path and no duplicated validation or scoring. This
    endpoint records nothing about the answers; it only closes the assignment so TPMS ▸ Form Mail
    Logs can show Submitted and the link stops accepting further visits.
    """
    from app.services.tpms_form_link_service import mark_submitted

    doc = await _assignment_for(token, current_user, must_be_open=True)
    await mark_submitted(doc)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# Admin: form-link viewer (list + resend)
# ─────────────────────────────────────────────────────────────
def _last_sent(doc: dict):
    """When this link was last put in front of its recipient.

    `sent_at` is the honest answer and is what the column means; it is absent only for a link
    that was never mailed (notifications off, or no template), so the row still sorts sensibly
    on when it was last touched, then on when it was created.
    """
    return doc.get("sent_at") or doc.get("updated_at") or doc.get("created_at")


def _as_utc(value):
    """A timestamp the client cannot misread.

    Mongo returns these NAIVE (no tzinfo) even though every writer stores UTC, and a naive
    value serialises as "2026-08-25T07:16:38" — no offset. `new Date()` parses an ISO string
    without an offset as LOCAL time, so in IST a link mailed three minutes ago rendered as
    "5h ago", exactly the +05:30 skew. Stamping UTC explicitly makes the wire value
    unambiguous for any client and any zone.
    """
    if not isinstance(value, datetime):
        return value
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _sort_ts(value) -> float:
    """Sortable epoch for a timestamp that may be missing, naive, or timezone-aware.

    Mongo hands back naive UTC while anything constructed in-process is aware; comparing the
    two raises, so both are normalised to UTC before sorting.
    """
    if not isinstance(value, datetime):
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


@router.get("/assignments")
async def list_form_assignments(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="'YYYY-MM'"),
    current_user: dict = Depends(get_current_user),
):
    """Every unique form link (tpms_form_assignments), newest first. Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.tpms_form_link_service import (
        ASSIGNMENT_COLLECTION, effective_status, configured_base_url, link_on,
    )
    query: dict = {}
    if company_id:
        query["company_id"] = str(company_id)
    if period:
        query["period"] = str(period)
    docs = await get_collection(ASSIGNMENT_COLLECTION).find(query).to_list(2000)
    now = datetime.now(timezone.utc)
    # The link is REBUILT from the token against the current Application URL, exactly as the
    # mail does. The stored `link` is frozen at creation, so a row minted before the URL was
    # configured would otherwise hand out a localhost address through Copy and Open.
    base = await configured_base_url()
    out = [{
        "id": str(d["_id"]),
        "form_type": d.get("form_type"),
        "form_title": d.get("form_title"),
        "period": d.get("period"),
        "company_id": d.get("company_id"),
        "company_name": d.get("company_name"),
        "respondent_name": d.get("respondent_name"),
        "respondent_email": d.get("respondent_email"),
        "respondent_role": d.get("respondent_role"),
        "link": link_on(base, d["token"]) if d.get("token") else d.get("link"),
        "status": effective_status(d, now),
        "email_status": d.get("email_status"),
        "created_at": _as_utc(d.get("created_at")),
        # When this link was last issued or re-sent — the column that tells an admin their
        # latest schedule really did go out, even though no new row appeared.
        "last_sent": _as_utc(_last_sent(d)),
    } for d in docs]

    # Ordered by LAST SENT — the same value the column shows, which is why it is sorted here
    # rather than in the query: `sent_at` falls back through `updated_at` to `created_at`, and
    # sorting Mongo on any one of those disagrees with what the reader sees (a row touched at
    # 07:00 but last mailed at 06:58 sorted above one mailed at 06:58:37).
    #
    # It matters because a monthly form issues ONE link per person: re-scheduling an activity
    # reuses the existing row instead of minting a second URL, so ordering by creation left a
    # row that had just been re-sent wherever its birthday put it, and made a fresh schedule
    # look as though it had produced nothing at all.
    out.sort(key=lambda r: _sort_ts(r["last_sent"]), reverse=True)
    return {"assignments": out}


@router.post("/assignments/{assignment_id}/resend")
async def resend_form_assignment(assignment_id: str, current_user: dict = Depends(get_current_user)):
    """Email the recipient their existing form link again. Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.tpms_form_link_service import (
        ASSIGNMENT_COLLECTION, mark_email_result, EMAIL_SENT, EMAIL_FAILED,
    )
    try:
        doc = await get_collection(ASSIGNMENT_COLLECTION).find_one({"_id": ObjectId(assignment_id)})
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id")
    if not doc:
        raise HTTPException(status_code=404, detail="Link not found")
    email = doc.get("respondent_email")
    if not email:
        raise HTTPException(status_code=400, detail="This recipient has no email on file.")
    title = doc.get("form_title") or doc.get("form_type")
    # Rebuilt from the token like every other send — resending a row created before the
    # Application URL was set must not re-mail the stale localhost address.
    from app.services.tpms_form_link_service import configured_base_url, link_on
    period = doc.get("period")
    link = link_on(await configured_base_url(), doc["token"]) if doc.get("token") else doc.get("link")
    html = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#1e293b">'
            f'<p>Hello {doc.get("respondent_name") or ""},</p>'
            f'<p>Here is your <b>{title}</b> form link for <b>{period}</b>. It is personal to you '
            f'and can be submitted once.</p>'
            f'<p><a href="{link}" style="display:inline-block;background:#4f46e5;color:#fff;'
            f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700">Open the form</a></p>'
            f'<p style="font-size:12px;color:#6b7280">{link}</p></div>')
    from app.services.notification_service import send_email_notification
    try:
        # send_email_notification returns False on failure and never raises, so the result
        # must be captured — otherwise a failed resend reports 200 OK and stamps the link
        # as delivered, and the admin has no idea the recipient still has nothing.
        delivered = await send_email_notification(
            email, f"[{title}] Your form link – {period}", html,
            user_id=doc.get("respondent_id"), slug=f"tpms_form_{doc.get('form_type')}_resend")
        if not delivered:
            await mark_email_result(doc["_id"], EMAIL_FAILED, "Delivery failed")
            raise HTTPException(
                status_code=502,
                detail="The mail server did not accept this message. The link has not been "
                       "resent — please try again shortly.")
        await mark_email_result(doc["_id"], EMAIL_SENT, None)
        return {"ok": True, "email": email}
    except HTTPException:
        raise
    except Exception as e:
        await mark_email_result(doc["_id"], EMAIL_FAILED, str(e))
        raise HTTPException(status_code=500, detail=f"Send failed: {e}")


@router.delete("/assignments/{assignment_id}")
async def delete_form_assignment(assignment_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a generated form link assignment. Admin only."""
    if (current_user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.tpms_form_link_service import ASSIGNMENT_COLLECTION
    try:
        res = await get_collection(ASSIGNMENT_COLLECTION).delete_one({"_id": ObjectId(assignment_id)})
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id")
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Form link assignment not found")
    return {"ok": True, "message": "Form link deleted"}

