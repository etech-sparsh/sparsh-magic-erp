"""
TPMS ▸ Leadership Score — feedback-giver links and email dispatch.

One unique, unguessable link per (subject × feedback giver), mailed to the giver, opened
at /lf/<token>, submitted once. This mirrors the security model already proven by
`tpms_form_link_service` for the four existing TPMS forms:

  • 32 random bytes from `secrets` — not guessable, not derived from any id.
  • Bound at creation to exactly ONE (cycle, subject, giver). Nothing about the target is
    encoded in the token, so it cannot be edited to reach another leader or another giver.
  • Expires at the end of the cycle's closing month.
  • Single submission: once submitted the row is terminal.

STORAGE ISOLATION
-----------------
Rows live in `tpms_leadership_assignments`, a NEW collection. `tpms_form_assignments` —
which carries the live links for Accountability / Ownership / Culture / Implementation
Feedback — is never read or written here, so the existing Form Mail Logs, resend action
and expiry behaviour are untouched. Only the pure helpers `new_token()` and
`public_link()`-style URL building are conceptually shared; nothing about storage is.

MAIL ISOLATION
--------------
Dispatch sends over WhatsApp only (see leadership_wa_service). It deliberately
does NOT route through `tpms_notify_service`, because that service's form hooks
(`_recipient_form_links`, `notify_form_submission`) are bound to the existing four forms
and to a schedule event, and `notify_form_submission` mails a per-employee scorecard —
which would breach the anonymity this module is required to preserve.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS,
    COLL_LS_CYCLES,
    WA_PENDING, WA_SENT,
    LEVEL_LABELS,
    LINK_EXPIRED, LINK_OPENED, LINK_PENDING, LINK_SENT, LINK_SUBMITTED,
    RELATION_LABELS, RESEND_COOLDOWN_HOURS,
    cycle_label, cycle_months, cycle_period,
)

logger = logging.getLogger(__name__)

# IST — the zone every TPMS date decision is made in.
IST = timezone(timedelta(hours=5, minutes=30))

# The base URL is NOT resolved here. It comes from the one place that owns it —
# tpms_form_link_service.configured_base_url() — which reads the Application URL set in
# Settings, then FRONTEND_URL, then the local origin. Leadership used to carry its own copy of
# that chain minus the Settings lookup, so a deployment could correct its TPMS links from the
# UI and still mail leadership invites pointing at http://localhost:5173.


def new_token() -> str:
    """A fresh, unguessable link credential."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What is stored. The raw token is a live credential — anyone holding it can submit
    as that giver for the whole window — so it is kept only in the recipient's mailbox,
    never in the database. A lookup hashes the incoming value and matches on that.

    Plain SHA-256 is right here, not a password KDF: the token is 32 bytes from `secrets`,
    so there is no dictionary to attack and stretching would only slow every form open."""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


async def public_link(token: str) -> str:
    """The in-app URL mailed to the giver: /lf/<token>.

    Always absolute. A relative href has no base document in an email, so the mail client
    would resolve it against its own origin and the recipient would land on a dead page.

    Async because the origin is a stored setting rather than a constant — an administrator can
    correct it from Settings on a running server, and the next invite goes out on the new host.
    """
    from app.services.tpms_form_link_service import configured_base_url

    return f"{await configured_base_url()}/lf/{token}"


def cycle_expiry_utc(cycle: str) -> Optional[datetime]:
    """Last instant of the cycle's closing month in IST, expressed in UTC.

    A cycle spans two months, so its links stay usable for exactly that window — tied to
    the business cycle rather than an arbitrary TTL.
    """
    try:
        period = cycle_period(cycle)
        year, month = int(period[:4]), int(period[5:7])
    except Exception:
        return None
    nxt = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=IST)
    return (nxt - timedelta(microseconds=1)).astimezone(timezone.utc)


def cycle_start_utc(cycle: str) -> Optional[datetime]:
    """First instant of the cycle's OPENING month in IST, expressed in UTC.

    The mirror of `cycle_expiry_utc`, and used for one thing only: telling a giver when an
    unconfigured window began. It is deliberately NOT wired into `survey_window`, because
    that function treats a missing `opens_at` as "open from the start" — giving it a
    calendar start would make every cycle PENDING before its first month, which is a change
    to when feedback is accepted rather than to what a message says.
    """
    try:
        year, first, _ = cycle_months(cycle)
    except (ValueError, TypeError):
        return None
    return datetime(year, first, 1, tzinfo=IST).astimezone(timezone.utc)


def message_window(cyc: dict) -> tuple:
    """(opens, closes) as an invitation should state them — neither ever None.

    `survey_window` leaves `opens` as None when HR configured no Open date, which is right
    for deciding access and useless in a sentence. Here that gap is filled with the cycle's
    own opening month, so the message can always name both ends of the window.
    """
    opens, closes = survey_window(cyc)
    return opens or cycle_start_utc((cyc or {}).get("cycle") or ""), closes


def format_window_dt(dt: Optional[datetime]) -> str:
    """A window date as it should appear on a phone: '12 Sep 2026, 10:00 AM IST'.

    Rendered in IST, and labelled. A WhatsApp template is plain text delivered by Meta —
    there is no client-side rendering, so the zone has to be chosen when the message is
    built. IST is the zone every date decision in TPMS is already made in and the one the
    recipients live in; naming it means a date on a handset can never be read as UTC.
    """
    if not dt:
        return ""
    local = (dt if getattr(dt, "tzinfo", None) else dt.replace(tzinfo=timezone.utc)).astimezone(IST)
    # %-d / %-I are not portable to Windows, so the leading zero is stripped by hand.
    return (f"{local.day} {local.strftime('%b %Y')}, "
            f"{local.strftime('%I:%M %p').lstrip('0')} IST")


def _aware(dt) -> Optional[datetime]:
    """A stored datetime as UTC-aware. Mongo hands naive values back, and comparing one
    against an aware `now` raises rather than returning False."""
    if not dt:
        return None
    return dt if getattr(dt, "tzinfo", None) else dt.replace(tzinfo=timezone.utc)


# Collection window states. `pending` is genuinely different from `closed`: one is "not
# yet" and the other is "no longer", and a giver holding a link needs to be told which.
WINDOW_PENDING = "pending"
WINDOW_OPEN = "open"
WINDOW_CLOSED = "closed"


def cycle_key(doc: dict) -> str:
    """Invitations are keyed by company AND cycle: the same cycle code exists at every
    client, so the code alone would collide across companies in any shared lookup."""
    return f"{doc.get('company_id')}|{doc.get('cycle')}"


async def cycles_for(docs: List[dict]) -> Dict[str, dict]:
    """The cycle document behind each invitation, fetched once for the whole set.

    A log can span cycles, and resolving expiry per row would be one query per row. Returns
    a map keyed by `cycle_key`; a row whose cycle has been deleted simply finds nothing and
    falls back to its stored expiry.
    """
    keys = {(str(d.get("company_id")), str(d.get("cycle")))
            for d in (docs or []) if d.get("cycle")}
    if not keys:
        return {}
    rows = await get_collection(COLL_LS_CYCLES).find(
        {"$or": [{"company_id": c, "cycle": y} for c, y in keys]}).to_list(500)
    return {cycle_key(r): r for r in rows}


def survey_window(cyc: dict) -> tuple:
    """(opens_at, closes_at) in UTC for a cycle — configured if set, derived if not.

    HR's own Open/Close date wins. With neither set the cycle's calendar months apply, which
    is exactly what governed access before the window was configurable — so every cycle
    already in the database behaves as it always did.
    """
    opens = _aware((cyc or {}).get("opens_at"))
    closes = _aware((cyc or {}).get("closes_at")) or cycle_expiry_utc((cyc or {}).get("cycle") or "")
    return opens, closes


def window_state(cyc: dict, now: Optional[datetime] = None) -> str:
    """Whether this cycle is accepting feedback right now."""
    now = now or datetime.now(timezone.utc)
    opens, closes = survey_window(cyc)
    if opens and now < opens:
        return WINDOW_PENDING
    if closes and now > closes:
        return WINDOW_CLOSED
    return WINDOW_OPEN


def window_is_closed(cyc: dict, now: Optional[datetime] = None) -> bool:
    """Whether this cycle's collection window has shut — configured Close date if HR set
    one, otherwise the cycle's own calendar months. The single answer that sending, link
    expiry and the giver's form all read, so none of them can disagree."""
    return window_state(cyc, now) == WINDOW_CLOSED


def cycle_is_expired(cycle: str, now: Optional[datetime] = None) -> bool:
    """Whether the cycle's own window has closed. Independent of any assignment row."""
    exp = cycle_expiry_utc(cycle)
    if not exp:
        return False
    return exp < (now or datetime.now(timezone.utc))


def delivery_status(doc: dict) -> str:
    """This invitation's delivery status.

    Reads `wa_status`, falling back to the retired `email_status` for rows written before
    Leadership moved to WhatsApp. The fallback is a READ, never a migration: those rows
    were genuinely delivered, and treating them as unsent would re-invite everybody the
    first time the button was pressed after the switch — and would hold every old cycle
    permanently unopenable, since open_readiness reads the same field.
    """
    return doc.get("wa_status") or doc.get("email_status") or ""


def resend_blocked_until(doc: dict) -> Optional[datetime]:
    """When this invitation becomes eligible for another automatic send, or None if now.

    Keyed on `sent_at`, which is written only on a SUCCESSFUL send. A row that has never
    been mailed, or whose last attempt failed, therefore has no cooldown and goes out
    immediately — a cooldown must never be the reason someone is left without their link.
    """
    if delivery_status(doc) != WA_SENT:
        return None
    sent_at = doc.get("sent_at")
    if not sent_at:
        return None
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return sent_at + timedelta(hours=RESEND_COOLDOWN_HOURS)


def in_resend_cooldown(doc: dict, now: Optional[datetime] = None) -> bool:
    until = resend_blocked_until(doc)
    return bool(until and until > (now or datetime.now(timezone.utc)))


def is_expired(doc: dict, now: Optional[datetime] = None,
               cyc: Optional[dict] = None) -> bool:
    """Past its window and never submitted. A submitted form is finished business and is
    never reported as expired, however long ago its cycle closed.

    Pass `cyc` and the CYCLE's window decides, which is the only way a Close date can move
    an existing link: `expires_at` is stamped when the link is created and would otherwise
    keep answering for a window HR has since changed. Reading it live also means no stored
    row has to be rewritten when the dates are edited.

    Without `cyc` the stored `expires_at` still answers, so a caller that has no cycle to
    hand behaves exactly as before rather than reporting nothing as expired.
    """
    if not doc or doc.get("status") == LINK_SUBMITTED:
        return False
    exp = survey_window(cyc)[1] if cyc else doc.get("expires_at")
    if not exp:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < (now or datetime.now(timezone.utc))


def effective_status(doc: dict, now: Optional[datetime] = None,
                     cyc: Optional[dict] = None) -> str:
    """Status as it should be shown. Expiry is DERIVED, not written by a sweep, so a link
    is never briefly reported live after its cycle closed just because no job has run —
    and so an edited Close date takes effect on the next read rather than on a rewrite."""
    if is_expired(doc, now, cyc):
        return LINK_EXPIRED
    return doc.get("status") or LINK_SENT


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("email") or "")


async def create_assignment(*, company_id: str, company_name: str, cycle: str,
                            subject: dict, giver: dict, relation: str,
                            assigned_by: Optional[dict] = None) -> dict:
    """One giver's link for one subject in one cycle, created idempotently.

    Re-dispatching a cycle must not mint a second link for the same pairing — the giver
    would hold two live URLs for one form and the log would double-count. An existing
    unsubmitted row is reused (expiry refreshed); a submitted one is returned untouched so
    a re-dispatch can never reopen completed feedback.
    """
    col = get_collection(COLL_LS_ASSIGNMENTS)
    key = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "subject_id": str(subject.get("subject_id")),
        "giver_id": str(giver.get("_id")),
    }
    existing = await col.find_one(key)
    if existing:
        if existing.get("status") != LINK_SUBMITTED:
            await col.update_one(
                {"_id": existing["_id"]},
                {"$set": {"expires_at": cycle_expiry_utc(cycle),
                          "relation": relation,
                          "updated_at": datetime.now(timezone.utc)}},
            )
            existing["relation"] = relation
        return existing

    now = datetime.now(timezone.utc)
    token = new_token()
    doc = {
        **key,
        "period": cycle_period(cycle),
        # The hash only. `_issued_token` carries the raw value back to the caller in
        # memory so this dispatch can mail it; it is never persisted and never returned by
        # an API. A resend mints a fresh token (see rotate_token).
        "token_hash": token_hash(token),
        "relation": relation,
        "company_name": company_name or "",
        # Subject snapshot: the giver's form must still name the leader correctly even if
        # the user record is later renamed.
        "subject_name": subject.get("subject_name") or "",
        "subject_level": subject.get("level") or "",
        "subject_designation": subject.get("designation") or "",
        # Giver snapshot. Held for dispatch, authorization and duplicate prevention only —
        # never serialized to a leader. See leadership_service._public_* helpers.
        "giver_name": _display_name(giver),
        "giver_email": giver.get("email") or "",
        # Snapshotted for the reminder ladder, which mails and messages non-submitters
        # without ever reading a response. Absent on rows created before this field
        # existed — leadership_notify_service falls back to a roster lookup for those.
        "giver_phone": giver.get("mobile") or "",
        # The GIVER's own Leadership level, for the {{giver_level}} placeholder. Copied
        # from their user record and never inferred from a designation. Distinct from
        # `subject_level` above, which is the level of the LEADER being rated — the two
        # must not be confused, since {{level_label}} renders the latter.
        # Snapshotted so a later promotion cannot rewrite an invitation already sent.
        "giver_level": str(giver.get("leadership_level") or "").strip().upper(),
        "assigned_by_id": str((assigned_by or {}).get("_id") or ""),
        "assigned_by_name": _display_name(assigned_by or {}),
        # Not "sent": nothing has gone out yet. mark_whatsapp_result promotes it.
        "status": LINK_PENDING,
        "wa_status": WA_PENDING,
        "wa_error": None,
        "sent_at": None,
        "opened_at": None,
        "submitted_at": None,
        "expires_at": cycle_expiry_utc(cycle),
        "created_at": now,
        "updated_at": now,
    }
    await col.insert_one(doc)
    doc["_issued_token"] = token
    return doc


async def remove_assignment(company_id: str, cycle: str, subject_id: str, giver_id: str) -> bool:
    """Drop a panel member who has not yet submitted. A submitted row is kept — removing it
    would silently delete collected feedback."""
    col = get_collection(COLL_LS_ASSIGNMENTS)
    res = await col.delete_one({
        "company_id": str(company_id), "cycle": str(cycle),
        "subject_id": str(subject_id), "giver_id": str(giver_id),
        "status": {"$ne": LINK_SUBMITTED},
    })
    return res.deleted_count > 0


async def resolve_token(token: str) -> Optional[dict]:
    """The assignment a link token refers to, or None when unknown.

    Matches on the HASH. Rows issued before hashing still carry a plaintext `token`, and
    those links are already in people's inboxes, so they are accepted as a second lookup —
    a giver must not be locked out of a form because of when their link was minted. Such a
    row is marked `legacy_token` so the admin screen can show which invitations still hold
    a credential in the database, and rotating one clears it for good.

    Returns expired and submitted rows too: the form page has to tell the giver WHY a link
    no longer works, which it cannot do if a dead token is indistinguishable from a typo.
    """
    if not token:
        return None
    col = get_collection(COLL_LS_ASSIGNMENTS)
    hashed = token_hash(token)
    doc = await col.find_one({"token_hash": hashed})
    if doc:
        return doc
    legacy = await col.find_one({"token": token})
    if legacy:
        legacy["legacy_token"] = True
        return legacy
    # A token already spent by a successful submission. Resolving it grants nothing — the
    # row's status is `submitted`, so every caller that requires an open link refuses it —
    # but it lets the giver be told they have already submitted rather than that their link
    # is invalid, which is the same reason expired rows are returned above.
    spent = await col.find_one({"spent_token_hash": hashed})
    if spent:
        spent["spent_token"] = True
    return spent


async def rotate_token(doc: dict) -> str:
    """Issue a fresh credential for an existing invitation and return it, once.

    Resending has to produce a working URL, and the old one cannot be reproduced because
    only its hash was kept. So a resend mints a new token and the previous link stops
    working. That is the safer default for a single-use form — a forwarded or leaked link
    dies the moment the real recipient is chased again — and it is what the resend button
    tells HR it will do.

    Also the repair path for a legacy row: rotating drops the plaintext `token` field, so
    the credential stops existing in the database.
    """
    token = new_token()
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"]},
        {"$set": {"token_hash": token_hash(token),
                  "updated_at": datetime.now(timezone.utc)},
         "$unset": {"token": "", "link": ""}},
    )
    doc["token_hash"] = token_hash(token)
    doc.pop("token", None)
    doc.pop("link", None)
    doc["_issued_token"] = token
    return token


async def claim_for_submission(doc: dict) -> bool:
    """Atomically take this invitation from open to submitted. True if this caller won it.

    This is what makes a response safe to store with NO rater identity on it. Duplicate
    submission used to be prevented by a unique index over (cycle, subject, giver_id) on
    the RESPONSE — which meant every answer carried the name of the person who gave it,
    permanently, to enforce a rule that belongs on the invitation.

    The filter is the lock: `status` must still be one of the open states, so two
    concurrent submits cannot both match, and only the winner goes on to write a response.
    If writing that response then fails, `release_claim` puts the row back.
    """
    now = datetime.now(timezone.utc)
    changes = {"status": LINK_SUBMITTED, "submitted_at": now, "updated_at": now}
    # Retire the live credential to `spent_token_hash`. It can no longer open or submit
    # anything — `token_hash` is what resolve_token treats as live, and the status check
    # refuses a submitted row regardless. Keeping the retired hash lets the giver's own
    # link be RECOGNISED afterwards, so a second submit is answered "already submitted"
    # instead of "not a valid link": without it the row became unfindable and an ordinary
    # double click looked like a broken invitation.
    #
    # Written only when a hash actually exists, never as "": a blank would be stored on
    # every tokenless row and collide the moment this field is indexed.
    if doc.get("token_hash"):
        changes["spent_token_hash"] = doc["token_hash"]
    res = await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": {"$in": [LINK_PENDING, LINK_SENT, LINK_OPENED]}},
        # Still removed: single use means the working credential is gone from the
        # database, not merely refused by a status check.
        {"$set": changes, "$unset": {"token_hash": "", "token": "", "link": ""}},
    )
    return res.modified_count == 1


async def release_claim(doc: dict) -> None:
    """Undo a claim whose response could not be written, so the giver can try again."""
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": LINK_SUBMITTED},
        {"$set": {"status": LINK_OPENED, "submitted_at": None,
                  "updated_at": datetime.now(timezone.utc)}},
    )


async def mark_opened(doc: dict) -> None:
    """First open moves Pending/Sent → Opened. `opened_at` records the FIRST view.

    Pending is accepted as well as Sent: opening the form is proof the link reached its
    owner, whatever the delivery log believes.
    """
    if doc.get("status") not in (LINK_PENDING, LINK_SENT):
        return
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": {"$in": [LINK_PENDING, LINK_SENT]}},
        {"$set": {"status": LINK_OPENED, "opened_at": now, "updated_at": now}},
    )


def template_map(doc: dict, link: str = "") -> dict:
    """Placeholder values for ONE assignment.

    `leadership_link` is the URL minted for this send. It is passed in rather than read
    off the row, because the row holds only a hash — the raw credential exists for the
    length of one dispatch and then only in the recipient's mailbox. Because the map is
    rebuilt per assignment, two givers can never receive the same link, which is what
    keeps both single-use submission and anonymity intact.
    """
    expires = doc.get("expires_at")
    return {
        "leadership_link": link or "",
        "giver_name": doc.get("giver_name") or "",
        # The GIVER's own level. Deliberately separate from `level_label` below, which is
        # the level of the leader being rated — filling one from the other would print the
        # wrong person's grade in the invitation.
        "giver_level": doc.get("giver_level") or "",
        "subject_name": doc.get("subject_name") or "a colleague",
        "subject_designation": doc.get("subject_designation") or "",
        "level_label": LEVEL_LABELS.get(doc.get("subject_level") or "", doc.get("subject_level") or ""),
        "cycle_label": cycle_label(doc.get("cycle") or ""),
        "company_name": doc.get("company_name") or "",
        "expires_on": expires.strftime("%Y-%m-%d") if hasattr(expires, "strftime") else "",
    }


def _ensure_link_present(html: str, link: str) -> str:
    """Append the link if the rendered body does not already carry it.

    An author who forgets `{{leadership_link}}` would otherwise send an invitation with no
    way to act on it, and the giver has no other route to the form — they are never given a
    token to enter by hand. This is the same guarantee the TPMS schedule mail makes.
    """
    if not link or link in (html or ""):
        return html
    return (html or "") + (
        '<div style="margin-top:18px;padding:14px 16px;border:1px solid #e5e7eb;'
        'border-radius:10px;background:#fafafa;font-family:Arial,sans-serif">'
        '<p style="margin:0 0 8px;font-weight:700;font-size:13px">Your feedback link</p>'
        f'<p style="margin:6px 0"><a href="{link}" style="color:#4f46e5;font-weight:700">'
        'Give your feedback</a></p>'
        '<p style="margin:8px 0 0;font-size:11px;color:#6b7280">'
        'This link is personal to you and can be submitted once.</p></div>'
    )


async def _giver_level_fallback(doc: dict) -> str:
    """The giver's level for an assignment minted before `giver_level` was snapshotted.

    Read live from the user record, exactly as `create_assignment` would have. Rows that
    predate the field would otherwise print an empty {{giver_level}} for the rest of their
    life, and there is nothing to migrate: the value is derivable on demand.

    An empty string is a real answer — that giver holds no level — and is returned as-is
    rather than guessed at from their designation.
    """
    from bson import ObjectId
    try:
        oid = ObjectId(str(doc.get("giver_id")))
    except Exception:
        return ""
    for coll in ("staff", "learners"):
        person = await get_collection(coll).find_one({"_id": oid}, {"leadership_level": 1})
        if person:
            return str(person.get("leadership_level") or "").strip().upper()
    return ""


async def mark_whatsapp_result(assignment_id, status: str, error=None) -> None:
    """Record a WhatsApp outcome on the invitation row.

    Writes `sent_at` ONLY on a real
    send: that timestamp is the resend cooldown's key, so stamping it on a refusal would
    lock a giver out of a retry for RESEND_COOLDOWN_HOURS having never received anything.
    """
    from app.models.leadership import WA_SENT
    now = datetime.now(timezone.utc)
    oid = assignment_id if isinstance(assignment_id, ObjectId) else ObjectId(str(assignment_id))
    updates = {"wa_status": status, "wa_error": error, "updated_at": now}
    if status == WA_SENT:
        updates["sent_at"] = now
    col = get_collection(COLL_LS_ASSIGNMENTS)
    await col.update_one({"_id": oid}, {"$set": updates})

    # A real delivery is what turns a minted link into a Sent one. Filtered so it can only
    # move pending -> sent: a resend must not drag a link the giver already opened backwards.
    if status == WA_SENT:
        await col.update_one({"_id": oid, "status": LINK_PENDING},
                             {"$set": {"status": LINK_SENT}})


async def send_assignment_whatsapp(doc: dict) -> dict:
    """Send one giver their link over WhatsApp. Never raises — a refusal is recorded.

    Every send mints a fresh credential, exactly as the email path did: the previous URL
    stops working, so a link that has been forwarded or is sitting in an old chat dies the
    moment the real recipient is chased again.
    """
    from app.services import leadership_wa_service as wa

    token = doc.get("_issued_token")
    link = await public_link(token if token else await rotate_token(doc))
    result = await wa.send_invitation(doc, link)
    await mark_whatsapp_result(doc["_id"], result["status"],
                               None if result.get("ok") else result.get("status"))
    return result


async def dispatch_pending(company_id: str, cycle: str,
                           subject_id: Optional[str] = None,
                           skip_subjects: Optional[list] = None) -> dict:
    """Mail every not-yet-submitted link for a cycle (or one subject within it).

    Two things are skipped rather than mailed:
      • already-submitted rows — a re-dispatch must never nag someone who is done;
      • rows mailed successfully within RESEND_COOLDOWN_HOURS — so pressing the button
        twice in a minute does not send the same invitation twice. They are chased again
        on the next dispatch after the cooldown, which is what the button is for.

    Neither skip loses a link: `skipped_recent` is reported back so the caller can say
    exactly how many were held, and a single giver can always be re-mailed immediately
    through the explicit per-assignment resend.

    `skip_subjects` is the third exclusion: leaders whose panel does not yet meet the
    document's 2-per-relation composition. The caller decides who those are (see
    leadership_service.incomplete_panels) — this function only honours the list, so one
    unfinished panel never holds up the leaders who are ready.
    """
    query: dict = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "status": {"$ne": LINK_SUBMITTED},
    }
    if subject_id:
        query["subject_id"] = str(subject_id)
    elif skip_subjects:
        query["subject_id"] = {"$nin": [str(x) for x in skip_subjects]}

    rows = await get_collection(COLL_LS_ASSIGNMENTS).find(query).to_list(2000)
    now = datetime.now(timezone.utc)
    due = [r for r in rows if not in_resend_cooldown(r, now)]
    skipped_recent = len(rows) - len(due)

    # Fetch the template ONCE for the batch, then fill it separately for every recipient —
    # each mail carries only that giver's own token URL. Scoped to the company being
    # dispatched, so one client's wording can never go out under another's name.
    # No template fetch: WhatsApp renders from the copy Meta approved, not from ours, so
    # there is nothing to fill in here. leadership_wa_service resolves the company's
    # template name per send and records its own refusal when none is configured.
    sent = failed = unreachable = 0
    for row in due:
        result = await send_assignment_whatsapp(row)
        if result.get("ok"):
            sent += 1
        elif result.get("status") == "unreachable":
            # Kept apart from `failed`: a missing mobile number is fixed on the person's
            # record, a refusal is fixed with Meta. Reporting them together sends HR to
            # the wrong place.
            unreachable += 1
        else:
            failed += 1

    next_at = None
    if skipped_recent:
        held = [resend_blocked_until(r) for r in rows if in_resend_cooldown(r, now)]
        held = [h for h in held if h]
        next_at = min(held) if held else None

    logger.info(
        "Leadership WhatsApp dispatch [%s/%s]: %d sent, %d failed, %d unreachable, "
        "%d held by the %dh cooldown (%d pending total)",
        company_id, cycle, sent, failed, unreachable, skipped_recent,
        RESEND_COOLDOWN_HOURS, len(rows),
    )
    return {
        "unreachable": unreachable,
        "channel": "whatsapp",
        "sent": sent,
        "failed": failed,
        "total": len(rows),
        "skipped_recent": skipped_recent,
        "cooldown_hours": RESEND_COOLDOWN_HOURS,
        "next_resend_at": next_at,
    }


async def assignments_for_subject(company_id: str, cycle: str, subject_id: str) -> List[dict]:
    return await get_collection(COLL_LS_ASSIGNMENTS).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).sort("created_at", 1).to_list(200)


async def panel_rows(docs: List[dict], now: Optional[datetime] = None,
                     cyc: Optional[dict] = None) -> List[dict]:
    """`panel_row` for each invitation, with the giver's number resolved in one pass.

    Read live rather than copied onto the assignment when it was created: a number corrected
    on someone's user record has to be the one shown here, or HR fixes the record and the
    panel still says they are unreachable.
    """
    ids = {str(d.get("giver_id")) for d in docs if d.get("giver_id")}
    oids = []
    for gid in ids:
        try:
            oids.append(ObjectId(gid))
        except Exception:
            continue

    phones: Dict[str, str] = {}
    if oids:
        for coll in ("staff", "learners"):
            for u in await get_collection(coll).find(
                    {"_id": {"$in": oids}}, {"mobile": 1, "phone": 1}).to_list(2000):
                phones[str(u["_id"])] = str(u.get("mobile") or u.get("phone") or "").strip()

    # One cycle lookup for the whole panel, so every row's Expired badge is measured
    # against the window HR actually configured. `cyc` short-circuits it for the caller
    # that already holds the cycle.
    cycles = {cycle_key(d): cyc for d in docs} if cyc else await cycles_for(docs)

    return [{**panel_row(d, now, cycles.get(cycle_key(d))),
             "giver_mobile": phones.get(str(d.get("giver_id")), "")} for d in docs]


def panel_row(doc: dict, now: Optional[datetime] = None,
              cyc: Optional[dict] = None) -> dict:
    """One panel member as HR sees them. HR-ONLY — this carries giver identity and must
    never be returned by a leader-facing or manager-facing endpoint."""
    return {
        "id": str(doc.get("_id")),
        "giver_id": doc.get("giver_id"),
        "giver_name": doc.get("giver_name"),
        "giver_email": doc.get("giver_email"),
        "relation": doc.get("relation"),
        "relation_label": RELATION_LABELS.get(doc.get("relation") or "", doc.get("relation") or ""),
        "status": effective_status(doc, now, cyc),
        "wa_status": doc.get("wa_status"),
        "wa_error": doc.get("wa_error"),
        # No link. Only its hash is stored, so there is nothing to hand back — and a URL
        # on screen is a live credential that could be used to submit as this person.
        # HR who needs one presses Resend, which mints a fresh link and mails it to them.
        "legacy_token": bool(doc.get("token")),
        "sent_at": doc.get("sent_at"),
        "opened_at": doc.get("opened_at"),
        "submitted_at": doc.get("submitted_at"),
    }
