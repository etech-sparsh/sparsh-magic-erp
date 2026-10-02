"""
Leadership ▸ WhatsApp delivery and its own tracking ledger.

Leadership sends its invitations by WhatsApp and by nothing else. Email is not a fallback
here: a feedback invitation names the leader being rated, so an inbox that is shared,
forwarded or auto-archived is a disclosure risk this module does not accept.

WHY THIS DOES NOT REUSE TPMS TRACKING
-------------------------------------
TPMS keys its templates on (activity, event kind, side) and its delivery log on an activity
id. A Leadership invitation has no activity, no side and no event kind, so it would have to
either invent codes or widen a schema belonging to a different module. Separate collections
also keep a TPMS retention sweep away from records that carry panel identity.

ANONYMITY
---------
This ledger records DELIVERY OF AN INVITATION, never a response. It holds who was invited —
which is precisely what the assignment row already holds — and nothing about what anybody
answered. The two cannot be joined: responses stopped carrying `assignment_ref`, so there
is no path from an answer to a row in here. Reading it is gated on `_require_panel` (HR and
internal staff), the same gate as the panel itself, because knowing who was invited IS
panel information — a clientadmin must not see it.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bson import ObjectId

from app.config.settings import settings
from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS, COLL_LS_WA_LOG, COLL_LS_WA_TEMPLATE, COLL_LS_WA_TEMPLATES,
    WA_DELIVERED, WA_FAILED, WA_PENDING, WA_READ, WA_SENT, WA_UNREACHABLE,
    WA_TPL_APPROVED, WA_TPL_DRAFT, WA_TPL_EDITABLE, WA_TPL_PENDING, WA_TPL_REJECTED,
    WA_VARIABLE_FIELDS, wa_is_forward,
)

logger = logging.getLogger(__name__)

# The values a template may use, and what fills each one. NAMED rather than numbered on
# purpose: a numbered template has to fix what {{1}} means for everybody, so the moment one
# variable becomes optional the positions shift underneath every other template. With names
# the body says {{company_name}}, any of them can be left out, and reordering the sentence
# cannot silently swap two values.
#
# `link` is MINTED PER INVITATION at send time — a fresh single-use token for one giver and
# one leader — so it can never be typed, pasted or stored. The admin writes {{link}}; the
# backend fills it.
SYSTEM_VARIABLES = {
    # Minted per invitation at send time. There is no field anywhere that accepts a link,
    # and a custom variable may not shadow this name.
    "feedback_link": "their unique feedback form link",
    "giver_name":    "the giver's name",
    # Named `leader_name` for the person writing the template, not `subject_name` as the
    # data model calls it — "subject" is our word for the rated person and means nothing to
    # anyone composing a message. The assignment field it reads is unchanged.
    #
    # Naming the leader in the message tells anyone glancing at that phone who is about to
    # be rated. Offered because it was asked for, but it is the one variable that costs
    # something to use.
    "leader_name":   "the leader they are rating",
    # Filled from the cycle's own collection window — HR's Open/Close dates when they set
    # them, the cycle's calendar months when they did not. The same window the form
    # enforces, so a message can never state a deadline the form disagrees with.
    "opens_at":      "when the feedback window opens",
    "closes_at":     "the last date to give feedback",
}

# What an invitation may be filed as. AUTHENTICATION is deliberately not offered — it is
# for one-time-passcode templates, whose body Meta fixes entirely, and a feedback invitation
# submitted under it is rejected on review.
#
# UTILITY is the right answer for an invitation: it is a transactional message about a
# process the recipient is part of. MARKETING is offered because Meta may insist on it, and
# a template it has already filed that way cannot be argued back — being able to author the
# next one to match is better than being unable to say it at all.
META_CATEGORIES = ("UTILITY", "MARKETING")
DEFAULT_CATEGORY = "UTILITY"


# Meta's own rule for a named parameter, mirrored so a bad name is refused while it can
# still be typed rather than after a review that takes hours.
VAR_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# What Meta sees in the sample it reviews. It requires an example for every variable, and
# there is exactly one sensible example for each of ours, so they are generated rather than
# asked for — and the sample link is obviously a sample.
SAMPLE_VALUES = {
    "giver_name": "Asha Rao",
    "feedback_link": "https://example.com/f/sample-link",
    "leader_name": "Rahul Mehta",
    "opens_at": "12 Sep 2026, 10:00 AM IST",
    "closes_at": "30 Sep 2026, 6:00 PM IST",
}


def _custom_map(variables) -> Dict[str, str]:
    """[{name, value}] → {name: value}, ignoring anything unnamed."""
    out: Dict[str, str] = {}
    for item in (variables or []):
        name = str((item or {}).get("name") or "").strip()
        if name:
            out[name] = str((item or {}).get("value") or "")
    return out


def validate_variables(body: str, variables) -> List[str]:
    """Everything that would make this template unusable, said before it is saved.

    Meta checks its own rules on review, hours later. These are the ones only WE can check:
    a variable in the body that nothing fills, a custom name shadowing a system one, and a
    declared variable with no value — each of which produces an APPROVED template that
    sends a blank where a word should be.
    """
    errors: List[str] = []
    custom = _custom_map(variables)

    for name in custom:
        if not VAR_NAME_RE.match(name):
            errors.append(f"'{name}' is not a usable variable name — use lowercase letters, "
                          "numbers and underscores, starting with a letter.")
        elif name in SYSTEM_VARIABLES:
            errors.append(f"'{name}' is a system variable and cannot be redefined.")
        elif not custom[name].strip():
            errors.append(f"Give {{{{{name}}}}} a value, or it will send as a blank.")

    used = set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", body or ""))
    unknown = sorted(used - set(SYSTEM_VARIABLES) - set(custom))
    if unknown:
        errors.append("Nothing fills " + ", ".join("{{%s}}" % u for u in unknown)
                      + " — add it as a variable, or remove it from the message.")

    unused = sorted(set(custom) - used)
    if unused:
        errors.append("Not used in the message: "
                      + ", ".join("{{%s}}" % u for u in unused) + ".")
    return errors


def authored_doc(name: str, language: str, body: str, variables=None,
                 category: Optional[str] = None) -> dict:
    """The full Meta template document, from what a user actually chooses.

    Variable style, header, footer and buttons stay fixed — a feedback invitation has one
    shape and offering those would be asking questions with a single right answer.

    CATEGORY is not one of them. It decides how Meta paces the message and whether it is
    delivered to someone who never opted in, so it belongs to whoever is accountable for
    the message going out. Meta still runs its own classifier over the content and its
    answer is final; this is the request, not the verdict.
    """
    text = str(body or "").strip()
    custom = _custom_map(variables)
    used = body_variables(text, custom)
    return {
        # Stored so a send can fill them: a custom variable is the same words for every
        # recipient, which is exactly why the admin types it once here.
        "variables": [{"name": n, "value": v} for n, v in custom.items()],
        "name": str(name or "").strip().lower(),
        "language": str(language or "en").strip() or "en",
        "category": normalise_category(category),
        "variable_style": "named",
        "header_format": "NONE",
        "body": text,
        # One example per variable ACTUALLY used, in the order it first appears — which is
        # exactly what Meta pairs with body_text_named_params.
        "body_examples": [SAMPLE_VALUES.get(v) or custom.get(v) or v for v in used],
        "footer": None,
        "buttons": [],
    }


def normalise_category(value: Optional[str]) -> str:
    """One of META_CATEGORIES, defaulting rather than raising.

    A category Meta would not accept is worth refusing, but not at the cost of losing a
    template someone spent ten minutes writing — an unknown value falls back to UTILITY,
    which is both the safe default and the one an invitation should usually carry.
    """
    got = str(value or "").strip().upper()
    return got if got in META_CATEGORIES else DEFAULT_CATEGORY


def body_variables(body: str, custom=None) -> List[str]:
    """The fillable variables this body uses, in first-appearance order.

    Anything nothing can fill is dropped rather than guessed at — validate_variables is what
    reports it, so a typo is a message on screen rather than a template that ships and sends
    a blank.
    """
    known = set(SYSTEM_VARIABLES) | set(custom or {})
    seen, out = set(), []
    for token in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", body or ""):
        if token in known and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Template — ONE invitation, shared by every company
#
# There is a single row. Every company's invitation is written once, submitted to Meta once
# and approved once, because the message says the same thing whoever receives it: who is
# asking, who they are rating, and where the form is. All three arrive as variables filled
# per invitation, so nothing in the wording is company-specific and nothing was gained by
# making each client author and get approved their own copy of the same sentence.
#
# It also removes the failure this module kept hitting: a Meta template name is global to
# the WhatsApp Business Account, so per-company names collided, and a company that had
# never written one simply could not send.
#
# `SHARED_KEY` is the row. It is a fixed filter rather than a hardcoded _id so the document
# is created by the first save like any other upsert.
# ─────────────────────────────────────────────────────────────
SHARED_KEY = {"scope": "shared"}


def _template_col():
    return get_collection(COLL_LS_WA_TEMPLATE)


async def suggest_template_name(company_id: str = "") -> str:
    """A Meta template name for the one shared invitation.

    One template for everyone means one obvious name. It still has to be a name no legacy
    per-company row already holds: to Meta a name IS the template, so reusing one would
    submit against that row's template and quietly adopt its approval and its wording.

    `company_id` is accepted and ignored — kept so an older caller cannot break.
    """
    base = "leadership_invite"
    legacy = get_collection(COLL_LS_WA_TEMPLATES)
    return base if not await legacy.find_one({"meta_template_name": base}) else f"{base}_all"


def _shape(doc: Optional[dict], suggested: str = "") -> dict:
    """One stored row rendered as the screen and the sender both read it.

    Shared by the live template and by a legacy per-company row, so the fallback in
    `send_invitation` is judged by exactly the same `is_ready` rule as the real thing.
    """
    return {
        "meta_template_name": (doc or {}).get("meta_template_name") or "",
        # Offered only when nothing is written yet, so it never overwrites a chosen name.
        "suggested_name": "" if (doc or {}).get("meta_template_name") else suggested,
        "language": (doc or {}).get("language") or "en",
        # What the author asked for, and what Meta actually filed it as. Kept apart:
        # Meta re-categorises on content, and a screen that showed only our request would
        # go on claiming UTILITY while every message was being paced as MARKETING.
        "category": (doc or {}).get("category") or DEFAULT_CATEGORY,
        "meta_category": (doc or {}).get("meta_category"),
        "categories": list(META_CATEGORIES),
        "system_variables": dict(SYSTEM_VARIABLES),
        "variables": (doc or {}).get("variables") or [],
        # Written on insert and reported for completeness. It stopped gating anything when
        # approval became the only gate — a template Meta has approved is one that sends.
        "active": bool((doc or {}).get("active", True)),
        "fields": list(WA_VARIABLE_FIELDS),
        "body": (doc or {}).get("body") or "",
        # There is one row for everybody, so having one IS being written.
        "is_customised": bool(doc),
        # Where the template stands with Meta. DRAFT means it has never been submitted.
        "status": str((doc or {}).get("status") or WA_TPL_DRAFT).upper(),
        "meta_template_id": (doc or {}).get("meta_template_id"),
        "rejected_reason": (doc or {}).get("rejected_reason"),
        "last_submit_error": (doc or {}).get("last_submit_error"),
        "submitted_at": (doc or {}).get("submitted_at"),
        "synced_at": (doc or {}).get("synced_at"),
        # Editable status is not enough: a company that has never written a template
        # is DRAFT by default, and offering Submit there is a button whose only
        # outcome is the 400 that says "save the template first".
        "can_submit": bool((doc or {}).get("meta_template_name"))
                      and bool((doc or {}).get("body"))
                      and str((doc or {}).get("status") or WA_TPL_DRAFT).upper() in WA_TPL_EDITABLE,
        # Nothing can be sent until the client names a template they had approved AND the
        # wiring is switched on. Said plainly, because "no messages arrived" is otherwise a
        # long afternoon.
        # Ready to SEND means Meta has approved it and the wiring is switched on. A name
        # typed in but never approved is exactly the case that used to fail per recipient.
        # Approval IS the gate. A second on/off switch beside it was one more thing to
        # forget, and pressing Send is already the decision to send.
        "is_ready": str((doc or {}).get("status") or "").upper() == WA_TPL_APPROVED
                    and bool((doc or {}).get("meta_template_name")),
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
    }


async def get_template(company_id: Optional[str] = None) -> dict:
    """THE invitation template — the same one for every company.

    `company_id` is accepted and ignored. Kept on the signature so a caller that still
    passes one gets the shared template rather than a TypeError.
    """
    doc = await _template_col().find_one(SHARED_KEY)
    suggested = "" if (doc or {}).get("meta_template_name") else await suggest_template_name()
    return _shape(doc, suggested)


async def legacy_company_template(company_id: str) -> dict:
    """A company's own pre-shared-template row, if it still has one.

    Read-only and used in exactly one place: keeping a company whose old template Meta had
    already approved able to send while the shared one is still being written or reviewed.
    Nothing writes here any more.
    """
    doc = await get_collection(COLL_LS_WA_TEMPLATES).find_one({"company_id": str(company_id)})
    return _shape(doc)


async def save_authored_template(doc: dict, user: dict) -> dict:
    """Store the composer's full definition as THE invitation, in DRAFT.

    The authored fields (header, body, footer, buttons, variable style, examples) are kept
    exactly as the composer produced them, because that is what Meta validates and renders
    from. Leadership's own wiring — which data field fills each placeholder, and whether the
    template is switched on — lives alongside and is left untouched by an edit here.
    """
    col = _template_col()
    existing = await col.find_one(SHARED_KEY) or {}

    # A Meta template NAME is global to the WhatsApp Business Account, so a name a legacy
    # per-company row still holds is ALREADY a template at Meta. Refused here, while it can
    # still be typed differently. Letting it through would fail at submit with Meta's
    # "Content in this language already exists", and — worse — a later Refresh matches on
    # name, so the shared template would adopt that old row's approval and start sending
    # one client's wording to everybody.
    #
    # Checked on the name alone, not name + language: to Meta a name is one template that
    # may carry several language versions, so a shared name collides whatever the language.
    name = str(doc.get("name") or "").strip().lower()
    if name:
        clash = await get_collection(COLL_LS_WA_TEMPLATES).find_one({"meta_template_name": name})
        if clash:
            raise ValueError(
                f"The template name '{name}' already belongs to a template on this "
                "WhatsApp Business Account. Meta template names are account-wide, so "
                "please choose a different one.")

    await col.update_one(
        SHARED_KEY,
        {"$set": {
            **doc,
            "meta_template_name": doc.get("name") or "",
            # Any edit returns it to DRAFT: Meta reviews content, so a changed template is
            # no longer the one it approved.
            "status": WA_TPL_DRAFT,
            "rejected_reason": None,
            "last_submit_error": None,
            "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
            "updated_at": _now(),
        },
         "$setOnInsert": {**SHARED_KEY, "created_at": _now(), "active": True}},
        upsert=True,
    )
    saved = await get_template()
    # The composer identifies what it is editing by `_id`; one template for everybody means
    # that is simply the shared row.
    row = await col.find_one(SHARED_KEY)
    saved["_id"] = str(row["_id"]) if row else None
    saved["meta_template_id"] = existing.get("meta_template_id")
    return saved


async def submit_template(user: dict) -> dict:
    """Send the shared template to Meta for review.

    Meta assigns it an id and it enters PENDING; approval usually lands within minutes to
    hours and is picked up by `sync_template_status`. A REJECTED template is EDITED rather
    than recreated — it still occupies its name on the WABA, and a second create for the
    same name comes back "Content in this language already exists".
    """
    from app.services.meta_whatsapp_service import (
        MetaTemplateError, create_message_template, edit_message_template, is_configured,
    )

    col = _template_col()
    doc = await col.find_one(SHARED_KEY)
    if not doc:
        raise ValueError("Save the template before submitting it.")
    if not is_configured():
        raise ValueError("WhatsApp template management is not configured on this server.")

    status = str(doc.get("status") or WA_TPL_DRAFT).upper()
    if status not in WA_TPL_EDITABLE:
        raise ValueError(f"This template is already {status} at Meta — nothing to submit.")
    if not str(doc.get("meta_template_name") or "").strip():
        raise ValueError("Give the template a name before submitting it.")
    if not str(doc.get("body") or "").strip():
        raise ValueError("Write the message body before submitting it.")

    # The stored definition IS the Meta document — header, body, footer, buttons and
    # examples, exactly as the composer authored and validated them. Rebuilding a simpler
    # shape here would submit something different from what was reviewed on screen.
    meta_doc = {**doc, "name": doc.get("name") or doc.get("meta_template_name")}

    now = _now()
    existing_id = str(doc.get("meta_template_id") or "").strip()
    try:
        # The category is never sent on an edit. `authored_doc` fixes it at UTILITY for every
        # Leadership template, so there is nothing a re-submission could be changing it to —
        # and once Meta has approved a template it refuses the field outright, which is what
        # made "edit an approved invitation and send it back for review" impossible.
        result = (await edit_message_template(existing_id, meta_doc, include_category=False)
                  if existing_id else await create_message_template(meta_doc))
    except MetaTemplateError as e:
        # The template stays editable — record why so it shows on the row rather than only
        # in a toast that disappears.
        await col.update_one({"_id": doc["_id"]},
                             {"$set": {"last_submit_error": e.message, "updated_at": now}})
        raise ValueError(e.message)
    except Exception as e:                                        # pragma: no cover
        await col.update_one({"_id": doc["_id"]},
                             {"$set": {"last_submit_error": str(e), "updated_at": now}})
        raise ValueError(str(e))

    meta_status = str(result.get("status") or WA_TPL_PENDING).upper()
    await col.update_one({"_id": doc["_id"]}, {"$set": {
        "status": meta_status,
        "meta_template_id": str(result.get("id") or "") or None,
        "rejected_reason": None,
        "last_submit_error": None,
        "submitted_at": now, "synced_at": now, "updated_at": now,
        "submitted_by": (user or {}).get("full_name") or (user or {}).get("email"),
    }})
    logger.info("Leadership invitation template '%s' submitted — %s",
                meta_doc["name"], meta_status)
    return await get_template()


async def sync_template_status() -> dict:
    """Ask Meta where the shared template stands, and mirror the verdict locally.

    Meta reviews asynchronously and does not call us back for templates, so the status only
    moves when somebody asks. Called from the screen's Refresh, which is why it is cheap and
    safe to repeat.
    """
    from app.services.meta_whatsapp_service import fetch_templates, is_configured

    col = _template_col()
    doc = await col.find_one(SHARED_KEY)
    name = str((doc or {}).get("meta_template_name") or "").strip()
    if not doc or not name or not is_configured():
        return await get_template()

    try:
        rows = await fetch_templates()
    except Exception as e:                                        # pragma: no cover
        # Unreachable Meta is not a verdict. Leaving the stored status alone is what stops
        # a network blink reading as "your approved template disappeared".
        logger.warning("Leadership template sync failed: %s", e)
        return await get_template()

    # Bind to the template we actually submitted. Once Meta has issued an id, that id IS
    # the identity — matching on name alone would let this row pick up the verdict on a
    # legacy per-company template that happens to share the name. The name match survives
    # only for a row that has never been submitted, and reuse of a legacy name is refused
    # on save, so it can no longer resolve to a different template.
    language = str(doc.get("language") or "en")
    tpl_id = str(doc.get("meta_template_id") or "").strip()
    match = next((r for r in (rows or []) if tpl_id and str(r.get("id") or "") == tpl_id), None)
    if match is None and not tpl_id:
        match = next((r for r in (rows or [])
                      if str(r.get("name") or "") == name
                      and str(r.get("language") or "") == language), None)
    if not match:
        return await get_template()

    status = str(match.get("status") or "").upper()
    updates = {"status": status, "synced_at": _now(), "updated_at": _now(),
               "meta_template_id": str(match.get("id") or "") or doc.get("meta_template_id")}
    # Meta classifies a template itself, and its answer is final — one authored as UTILITY
    # can come back MARKETING, which changes how it is paced and who receives it. Recorded
    # SEPARATELY from the authored category so the screen can show the disagreement instead
    # of quietly adopting Meta's answer as though it had been the request all along.
    if match.get("category"):
        updates["meta_category"] = str(match["category"]).upper()
    updates["rejected_reason"] = (match.get("rejected_reason")
                                  if status == WA_TPL_REJECTED else None)
    await col.update_one({"_id": doc["_id"]}, {"$set": updates})
    return await get_template()


async def open_entry(assignment: dict, phone: str, status: str,
                     error: Optional[str] = None) -> str:
    """Record an attempt BEFORE it is made, and return the row id.

    Written first on purpose: a crash between "we decided to send" and "Meta answered"
    otherwise leaves no trace, and the invitation looks as though it was never attempted.
    """
    now = _now()
    doc = {
        "company_id": str(assignment.get("company_id")),
        "cycle": str(assignment.get("cycle")),
        "subject_id": str(assignment.get("subject_id")),
        "subject_name": assignment.get("subject_name"),
        "assignment_id": str(assignment.get("_id")),
        # Panel identity, which this collection is gated to HR for. It is NOT joinable to
        # any response — see the module docstring.
        "giver_id": str(assignment.get("giver_id") or ""),
        "giver_name": assignment.get("giver_name") or "",
        "phone": phone or "",
        "status": status,
        "error": error,
        "message_id": None,
        "attempts": 1,
        "created_at": now,
        "updated_at": now,
        f"{status}_at": now,
    }
    res = await get_collection(COLL_LS_WA_LOG).insert_one(doc)
    return str(res.inserted_id)


async def close_entry(entry_id: str, status: str, message_id: Optional[str] = None,
                      error: Optional[str] = None, meta_status: Optional[str] = None,
                      wa_id: Optional[str] = None) -> None:
    """Stamp the outcome of the attempt this row was opened for.

    `meta_status` is Meta's own verdict on the send — `accepted`, or
    `held_for_quality_assessment`, which returns an ordinary message id and is never
    delivered. Recorded here rather than in a second write, because this update is already
    touching the row.
    """
    updates = {"status": status, "updated_at": _now(), f"{status}_at": _now()}
    if message_id:
        updates["message_id"] = str(message_id)
    if error is not None:
        updates["error"] = error
    if meta_status:
        updates["message_status"] = str(meta_status)
    if wa_id:
        # What Meta resolved the number to. A missing wa_id means it does not recognise
        # that number on WhatsApp at all, which no other field records.
        updates["wa_id"] = str(wa_id)
    await get_collection(COLL_LS_WA_LOG).update_one(
        {"_id": ObjectId(entry_id)}, {"$set": updates})


async def apply_status(message_id: str, status: str,
                       error: Optional[str] = None) -> bool:
    """Move a logged message to `status`, if that is forward progress.

    Meta's delivery callbacks arrive out of order often enough that a late "sent" would
    otherwise drag a message that is already "read" backwards — `wa_is_forward` is what
    stops the ledger going into reverse. Returns whether anything changed.
    """
    if status not in (WA_SENT, WA_DELIVERED, WA_READ, WA_FAILED, WA_UNREACHABLE):
        return False
    col = get_collection(COLL_LS_WA_LOG)
    row = await col.find_one({"message_id": str(message_id)})
    if not row or not wa_is_forward(row.get("status") or WA_PENDING, status):
        return False

    updates = {"status": status, "updated_at": _now(), f"{status}_at": _now()}
    if error is not None:
        updates["error"] = error
    await col.update_one({"_id": row["_id"]}, {"$set": updates})
    return True


def _mask_phone(phone: str) -> str:
    """`••••8982` — enough to recognise a number you already know, not enough to collect
    one you do not. A raw list of every giver's mobile on an administrator's screen is a
    panel roster by another name."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return ("\u2022" * 4 + digits[-4:]) if len(digits) >= 4 else ""


async def company_log(company_id: Optional[str] = None, limit: int = 60) -> dict:
    """Recent WhatsApp send attempts, WITHOUT panel identity. No company means all of them.

    Deliberately drops giver_name, giver_id, subject_name and subject_id. This screen is
    administrators-only and they must not learn who gives feedback about whom — a delivery
    log carrying both names is exactly the join the whole module exists to prevent. What
    survives is what diagnoses a send: when it went, roughly where, what Meta said, and the
    id needed to look it up on Meta's own dashboard. None of that identifies anybody, which
    is what makes the unscoped read safe for staff.
    """
    scope = {"company_id": str(company_id)} if company_id else {}
    rows = await get_collection(COLL_LS_WA_LOG).find(
        scope).sort("created_at", -1).to_list(max(1, min(limit, 200)))

    counts: Dict[str, int] = {}
    out = []
    for r in rows:
        status = str(r.get("status") or WA_PENDING)
        counts[status] = counts.get(status, 0) + 1
        out.append({
            "id": str(r.get("_id")),
            "at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "cycle": r.get("cycle"),
            "status": status,
            "phone": _mask_phone(r.get("phone")),
            "error": r.get("error"),
            "message_id": r.get("message_id"),
            # Meta's own verdict on the send, when it gave one. `held_for_quality_assessment`
            # means the message was taken and will not be delivered — which looked identical
            # to a successful send until it was recorded.
            "message_status": r.get("message_status"),
            "attempts": r.get("attempts") or 1,
        })

    # Every row stops at `sent` when Meta has nowhere to report delivery to. Said on the
    # screen rather than left as a mystery, because "all sent, none delivered" reads as a
    # broken integration when it is actually an unconfigured callback.
    callbacks_ready = bool((settings.WHATSAPP_APP_SECRET or "").strip())

    return {"rows": out, "counts": counts, "total": len(out),
            "callbacks_configured": callbacks_ready}


async def cycle_tracking(company_id: str, cycle: str) -> dict:
    """Every send attempt for a cycle, newest first, with the counts the screen leads on."""
    rows = await get_collection(COLL_LS_WA_LOG).find({
        "company_id": str(company_id), "cycle": str(cycle),
    }).sort("updated_at", -1).to_list(5000)

    counts = {s: 0 for s in
              (WA_PENDING, WA_SENT, WA_DELIVERED, WA_READ, WA_FAILED, WA_UNREACHABLE)}
    out = []
    for r in rows:
        status = r.get("status") or WA_PENDING
        counts[status] = counts.get(status, 0) + 1
        out.append({
            "id": str(r["_id"]),
            "subject_id": r.get("subject_id"),
            "subject_name": r.get("subject_name"),
            "giver_name": r.get("giver_name"),
            "phone": r.get("phone"),
            "status": status,
            "error": r.get("error"),
            "attempts": r.get("attempts", 1),
            "sent_at": r.get("sent_at"),
            "delivered_at": r.get("delivered_at"),
            "read_at": r.get("read_at"),
            "failed_at": r.get("failed_at") or r.get("unreachable_at"),
            "updated_at": r.get("updated_at"),
        })
    return {"company_id": str(company_id), "cycle": str(cycle),
            "counts": counts, "rows": out, "total": len(out)}


# ─────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────
async def _giver_phone(giver_id: str) -> str:
    """The giver's number, from whichever collection holds them."""
    if not giver_id:
        return ""
    try:
        oid = ObjectId(str(giver_id))
    except Exception:
        return ""
    for coll in ("staff", "learners"):
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return str(doc.get("mobile") or doc.get("phone") or "").strip()
    return ""


def build_components(template: dict, context: Dict[str, str]) -> List[dict]:
    """The Cloud API `components` array for one send.

    Body parameters only. A survey invitation is a sentence and a link, and Leadership never
    had a way to author a header or button variable — the mapping existed but nothing could
    ever set it, so every send passed an empty list through two extra branches.

    An empty list is valid: a template with no variables at all needs no components.
    """
    custom = _custom_map((template or {}).get("variables"))
    used = body_variables((template or {}).get("body") or "", custom)
    if not used:
        return []
    # Meta addresses a NAMED template's parameters by `parameter_name`, so the order of this
    # list does not matter to it — but building it from the body means a variable the admin
    # removed simply stops being sent, with no positions to keep in step.
    return [{
        "type": "body",
        # A system variable comes from the invitation being sent; a custom one is the fixed
        # words the admin typed. Context wins, so a custom variable can never shadow the link.
        "parameters": [{"type": "text", "parameter_name": v,
                        "text": str(context.get(v, custom.get(v, "")))}
                       for v in used],
    }]




async def _post_template(phone: str, template_name: str, language: str,
                         components: List[dict], params: List[str]) -> dict:
    """Send one approved template and return {ok, message_id, error}.

    Leadership posts to Meta itself rather than calling notification_service.
    send_whatsapp_template, which returns a bare True/False. Delivered and Read arrive
    later as webhooks carrying only Meta's message id, so a sender that discards that id
    makes those two states permanently unreachable — the ledger could never move past
    `sent`. Widening the shared TPMS function's return type would change what every TPMS
    caller stores in its own log, so Leadership keeps its own sender, exactly as it keeps
    its own ledger.
    """
    import requests
    from app.services.notification_service import (
        _normalize_wa_phone, _wa_configured, _wa_endpoint, _wa_headers, log_notification,
    )

    if not _wa_configured():
        return {"ok": False, "error": "WhatsApp Cloud API credentials are not configured"}
    to = _normalize_wa_phone(phone)
    if not to:
        return {"ok": False, "error": f"'{phone}' is not a usable WhatsApp number"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language or "en"},
            "components": components,
        },
    }
    log_text = f"[leadership:{template_name}] " + " | ".join(str(p) for p in params)

    try:
        response = requests.post(_wa_endpoint(), json=payload,
                                 headers=_wa_headers(), timeout=20)
    except Exception as e:                                        # pragma: no cover
        logger.error("Leadership WhatsApp post failed for %s: %s", to, e)
        await log_notification(None, to, "whatsapp", "leadership_invite", log_text,
                               "failed", str(e))
        return {"ok": False, "error": str(e)}

    if response.status_code != 200:
        error = f"{response.status_code} - {response.text[:300]}"
        logger.error("Leadership WhatsApp refused for %s: %s", to, error)
        await log_notification(None, to, "whatsapp", "leadership_invite", log_text,
                               "failed", error)
        return {"ok": False, "error": error}

    # Meta answers {"messages":[{"id":"wamid...."}]}. That id is the only handle the later
    # delivered/read webhooks carry, so losing it here would strand the row at `sent`.
    # `message_status` is the field that separates "Meta will deliver this" from "Meta has
    # taken it and will not" — held_for_quality_assessment returns a perfectly ordinary
    # message id. Keeping only the id made those two outcomes indistinguishable.
    message_id = meta_status = wa_id = None
    try:
        body = response.json() or {}
        msg = (body.get("messages") or [{}])[0]
        message_id, meta_status = msg.get("id"), msg.get("message_status")
        wa_id = ((body.get("contacts") or [{}])[0]).get("wa_id")
    except Exception:
        pass
    await log_notification(None, to, "whatsapp", "leadership_invite", log_text, "sent")
    return {"ok": True, "message_id": message_id,
            "message_status": meta_status, "wa_id": wa_id}


async def send_invitation(assignment: dict, link: str) -> dict:
    """Send one giver their form link over WhatsApp, and log the attempt either way.

    Every exit writes a ledger row, including the ones that never reach Meta. A giver with
    no number on file is `unreachable`, not a silent skip — HR can only fix what the screen
    admits is broken.
    """
    company_id = str(assignment.get("company_id"))
    template = await get_template()

    # Transition only. The shared template is the one every invitation should go out on,
    # but Meta approval takes hours to days — so a company that was already sending on its
    # own approved template keeps sending on it until the shared one is approved, rather
    # than going dark for the length of a review it did not ask for. Once the shared
    # template is APPROVED this branch is never reached again, and the legacy rows it reads
    # can be dropped.
    if not template.get("is_ready"):
        legacy = await legacy_company_template(company_id)
        if legacy.get("is_ready"):
            logger.info("Leadership invitation for company %s sent on its legacy template "
                        "'%s' — the shared template is %s",
                        company_id, legacy.get("meta_template_name"), template.get("status"))
            template = legacy

    phone = await _giver_phone(assignment.get("giver_id"))
    if not phone:
        reason = "No mobile number on this person's record"
        entry = await open_entry(assignment, "", WA_UNREACHABLE, reason)
        return {"ok": False, "status": WA_UNREACHABLE, "entry_id": entry, "error": reason}

    if not template.get("is_ready"):
        reason = ("No WhatsApp invitation template has been written yet"
                  if not template.get("meta_template_name") else
                  f"The WhatsApp invitation template is {template.get('status')}, "
                  "so Meta will not deliver it")
        entry = await open_entry(assignment, phone, WA_FAILED, reason)
        return {"ok": False, "status": WA_FAILED, "entry_id": entry, "error": reason}

    entry = await open_entry(assignment, phone, WA_PENDING)

    # The window this giver is actually held to. Read from the cycle at SEND time rather
    # than copied onto the assignment when it was created, so an Open or Close date HR
    # edits afterwards is the one the next message states.
    from app.services.leadership_link_service import format_window_dt, message_window
    from app.services.leadership_service import get_cycle
    cyc = await get_cycle(company_id, str(assignment.get("cycle") or "")) or {}
    opens, closes = message_window(cyc)

    context = {
        "giver_name": assignment.get("giver_name") or "there",
        "leader_name": assignment.get("subject_name") or "your colleague",
        "feedback_link": link,
        "opens_at": format_window_dt(opens),
        "closes_at": format_window_dt(closes),
    }

    components = build_components(template, context)
    # The log line shows what was substituted, taken from the components actually sent
    # rather than recomputed — a log that can disagree with the message is worse than none.
    logged = [p.get("text", "") for c in components for p in c.get("parameters", [])]
    result = await _post_template(
        phone,
        template["meta_template_name"],
        template.get("language") or "en",
        components,
        logged,
    )
    if result.get("ok"):
        await close_entry(entry, WA_SENT, message_id=result.get("message_id"),
                          meta_status=result.get("message_status"),
                          wa_id=result.get("wa_id"))
        return {"ok": True, "status": WA_SENT, "entry_id": entry}

    reason = result.get("error") or "Delivery refused"
    await close_entry(entry, WA_FAILED, error=reason)
    return {"ok": False, "status": WA_FAILED, "entry_id": entry, "error": reason}


async def resend_invitation(assignment_id: str, link_builder) -> dict:
    """Re-send one invitation and count the attempt on its existing ledger rows."""
    doc = await get_collection(COLL_LS_ASSIGNMENTS).find_one({"_id": ObjectId(str(assignment_id))})
    if not doc:
        raise ValueError("This invitation no longer exists")
    await get_collection(COLL_LS_WA_LOG).update_many(
        {"assignment_id": str(assignment_id)}, {"$inc": {"attempts": 1}})
    return await send_invitation(doc, await link_builder(doc))
