"""TPMS ▸ WhatsApp notification validator — the Schedule event end to end.

Two modes: one proves the code path, one diagnoses the data and credentials behind it.

  --self-test   Exercises the REAL notify path (notify_schedule → _dispatch → send_whatsapp)
                against an in-memory database and a stubbed Cloud API. No Mongo, no Meta
                credentials, no network. This is what proves a scheduled activity dispatches
                WhatsApp alongside its mail, and that a failed send is reported as failed.

  (default)     Live diagnosis against the configured database and WhatsApp Business Account:
                credentials, the Meta library's approval status, the (activity × side × event)
                wiring rows, and — with --event-id — the recipients and the phone numbers a
                real send would resolve to. Add --send to actually deliver.

Usage (PowerShell, from backend/):
    python scripts/validate_tpms_whatsapp.py --self-test
    python scripts/validate_tpms_whatsapp.py --activity "Accountability & Ownership Rating"
    python scripts/validate_tpms_whatsapp.py --activity "Accountability & Ownership Rating" `
        --event-id 665f0c1234567890abcdef01 --send
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId  # noqa: E402

OK, BAD, WARN, DOT = "[PASS]", "[FAIL]", "[WARN]", " -"

_results: list = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    _results.append(bool(condition))
    print(f"{OK if condition else BAD} {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


# ─────────────────────────────────────────────────────────────
# Self-test — in-memory Mongo + stubbed Cloud API
# ─────────────────────────────────────────────────────────────
def _match(doc: dict, query: dict) -> bool:
    """The operator subset the notify service actually uses: equality, $ne, $in, $regex."""
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$regex" in cond:
                flags = re.I if "i" in str(cond.get("$options") or "") else 0
                if not re.search(cond["$regex"], str(val or ""), flags):
                    return False
        elif val != cond:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, length=None):
        return list(self._docs)[: length or len(self._docs)]


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, query=None, *_a, **_k):
        for d in self.docs:
            if _match(d, query or {}):
                return dict(d)
        return None

    def find(self, query=None, *_a, **_k):
        return _FakeCursor([dict(d) for d in self.docs if _match(d, query or {})])

    async def insert_one(self, doc, *_a, **_k):
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc.get("_id")})()

    async def update_one(self, *_a, **_k):
        return type("R", (), {"modified_count": 0})()


DOER_ID = ObjectId("665f000000000000000000d1")
DOER2_ID = ObjectId("665f000000000000000000d2")
STAFF_ID = ObjectId("665f000000000000000000f1")

ACTIVITY = "Accountability & Ownership Rating"
TPL_NAME = "tpms_activity_schedule"
# What the wiring row maps {{1}}..{{4}} to, and therefore what Meta must receive, in order.
EXPECTED_PARAMS = ["Acme Pvt Ltd", ACTIVITY, "2026-08-20", "11:30"]


def _event(**over) -> dict:
    ev = {
        "_id": "665f000000000000000000aa",
        "kind": "tpms_activity",
        "activity": ACTIVITY,
        "title": "A&O Rating - August",
        "company_name": "Acme Pvt Ltd",
        "company_id": "665f000000000000000000c0",
        "start": "2026-08-20T11:30:00",
        "assigned_member_ids": [str(DOER_ID)],
        "coach_ids": [str(STAFF_ID)],
        "assigned_departments": ["Sales"],
        "activity_meta": {"scope": "hod"},
    }
    ev.update(over)
    return ev


def _wiring(activity: str, side: str, event: str = "schedule", **over) -> dict:
    row = {
        "activity": activity, "side": side, "event": event,
        "meta_template_name": TPL_NAME, "name": TPL_NAME, "language": "en",
        "variables": ["Company_Name", "Activity", "Event_Date", "Event_Time"],
        "header_variables": [], "button_variables": [], "active": True,
    }
    row.update(over)
    return row


class _Harness:
    """Patches the service's database handle and the two delivery functions, then restores
    them. Everything between the patches is the real, shipped code path."""

    def __init__(self, wiring_rows, learners=None, staff=None, wa_result=True):
        from app.models.tpms import COLL_MAIL_TEMPLATES, COLL_WHATSAPP_TEMPLATES

        self.collections = {
            COLL_WHATSAPP_TEMPLATES: _FakeCollection(wiring_rows),
            COLL_MAIL_TEMPLATES: _FakeCollection([]),
            "learners": _FakeCollection(learners if learners is not None else [{
                "_id": DOER_ID, "full_name": "Priya Doer",
                "email": "priya@acme.test", "mobile": "09876543210",
            }]),
            "staff": _FakeCollection(staff if staff is not None else [{
                "_id": STAFF_ID, "full_name": "Ravi Coach",
                "email": "ravi@dtable.test", "mobile": "+91 90000 11111",
            }]),
        }
        self.wa_result = wa_result
        self.mails: list = []
        self.whatsapps: list = []

    def _collection(self, name):
        return self.collections.setdefault(name, _FakeCollection([]))

    async def _send_email(self, to, subject, html, **kw):
        self.mails.append({"to": to, "subject": subject, "slug": kw.get("slug")})
        return True

    async def _send_wa(self, phone, template_name, language, params, **kw):
        self.whatsapps.append({
            "phone": phone, "template": template_name, "language": language,
            "params": list(params or []), "slug": kw.get("slug"),
            "components": kw.get("components"), "meta": kw.get("meta"),
        })
        return self.wa_result

    async def __aenter__(self):
        import app.services.notification_service as ns
        import app.services.tpms_form_link_service as fls
        import app.services.tpms_notify_service as svc

        self._svc, self._ns, self._fls = svc, ns, fls
        self._saved = (svc.get_collection, ns.send_email_notification,
                       ns.send_whatsapp_template, fls.assignments_for_event)
        svc.get_collection = self._collection
        ns.send_email_notification = self._send_email
        ns.send_whatsapp_template = self._send_wa

        async def _no_assignments(*_a, **_k):
            return []
        fls.assignments_for_event = _no_assignments
        return self

    async def __aexit__(self, *_exc):
        (self._svc.get_collection, self._ns.send_email_notification,
         self._ns.send_whatsapp_template, self._fls.assignments_for_event) = self._saved
        return False


async def self_test() -> None:
    import app.services.tpms_notify_service as svc

    print("\n=== TPMS WhatsApp — Schedule end-to-end (in-memory DB, stubbed Cloud API) ===\n")

    # 1 ─ the fix itself: a schedule dispatch now sends WhatsApp to both wired sides.
    print("1. Schedule dispatches WhatsApp to both sides")
    async with _Harness([_wiring(ACTIVITY, "company"), _wiring(ACTIVITY, "staff")]) as h:
        res = await svc.notify_schedule(_event())
    wa = res.get("whatsapp") or {}
    check("WhatsApp sent to both sides", len(h.whatsapps) == 2, f"{len(h.whatsapps)} send(s)")
    check("counters report 2 sent / 0 failed", wa.get("sent") == 2 and wa.get("failed") == 0, str(wa))
    check("mail still sent to both sides", len(h.mails) == 2, f"{len(h.mails)} mail(s)")
    by_slug = {w["slug"]: w for w in h.whatsapps}
    check("slugs identify event and side",
          set(by_slug) == {"tpms_wa_schedule_company", "tpms_wa_schedule_staff"}, str(set(by_slug)))
    company = by_slug.get("tpms_wa_schedule_company") or {}
    check("approved template name used", company.get("template") == TPL_NAME, str(company.get("template")))
    check("ordered params resolved from build_map",
          company.get("params") == EXPECTED_PARAMS, str(company.get("params")))
    check("phone normalised to country code", company.get("phone") == "919876543210",
          str(company.get("phone")))
    check("staff phone normalised from '+91 90000 11111'",
          (by_slug.get("tpms_wa_schedule_staff") or {}).get("phone") == "919000011111")
    check("body-only template sends no components override",
          company.get("components") is None)
    # The Logs Report reads activity / company_name straight off the log row, so the send must
    # carry them the way the mail path does — otherwise the WhatsApp rows render as dashes.
    meta = company.get("meta") or {}
    check("log context recorded on the send",
          meta.get("activity") == ACTIVITY and meta.get("company_name") == "Acme Pvt Ltd",
          str(meta))
    check("log context carries the event id",
          meta.get("event_id") == "665f000000000000000000aa", str(meta.get("event_id")))

    # 2 ─ the wiring row's activity is free text; the lookup must survive case and stray space.
    print("\n2. Activity matching is tolerant of case and surrounding space")
    async with _Harness([_wiring("  accountability & ownership rating ", "company")]) as h:
        res = await svc.notify_schedule(_event())
    check("row saved with wrong case/space still matches",
          len(h.whatsapps) == 1, f"{len(h.whatsapps)} send(s)")
    check("exact-name row is unaffected", (res.get("whatsapp") or {}).get("sent") == 1)

    # 3 ─ no row wired = the documented per-event off switch, and it must not touch mail.
    print("\n3. No wiring row = intentional skip")
    async with _Harness([]) as h:
        res = await svc.notify_schedule(_event())
    wa = res.get("whatsapp") or {}
    check("nothing sent", len(h.whatsapps) == 0)
    check("both sides counted as skipped", wa.get("skipped") == 2, str(wa))
    check("mail unaffected", len(h.mails) == 2)

    # 4 ─ an inactive row is the admin UI's off switch for one notification.
    print("\n4. Inactive row is honoured")
    async with _Harness([_wiring(ACTIVITY, "company", active=False),
                         _wiring(ACTIVITY, "staff")]) as h:
        await svc.notify_schedule(_event())
    check("only the active side sends", len(h.whatsapps) == 1, f"{len(h.whatsapps)} send(s)")

    # 5 ─ '*' is the catch-all when no activity-specific row exists.
    print("\n5. '*' catch-all applies when no activity row exists")
    async with _Harness([_wiring("*", "company")]) as h:
        await svc.notify_schedule(_event())
    check("catch-all row used", len(h.whatsapps) == 1, f"{len(h.whatsapps)} send(s)")

    # 6 ─ the Cloud API reports failure by RETURNING False, not by raising.
    print("\n6. A rejected send is counted as failed, not sent")
    async with _Harness([_wiring(ACTIVITY, "company")], wa_result=False) as h:
        res = await svc.notify_schedule(_event())
    wa = res.get("whatsapp") or {}
    check("attempt was made", len(h.whatsapps) == 1)
    check("reported as failed", wa.get("failed") == 1 and wa.get("sent") == 0, str(wa))

    # 7 ─ a recipient with no mobile is reported, not silently dropped.
    print("\n7. Recipient without a mobile number is reported")
    async with _Harness(
        [_wiring(ACTIVITY, "company")],
        learners=[{"_id": DOER_ID, "full_name": "Priya Doer", "email": "priya@acme.test"},
                  {"_id": DOER2_ID, "full_name": "Amit Doer", "email": "amit@acme.test",
                   "mobile": "9812345678"}],
        staff=[],
    ) as h:
        res = await svc.notify_schedule(_event(assigned_member_ids=[str(DOER_ID), str(DOER2_ID)],
                                               coach_ids=[]))
    wa = res.get("whatsapp") or {}
    check("only the reachable doer is messaged", len(h.whatsapps) == 1, f"{len(h.whatsapps)} send(s)")
    check("missing number counted", wa.get("no_phone") == 1 and wa.get("sent") == 1, str(wa))

    # 8 ─ the reminder path is untouched: it calls send_whatsapp directly, never _dispatch.
    print("\n8. Reminder path unchanged (no double-send from _dispatch)")
    async with _Harness([_wiring(ACTIVITY, "company", event="reminder")]) as h:
        rem = await svc.send_whatsapp(_event(), "reminder", "company")
        sched = await svc.notify_schedule(_event())
    check("reminder row sends on the reminder path", rem.get("sent") == 1, str(rem))
    check("schedule does not fire the reminder row",
          (sched.get("whatsapp") or {}).get("sent") == 0,
          str(sched.get("whatsapp")))
    check("no mail sent by the reminder path", len(h.mails) == 2, f"{len(h.mails)} mail(s)")

    # 9 ─ header/button templates keep their explicit components array.
    print("\n9. Header/button variables still produce a components override")
    async with _Harness([_wiring(ACTIVITY, "company", header_variables=["Company_Name"],
                                 button_variables=[{"index": 1, "field": "Schedule_ID"}])]) as h:
        await svc.notify_schedule(_event())
    comps = (h.whatsapps[0] if h.whatsapps else {}).get("components") or []
    kinds = [c.get("type") for c in comps]
    check("header, body and button components built", kinds == ["header", "body", "button"], str(kinds))
    check("button keeps its real template index",
          any(c.get("type") == "button" and c.get("index") == "1" for c in comps))

    # 10 ─ Meta names are lowercase-only; a row typed in title case must still reach the template.
    print("\n10. Template name normalised to Meta's lowercase-only rule")
    async with _Harness([_wiring(ACTIVITY, "company", meta_template_name="Accountability",
                                 name="Accountability")]) as h:
        await svc.notify_schedule(_event())
    check("'Accountability' sent as 'accountability'",
          (h.whatsapps[0] if h.whatsapps else {}).get("template") == "accountability",
          str((h.whatsapps[0] if h.whatsapps else {}).get("template")))


# ─────────────────────────────────────────────────────────────
# Live diagnosis
# ─────────────────────────────────────────────────────────────
async def _load_event(event_id: str):
    from app.db.mongodb import get_collection
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS

    try:
        oid = ObjectId(event_id)
    except Exception:
        print(f"{BAD} --event-id is not a valid ObjectId")
        return None, None
    for name in CALENDAR_COLLECTIONS + ["calendar_events"]:
        doc = await get_collection(name).find_one({"_id": oid})
        if doc:
            return doc, name
    return None, None


async def live(activity: str, event_kind: str, sides, event_id: str, do_send: bool) -> None:
    from app.db.mongodb import connect_to_mongo, get_collection
    from app.models.tpms import (COLL_META_TEMPLATES, COLL_WHATSAPP_TEMPLATES,
                                 META_STATUS_APPROVED, TPMS_NOTIFICATIONS_ENABLED)
    from app.services.meta_whatsapp_service import approved_template_names, config_status
    from app.services.tpms_notify_service import (_recipients, get_whatsapp_template,
                                                  normalize_phone, send_whatsapp)

    await connect_to_mongo()
    print(f"\n=== TPMS WhatsApp live check — '{activity}' / {event_kind} ===\n")

    # 1 ─ credentials
    cfg = config_status()
    print("1. Credentials")
    check("sending configured (WHATSAPP_PHONE_NUMBER_ID + ACCESS_TOKEN)", cfg["sending_configured"])
    check("template management configured (WHATSAPP_BUSINESS_ACCOUNT_ID)", cfg["configured"],
          f"waba={cfg['waba_id']}")
    check("TPMS notifications master switch on", bool(TPMS_NOTIFICATIONS_ENABLED))

    # 2 ─ what Meta itself says is approved
    print("\n2. Meta template library")
    remote = await approved_template_names()
    if remote is None:
        print(f"{WARN} could not read the WABA (not configured or Graph unreachable) —"
              " approval could not be verified")
    else:
        print(f"{DOT} Meta reports {len(remote)} approved template(s)")

    local_approved = {d.get("name") for d in await get_collection(COLL_META_TEMPLATES)
                      .find({"status": META_STATUS_APPROVED}).to_list(500)}
    print(f"{DOT} local library holds {len(local_approved)} APPROVED row(s)")
    if remote:
        missing = {n for n in remote if n not in local_approved}
        if missing:
            print(f"{WARN} approved at Meta but absent/not-approved locally: "
                  f"{', '.join(sorted(missing)[:10])}")
            print(f"{DOT} run POST /tpms/meta-templates/sync (Sync from Meta) to import them —"
                  " the wiring screen only offers locally-APPROVED templates")

    # 3 ─ wiring rows
    print("\n3. Wiring rows (activity x side x event)")
    rows = await get_collection(COLL_WHATSAPP_TEMPLATES).find({}).to_list(500)
    mine = [r for r in rows if str(r.get("activity") or "").strip().lower()
            in {activity.strip().lower(), "*"}]
    if not mine:
        print(f"{WARN} no row for '{activity}' or '*' in any event/side")
    for r in sorted(mine, key=lambda d: (d.get("event") or "", d.get("side") or "")):
        state = "active" if r.get("active", True) else "INACTIVE"
        print(f"{DOT} {r.get('activity')} / {r.get('side')} / {r.get('event')} "
              f"-> {r.get('meta_template_name')} [{state}]")

    for side in sides:
        print(f"\n   resolving {side}/{event_kind}:")
        tpl = await get_whatsapp_template(activity, event_kind, side)
        if not check(f"a template resolves for {side}/{event_kind}", bool(tpl)):
            print(f"{DOT} wire one under TPMS > Templates > WhatsApp, event '{event_kind}'")
            continue
        raw = str(tpl.get("meta_template_name") or tpl.get("name") or "").strip()
        name = raw.lower()   # what the send layer will actually ask Meta for
        print(f"{DOT} matched row activity='{tpl.get('activity')}' -> {raw} "
              f"({tpl.get('language') or 'en'}), variables={tpl.get('variables') or []}")
        if raw != name:
            print(f"{DOT} row name is not lowercase; sent as '{name}' (Meta names are lowercase-only)")
        check(f"'{name}' is APPROVED locally", name in {str(n or '').lower() for n in local_approved})
        if remote is not None:
            check(f"'{name}' is APPROVED at Meta", name in {str(n or '').lower() for n in remote})
        wanted = len(tpl.get("variables") or [])
        meta_row = await get_collection(COLL_META_TEMPLATES).find_one(
            {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
        if meta_row:
            slots = len(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", meta_row.get("body") or "")))
            check(f"mapped variables match the template's {slots} body slot(s)",
                  wanted == slots, f"{wanted} mapped")

    # 4 ─ recipients (needs a real event)
    if not event_id:
        print(f"\n4. Recipients — pass --event-id <calendar event id> to check phone numbers")
        return
    print("\n4. Recipients")
    event, coll = await _load_event(event_id)
    if not check("event found", bool(event), coll or "not in any calendar collection"):
        return
    print(f"{DOT} '{event.get('title')}' activity='{event.get('activity')}' in {coll}")
    check("event activity matches the one being checked",
          str(event.get("activity") or "").strip().lower() == activity.strip().lower(),
          str(event.get("activity")))
    people = await _recipients(event)
    for side in sides:
        crowd = people.get(side) or []
        reachable = [p for p in crowd if normalize_phone(p.get("phone"))]
        check(f"{side}: at least one reachable number",
              bool(reachable), f"{len(reachable)}/{len(crowd)} recipient(s)")
        for p in crowd:
            norm = normalize_phone(p.get("phone"))
            print(f"{DOT} {side}: {p.get('name')} <{p.get('email')}> "
                  f"{norm or 'NO MOBILE ON RECORD'}")

    # 5 ─ real send
    if do_send:
        print("\n5. Live send")
        for side in sides:
            result = await send_whatsapp(event, event_kind, side)
            check(f"{side}: delivered", (result.get("sent") or 0) > 0, str(result))
    else:
        print("\n5. Live send skipped (pass --send to deliver for real)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the TPMS WhatsApp notification chain")
    ap.add_argument("--self-test", action="store_true",
                    help="run the offline end-to-end test (no DB, no Meta)")
    ap.add_argument("--activity", default="Accountability & Ownership Rating")
    ap.add_argument("--event", default="schedule",
                    help="schedule | reminder | reschedule | cancel | completed")
    ap.add_argument("--side", default="both", choices=["company", "staff", "both"])
    ap.add_argument("--event-id", default="", help="a real calendar event id, to check recipients")
    ap.add_argument("--send", action="store_true", help="actually deliver (live mode only)")
    args = ap.parse_args()

    sides = ["company", "staff"] if args.side == "both" else [args.side]
    if args.self_test:
        asyncio.run(self_test())
    else:
        asyncio.run(live(args.activity, args.event, sides, args.event_id, args.send))

    failed = _results.count(False)
    print(f"\n{'-' * 60}\n{len(_results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
