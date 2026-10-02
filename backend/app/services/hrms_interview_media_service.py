"""Interview reports and recordings, and the rule about who may keep a copy (spec §10).

    CV                  view + download
    Interview report    view
    Interview recording watch only

-- What "watch only" actually buys, and what it does not ---------------------------------
A browser must receive the bytes to play them. Anyone determined can keep a copy, and no
amount of server code changes that. Saying otherwise would be a false promise, so this
module does not make one.

What it does is remove every easy path and leave a trail on the hard one:

  * a client is never given a storage URL. The CV download hands out a presigned S3 link;
    a recording does not. The bytes come through our own endpoint.
  * that endpoint answers a short-lived token bound to ONE share, so a copied link is
    useless to anybody else and worthless within hours.
  * it sends `Content-Disposition: inline`, never `attachment`, and the UI offers no
    download control.
  * every view is audited against the client and the candidate.

Casual redistribution -- forwarding a link, saving from a right-click -- is what this stops.
Determined extraction is not, and the audit row is the answer to that.

-- Why not the document register ------------------------------------------------------------
`hrms_documents` is a filing cabinet for a person's paperwork: typed, verified, retained
against the employee. Interview evidence is about one CONVERSATION, is never verified, and
is shown to a client who holds no `document.read` at all. Filing it there would have meant
either granting clients that capability or bolting a second rule onto every document read.

House convention: services validate, gate and audit; routes only check the capability.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.config.settings import settings
from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_INTERVIEW_MEDIA_REMOVED, AUDIT_INTERVIEW_RECORDING_ADDED,
    AUDIT_INTERVIEW_RECORDING_VIEWED, AUDIT_INTERVIEW_REPORT_ADDED,
    AUDIT_INTERVIEW_REPORT_VIEWED, COLL_CANDIDATES, COLL_INTERVIEWS,
    ENTITY_CANDIDATE, MAX_RECORDING_BYTES, MAX_REPORT_BYTES, RECORDING_MIME,
    RECORDING_TOKEN_TTL_SECONDS, REPORT_MIME,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text, safe_filename

ENTITY_INTERVIEW = "interview"

# The two kinds of evidence, and everything that differs between them, in one table so a
# reader can see the whole rule rather than chase two near-identical code paths.
MEDIA_SPEC = {
    "report": {
        "field": "report",
        "mime": REPORT_MIME,
        "max_bytes": MAX_REPORT_BYTES,
        "label": "Interview report",
        "audit_added": AUDIT_INTERVIEW_REPORT_ADDED,
        "audit_viewed": AUDIT_INTERVIEW_REPORT_VIEWED,
        # A report is a PDF the browser renders. "View" and "download" are the same act for
        # a PDF, so this is inline and honest about it rather than pretending otherwise.
        "client_may_download": False,
    },
    "recording": {
        "field": "recording",
        "mime": RECORDING_MIME,
        "max_bytes": MAX_RECORDING_BYTES,
        "label": "Interview recording",
        "audit_added": AUDIT_INTERVIEW_RECORDING_ADDED,
        "audit_viewed": AUDIT_INTERVIEW_RECORDING_VIEWED,
        "client_may_download": False,
    },
}


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _spec(kind: str) -> dict:
    if kind not in MEDIA_SPEC:
        raise HTTPException(
            status_code=422,
            detail=f"Kind must be one of: {', '.join(sorted(MEDIA_SPEC))}.")
    return MEDIA_SPEC[kind]


async def _require_interview(company_id: str, interview_no: str) -> dict:
    doc = await get_collection(COLL_INTERVIEWS).find_one(
        {"interview_no": interview_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Interview not found.")
    return doc


def _decode(payload: dict, spec: dict) -> tuple:
    """Validate and decode an upload. Returns (raw, name, mime) or (None, None, None) when
    the caller supplied a link instead of bytes.

    Size is checked against the DECLARED length before decoding, so a 2 GB body is refused
    without ever being held in memory, and again after -- the declared figure is supplied by
    the caller and is not evidence of anything.
    """
    if payload.get("external_url"):
        return None, None, None

    data = payload.get("data") or ""
    if not data:
        raise HTTPException(
            status_code=422,
            detail=f"Attach a file, or give a link to where the "
                   f"{spec['label'].lower()} already lives.")

    mime = (payload.get("mime_type") or "").strip().lower()
    if mime not in spec["mime"]:
        raise HTTPException(
            status_code=415,
            detail=(f"{spec['label']}: that file type is not accepted. "
                    f"Use one of: {', '.join(sorted(spec['mime']))}."))

    if "," in data[:120] and data[:5].lower() == "data:":
        data = data.split(",", 1)[1]
    limit_mb = spec["max_bytes"] // 1024 // 1024
    if len(data) > (spec["max_bytes"] * 4 // 3) + 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{spec['label']} is too large. The limit is {limit_mb} MB.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400,
                            detail=f"{spec['label']} could not be read.")
    if not raw:
        raise HTTPException(status_code=400, detail=f"{spec['label']} is empty.")
    if len(raw) > spec["max_bytes"]:
        raise HTTPException(
            status_code=413,
            detail=f"{spec['label']} is too large. The limit is {limit_mb} MB.")
    name = safe_filename(clean_text(payload.get("name"), limit=180) or "interview")
    return raw, name, mime


# ─────────────────────────────────────────────────────────────
# Writes — Sparsh side
# ─────────────────────────────────────────────────────────────
async def attach_media(actor: dict, company_id: str, interview_no: str, kind: str,
                       payload: dict) -> dict:
    """Attach a report or a recording to one interview.

    Replacing keeps the previous entry in `<kind>_history` rather than overwriting it. A
    client may already have watched the old one, and a record that silently changes under
    an audit row saying somebody watched "the recording" is not a record.
    """
    spec = _spec(kind)
    interview = await _require_interview(company_id, interview_no)
    raw, name, mime = _decode(payload, spec)

    now = datetime.now(timezone.utc)
    entry = {
        "name": name,
        "mime_type": mime,
        "notes": clean_text(payload.get("notes"), limit=2000),
        "uploaded_by": str((actor or {}).get("_id") or ""),
        "uploaded_by_name": _actor_name(actor),
        "uploaded_at": now,
    }

    if raw is None:
        # A link to where it already lives. Stored as given; the client player treats an
        # external recording as an embed rather than a stream, and the no-download rule is
        # then the hosting tool's to keep, which is stated plainly in the UI.
        url = clean_text(payload.get("external_url"), limit=1000)
        if not str(url or "").lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="A link must start with http:// or https://.")
        entry.update({"external_url": url, "key": None,
                      "name": name or "external recording"})
    else:
        from app.services.s3_service import upload_file_to_s3_with_key
        try:
            stored = upload_file_to_s3_with_key(
                io.BytesIO(raw), f"{kind}_{interview_no}_{name}", mime)
        except Exception as e:
            print(f"[WARN] HRMS {kind} upload failed for {interview_no}: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"The {spec['label'].lower()} could not be uploaded right now. "
                       f"Please try again.")
        entry.update({"key": stored.get("key"), "size_bytes": len(raw),
                      "external_url": None})

    if kind == "recording" and payload.get("duration_minutes") is not None:
        try:
            entry["duration_minutes"] = max(0, int(payload["duration_minutes"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422,
                                detail="Duration must be a whole number of minutes.")

    updates = {spec["field"]: entry, "updated_at": now}
    push = {}
    previous = interview.get(spec["field"])
    if previous:
        push = {f"{spec['field']}_history": {**previous, "replaced_at": now}}

    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)},
        {"$set": updates, **({"$push": push} if push else {})})
    await audit(actor, spec["audit_added"], ENTITY_INTERVIEW, interview_no,
                f"{spec['label']} for {interview.get('candidate_name')}"
                + (" (replaced)" if previous else ""), company_id)
    return await get_media(company_id, interview_no)


async def remove_media(actor: dict, company_id: str, interview_no: str,
                       kind: str) -> dict:
    """Detach evidence. The stored object is left in place, as the document register does:
    an audit row saying a client watched something must not point at nothing."""
    spec = _spec(kind)
    interview = await _require_interview(company_id, interview_no)
    if not interview.get(spec["field"]):
        raise HTTPException(status_code=404,
                            detail=f"No {spec['label'].lower()} is attached.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)},
        {"$set": {spec["field"]: None, "updated_at": now},
         "$push": {f"{spec['field']}_history":
                   {**interview[spec["field"]], "removed_at": now,
                    "removed_by": str((actor or {}).get("_id") or "")}}})
    await audit(actor, AUDIT_INTERVIEW_MEDIA_REMOVED, ENTITY_INTERVIEW, interview_no,
                spec["label"], company_id)
    return await get_media(company_id, interview_no)


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
def _summarise(entry: Optional[dict], *, for_client: bool) -> Optional[dict]:
    """What a caller is told ABOUT a piece of evidence, before they open it.

    The storage key is stripped for a client for the same reason it is on a share: it is our
    layout, and their access runs through a token bound to their own share.
    """
    if not entry:
        return None
    out = {
        "name": entry.get("name"),
        "mime_type": entry.get("mime_type"),
        "notes": entry.get("notes"),
        "uploaded_at": entry.get("uploaded_at"),
        "duration_minutes": entry.get("duration_minutes"),
        "is_external": bool(entry.get("external_url")),
    }
    if for_client:
        return out
    out.update({"key": entry.get("key"), "external_url": entry.get("external_url"),
                "uploaded_by_name": entry.get("uploaded_by_name"),
                "size_bytes": entry.get("size_bytes")})
    return out


async def get_media(company_id: str, interview_no: str, *,
                    for_client: bool = False) -> dict:
    interview = await _require_interview(company_id, interview_no)
    return {
        "interview_no": interview_no,
        "uk": interview.get("uk"),
        "round": interview.get("round"),
        "scheduled_at": interview.get("scheduled_at"),
        "status": interview.get("status"),
        "outcome": interview.get("outcome"),
        "report": _summarise(interview.get("report"), for_client=for_client),
        "recording": _summarise(interview.get("recording"), for_client=for_client),
    }


async def interviews_for_candidate(company_id: str, uk: str, *,
                                   for_client: bool = False) -> list:
    """Every interview for one candidate, newest first, with what evidence each carries.

    Used by the candidate hub on the Sparsh side and by the client's own candidate view --
    the same reads, differing only in whether storage keys come back.
    """
    rows = await get_collection(COLL_INTERVIEWS).find(
        {"company_id": str(company_id), "uk": uk}).sort("scheduled_at", -1).to_list(50)
    out = []
    for r in rows:
        item = {
            "interview_no": r.get("interview_no"),
            "round": r.get("round"),
            "mode": r.get("mode"),
            "scheduled_at": r.get("scheduled_at"),
            "duration_min": r.get("duration_min"),
            "status": r.get("status"),
            "outcome": r.get("outcome"),
            "report": _summarise(r.get("report"), for_client=for_client),
            "recording": _summarise(r.get("recording"), for_client=for_client),
        }
        if not for_client:
            # Scores and the panel are Sparsh's assessment of the conversation. A client is
            # shown the REPORT, which is what we chose to write for them; the raw
            # competency numbers and who sat on the panel are not theirs.
            item.update({
                "interviewer_name": r.get("interviewer_name"),
                "average_score": r.get("average_score"),
                "remarks": r.get("remarks"),
                "panel": r.get("panel"),
            })
        out.append(item)
    return out


# ─────────────────────────────────────────────────────────────
# The watch token
# ─────────────────────────────────────────────────────────────
# Bound to (interview, kind, share) so a link is useless outside the share it was minted
# for -- a client who forwards it to another client hands over something that will not open,
# because the recipient's own share number is not the one inside the signature.
def mint_token(interview_no: str, kind: str, share_no: str,
               ttl: int = RECORDING_TOKEN_TTL_SECONDS) -> dict:
    expiry = int(time.time()) + int(ttl)
    return {"interview_no": interview_no, "kind": kind, "share_no": share_no,
            "expires": expiry,
            "signature": _sign(interview_no, kind, share_no, expiry)}


def _sign(interview_no: str, kind: str, share_no: str, expiry: int) -> str:
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    message = f"{interview_no}|{kind}|{share_no}|{expiry}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_token(interview_no: str, kind: str, share_no: str, expires: str,
                 signature: str) -> tuple:
    """(ok, reason). The reason is for the log; the caller sees one message however it
    failed, because telling somebody which half of a link was wrong helps only a guesser."""
    try:
        expiry = int(expires)
    except (TypeError, ValueError):
        return False, "malformed expiry"
    if expiry < int(time.time()):
        return False, "expired"
    expected = _sign(interview_no, kind, share_no, expiry)
    if not hmac.compare_digest(expected, str(signature or "")):
        return False, "bad signature"
    return True, ""


async def open_stream(actor: dict, company_id: str, interview_no: str, kind: str,
                      share_no: str) -> dict:
    """The bytes (or the external link) for one piece of evidence, plus how to serve it.

    Returns a dict the route turns into a response. The route does not decide the
    disposition -- that rule belongs with the rule about who may keep a copy.
    """
    spec = _spec(kind)
    interview = await _require_interview(company_id, interview_no)
    entry = interview.get(spec["field"])
    if not entry:
        raise HTTPException(status_code=404,
                            detail=f"No {spec['label'].lower()} is attached.")

    await audit(actor, spec["audit_viewed"], ENTITY_INTERVIEW, interview_no,
                f"{spec['label']} for {interview.get('candidate_name')} "
                f"(share {share_no})", company_id)

    if entry.get("external_url"):
        return {"external_url": entry["external_url"], "name": entry.get("name")}

    from app.services.s3_service import get_signed_url
    # NO `download_as`. That parameter sets Content-Disposition: attachment, which is
    # exactly what this must not do -- it is the difference between the CV route and this
    # one, and the whole of spec §10's distinction lives in that one omitted argument.
    url = get_signed_url(entry["key"], expires_in=RECORDING_TOKEN_TTL_SECONDS)
    if not url:
        raise HTTPException(
            status_code=503,
            detail=f"The {spec['label'].lower()} could not be opened right now.")
    return {"stream_url": url, "name": entry.get("name"),
            "mime_type": entry.get("mime_type"),
            "duration_minutes": entry.get("duration_minutes")}
