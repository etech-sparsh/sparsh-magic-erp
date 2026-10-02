"""HRMS > referral capture (Phase 11-R, Item 5).

ONE resolver, used by BOTH intake paths — the public application form and the manual
add-candidate modal. A referral typed by an applicant and one entered by HR on a walk-in CV
must be validated identically and stored identically, or reporting can tell them apart and
the numbers stop meaning one thing.

-- PRIVACY: the public form must never become an employee directory ------------------------
This is the constraint that shaped the whole module. The applicant TYPES an employee code;
the server resolves it. There is deliberately:

  * no public endpoint that reads hrms_employee_profiles,
  * no autocomplete, no picker, no "did you mean",
  * and ONE opaque message for every failure — unknown code, wrong company, malformed,
    inactive — so the form cannot be used as an oracle to discover who works somewhere.

That is the same discipline hrms_public_guard.INVALID_LINK applies to posting codes, and the
same reasoning: an error that distinguishes "no such thing" from "not yours" is an
information leak wearing a helpful face.

-- Validation order ------------------------------------------------------------------------
The code is pattern-checked against EMPLOYEE_CODE_RE BEFORE any database call, so a crafted
value can never reach Mongo as an operator document. Structurally impossible, not merely
unlikely.

-- A failed lookup does not reject the application ------------------------------------------
...except when the applicant explicitly claimed an EMPLOYEE referral, where the code IS the
claim. For every other referral source the code is optional context; losing an application
because somebody mistyped a colleague's staff number would be a poor trade.
"""
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_EMPLOYEE_PROFILES, EMPLOYEE_CODE_RE, INVALID_EMPLOYEE_CODE,
    REFERRAL_SOURCE_LABEL, ReferralSource,
)
from app.utils.hrms_public_guard import clean_text


async def resolve_referral(payload: dict, company_id: str, *,
                           source_from_applicant: bool = True) -> dict:
    """Validate the discovery / referral block and return the fields to store.

    Two jobs, because the form asks two related questions:

      1. WHERE DID YOU FIND THIS JOB -- always captured when answered, and stored as the
         candidate's `source`. This is why one posting needs only ONE form link rather than
         a link per platform: the channel is captured from the applicant instead of
         inferred from which URL they happened to click.
      2. WERE YOU REFERRED -- optional, and only then are the referrer fields required.

    Returns `{}` when neither was answered, so a caller can `doc.update(...)` it
    unconditionally and an application from before this phase is unchanged.

    `source_from_applicant` says whose answer owns `source`. On the public form it is the
    applicant's -- nobody else knows which channel they came through. On the manual
    add-candidate path HR picks the source themselves from a CV in front of them, so their
    choice must not be silently replaced; a declared REFERRAL still wins there, because a
    referral is what that candidate is regardless of who typed it.

    Raises 422 with a field-naming message when a referral claim is incomplete, and the
    deliberately opaque INVALID_EMPLOYEE_CODE when an employee code does not resolve.
    """
    source = getattr(payload.get("referral_source"), "value", payload.get("referral_source"))
    if source and source not in {s.value for s in ReferralSource}:
        raise HTTPException(status_code=422, detail="Choose a valid referral source.")

    if not payload.get("is_referral"):
        # Not a referral, but the applicant told us how they found the role -- and that
        # answer IS the source. A posting no longer carries a platform to infer one from:
        # there is a single link, shared wherever the company likes, so the only party who
        # knows which channel worked is the applicant. `referral_source` keeps the same
        # value so the two breakdowns still line up.
        if not source:
            return {}
        out = {"referral_source": source, "is_referral": False}
        if source_from_applicant:
            out["source"] = source
        return out

    referred_by = clean_text(payload.get("referred_by"), limit=140)

    # Both are required the moment the applicant says "yes, I was referred" -- a referral
    # with neither a referrer nor a channel records nothing and would quietly pollute the
    # source breakdown with an empty bucket.
    if not referred_by:
        raise HTTPException(
            status_code=422, detail="Enter the name of the person who referred you.")
    if not source:
        raise HTTPException(
            status_code=422, detail="Choose where you heard about this role.")

    out = {
        "is_referral": True,
        "referred_by": referred_by,
        "referral_source": source,
        "referral_relation": clean_text(payload.get("referral_relation"), limit=120),
        "referrer_employee_code": None,
        "referrer_name": None,
        "referrer_user_id": None,
        # Referrals land in the EXISTING Phase 10 `source` breakdown rather than needing a
        # parallel dimension -- one fewer way for two screens to disagree on a total.
        "source": REFERRAL_SOURCE_LABEL,
    }

    raw_code = (payload.get("referrer_employee_code") or "").strip().upper()

    if source == ReferralSource.EMPLOYEE.value:
        # The code IS the claim here, so it is mandatory and must resolve.
        if not raw_code:
            raise HTTPException(
                status_code=422,
                detail="Enter the employee code of the colleague who referred you.")
        employee = await _lookup_employee(raw_code, company_id)
        if not employee:
            raise HTTPException(status_code=422, detail=INVALID_EMPLOYEE_CODE)
        out["referrer_employee_code"] = raw_code
        out["referrer_name"] = _employee_name(employee)
        out["referrer_user_id"] = employee.get("user_id")
        return out

    # Any other source: a code is optional extra context. An unresolvable one is dropped
    # silently rather than failing the application -- see the module docstring.
    if raw_code:
        employee = await _lookup_employee(raw_code, company_id)
        if employee:
            out["referrer_employee_code"] = raw_code
            out["referrer_name"] = _employee_name(employee)
            out["referrer_user_id"] = employee.get("user_id")
    return out


async def _lookup_employee(code: str, company_id: str) -> Optional[dict]:
    """Resolve an employee code within one company, or None.

    Pattern first: the value is checked against EMPLOYEE_CODE_RE before it reaches a query.
    `company_id` is part of the filter rather than a post-check, so a valid code belonging
    to another tenant resolves to None and is indistinguishable from one that never existed.
    """
    if not code or not EMPLOYEE_CODE_RE.match(code):
        return None
    return await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"employee_code": code, "company_id": str(company_id)})


def _employee_name(employee: dict) -> Optional[str]:
    employee = employee or {}
    return (employee.get("employee_name") or employee.get("full_name")
            or employee.get("name") or employee.get("employee_code"))


async def notify_referrer(candidate: dict, title: str, message: str,
                          kind: str = "info") -> None:
    """Tell the referring employee something happened to their referral. Never raises.

    In-app only by default. Emailing an employee every time a person they mentioned once
    moves a stage is the kind of well-meant noise that gets a notification channel muted,
    and a muted channel is worse than a quiet one.
    """
    user_id = (candidate or {}).get("referrer_user_id")
    if not user_id:
        return
    try:
        from app.services.hrms_notify_service import notify_user
        await notify_user(str(user_id), title, message, kind=kind,
                          link="/hrms/candidates", email=False)
    except Exception as e:
        print(f"[WARN] HRMS referrer notification failed: {e}")


# Stages at which a referrer is told their referral progressed. Deliberately just the two
# that matter to the person who made the introduction -- selection and joining. Notifying on
# every stage would make the feature noise.
REFERRAL_MILESTONES = {
    "Selected": ("Your referral was selected",
                 "{name}, whom you referred, has been selected."),
    "Joined":   ("Your referral has joined",
                 "{name}, whom you referred, has joined the company."),
}


async def notify_referral_milestone(candidate: dict, new_status: str) -> None:
    """Fire the milestone notification for a stage change, if this stage is one."""
    milestone = REFERRAL_MILESTONES.get(new_status)
    if not milestone or not (candidate or {}).get("referrer_user_id"):
        return
    title, template = milestone
    await notify_referrer(
        candidate, title,
        template.format(name=candidate.get("candidate_name") or "Your referral"),
        kind="success")
