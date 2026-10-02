"""
Import TPMS Schedule Data from Google Sheet CSV to MongoDB (Bulk Optimized).

Collection target: `LEARNER_CALENDER` with `kind: "tpms_activity"`
Tracker target: `tpms_activity_tracker`
"""

import csv
import asyncio
import os
import sys
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Unbuffer stdout so logs display immediately
sys.stdout.reconfigure(line_buffering=True)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
CSV_PATH = os.path.join(os.path.dirname(BACKEND_DIR), "Export_Calender_with_dashboard - Calendar_Schedule.csv")

load_dotenv(ENV_PATH)

MONGO_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "sparsh_erp")

HARDCODED_COMPANY_MAP = {
    "KEPL001": "69f4a1504cf251556e13dc15",    # Khokhar Electricals - Industrial
    "KITCH001": "69dce7f6cb349419bfc0a169",   # Kutchina - Consumer Durables
    "ENIND001": "69dce5f8cb349419bfc0a155",   # Ener Industries - Industrial
    "ARIHA001": "69dce79bcb349419bfc0a165",   # Arihant Connect Private Limited- Supply Chain
    "GANPA001": "69fb371dea238c4b65b2bca8",   # Ganpatraj Gold Pvt. Ltd
    "SITAR001": "69fc468bea238c4b65b2bcbd",   # Sitaram & CoSitaram & Co - Industrial
    "ATMA001": "69f4a0e44cf251556e13dc11",    # ATMA - Non-Profit Social
    "JOLLY001": "69dce73fcb349419bfc0a161",   # Jolly Healthcare - Pharameceuticals
    "CHAVAN001": "6a01d087b17da672d7e116a2",  # Chavan Motors - Automobile
    "SURGU001": "69dce365cb349419bfc0a150",   # Surguja Auto Cares - Automobile
    "ICARE001": "69f4a1de4cf251556e13dc19",   # Icare Lifts- Logistics
    "PEECO001": "69f59f79d19aee7514c8e7b4",   # Peeco Polytech - Chemicals
    "PTOP001": "69d782804c39e25a85456dc2",    # People to Process
    "SOURUSH001": "6a5092fb312aa18f1fa2214a", # SOURUSH TECHNO SOLUTIONS PVT LTD
}

def erp_status_for(tpms_status: str) -> str:
    status_map = {
        "Scheduled": "schedule",
        "Rescheduled": "reschedule",
        "Cancelled": "canceled",
        "Completed": "completed",
        "Lapsed": "schedule",
    }
    return status_map.get(tpms_status, "schedule")

def parse_dt(val: str):
    if not val:
        return None
    val = str(val).strip()
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None

def period_from_date(date_str: str) -> str:
    d = str(date_str or "").strip()
    return d[:7] if len(d) >= 7 else datetime.utcnow().strftime("%Y-%m")

async def get_or_create_company(db, company_code: str, company_name: str, db_company_cache: dict) -> tuple[str, str]:
    code = (company_code or "").strip()
    name = (company_name or "").strip()
    
    if code in HARDCODED_COMPANY_MAP:
        cid = HARDCODED_COMPANY_MAP[code]
        c_doc = db_company_cache.get(cid)
        c_name = c_doc.get("name") if c_doc else name
        return cid, c_name
    
    for cid, c_doc in db_company_cache.items():
        c_code = str(c_doc.get("code") or "")
        c_db_name = str(c_doc.get("name") or "")
        if code and code.lower() == c_code.lower():
            return cid, c_db_name
        if name and name.lower() == c_db_name.lower():
            return cid, c_db_name

    print(f"[!] Creating missing company in DB: code='{code}', name='{name}'", flush=True)
    new_doc = {
        "name": name or code,
        "code": code,
        "tpms_enabled": True,
        "created_at": datetime.utcnow(),
    }
    res = await db.companies.insert_one(new_doc)
    new_id = str(res.inserted_id)
    new_doc["_id"] = new_id
    db_company_cache[new_id] = new_doc
    return new_id, name or code

async def import_tpms():
    print(f"Connecting to MongoDB database '{DATABASE_NAME}'...", flush=True)
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DATABASE_NAME]

    target_coll = db["LEARNER_CALENDER"]
    tracker_coll = db["tpms_activity_tracker"]

    # Load existing company docs
    companies_list = await db.companies.find({}).to_list(1000)
    company_cache = {str(c["_id"]): c for c in companies_list}

    # Load existing learners & staff for email-to-id mapping
    learners_list = await db.learners.find({}).to_list(2000)
    staff_list = await db.staff.find({}).to_list(2000)

    learner_email_to_id = {str(l.get("email")).strip().lower(): str(l["_id"]) for l in learners_list if l.get("email")}
    staff_email_to_id = {str(s.get("email")).strip().lower(): str(s["_id"]) for s in staff_list if s.get("email")}

    # Upfront fetch of all existing tpms_schedule_ids for idempotency
    existing_ids = set(await target_coll.distinct("tpms_schedule_id"))
    print(f"Loaded {len(company_cache)} companies, {len(learner_email_to_id)} learners, {len(staff_email_to_id)} staff from DB.", flush=True)
    print(f"Found {len(existing_ids)} existing TPMS schedule IDs in 'LEARNER_CALENDER'.", flush=True)

    if not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV file not found at '{CSV_PATH}'", flush=True)
        return

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} rows from CSV file: {CSV_PATH}", flush=True)

    events_to_insert = []
    tracker_to_insert = []
    skipped_events = 0

    for idx, row in enumerate(rows):
        schedule_id = (row.get("Schedule_ID") or "").strip()
        batch_id = (row.get("Batch_ID") or "").strip()
        title = (row.get("Title") or "").strip()
        activity = (row.get("Activity") or "").strip()
        event_date = (row.get("Event_Date") or "").strip()
        event_time = (row.get("Event_Time") or "").strip()
        comp_id_raw = (row.get("Company_ID") or "").strip()
        comp_name_raw = (row.get("Company_Name") or "").strip()
        status = (row.get("Status") or "Scheduled").strip()
        departments_raw = (row.get("Departments") or "HOD").strip()
        assigners_raw = (row.get("Company_Assigners") or "").strip()
        staff_raw = (row.get("Staff_Assigner") or "").strip()
        recurrence = (row.get("Recurrence") or "One-time").strip()
        plan_start = (row.get("Plan_Start") or event_date).strip()
        plan_end = (row.get("Plan_End") or "").strip()
        created_at_raw = (row.get("Created_At") or "").strip()
        created_by_raw = (row.get("Created_By") or "").strip()
        reschedule_count_raw = (row.get("Reschedule_Count") or "0").strip()
        completed_at_raw = (row.get("Completed_At") or "").strip()
        comment = (row.get("Comment") or "").strip()
        completed_by = (row.get("Completed_by") or "").strip()
        esc_stage_raw = (row.get("Esc_Stage") or "0").strip()
        learner_done_raw = (row.get("Learner_Done") or "").strip()
        learner_done_by = (row.get("Learner_Done_By") or "").strip()
        learner_done_at_raw = (row.get("Learner_Done_At") or "").strip()

        if not title or not event_date:
            continue

        # Skip existing for idempotency
        if schedule_id and schedule_id in existing_ids:
            skipped_events += 1
            continue

        company_id, company_name = await get_or_create_company(db, comp_id_raw, comp_name_raw, company_cache)

        departments = [d.strip() for d in departments_raw.split(",") if d.strip()] or ["HOD"]
        assigner_emails = [a.strip() for a in assigners_raw.split(",") if a.strip()]
        member_ids = [learner_email_to_id.get(a.lower(), a) for a in assigner_emails]

        staff_emails = [s.strip() for s in staff_raw.split(",") if s.strip()]
        coach_ids = [staff_email_to_id.get(s.lower(), s) for s in staff_emails]

        if event_time:
            start_iso = f"{event_date}T{event_time}:00"
            all_day = False
        else:
            start_iso = event_date
            all_day = True

        created_at = parse_dt(created_at_raw) or datetime.utcnow()
        completed_at = parse_dt(completed_at_raw)
        learner_done_at = parse_dt(learner_done_at_raw)

        is_learner_done = learner_done_raw.upper() in ("TRUE", "1", "YES") or status == "Completed"
        if status == "Completed" and not learner_done_by:
            learner_done_by = assigner_emails[0] if assigner_emails else (completed_by or "Learner")
        if status == "Completed" and not learner_done_at:
            learner_done_at = completed_at or created_at

        try:
            esc_stage = int(esc_stage_raw)
        except ValueError:
            esc_stage = 0

        try:
            reschedule_count = int(reschedule_count_raw)
        except ValueError:
            reschedule_count = 0

        event_oid = ObjectId()
        event_id_str = str(event_oid)

        event_doc = {
            "_id": event_oid,
            "title": title,
            "type": "event",
            "start": start_iso,
            "all_day": all_day,
            "kind": "tpms_activity",
            "tpms_schedule_id": schedule_id or f"SCH-{int(datetime.utcnow().timestamp()*1000)}-{idx}",
            "tpms_batch_id": batch_id or f"BATCH-{int(datetime.utcnow().timestamp()*1000)}",
            "tpms_status": status,
            "status": erp_status_for(status),
            "activity": activity,
            "company_id": company_id,
            "company_name": company_name,
            "assigned_departments": departments,
            "assigned_member_ids": member_ids,
            "coach_ids": coach_ids,
            "additional_details": comment,
            "reminders": [],
            "esc_stage": esc_stage,
            "reschedule_count": reschedule_count,
            "learner_done": is_learner_done,
            "learner_done_by": learner_done_by,
            "learner_done_at": learner_done_at,
            "completed_at": completed_at,
            "completed_by": completed_by,
            "user_id": created_by_raw or "system_import",
            "scheduled_by_side": "internal",
            "scheduled_by_name": created_by_raw or "SMOps",
            "created_at": created_at,
            "activity_meta": {
                "scope": "company",
                "recurrence": recurrence,
                "plan_start": plan_start,
                "plan_end": plan_end or None,
            },
        }

        events_to_insert.append(event_doc)

        period = period_from_date(event_date)
        for mem_id in (member_ids or [company_id]):
            tracker_to_insert.append({
                "company_id": company_id,
                "member_id": mem_id,
                "period": period,
                "date": event_date,
                "activity": activity,
                "status": status,
                "event_id": event_id_str,
                "updated_at": completed_at or created_at,
            })

    print(f"Prepared {len(events_to_insert)} calendar events and {len(tracker_to_insert)} tracker records for bulk insert.", flush=True)

    # Bulk insert into LEARNER_CALENDER
    if events_to_insert:
        batch_size = 500
        for i in range(0, len(events_to_insert), batch_size):
            chunk = events_to_insert[i:i+batch_size]
            await target_coll.insert_many(chunk)
            print(f"Inserted batch {i//batch_size + 1}: {len(chunk)} events", flush=True)

    # Bulk insert into tpms_activity_tracker
    if tracker_to_insert:
        batch_size = 500
        for i in range(0, len(tracker_to_insert), batch_size):
            chunk = tracker_to_insert[i:i+batch_size]
            try:
                await tracker_coll.insert_many(chunk, ordered=False)
                print(f"Inserted tracker batch {i//batch_size + 1}: {len(chunk)} tracking rows", flush=True)
            except Exception as e:
                print(f"Tracker batch warning: {e}", flush=True)

    print("\n==================================================", flush=True)
    print("      TPMS CSV IMPORT SUMMARY RESULTS            ", flush=True)
    print("==================================================", flush=True)
    print(f"Total Rows in CSV         : {len(rows)}", flush=True)
    print(f"Events Inserted           : {len(events_to_insert)}", flush=True)
    print(f"Events Skipped (Existing) : {skipped_events}", flush=True)
    print(f"Tracker Rows Created      : {len(tracker_to_insert)}", flush=True)
    print("==================================================\n", flush=True)

    client.close()

if __name__ == "__main__":
    asyncio.run(import_tpms())
