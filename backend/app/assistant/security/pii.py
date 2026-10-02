"""PII detection / redaction helpers.

Primary PII protection is field whitelisting in utils/serializers.py (other
users' data never enters tool output). This module is an output-side backstop
for free text (e.g. knowledge snippets) when redaction is desired.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?\d[\d\s-]{8,}\d)\b")
_LONG_DIGITS = re.compile(r"\b\d{12,}\b")  # card/long identifiers


def detect(text: str) -> dict:
    text = text or ""
    return {
        "email": bool(_EMAIL.search(text)),
        "phone": bool(_PHONE.search(text)),
        "long_digits": bool(_LONG_DIGITS.search(text)),
    }


def redact(text: str) -> str:
    if not text:
        return text
    text = _EMAIL.sub("[email]", text)
    text = _LONG_DIGITS.sub("[redacted]", text)
    text = _PHONE.sub("[phone]", text)
    return text
