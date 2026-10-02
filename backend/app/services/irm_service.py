"""
IRM ▸ calculation engine.

Read-only over existing data: nothing here writes to tasks or to TPMS form submissions.
It reads the company's weightage config, derives each person's achievement % per
parameter, applies the configured weightage, and sums.

    Achievement %  = (achieved ÷ assigned) × 100          task-type parameters
                   = (Σ rating ÷ (n × 5)) × 100           form-type parameters
    Weighted Score = (Achievement % × Weightage) ÷ 100
    Final IRM      = Σ Weighted Score

No weightage literal appears below — every number comes from `irm_configs` (seeded
from app.models.irm.IRM_PARAMETERS the first time a company is read). Change a
weightage and the very next read recomputes with it; nothing is cached.

MISSING DATA
------------
A parameter with nothing to score (no tasks assigned that month, HOD hasn't rated the
person yet) reports `achievement: None` and contributes 0 — never a division by zero
and never a silent 0% that reads like a real failure. Because that dilutes the total,
each row also carries `applicable_weightage` (the weightage that DID have data) and
`final_irm_applicable` (the score rebased onto it), so a partially-scored month can be
read honestly. `final_irm` stays the plain out-of-100 sum the sheet specifies.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.forms import SCALE_MAX, submission_collection
from app.models.irm import (
    COLL_IRM_CONFIG, COLL_IRM_CUSTOM_KPIS, COLL_IRM_KPI_SCORES,
    COLL_IRM_PERSON_CONFIG, COLL_IRM_SCORES,
    ACHIEVEMENT_MAX, SOURCE_MANUAL, make_custom_code,
    BALANCE_FROM, BALANCE_MANUAL, BALANCE_SPREAD,
    IRM_PARAMETERS, PARAMETER_CODES,
    SCOPE_COMPANY, SCOPE_DEFAULT, SCOPE_PERSON,
    SOURCE_ATTENDANCE, SOURCE_FORM, SOURCE_TASK,
    TASK_WEIGHT_DEFAULT, TASK_WEIGHT_MAX, TASK_WEIGHT_MIN,
    TOTAL_WEIGHTAGE, WEIGHTAGE_EPSILON,
    default_weightages,
)
from app.models.tpms import period_tokens
from app.services.report_service import fetch_tasks, doer_ids
from app.routes.tasks import _resolve_workflow_status

logger = logging.getLogger(__name__)

# The user collections a company's people live in (same union as TPMS ▸ Forms members).
PERSON_COLLECTIONS = ("staff", "learners")


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def period_bounds(period: str) -> tuple:
    """'YYYY-MM' → (start_iso, end_iso) covering the whole month.

    Task documents store `start` as an ISO string, so the window is compared as text —
    which is why the bounds are produced in the same ISO shape.
    """
    try:
        year, month = int(period[:4]), int(period[5:7])
        first = datetime(year, month, 1)
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"Invalid period '{period}' — expected YYYY-MM")
    next_first = datetime(year + (month == 12), (month % 12) + 1, 1)
    last_moment = next_first - timedelta(microseconds=1)
    return first.isoformat(), last_moment.isoformat()


def _pct(part: float, whole: float) -> Optional[float]:
    """part/whole as a percentage, or None when there is nothing to divide by."""
    if not whole:
        return None
    return round(part / whole * 100, 2)


def _display_name(u: dict) -> str:
    return (
        u.get("full_name")
        or f"{u.get('first_name', '') or ''} {u.get('last_name', '') or ''}".strip()
        or u.get("email")
        or "Unknown"
    )


# ─────────────────────────────────────────────────────────────
# Weightage config — the editable cells from the sheet
# ─────────────────────────────────────────────────────────────
def _merge_weightages(base: Dict[str, float], stored: Optional[dict]) -> Dict[str, float]:
    """Overlay a stored weightage map onto `base`, ignoring unknown or unparseable codes.

    A parameter added to the registry later inherits its default rather than scoring 0 for
    every config saved before it existed.
    """
    weights = dict(base)
    for code, value in (stored or {}).items():
        if code in weights:
            try:
                weights[code] = round(float(value), 2)
            except (TypeError, ValueError):
                continue
    return weights


async def get_weightages(company_id: str, person_id: Optional[str] = None) -> Dict[str, float]:
    """The weightage map in force — for one person, or for the company as a whole.

    Resolution is most-specific-first: the person's own override, then the company
    default, then the registry seeds. Passing no `person_id` asks for the company row,
    which is exactly what the old single-argument call meant, so every existing caller
    keeps its behaviour.
    """
    weights, _scope = await resolve_weightages(company_id, person_id)
    return weights


# -------------------------------------------------------------
# Custom KPIs - company-defined parameters, carried by chosen people only
#
# A custom KPI is an ordinary row of the sheet in every respect except where its achievement
# comes from: the built-in five read data the ERP already holds, a custom one is typed in by
# the person being scored. Everything downstream - the weightage column, the 100% rule, the
# (achievement x weightage) / 100 formula, the Create Task accordion - treats it identically,
# which is why the only code that knows the difference is the `manual` branch in _build_row.
# -------------------------------------------------------------
def _kpi_as_parameter(kpi: dict) -> dict:
    """A stored KPI definition in the same shape as a built-in registry entry, so callers can
    iterate one list without caring which kind they are looking at."""
    return {
        "code": kpi.get("code"),
        "name": kpi.get("name") or kpi.get("code"),
        "description": kpi.get("description") or "",
        "source": SOURCE_MANUAL,
        "default_weightage": float(kpi.get("weightage") or 0.0),
        "custom": True,
        "person_ids": [str(x) for x in (kpi.get("person_ids") or [])],
    }


async def list_custom_kpis(company_id: str) -> List[dict]:
    """Every custom KPI a company has defined, oldest first."""
    rows = await get_collection(COLL_IRM_CUSTOM_KPIS).find(
        {"company_id": str(company_id)}).to_list(200)
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return rows


async def kpis_by_person(company_id: str) -> Dict[str, List[dict]]:
    """{person_id: [parameter, ...]} for a whole company in ONE read.

    Scoring a roster must not cost a query per person - this mirrors load_person_weightages,
    which exists for the same reason.
    """
    out: Dict[str, List[dict]] = {}
    for kpi in await list_custom_kpis(company_id):
        param = _kpi_as_parameter(kpi)
        for pid in param["person_ids"]:
            out.setdefault(pid, []).append(param)
    return out


async def custom_kpis_for_person(company_id: str, person_id: Optional[str]) -> List[dict]:
    """The custom parameters on one person's sheet. Empty for the company column: a custom
    KPI belongs to named people, so it is never part of the shared company default."""
    if not person_id:
        return []
    return [_kpi_as_parameter(k) for k in await list_custom_kpis(company_id)
            if str(person_id) in [str(x) for x in (k.get("person_ids") or [])]]


async def parameters_for(company_id: str, person_id: Optional[str] = None) -> List[dict]:
    """The rows of one sheet: the five built-ins, then this person's custom KPIs."""
    return list(IRM_PARAMETERS) + await custom_kpis_for_person(company_id, person_id)


def fit_to_100(weights: Dict[str, float], pinned: Dict[str, float]) -> Dict[str, float]:
    """`weights` adjusted to total exactly 100, holding `pinned` codes at their given values.

    Assigning a KPI worth 10% has to take that 10% from somewhere, and leaving the admin to
    find it by hand would push every assignee's column to 110% the moment the KPI was created
    - the exact "total is not 100%" state the sheet refuses to save. The remainder is shared
    out in proportion, so a column that was 25/30/25/20 keeps those relative shares.
    """
    pinned = {c: round(float(w), 2) for c, w in (pinned or {}).items()}
    room = round(TOTAL_WEIGHTAGE - sum(pinned.values()), 2)
    others = {c: float(w) for c, w in weights.items() if c not in pinned}

    if room <= 0:
        # The pinned rows already fill (or overfill) the column; nothing is left to share.
        return {**{c: 0.0 for c in others}, **pinned}
    if not others:
        return dict(pinned)

    other_total = round(sum(others.values()), 2)
    if other_total <= 0:
        # Nothing to scale in proportion to - split the remainder evenly rather than leaving
        # a column that cannot reach 100 at all.
        share = round(room / len(others), 2)
        scaled = {c: share for c in others}
    else:
        scaled = {c: round(w * room / other_total, 2) for c, w in others.items()}

    result = {**scaled, **pinned}
    # Rounding to 2dp can leave the column a hundredth out; absorb it into the largest
    # scalable row so the saved column is exactly 100 rather than 99.99.
    drift = round(TOTAL_WEIGHTAGE - sum(result.values()), 2)
    if drift and scaled:
        biggest = max(scaled, key=lambda c: result[c])
        result[biggest] = round(result[biggest] + drift, 2)
    return result


def take_from(weights: Dict[str, float], pinned: Dict[str, float],
              source: str) -> Dict[str, float]:
    """`weights` with the pinned rows funded out of ONE named parameter.

    Precise where fit_to_100 is proportional: "the 12% comes out of Task" leaves every other
    parameter at exactly the number the admin last chose, which is the point of asking. If the
    source has less to give than the KPI needs it is emptied rather than driven negative, and
    the shortfall is left visible in the total for somebody to resolve - silently topping it up
    from elsewhere would be the guessing this mode exists to avoid.
    """
    pinned = {c: round(float(w), 2) for c, w in (pinned or {}).items()}
    result = {c: round(float(w), 2) for c, w in weights.items()}
    needed = round(sum(pinned.values()), 2)
    available = round(float(result.get(source, 0.0)), 2)
    result[source] = round(max(0.0, available - needed), 2)
    result.update(pinned)
    return result


async def sync_person_columns(company_id: str, user: Optional[dict] = None,
                              balance: str = BALANCE_MANUAL,
                              balance_from: Optional[str] = None) -> int:
    """Re-fit every affected person's column to the KPIs they now carry. Returns how many changed.

    Run after any KPI create / update / delete.

    `balance` decides how somebody who GAINED a KPI pays for it:
      · spread - every other parameter scaled down in proportion
      · from   - the whole amount taken out of `balance_from`
      · manual - nothing written at all. Their column then reads over 100% and the board says
                 so, which is the admin's cue to set the numbers themselves. This is the
                 default: quietly re-cutting somebody's weightages is not a side effect worth
                 having.

    Somebody who LOST a KPI is always closed up regardless of mode - the row is gone, and a
    column left with a hole in it is not a decision anybody made, just debris.
    """
    assigned = await kpis_by_person(company_id)
    overrides = await load_person_weightages(company_id)
    company_weights, _ = await resolve_weightages(company_id)
    builtin_codes = set(PARAMETER_CODES)

    touched = 0
    # Everyone who carries a KPI now, plus everyone who already has a stored column - they may
    # have just lost one, and that column still needs the gap closing.
    for pid in set(assigned) | set(overrides):
        kpis = assigned.get(pid, [])
        stored = overrides.get(pid) or {}
        # The built-in half of this person's column, as it stands today.
        base = {c: w for c, w in _merge_weightages(company_weights, stored).items()
                if c in builtin_codes}
        before = {**{c: w for c, w in stored.items()}}

        if kpis:
            if balance == BALANCE_MANUAL:
                # Nothing to write: resolve_weightages already seeds the KPI from its own
                # definition, so it is a row on their sheet either way. Leaving the stored
                # column untouched is what makes the overage visible instead of absorbed.
                continue
            pinned = {k["code"]: k["default_weightage"] for k in kpis}
            if balance == BALANCE_FROM and balance_from:
                target = take_from({**base, **{c: 0.0 for c in pinned}}, pinned, balance_from)
            else:
                target = fit_to_100({**base, **{c: 0.0 for c in pinned}}, pinned)
        else:
            # No custom rows any more. Somebody who never had an override is left completely
            # alone — re-fitting would rewrite numbers nobody touched.
            if not stored:
                continue
            # Re-fit only a column that is actually off 100, which is exactly what losing a
            # KPI does to it: the row is gone and its share went with it. Testing the TOTAL
            # rather than "did it hold a custom code" matters because delete_custom_kpi
            # unsets the dead code first — so by the time this runs there is no custom code
            # left to spot, only the hole it left behind.
            gap = abs(round(sum(base.values()), 2) - TOTAL_WEIGHTAGE)
            stale = [c for c in stored if c not in builtin_codes]
            if gap <= WEIGHTAGE_EPSILON and not stale:
                continue
            target = fit_to_100(base, {})

        if target == before:
            continue
        await get_collection(COLL_IRM_PERSON_CONFIG).update_one(
            {"company_id": str(company_id), "person_id": str(pid)},
            {"$set": {"company_id": str(company_id), "person_id": str(pid),
                      "weightages": target,
                      "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
                      "updated_at": datetime.utcnow()},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True)
        touched += 1
    return touched


async def _record_funding(company_id: str, code: str, payload) -> None:
    """Remember how this KPI's weightage was found, so removing it can give back exactly that.

    NOT used to re-apply the balance on a later save - "take it from Task" answers how to make
    room once, and repeating it on an unrelated rename would raid Task again. It is recorded
    solely so deletion is the precise inverse of creation: proportional scaling reverses
    cleanly, but taking 12% out of Task does not, and without this the freed 12% would come
    back spread across every parameter and quietly move numbers the admin had chosen.
    """
    await get_collection(COLL_IRM_CUSTOM_KPIS).update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": {"funded_mode": payload.balance,
                  "funded_from": payload.balance_from if payload.balance == BALANCE_FROM else None,
                  "funded_amount": round(float(payload.weightage), 2)}})


async def create_custom_kpi(company_id: str, payload, user: Optional[dict] = None) -> dict:
    """Define a new KPI and give it to the chosen people."""
    code = make_custom_code(payload.name)
    col = get_collection(COLL_IRM_CUSTOM_KPIS)
    if await col.find_one({"company_id": str(company_id), "code": code}):
        raise ValueError(f"A KPI named '{payload.name}' already exists.")
    doc = {
        "company_id": str(company_id),
        "code": code,
        "name": payload.name,
        "description": payload.description or "",
        "weightage": round(float(payload.weightage), 2),
        "person_ids": [str(p) for p in payload.person_ids],
        "created_at": datetime.utcnow(),
        "created_by": (user or {}).get("full_name") or (user or {}).get("email"),
    }
    await col.insert_one(doc)
    doc["columns_rebalanced"] = await sync_person_columns(
        company_id, user, payload.balance, payload.balance_from)
    await _record_funding(company_id, code, payload)
    return doc


async def update_custom_kpi(company_id: str, code: str, payload, user: Optional[dict] = None) -> dict:
    """Edit a KPI in place. The CODE never changes, so the scores and weightages already filed
    against it stay attached through a rename."""
    col = get_collection(COLL_IRM_CUSTOM_KPIS)
    existing = await col.find_one({"company_id": str(company_id), "code": code})
    if not existing:
        raise LookupError(f"No KPI '{code}' for this company")
    await col.update_one(
        {"_id": existing["_id"]},
        {"$set": {"name": payload.name,
                  "description": payload.description or "",
                  "weightage": round(float(payload.weightage), 2),
                  "person_ids": [str(p) for p in payload.person_ids],
                  "updated_at": datetime.utcnow(),
                  "updated_by": (user or {}).get("full_name") or (user or {}).get("email")}})
    touched = await sync_person_columns(
        company_id, user, payload.balance, payload.balance_from)
    await _record_funding(company_id, code, payload)
    doc = await col.find_one({"_id": existing["_id"]})
    doc["columns_rebalanced"] = touched
    return doc


async def delete_custom_kpi(company_id: str, code: str, user: Optional[dict] = None) -> dict:
    """Remove a KPI, the scores filed against it, and its row from every column.

    The scores go with it deliberately: they are readings of a KPI that no longer exists, and
    leaving them would let a later KPI that happened to reuse the name inherit somebody else's
    numbers.
    """
    kpi = await get_collection(COLL_IRM_CUSTOM_KPIS).find_one(
        {"company_id": str(company_id), "code": code})
    if not kpi:
        raise LookupError(f"No KPI '{code}' for this company")
    mode = kpi.get("funded_mode") or BALANCE_SPREAD
    funder = kpi.get("funded_from")
    amount = round(float(kpi.get("funded_amount") or 0.0), 2)
    carriers = [str(x) for x in (kpi.get("person_ids") or [])]

    await get_collection(COLL_IRM_CUSTOM_KPIS).delete_one({"_id": kpi["_id"]})
    scores = await get_collection(COLL_IRM_KPI_SCORES).delete_many(
        {"company_id": str(company_id), "code": code})
    # Drop the now-dead row from every stored column first, or the repair below would keep
    # working around a code nothing can ever score again.
    await get_collection(COLL_IRM_PERSON_CONFIG).update_many(
        {"company_id": str(company_id)}, {"$unset": {f"weightages.{code}": ""}})

    # Give back precisely what creating it took. Anything else would be this function deciding
    # somebody's weightages on its own, which is the thing the balance modes exist to avoid.
    if mode == BALANCE_MANUAL:
        # Nothing was taken automatically, so nothing is owed. Whatever the admin set by hand
        # is left exactly as they set it.
        touched = 0
    elif mode == BALANCE_FROM and funder:
        touched = await _refund_to(company_id, carriers, funder, amount, user)
    else:
        # Proportional scaling is its own inverse, so scaling back up restores the original
        # split exactly.
        touched = await sync_person_columns(company_id, user, BALANCE_SPREAD)

    return {"removed": 1, "scores_removed": scores.deleted_count,
            "columns_rebalanced": touched, "refunded_to": funder if mode == BALANCE_FROM else None}


async def _refund_to(company_id: str, person_ids, code: str, amount: float,
                     user: Optional[dict] = None) -> int:
    """Hand `amount` back to one parameter on each named person's column.

    Capped so the column cannot pass 100: if the admin has been editing since, the freed
    weightage may no longer fit, and overshooting would leave a sheet the save endpoint
    refuses.
    """
    if not person_ids or amount <= 0:
        return 0
    col = get_collection(COLL_IRM_PERSON_CONFIG)
    touched = 0
    for pid in person_ids:
        doc = await col.find_one({"company_id": str(company_id), "person_id": str(pid)})
        if not doc:
            continue
        weights = {c: round(float(w), 2) for c, w in (doc.get("weightages") or {}).items()}
        if code not in weights:
            continue
        headroom = round(TOTAL_WEIGHTAGE - sum(weights.values()), 2)
        give = min(amount, headroom) if headroom > 0 else 0.0
        if give <= 0:
            continue
        weights[code] = round(weights[code] + give, 2)
        await col.update_one({"_id": doc["_id"]},
                             {"$set": {"weightages": weights,
                                       "updated_by": (user or {}).get("full_name")
                                       or (user or {}).get("email"),
                                       "updated_at": datetime.utcnow()}})
        touched += 1
    return touched


# -------------------------------------------------------------
# Self-reported scores
# -------------------------------------------------------------
async def load_kpi_scores(company_id: str, period: str) -> Dict[str, Dict[str, dict]]:
    """{person_id: {code: score_doc}} for one period, in a single read."""
    rows = await get_collection(COLL_IRM_KPI_SCORES).find(
        {"company_id": str(company_id), "period": str(period)}).to_list(20000)
    out: Dict[str, Dict[str, dict]] = {}
    for r in rows:
        out.setdefault(str(r.get("person_id")), {})[str(r.get("code"))] = r
    return out


async def set_kpi_score(company_id: str, person_id: str, code: str, period: str,
                        achievement: float, note: str = "", user: Optional[dict] = None) -> dict:
    """File one person's achievement for one KPI in one month.

    Refuses a KPI the person does not carry: a score against a row that is not on their sheet
    would never be read, and silently accepting it would look like it had been saved.
    """
    kpi = await get_collection(COLL_IRM_CUSTOM_KPIS).find_one(
        {"company_id": str(company_id), "code": code})
    if not kpi:
        raise LookupError(f"No KPI '{code}' for this company")
    if str(person_id) not in [str(x) for x in (kpi.get("person_ids") or [])]:
        raise PermissionError(f"'{kpi.get('name')}' is not on this person's sheet")

    period_bounds(period)   # reject a malformed month before storing anything against it
    doc = {
        "company_id": str(company_id), "person_id": str(person_id),
        "code": code, "period": str(period),
        "achievement": round(float(achievement), 2),
        "note": str(note or "").strip(),
        "updated_at": datetime.utcnow(),
        "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
        "updated_by_id": str((user or {}).get("_id") or ""),
    }
    await get_collection(COLL_IRM_KPI_SCORES).update_one(
        {"company_id": str(company_id), "person_id": str(person_id),
         "code": code, "period": str(period)},
        {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True)
    return doc


async def person_kpi_sheet(company_id: str, person_id: str, period: str) -> dict:
    """One person's custom KPIs with whatever they have filed for the period - the payload the
    self-service entry screen renders."""
    kpis = await custom_kpis_for_person(company_id, person_id)
    scores = (await load_kpi_scores(company_id, period)).get(str(person_id), {})
    weights, _scope = await resolve_weightages(company_id, person_id)
    return {
        "company_id": str(company_id),
        "person_id": str(person_id),
        "period": period,
        "kpis": [{
            "code": k["code"],
            "name": k["name"],
            "description": k["description"],
            "weightage": round(float(weights.get(k["code"], k["default_weightage"])), 2),
            "achievement": (scores.get(k["code"]) or {}).get("achievement"),
            "note": (scores.get(k["code"]) or {}).get("note") or "",
            "updated_at": (scores.get(k["code"]) or {}).get("updated_at"),
            "updated_by": (scores.get(k["code"]) or {}).get("updated_by"),
        } for k in kpis],
    }


async def resolve_weightages(company_id: str,
                             person_id: Optional[str] = None) -> tuple:
    """(weights, scope) — scope names which row actually supplied them.

    Reported rather than inferred so the screen can say "own mix" vs "company default"
    without re-querying, and so a snapshot records what a score was actually built from.
    """
    company_doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    # Seeded from THIS sheet's rows, not the global registry: _merge_weightages drops codes it
    # has never heard of, so a custom KPI has to be in the base map or a stored weightage for
    # it would be silently discarded on every read.
    seeds = {p["code"]: float(p["default_weightage"])
             for p in await parameters_for(company_id, person_id)}
    weights = _merge_weightages(seeds, (company_doc or {}).get("weightages"))
    scope = SCOPE_COMPANY if company_doc else SCOPE_DEFAULT

    if person_id:
        person_doc = await get_collection(COLL_IRM_PERSON_CONFIG).find_one({
            "company_id": str(company_id), "person_id": str(person_id)})
        if person_doc:
            weights = _merge_weightages(weights, person_doc.get("weightages"))
            scope = SCOPE_PERSON
    return weights, scope


async def load_person_weightages(company_id: str) -> Dict[str, dict]:
    """{person_id: stored_weightage_map} for every override in one company.

    Fetched in a single query so scoring a roster costs one read rather than one per
    person — compute_company_irm runs this once and resolves each row from it.
    """
    rows = await get_collection(COLL_IRM_PERSON_CONFIG).find(
        {"company_id": str(company_id)}).to_list(5000)
    return {str(r.get("person_id")): (r.get("weightages") or {}) for r in rows}


async def get_config(company_id: str, person_id: Optional[str] = None) -> dict:
    """Weightages plus the parameter metadata the UI renders the sheet from.

    With `person_id` this is that person's effective sheet — their override if they have
    one, otherwise the company column they inherit. `is_customised` keeps meaning "a row
    exists at the scope being read", which is what the screen's subtitle is driven from.
    """
    if person_id:
        doc = await get_collection(COLL_IRM_PERSON_CONFIG).find_one({
            "company_id": str(company_id), "person_id": str(person_id)})
    else:
        doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    weights, scope = await resolve_weightages(company_id, person_id)
    parameters = [{
        "code": p["code"],
        "name": p["name"],
        "description": p.get("description", ""),
        "source": p["source"],
        "default_weightage": p["default_weightage"],
        "weightage": weights.get(p["code"], p["default_weightage"]),
        # Lets the sheet mark which rows are this company's own additions, and which of them
        # are waiting on a number only the assignee can supply.
        "custom": bool(p.get("custom")),
    } for p in await parameters_for(company_id, person_id)]
    total = round(sum(weights.values()), 2)
    # The shift rule travels with the config because the punctuality parameter is
    # meaningless without it — one call gives Setup both halves of the same screen.
    from app.services.irm_attendance_service import get_shift
    return {
        "company_id": str(company_id),
        "person_id": str(person_id) if person_id else None,
        "scope": scope,
        "shift": await get_shift(company_id),
        "parameters": parameters,
        "weightages": weights,
        "total_weightage": total,
        "required_total": TOTAL_WEIGHTAGE,
        "is_valid": abs(total - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "is_customised": bool(doc),
        # True only when a person is being read and is riding the company column, so the
        # screen can offer "customise for this person" rather than implying they have one.
        "inherited": bool(person_id) and scope != SCOPE_PERSON,
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
    }


async def save_weightages(company_id: str, weightages: Dict[str, float], user: dict,
                          person_id: Optional[str] = None) -> dict:
    """Persist a weightage column — the company default, or one person's override.

    The 100% rule is enforced by IRMConfigUpdate before this is reached; it is re-checked
    here so a direct service call can't bypass it. It applies identically at both scopes:
    a person's sheet is still a sheet, and a column that does not total 100 cannot be read
    as a percentage of anything.
    """
    total = round(sum(weightages.values()), 2)
    if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
        raise ValueError(
            f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
        )
    # The model accepted any well-formed custom code; only here is the person known, so only
    # here can "is this KPI actually on their sheet?" be answered. Saving one that is not
    # would put a row on the column that nothing can ever score.
    allowed = {p["code"] for p in await parameters_for(company_id, person_id)}
    unknown = [c for c in weightages if c not in allowed]
    if unknown:
        raise ValueError(
            "These KPIs are not on this sheet: " + ", ".join(sorted(unknown))
            + ". Assign the KPI to this person first."
        )
    cleaned = {c: round(float(w), 2) for c, w in weightages.items()}
    stamp = {
        "weightages": cleaned,
        "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
        "updated_at": datetime.utcnow(),
    }

    if person_id:
        await get_collection(COLL_IRM_PERSON_CONFIG).update_one(
            {"company_id": str(company_id), "person_id": str(person_id)},
            {"$set": {"company_id": str(company_id), "person_id": str(person_id), **stamp},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
    else:
        await get_collection(COLL_IRM_CONFIG).update_one(
            {"company_id": str(company_id)},
            {"$set": {"company_id": str(company_id), **stamp},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
    return await get_config(company_id, person_id)


async def clear_person_weightages(company_id: str, person_id: str) -> dict:
    """Drop one person's override so they fall back to the company column.

    Without this an override could be changed but never undone, which would make the
    company default unreachable for anyone who had ever been customised.
    """
    res = await get_collection(COLL_IRM_PERSON_CONFIG).delete_one({
        "company_id": str(company_id), "person_id": str(person_id)})
    config = await get_config(company_id, person_id)
    config["removed"] = res.deleted_count
    return config


# ─────────────────────────────────────────────────────────────
# Raw achievement inputs
# ─────────────────────────────────────────────────────────────
async def load_people(company_id: str) -> Dict[str, dict]:
    """{person_id: {...}} for the company's active roster.

    Keyed by Mongo _id. `employee_id` is captured too because TPMS rating cells may be
    written against either identifier (see routes/forms.py) — _form_totals maps those
    back onto the person.
    """
    people: Dict[str, dict] = {}
    query = {"company_id": str(company_id), "is_active": {"$ne": False}}
    for coll in PERSON_COLLECTIONS:
        for u in await get_collection(coll).find(query).to_list(2000):
            pid = str(u["_id"])
            people[pid] = {
                "person_id": pid,
                "name": _display_name(u),
                "email": u.get("email"),
                "employee_id": u.get("employee_id") or u.get("emp_id") or u.get("emp_code"),
                "designation": u.get("designation"),
                "department": u.get("department"),
                "role": u.get("role"),
            }
    return people


def task_credit(doc: dict) -> float:
    """How much of ONE task counts as achieved, between 0 and 1.

    A task cannot be completed until every check point on it is ticked (routes/tasks.py
    enforces that on the complete call). So a task carrying a checklist already reports
    its own progress, and counting the task all-or-nothing threw that away: nine of ten
    check points done scored exactly the same as a task nobody had opened — zero — which
    made a genuinely productive month read as a failed one and gave the person no reason
    to tick anything until the last item landed.

    Completed → 1.0. Otherwise the share of check points done. A task with no checklist
    has nothing partial to measure and stays all-or-nothing, exactly as before.
    """
    if _resolve_workflow_status(doc) == "completed":
        return 1.0
    items = [c for c in (doc.get("checklist") or []) if isinstance(c, dict)]
    if not items:
        return 0.0
    done = sum(1 for c in items if c.get("completed"))
    return done / len(items)


def task_weight(doc: dict) -> float:
    """How many units of "assigned" ONE task is worth. 1.0 unless it says otherwise.

    Every task used to count the same, so a fortnight's project scored exactly as much as
    a five-minute errand and a month of small tasks could outscore a month of hard ones.
    `irm_weight` lets the person setting the task say what it is worth; absent or
    unreadable it stays 1.0, which is precisely the old behaviour — so nothing already in
    the database scores differently than it did.
    """
    try:
        w = float(doc.get("irm_weight"))
    except (TypeError, ValueError):
        return TASK_WEIGHT_DEFAULT
    if w != w:                              # NaN
        return TASK_WEIGHT_DEFAULT
    return max(TASK_WEIGHT_MIN, min(TASK_WEIGHT_MAX, round(w, 2)))


def _irm_bucket(doc: dict) -> Optional[str]:
    """Which IRM bucket a task scores in — "task", "delegation", or None for neither.

    NOT the same test as report_service.is_delegated (that one only asks who assigned the
    task, and also backs the unrelated Task Overview "delegators" stat, so it stays untouched).

    Only two kinds of work are scored:

      • RECURRING (a "checklist": generated by recurring_task_service, re-earning its credit
        every period through its own check points) → Task, however it was assigned. A daily
        routine handed to someone is still a routine, not a delegation.
      • ONE-TIME work someone else hand-assigned → Delegation.

    Everything else scores NOWHERE — which in practice means a one-time task a person set for
    themselves. Nobody asked them for it, so it is neither a routine they are keeping nor a
    request they are answering, and counting it would let anyone move their own score simply
    by writing themselves to-dos.
    """
    if str(doc.get("repeat") or "").strip() not in ("", "Does not repeat"):
        return "task"
    if doc.get("assigned_to") == "other" and doc.get("target_staff_id"):
        return "delegation"
    return None


async def _task_totals(company_id: str, period: str, people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {"task": {...}, "delegation": {...}}} — per bucket:

        assigned   how many tasks
        achieved   credit earned, fractional (see `task_credit`)
        completed  how many finished outright
        partial    how many contributed part of a task through their checklist

    A task counts for whoever DOES it (`doer_ids`), split by what kind of work it is: a
    recurring task/checklist → Task, however it was assigned; a one-time task someone else
    hand-assigned → Delegation Score. A one-time task a person set for themselves counts in
    neither. See `_irm_bucket`.
    """
    start_iso, end_iso = period_bounds(period)
    tasks = await fetch_tasks(start_iso, end_iso)
    cid = str(company_id)
    # Every occurrence dated inside the period counts, including days still ahead: a month's
    # checklist is a month's plan, so the denominator is the whole plan from the moment it is
    # set, not just the part that has come round. Mid-month that reads low by design — it is
    # progress against the month, and it closes as the days are ticked off.

    def _bucket():
        # `assigned` is a sum of WEIGHTS, not a headcount, so `count` is carried alongside
        # it — the screen still wants to say "5 tasks", and 5 tasks can weigh 7.5.
        return {"assigned": 0.0, "achieved": 0.0, "completed": 0, "partial": 0, "count": 0}

    totals = {pid: {"task": _bucket(), "delegation": _bucket()} for pid in people}

    for doc in tasks:
        # Scoping comes from the DOER: `totals` is keyed by this company's roster, so a task
        # can only ever score for someone who is on it. The document's own company_id is used
        # just to rule out a task explicitly tagged to a DIFFERENT company.
        #
        # It used to be required to match, which silently dropped every task that carries no
        # company_id at all — and the Task module does not stamp one, so ordinary delegated and
        # recurring work never reached the score. That is why a person could have a month of
        # real tasks behind them and still read as "No data" here.
        doc_cid = str(doc.get("company_id") or "")
        if doc_cid and doc_cid != cid:
            continue
        bucket = _irm_bucket(doc)
        if bucket is None:
            continue  # scores in neither bucket — see _irm_bucket

        credit = task_credit(doc)
        # DELEGATION IS COUNTED PER TASK, NOT BY WEIGHT.
        #
        # Weighting is kept for Task, where it does what it was built for: two recurring
        # routines can be genuinely unequal. Delegation reads differently — it answers "how
        # much of what you were handed did you do", and there a single task weighted 10
        # swallowed the column: four delegated tasks with two done showed 35%, not 50%, and
        # no amount of staring at the task list explained the gap. A delegated task is one
        # task. `irm_weight` is left untouched on the document; it simply no longer moves
        # this bucket.
        weight = 1.0 if bucket == "delegation" else task_weight(doc)
        for pid in doer_ids(doc):
            row = totals.get(pid)
            if row is None:
                continue  # doer is not on this company's active roster
            cell = row[bucket]
            # Both sides scale together, so the ratio is unchanged for a weight of 1 and a
            # heavier task simply counts for more of the month on both halves of it.
            cell["assigned"] += weight
            cell["achieved"] += credit * weight
            cell["count"] += 1
            if credit >= 1.0:
                cell["completed"] += 1
            elif credit > 0:
                cell["partial"] += 1
    return totals


async def _form_totals(company_id: str, period: str, form_type: str,
                       people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {"points": Σ rating, "max_points": n × SCALE_MAX, "ratings": n}}

    Rating matrices store one cell per (criterion, member) — ratings.{code}.{member_id}
    — so a member rated on 3 of 5 criteria is scored out of 3, not penalised for the
    two the HOD skipped.
    """
    coll = submission_collection(form_type)
    totals = {pid: {"points": 0.0, "max_points": 0.0, "ratings": 0} for pid in people}
    if not coll:
        return totals

    # employee_id → person_id, because a cell may be keyed by either.
    alias = {str(p["employee_id"]): pid for pid, p in people.items() if p.get("employee_id")}

    docs = await get_collection(coll).find({
        "company_id": str(company_id),
        "period": {"$in": period_tokens(period)},
    }).to_list(2000)

    for d in docs:
        for _code, members in (d.get("ratings") or {}).items():
            for member_id, cell in (members or {}).items():
                pid = member_id if member_id in totals else alias.get(str(member_id))
                if pid is None:
                    continue
                rating = (cell or {}).get("rating")
                if not isinstance(rating, (int, float)):
                    continue
                row = totals[pid]
                row["points"] += float(rating)
                row["max_points"] += float(SCALE_MAX)
                row["ratings"] += 1
    return totals


# ─────────────────────────────────────────────────────────────
# The calculation
# ─────────────────────────────────────────────────────────────
def _build_row(person: dict, weights: Dict[str, float],
               task_totals: dict, form_totals: Dict[str, dict],
               scope: str = SCOPE_COMPANY,
               attendance: Optional[dict] = None,
               parameters: Optional[List[dict]] = None,
               kpi_scores: Optional[Dict[str, dict]] = None) -> dict:
    """One person's IRM — every intermediate value kept so the maths stays auditable.

    `weights` is THIS person's map, which may be their own override or the company
    column. It is echoed back on the row (with the scope that produced it) so a score can
    be read without guessing which sheet it was built from.
    """
    breakdown: List[dict] = []
    final_irm = 0.0
    applicable_weightage = 0.0

    for p in (parameters if parameters is not None else IRM_PARAMETERS):
        code = p["code"]
        weightage = float(weights.get(code, 0.0))

        if p["source"] == SOURCE_MANUAL:
            # Self-reported. Nothing filed yet reads as "no data" rather than 0% - the same
            # path an un-submitted rating form takes - so an unanswered KPI never drags the
            # score down, it simply drops out of the applicable weightage until it is filled.
            filed = (kpi_scores or {}).get(code) or {}
            achievement = filed.get("achievement")
            achievement = float(achievement) if achievement is not None else None
            detail = {
                "achieved": achievement,
                "assigned": ACHIEVEMENT_MAX if achievement is not None else None,
                "note": filed.get("note") or "",
                "filed_by": filed.get("updated_by") or "",
                "filed_at": filed.get("updated_at"),
                "awaiting_entry": achievement is None,
            }
        elif p["source"] == SOURCE_ATTENDANCE:
            a = attendance or {}
            present = a.get("present", 0)
            punctual = a.get("punctual", 0)
            achievement = _pct(punctual, present)
            detail = {
                "achieved": punctual,
                "assigned": present,
                "late_in": a.get("late_in", 0),
                "early_out": a.get("early_out", 0),
                "missing_out": a.get("missing_out", 0),
            }
        elif p["source"] == SOURCE_TASK:
            counts = (task_totals or {}).get(code) or {}
            assigned = counts.get("assigned", 0)
            achieved = counts.get("achieved", 0.0)
            achievement = _pct(achieved, assigned)
            # `achieved` is credit, not a headcount — a part-finished checklist contributes
            # a fraction — so the whole/part split is sent alongside it and the screen can
            # say "3 done + 2 in progress" instead of showing a puzzling 3.6.
            detail = {
                "achieved": round(achieved, 2),
                "assigned": round(assigned, 2),
                "count": counts.get("count", 0),
                "completed": counts.get("completed", 0),
                "partial": counts.get("partial", 0),
                # True when the tasks in this bucket did not all weigh 1, so the screen can
                # explain why "3 of 5 tasks" is not the same as the percentage shown.
                "weighted": round(assigned, 2) != counts.get("count", 0),
            }
        else:
            f = (form_totals.get(code) or {})
            achievement = _pct(f.get("points", 0.0), f.get("max_points", 0.0))
            detail = {
                "achieved": round(f.get("points", 0.0), 2),
                "assigned": round(f.get("max_points", 0.0), 2),
                "ratings": f.get("ratings", 0),
                "scale_max": SCALE_MAX,
            }

        has_data = achievement is not None
        # (Achievement % × Weightage) ÷ 100 — the sheet's formula, verbatim.
        weighted = round(achievement * weightage / 100, 2) if has_data else 0.0
        final_irm += weighted
        if has_data:
            applicable_weightage += weightage

        breakdown.append({
            "code": code,
            "name": p["name"],
            "source": p["source"],
            "custom": bool(p.get("custom")),
            "weightage": round(weightage, 2),
            "achievement": achievement,          # None = nothing to score
            "weighted_score": weighted,
            "max_score": round(weightage, 2),    # the most this parameter can contribute
            "has_data": has_data,
            **detail,
        })

    final_irm = round(final_irm, 2)
    applicable_weightage = round(applicable_weightage, 2)
    return {
        **person,
        "parameters": breakdown,
        "final_irm": final_irm,
        "weightages": {c: round(float(w), 2) for c, w in weights.items()},
        "weightage_scope": scope,
        "total_weightage": round(sum(weights.values()), 2),
        # Rebased onto only the parameters that had data — None when nothing did.
        "applicable_weightage": applicable_weightage,
        "final_irm_applicable": (round(final_irm / applicable_weightage * 100, 2)
                                 if applicable_weightage else None),
        "has_data": applicable_weightage > 0,
    }


async def compute_company_irm(company_id: str, period: Optional[str] = None,
                              person_id: Optional[str] = None) -> dict:
    """Every person's IRM for a company and period (or just one person).

    Always computed live from the current config, so an admin's weightage edit is
    reflected on the next call with no recalculation step in between.
    """
    period = period or current_period()
    period_bounds(period)  # validate early — a bad period should 400, not score 0

    # The company column, plus every per-person override in one read. Resolving each row
    # from these two rather than querying per person keeps a 500-person roster at two
    # config reads, exactly as it was when the column was company-wide.
    company_weights, company_scope = await resolve_weightages(company_id)
    overrides = await load_person_weightages(company_id)
    # Both in one read each, for the same reason the two config reads are batched: a roster
    # must not cost a query per person.
    custom_by_person = await kpis_by_person(company_id)
    kpi_scores = await load_kpi_scores(company_id, period)

    people = await load_people(company_id)
    if person_id:
        people = {pid: p for pid, p in people.items() if pid == str(person_id)}

    def _weights_for(pid: str) -> tuple:
        stored = overrides.get(str(pid))
        customs = custom_by_person.get(str(pid), [])
        if not stored and not customs:
            return company_weights, company_scope
        # Their own row seeded with their own KPIs, so a custom code is never dropped as
        # unknown on the way through _merge_weightages.
        seeds = {**company_weights,
                 **{k["code"]: k["default_weightage"] for k in customs}}
        return _merge_weightages(seeds, stored), SCOPE_PERSON

    tasks = await _task_totals(company_id, period, people)
    forms = {p["code"]: await _form_totals(company_id, period, p["form_type"], people)
             for p in IRM_PARAMETERS if p["source"] == SOURCE_FORM}

    # Imported punches, scored against the company's shift rule. A month with nothing
    # imported yields no `present` days, so punctuality reports achievement None and
    # contributes nothing — the same "missing data" path every other parameter uses.
    attendance: Dict[str, dict] = {}
    if any(p["source"] == SOURCE_ATTENDANCE for p in IRM_PARAMETERS):
        from app.services.irm_attendance_service import attendance_totals
        attendance = await attendance_totals(company_id, period, people)

    rows = []
    for pid, person in people.items():
        person_weights, scope = _weights_for(pid)
        person_params = list(IRM_PARAMETERS) + custom_by_person.get(str(pid), [])
        rows.append(_build_row(
            person,
            person_weights,
            tasks.get(pid, {}),
            {code: totals.get(pid, {}) for code, totals in forms.items()},
            scope,
            attendance.get(pid, {}),
            person_params,
            kpi_scores.get(str(pid), {}),
        ))
    # Highest IRM first; people with no data at all sink to the bottom.
    rows.sort(key=lambda r: (r["has_data"], r["final_irm"]), reverse=True)

    scored = [r for r in rows if r["has_data"]]
    total_weightage = round(sum(company_weights.values()), 2)
    # The top-level column stays the COMPANY default — it is the sheet header, and each
    # row now carries its own `weightages` for anyone on a different mix.
    return {
        "company_id": str(company_id),
        "period": period,
        "weightages": company_weights,
        "total_weightage": total_weightage,
        "is_valid_weightage": abs(total_weightage - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "customised_people": sum(1 for r in rows if r.get("weightage_scope") == SCOPE_PERSON),
        "parameters": [{"code": p["code"], "name": p["name"], "source": p["source"],
                        "weightage": company_weights.get(p["code"], 0.0)}
                       for p in IRM_PARAMETERS],
        "rows": rows,
        "summary": {
            "people": len(rows),
            "scored": len(scored),
            "average_irm": round(sum(r["final_irm"] for r in scored) / len(scored), 2) if scored else None,
            "highest": scored[0]["final_irm"] if scored else None,
            "lowest": scored[-1]["final_irm"] if scored else None,
        },
    }


async def recalculate_and_store(company_id: str, period: Optional[str] = None) -> dict:
    """Snapshot the computed IRM into `irm_scores` for history/reporting.

    The API always serves freshly computed numbers, so this is a record of what the
    score was under the weightages in force — not a cache the reads depend on.
    """
    result = await compute_company_irm(company_id, period)
    now = datetime.utcnow()
    col = get_collection(COLL_IRM_SCORES)

    for row in result["rows"]:
        await col.update_one(
            {"company_id": result["company_id"], "period": result["period"],
             "person_id": row["person_id"]},
            {"$set": {
                "company_id": result["company_id"],
                "period": result["period"],
                "person_id": row["person_id"],
                "person_name": row.get("name"),
                # The row's OWN map, not the company column — a snapshot has to record
                # what the score was actually built from or it cannot be audited.
                "weightages": row.get("weightages") or result["weightages"],
                "weightage_scope": row.get("weightage_scope"),
                "parameters": row["parameters"],
                "final_irm": row["final_irm"],
                "final_irm_applicable": row["final_irm_applicable"],
                "applicable_weightage": row["applicable_weightage"],
                "computed_at": now,
            }},
            upsert=True,
        )

    logger.info("IRM recalculated: %s rows [company=%s period=%s]",
                len(result["rows"]), result["company_id"], result["period"])
    return {"company_id": result["company_id"], "period": result["period"],
            "recalculated": len(result["rows"]), "computed_at": now}
