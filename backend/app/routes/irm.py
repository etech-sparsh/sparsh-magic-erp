"""
IRM — Individual Result Matrix ▸ API routes (mounted under /api).

  GET  /irm/parameters     the parameter registry (names, sources, seed weightages)
  GET  /irm/people         the roster, flagged with who has their own column
  GET  /irm/config         a weightage column + validity (company, or one person)
  PUT  /irm/config         save a weightage column (must total exactly 100%)
  DEL  /irm/config         drop a person's override so they inherit the company column
  GET  /irm/scores         every person's IRM for a period, fully broken down
  GET  /irm/scores/{id}    one person's IRM
  POST /irm/recalculate    snapshot the current numbers into irm_scores
  GET  /irm/kpis           the company's custom KPIs and who carries each
  POST /irm/kpis           define a new KPI and assign it to people
  PUT  /irm/kpis/{code}    rename / re-weight / re-assign one
  DEL  /irm/kpis/{code}    remove it, its scores, and its row from every column
  GET  /irm/kpis/sheet     one person's KPIs + what they have filed for a period
  PUT  /irm/kpis/{code}/score   file an achievement (the assignee's own, or an admin's)
  PUT  /irm/shift          the shift rule punctuality is measured against
  POST /irm/attendance/import   load punch times from .xlsx/.csv
  GET  /irm/attendance/template the import template, pre-filled with the roster
  GET  /irm/attendance/export   the stored punches, in the shape the importer reads

Scoping
-------
Internal staff (superadmin/admin) pass `company_id` and may read any company.
Client-side users are pinned to their own company: `clientadmin` sees the whole
roster, `clientuser` sees only their own row.

Who may set weightages: superadmin, admin, and a company's own clientadmin.

The clientadmin case is safe because of `_resolve_company`, which pins every client-side
request to the caller's own company whatever `company_id` they pass — so a clientadmin can
only ever reweight their own people, never another client's. `clientuser` is excluded: they
are the ones being scored.

Scope
-----
`person_id` is optional on the config routes. Without it they read and write the COMPANY
column, which is what they have always done. With it they read and write that one
person's override, which falls back to the company column wherever it says nothing. The
same 100% rule applies at both scopes.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from typing import Optional

from app.controllers.auth_controller import get_current_user
from app.models.irm import (
    IRM_PARAMETERS, IRMConfigUpdate, IRMCustomKpiCreate, IRMCustomKpiUpdate,
    IRMKpiScoreUpdate, IRMShiftUpdate, TOTAL_WEIGHTAGE,
)
from app.services import irm_attendance_service, irm_service

router = APIRouter(prefix="/irm", tags=["IRM"])

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}
# Who may edit the weightage cells. A clientadmin is included: reweighting their own
# company's people is theirs to decide, and _resolve_company makes it impossible for them
# to reach anyone else's. `clientuser` stays out — they are the ones being scored, so
# setting their own weightages would be marking their own homework.
CONFIG_ROLES = STAFF_ROLES | {"clientadmin"}
# Refreshing the stored snapshot recomputes from data that already exists and changes no
# configuration, so it stays available to a client's own admin too.
RECALC_ROLES = STAFF_ROLES | {"clientadmin"}
# Defining a KPI and deciding its weightage is the same authority as setting weightages, so
# it reuses CONFIG_ROLES exactly - a clientuser cannot invent a row of their own sheet.
KPI_ADMIN_ROLES = CONFIG_ROLES


def _is_staff(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES


def _resolve_company(user: dict, company_id: Optional[str]) -> str:
    """The company this request may act on. Client-side users are pinned to their own,
    whatever they passed; staff must name one explicitly."""
    if user.get("role") in CLIENT_ROLES:
        own = str(user.get("company_id") or "")
        if not own:
            raise HTTPException(status_code=400, detail="Your account is not linked to a company")
        return own
    if _is_staff(user):
        cid = str(company_id or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="company_id is required")
        return cid
    raise HTTPException(status_code=403, detail="Not authorized to access IRM")


async def _assert_on_roster(company_id: str, person_id: Optional[str]) -> None:
    """Refuse a per-person write for somebody who is not on this company's roster.

    `_resolve_company` already stops a caller reaching another company's config, but on its
    own it would still let any `person_id` be written under the caller's own company_id.
    That row could never score anybody — load_people would not return that person — so it
    would sit in the collection as invisible clutter, and a typo'd id would look like a
    saved override that silently does nothing. Checked here rather than in the service so
    the failure is a 404 with a reason, not a successful write nobody can see.
    """
    if not person_id:
        return
    people = await irm_service.load_people(company_id)
    if str(person_id) not in people:
        raise HTTPException(status_code=404, detail="No such person in this company")


def _visible_person(user: dict) -> Optional[str]:
    """A clientuser only ever sees their own row; everyone else sees the roster."""
    if user.get("role") == "clientuser":
        return str(user.get("_id"))
    return None


@router.get("/parameters")
async def list_parameters(current_user: dict = Depends(get_current_user)):
    """The evaluation parameters, so the UI never hardcodes names or weightages."""
    return {
        "parameters": [{
            "code": p["code"],
            "name": p["name"],
            "description": p.get("description", ""),
            "source": p["source"],
            "default_weightage": p["default_weightage"],
        } for p in IRM_PARAMETERS],
        "required_total": TOTAL_WEIGHTAGE,
    }


@router.get("/people")
async def list_people(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The roster the weightage screen picks from, and who already has an override.

    Deliberately NOT /irm/scores: populating a dropdown does not need every person's tasks,
    ratings and punches computed. `has_override` rides along so the picker can mark who is
    on their own column without a request per person.
    """
    cid = _resolve_company(current_user, company_id)
    people = await irm_service.load_people(cid)
    overrides = await irm_service.load_person_weightages(cid)
    restricted = _visible_person(current_user)

    rows = [{
        "person_id": pid,
        "name": p.get("name"),
        "designation": p.get("designation"),
        "department": p.get("department"),
        "has_override": pid in overrides,
    } for pid, p in people.items() if not restricted or pid == restricted]
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return {"company_id": cid, "people": rows,
            "customised": sum(1 for r in rows if r["has_override"])}


@router.get("/config")
async def read_config(
    company_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, description="Read one person's effective column"),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    # A clientuser may only ever look at their own sheet, matching the scores routes.
    restricted = _visible_person(current_user)
    if restricted and person_id and person_id != restricted:
        raise HTTPException(status_code=403, detail="You can only view your own IRM weightages")
    config = await irm_service.get_config(cid, person_id)
    config["can_edit"] = current_user.get("role") in CONFIG_ROLES
    return config


@router.put("/config")
async def update_config(
    payload: IRMConfigUpdate,
    company_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, description="Save one person's override"),
    current_user: dict = Depends(get_current_user),
):
    """Save the weightages. IRMConfigUpdate rejects anything that doesn't total 100%,
    so a partial column can never be persisted.

    Nothing needs recalculating afterwards: scores are derived from this config on every
    read, so the next /irm/scores call already uses the new numbers. The snapshot in
    `irm_scores` is refreshed here too, keeping stored history consistent with the change.
    """
    if current_user.get("role") not in CONFIG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to edit IRM weightages",
        )
    cid = _resolve_company(current_user, company_id)
    await _assert_on_roster(cid, person_id)

    try:
        config = await irm_service.save_weightages(cid, payload.as_map(), current_user, person_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Best-effort snapshot refresh — a storage hiccup must not fail the save itself.
    try:
        await irm_service.recalculate_and_store(cid)
    except Exception:
        pass

    config["can_edit"] = True
    config["message"] = (
        "Weightages saved for this person. Their IRM now uses this column; everyone else "
        "stays on the company default."
        if person_id else
        "Weightages saved. IRM scores now use the updated values."
    )
    return config


@router.delete("/config")
async def clear_person_config(
    person_id: str = Query(..., description="The person whose override is being removed"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Drop one person's override so they go back to the company column.

    Only ever touches `irm_person_configs` — the company row is not readable or writable
    through this route, so there is no way to delete a company's own weightages here.
    """
    if current_user.get("role") not in CONFIG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to edit IRM weightages",
        )
    cid = _resolve_company(current_user, company_id)
    await _assert_on_roster(cid, person_id)
    config = await irm_service.clear_person_weightages(cid, person_id)

    try:
        await irm_service.recalculate_and_store(cid)
    except Exception:
        pass

    config["can_edit"] = True
    config["message"] = ("Override removed. This person is back on the company column."
                         if config.get("removed") else
                         "This person had no override — nothing to remove.")
    return config


@router.get("/scores")
async def read_scores(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    try:
        return await irm_service.compute_company_irm(cid, period, _visible_person(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scores/{person_id}")
async def read_person_score(
    person_id: str,
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    restricted = _visible_person(current_user)
    if restricted and restricted != person_id:
        raise HTTPException(status_code=403, detail="You can only view your own IRM")

    try:
        result = await irm_service.compute_company_irm(cid, period, person_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result["rows"]:
        raise HTTPException(status_code=404, detail="No such person in this company")
    return {**result, "person": result["rows"][0]}


# ─────────────────────────────────────────────────────────────
# Attendance ▸ the punctuality parameter's only input
#
# Import is the ONLY writer. There is no endpoint that marks a day by hand, deliberately:
# punctuality is an evaluation input, so a punch has to trace back to the device export
# rather than to somebody's recollection of it.
# ─────────────────────────────────────────────────────────────
# -------------------------------------------------------------
# Custom KPIs
#
# The five built-in parameters measure things the ERP already records. A custom KPI measures
# something it does not, so its number is typed in by the person being scored - which is the
# one place this module lets the subject of a score write to it.
#
# The line is drawn at WEIGHTAGE vs ACHIEVEMENT, and it matters:
#   · weightage  - how much the KPI counts. Admin only, like every other weightage. A person
#                  who could set their own would be marking their own homework.
#   · achievement - what they actually did. Theirs to report, with the admin able to correct
#                  it and every entry stamped with who filed it and when.
# -------------------------------------------------------------
def _kpi_admin(user: dict) -> None:
    if user.get("role") not in KPI_ADMIN_ROLES:
        raise HTTPException(status_code=403,
                            detail="Only an administrator can define IRM KPIs.")


async def _assert_people_on_roster(company_id: str, person_ids) -> None:
    """Every person a KPI is given to must be on this company's roster.

    Same reasoning as _assert_on_roster for a single id: an unknown id would sit in the
    definition looking assigned while scoring nobody, because load_people never returns it.
    """
    if not person_ids:
        return
    people = await irm_service.load_people(company_id)
    missing = [pid for pid in person_ids if str(pid) not in people]
    if missing:
        raise HTTPException(status_code=404,
                            detail=f"{len(missing)} of those people are not in this company")


@router.get("/kpis")
async def list_kpis(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The company's custom KPIs. A clientuser sees only the ones they carry."""
    cid = _resolve_company(current_user, company_id)
    restricted = _visible_person(current_user)
    rows = []
    for k in await irm_service.list_custom_kpis(cid):
        people = [str(x) for x in (k.get("person_ids") or [])]
        if restricted and restricted not in people:
            continue
        rows.append({
            "code": k.get("code"),
            "name": k.get("name"),
            "description": k.get("description") or "",
            "weightage": round(float(k.get("weightage") or 0), 2),
            "person_ids": people,
            "person_count": len(people),
            "updated_at": k.get("updated_at") or k.get("created_at"),
            "updated_by": k.get("updated_by") or k.get("created_by"),
        })
    return {"company_id": cid, "kpis": rows, "can_manage": current_user.get("role") in KPI_ADMIN_ROLES}


@router.post("/kpis")
async def create_kpi(
    payload: IRMCustomKpiCreate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Define a KPI and give it to people.

    `balance` says where its weightage comes from inside each assignee's column - spread
    across the others, taken out of one named parameter, or left for the admin to set by hand
    (the default). The response reports how many columns were actually rewritten, so the
    screen can say what happened rather than leaving it to be discovered.
    """
    cid = _resolve_company(current_user, company_id)
    _kpi_admin(current_user)
    await _assert_people_on_roster(cid, payload.person_ids)
    try:
        doc = await irm_service.create_custom_kpi(cid, payload, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "code": doc["code"], "name": doc["name"],
            "balance": payload.balance,
            "columns_rebalanced": doc.get("columns_rebalanced", 0)}


@router.put("/kpis/{code}")
async def update_kpi(
    code: str,
    payload: IRMCustomKpiUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Rename, re-weight or re-assign a KPI. The code is immutable, so scores already filed
    against it survive a rename."""
    cid = _resolve_company(current_user, company_id)
    _kpi_admin(current_user)
    await _assert_people_on_roster(cid, payload.person_ids)
    try:
        doc = await irm_service.update_custom_kpi(cid, code, payload, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "code": doc["code"], "name": doc["name"],
            "balance": payload.balance,
            "columns_rebalanced": doc.get("columns_rebalanced", 0)}


@router.delete("/kpis/{code}")
async def delete_kpi(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a KPI, everything filed against it, and its row from every column."""
    cid = _resolve_company(current_user, company_id)
    _kpi_admin(current_user)
    try:
        return {"ok": True, **await irm_service.delete_custom_kpi(cid, code, current_user)}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/kpis/sheet")
async def read_kpi_sheet(
    company_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, description="Defaults to the caller"),
    period: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    current_user: dict = Depends(get_current_user),
):
    """One person's custom KPIs and what they have filed - the self-entry screen's payload.

    Defaults to the CALLER, so the common case (somebody filling in their own) needs no id.
    A clientuser may only ever read their own; anyone else may read a colleague's.
    """
    cid = _resolve_company(current_user, company_id)
    restricted = _visible_person(current_user)
    target = str(person_id or current_user.get("_id"))
    if restricted and target != restricted:
        raise HTTPException(status_code=403, detail="You can only see your own KPIs.")
    await _assert_on_roster(cid, target)
    return await irm_service.person_kpi_sheet(cid, target, period or irm_service.current_period())


@router.put("/kpis/{code}/score")
async def file_kpi_score(
    code: str,
    payload: IRMKpiScoreUpdate,
    company_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, description="Defaults to the caller"),
    period: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    current_user: dict = Depends(get_current_user),
):
    """File an achievement for one KPI in one month.

    The assignee files their own; an administrator may file or correct anyone's. Nobody else
    can write to somebody else's row - a colleague reporting your numbers for you would make
    the score untraceable, and every entry records who typed it.
    """
    cid = _resolve_company(current_user, company_id)
    target = str(person_id or current_user.get("_id"))
    is_self = target == str(current_user.get("_id"))
    if not is_self and current_user.get("role") not in KPI_ADMIN_ROLES:
        raise HTTPException(status_code=403,
                            detail="You can only fill in your own KPI score.")
    await _assert_on_roster(cid, target)
    try:
        doc = await irm_service.set_kpi_score(
            cid, target, code, period or irm_service.current_period(),
            payload.achievement, payload.note, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "code": code, "person_id": target,
            "period": doc["period"], "achievement": doc["achievement"]}


@router.put("/shift")
async def update_shift(
    payload: IRMShiftUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Set what counts as on time. Changing it re-scores history on the next read — the
    verdict is derived from the punches, never frozen into them."""
    if current_user.get("role") not in CONFIG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only a Super Admin or Admin can change the shift rule",
        )
    cid = _resolve_company(current_user, company_id)
    shift = await irm_attendance_service.save_shift(cid, payload.as_map(), current_user)
    return {"company_id": cid, "shift": shift,
            "message": "Shift saved. Punctuality is recalculated from it on the next read."}


@router.post("/attendance/import")
async def import_attendance(
    file: UploadFile = File(...),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Load punch times for this company from an .xlsx/.csv export.

    Rows that cannot be matched to somebody on the roster are REPORTED, never guessed at:
    attendance landing on the wrong person is worse than attendance that fails to land,
    because the first is invisible and the second is not.
    """
    if current_user.get("role") not in RECALC_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to import attendance")
    cid = _resolve_company(current_user, company_id)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")

    people = await irm_service.load_people(cid)
    try:
        return await irm_attendance_service.import_attendance(
            cid, content, file.filename or "", people, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/attendance/template")
async def attendance_template(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The import template: the expected headers, plus a row per person on the roster.

    Pre-filling the identity columns is the whole point. The importer matches on Employee
    ID, then Email, then Name, and the commonest way an import fails is a file carrying
    employee codes this system does not hold — every row lands in `unmatched` and nothing
    scores. Handing back the identifiers that WILL match turns that into a copy-paste.
    """
    from fastapi.responses import StreamingResponse

    if current_user.get("role") not in RECALC_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to import attendance")
    cid = _resolve_company(current_user, company_id)

    people = await irm_service.load_people(cid)
    data = irm_attendance_service.roster_template(people)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="irm-attendance-template.xlsx"'},
    )


@router.get("/attendance/export")
async def export_attendance(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="YYYY-MM; omit for every month"),
    current_user: dict = Depends(get_current_user),
):
    """The stored punches as .xlsx, in exactly the shape the importer reads back.

    Round-tripping is the point: the export is how an admin corrects a bad import, so a
    file that could not be re-imported would make the pair useless. With nothing stored
    yet it returns the empty template, which is what tells them the column names.
    """
    from fastapi.responses import StreamingResponse

    if current_user.get("role") not in RECALC_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to export attendance")
    cid = _resolve_company(current_user, company_id)

    people = await irm_service.load_people(cid)
    data = await irm_attendance_service.export_attendance(cid, period, people)
    if not data:
        data = irm_attendance_service.blank_template()

    stamp = period or "all"
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="irm-attendance-{stamp}.xlsx"'},
    )


@router.post("/recalculate")
async def recalculate(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Recompute and snapshot. Scores are always live on read, so this exists to refresh
    the stored history — e.g. after a month's tasks or ratings have settled."""
    if current_user.get("role") not in RECALC_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to recalculate IRM")
    cid = _resolve_company(current_user, company_id)
    try:
        return await irm_service.recalculate_and_store(cid, period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
