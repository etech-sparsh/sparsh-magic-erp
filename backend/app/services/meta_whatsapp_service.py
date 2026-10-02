"""
TPMS ▸ Meta WhatsApp **template management** (Graph API).

The existing send layer (app/services/notification_service.py) talks to
`/{phone_number_id}/messages` — it *sends* against templates a human had already approved by
hand in WhatsApp Manager. This module is the other half: it talks to
`/{waba_id}/message_templates`, so a TPMS admin can author a template in the CRM, submit it to
Meta for review, and track APPROVED / PENDING / REJECTED without leaving the app.

Same credentials, same Graph version, same WhatsApp Business Account — nothing here opens a
second integration. `WHATSAPP_BUSINESS_ACCOUNT_ID` was already declared in settings and unused;
this is what it is for.

Layout:
  · variable parsing + validation   — the rules Meta enforces, applied before we ever call out
  · build_create_payload()          — a stored document → the exact Graph JSON ("Check payload")
  · Graph calls                     — create / list / delete / media-handle upload
  · approved_template_names()       — the gate the notification mapping is checked against

Every Graph call is blocking `requests` (the dependency this project already has) run through
asyncio.to_thread, so the event loop is never held.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.config.settings import settings
from app.models.tpms import (
    META_BUTTON_PHONE_NUMBER, META_BUTTON_QUICK_REPLY, META_BUTTON_TYPES, META_BUTTON_URL,
    META_CATEGORIES, META_CATEGORY_AUTHENTICATION, META_HEADER_FORMATS, META_HEADER_NONE,
    META_HEADER_TEXT, META_LIMIT_BODY, META_LIMIT_BUTTON_TEXT, META_LIMIT_FOOTER,
    META_LIMIT_HEADER, META_LIMIT_NAME, META_MAX_BUTTONS, META_MAX_PHONE_BUTTONS,
    META_MAX_URL_BUTTONS, META_MEDIA_HEADERS, META_STATUS_APPROVED, META_STATUS_PENDING,
    META_VAR_NAMED, META_VAR_NUMBERED, META_VAR_STYLES,
)

logger = logging.getLogger(__name__)

GRAPH_TIMEOUT = 30

# {{1}} / {{customer_name}} — the two styles Meta accepts. One per template, never mixed.
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_NAMED_VAR_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class MetaTemplateError(Exception):
    """A Graph API call was rejected. `message` is already user-facing — Meta's
    `error_user_msg` when it supplied one, its `message` otherwise."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 payload: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
def is_configured() -> bool:
    """True when template management can reach Meta. Needs the WABA id on top of the
    credentials the send layer uses — templates live on the business account, not the number."""
    return bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_BUSINESS_ACCOUNT_ID)


def config_status() -> dict:
    """What the UI banner reports, so a missing env var is visible rather than showing up as a
    failed submit later."""
    return {
        "configured": is_configured(),
        "api_version": settings.WHATSAPP_API_VERSION,
        "waba_id": settings.WHATSAPP_BUSINESS_ACCOUNT_ID or None,
        "sending_configured": bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID),
        "media_upload_configured": bool(settings.WHATSAPP_APP_ID),
    }


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}


def _templates_endpoint() -> str:
    return (f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
            f"/{settings.WHATSAPP_BUSINESS_ACCOUNT_ID}/message_templates")


def _require_config() -> None:
    if not is_configured():
        raise MetaTemplateError(
            "WhatsApp template management is not configured. Set WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_BUSINESS_ACCOUNT_ID in the backend environment.")


def _graph_error(response: requests.Response) -> MetaTemplateError:
    """Meta nests the useful sentence in error.error_user_msg; error.message is the developer
    string. Prefer the former, fall back through to raw text so nothing is ever swallowed."""
    detail, payload = response.text, {}
    try:
        payload = response.json() or {}
        err = payload.get("error") or {}
        detail = err.get("error_user_msg") or err.get("message") or detail
        title = err.get("error_user_title")
        if title and title not in detail:
            detail = f"{title}: {detail}"
    except ValueError:
        pass
    return MetaTemplateError(f"Meta rejected the request — {detail}",
                             status_code=response.status_code, payload=payload)


# ─────────────────────────────────────────────────────────────
# Variables
# ─────────────────────────────────────────────────────────────
def extract_variables(text: str) -> List[str]:
    """Every {{token}} in order of appearance, duplicates kept — position is what Meta
    counts for numbered templates."""
    return _VAR_RE.findall(text or "")


def ordered_body_variables(text: str, style: str) -> List[str]:
    """The distinct variables a body declares, in the order their first {{…}} appears.

    For numbered templates this is what maps 1:1 onto the positional parameters at send time;
    for named templates it is the parameter-name list."""
    seen, out = set(), []
    for token in extract_variables(text):
        if token not in seen:
            seen.add(token)
            out.append(token)
    if style == META_VAR_NUMBERED:
        # Sort numerically so {{2}} appearing before {{1}} still yields [1, 2]; the sequence
        # check in validate() is what refuses a genuinely broken numbering.
        try:
            out.sort(key=int)
        except (TypeError, ValueError):
            pass
    return out


def detect_variable_style(text: str) -> Optional[str]:
    """'numbered', 'named', or None when the text has no variables. Returns 'mixed' when both
    styles are present — which Meta rejects outright."""
    tokens = extract_variables(text)
    if not tokens:
        return None
    numbered = [t for t in tokens if t.isdigit()]
    named = [t for t in tokens if not t.isdigit()]
    if numbered and named:
        return "mixed"
    return META_VAR_NUMBERED if numbered else META_VAR_NAMED


def _has_adjacent_variables(text: str) -> bool:
    """Meta rejects `{{1}} {{2}}` with nothing between them — a parameter must be separated
    from the next by real copy."""
    return bool(re.search(r"\}\}\s*\{\{", text or ""))


def _starts_or_ends_with_variable(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return bool(re.match(r"^\{\{", stripped) or re.search(r"\}\}$", stripped))


# ─────────────────────────────────────────────────────────────
# Validation — Meta's rules, applied here so a bad template never costs a round trip
# ─────────────────────────────────────────────────────────────
def validate_template(doc: dict) -> List[str]:
    """Return a list of human-readable problems. Empty list = ready to submit.

    These mirror the constraints the Cloud API documents; anything Meta checks that we cannot
    know locally (duplicate name on the WABA, policy review) still comes back from the submit
    call and is surfaced as the rejection reason."""
    errors: List[str] = []

    name = str(doc.get("name") or "").strip()
    if not name:
        errors.append("Template name is required.")
    elif not _NAME_RE.match(name):
        errors.append("Template name may only contain lowercase letters, numbers and "
                      "underscores — Meta rejects anything else.")
    elif len(name) > META_LIMIT_NAME:
        errors.append(f"Template name must be {META_LIMIT_NAME} characters or fewer.")

    if not str(doc.get("language") or "").strip():
        errors.append("Language is required.")

    category = str(doc.get("category") or "").strip().upper()
    if category not in META_CATEGORIES:
        errors.append(f"Category must be one of {', '.join(META_CATEGORIES)}.")

    # Authentication templates carry no author-written copy — Meta generates the body and the
    # only permitted button is the one-time-password button.
    if category == META_CATEGORY_AUTHENTICATION:
        minutes = doc.get("code_expiration_minutes")
        if minutes not in (None, ""):
            try:
                minutes = int(minutes)
            except (TypeError, ValueError):
                errors.append("Code expiry must be a whole number of minutes.")
            else:
                if not 1 <= minutes <= 90:
                    errors.append("Code expiry must be between 1 and 90 minutes.")
        return errors

    style = str(doc.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    if style not in META_VAR_STYLES:
        errors.append("Type of variable must be either numbered or named.")
        style = META_VAR_NUMBERED

    errors += _validate_header(doc, style)
    errors += _validate_body(doc, style)
    errors += _validate_footer(doc)
    errors += _validate_buttons(doc)
    return errors


def _validate_header(doc: dict, style: str) -> List[str]:
    errors: List[str] = []
    fmt = str(doc.get("header_format") or META_HEADER_NONE).strip().upper()
    if fmt not in META_HEADER_FORMATS:
        return [f"Header must be one of {', '.join(META_HEADER_FORMATS)}."]
    if fmt == META_HEADER_NONE:
        return errors

    if fmt == META_HEADER_TEXT:
        text = str(doc.get("header_text") or "").strip()
        if not text:
            errors.append("A text header needs header text.")
        elif len(text) > META_LIMIT_HEADER:
            errors.append(f"Header text must be {META_LIMIT_HEADER} characters or fewer.")
        variables = extract_variables(text)
        if len(variables) > 1:
            errors.append("A header may contain at most one variable.")
        if variables:
            found = detect_variable_style(text)
            if found == "mixed" or (found and found != style):
                errors.append("The header uses a different variable style from the body — "
                              "Meta rejects a mix.")
            examples = [e for e in (doc.get("header_examples") or []) if str(e).strip()]
            if not examples:
                errors.append("Give a sample value for the header variable — Meta requires an "
                              "example for every variable.")
    elif fmt in META_MEDIA_HEADERS:
        if not (str(doc.get("header_handle") or "").strip()
                or str(doc.get("header_media_url") or "").strip()):
            errors.append(f"A {fmt.lower()} header needs a sample file — paste a public URL to "
                          "the sample media (or an existing Meta media handle).")
    return errors


def _validate_body(doc: dict, style: str) -> List[str]:
    errors: List[str] = []
    body = str(doc.get("body") or "").strip()
    if not body:
        return ["Body is required."]
    if len(body) > META_LIMIT_BODY:
        errors.append(f"Body must be {META_LIMIT_BODY} characters or fewer "
                      f"(currently {len(body)}).")

    found = detect_variable_style(body)
    if found == "mixed":
        errors.append("The body mixes {{1}} and {{named}} variables — pick one style; Meta "
                      "rejects a template that uses both.")
        return errors
    if found and found != style:
        errors.append(f"The body uses {found} variables but the template is set to {style}.")
        return errors

    variables = ordered_body_variables(body, style)
    if variables:
        if _starts_or_ends_with_variable(body):
            errors.append("The body cannot start or end with a variable — Meta requires text "
                          "around every parameter.")
        if _has_adjacent_variables(body):
            errors.append("Two variables cannot sit next to each other — put some text between "
                          "them.")
        if style == META_VAR_NUMBERED:
            expected = [str(i) for i in range(1, len(variables) + 1)]
            if variables != expected:
                errors.append("Numbered variables must run 1, 2, 3 … with no gaps — found "
                              + ", ".join("{{%s}}" % v for v in variables) + ".")
        else:
            bad = [v for v in variables if not _NAMED_VAR_RE.match(v)]
            if bad:
                errors.append("Named variables must be lowercase words starting with a letter — "
                              "fix " + ", ".join("{{%s}}" % v for v in bad) + ".")

        examples = [str(e).strip() for e in (doc.get("body_examples") or [])]
        if len(examples) < len(variables) or any(not e for e in examples[:len(variables)]):
            errors.append("Give a sample value for every body variable — Meta requires an "
                          "example for each one before it will review the template.")
    return errors


def _validate_footer(doc: dict) -> List[str]:
    footer = str(doc.get("footer") or "").strip()
    if not footer:
        return []
    errors = []
    if len(footer) > META_LIMIT_FOOTER:
        errors.append(f"Footer must be {META_LIMIT_FOOTER} characters or fewer.")
    if extract_variables(footer):
        errors.append("Footers cannot contain variables.")
    return errors


def _validate_buttons(doc: dict) -> List[str]:
    buttons = doc.get("buttons") or []
    if not buttons:
        return []
    errors: List[str] = []
    if len(buttons) > META_MAX_BUTTONS:
        errors.append(f"A template may have at most {META_MAX_BUTTONS} buttons.")

    seen_text, urls, phones = set(), 0, 0
    for i, btn in enumerate(buttons, start=1):
        btype = str((btn or {}).get("type") or "").strip().upper()
        text = str((btn or {}).get("text") or "").strip()
        if btype not in META_BUTTON_TYPES:
            errors.append(f"Button {i}: type must be one of {', '.join(META_BUTTON_TYPES)}.")
            continue
        if not text:
            errors.append(f"Button {i}: label is required.")
        elif len(text) > META_LIMIT_BUTTON_TEXT:
            errors.append(f"Button {i}: label must be {META_LIMIT_BUTTON_TEXT} characters or fewer.")
        key = text.lower()
        if key and key in seen_text:
            errors.append(f"Button {i}: two buttons cannot share the label “{text}”.")
        seen_text.add(key)

        if btype == META_BUTTON_URL:
            urls += 1
            url = str((btn or {}).get("url") or "").strip()
            if not url:
                errors.append(f"Button {i}: a URL button needs a URL.")
            elif not url.lower().startswith(("http://", "https://")):
                errors.append(f"Button {i}: the URL must start with http:// or https://.")
            variables = extract_variables(url)
            if len(variables) > 1:
                errors.append(f"Button {i}: a URL may contain at most one variable, at the end.")
            elif variables and not url.rstrip().endswith("}}"):
                errors.append(f"Button {i}: a URL variable must be the last part of the URL.")
            if variables and not str((btn or {}).get("url_example") or "").strip():
                errors.append(f"Button {i}: give a sample full URL — Meta requires an example "
                              "for a variable URL.")
        elif btype == META_BUTTON_PHONE_NUMBER:
            phones += 1
            phone = str((btn or {}).get("phone_number") or "").strip()
            if not phone:
                errors.append(f"Button {i}: a call button needs a phone number.")
            elif not re.match(r"^\+?\d{6,20}$", phone):
                errors.append(f"Button {i}: enter the phone number in international format, "
                              "e.g. +919876543210.")

    if urls > META_MAX_URL_BUTTONS:
        errors.append(f"At most {META_MAX_URL_BUTTONS} URL buttons are allowed.")
    if phones > META_MAX_PHONE_BUTTONS:
        errors.append(f"At most {META_MAX_PHONE_BUTTONS} call button is allowed.")
    return errors


# ─────────────────────────────────────────────────────────────
# Document → Graph payload
# ─────────────────────────────────────────────────────────────
def _example_slice(values: List[Any], count: int) -> List[str]:
    """Exactly `count` sample strings, padded so a short list can never produce a ragged
    example array (Meta 400s on one)."""
    out = [str(v) for v in (values or [])][:count]
    out += [""] * (count - len(out))
    return out


def build_components(doc: dict) -> List[dict]:
    """The `components` array for POST /{waba_id}/message_templates."""
    category = str(doc.get("category") or "").strip().upper()
    if category == META_CATEGORY_AUTHENTICATION:
        return _build_authentication_components(doc)

    style = str(doc.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    components: List[dict] = []

    # ── header ──
    fmt = str(doc.get("header_format") or META_HEADER_NONE).strip().upper()
    if fmt == META_HEADER_TEXT:
        header_text = str(doc.get("header_text") or "")
        component = {"type": "HEADER", "format": "TEXT", "text": header_text}
        header_vars = extract_variables(header_text)
        if header_vars:
            samples = _example_slice(doc.get("header_examples"), len(header_vars))
            if style == META_VAR_NAMED:
                component["example"] = {"header_text_named_params": [
                    {"param_name": v, "example": s} for v, s in zip(header_vars, samples)]}
            else:
                component["example"] = {"header_text": samples}
        components.append(component)
    elif fmt in META_MEDIA_HEADERS:
        handle = str(doc.get("header_handle") or "").strip()
        component = {"type": "HEADER", "format": fmt}
        if handle:
            component["example"] = {"header_handle": [handle]}
        components.append(component)

    # ── body ──
    body = str(doc.get("body") or "")
    component = {"type": "BODY", "text": body}
    body_vars = ordered_body_variables(body, style)
    if body_vars:
        samples = _example_slice(doc.get("body_examples"), len(body_vars))
        if style == META_VAR_NAMED:
            component["example"] = {"body_text_named_params": [
                {"param_name": v, "example": s} for v, s in zip(body_vars, samples)]}
        else:
            # Numbered examples are a list *of lists* — one inner list per example set.
            component["example"] = {"body_text": [samples]}
    components.append(component)

    # ── footer ──
    footer = str(doc.get("footer") or "").strip()
    if footer:
        components.append({"type": "FOOTER", "text": footer})

    # ── buttons ──
    buttons = [_button_payload(b) for b in (doc.get("buttons") or [])]
    buttons = [b for b in buttons if b]
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})

    return components


def _button_payload(btn: dict) -> Optional[dict]:
    btype = str((btn or {}).get("type") or "").strip().upper()
    text = str((btn or {}).get("text") or "").strip()
    if btype == META_BUTTON_QUICK_REPLY:
        return {"type": "QUICK_REPLY", "text": text}
    if btype == META_BUTTON_URL:
        url = str(btn.get("url") or "").strip()
        out = {"type": "URL", "text": text, "url": url}
        if extract_variables(url):
            out["example"] = [str(btn.get("url_example") or "").strip()]
        return out
    if btype == META_BUTTON_PHONE_NUMBER:
        return {"type": "PHONE_NUMBER", "text": text,
                "phone_number": str(btn.get("phone_number") or "").strip()}
    return None


def _build_authentication_components(doc: dict) -> List[dict]:
    """Authentication templates have a fixed shape: Meta writes the copy, we only choose
    whether to append the security warning, how long the code is valid, and the label on the
    copy-code button."""
    components: List[dict] = [{
        "type": "BODY",
        "add_security_recommendation": bool(doc.get("add_security_recommendation", True)),
    }]
    minutes = doc.get("code_expiration_minutes")
    if minutes not in (None, ""):
        try:
            components.append({"type": "FOOTER", "code_expiration_minutes": int(minutes)})
        except (TypeError, ValueError):
            pass
    label = ""
    for btn in (doc.get("buttons") or []):
        label = str((btn or {}).get("text") or "").strip()
        if label:
            break
    components.append({"type": "BUTTONS", "buttons": [
        {"type": "OTP", "otp_type": "COPY_CODE", "text": label or "Copy code"}]})
    return components


def _url_button_sample(button: dict) -> str:
    """The value Meta substitutes into a variable URL button.

    The button carries a whole sample URL but the send API wants only the part that replaces
    the variable, so the static prefix is subtracted: url 'https://x.io/f/{{1}}' with example
    'https://x.io/f/AB12' yields 'AB12'."""
    url = str(button.get("url") or "")
    example = str(button.get("url_example") or "").strip()
    prefix = url.split("{{", 1)[0]
    if example.startswith(prefix):
        return example[len(prefix):] or "sample"
    return example or "sample"


def _fill(text: str, variables: List[str], examples: List[Any]) -> str:
    """Substitute each {{var}} with its sample value, leaving unfilled ones visible as tokens
    so a missing example is obvious in the preview rather than silently blank."""
    out = str(text or "")
    values = list(examples or [])
    for i, name in enumerate(variables):
        sample = str(values[i]).strip() if i < len(values) else ""
        if sample:
            out = out.replace("{{%s}}" % name, sample)
    return out


def build_sample_send_components(doc: dict) -> Tuple[List[dict], List[str]]:
    """Components + body values for a *test send* of an approved template, using the sample
    values the template was reviewed with. Returns (components, body_params) — the second is
    only for the delivery log.

    This is the send-time shape (lowercase `type`, `parameters`), which is a different schema
    from build_components()'s create-time shape. They are not interchangeable."""
    category = str(doc.get("category") or "").strip().upper()
    if category == META_CATEGORY_AUTHENTICATION:
        # Meta requires the code in the body *and* echoed into the copy-code button.
        code = "123456"
        return ([
            {"type": "body", "parameters": [{"type": "text", "text": code}]},
            {"type": "button", "sub_type": "url", "index": "0",
             "parameters": [{"type": "text", "text": code}]},
        ], [code])

    style = str(doc.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    components: List[dict] = []

    fmt = str(doc.get("header_format") or META_HEADER_NONE).strip().upper()
    if fmt == META_HEADER_TEXT:
        header_vars = extract_variables(doc.get("header_text") or "")
        if header_vars:
            samples = _example_slice(doc.get("header_examples"), len(header_vars))
            components.append({"type": "header", "parameters": [
                {"type": "text", "text": s or "sample"} for s in samples]})
    elif fmt in META_MEDIA_HEADERS:
        link = str(doc.get("header_media_url") or "").strip()
        if link:
            key = fmt.lower()   # image | video | document
            components.append({"type": "header",
                               "parameters": [{"type": key, key: {"link": link}}]})

    body_vars = ordered_body_variables(doc.get("body") or "", style)
    body_params = [s or "sample" for s in _example_slice(doc.get("body_examples"), len(body_vars))]
    if body_params:
        components.append({"type": "body", "parameters": [
            {"type": "text", "text": p} for p in body_params]})

    for index, button in enumerate(doc.get("buttons") or []):
        if str((button or {}).get("type") or "").upper() != META_BUTTON_URL:
            continue
        if not extract_variables(button.get("url") or ""):
            continue
        components.append({"type": "button", "sub_type": "url", "index": str(index),
                           "parameters": [{"type": "text", "text": _url_button_sample(button)}]})

    return components, body_params


def render_preview_text(doc: dict) -> str:
    """The template flattened to a plain-text message, sample values filled in.

    Used to test a template Meta has *not* approved yet: a template message would be refused,
    but the same copy can go out as a free-form message so the wording can still be read on a
    phone. Buttons are listed rather than rendered — free-form text has no button chrome."""
    category = str(doc.get("category") or "").strip().upper()
    if category == META_CATEGORY_AUTHENTICATION:
        return "123456 is your verification code."

    style = str(doc.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    lines: List[str] = []

    fmt = str(doc.get("header_format") or META_HEADER_NONE).strip().upper()
    if fmt == META_HEADER_TEXT and (doc.get("header_text") or "").strip():
        header_vars = extract_variables(doc.get("header_text") or "")
        lines.append("*%s*" % _fill(doc.get("header_text"), header_vars,
                                    doc.get("header_examples")).strip())
    elif fmt in META_MEDIA_HEADERS:
        lines.append(f"[{fmt.lower()} header]")

    body_vars = ordered_body_variables(doc.get("body") or "", style)
    body = _fill(doc.get("body"), body_vars, doc.get("body_examples")).strip()
    if body:
        lines.append(body)

    footer = str(doc.get("footer") or "").strip()
    if footer:
        lines.append(footer)

    labels = [str((b or {}).get("text") or "").strip() for b in (doc.get("buttons") or [])]
    labels = [l for l in labels if l]
    if labels:
        lines.append("Buttons: " + "  |  ".join(labels))

    return "\n\n".join(lines)


def build_create_payload(doc: dict) -> dict:
    """The complete JSON body sent to Meta. This is what the modal's "Check payload" shows —
    what you review is byte-for-byte what gets submitted.

    `parameter_format` declares which placeholder syntax the template uses, and Meta defaults it
    to POSITIONAL when it is absent. Leaving it off meant a {{named}} template was reviewed as if
    it were {{1}}-style, where `{{date}}` is not a valid placeholder at all: Meta created the
    template, discarded the body_text_named_params examples it could not parse, and rejected it
    immediately with INVALID_FORMAT."""
    style = str(doc.get("variable_style") or META_VAR_NUMBERED).strip().lower()
    return {
        "name": str(doc.get("name") or "").strip(),
        "language": str(doc.get("language") or "en").strip(),
        "category": str(doc.get("category") or "").strip().upper(),
        "parameter_format": "NAMED" if style == META_VAR_NAMED else "POSITIONAL",
        "components": build_components(doc),
    }


# ─────────────────────────────────────────────────────────────
# Graph calls
# ─────────────────────────────────────────────────────────────
def _post_template(payload: dict) -> dict:
    response = requests.post(_templates_endpoint(), json=payload, headers=_headers(),
                             timeout=GRAPH_TIMEOUT)
    if response.status_code not in (200, 201):
        raise _graph_error(response)
    return response.json() or {}


async def create_message_template(doc: dict) -> dict:
    """Submit a template to Meta for review.

    Returns Meta's `{id, status, category}`. A template lands in PENDING and is reviewed
    within minutes-to-hours; poll with fetch_templates() to pick up the verdict."""
    _require_config()
    payload = build_create_payload(doc)
    result = await asyncio.to_thread(_post_template, payload)
    logger.info("Submitted WhatsApp template '%s' (%s) to Meta — id=%s status=%s",
                payload["name"], payload["language"], result.get("id"), result.get("status"))
    return result


def _post_template_edit(template_id: str, payload: dict) -> dict:
    response = requests.post(
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{template_id}",
        json=payload, headers=_headers(), timeout=GRAPH_TIMEOUT)
    if response.status_code not in (200, 201):
        raise _graph_error(response)
    return response.json() or {}


async def edit_message_template(template_id: str, doc: dict, *,
                                include_category: bool = True) -> dict:
    """Correct a template Meta already holds and put it back into review.

    Creating is not an option once the name exists on the WABA — Meta answers a second create
    with 2388024 "Content in this language already exists" — so a REJECTED template can only be
    fixed in place. Name and language are immutable and are dropped from the payload; the rest
    (parameter_format, components, and optionally category) is what gets re-reviewed.

    `include_category=False` omits the category. Meta REFUSES a category on a template it has
    already approved — "Cannot update an approved template category" — which a caller hits
    whenever it edits approved wording, because the template is approved at Meta even while
    the caller's own copy has gone back to draft. Callers whose category is fixed and can
    never change should pass False; there is nothing to send and it is the only way the edit
    succeeds. Defaults to True so existing callers submit exactly the payload they always did.

    Returns the same `{id, status, category}` shape as create_message_template, read back from
    Meta, because the edit call itself answers only `{"success": true}`."""
    _require_config()
    payload = build_create_payload(doc)
    name = payload.pop("name", "")
    payload.pop("language", None)
    if not include_category:
        payload.pop("category", None)
    await asyncio.to_thread(_post_template_edit, template_id, payload)

    rows = await fetch_templates(name=name) if name else []
    current = next((r for r in rows if str(r.get("id")) == str(template_id)), None)
    status = str((current or {}).get("status") or META_STATUS_PENDING).upper()
    logger.info("Edited WhatsApp template '%s' at Meta — id=%s status=%s", name, template_id, status)
    return {
        "id": template_id,
        "status": status,
        "category": (current or {}).get("category") or payload.get("category"),
    }


def _get_templates(params: dict) -> dict:
    response = requests.get(_templates_endpoint(), params=params, headers=_headers(),
                            timeout=GRAPH_TIMEOUT)
    if response.status_code != 200:
        raise _graph_error(response)
    return response.json() or {}


async def fetch_templates(name: Optional[str] = None, limit: int = 200) -> List[dict]:
    """Every template on the WABA (optionally filtered to one name), following Meta's cursor
    pagination. This is the source of truth for approval status."""
    _require_config()
    params = {
        "fields": "id,name,language,status,category,rejected_reason,quality_score,components",
        "limit": min(int(limit or 200), 250),
    }
    if name:
        params["name"] = name

    out: List[dict] = []
    page = await asyncio.to_thread(_get_templates, params)
    while True:
        out.extend(page.get("data") or [])
        after = ((page.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (page.get("paging") or {}).get("next") or len(out) >= 1000:
            break
        page = await asyncio.to_thread(_get_templates, {**params, "after": after})
    return out


def _delete_template(params: dict) -> dict:
    response = requests.delete(_templates_endpoint(), params=params, headers=_headers(),
                               timeout=GRAPH_TIMEOUT)
    if response.status_code != 200:
        raise _graph_error(response)
    return response.json() or {}


async def delete_message_template(name: str, template_id: Optional[str] = None) -> dict:
    """Delete a template from the WABA. Passing the id deletes just that language;
    name alone deletes every language of it."""
    _require_config()
    params: Dict[str, Any] = {"name": name}
    if template_id:
        params["hsm_id"] = template_id
    return await asyncio.to_thread(_delete_template, params)


# ─────────────────────────────────────────────────────────────
# Media sample upload (IMAGE / VIDEO / DOCUMENT headers)
# ─────────────────────────────────────────────────────────────
_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "mp4": "video/mp4", "pdf": "application/pdf",
}


def _upload_handle(file_bytes: bytes, mime: str) -> str:
    """Meta's Resumable Upload API: open a session, push the bytes, get back the `h` handle
    a template's header example needs. Two calls, both against the *app*, not the WABA."""
    version = settings.WHATSAPP_API_VERSION
    start = requests.post(
        f"https://graph.facebook.com/{version}/{settings.WHATSAPP_APP_ID}/uploads",
        params={"file_length": len(file_bytes), "file_type": mime,
                "access_token": settings.WHATSAPP_ACCESS_TOKEN},
        timeout=GRAPH_TIMEOUT)
    if start.status_code != 200:
        raise _graph_error(start)
    session_id = (start.json() or {}).get("id")
    if not session_id:
        raise MetaTemplateError("Meta did not return an upload session for the sample media.")

    finish = requests.post(
        f"https://graph.facebook.com/{version}/{session_id}",
        data=file_bytes,
        headers={"Authorization": f"OAuth {settings.WHATSAPP_ACCESS_TOKEN}",
                 "file_offset": "0", "Content-Type": "application/octet-stream"},
        timeout=GRAPH_TIMEOUT * 2)
    if finish.status_code != 200:
        raise _graph_error(finish)
    handle = (finish.json() or {}).get("h")
    if not handle:
        raise MetaTemplateError("Meta did not return a media handle for the sample media.")
    return handle


def _download(url: str) -> Tuple[bytes, str]:
    response = requests.get(url, timeout=GRAPH_TIMEOUT, stream=True)
    if response.status_code != 200:
        raise MetaTemplateError(f"Could not download the sample media ({response.status_code}). "
                                "The URL must be publicly reachable.")
    content = response.content
    if len(content) > 16 * 1024 * 1024:
        raise MetaTemplateError("Sample media must be 16 MB or smaller.")
    mime = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    if not mime or mime == "application/octet-stream":
        ext = url.rsplit(".", 1)[-1].split("?")[0].lower()
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
    return content, mime


async def resolve_header_handle(doc: dict) -> Optional[str]:
    """Turn a media header's sample URL into the handle Meta wants, uploading it if we haven't
    already. Returns the existing handle untouched when one is stored, so re-submitting a
    corrected template does not re-upload the sample."""
    fmt = str(doc.get("header_format") or META_HEADER_NONE).strip().upper()
    if fmt not in META_MEDIA_HEADERS:
        return None
    handle = str(doc.get("header_handle") or "").strip()
    if handle:
        return handle
    url = str(doc.get("header_media_url") or "").strip()
    if not url:
        return None
    if not settings.WHATSAPP_APP_ID:
        raise MetaTemplateError(
            "Uploading sample media needs WHATSAPP_APP_ID in the backend environment. Either "
            "set it, or paste a media handle you already hold.")
    content, mime = await asyncio.to_thread(_download, url)
    return await asyncio.to_thread(_upload_handle, content, mime)


# ─────────────────────────────────────────────────────────────
# The approval gate
# ─────────────────────────────────────────────────────────────
async def approved_template_names() -> Optional[set]:
    """Names Meta currently reports as APPROVED on the WABA.

    Returns None — meaning "could not be determined" — when template management is not
    configured or Graph is unreachable. Callers must treat None as *unknown*, not as *empty*:
    refusing every template because the network blinked would take TPMS notifications down."""
    if not is_configured():
        return None
    try:
        rows = await fetch_templates()
    except MetaTemplateError as e:
        logger.warning("Could not read approved WhatsApp templates from Meta: %s", e.message)
        return None
    except Exception as e:                                    # noqa: BLE001 — never fatal
        logger.warning("Could not read approved WhatsApp templates from Meta: %s", e)
        return None
    return {str(r.get("name") or "").strip()
            for r in rows
            if str(r.get("status") or "").strip().upper() == META_STATUS_APPROVED
            and r.get("name")}
