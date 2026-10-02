"""HRMS > public surface guard.

Everything that protects the module's only internet-facing endpoints: rate limiting, code
validation, upload validation and PII-safe errors.

-- Why this is its own module ------------------------------------------------------
The public routes are the one place in HRMS reachable with no token, by anyone, and they
accept files and personal data. Concentrating their defences here means the protections can
be reviewed in one sitting rather than inferred from four handlers, and a new public route
gets them by calling one function.

-- Why a DB-backed limiter rather than app/assistant/ratelimit.py -------------------
That limiter is in-process (its own docstring says a shared store is needed for multi-worker
deployments). For an authenticated assistant that is a reasonable trade. For an
INTERNET-FACING surface it is not: state is lost on restart and is not shared across
workers or containers, so an attacker spreading requests across workers multiplies their
effective limit. Reusing it would also couple HRMS's public-surface security to another
module's config, which the scope rule discourages.

-- Fixed window, deliberately -------------------------------------------------------
A sliding window must store every hit timestamp, so a flood makes the limiter's own storage
grow -- the defence becomes an amplifier. A fixed-window counter is O(1) storage per key per
window and cannot be made to grow. The cost is boundary burst (up to 2x the limit across a
window edge), which is an acceptable trade for abuse prevention rather than billing.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, Request

from app.db.mongodb import get_collection
from app.models.hrms import (
    ALLOWED_UPLOAD_MIME, COLL_PUBLIC_RATELIMIT, MAX_UPLOAD_BYTES, POSTING_CODE_RE,
)

# (limit, window_seconds) per scope.
#   view   -- browsing a job ad is cheap; be generous so a shared office IP is not blocked.
#   apply  -- creates a candidate and stores files; the expensive, abusable one.
#   posting-- a per-code ceiling, so one viral/targeted ad cannot be used to flood the DB
#             even from many different IPs.
RATE_LIMITS = {
    "view":          (60, 60),       # 60 per minute per IP
    "apply":         (5, 3600),      # 5 applications per hour per IP
    "apply-posting": (200, 3600),    # 200 applications per hour per posting code
    # Assessment links are per-candidate and unguessable, so the risk is not mass abuse but
    # brute-forcing a code. A tight per-IP ceiling on views makes enumeration hopeless
    # long before the 128-bit keyspace does.
    "assess-view":   (30, 60),       # 30 per minute per IP
    "assess-submit": (10, 3600),     # 10 submissions per hour per IP
    # An offer link is read repeatedly (a candidate re-reads terms, shows a partner) but
    # responded to once, so viewing is generous and responding is tight.
    "offer-view":    (40, 60),       # 40 per minute per IP
    "offer-respond": (10, 3600),     # 10 responses per hour per IP
    # The pre-onboarding form is long and carries files, so a new hire reasonably reloads
    # it, opens it on a second device and retries a failed upload. Viewing is therefore
    # generous; submitting is tight because it is a once-only act.
    "onboard-view":   (40, 60),      # 40 per minute per IP
    "onboard-submit": (10, 3600),    # 10 submissions per hour per IP
    # Phase 11-R: an appointment letter is read like an offer (repeatedly) and acknowledged
    # once, so the same generous-view / tight-act split applies.
    "appointment-view": (40, 60),    # 40 per minute per IP
    "appointment-ack":  (10, 3600),  # 10 acknowledgements per hour per IP
    # Phase INT-2: the new-hire experience surveys. A survey is opened, thought about, and
    # answered once -- so viewing is generous (people come back to it) and submitting is
    # tight, exactly as the offer and onboarding surfaces are. Deliberately identical
    # figures rather than new ones: a limit invented per endpoint is a limit nobody can
    # reason about across the surface.
    "survey-view":    (40, 60),      # 40 per minute per IP
    "survey-submit":  (10, 3600),    # 10 submissions per hour per IP
}

# Deliberately vague: a public error must never reveal whether a code exists, who applied,
# or what the system knows. "Invalid link" covers not-found, malformed and wrong-tenant
# alike, mirroring how /auth/forgot-password answers identically for known and unknown
# emails.
INVALID_LINK = "This application link is not valid."
CLOSED_LINK = "This position is no longer accepting applications."
RATE_LIMITED = "Too many requests. Please try again later."


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    Honours X-Forwarded-For because this app is deployed behind nginx (see nginx.conf /
    docker-compose). Only the FIRST hop is used -- the rest of the header is client-supplied
    and trivially forged. Falls back to the socket peer.

    NOTE: a determined attacker behind a rotating proxy pool can still spread load. That is
    why `apply-posting` exists as a second, IP-independent ceiling.
    """
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()[:64]
    return (getattr(request.client, "host", None) or "unknown")[:64]


async def enforce_rate_limit(scope: str, identifier: str) -> None:
    """Raise 429 when `identifier` has exceeded the limit for `scope`.

    Atomic: a single find_one_and_update increments and reads in one round trip, so
    concurrent requests cannot both observe an under-limit count.

    Fails OPEN. If the rate-limit store is unavailable, the module keeps serving rather than
    refusing every applicant -- availability of a hiring form is worth more than perfect
    throttling, and the per-code ceiling plus the upload limits remain in force.
    """
    limit, window = RATE_LIMITS.get(scope, (60, 60))
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // window
    key = f"{scope}:{identifier}:{bucket}"

    try:
        from pymongo import ReturnDocument
        doc = await get_collection(COLL_PUBLIC_RATELIMIT).find_one_and_update(
            {"_id": key},
            {"$inc": {"count": 1},
             "$setOnInsert": {
                 "scope": scope,
                 # TTL cleanup only -- expiry is enforced by the bucket arithmetic above, so
                 # a late sweep can never widen the window.
                 "expires_at": now + timedelta(seconds=window * 2),
             }},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        count = int((doc or {}).get("count", 1))
    except Exception as e:
        print(f"[WARN] HRMS rate-limit store unavailable ({scope}): {e}")
        return

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=RATE_LIMITED,
            headers={"Retry-After": str(window)},
        )


def validate_posting_code(code: str) -> str:
    """Validate a public code BEFORE it reaches a query.

    Two jobs. It rejects malformed codes with the same opaque message as a missing one, so
    the endpoint cannot be used as an existence oracle. And because the value is
    pattern-checked against `^[A-Z]{2}-[A-Z0-9]{6}$` before any database call, a crafted
    value can never reach Mongo as an operator document -- NoSQL operator injection is
    structurally impossible here, not merely unlikely.
    """
    # `isinstance` first, deliberately. FastAPI coerces a path parameter to str, so a dict
    # cannot arrive here through HTTP -- but this is the last line of defence for a public
    # surface, and a non-string reaching `.strip()` would raise AttributeError and surface
    # as a 500 rather than the opaque 404 the contract promises. A guard that crashes on
    # unexpected input is not a guard.
    if not isinstance(code, str):
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    code = code.strip().upper()
    if not POSTING_CODE_RE.match(code):
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    return code


def new_access_code() -> str:
    """Mint an unguessable access code for a candidate-specific link.

    `secrets.token_urlsafe(16)` is 128 bits of cryptographic randomness. This is deliberately
    NOT the posting-code generator: a posting code is a short public identifier shared on a
    job board, whereas an access code is the ONLY thing protecting one candidate's
    assessment, offer or onboarding record.

    The source used ~40 bits from `Math.random()` for exactly this purpose and its own
    analysis called the result "enumerable-adjacent" while carrying PAN, Aadhaar and bank
    details (BACKEND_ANALYSIS 7.5). 128 CSPRNG bits ends that argument.
    """
    import secrets
    return secrets.token_urlsafe(16)


# token_urlsafe output alphabet. Bounded 20-64 so a malformed value is rejected before it
# reaches a query, exactly as posting codes are.
ACCESS_CODE_RE = _AC_RE = __import__("re").compile(r"^[A-Za-z0-9_-]{20,64}$")


def validate_access_code(code: str) -> str:
    """Validate a candidate-link access code BEFORE it reaches a query.

    Same contract as validate_posting_code: pattern first, identical opaque 404 for
    malformed and unknown alike, so the endpoint is never an existence oracle and a crafted
    value can never arrive at Mongo as an operator document.

    Note it does NOT upper-case: unlike a posting code, this value is case-SENSITIVE --
    normalising it would collapse the keyspace and throw away entropy.
    """
    # Non-string first -- see the note in validate_posting_code.
    if not isinstance(code, str):
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    code = code.strip()
    if not ACCESS_CODE_RE.match(code):
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    return code


async def assert_link_live(code: str) -> None:
    """Refuse a REVOKED or EXPIRED public link (Phase 11-R, Item 1).

    Called by every public handler BEFORE it does any work, which is what makes revocation
    real rather than cosmetic. A registry that merely displayed a "Revoked" chip while the
    link kept serving would be worse than no registry at all.

    Three properties worth stating:

    1. **Legacy links are never locked out.** A code with no registry row -- every link
       issued before this phase -- reads as live and passes. Failing closed here would break
       every outstanding offer and onboarding link the moment this shipped, which is not a
       trade a hiring system gets to make.

    2. **The error is the EXISTING vague one.** A revoked link answers with exactly the same
       CLOSED_LINK message a finished posting gives, so the endpoint cannot be used to
       distinguish "this was withdrawn from you specifically" from "this role is filled".

    3. **It fails OPEN on infrastructure trouble**, matching enforce_rate_limit. If the
       registry is unreachable, a candidate can still complete their onboarding form; the
       access code itself remains 128 bits of protection.
    """
    if not code:
        return
    try:
        from datetime import datetime as _dt
        from app.db.mongodb import get_collection
        from app.models.hrms import (
            COLL_LINKS, LIVE_LINK_STATUSES, effective_link_status,
        )
        doc = await get_collection(COLL_LINKS).find_one({"code": code})
        if not doc:
            return                                   # legacy / unregistered — see (1)
        today = _dt.now(timezone.utc).strftime("%Y-%m-%d")
        status = effective_link_status(doc, today)
        live = {s.value for s in LIVE_LINK_STATUSES}
    except Exception as e:
        # Catches HTTPException too, deliberately. `get_db()` raises HTTPException(503) when
        # Mongo is unreachable, so re-raising HTTPException here would turn every public
        # page into a 503 the moment the database hiccuped -- a bookkeeping lookup taking
        # down the applicant-facing surface is exactly the failure mode this guard must not
        # have. The intentional 410 below is raised OUTSIDE this block, so it is unaffected.
        print(f"[WARN] HRMS link-status check unavailable ({code}): {e}")
        return                                       # fail open — see (3)

    if status not in live:
        # 410 Gone, matching how a closed posting answers: the link was real, this is over.
        raise HTTPException(status_code=410, detail=CLOSED_LINK)


def decode_upload(upload, *, label: str = "File") -> Tuple[bytes, str, str]:
    """Validate and decode one base64 upload. Returns (raw_bytes, filename, mime_type).

    Order matters: the declared size is checked BEFORE decoding, so a 1 GB payload is
    rejected without ever being materialised in memory. The decoded size is then re-checked,
    because the declared length is attacker-controlled.

    Accepts an `UploadIn` OR a plain dict. Both shapes genuinely occur: the routes hand
    services `body.model_dump()`, which recursively turns nested models into dicts, while
    tests and internal callers pass the model. Reading only attributes silently produced an
    empty mime type for the dict shape and rejected every real upload with 415 -- see
    PHASE_9_REPORT Finding #1.
    """
    if upload is None:
        return b"", "", ""

    def field(key: str) -> str:
        if isinstance(upload, dict):
            return upload.get(key) or ""
        return getattr(upload, key, "") or ""

    data = field("data")
    name = (field("name") or "file").strip()[:180]
    mime = field("mime_type").strip().lower()

    if mime not in ALLOWED_UPLOAD_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"{label}: that file type is not accepted. Use PDF, Word or an image.")

    # Strip a data: URL prefix if the browser sent one.
    if "," in data[:120] and data[:5].lower() == "data:":
        data = data.split(",", 1)[1]

    # base64 expands ~4/3, so this bounds the decoded size without decoding.
    if len(data) > (MAX_UPLOAD_BYTES * 4 // 3) + 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{label} is too large. The limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")

    import base64
    import binascii
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} could not be read.")

    if not raw:
        raise HTTPException(status_code=400, detail=f"{label} is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{label} is too large. The limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")

    return raw, safe_filename(name), mime


def safe_filename(name: str) -> str:
    """Reduce an attacker-supplied filename to something inert.

    The name reaches an S3 key and is later shown in the UI, so path separators, traversal
    sequences and control characters are stripped rather than escaped. A name that reduces
    to nothing becomes 'file'.
    """
    import re
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"\.{2,}", ".", name)
    name = re.sub(r"[^A-Za-z0-9._\- ]", "_", name).strip(" .")
    return name[:120] or "file"


def clean_text(value: Optional[str], *, limit: int = 500) -> Optional[str]:
    """Normalise a free-text field from an untrusted form.

    Control characters are removed and length is capped so a form field cannot be used to
    store megabytes. HTML is NOT escaped here: React escapes on render, and escaping at the
    boundary would double-encode legitimate characters such as & in a company name. The
    value is stored inert and rendered inert.
    """
    if value is None:
        return None
    import re
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value)).strip()
    return text[:limit] or None
