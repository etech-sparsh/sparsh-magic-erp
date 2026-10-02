"""
TPMS ▸ Success-Measure engine.

Port of the Apps Script scoring pipeline:
  • seedSuccessMeasures   (code.js:2209) → seed_success_measures()
  • syncSuccessMeasures   (code.js:2054) → sync_success_measures()
  • reviewScoreMap_       (code.js:2019) → activity_score_pct() / review_score_map()
  • manualScoresMap_      (code.js:1964) → manual rows in tpms_success_measures

SEED vs SYNC — kept separate, exactly as the source
---------------------------------------------------
`sync` only ever UPDATES; it skips any aggregate with no pre-seeded row (code.js:2154).
`seed` is what creates rows. The Apps Script installed a trigger for each
(setupSuccessSeedTrigger :2264, setupSuccessSyncTrigger :2272), so both ran daily. We do
the same — run_daily() seeds then syncs — which preserves the semantics while ensuring a
month never silently scores nothing.

THE NUMBERS
-----------
    Actual_Implementation_%  = 100 if any occurrence completed else 0   (BINARY, per source)
    autoScore                = completed ÷ total × 100
    Achievement_%            = Actual_Score ÷ Score_Target × 100

`Actual_Score_%` resolves by the activity's score_mode:
    form   → pooled average across the activity's form submissions
    manual → the manually-entered row(s); HOD-scoped activities average across HODs
    auto   → autoScore

`Calendar Discipline` is a pseudo-activity with no schedules of its own: its score is the
completion rate across every OTHER activity that month, excluding itself and
`Action Closure Review` (code.js:2093).
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.forms import (
    ACTIVITY_FORM_MAP, KIND_YESNO_CHECKLIST, SCALE_MAX,
    form_kind, submission_collection,
)
from app.models.tpms import (
    CAL_DISCIPLINE_ACTIVITY, CAL_DISCIPLINE_EXCLUDE,
    COLL_ACTIVITIES, COLL_ACTIVITY_TRACKER, COLL_SUCCESS_MEASURES,
    SCOPE_COMPANY, SCOPE_HOD, SCORE_MODE_FORM, SCORE_MODE_MANUAL,
    STATUS_CANCELLED, STATUS_COMPLETED,
    period_tokens,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Review-backed scores — port of reviewScoreMap_ (code.js:2019)
#
# ⚠ POOLED, not an average-of-averages. The Apps Script accumulates sum/count across ALL
# of an activity's source forms into ONE bucket and divides once:
#       (sumA + sumO) ÷ ((cntA + cntO) × 5) × 100
# Averaging each form's percentage separately gives a different answer whenever the two
# forms have different numbers of ratings — which they do (Accountability has 4 criteria,
# Ownership 4, but partial submission means the counts diverge).
# ─────────────────────────────────────────────────────────────
async def activity_score_pct(activity: str, company_id: str,
                             tokens: Optional[List[str]] = None,
                             period: Optional[str] = None) -> Optional[int]:
    """Pooled score % for a form-backed activity, or None when there are no submissions."""
    form_types = ACTIVITY_FORM_MAP.get(activity)
    if not form_types:
        return None
    if tokens is None:
        tokens = period_tokens(period) if period else []

    rating_sum = rating_count = yes_count = answer_count = 0

    for ft in form_types:
        coll = submission_collection(ft)
        if not coll:
            continue
        query = {"company_id": company_id}
        if tokens:
            query["period"] = {"$in": tokens}
        docs = await get_collection(coll).find(query).to_list(2000)

        if form_kind(ft) == KIND_YESNO_CHECKLIST:
            for d in docs:
                for _qid, ans in (d.get("answers") or {}).items():
                    answer_count += 1
                    if ans.get("checked"):
                        yes_count += 1
        else:
            for d in docs:
                for _code, members in (d.get("ratings") or {}).items():
                    for _mid, cell in (members or {}).items():
                        r = cell.get("rating")
                        if isinstance(r, (int, float)):
                            rating_sum += r
                            rating_count += 1

    # Yes/No takes precedence when present — mirrors the source's `if (g.tot>0)` branch.
    if answer_count > 0:
        return round(yes_count / answer_count * 100)
    if rating_count > 0:
        return round(rating_sum / (rating_count * SCALE_MAX) * 100)
    return None


# ─────────────────────────────────────────────────────────────
# Aggregation from the activity tracker
# ─────────────────────────────────────────────────────────────
async def _aggregate_tracker(period: Optional[str]) -> Dict[tuple, dict]:
    """{(company_id, activity_lower, period): {total, completed, activity}} plus the
    derived Calendar Discipline pseudo-activity."""
    query = {}
    if period:
        query["period"] = period
    rows = await get_collection(COLL_ACTIVITY_TRACKER).find(query).to_list(20000)

    agg: Dict[tuple, dict] = {}
    cal_pool: Dict[tuple, dict] = {}
    excl = CAL_DISCIPLINE_EXCLUDE.lower()
    cal_lower = CAL_DISCIPLINE_ACTIVITY.lower()

    for r in rows:
        cid = str(r.get("company_id") or "")
        activity = str(r.get("activity") or "")
        per = str(r.get("period") or "")
        status = str(r.get("status") or "")
        if not cid or not activity or not per:
            continue
        if status == STATUS_CANCELLED:
            continue

        key = (cid, activity.lower(), per)
        g = agg.setdefault(key, {"company_id": cid, "activity": activity,
                                 "period": per, "total": 0, "completed": 0})
        g["total"] += 1
        if status == STATUS_COMPLETED:
            g["completed"] += 1

        al = activity.lower()
        if al not in (excl, cal_lower):
            ck = (cid, per)
            c = cal_pool.setdefault(ck, {"total": 0, "completed": 0})
            c["total"] += 1
            if status == STATUS_COMPLETED:
                c["completed"] += 1

    for (cid, per), c in cal_pool.items():
        if c["total"] <= 0:
            continue
        agg[(cid, cal_lower, per)] = {
            "company_id": cid, "activity": CAL_DISCIPLINE_ACTIVITY, "period": per,
            "total": c["total"], "completed": c["completed"],
        }
    return agg


# ─────────────────────────────────────────────────────────────
# Seed — port of seedSuccessMeasures (code.js:2209)
# ─────────────────────────────────────────────────────────────
async def seed_success_measures(period: str, company_ids: Optional[List[str]] = None) -> dict:
    """Create the company × activity rows for a period, with default 100% targets.
    Insert-only: existing rows are never touched."""
    activities = await get_collection(COLL_ACTIVITIES).find(
        {"active": {"$ne": False}}
    ).to_list(200)

    if company_ids is None:
        companies = await get_collection("companies").find(
            {"is_active": {"$ne": False}}
        ).to_list(1000)
        company_ids = [str(c["_id"]) for c in companies]

    existing = set()
    for row in await get_collection(COLL_SUCCESS_MEASURES).find(
        {"period": period, "scope": SCOPE_COMPANY}
    ).to_list(20000):
        existing.add((str(row.get("company_id")), str(row.get("activity", "")).lower()))

    now = datetime.utcnow()
    new_rows = [{
        "company_id": cid,
        "activity": a["name"],
        "period": period,
        "impl_target": 100,
        "impl_actual": None,
        "score_target": 100,
        "score_actual": None,
        "achievement": None,
        "scope": SCOPE_COMPANY,
        "hod_id": None,
        "updated_at": now,
    } for cid in company_ids for a in activities
        if (cid, a["name"].lower()) not in existing]

    if new_rows:
        try:
            await get_collection(COLL_SUCCESS_MEASURES).insert_many(new_rows, ordered=False)
        except Exception:
            pass  # unique index absorbs concurrent seeds
    return {"seeded": len(new_rows), "period": period}


# ─────────────────────────────────────────────────────────────
# Sync — port of syncSuccessMeasures (code.js:2054)
# ─────────────────────────────────────────────────────────────
async def sync_success_measures(period: Optional[str] = None) -> dict:
    """Recompute Implementation %, Score % and Achievement % for every seeded row.

    Rows with no seeded counterpart are skipped and counted, exactly as the source does.
    """
    agg = await _aggregate_tracker(period)

    catalogue = {}
    for a in await get_collection(COLL_ACTIVITIES).find({}).to_list(200):
        catalogue[str(a.get("name", "")).lower()] = a

    query = {"period": period} if period else {}
    rows = await get_collection(COLL_SUCCESS_MEASURES).find(query).to_list(20000)

    # Manual per-HOD rows, grouped so a HOD-scoped activity can average across HODs.
    manual_hod: Dict[tuple, List[dict]] = {}
    for r in rows:
        if r.get("scope") == SCOPE_HOD and r.get("hod_id"):
            manual_hod.setdefault(
                (str(r.get("company_id")), str(r.get("activity", "")).lower(), str(r.get("period"))),
                [],
            ).append(r)

    updated = skipped = 0
    now = datetime.utcnow()

    for row in rows:
        if row.get("scope") == SCOPE_HOD:
            continue  # per-HOD manual entries are inputs, not outputs

        cid = str(row.get("company_id") or "")
        activity = str(row.get("activity") or "")
        per = str(row.get("period") or "")
        key = (cid, activity.lower(), per)
        meta = catalogue.get(activity.lower()) or {}
        score_mode = meta.get("score_mode")

        g = agg.get(key)
        if not g and score_mode not in (SCORE_MODE_FORM, SCORE_MODE_MANUAL):
            skipped += 1
            continue

        total = (g or {}).get("total", 0)
        completed = (g or {}).get("completed", 0)
        impl_actual = 100 if completed > 0 else 0          # binary — per source
        auto_score = round(completed / total * 100) if total > 0 else 0

        score_target = row.get("score_target")
        score_actual = auto_score

        if score_mode == SCORE_MODE_FORM:
            pct = await activity_score_pct(activity, cid, tokens=period_tokens(per))
            score_actual = pct  # may be None → renders as "no data"
        elif score_mode == SCORE_MODE_MANUAL:
            if meta.get("scope") == SCOPE_HOD:
                hod_rows = manual_hod.get(key, [])
                actuals = [h["score_actual"] for h in hod_rows if h.get("score_actual") is not None]
                targets = [h["score_target"] for h in hod_rows if h.get("score_target") is not None]
                score_actual = round(sum(actuals) / len(actuals)) if actuals else None
                if targets:
                    score_target = round(sum(targets) / len(targets))
            else:
                # Company-scoped manual value is typed directly onto this row.
                score_actual = row.get("score_actual")

        if score_actual is None:
            achievement = None
        elif score_target:
            achievement = round(score_actual / score_target * 100)
        else:
            achievement = score_actual

        await get_collection(COLL_SUCCESS_MEASURES).update_one(
            {"_id": row["_id"]},
            {"$set": {
                "impl_actual": impl_actual,
                "score_actual": score_actual,
                "score_target": score_target if score_target is not None else 100,
                "impl_target": row.get("impl_target") if row.get("impl_target") is not None else 100,
                "achievement": achievement,
                "updated_at": now,
            }},
        )
        updated += 1

    msg = f"TPMS success measures: {updated} updated, {skipped} skipped" + (f" [{period}]" if period else "")
    logger.info(msg)
    return {"updated": updated, "skipped": skipped, "period": period}


def pct_num(v):
    """Port of pctNum_ (spec §18).

    Accepts 95, "95", "95%" or 0.95 (a fraction) and always returns an integer 0-100, or
    None for blank/unparseable input. A bare value below 1 is read as a fraction — a real
    1% would be entered as "1", not "0.01" — and the result is clamped to the 0-100 range.
    """
    if v is None or v == "":
        return None
    try:
        n = float(str(v).strip().replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    if 0 < n < 1:
        n *= 100
    return max(0, min(100, int(round(n))))


async def save_manual_score(user: dict, payload: dict) -> dict:
    """Upsert a manually-entered score (saveManualScore, code.js:2636).
    `scope` is 'company' or 'hod'; HOD-scoped rows carry hod_id and are averaged by sync."""
    company_id = str(payload.get("company_id") or "")
    activity = str(payload.get("activity") or "")
    period = str(payload.get("period") or "")
    scope = str(payload.get("scope") or SCOPE_COMPANY).lower()
    hod_id = str(payload.get("hod_id") or "") or None

    if not company_id or not activity or not period:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="company_id, activity and period are required")
    if scope == SCOPE_HOD and not hod_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="hod_id is required for HOD-scoped scores")

    await get_collection(COLL_SUCCESS_MEASURES).update_one(
        {"company_id": company_id, "activity": activity, "period": period,
         "scope": scope, "hod_id": hod_id},
        {"$set": {
            "score_target": pct_num(payload.get("target")),
            "score_actual": pct_num(payload.get("actual")),
            "hod_name": payload.get("hod_name"),
            "updated_by": user.get("full_name") or user.get("email"),
            "updated_at": datetime.utcnow(),
        }},
        upsert=True,
    )
    await sync_success_measures(period)
    return {"ok": True}


async def dedupe_success_measures() -> dict:
    """One-off cleanup (port of dedupeSuccessMeasures): collapse duplicate Success_Measure
    rows to the most-recently-updated one per (company, activity, period, scope, hod). A unique
    index now prevents new duplicates, but migrated/legacy data may still carry them."""
    col = get_collection(COLL_SUCCESS_MEASURES)
    seen = {}
    dupes = []
    async for row in col.find({}):
        key = (str(row.get("company_id") or ""), str(row.get("activity") or ""),
               str(row.get("period") or ""), str(row.get("scope") or SCOPE_COMPANY),
               str(row.get("hod_id") or ""))
        keep = seen.get(key)
        if keep is None:
            seen[key] = row
            continue
        # Keep whichever was updated later; drop the older row.
        keep_at = keep.get("updated_at") or datetime.min
        row_at = row.get("updated_at") or datetime.min
        older, newer = (keep, row) if keep_at <= row_at else (row, keep)
        seen[key] = newer
        dupes.append(older["_id"])
    if dupes:
        await col.delete_many({"_id": {"$in": dupes}})
    return {"ok": True, "removed": len(dupes), "kept": len(seen)}


async def run_daily(period: Optional[str] = None) -> dict:
    """Seed then sync — the two triggers the Apps Script installed, in their order."""
    if period is None:
        now = datetime.utcnow()
        period = f"{now.year:04d}-{now.month:02d}"
    seeded = await seed_success_measures(period)
    synced = await sync_success_measures(period)
    return {"seed": seeded, "sync": synced}
