"""Mongo document → clean, whitelisted dict.

Never serialize secrets (password hashes, tokens). Phase 0 stub; concrete
per-entity serializers land with the tools in Phase 1.
"""
from __future__ import annotations

from typing import Dict

from bson import ObjectId

# Fields that must never be returned to the model or the user.
SENSITIVE_FIELDS = {"password", "hashed_password", "password_hash", "token", "otp"}

# Personal contact details and auth metadata. These must never be surfaced by
# org-wide (admin) tools that return OTHER users'/companies' records, even if a
# caller mistakenly whitelists them. A user's own profile (get_my_profile) is a
# separate, deliberately permitted path and does not use serialize_public.
PII_FIELDS = {
    "email", "personal_email", "mobile", "phone", "contact", "whatsapp",
    "address", "pin", "gst",
    "last_login", "last_login_at", "login_count", "ip_address", "last_ip",
    "reset_token", "refresh_token", "access_token", "session_token",
    "google_id", "provider_id", "auth_provider", "permissions",
}


def strip_sensitive(doc: Dict) -> Dict:
    """Remove always-sensitive fields. Safe, used by future serializers."""
    return {k: v for k, v in (doc or {}).items() if k not in SENSITIVE_FIELDS}


def strip_pii(doc: Dict) -> Dict:
    """Remove contact details and auth metadata (PII_FIELDS) on top of secrets."""
    return {k: v for k, v in strip_sensitive(doc).items() if k not in PII_FIELDS}


def serialize(doc: Dict, allowed_fields) -> Dict:
    """Project a Mongo doc to a whitelisted set of fields.

    - Only `allowed_fields` are returned (plus a stringified `id` from `_id`).
    - Always-sensitive fields are dropped even if explicitly allowed.
    - `ObjectId` values are stringified so the result is JSON-serializable.
    """
    if not doc:
        return {}

    out: Dict = {}
    if "_id" in doc:
        out["id"] = str(doc["_id"])

    for field in allowed_fields:
        if field in SENSITIVE_FIELDS or field not in doc:
            continue
        value = doc[field]
        out[field] = str(value) if isinstance(value, ObjectId) else value

    return strip_sensitive(out)


def serialize_public(doc: Dict, allowed_fields) -> Dict:
    """Whitelist-project a doc, then hard-strip PII (emails, phones, auth metadata).

    Use for org-wide/admin tools that surface OTHER users' or companies' records.
    Acts as a backstop: even if `allowed_fields` includes a PII field, it is
    dropped from the output.
    """
    return strip_pii(serialize(doc, allowed_fields))
