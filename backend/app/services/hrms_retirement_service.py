"""HRMS > Retirement alerts (BA/Functional Design v2.2, §7.20, step 155).

Deliberately the thinnest of the Phase MOVE-1 services — see the module docstring at the top
of the Phase MOVE-1 block in models/hrms.py for why. This is a proactive, read-only alert
("who retires in the next N months") computed from an employee's DOB and the company's own
configured retirement age; there is no case to open here, because once HR acts on an alert the
existing Exit Management (Phase EXIT-1) flow runs the actual separation end to end, with
`exit_type=Retirement`.

Demise/Missing's nominee-and-legal-documentation extension lives in hrms_exit_service.py
instead, alongside the separation record it belongs to (see save_nominee_details there) —
not here, since there is no "alert" to compute for either.
"""
from datetime import date, datetime, timezone

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_EMPLOYEE_PROFILES, COLL_SETTINGS,
    DEFAULT_RETIREMENT_ALERT_MONTHS, DEFAULT_RETIREMENT_AGE,
    EmploymentStatus,
)


async def get_retirement_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("retirement_policy") or {}
    return {
        "retirement_age": stored.get("retirement_age", DEFAULT_RETIREMENT_AGE),
        "alert_months_ahead": stored.get("alert_months_ahead", DEFAULT_RETIREMENT_ALERT_MONTHS),
        # Surfaced so HR sees plainly that this is a placeholder, not a client sign-off — the
        # BA doc says the age itself "must be confirmed" (§7.20 BR).
        "policy_confirmed": stored.get("policy_confirmed", False),
    }


async def save_retirement_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_retirement_policy(company_id),
             **{k: v for k, v in payload.items() if v is not None}}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"retirement_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    return merged


def _retirement_date(dob: str, retirement_age: int) -> str:
    y, m, d = (int(x) for x in dob.split("-"))
    try:
        return date(y + retirement_age, m, d).isoformat()
    except ValueError:
        # Feb 29 on a non-leap retirement year — the nearest real date, not an error.
        return date(y + retirement_age, m, d - 1).isoformat()


async def list_upcoming_retirements(actor: dict, company_id: str) -> list:
    """§7.20 step 155: the alert list HR/manager sees in advance. Active employees only —
    someone already separated has nothing left to alert on."""
    policy = await get_retirement_policy(company_id)
    horizon = date.today()
    alert_year = horizon.year + (1 if horizon.month + policy["alert_months_ahead"] > 12 else 0)
    alert_month = ((horizon.month - 1 + policy["alert_months_ahead"]) % 12) + 1
    cutoff = date(alert_year, alert_month, horizon.day if horizon.day <= 28 else 28).isoformat()

    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find({
        "company_id": str(company_id),
        "employment_status": {"$nin": [EmploymentStatus.RESIGNED.value,
                                       EmploymentStatus.TERMINATED.value]},
        "date_of_birth": {"$ne": None},
    }).to_list(2000)

    upcoming = []
    for r in rows:
        dob = r.get("date_of_birth")
        if not dob:
            continue
        retirement_date = _retirement_date(dob, policy["retirement_age"])
        if horizon.isoformat() <= retirement_date <= cutoff:
            upcoming.append({
                "employee_code": r.get("employee_code"),
                "display_name": r.get("display_name") or r.get("full_name"),
                "date_of_birth": dob,
                "retirement_date": retirement_date,
            })
    upcoming.sort(key=lambda x: x["retirement_date"])
    return upcoming
