"""
Shared builder for a WhatsApp Cloud API `components` array.

A Meta-approved template can take variables in three places — the text header, the body, and a
variable URL button — and each is addressed differently in the send payload. That mapping is
fiddly enough (buttons in particular are addressed by their own position in the template, not
by their position among the *variable* buttons) that it should exist once.

It was written for TPMS and lived in tpms_notify_service; Task & Delegation and the Checklist
repeat-task triggers need the identical structure, so it is lifted here verbatim in behaviour.
tpms_notify_service now delegates to it and its send payloads are byte-for-byte unchanged.

The caller supplies the FIELD NAMES that fill each slot plus the mapping of field name → value.
`guess` is an optional last-resort resolver for a field name the mapping doesn't know; TPMS
passes its heuristic guesser, other callers pass nothing.
"""
from typing import Callable, Dict, List, Optional

# Meta rejects a blank parameter outright, so an unresolved slot sends a dash rather than "".
EMPTY_PARAM = "-"


def resolve_params(keys, mapping: Dict[str, str],
                   guess: Optional[Callable[[str, Dict[str, str]], str]] = None) -> list:
    """Field names → the values Meta will substitute, in order."""
    out = []
    for key in (keys or []):
        value = mapping.get(key) if mapping else None
        if not value and guess:
            value = guess(key, mapping or {})
        out.append(str(value or EMPTY_PARAM))
    return out


def build_send_components(
    body_params: list,
    header_keys=None,
    button_keys=None,
    mapping: Optional[Dict[str, str]] = None,
    guess: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> Optional[list]:
    """The Cloud API `components` array for one send.

    Returns None when the template only takes body parameters, so the send layer keeps using
    its own body-only shape and nothing about that path changes. Header and button parameters
    are only produced for templates authored with them — the wiring row stores which data field
    fills each slot.
    """
    header_keys = header_keys or []
    button_keys = button_keys or []
    if not header_keys and not button_keys:
        return None

    mapping = mapping or {}
    components: List[dict] = []
    if header_keys:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": v}
                           for v in resolve_params(header_keys, mapping, guess)],
        })
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        })
    # Meta addresses button parameters by the button's own position in the template, one
    # component per button — hence the stored index rather than the loop counter. Rows written
    # before that was recorded stored bare field names; those fall back to their list position.
    for position, entry in enumerate(button_keys):
        field = entry.get("field") if isinstance(entry, dict) else entry
        index = entry.get("index", position) if isinstance(entry, dict) else position
        value = resolve_params([field], mapping, guess)[0]
        components.append({
            "type": "button", "sub_type": "url", "index": str(index),
            "parameters": [{"type": "text", "text": value}],
        })
    return components
