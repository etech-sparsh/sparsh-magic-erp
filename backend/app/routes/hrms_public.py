"""
HRMS > PUBLIC routes (NO AUTHENTICATION).

Mounted under /api/hrms/public.

  GET  /hrms/public/apply/{code}     the job ad behind a shared application link
  POST /hrms/public/apply/{code}     submit an application
  GET  /hrms/public/assess/{code}    a candidate's assessment
  POST /hrms/public/assess/{code}    submit an assessment
  GET  /hrms/public/offer/{code}     a candidate's offer letter
  POST /hrms/public/offer/{code}     accept or decline
  GET  /hrms/public/onboard/{code}   a new hire's pre-onboarding form
  POST /hrms/public/onboard/{code}   submit joining details and KYC documents
  GET  /hrms/public/appointment/{code}   a candidate's appointment letter   (Phase 11-R)
  POST /hrms/public/appointment/{code}   acknowledge it                     (Phase 11-R)
  GET  /hrms/public/survey/{code}    a new joiner's experience survey   (Phase INT-2)
  POST /hrms/public/survey/{code}    submit it, anonymously             (Phase INT-2)

*** READ THIS BEFORE ADDING AN ENDPOINT HERE ***

This is the only router in the ERP reachable with no token, by anyone on the internet. It
accepts files and personal data. Everything else in the app can assume an authenticated,
tenant-scoped caller; nothing here can.

Rules for this file, all enforced by tests in test_phase4_public_security.py:

1. NO `Depends(get_current_user)`, and NO router-level company gate. Adding either would
   break the public flow; forgetting the rest of this list would break security.
2. The URL code is the ONLY credential. It is pattern-validated (`validate_posting_code`)
   before it reaches a query, so a crafted value cannot arrive at Mongo as an operator
   document -- NoSQL operator injection is structurally impossible, not merely unlikely.
3. Every endpoint is rate limited BEFORE it does any work, on two independent axes: per
   client IP, and per posting code. The second exists because the first is defeatable with
   a proxy pool.
4. Errors are deliberately vague and identical for "not found", "malformed" and "wrong
   tenant", so the endpoint cannot be used as an existence oracle. This mirrors how
   /auth/forgot-password answers identically for known and unknown emails.
5. Responses expose ONLY what a candidate needs. No company_id, no requisition number, no
   internal flags, no other applicant's data.
6. This router is NOT gated by `hrms_enabled`. A posting code is only ever issued by an
   enabled company, and checking the toggle here would let an applicant infer a client's
   subscription state from a shared link.
"""
from fastapi import APIRouter, Request

from app.models.hrms import (
    PublicAppointmentAckIn, PublicApplicationIn, PublicAssessmentIn, PublicOfferResponseIn,
    PublicOnboardIn,
)
# ── Phase INT-2 ── the sixth public surface.
from app.models.hrms import ClientApplicationIn, SurveyResponseIn
from app.services import hrms_appointment_service as appointments
from app.services import hrms_assessment_service as assessments
from app.services import hrms_link_service as links
from app.services import hrms_offer_service as offers
from app.services import hrms_onboarding_service as onboarding
from app.services import hrms_client_posting_service as client_postings
from app.services import hrms_posting_service as postings
from app.services import hrms_survey_service as surveys
from app.utils.hrms_public_guard import (
    assert_link_live, client_ip, enforce_rate_limit, validate_access_code,
    validate_posting_code,
)

router = APIRouter(prefix="/hrms/public", tags=["HRMS Public"])

# ── Phase 11-R, Item 1: the registry hooks ───────────────────────────────────────────
# Every handler below follows the same four-step order, and the order matters:
#
#   1. validate the code shape      -- a crafted value never reaches Mongo
#   2. rate limit                   -- before any real work
#   3. assert_link_live(code)       -- revocation and expiry, answered with the vague
#                                      CLOSED_LINK so it is not an existence oracle
#   4. do the work, then record the open (GET) or the consumption (POST)
#
# Steps 3 and 4 are additive: they change no existing status code, payload or message on
# any of the eight pre-existing endpoints. A link with no registry row -- everything issued
# before this phase -- passes step 3 untouched.


@router.get("/apply/{code}")
async def public_job_ad(code: str, request: Request):
    """The job ad behind a public application link.

    Rate limited generously -- browsing an ad is cheap, and a shared office or campus IP
    should not be locked out for reading a job posting.
    """
    code = validate_posting_code(code)
    await enforce_rate_limit("view", client_ip(request))
    await assert_link_live(code)
    result = await postings.get_public_posting(code)
    await links.record_open(code)
    return result


@router.post("/apply/{code}")
async def public_apply(code: str, body: PublicApplicationIn, request: Request):
    """Submit an application.

    The expensive endpoint: it creates a record and stores files. Limited per IP (5/hour)
    AND per posting code (200/hour), so neither a single abusive client nor a distributed
    flood against one popular ad can fill the database.
    """
    code = validate_posting_code(code)
    ip = client_ip(request)
    await enforce_rate_limit("apply", ip)
    await enforce_rate_limit("apply-posting", code)
    await assert_link_live(code)
    result = await postings.submit_application(code, body.model_dump())
    # An apply link is shared, so it is NOT consumed by one submission -- the next
    # applicant must still be able to use it. Only per-candidate links are consumed.
    return result


@router.get("/assess/{code}")
async def public_assessment(code: str, request: Request):
    """The assessment behind a candidate's link.

    The code here is a 128-bit access token, not a short public identifier like a posting
    code -- it is the ONLY thing protecting one candidate's submission, so it is validated
    against its own pattern and never normalised (case-folding would throw away entropy).

    Viewing marks the assessment Opened on first sight, which is how HR distinguishes
    "never looked at it" from "opened it and went quiet".
    """
    code = validate_access_code(code)
    await enforce_rate_limit("assess-view", client_ip(request))
    await assert_link_live(code)
    result = await assessments.get_public_assessment(code)
    await links.record_open(code)
    return result


@router.post("/assess/{code}")
async def public_assessment_submit(code: str, body: PublicAssessmentIn, request: Request):
    """Submit an assessment. Accepts a written response, attachments, or both."""
    code = validate_access_code(code)
    await enforce_rate_limit("assess-submit", client_ip(request))
    await assert_link_live(code)
    result = await assessments.submit_public_assessment(code, body.model_dump())
    await links.record_consumed(code)
    return result


@router.get("/offer/{code}")
async def public_offer(code: str, request: Request):
    """The offer letter behind a candidate's link.

    A DRAFT is invisible here -- it has not been issued, so as far as the world is concerned
    it does not exist, and it returns the same opaque 404 as an unknown code.
    """
    code = validate_access_code(code)
    await enforce_rate_limit("offer-view", client_ip(request))
    await assert_link_live(code)
    result = await offers.get_public_offer(code)
    await links.record_open(code)
    return result


@router.post("/offer/{code}")
async def public_offer_respond(code: str, body: PublicOfferResponseIn, request: Request):
    """Accept or decline. Accepting requires a typed signature; declining does not."""
    code = validate_access_code(code)
    await enforce_rate_limit("offer-respond", client_ip(request))
    await assert_link_live(code)
    result = await offers.respond_to_offer(code, body.model_dump())
    await links.record_consumed(code)
    return result


@router.get("/onboard/{code}")
async def public_onboarding(code: str, request: Request):
    """The pre-onboarding form behind a new hire's link.

    Returns only enough for them to recognise the form as theirs -- their name, the role and
    the joining date. Never the offer terms, the requisition, or any internal status beyond
    "you have already submitted this".
    """
    code = validate_access_code(code)
    await enforce_rate_limit("onboard-view", client_ip(request))
    await assert_link_live(code)
    result = await onboarding.get_public_onboarding(code)
    await links.record_open(code)
    return result


@router.post("/onboard/{code}")
async def public_onboarding_submit(code: str, body: PublicOnboardIn, request: Request):
    """Submit joining details and KYC documents.

    PAN-or-Aadhaar is enforced HERE, server-side. The source checked it in the browser only
    (BACKEND_ANALYSIS 8), so any request that skipped the form put an employee into payroll
    with no identity document at all.
    """
    code = validate_access_code(code)
    await enforce_rate_limit("onboard-submit", client_ip(request))
    await assert_link_live(code)
    result = await onboarding.submit_public_onboarding(code, body.model_dump())
    await links.record_consumed(code)
    return result


# ─────────────────────────────────────────────────────────────
# Phase 11-R, Item 3 — the appointment letter
# ─────────────────────────────────────────────────────────────
@router.get("/appointment/{code}")
async def public_appointment(code: str, request: Request):
    """The appointment letter behind a candidate's link.

    Modelled exactly on the offer page: a GENERATED (not yet sent) letter is invisible and
    answers with the same opaque 404 as an unknown code, because as far as the world is
    concerned it has not been issued.

    Viewing moves a Sent letter to `Pending Acknowledgement`, which is how HR tells "they
    have not opened it" from "they opened it and have not signed" — the same distinction
    AssessmentStatus.OPENED draws.
    """
    code = validate_access_code(code)
    await enforce_rate_limit("appointment-view", client_ip(request))
    await assert_link_live(code)
    result = await appointments.get_public_appointment(code)
    await links.record_open(code)
    return result


@router.post("/appointment/{code}")
async def public_appointment_ack(code: str, body: PublicAppointmentAckIn, request: Request):
    """Acknowledge an appointment letter.

    A typed signature is REQUIRED. Acknowledging is an act with consequences — it is the
    candidate confirming the joining terms — so it is attributable, exactly as accepting an
    offer is (there is no "decline" here: declining happens at the offer, one step earlier).
    """
    code = validate_access_code(code)
    await enforce_rate_limit("appointment-ack", client_ip(request))
    await assert_link_live(code)
    result = await appointments.acknowledge_appointment(code, body.model_dump())
    await links.record_consumed(code)
    return result


# ─────────────────────────────────────────────────────────────
# Phase INT-2 — the new-hire experience surveys (SOP §10)
# ─────────────────────────────────────────────────────────────
# The sixth public surface, and it follows the same four-step order as every one above it:
# validate the code shape, rate limit, assert the link is live, then do the work.
#
# One thing is different, and it is the point of the whole feature: this surface is
# ANONYMOUS TO THE READER. The GET returns the questionnaire and nothing about the person --
# no employee code, no name, no requisition. The respondent already knows who they are, and
# a page that echoes their identity back is a page that can be screenshotted next to their
# answers. The stored `employee_code` exists solely so nobody answers twice, and the
# reporting layer refuses to return a figure below SURVEY_MIN_RESPONSES.
@router.get("/survey/{code}")
async def public_survey(code: str, request: Request):
    """The questionnaire behind a new joiner's link."""
    code = validate_access_code(code)
    await enforce_rate_limit("survey-view", client_ip(request))
    await assert_link_live(code)
    result = await surveys.get_public_survey(code)
    await links.record_open(code)
    return result


@router.post("/survey/{code}")
async def public_survey_submit(code: str, body: SurveyResponseIn, request: Request):
    """Submit answers. Once submitted a response is final -- a live link that can rewrite an
    average after somebody has read it would make the figure meaningless."""
    code = validate_access_code(code)
    await enforce_rate_limit("survey-submit", client_ip(request))
    await assert_link_live(code)
    result = await surveys.submit_public_survey(code, body.model_dump())
    await links.record_consumed(code)
    return result


# ─────────────────────────────────────────────────────────────
# Client Hiring — a client company's vacancy, advertised by Sparsh
#
# Separate from /apply above, which is Sparsh Magic's OWN recruitment. Same public
# contract, same rate limits, same opaque 404 on a bad code — but a different collection
# and a different tenant, because a client's advert and Sparsh's own must never be served
# by one lookup.
#
# NOT gated by the link service: an internal apply link is issued per posting and tracked
# for opens, whereas a client vacancy code is simply the address of a public advert.
# ─────────────────────────────────────────────────────────────
@router.get("/client-apply/{code}")
async def public_client_job_ad(code: str, request: Request):
    """The advert behind a client vacancy link."""
    code = validate_posting_code(code)
    await enforce_rate_limit("view", client_ip(request))
    return await client_postings.get_public_client_posting(code)


@router.post("/client-apply/{code}")
async def public_client_apply(code: str, body: ClientApplicationIn, request: Request):
    """Apply to a client vacancy.

    Creates an ordinary client candidate at SOURCED, so the recruiter's existing chain
    picks it up unchanged. Rate limited per IP and per vacancy, like the internal surface:
    neither one abusive client nor a flood against one popular ad can fill the database.
    """
    code = validate_posting_code(code)
    ip = client_ip(request)
    await enforce_rate_limit("apply", ip)
    await enforce_rate_limit("apply-posting", code)
    return await client_postings.submit_client_application(code, body.model_dump())
