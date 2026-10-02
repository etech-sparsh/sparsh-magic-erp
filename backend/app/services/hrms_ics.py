"""HRMS > RFC 5545 calendar invites.

Pure text generation: no I/O, no clock, no DB. Given interview facts it returns a VCALENDAR
string, which makes it trivially testable and safe to call from anywhere.

-- Why hand-rolled rather than a library --------------------------------------------
A single VEVENT is about forty lines of well-specified text. Adding a dependency to the
shared requirements.txt for that would be a poor trade, and the escaping rules that actually
matter (RFC 5545 s3.3.11) are three characters.

-- Timezone ------------------------------------------------------------------------
Times are emitted in UTC with a trailing `Z`. This is the one form every calendar client
resolves identically, so an invite is never off by an hour for a participant in another
zone. Naive datetimes are ASSUMED to be IST and converted, because the rest of the ERP works
in IST (see the Phase 12/13 date discipline).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

# The ERP's operating timezone. Naive input is interpreted here before conversion to UTC.
IST = timezone(timedelta(hours=5, minutes=30))

# RFC 5545 s3.1: lines SHOULD NOT exceed 75 octets, continued with CRLF + a single space.
_MAX_LINE = 74


def _escape(value: str) -> str:
    """Escape a TEXT value per RFC 5545 s3.3.11.

    Backslash first -- escaping it after the others would double-escape the ones just
    inserted.
    """
    if value is None:
        return ""
    return (str(value)
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n"))


def _fold(line: str) -> str:
    """Fold a long content line. Folding is on octets, not characters, so a multi-byte
    character is never split across a boundary."""
    raw = line.encode("utf-8")
    if len(raw) <= _MAX_LINE:
        return line
    out, start = [], 0
    limit = _MAX_LINE
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Back off to a codepoint boundary.
        while end > start and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        out.append(raw[start:end].decode("utf-8"))
        start = end
        limit = _MAX_LINE - 1          # continuation lines carry a leading space
    return "\r\n ".join(out)


def _utc(value: datetime) -> str:
    """Format a datetime as a UTC iCalendar stamp."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_invite(
    *,
    uid: str,
    summary: str,
    start: datetime,
    duration_min: int,
    description: str = "",
    location: str = "",
    organizer_email: Optional[str] = None,
    attendee_emails: Optional[List[str]] = None,
    url: Optional[str] = None,
    sequence: int = 0,
    cancelled: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """Build a VCALENDAR containing one VEVENT.

    `sequence` must INCREASE on every update to the same `uid` -- that is how a calendar
    client knows a reschedule supersedes the original rather than creating a second entry.

    `cancelled` emits METHOD:CANCEL and STATUS:CANCELLED, which removes the event from a
    participant's calendar instead of leaving a stale booking behind.

    `now` is injectable so output is deterministic in tests; it defaults to the real clock.
    """
    stamp = _utc(now or datetime.now(timezone.utc))
    end = start + timedelta(minutes=max(1, int(duration_min or 1)))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sparsh ERP//HRMS//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{'CANCEL' if cancelled else 'REQUEST'}",
        "BEGIN:VEVENT",
        f"UID:{_escape(uid)}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_utc(start)}",
        f"DTEND:{_utc(end)}",
        f"SEQUENCE:{int(sequence)}",
        f"SUMMARY:{_escape(summary)}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        "TRANSP:OPAQUE",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if url:
        lines.append(f"URL:{_escape(url)}")
    if organizer_email:
        lines.append(f"ORGANIZER:mailto:{organizer_email}")
    for email in (attendee_emails or []):
        if email:
            lines.append(
                "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:"
                f"mailto:{email}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    # CRLF line endings are mandatory (RFC 5545 s3.1); LF-only breaks strict parsers.
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
