"""
H11 — author + insert default mail templates for the 3 activities the source `Templates`
sheet never covered: Customer Satisfaction Index, Organization Result Matrix,
Team Engagement Index. Without these, those activities fall back to the built-in generic body.

Generates one document per (activity × side × event) = 3 × 2 × 5 = 30 rows, upserted on
(activity, side, event) so it is safe to re-run. Every row is tagged
`source="authored_default"` so it can be identified or removed in one query.

Bodies use ONLY placeholders that app/services/tpms_notify_service.build_map() actually
provides ({{Title}}, {{Activity}}, {{Company_Name}}, {{Event_Date}}, {{Event_Time}},
{{Status}}, {{Comment}}) so nothing renders as a literal {{token}}.

Usage (from backend/):
    python -m scripts.seed_missing_templates            # apply
    python -m scripts.seed_missing_templates --dry-run  # preview
"""
import asyncio
import sys
from datetime import datetime

from app.db.mongodb import connect_to_mongo, get_collection
from app.models.tpms import COLL_MAIL_TEMPLATES

MISSING_ACTIVITIES = [
    "Customer Satisfaction Index",
    "Organization Result Matrix",
    "Team Engagement Index",
]

SIDES = ["staff", "company"]

# event → (subject, heading, intro sentence)
EVENTS = {
    "schedule":   ("[Scheduled] {{Title}} – {{Activity}}", "Activity Scheduled",
                   "A new activity has been scheduled for <b>{{Company_Name}}</b>."),
    "reminder":   ("[Reminder] {{Title}} – {{Activity}}", "Activity Reminder",
                   "This is a reminder for an upcoming activity for <b>{{Company_Name}}</b>."),
    "reschedule": ("[Rescheduled] {{Title}} – {{Activity}}", "Activity Rescheduled",
                   "An activity for <b>{{Company_Name}}</b> has been rescheduled."),
    "cancel":     ("[Cancelled] {{Title}} – {{Activity}}", "Activity Cancelled",
                   "An activity for <b>{{Company_Name}}</b> has been cancelled."),
    "completed":  ("[Completed] {{Title}} – {{Activity}}", "Activity Completed",
                   "An activity for <b>{{Company_Name}}</b> has been completed."),
}


def _body(heading: str, intro: str) -> str:
    return (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px;max-width:600px;margin:auto;'
        'border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">'
        '<div style="background:#4f46e5;color:#fff;padding:16px 20px;font-weight:800">' + heading + '</div>'
        '<div style="padding:20px">'
        '<p>' + intro + '</p>'
        '<table style="border-collapse:collapse;font-size:14px;margin-top:8px">'
        '<tr><td style="padding:4px 12px 4px 0;color:#64748b">Activity</td><td style="padding:4px 0"><b>{{Activity}}</b></td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#64748b">Company</td><td style="padding:4px 0">{{Company_Name}}</td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#64748b">Date</td><td style="padding:4px 0">{{Event_Date}} {{Event_Time}}</td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#64748b">Status</td><td style="padding:4px 0">{{Status}}</td></tr>'
        '</table>'
        '<p style="color:#64748b;margin-top:12px">{{Comment}}</p>'
        '</div></div>'
    )


def build_docs():
    docs = []
    for activity in MISSING_ACTIVITIES:
        for side in SIDES:
            for event, (subject, heading, intro) in EVENTS.items():
                docs.append({
                    "activity": activity,
                    "side": side,
                    "event": event,
                    "subject": subject,
                    "body_html": _body(heading, intro),
                    "active": True,
                    "source": "authored_default",
                })
    return docs


async def main(dry_run: bool):
    docs = build_docs()
    print(f"Prepared {len(docs)} template(s) for {len(MISSING_ACTIVITIES)} activities "
          f"({len(SIDES)} sides x {len(EVENTS)} events).")
    if dry_run:
        print("[DRY-RUN] Nothing written.")
        return

    await connect_to_mongo()
    coll = get_collection(COLL_MAIL_TEMPLATES)
    now = datetime.utcnow()
    written = 0
    for d in docs:
        d["migrated_at"] = now
        await coll.update_one(
            {"activity": d["activity"], "side": d["side"], "event": d["event"]},
            {"$set": d},
            upsert=True,
        )
        written += 1
    total = await coll.count_documents({})
    covered = len(await coll.distinct("activity"))
    print(f"[OK] Upserted {written}. Collection now holds {total} template(s) "
          f"covering {covered} activities.")


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv))
