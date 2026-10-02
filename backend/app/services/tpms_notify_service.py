"""
TPMS ▸ notification service.

Port of the Apps Script mail layer (`copy_of calender/code.js`):
  • getTemplate_          (:955)  → get_template()
  • fill_ / buildMap_     (:1082) → fill() / build_map()
  • sendScheduleEmails_   (:1141) → notify_schedule()
  • sendStatusEmails_     (:970)  → notify_status()
  • defaultBody_          (:1090) → _default_body()

Templates come from `tpms_mail_templates`, keyed (activity × side × event) — the shape of
the sheet's `Templates` tab, which carried 11 columns per activity:
    Staff|Company  ×  schedules | reminder | status_reschedule | status_cancel | status_completed
A row with activity "*" is the catch-all. When no template matches, the ported default
body is used, exactly as the source falls back.

Delivery reuses the ERP's existing notification service (SMTP + logging), so TPMS adds no
second mail stack. Every send is logged with a `tpms_*` slug so the Logs Report can
separate TPMS traffic from the rest of the ERP.
"""
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.services.whatsapp_components import build_send_components, resolve_params
from app.models.tpms import COLL_MAIL_TEMPLATES, TPMS_NOTIFICATIONS_ENABLED

logger = logging.getLogger(__name__)

SIDE_STAFF = "staff"
SIDE_COMPANY = "company"

EVENT_SCHEDULE = "schedule"
EVENT_REMINDER = "reminder"
EVENT_RESCHEDULE = "reschedule"
EVENT_CANCEL = "cancel"
EVENT_COMPLETED = "completed"
# Fired after a review form is submitted — the HOD/MD summary and the per-employee scorecard.
EVENT_FORM_SUMMARY = "form_summary"
EVENT_FORM_SCORECARD = "form_scorecard"

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def fill(template: str, mapping: Dict[str, str]) -> str:
    """Port of fill_ (code.js:1082). Unknown placeholders are left untouched, which is
    what the source does — a missing value shows as `{{Name}}` rather than blanking."""
    def repl(m):
        key = m.group(1)
        return str(mapping[key]) if key in mapping and mapping[key] is not None else m.group(0)
    return _PLACEHOLDER.sub(repl, str(template or ""))


async def _resolve_names(ids, collection: str) -> str:
    """Comma-joined display names for a list of user ids from a collection."""
    from bson import ObjectId
    oids = []
    for i in ids or []:
        try:
            oids.append(ObjectId(str(i)))
        except Exception:
            pass
    if not oids:
        return ""
    names = []
    for u in await get_collection(collection).find({"_id": {"$in": oids}}).to_list(200):
        n = (u.get("full_name")
             or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
             or u.get("email") or "")
        if n:
            names.append(n)
    return ", ".join(names)


# Spec §11 — a form may set `noCid` to suppress the company parameter on its deep link.
# Keyed by form_type; add an entry to opt a form out.
FORM_NO_CID = {
    # "implementation_feedback": True,
}


def _form_link(event: dict) -> str:
    """Fallback value for {{Form_Link}} when no per-recipient link applies.

    The in-app Forms UI this used to deep-link into has been removed: a form is now opened
    only through a unique, per-assignee token URL, which cannot be derived from the event alone
    (it is bound to one respondent). `_dispatch` therefore overrides {{Form_Link}} for each
    company-side recipient with THEIR link — see `_recipient_form_links`. This function is what
    remains for anyone the override cannot resolve a link for, and it returns an empty string
    rather than a URL that would 404.
    """
    return ""


async def _recipient_form_links(event: dict, actor: Optional[dict] = None) -> Dict[str, List[dict]]:
    """respondent_id → the form links that person owes, for a form-scored activity.

    Creating the assignments here is deliberate: it puts link generation on exactly the same
    path as the mail that carries it, so a link can never be minted without a delivery attempt
    being logged, and the schedule mail keeps its existing template, trigger and recipients —
    only the VALUE of {{Form_Link}} changes, from a shared in-app URL to a per-person token URL.

    A list, not a single link: one activity can carry two forms (Accountability & Ownership
    maps to both), and each is a separate assignment with its own link, so the recipient must
    receive both to be able to complete their work.

    Returns ({}, {}) for every non-form activity, which leaves the rest of the TPMS calendar
    exactly as it was.

    The second return value is the respondents themselves, in _recipients() shape. It exists
    because the two audiences are NOT the same set: the schedule mail goes to the activity's
    assigned members (the doers), while a form is owed by its audience — HODs for the rating
    forms, the MD for the feedback checklist. When the assigned doer is not an HOD/MD the link
    is issued to someone who was never a recipient, so the mail that went out carried no link
    and the person who owed the form got nothing at all. _dispatch unions them in.
    """
    try:
        from app.services.tpms_form_link_service import assignments_for_event
        rows = await assignments_for_event(event, actor)
    except Exception as e:
        logger.error(f"TPMS form link generation failed for '{event.get('activity')}': {e}")
        return {}, {}
    from app.services.tpms_form_link_service import configured_base_url, link_on

    # Rebuilt from the token against the CURRENT Application URL rather than read from the
    # `link` frozen at creation — an assignment minted while the URL was wrong is still mailed
    # with a working address once Settings is corrected.
    base = await configured_base_url()
    links: Dict[str, List[dict]] = {}
    respondents: Dict[str, dict] = {}
    for row in rows:
        if not row.get("token"):
            continue
        rid = str(row.get("respondent_id"))
        links.setdefault(rid, []).append({
            "link": link_on(base, row["token"]),
            "title": row.get("form_title") or row.get("form_type") or "Form",
        })
        if row.get("respondent_email"):
            respondents.setdefault(rid, {
                "id": rid,
                "email": row["respondent_email"],
                "name": row.get("respondent_name") or "",
                "phone": "",
            })
    return links, respondents


# ─────────────────────────────────────────────────────────────
# Form links in TPMS mail — staged rollout
#
# STAGE 1 (current): a TPMS scheduled mail must carry NO form link of any kind. Three separate
# sources have to be covered, only one of which lives in this repo:
#   • a legacy Google Form / forms.gle URL hardcoded into an admin's stored template body
#     (tpms_mail_templates lives in the database, so it cannot be fixed in code);
#   • a link to the removed in-app Forms UI (/tpms/forms/...);
#   • the code-generated /f/<token> link this service injects.
# Assignments and their tokens are STILL created and logged, so TPMS ▸ Form Mail Logs keeps
# working and stage 2 has its links ready — they are simply not put into the mail.
#
# STAGE 2: flip SEND_FORM_LINKS to True. The generated /f/<token> link is injected and delivered
# again; the Google / legacy patterns stay stripped permanently.
#
# Stored templates are never rewritten — the scrub runs on the RENDERED copy at send time, so an
# admin's template is left exactly as they authored it and the change is reversible.
# ─────────────────────────────────────────────────────────────
SEND_FORM_LINKS = True

# Never mailed, at any stage.
_FORBIDDEN_LINK_PATTERNS = (
    "forms.gle",
    "docs.google.com/forms",
    "google.com/forms",
    "/tpms/forms",          # the removed in-app Forms UI
)

_ANCHOR_RE = re.compile(r"<a(?:\s[^>]*)?>.*?</a>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
# A generated form link sitting in the body as plain text — what a template that writes a bare
# {{Form_Link}} (rather than <a href="{{Form_Link}}">) leaves behind once it is filled.
_BARE_FORM_URL_RE = re.compile(r"https?://\S*/f/[A-Za-z0-9_\-]+")
# {{Form_Link}} wired into the template's OWN anchor, e.g. <a href="{{Form_Link}}">Fill it</a>.
_FORM_LINK_AS_HREF_RE = re.compile(
    r"""href\s*=\s*["']\s*\{\{\s*Form_Link\s*\}\}\s*["']""", re.IGNORECASE)


def _template_wires_own_button(body_tpl: str) -> bool:
    """True when the template builds its own link around {{Form_Link}}.

    Such a template wants the raw URL and supplies its own label. A template that merely drops
    {{Form_Link}} into the body as text wants a link it does not have to build — and gets the
    labelled block, placed exactly where the placeholder sits.
    """
    return bool(_FORM_LINK_AS_HREF_RE.search(body_tpl or ""))


def _is_form_link(url: str) -> bool:
    """Whether an anchor's href is a form link that must not go out."""
    u = (url or "").strip().lower()
    # An empty href is what {{Form_Link}} leaves behind once it resolves to nothing — a dead
    # "fill the form" button. TPMS mail has no other placeholder that can render empty into an
    # href (see build_map), so this removes the broken control, not the text around it.
    if not u:
        return True
    if any(pattern in u for pattern in _FORBIDDEN_LINK_PATTERNS):
        return True
    # Our own generated link, while stage 1 stands.
    return not SEND_FORM_LINKS and "/f/" in u


def _strip_form_links(html: str) -> str:
    """Remove every form link from a RENDERED mail body."""
    def drop_form_anchors(match):
        anchor_html = match.group(0)
        href = _HREF_RE.search(anchor_html)
        return "" if _is_form_link(href.group(1) if href else "") else anchor_html

    body = _ANCHOR_RE.sub(drop_form_anchors, html or "")
    # Bare URLs pasted into a body as plain text, which no anchor rule would catch.
    for pattern in _FORBIDDEN_LINK_PATTERNS:
        body = re.sub(r"https?://\S*" + re.escape(pattern) + r"\S*", "", body, flags=re.IGNORECASE)
    return body


def _link_block(entries: List[dict]) -> str:
    """A minimal HTML block listing form links, appended to a rendered mail body.

    This is NOT a template and does not touch the template system: admins keep authoring the
    schedule mail exactly as before. It is the guarantee that the recipient can actually reach
    their form — a template that never referenced {{Form_Link}} would otherwise deliver no link
    at all, and an activity with two forms would deliver only the first.
    """
    rows = "".join(
        f'<p style="margin:6px 0"><a href="{e["link"]}" '
        f'style="color:#4f46e5;font-weight:700">{e["title"]}</a></p>'
        for e in entries
    )
    return (
        '<div style="margin-top:18px;padding:14px 16px;border:1px solid #e5e7eb;'
        'border-radius:10px;background:#fafafa">'
        '<p style="margin:0 0 8px;font-weight:700;font-size:13px">Your form link'
        f'{"s" if len(entries) > 1 else ""}</p>{rows}'
        '<p style="margin:8px 0 0;font-size:11px;color:#6b7280">'
        'This link is personal to you and can be submitted once.</p></div>'
    )


def _linked_hrefs(html: str) -> set:
    """Every URL the rendered body exposes as a real, clickable anchor."""
    return {(m.group(1) or "").strip() for m in _HREF_RE.finditer(html or "")}


def _strip_bare_form_urls(html: str) -> str:
    """Drop naked form URLs from the body, leaving anchors untouched.

    A template that writes `{{Form_Link}}` on its own — as the Accountability & Ownership one
    does — renders the raw https://…/f/<token> string into the mail as text. Some clients
    auto-link it, most show an unlabelled URL, and the recipient cannot tell WHICH form it
    opens. The link is not lost: _ensure_links_delivered puts it back below, named after the
    form it belongs to. Only text outside <a>…</a> is cleaned, so a template that wraps the
    placeholder in its own button keeps that button exactly as authored.
    """
    body = html or ""
    out, last = [], 0
    for m in _ANCHOR_RE.finditer(body):
        out.append(_BARE_FORM_URL_RE.sub("", body[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_BARE_FORM_URL_RE.sub("", body[last:]))
    return "".join(out)


def _ensure_links_delivered(html: str, entries: List[dict]) -> str:
    """Append every form link the rendered body does not already offer as a labelled anchor.

    A template that uses <a href="{{Form_Link}}">…</a> already carries that link, so nothing is
    appended for it and the mail looks exactly as the admin designed it. Anything else is added
    below, so "the assignee receives the email with their unique link" cannot depend on how the
    template happens to be written.

    Membership is judged on ANCHOR HREFS, not on the raw text. "Accountability & Ownership
    Rating" carries two forms and the stored template has a single bare {{Form_Link}}: the
    accountability URL was therefore present as plain text, counted as already delivered, and
    only the ownership link got a label — which is the reported "no link for ownership form in
    template, only accountability". Judged by href, neither is linked, so both are appended,
    each named after its own form.
    """
    linked = _linked_hrefs(html)
    missing = [e for e in entries if e["link"] not in linked]
    return html + _link_block(missing) if missing else html


async def build_map(event: dict, extra: Optional[dict] = None) -> Dict[str, str]:
    """Placeholder values available to every template (buildMap_, code.js:1084)."""
    start = str(event.get("start") or "")
    meta = event.get("activity_meta") or {}
    mapping = {
        "Title": event.get("title") or "",
        "Activity": event.get("activity") or "",
        "Company_Name": event.get("company_name") or "",
        "Company_ID": str(event.get("company_id") or ""),
        "Event_Date": start[:10],
        "Event_Time": start[11:16],
        "Status": event.get("tpms_status") or "",
        "Departments": ", ".join(event.get("assigned_departments") or []),
        "Comment": event.get("additional_details") or "",
        "Schedule_ID": str(event.get("_id") or ""),
        # Previously-unfilled placeholders (rendered as literal {{…}} before this fix).
        "Staff_Assigner": await _resolve_names(event.get("coach_ids"), "staff"),
        "Company_Assigners": await _resolve_names(event.get("assigned_member_ids"), "learners"),
        "Session_Type": (str(meta.get("scope") or "").upper() or (event.get("activity") or "")),
        # The stored templates read "A new {{Calendar_Type}} has been scheduled for …", so this
        # is the NOUN for the calendar entry, not a code. It was never in this mapping, and
        # fill() leaves an unknown placeholder untouched by design — so 22 templates delivered
        # the literal text "{{Calendar_Type}}" to recipients. Anything carrying an `activity`
        # is a TPMS activity; any other calendar row keeps its own word.
        "Calendar_Type": "activity" if event.get("activity") else (event.get("type") or "event"),
        "Form_Link": _form_link(event),
        # Overridden per-recipient by _dispatch and by the reminder sender, which are the only
        # places a personal link exists. They default to EMPTY rather than being absent: fill()
        # leaves an unknown placeholder untouched, so a template written with {{Form_Links}}
        # delivered the literal text "{{Form_Links}}" to the recipient.
        "Form_Link_2": "",
        "Form_Links": "",
    }
    if extra:
        mapping.update({k: v for k, v in extra.items() if v is not None})
    return mapping


def log_context(event: dict) -> Dict[str, str]:
    """Spec §14 — the delivery log is joined to its activity so the Logs Report can show
    Activity / Company / Date next to the send result. Recorded at write time rather than
    resolved afterwards, because the log has no other route back to the schedule."""
    return {
        "event_id": str(event.get("_id") or ""),
        "activity": event.get("activity") or "",
        "company_id": str(event.get("company_id") or ""),
        "company_name": event.get("company_name") or "",
        "event_date": str(event.get("start") or "")[:10],
    }


async def get_template(activity: str, event_kind: str, side: str) -> Optional[dict]:
    """Most specific template wins: exact activity, then the '*' catch-all."""
    coll = get_collection(COLL_MAIL_TEMPLATES)
    for name in (activity, "*"):
        if not name:
            continue
        doc = await coll.find_one({"activity": name, "side": side,
                                   "event": event_kind, "active": {"$ne": False}})
        if doc:
            return doc
    return None


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:3px 12px 3px 0;color:#64748b">{label}</td>'
            f'<td style="padding:3px 0">{value}</td></tr>')


def _default_body(mapping: Dict[str, str], heading: str) -> str:
    """Port of defaultBody_ (code.js:1090)."""
    return (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        f'<h3 style="margin:0 0 10px">{heading}: {mapping.get("Title", "")}</h3>'
        '<table style="border-collapse:collapse;font-size:14px">'
        + _row("Activity", f'<b>{mapping.get("Activity", "")}</b>')
        + _row("Company", mapping.get("Company_Name", ""))
        + _row("Scheduled", f'{mapping.get("Event_Date", "")} {mapping.get("Event_Time", "")}')
        + (_row("Departments", mapping.get("Departments", "")) if mapping.get("Departments") else "")
        + (_row("Note", mapping.get("Comment", "")) if mapping.get("Comment") else "")
        + "</table></div>"
    )


async def _recipients(event: dict) -> Dict[str, List[dict]]:
    """Company side = the doers. Staff side = the assigned internal users."""
    from bson import ObjectId

    def name_of(u):
        return (u.get("full_name")
                or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                or u.get("email") or "")

    def to_oids(ids):
        out = []
        for i in ids or []:
            try:
                out.append(ObjectId(str(i)))
            except Exception:
                pass
        return out

    def phone_of(u):
        return u.get("mobile") or u.get("phone") or u.get("whatsapp") or ""

    company, staff = [], []
    member_oids = to_oids(event.get("assigned_member_ids"))
    if member_oids:
        for u in await get_collection("learners").find({"_id": {"$in": member_oids}}).to_list(500):
            if u.get("email"):
                company.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"]), "phone": phone_of(u)})
    staff_oids = to_oids(event.get("coach_ids"))
    if staff_oids:
        for u in await get_collection("staff").find({"_id": {"$in": staff_oids}}).to_list(500):
            if u.get("email"):
                staff.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"]), "phone": phone_of(u)})
    return {SIDE_COMPANY: company, SIDE_STAFF: staff}


# ─────────────────────────────────────────────────────────────
# H1 — WhatsApp send layer (Meta templates). Sending is gated by the TPMS switch, so this is
# fully dormant while notifications are off; the resolution/normalisation logic is ready.
# ─────────────────────────────────────────────────────────────
def normalize_phone(raw: str) -> str:
    """Spec §11 — strip non-digits, strip leading zeros, then prefix the country code when
    exactly 10 digits remain. The zero-strip is what makes a locally-dialled "09876543210"
    resolve to the same number as "9876543210"."""
    digits = re.sub(r"\D", "", str(raw or ""))
    digits = digits.lstrip("0")
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "91" + digits
    return digits


# Spec §11 — waGuessField_: when a template variable isn't a known placeholder name, infer
# the intended field from the words in it. Ordered most-specific first, because "event date"
# must match the date rule before the generic "event" one would ever apply.
_WA_GUESS_RULES = [
    (("date", "day", "schedule"), "Event_Date"),
    (("time", "hour"), "Event_Time"),
    (("activity", "task"), "Activity"),
    (("company", "client", "org"), "Company_Name"),
    (("title", "subject", "name of"), "Title"),
    (("status", "state"), "Status"),
    (("department", "dept"), "Departments"),
    (("staff", "om", "smops"), "Staff_Assigner"),
    (("doer", "assigner", "member", "employee"), "Company_Assigners"),
    (("link", "url", "form"), "Form_Link"),
    (("comment", "note", "remark"), "Comment"),
    (("recipient", "to"), "Recipient_Name"),
]


def wa_guess_field(variable: str, mapping: Dict[str, str]) -> str:
    """Best-effort value for an unmapped template variable. Returns "" when nothing fits,
    which leaves the caller's "-" guard in charge (Meta rejects blank params)."""
    needle = str(variable or "").replace("_", " ").lower()
    if not needle:
        return ""
    for words, field in _WA_GUESS_RULES:
        if any(w in needle for w in words):
            value = mapping.get(field)
            if value:
                return str(value)
    return ""


async def get_whatsapp_template(activity: str, event_kind: str, side: str) -> Optional[dict]:
    """Most-specific WhatsApp template wins: the exact activity, the same name ignoring case
    and surrounding space, then the '*' catch-all. Returns None when no row exists — the
    business's per-event on/off switch ("no template row = skip").

    The tolerant middle step matters because the wiring row stores the activity as free text
    while the calendar event carries the canonical name: a row saved as "accountability &
    ownership rating" (or with a trailing space) would otherwise never match
    "Accountability & Ownership Rating", and the send would skip silently."""
    from app.models.tpms import COLL_WHATSAPP_TEMPLATES
    coll = get_collection(COLL_WHATSAPP_TEMPLATES)
    base = {"side": side, "event": event_kind, "active": {"$ne": False}}
    name = str(activity or "").strip()
    if name:
        doc = await coll.find_one({**base, "activity": name})
        if doc:
            return doc
        doc = await coll.find_one(
            {**base, "activity": {"$regex": rf"^\s*{re.escape(name)}\s*$", "$options": "i"}})
        if doc:
            return doc
    return await coll.find_one({**base, "activity": "*"})


def _resolve_params(keys, mapping: Dict[str, str]) -> list:
    """Data-field names → the values Meta will substitute. A key that doesn't name a known
    field falls back to the heuristic guesser (spec §11); "-" is the last resort because Meta
    rejects a blank parameter outright."""
    return resolve_params(keys, mapping, wa_guess_field)


def _build_send_components(tpl: dict, mapping: Dict[str, str], body_params: list) -> Optional[list]:
    """The Cloud API `components` array for one send — see services/whatsapp_components.

    The structure is shared with Task & Delegation and the Checklist repeat-task triggers, so it
    lives in one place; this wrapper only supplies the TPMS wiring row's own key names and the
    spec §11 guesser."""
    return build_send_components(
        body_params,
        header_keys=tpl.get("header_variables"),
        button_keys=tpl.get("button_variables"),
        mapping=mapping,
        guess=wa_guess_field,
    )


async def send_whatsapp(event: dict, event_kind: str, side: str) -> dict:
    """Resolve a Meta template, map ordered positional params from build_map, normalise
    phones, and send. No template row → skip (returns skipped=1). Gated by the TPMS switch."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0, "failed": 0, "skipped": 0, "no_phone": 0}
    activity = event.get("activity") or ""
    tpl = await get_whatsapp_template(activity, event_kind, side)
    if not tpl:
        # Not an error — but the single most common reason a WhatsApp notification "never
        # arrives", so say which key was looked up instead of returning in silence.
        logger.info("TPMS WhatsApp skip: no active template wired for "
                    f"'{activity}' / {side} / {event_kind}")
        return {"sent": 0, "failed": 0, "skipped": 1, "no_phone": 0}
    from app.services.notification_service import send_whatsapp_template

    mapping = await build_map(event)
    # Meta requires ORDERED params; the template row stores the variable order.
    params = _resolve_params(tpl.get("variables") or [], mapping)
    components = _build_send_components(tpl, mapping, params)
    people = await _recipients(event)
    recipients = people.get(side) or []
    # Meta template names are lowercase-only (validate_template enforces ^[a-z0-9_]+$), but the
    # wiring row holds whatever was typed. Sending "Accountability" for the approved
    # "accountability" is rejected as a non-existent template, per recipient, in the log only —
    # so normalise here and let rows written before this keep working without a data migration.
    tpl_name = str(tpl.get("meta_template_name") or tpl.get("name") or "").strip().lower()
    # Same Activity / Company context the mail path records, so the Logs Report can fill its
    # ACTIVITY and COMPANY columns for a WhatsApp row instead of showing a dash.
    context = log_context(event)
    sent = failed = no_phone = 0
    for person in recipients:
        phone = normalize_phone(person.get("phone"))
        if not phone:
            no_phone += 1
            continue
        try:
            ok = await send_whatsapp_template(phone, tpl_name,
                                              tpl.get("language") or "en", params,
                                              user_id=person.get("id"),
                                              slug=f"tpms_wa_{event_kind}_{side}",
                                              components=components, meta=context)
        except Exception as e:
            ok = False
            logger.error(f"TPMS WhatsApp to {phone} failed: {e}")
        # The send layer REPORTS failure by returning False — missing credentials, a template
        # Meta does not consider approved, a number not on WhatsApp — and only raises on an
        # unexpected error. Counting that as sent is what made this look delivered when
        # nothing arrived; the Cloud API's own error is already in the notification log.
        if ok:
            sent += 1
        else:
            failed += 1
    if no_phone:
        logger.warning(f"TPMS WhatsApp '{tpl_name}' ({side}/{event_kind}): {no_phone} of "
                       f"{len(recipients)} recipient(s) have no usable mobile number")
    return {"sent": sent, "failed": failed, "skipped": 0, "no_phone": no_phone}


async def _record_form_link_delivery(event: dict, person: dict, status: str,
                                     error: Optional[str]) -> None:
    """Stamp the delivery outcome onto every form assignment this recipient holds for the
    period, so TPMS ▸ Form Mail Logs shows whether the link actually reached them. Failures here
    are swallowed: the mail already went out (or already failed) and the log must never be the
    thing that breaks scheduling."""
    try:
        from app.services.tpms_form_link_service import (
            ASSIGNMENT_COLLECTION, mark_email_result,
        )
        period = str(event.get("start") or "")[:7]
        rows = await get_collection(ASSIGNMENT_COLLECTION).find({
            "company_id": str(event.get("company_id") or ""),
            "period": period,
            "respondent_id": str(person.get("id") or ""),
            "activity": event.get("activity") or "",
        }).to_list(20)
        for row in rows:
            await mark_email_result(row["_id"], status, error)
    except Exception as e:
        logger.error(f"TPMS form link delivery log failed: {e}")


async def _dispatch(event: dict, event_kind: str, heading: str,
                    extra: Optional[dict] = None) -> dict:
    """Resolve a template per side, fill it and send — mail first, then WhatsApp for the sides
    that have a template wired. Never raises: a delivery failure must not roll back the action
    that triggered it (the source wraps every send too)."""
    # TPMS notifications globally disabled → send nothing (schedule/reschedule/cancel/complete).
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0, "failed": 0}
    from app.services.notification_service import send_email_notification

    mapping = await build_map(event, extra)
    people = await _recipients(event)
    activity = event.get("activity") or ""
    sent = failed = 0

    # Per-recipient form links. Generated only when this activity is form-scored, and only on
    # the schedule mail — a reminder or cancellation must not mint fresh links, and the existing
    # reminder / reschedule / cancel / completed flows are untouched by this.
    form_links: Dict[str, List[dict]] = {}
    form_respondents: Dict[str, dict] = {}
    if event_kind == EVENT_SCHEDULE:
        form_links, form_respondents = await _recipient_form_links(event, (extra or {}).get("actor"))
        # A respondent who owes a form but was not on the activity's assignee list would
        # otherwise never be mailed, while the doer who WAS mailed got a body with no link —
        # the link and the mail went to different people. Add them to the company side so each
        # person receives the mail carrying THEIR OWN link. Links are personal, so this only
        # ever adds the person the link belongs to; nobody sees anyone else's.
        if form_respondents:
            company = people.get(SIDE_COMPANY) or []
            known = {str(p.get("id") or "") for p in company}
            people[SIDE_COMPANY] = company + [r for rid, r in form_respondents.items() if rid not in known]

    for side in (SIDE_STAFF, SIDE_COMPANY):
        recipients = people.get(side) or []
        if not recipients:
            continue
        tpl = await get_template(activity, event_kind, side)
        # Spec parity (defaultBody_): when no Active template with a body is configured for this
        # (activity, side), fall back to a branded default body + generic subject so the
        # notification still goes out — instead of silently sending nothing.
        if tpl and tpl.get("body_html"):
            subject_tpl = tpl.get("subject") or f"[{heading}] {{{{Title}}}} – {{{{Activity}}}}"
            body_tpl = tpl.get("body_html")
        else:
            subject_tpl = f"[{heading}] {{{{Title}}}} – {{{{Activity}}}}"
            body_tpl = _default_body(mapping, heading)

        for person in recipients:
            person_map = {**mapping, "Recipient_Name": person["name"]}
            # This recipient's own secure form links, when they are one of the form's
            # respondents. Staff-side recipients and non-form activities keep the empty default.
            my_links = form_links.get(str(person.get("id") or "")) or []
            if my_links and SEND_FORM_LINKS:
                # Where the links LAND matters as much as whether they are sent. A template that
                # writes a bare {{Form_Link}} gets the labelled block substituted at that exact
                # spot — inside the body, above the sign-off. Appending it after the template
                # instead put it below the "Sparsh Magic Automation" footer, where the mail looks
                # finished: on a phone the links were off-screen and read as missing.
                # A template that wires its own <a href="{{Form_Link}}"> still gets the raw URL.
                person_map["Form_Link"] = (my_links[0]["link"]
                                           if _template_wires_own_button(body_tpl)
                                           else _link_block(my_links))
                # Second form's link — e.g. "Accountability & Ownership Rating" carries TWO forms
                # (accountability + ownership), so each HOD needs both. Empty when there is only one.
                person_map["Form_Link_2"] = my_links[1]["link"] if len(my_links) > 1 else ""
                # A ready-made HTML block of ALL of this recipient's links; drop it anywhere.
                person_map["Form_Links"] = _link_block(my_links)
            subject = fill(subject_tpl, person_map)
            html = fill(body_tpl, person_map)
            if my_links and SEND_FORM_LINKS:
                # Clean first, then guarantee: a bare {{Form_Link}} leaves an unlabelled URL
                # that hides which form it opens, and would also mask the link from the
                # completeness check below.
                html = _strip_bare_form_urls(html)
                html = _ensure_links_delivered(html, my_links)
            # Stage 1 guarantee: whatever the stored template contained — a legacy Google Form
            # URL, an old /tpms/forms deep link, or a now-empty {{Form_Link}} button — no form
            # link leaves in this mail.
            html = _strip_form_links(html)
            try:
                # send_email_notification returns False on failure and NEVER raises, so this
                # except block could not see a delivery failure: every send counted as `sent`
                # and every form link was stamped delivered. Capture the result instead.
                delivered = await send_email_notification(
                    person["email"], subject, html,
                    user_id=person.get("id"), slug=f"tpms_{event_kind}_{side}",
                    meta=log_context(event),
                )
                if delivered:
                    sent += 1
                else:
                    failed += 1
                    logger.warning(f"TPMS {event_kind} mail to {person['email']} was not delivered")
                if my_links and SEND_FORM_LINKS:
                    await _record_form_link_delivery(
                        event, person,
                        "sent" if delivered else "failed",
                        None if delivered else "Delivery failed",
                    )
            except Exception as e:
                failed += 1
                logger.error(f"TPMS {event_kind} mail to {person['email']} failed: {e}")
                if my_links and SEND_FORM_LINKS:
                    await _record_form_link_delivery(event, person, "failed", str(e))

    # ── WhatsApp, off the same (activity × side × event) wiring as the mail above.
    # Every lifecycle event goes through here, not just reminders: the admin screen has always
    # offered `schedule` / `reschedule` / `cancel` / `completed` for WhatsApp and validated the
    # chosen template against Meta, but this dispatcher was mail-only, so those rows saved,
    # listed — and never fired. The reminder path calls send_whatsapp() directly from the
    # reminder scheduler and never reaches _dispatch, so nothing double-sends.
    #
    # Isolated per side and non-fatal by design: mail has already gone out at this point, and a
    # WhatsApp failure must not turn a delivered notification into a failed request.
    whatsapp = {"sent": 0, "failed": 0, "skipped": 0, "no_phone": 0}
    for side in (SIDE_STAFF, SIDE_COMPANY):
        if not (people.get(side) or []):
            continue
        try:
            result = await send_whatsapp(event, event_kind, side)
        except Exception as e:
            logger.error(f"TPMS {event_kind} WhatsApp ({side}) failed: {e}")
            continue
        for key in whatsapp:
            whatsapp[key] += result.get(key) or 0

    return {"sent": sent, "failed": failed, "whatsapp": whatsapp}


# ─────────────────────────────────────────────────────────────
# Public API — one call per lifecycle transition
# ─────────────────────────────────────────────────────────────
async def notify_schedule(event: dict) -> dict:
    """Sent on save to both sides (sendScheduleEmails_, code.js:1141)."""
    return await _dispatch(event, EVENT_SCHEDULE, "Scheduled")


# ─────────────────────────────────────────────────────────────
# Async status mail (spec §11 "Async Mail Queue", §1.4, §5.18)
#
# The source queued the job and fired a one-off trigger ~3 seconds later so updateSchedule
# returned to the UI immediately. The asyncio equivalent is to detach the send onto the
# running loop: the caller returns as soon as the hand-off is accepted, and the sends
# proceed in the background.
#
# §18.14 — if the hand-off cannot be scheduled (no running loop), the mail is sent inline
# straight away rather than lost. Strong references are held until each task finishes,
# otherwise the loop may garbage-collect a send mid-flight.
# ─────────────────────────────────────────────────────────────
_BACKGROUND_SENDS: set = set()


async def _dispatch_detached(event: dict, event_kind: str, heading: str,
                             extra: Optional[dict]) -> None:
    try:
        await _dispatch(event, event_kind, heading, extra)
    except Exception as e:
        logger.error(f"TPMS detached {event_kind} mail failed: {e}")


def _enqueue_status_mail(event: dict, event_kind: str, heading: str,
                         extra: Optional[dict]) -> bool:
    """Hand the send to the event loop. False = could not be scheduled, send inline."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return False          # nothing to queue; _dispatch will no-op immediately
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False          # no loop (sync context / shutdown) → inline fallback
    task = loop.create_task(_dispatch_detached(event, event_kind, heading, extra))
    _BACKGROUND_SENDS.add(task)
    task.add_done_callback(_BACKGROUND_SENDS.discard)
    return True


async def notify_status(event: dict, status_kind: str, extra: Optional[dict] = None) -> dict:
    """Sent on reschedule / cancel / completion (sendStatusEmails_, code.js:970).

    Detached so the caller — updateSchedule, confirmCompletion, the reschedule decision —
    returns without waiting on delivery to every assigned recipient. Schedule mail is
    deliberately NOT detached: the spec scopes the queue to status-change mail only.
    """
    headings = {EVENT_RESCHEDULE: "Rescheduled", EVENT_CANCEL: "Cancelled",
                EVENT_COMPLETED: "Completed"}
    heading = headings.get(status_kind, "Update")
    if _enqueue_status_mail(event, status_kind, heading, extra):
        return {"queued": 1, "sent": 0, "failed": 0}
    return await _dispatch(event, status_kind, heading, extra)


async def notify_learner_done(event: dict, doer_name: str) -> dict:
    """Staff-only nudge asking them to confirm (markLearnerDone, code.js:3901)."""
    # TPMS notifications globally disabled → no confirm-me nudge.
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Doer_Name": doer_name})
    subject = fill("[Marked Done] {{Title}} – awaiting your confirmation", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        '<h3 style="color:#15803d;margin:0 0 10px">Activity marked done by doer</h3>'
        f'<p><b>{doer_name}</b> marked <b>{mapping["Activity"]}</b> '
        f'({mapping["Company_Name"]}) as done. Please confirm to finalize completion.</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_STAFF) or []:
        try:
            # Result captured: a False return means the mail did not go out.
            if await send_email_notification(person["email"], subject, html,
                                             user_id=person.get("id"), slug="tpms_learner_done"):
                sent += 1
            else:
                logger.warning(f"TPMS learner-done mail to {person['email']} was not delivered")
        except Exception as e:
            logger.error(f"TPMS learner-done mail to {person['email']} failed: {e}")
    return {"sent": sent}


async def notify_reschedule_request(event: dict, requester_name: str, new_date: str) -> dict:
    """H9 — tell internal staff a doer has REQUESTED a reschedule. Staff-side only."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Requested_By": requester_name, "New_Date": new_date})
    subject = fill("[Reschedule Requested] {{Title}} – {{Activity}}", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        '<h3 style="color:#b45309;margin:0 0 10px">Reschedule requested</h3>'
        f'<p><b>{requester_name}</b> requested to reschedule <b>{mapping["Activity"]}</b> '
        f'({mapping["Company_Name"]}) to <b>{new_date}</b>. Please review and approve or reject.</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_STAFF) or []:
        try:
            # Result captured: a False return means the mail did not go out.
            if await send_email_notification(person["email"], subject, html,
                                             user_id=person.get("id"), slug="tpms_reschedule_request"):
                sent += 1
            else:
                logger.warning(f"TPMS reschedule-request mail to {person['email']} was not delivered")
        except Exception as e:
            logger.error(f"TPMS reschedule-request mail to {person['email']} failed: {e}")
    return {"sent": sent}


async def notify_reschedule_decision(event: dict, approved: bool, note: str = "") -> dict:
    """H9 — tell the doer(s) their reschedule request was approved/rejected. Company-side only.
    (Approval ALSO sends the standard reschedule status mail to both sides via notify_status.)"""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Note": note})
    verdict = "approved" if approved else "rejected"
    color = "#15803d" if approved else "#b91c1c"
    subject = fill(f"[Reschedule {verdict.title()}] {{{{Title}}}} – {{{{Activity}}}}", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        f'<h3 style="color:{color};margin:0 0 10px">Reschedule {verdict}</h3>'
        f'<p>Your reschedule request for <b>{mapping["Activity"]}</b> ({mapping["Company_Name"]}) '
        f'was <b>{verdict}</b>.{(" Note: " + note) if note else ""}</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_COMPANY) or []:
        try:
            # Result captured: a False return means the mail did not go out.
            if await send_email_notification(person["email"], subject, html,
                                             user_id=person.get("id"), slug=f"tpms_reschedule_{verdict}"):
                sent += 1
            else:
                logger.warning(f"TPMS reschedule-decision mail to {person['email']} was not delivered")
        except Exception as e:
            logger.error(f"TPMS reschedule-decision mail to {person['email']} failed: {e}")
    return {"sent": sent}


def _form_response_table(cells: List[dict], qlabel) -> str:
    """HOD/MD summary — ratings grouped by criterion, each member's score listed under it."""
    if not cells:
        return ""
    by_q: Dict[str, List[dict]] = {}
    order: List[str] = []
    for c in cells:
        code = str(c.get("criterion_code"))
        if code not in by_q:
            by_q[code] = []
            order.append(code)
        by_q[code].append(c)
    blocks = []
    for i, code in enumerate(order, 1):
        rows = "".join(
            f'<tr><td style="border:1px solid #e5e7eb;padding:6px 10px">{c.get("member_name","")}</td>'
            f'<td align="center" style="border:1px solid #e5e7eb;padding:6px 10px"><b>{c.get("rating")}</b>/5</td></tr>'
            for c in by_q[code])
        blocks.append(
            f'<div style="margin:16px 0 6px;font-weight:600">{i}. {qlabel(code)}</div>'
            '<table style="border-collapse:collapse;width:100%;font-size:13px">'
            '<tr><th align="left" style="border:1px solid #e5e7eb;padding:6px 10px;background:#f5f5f5">Employee</th>'
            '<th style="border:1px solid #e5e7eb;padding:6px 10px;background:#f5f5f5;width:90px">Rating</th></tr>'
            f'{rows}</table>')
    return "".join(blocks)


def _form_score_table(cells: List[dict], qlabel) -> str:
    """Per-employee scorecard — their criterion → score."""
    rows = "".join(
        f'<tr><td style="border:1px solid #e5e7eb;padding:8px 10px">{qlabel(c.get("criterion_code"))}</td>'
        f'<td align="center" style="border:1px solid #e5e7eb;padding:8px 10px"><b>{c.get("rating")}</b>/5</td></tr>'
        for c in cells)
    return ('<table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:8px">'
            '<tr><th align="left" style="border:1px solid #e5e7eb;padding:8px 10px;background:#f5f5f5">Criteria</th>'
            '<th style="border:1px solid #e5e7eb;padding:8px 10px;background:#f5f5f5;width:90px">Score</th></tr>'
            f'{rows}</table>')


async def notify_form_submission(*, form_type: str, title: str, company_id: str, period: str,
                                 respondent_id: str, respondent_name: str,
                                 ratings: Optional[List[dict]] = None) -> dict:
    """H3 — after a review form is submitted: a summary mail to the HOD/MD respondent, plus a
    per-employee scorecard mail to each rated team member (rating forms only).

    Both are template-driven — events `form_summary` / `form_scorecard`, side `company` — with
    a built-in default body when no active template is configured. Gated by the TPMS switch."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"summary_sent": 0, "employee_sent": 0}
    from bson import ObjectId
    from app.services.notification_service import send_email_notification

    def _wrap(heading, inner, color="#4f46e5"):
        return ('<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px;max-width:600px;margin:auto">'
                f'<h3 style="color:{color};margin:0 0 10px">{heading}</h3>' + inner + '</div>')

    async def _find(uid):
        try:
            return await get_collection("learners").find_one({"_id": ObjectId(str(uid))})
        except Exception:
            return None

    # Company name + a criterion_code → question-text map, so the tables read nicely.
    company_name = str(company_id)
    try:
        co = await get_collection("companies").find_one({"_id": ObjectId(str(company_id))})
        if co:
            company_name = co.get("name") or str(company_id)
    except Exception:
        pass
    qtitle: Dict[str, str] = {}
    try:
        from app.models.forms import QUESTION_COLLECTION
        for q in await get_collection(QUESTION_COLLECTION).find({"form_type": form_type}).to_list(200):
            qtitle[str(q.get("item_id"))] = q.get("title") or q.get("prompt") or str(q.get("item_id"))
    except Exception:
        pass

    def qlabel(code):
        return qtitle.get(str(code)) or str(code)

    submitted_on = datetime.utcnow().strftime("%d %b %Y")
    base = {
        "Form_Type": title, "Company_Name": company_name, "Company_ID": str(company_id),
        "Month": period, "HOD_Name": respondent_name, "Submitted_On": submitted_on,
        "Total_Ratings": str(len(ratings or [])),
    }
    summary_sent = employee_sent = 0

    # 1) Respondent (HOD/MD) summary — template first, else default body.
    respondent = await _find(respondent_id)
    if respondent and respondent.get("email"):
        ctx = {**base, "Recipient_Name": respondent_name or respondent.get("full_name", ""),
               "Response_Table": _form_response_table(ratings or [], qlabel)}
        tpl = await get_template(title, EVENT_FORM_SUMMARY, SIDE_COMPANY)
        if tpl and tpl.get("body_html"):
            subject = fill(tpl.get("subject") or f"[{title}] Submission received – {{{{Month}}}}", ctx)
            html = _strip_form_links(fill(tpl["body_html"], ctx))
        else:
            subject = f"[{title}] Submission received – {period}"
            html = _wrap(f"{title} submitted",
                         f"<p>Your <b>{title}</b> submission for <b>{period}</b> has been received. Thank you.</p>"
                         + (ctx["Response_Table"] or ""))
        try:
            if await send_email_notification(respondent["email"], subject, html,
                                             user_id=str(respondent["_id"]),
                                             slug=f"tpms_form_{form_type}_summary"):
                summary_sent += 1
            else:
                logger.warning("TPMS form summary mail was not delivered")
        except Exception as e:
            logger.error(f"TPMS form summary mail failed: {e}")

    # 2) Per-employee scorecards (rating forms only) — template first, else default body.
    if ratings:
        by_member: Dict[tuple, List[dict]] = {}
        for c in ratings:
            by_member.setdefault((str(c.get("member_id")), c.get("member_name") or ""), []).append(c)
        tpl_emp = await get_template(title, EVENT_FORM_SCORECARD, SIDE_COMPANY)
        for (mid, mname), cells in by_member.items():
            member = await _find(mid)
            if not member or not member.get("email"):
                continue
            avg = sum(int(c.get("rating") or 0) for c in cells) / max(1, len(cells))
            ctx = {**base,
                   "Recipient_Name": mname or member.get("full_name", ""),
                   "Employee_Name": mname or member.get("full_name", ""),
                   "Average_Rating": f"{round(avg, 1):.1f}",
                   "Total_Questions": str(len(cells)),
                   "Score_Table": _form_score_table(cells, qlabel)}
            if tpl_emp and tpl_emp.get("body_html"):
                subject = fill(tpl_emp.get("subject") or f"[{title}] Your scorecard – {{{{Month}}}}", ctx)
                html = _strip_form_links(fill(tpl_emp["body_html"], ctx))
            else:
                subject = f"[{title}] Your scorecard – {period}"
                html = _wrap(f"Your {title} scorecard – {period}",
                             f'<p>Hello {ctx["Employee_Name"]}, your ratings for <b>{period}</b>:</p>'
                             + ctx["Score_Table"])
            try:
                if await send_email_notification(member["email"], subject, html,
                                                 user_id=str(member["_id"]),
                                                 slug=f"tpms_form_{form_type}_scorecard"):
                    employee_sent += 1
                else:
                    logger.warning("TPMS form scorecard mail was not delivered")
            except Exception as e:
                logger.error(f"TPMS form scorecard mail failed: {e}")

    return {"summary_sent": summary_sent, "employee_sent": employee_sent}
