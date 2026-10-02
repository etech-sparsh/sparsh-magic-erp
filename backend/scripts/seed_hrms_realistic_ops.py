"""Seed a realistic, production-SHAPED HRMS dataset for one operating company.

This is the bigger sibling of `seed_hrms_recruitment_demo.py`. That script walks ONE
requisition end to end, to prove the pipeline works. This one builds a book of work that
looks like a live recruitment desk: several clients, several roles per client, a spread of
requisition states, and candidates distributed across every stage a real pipeline holds at
any given moment -- including the ones nobody demos, like CVs still sitting unread and CVs
shared with a client who has not replied.

-- It drives the REAL services --------------------------------------------------------
Nothing is hand-inserted. Every record is created through the same service functions the
API calls, so business ids are minted properly, every stage move is legal under
FORWARD_TRANSITIONS, the audit trail is complete and the public link registry is populated.
A dataset assembled by writing documents directly would be a dataset that tests nothing --
it would encode whatever the author believed the shape to be rather than what the
application actually produces.

-- It cannot disturb the existing seed -------------------------------------------------
Everything created here is stamped `demo_seed: "realistic-ops"`. The recruitment demo uses
`"recruitment-demo"`, and `--undo` on either script deletes only its own marker. This script
also creates its own departments, designations and sanctioned-strength rows rather than
reusing the company's, so removing it leaves the masters exactly as it found them.

-- Clients are the ERP's companies -----------------------------------------------------
Requisitions are tagged with real company ids from the Companies section, which is what the
recruitment dashboard's client filter reads. Companies are NEVER created or edited here --
the script picks from what already exists and fails if there are not enough.

-- No personal data --------------------------------------------------------------------
Every candidate is invented. The values are chosen so they cannot collide with a real
person's:
  * emails end in `example.com`, reserved by RFC 2606 and permanently unroutable;
  * phone numbers are `+91 00000 xxxxx` -- no Indian mobile number begins with 0, so the
    number is well-formed for the validator and unassignable in reality;
  * PAN and Aadhaar values are structurally valid but deliberately impossible (an Aadhaar
    never starts with 0 or 1), so no real identity document is reproduced.
Real USERS are read, never written: the script acts AS existing staff to raise and approve
work, and changes nobody's account or permissions.

-- Two side effects are suppressed -----------------------------------------------------
Notifications (in-app and email) and S3 uploads, for the same reason the demo suppresses
them: this writes to a shared database and real colleagues should not be told about invented
candidates.

Usage (from backend/):
    python scripts/seed_hrms_realistic_ops.py --company <company_id> [--dry-run]
    python scripts/seed_hrms_realistic_ops.py --company <company_id> --undo
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import app.db.mongodb as mongo                                        # noqa: E402
# The connection, the notification/S3 muzzle and the actor resolution are identical to the
# recruitment demo's, so they are imported rather than copied. A second copy of the muzzle
# is the one that goes out of date and mails a real person about a fake candidate.
from scripts.seed_hrms_recruitment_demo import (                      # noqa: E402
    connect, log, pick_actors, silence_side_effects,
)

MARKER = "realistic-ops"

# Every collection this script can write to, for the stamping and the undo. The masters and
# the sanction rows are included because -- unlike the demo -- this script creates its own.
SEEDED_COLLECTIONS = [
    "hrms_departments", "hrms_designations", "hrms_sanctioned_strength",
    "hrms_requisitions", "hrms_job_descriptions", "hrms_job_postings",
    "hrms_candidates", "hrms_assessments", "hrms_interviews", "hrms_offers",
    "hrms_appointments", "hrms_onboarding", "hrms_employee_profiles",
    "hrms_links", "hrms_documents", "hrms_audit_log",
    # Phase INT-2: the internal-track engagement writes these too, so `--undo` has to know
    # about them or a re-seed leaves the last run's governance records behind.
    "hrms_position_scorecards", "hrms_reference_checks", "hrms_probation_reviews",
    "hrms_exceptions", "hrms_shortlist_reviews", "hrms_interview_windows",
    "hrms_preboarding_touchpoints", "hrms_salary_bands", "hrms_comm_log",
    "hrms_survey_responses",
    # Deliberately ABSENT: hrms_comm_templates, hrms_surveys and hrms_policies. Those are
    # seeded-on-first-read CONFIGURATION that a real company then edits, so deleting them
    # on `--undo` would take away an operator's own wording along with the demo data.
]

NOW = datetime.now(timezone.utc)


def day(offset: int) -> str:
    """A YYYY-MM-DD date `offset` days from now (negative for the past)."""
    return (NOW + timedelta(days=offset)).strftime("%Y-%m-%d")


def at(offset: int, hour: int = 11) -> str:
    """An ISO timestamp `offset` days from now, on the hour."""
    return (NOW + timedelta(days=offset)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# The organisation this script builds
# ═══════════════════════════════════════════════════════════════════════════
# Departments and designations are created here rather than borrowed, so `--undo` can take
# them away again. Names are chosen not to collide with what a company is likely to have
# already (the masters are unique per company, case-insensitively).
DEPARTMENTS = [
    ("Engineering",        "ENG",  "Product and platform engineering"),
    ("Data & Analytics",   "DATA", "Reporting, data engineering and insight"),
    ("Sales & Marketing",  "SLS",  "Revenue, demand generation and accounts"),
    ("Finance & Accounts", "FIN",  "Controlling, payables and compliance"),
    ("Client Operations",  "OPS",  "Delivery and day-to-day client servicing"),
]

# (name, level) -- level orders the ladder for the org chart.
DESIGNATIONS = [
    ("Senior Software Engineer",     4),
    ("Software Engineer",            3),
    ("QA Engineer",                  3),
    ("Data Analyst",                 3),
    ("Business Development Manager", 4),
    ("Accounts Executive",           2),
    ("Client Operations Executive",  2),
]

# Sanctioned headcount per (department, designation). Set generously so requisitions clear
# approval normally -- EXCEPT the one deliberately left tight, which sends its requisition up
# the escalation ladder. A dataset where every approval takes the happy path does not
# exercise the ladder, and the ladder is the part most likely to break.
SANCTIONED = {
    ("Engineering",        "Senior Software Engineer"):     18,
    ("Engineering",        "Software Engineer"):            24,
    ("Engineering",        "QA Engineer"):                  10,
    ("Data & Analytics",   "Data Analyst"):                 12,
    ("Sales & Marketing",  "Business Development Manager"):  9,
    ("Finance & Accounts", "Accounts Executive"):            1,   # deliberately tight
    ("Client Operations",  "Client Operations Executive"):  14,
}


# ═══════════════════════════════════════════════════════════════════════════
# Candidate archetypes -- where a CV ends up, and how it got there
# ═══════════════════════════════════════════════════════════════════════════
# A real pipeline is not a queue of people marching to an offer. At any moment it holds CVs
# nobody has opened, CVs a client is sitting on, people parked for a month and people who
# took a counter-offer. Each archetype below is one of those honest endings.
#
#   applied           just arrived, untouched -- this is what makes "awaiting review" > 0
#   under_review      opened, no decision yet
#   screened_out      rejected at first read, with a reason on record
#   duplicate         the same person applied twice
#   on_hold           parked, not rejected
#   shared_pending    sent to the client, no verdict yet          (client flow)
#   client_rejected   the client said no                          (client flow)
#   client_ok_hired   client shortlisted -> interviews -> offer accepted -> joined
#   client_ok_declined  client shortlisted -> offer -> candidate took a counter-offer
#   assessment_failed sat the test, did not clear it
#   interview_failed  cleared the test, failed the technical round
#   in_interview      interview booked, not yet evaluated -- live work in progress
#   offer_out         offer sent, awaiting the candidate's answer -- live work in progress
CLIENT_FLOW = {"shared_pending", "client_rejected", "client_ok_hired", "client_ok_declined"}
# Archetypes that never leave the screening stage.
NO_ADVANCE = {"applied", "under_review", "screened_out", "duplicate", "on_hold"}


def engagements(client_ids: list) -> list:
    """The book of work, bound to real client companies.

    Ten requisitions across five clients plus two in-house, with a deliberate spread of
    closing states. `assessment` drives the posting's `requires_assessment` flag, and it is
    False on every client-facing role for a reason the lifecycle enforces: shortlisting a
    candidate for an assessment-required posting moves them straight to Assessment Pending,
    and SHARED_WITH_CLIENT is not reachable from there. Sharing a CV happens BEFORE the
    testing, which is exactly how an agency works.
    """
    C = client_ids
    return [
        # ── Client 1: a delivery pod build-out, the flagship engagement ──
        dict(client=C[0], dept="Engineering", desig="Senior Software Engineer",
             vacancy=3, urgency="High", ctc=1850000, assessment=False, closing="Open",
             experience="5-8 years", location="Hybrid",
             notes="Pod build-out for the client's new platform programme.",
             mix={"client_ok_hired": 1, "client_ok_declined": 1, "client_rejected": 2,
                  "shared_pending": 2, "screened_out": 2, "applied": 2,
                  "under_review": 1}),
        dict(client=C[0], dept="Engineering", desig="QA Engineer",
             vacancy=2, urgency="Medium", ctc=1100000, assessment=False, closing="Open",
             experience="3-5 years", location="Office",
             notes="Manual plus automation, paired with the delivery pod.",
             mix={"shared_pending": 2, "client_rejected": 1, "in_interview": 1,
                  "applied": 2, "on_hold": 1}),

        # ── Client 2: filled, and closed as Hired ──
        dict(client=C[1], dept="Data & Analytics", desig="Data Analyst",
             vacancy=1, urgency="High", ctc=1250000, assessment=False, closing="Hired",
             experience="3-6 years", location="Remote",
             notes="Reporting layer for the client's operations dashboard.",
             mix={"client_ok_hired": 1, "client_rejected": 2, "screened_out": 1,
                  "duplicate": 1}),

        # ── Client 3: a live offer and a stalled client ──
        dict(client=C[2], dept="Sales & Marketing", desig="Business Development Manager",
             vacancy=2, urgency="High", ctc=1600000, assessment=False, closing="Open",
             experience="6-10 years", location="Office",
             notes="Two territory owners for the western region.",
             mix={"offer_out": 1, "client_ok_hired": 1, "shared_pending": 3,
                  "client_rejected": 1, "screened_out": 1, "applied": 1}),

        # ── Client 4: parked by the client ──
        dict(client=C[3], dept="Client Operations", desig="Client Operations Executive",
             vacancy=4, urgency="Medium", ctc=650000, assessment=False, closing="Hold",
             experience="1-3 years", location="Office",
             notes="Volume hiring for the service desk. Paused at the client's request.",
             mix={"shared_pending": 3, "client_rejected": 2, "on_hold": 2,
                  "screened_out": 2, "applied": 3}),

        # ── Client 5: cancelled after the client withdrew the mandate ──
        dict(client=C[4], dept="Engineering", desig="Software Engineer",
             vacancy=2, urgency="Low", ctc=950000, assessment=False, closing="Cancel",
             experience="2-4 years", location="Hybrid",
             notes="Mandate withdrawn -- the client filled it internally.",
             mix={"screened_out": 2, "on_hold": 1, "applied": 2}),

        # ── In-house: our own engineering hire, with an assessment gate ──
        dict(client=None, dept="Engineering", desig="Software Engineer",
             vacancy=2, urgency="Medium", ctc=1050000, assessment=True, closing="Open",
             experience="2-5 years", location="Hybrid",
             notes="Net-new seats on our own delivery team.",
             mix={"assessment_failed": 2, "interview_failed": 1, "in_interview": 1,
                  "screened_out": 1, "applied": 2, "under_review": 2}),

        # ── In-house: the tight-sanction role that must climb the escalation ladder ──
        dict(client=None, dept="Finance & Accounts", desig="Accounts Executive",
             vacancy=2, urgency="High", ctc=550000, assessment=False, closing="Open",
             experience="2-4 years", location="Office",
             notes="Payables cover. Raised above the sanctioned figure on purpose.",
             mix={"in_interview": 1, "screened_out": 1, "applied": 1, "on_hold": 1}),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Invented people
# ═══════════════════════════════════════════════════════════════════════════
FIRST_NAMES = [
    "Aarav", "Aditi", "Akash", "Ananya", "Arjun", "Bhavna", "Chirag", "Deepa",
    "Devansh", "Esha", "Farhan", "Gauri", "Harsh", "Ishaan", "Jaya", "Kabir",
    "Kavya", "Lakshya", "Manish", "Meher", "Naveen", "Nisha", "Omkar", "Pallavi",
    "Pranav", "Priya", "Rahul", "Ridhi", "Rohit", "Sanya", "Shreya", "Siddharth",
    "Tanvi", "Uday", "Varun", "Vidya", "Yash", "Zoya",
]
SURNAMES = [
    "Agarwal", "Bhatt", "Chauhan", "Desai", "Gupta", "Iyer", "Joshi", "Kulkarni",
    "Menon", "Nair", "Patel", "Rao", "Reddy", "Sharma", "Shetty", "Singh",
    "Verma", "Yadav",
]

SOURCES = ["Job Portal", "Social Media", "Employee", "Consultant / Agency",
           "Walk-in", "Ex-Employee", "Client", "Other"]

CURRENT_EMPLOYERS = [
    "Northwind Systems", "Blue Harbour Tech", "Meridian Analytics", "Cedar & Co",
    "Sunfield Retail", "Kestrel Logistics", "Ironwood Consulting", "Lumen Digital",
]
CITIES = ["Pune", "Bengaluru", "Mumbai", "Hyderabad", "Chennai", "Indore", "Jaipur"]
NOTICE = ["Immediate", "15 days", "30 days", "60 days", "90 days"]


class People:
    """A deterministic, collision-free source of invented candidates.

    Deterministic on purpose: two runs produce the same names in the same order, so a bug
    found on one run can be reproduced on the next. The counter also guarantees uniqueness,
    which matters because a duplicate email is a real 409 from the application form.
    """

    def __init__(self):
        self.n = 0

    def next(self) -> dict:
        i = self.n
        self.n += 1
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = SURNAMES[(i // len(FIRST_NAMES) + i * 7) % len(SURNAMES)]
        return {
            "name": f"{first} {last}",
            # example.com is reserved by RFC 2606 and cannot be registered by anyone.
            "email": f"{first.lower()}.{last.lower()}{i:03d}@example.com",
            # No Indian mobile number starts with 0, so this is well-formed and unassignable.
            "phone": f"+91 00000 {i:05d}",
            "source": SOURCES[i % len(SOURCES)],
            "employer": CURRENT_EMPLOYERS[i % len(CURRENT_EMPLOYERS)],
            "city": CITIES[i % len(CITIES)],
            "notice": NOTICE[i % len(NOTICE)],
            "experience": f"{2 + (i % 9)} years",
            "index": i,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════
async def build_masters(MS, SANC, actor: dict, company_id: str) -> tuple:
    """Create the departments, designations and sanctioned figures this dataset needs.

    Re-runnable: a master that already exists (409) is looked up and reused rather than
    treated as an error, so a partial run can be finished by running again.
    """
    departments, designations = {}, {}

    for name, code, description in DEPARTMENTS:
        try:
            row = await MS.create_master("department", company_id, {
                "name": name, "code": code, "description": description}, actor)
            departments[name] = row["id"]
        except Exception as e:
            if "already exists" not in str(e):
                raise
            existing = await mongo.get_collection("hrms_departments").find_one(
                {"company_id": company_id, "name": name})
            departments[name] = str(existing["_id"])
    log(f"{len(departments)} departments ready")

    for name, level in DESIGNATIONS:
        try:
            row = await MS.create_master("designation", company_id, {
                "name": name, "level": level}, actor)
            designations[name] = row["id"]
        except Exception as e:
            if "already exists" not in str(e):
                raise
            existing = await mongo.get_collection("hrms_designations").find_one(
                {"company_id": company_id, "name": name})
            designations[name] = str(existing["_id"])
    log(f"{len(designations)} designations ready")

    for (dept_name, desig_name), count in SANCTIONED.items():
        await SANC.set_sanction(actor, company_id, {
            "department_id": departments[dept_name],
            "designation_id": designations[desig_name],
            "sanctioned_count": count,
            "effective_from": day(-180),
            "notes": "Approved headcount for the current financial year."})
    log(f"{len(SANCTIONED)} sanctioned-strength figures set")

    return departments, designations


async def pick_clients(company_id: str, wanted: int) -> list:
    """Real companies to act as clients, from the Companies section.

    The operating company is excluded -- an agency does not recruit for itself, and leaving
    it in would make the client comparison table read as if it did. Companies are only READ
    here; this script never creates or edits one.
    """
    from bson import ObjectId

    rows = await mongo.get_collection("companies").find(
        {"is_active": {"$ne": False}}, {"name": 1}).sort("name", 1).to_list(500)
    rows = [r for r in rows if str(r["_id"]) != str(company_id)]
    if len(rows) < wanted:
        raise SystemExit(
            f"Only {len(rows)} other active companies exist; this dataset needs {wanted}. "
            f"Add companies under the Companies section first.")
    picked = rows[:wanted]
    for r in picked:
        log(f"client: {r.get('name')}")
    return [str(r["_id"]) for r in picked]


# ═══════════════════════════════════════════════════════════════════════════
# One engagement, end to end
# ═══════════════════════════════════════════════════════════════════════════
async def raise_requisition(ctx, spec: dict, departments: dict, designations: dict) -> dict:
    """Raise, HR-review, walk any escalation, and MD-approve one requisition."""
    RS, M = ctx["RS"], ctx["M"]
    HR, MD, HOD = ctx["HR"], ctx["MD"], ctx["HOD"]
    company_id = ctx["company_id"]
    role = spec["desig"]

    req = await RS.create_requisition(HOD, company_id, {
        "department_id": departments[spec["dept"]],
        "designation_id": designations[role],
        "assignee_id": HR["_id"],
        "client_id": spec["client"],
        "vacancy": spec["vacancy"],
        "required_date": day(60),
        "experience_required": spec["experience"],
        "qualification": "Graduate or above in a relevant discipline",
        "essential_skills": ROLE_SKILLS[role],
        "employment_type": "Full-time",
        "work_location": spec["location"],
        "urgency_level": spec["urgency"],
        "offering_ctc": spec["ctc"],
        "notes": spec["notes"],
        # Both budget figures, so budget_status reads a real state rather than "Not Set".
        "budget_sanctioned_amount": spec["ctc"] * spec["vacancy"],
        "budget_sanctioned_by": MD["_id"],
        "budget_sanctioned_on": day(-30),
        "budget_hod_amount": spec["ctc"] * spec["vacancy"],
        "budget_hod_by": HOD["_id"],
        "budget_hod_on": day(-28),
        "budget_remarks": "Within the quarter's approved recruitment budget.",
        "jd": {
            "title": role,
            "responsibilities": ROLE_RESPONSIBILITIES[role],
            "skills": ROLE_SKILLS[role],
            "qualifications": "Graduate or above in a relevant discipline",
            "experience": spec["experience"],
            "location": spec["location"],
            "ctc": f"{int(spec['ctc'] / 100000)} LPA (indicative)",
            "benefits": "Health cover, annual learning budget, flexible hours",
            "employment_type": "Full-time",
        },
    })
    REQ, JD = req["request_no"], req["jd_no"]

    state = await RS.act_on_requisition(
        HR, company_id, REQ, "hr-approve",
        remarks="Headcount and band checked against the plan.")

    # A position raised above its sanctioned strength routes up the reporting line before it
    # reaches the MD. The MD may clear any rung, so the ladder is walked to the top rather
    # than left half-approved.
    rungs = 0
    while state["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value:
        rungs += 1
        if rungs > M.MAX_ESCALATION_LEVELS + 1:
            raise SystemExit(f"{REQ} is stuck in escalation after {rungs} steps.")
        state = await RS.act_on_requisition(
            MD, company_id, REQ, "escalate-approve",
            remarks="Over-sanction accepted for this quarter.")

    await RS.act_on_requisition(
        MD, company_id, REQ, "md-approve", remarks="Approved. Start sourcing.")

    label = f"{REQ}  {role}"
    log(f"{label:<42} {spec['vacancy']} seat(s)"
        + (f", escalated {rungs} rung(s)" if rungs else ""))
    return {"request_no": REQ, "jd_no": JD, "escalations": rungs}


ROLE_SKILLS = {
    "Senior Software Engineer":     "Python, SQL, REST API design, cloud deployment, code review",
    "Software Engineer":            "Python or Java, SQL, Git, unit testing",
    "QA Engineer":                  "Test design, Selenium or Playwright, API testing, defect triage",
    "Data Analyst":                 "SQL, Excel, Power BI or Tableau, stakeholder reporting",
    "Business Development Manager": "Enterprise sales, pipeline management, negotiation, CRM discipline",
    "Accounts Executive":           "Tally, GST returns, reconciliations, payables",
    "Client Operations Executive":  "Ticket handling, SLA tracking, written communication",
}

ROLE_RESPONSIBILITIES = {
    "Senior Software Engineer": (
        "Own a delivery workstream end to end: shape the technical approach, build and ship "
        "the services behind it, and review the team's work."),
    "Software Engineer": (
        "Build and ship features against an agreed design, with tests, and support them "
        "once they are live."),
    "QA Engineer": (
        "Design and run the test suite for a delivery pod, automate the regression pack and "
        "triage defects with the engineers."),
    "Data Analyst": (
        "Model the reporting layer, build the dashboards the client's operations team runs "
        "on, and answer the questions behind the numbers."),
    "Business Development Manager": (
        "Own a territory end to end: build the pipeline, run the commercial conversation "
        "and close."),
    "Accounts Executive": (
        "Run payables and reconciliations, file returns on time and keep the ledger clean."),
    "Client Operations Executive": (
        "Handle the client's day-to-day service requests against agreed SLAs and escalate "
        "what cannot be resolved at the desk."),
}


async def apply_candidates(ctx, posting_code: str, request_no: str, mix: dict) -> dict:
    """Submit one application per person in the mix. Returns {archetype: [(uk, person)]}."""
    PS = ctx["PS"]
    people = ctx["people"]
    grouped = {}

    for archetype, count in mix.items():
        for _ in range(count):
            p = people.next()
            payload = {
                "candidate_name": p["name"], "can_email": p["email"],
                "can_contact": p["phone"], "declaration": True,
                "referral_source": p["source"], "current_location": p["city"],
                "notice_period": p["notice"], "total_experience": p["experience"],
                "qualification": "B.Tech, Computer Science",
                "current_company": p["employer"],
                "current_ctc": str(600000 + (p["index"] % 12) * 75000),
                "expected_ctc": str(900000 + (p["index"] % 12) * 90000),
                "cover_note": "Happy to walk through the work I have shipped recently.",
                "certificates": [],
            }
            # A referral is only claimed where it can be substantiated. An "Employee"
            # referral REQUIRES an employee code that resolves (hrms_referral_service:
            # "the code IS the claim here"), so it is claimed only once this run has
            # actually hired somebody; before that the same person is recorded as an
            # ex-employee referral, which needs a name and no code. Inventing a code would
            # produce a 422, and inventing one that happened to resolve would attribute the
            # referral to a real employee who never made it.
            if p["source"] == "Employee":
                code = ctx["employee_codes"][p["index"] % len(ctx["employee_codes"])] \
                    if ctx["employee_codes"] else None
                payload.update({
                    "is_referral": True,
                    "referred_by": "A colleague on the delivery team",
                    "referral_relation": "Current colleague",
                    "referral_source": "Employee" if code else "Ex-Employee",
                    "referrer_employee_code": code,
                })
            result = await PS.submit_application(posting_code, payload)
            grouped.setdefault(archetype, []).append((result["reference"], p))

    total = sum(len(v) for v in grouped.values())
    log(f"{'':<42} {total} application(s) received")
    return grouped


async def screen(ctx, grouped: dict) -> None:
    """Run the bulk screening pass, the way a recruiter actually works a list."""
    CS = ctx["CS"]
    company_id = ctx["company_id"]

    def uks(*archetypes):
        return [uk for a in archetypes for uk, _p in grouped.get(a, [])]

    # Everything except the untouched inbox gets a first read.
    reviewed = uks(*(set(grouped) - {"applied"}))
    if reviewed:
        await CS.screen_candidates(ctx["HR"], company_id, {
            "uks": reviewed, "action": "review",
            "remarks": "First pass over the applications."})

    rejected = uks("screened_out")
    if rejected:
        await CS.screen_candidates(ctx["HR"], company_id, {
            "uks": rejected, "action": "reject",
            "remarks": "Experience and skills do not match the brief."})

    held = uks("on_hold")
    if held:
        await CS.screen_candidates(ctx["HR"], company_id, {
            "uks": held, "action": "hold",
            "remarks": "Parked pending the client's revised brief."})

    dupes = uks("duplicate")
    if dupes:
        await CS.screen_candidates(ctx["HR"], company_id, {
            "uks": dupes, "action": "duplicate",
            "remarks": "Same person already in the pipeline for this role."})

    # Everyone who progresses is shortlisted. For an assessment-required posting this lands
    # them on Assessment Pending in one legal hop; otherwise on Shortlisted.
    advancing = uks(*(set(grouped) - NO_ADVANCE))
    if advancing:
        await CS.screen_candidates(ctx["HR"], company_id, {
            "uks": advancing, "action": "shortlist",
            "remarks": "Relevant experience and a clear CV."})


async def share_with_client(ctx, grouped: dict) -> None:
    """Send the client-flow CVs out, then record the verdicts that came back."""
    CS = ctx["CS"]
    company_id = ctx["company_id"]
    HR = ctx["HR"]

    shared = [uk for a in CLIENT_FLOW for uk, _p in grouped.get(a, [])]
    if not shared:
        return
    await CS.screen_candidates(HR, company_id, {
        "uks": shared, "action": "share_with_client",
        "client_contact": "Talent Acquisition Lead",
        "remarks": "Shortlist for your review -- CVs attached."})

    for uk, p in grouped.get("client_rejected", []):
        await CS.record_client_response(HR, company_id, {
            "uk": uk, "status": "Rejected",
            "remarks": "Not enough depth in the core skill for this role."})

    for archetype in ("client_ok_hired", "client_ok_declined"):
        for uk, p in grouped.get(archetype, []):
            await CS.record_client_response(HR, company_id, {
                "uk": uk, "status": "Shortlisted",
                "remarks": "Please line up an interview."})

    # `shared_pending` is left exactly as it is. A client who has not replied yet is the
    # most common state on a real desk and the one dashboards most often forget to show.
    log(f"{'':<42} {len(shared)} CV(s) shared with the client")


async def assess(ctx, grouped: dict) -> None:
    """Issue, submit and review assessments for the archetypes that sit one."""
    ASM = ctx["ASM"]
    company_id = ctx["company_id"]
    HR, HOD = ctx["HR"], ctx["HOD"]

    sitting = [("assessment_failed", "Fail", 22),
               ("interview_failed", "Pass", 38),
               ("in_interview", "Pass", 41)]

    for archetype, verdict, score in sitting:
        for uk, p in grouped.get(archetype, []):
            issued = await ASM.send_assessment(HR, company_id, {
                "uk": uk, "title": "Take-home exercise and design walkthrough",
                "instructions": "Complete the brief and be ready to talk through your choices.",
                "max_score": 50, "due_date": day(5)})
            doc = await mongo.get_collection("hrms_assessments").find_one(
                {"assessment_no": issued["assessment_no"]})
            await ASM.get_public_assessment(doc["access_code"])
            await ASM.submit_public_assessment(doc["access_code"], {
                "response": "Solution and design notes are in the attached repository."})
            # Both reviewers must agree, so HR records first and the hiring manager decides.
            await ASM.review_assessment(HR, company_id, issued["assessment_no"], {
                "decision": "Pass", "score": score,
                "remarks": "Reviewed the submission end to end."})
            await ASM.review_assessment(HOD, company_id, issued["assessment_no"], {
                "decision": verdict,
                "remarks": ("Solid, worth interviewing." if verdict == "Pass"
                            else "Did not hold up on the follow-up questions.")})


def scorecard(outcome: str, who: str, base: int, remarks: str = None) -> dict:
    return {"outcome": outcome, "signature": who, "technical": base,
            "communication": base, "problem_solving": base, "behavior": base,
            "confidence": base, "team_fit": base, "remarks": remarks}


async def interview(ctx, grouped: dict) -> None:
    """Book and evaluate the interview rounds."""
    IV = ctx["IV"]
    company_id = ctx["company_id"]
    HR, MD, HOD = ctx["HR"], ctx["MD"], ctx["HOD"]

    async def book(actor, uk, round_name, offset, card):
        booked = await IV.schedule_interview(actor, company_id, {
            "uk": uk, "round": round_name, "scheduled_at": at(offset),
            "duration_min": 45, "mode": "Virtual",
            "interviewer_id": actor["_id"],
            "meeting_link": "https://meet.example.com/interview-room"})
        if card:
            await IV.evaluate_interview(actor, company_id, booked["interview_no"], card)
        return booked

    # Every round is booked in the FUTURE. `schedule_interview` refuses a past date outright
    # ("An interview cannot be scheduled in the past"), so there is no way through the API to
    # create a completed round that already happened -- and reaching around the service to
    # back-date one would mean this dataset no longer matched what the application can
    # produce. Evaluated rounds therefore carry a forward date; the outcome is what the
    # pipeline reads, not the clock.
    for archetype in ("client_ok_hired", "client_ok_declined", "offer_out"):
        for uk, p in grouped.get(archetype, []):
            await book(HR, uk, "HR Round", 1,
                       scorecard("Pass", HR["full_name"], 4, "Communicates clearly."))
            await book(HOD, uk, "Technical", 3,
                       scorecard("Pass", HOD["full_name"], 4, "Strong on fundamentals."))
            await book(MD, uk, "MD Round", 5,
                       scorecard("Pass", MD["full_name"], 5, "Make the offer."))

    for uk, p in grouped.get("interview_failed", []):
        await book(HOD, uk, "Technical", 2,
                   scorecard("Fail", HOD["full_name"], 2,
                             "Could not work through the data-modelling question."))

    # Booked but not yet evaluated -- the interviews a recruiter is walking into next week.
    for uk, p in grouped.get("in_interview", []):
        await book(HR, uk, "HR Round", 6, None)


async def offer_and_join(ctx, grouped: dict, role: str) -> int:
    """Offers, appointment letters, onboarding and the employee record. Returns hires."""
    OF, AP, OB, M = ctx["OF"], ctx["AP"], ctx["OB"], ctx["M"]
    company_id = ctx["company_id"]
    HR, MD = ctx["HR"], ctx["MD"]
    hires = 0

    async def make_offer(uk, ctc):
        created = await OF.create_offer(HR, company_id, {
            "uk": uk, "ctc": ctc, "joining_date": day(30), "designation": role,
            "content": f"We are delighted to offer you the role of {role}."})
        await OF.send_offer(HR, company_id, created["offer_no"],
                            {"signature": f"{MD['full_name']}, Managing Director"})
        doc = await mongo.get_collection("hrms_offers").find_one(
            {"offer_no": created["offer_no"]})
        return created["offer_no"], doc["access_code"]

    # Sent, no answer yet -- a live offer is a real state a dashboard must show.
    for uk, p in grouped.get("offer_out", []):
        await make_offer(uk, 1500000)

    for uk, p in grouped.get("client_ok_declined", []):
        _no, code = await make_offer(uk, 1450000)
        await OF.respond_to_offer(code, {
            "action": "decline", "note": "I have accepted a counter-offer. Thank you."})

    for uk, p in grouped.get("client_ok_hired", []):
        _no, code = await make_offer(uk, 1600000)
        await OF.respond_to_offer(code, {
            "action": "accept", "signature": p["name"],
            "note": "Delighted to accept."})

        appointment = await AP.create_appointment(HR, company_id, {"uk": uk})
        await AP.send_appointment(HR, company_id, appointment["appointment_no"],
                                  {"signature": f"{MD['full_name']}, Managing Director"})
        appt_doc = await mongo.get_collection("hrms_appointments").find_one(
            {"appointment_no": appointment["appointment_no"]})
        await AP.acknowledge_appointment(appt_doc["access_code"], {
            "signature": p["name"], "note": "Acknowledged with thanks."})

        started = await OB.start_onboarding(HR, company_id, {"uk": uk})
        ONB = started["onb_no"]
        onb_doc = await mongo.get_collection("hrms_onboarding").find_one({"onb_no": ONB})
        i = p["index"]
        await OB.submit_public_onboarding(onb_doc["access_code"], {
            # Structurally valid, deliberately impossible: no Aadhaar begins with 0.
            "pan": f"AAAPZ{1000 + i % 9000}A",
            "aadhaar": f"0000 {1000 + i % 9000} {2000 + i % 7000}",
            "date_of_birth": "1995-06-15",
            # Cycled rather than fixed, so the diversity reporting has something to group.
            "gender": ("Female", "Male", "Other")[i % 3],
            "address": f"{10 + i} Example Road, {p['city']}",
            "bank_name": "Example Bank", "bank_account": f"0000{i:010d}",
            "bank_ifsc": "EXMP0000001",
            "emergency_contact_name": "Emergency Contact",
            "emergency_contact_phone": f"+91 00000 9{i:04d}",
            "emergency_contact_relation": "Parent",
            "references": [{"name": "Former Manager", "relation": "Reporting manager",
                            "phone": f"+91 00000 8{i:04d}"}],
            "documents": []})
        await OB.verify_documents(HR, company_id, ONB)
        await OB.update_bg(HR, company_id, ONB, {
            "bg_verification": M.BgVerification.CLEARED.value,
            "bg_remarks": "Employment dates confirmed with the previous employer."})
        for key in ("offer_signed", "email_created", "system_access", "asset_issued",
                    "workspace", "induction"):
            await OB.set_checklist(HR, company_id, ONB, {"key": key, "done": True})
        handover = await OB.generate_employee_id(HR, company_id, ONB)
        for key in ("policy_ack", "bank_payroll", "buddy_assigned"):
            await OB.set_checklist(HR, company_id, ONB, {"key": key, "done": True})
        hires += 1
        # Recorded so later applications can carry a REAL employee referral (see
        # apply_candidates), which is how a referral programme actually compounds.
        ctx["employee_codes"].append(handover["employee_id"])
        log(f"{'':<42} {handover['employee_id']} joined ({p['name']})")

    return hires


# ═══════════════════════════════════════════════════════════════════════════
# Phase INT-2 — one INTERNAL requisition that exercises every new gate
# ═══════════════════════════════════════════════════════════════════════════
# Everything above this line is the CLIENT track: an agency book of work. This section adds
# Sparsh Magic hiring for itself, so the internal governance is visible in a seeded database
# rather than only in the tests.
#
# It deliberately produces THREE outcomes on ONE requisition, because a dataset where every
# gate is satisfied teaches nothing about what the gates do:
#
#   * one candidate walks the whole track -- committee, panel, references, offer,
#     onboarding, probation confirmed, personnel file closed;
#   * one is BLOCKED at probation confirmation by an incomplete statutory check, and is
#     LEFT blocked, so the screens show what an open control actually looks like;
#   * one is RELEASED past the shortlisting-committee gate by an approved exception, so the
#     exception log holds a real entry that really lifted something.
#
# It also leaves live governance state: a standing salary band the budget gate pre-filled
# from, an interview window, a committee sitting convened and not decided, a pre-boarding
# touchpoint flagged At Risk, and a talent-pool entry with recorded consent.
INTERNAL_DEPT = "Client Operations"
INTERNAL_ROLE = "Client Operations Executive"

# The three internal candidates, and what each is here to demonstrate.
INTERNAL_OUTCOMES = [
    ("confirmed", "walks the whole track and is confirmed"),
    ("blocked",   "blocked at confirmation by an open statutory check"),
    ("exception", "released past the committee gate by an approved exception"),
]


async def seed_internal_track(ctx, departments: dict, designations: dict) -> dict:
    """Build the internal-track engagement. Returns a summary for the console."""
    M = ctx["M"]
    RS, PS, CS, IV, OF, OB = (ctx["RS"], ctx["PS"], ctx["CS"], ctx["IV"],
                              ctx["OF"], ctx["OB"])
    HR, MD, HOD = ctx["HR"], ctx["MD"], ctx["HOD"]
    company_id = ctx["company_id"]

    import app.services.hrms_comm_service as CM
    import app.services.hrms_exception_service as EX
    import app.services.hrms_interview_window_service as IW
    import app.services.hrms_policy_service as PO
    import app.services.hrms_preboarding_service as PBT
    import app.services.hrms_probation_service as PB
    import app.services.hrms_reference_service as RC
    import app.services.hrms_salary_band_service as SB
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_survey_service as SV

    department_id = departments[INTERNAL_DEPT]
    designation_id = designations[INTERNAL_ROLE]

    # -- The standing band Finance agreed, so the budget gate has something to pre-fill --
    band = await SB.create_salary_band(MD, company_id, {
        "department_id": department_id, "designation_id": designation_id,
        "min": 420000, "max": 620000, "effective_from": day(-120),
        "notes": "FY26 band, agreed with Finance at the annual review."})
    log(f"{'salary band':<42} {band['band_no']}  420,000-620,000")

    # -- A batch interview window (Annexure C). Advisory: scheduling outside it warns. --
    await IW.create_window(HR, company_id, {
        "department_id": department_id, "weekday": "Wednesday",
        "start_time": "14:00", "end_time": "17:00",
        "notes": "The Ops panel keeps Wednesday afternoons free for interviews."})
    log(f"{'interview window':<42} Wednesday 14:00-17:00")

    # -- The requisition, through the INTERNAL approval chain --------------------------
    req = await RS.create_requisition(HOD, company_id, {
        "requisition_track": "internal",
        "department_id": department_id,
        "designation_id": designation_id,
        "assignee_id": HR["_id"],
        "vacancy": 3,
        "required_date": day(45),
        "experience_required": "2-4 years",
        "qualification": "Graduate or above in a relevant discipline",
        "essential_skills": ROLE_SKILLS[INTERNAL_ROLE],
        "employment_type": "Full-time",
        "work_location": "Office",
        "urgency_level": "High",
        "offering_ctc": 520000,
        "notes": "Backfilling the Ops desk ahead of the new client onboarding.",
        "jd": {
            "title": INTERNAL_ROLE,
            "responsibilities": ROLE_RESPONSIBILITIES[INTERNAL_ROLE],
            "skills": ROLE_SKILLS[INTERNAL_ROLE],
            "qualifications": "Graduate or above in a relevant discipline",
            "experience": "2-4 years",
            "location": "Office",
            "ctc": "5.2 LPA (indicative)",
            "benefits": "Health cover, annual learning budget, flexible hours",
            "employment_type": "Full-time",
        },
    })
    REQ, JD = req["request_no"], req["jd_no"]

    await RS.act_on_requisition(HR, company_id, REQ, "hr-verify",
                                remarks="Requisition is complete and justified.")
    # The band figures are taken STRAIGHT FROM THE MASTER, so `band_source` stamps as
    # `master` and the seeded data shows the pre-fill working rather than an override.
    state = await RS.act_on_requisition(
        MD, company_id, REQ, "budget-approve",
        remarks="Within the FY26 band.",
        budget={"approved_headcount": 3,
                "approved_salary_band_min": band["min"],
                "approved_salary_band_max": band["max"]})

    rungs = 0
    while state["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value:
        rungs += 1
        if rungs > M.MAX_ESCALATION_LEVELS + 1:
            raise SystemExit(f"{REQ} is stuck in escalation after {rungs} steps.")
        state = await RS.act_on_requisition(
            MD, company_id, REQ, "escalate-approve",
            remarks="Over-sanction accepted for this quarter.")

    # The position scorecard: HR drafts, the HOD approves. Not a managerial role, so one
    # signature completes it.
    card = await SC.create_scorecard(HR, company_id, {
        "request_no": REQ,
        "title": f"{INTERNAL_ROLE} hiring bar",
        "managerial": False,
        "criteria": [
            {"label": "Service handling", "category": "skill", "weight": 3},
            {"label": "Written communication", "category": "skill", "weight": 2},
            {"label": "Relevant experience", "category": "experience", "weight": 2},
            {"label": "Team fit", "category": "culture_fit", "weight": 1},
        ],
        "notes": "Agreed with the Ops lead before sourcing opened."})
    await SC.approve_scorecard(HOD, company_id, card["scr_no"], {
        "decision": "Pass", "signature": HOD["full_name"], "remarks": "Bar agreed."})
    await RS.act_on_requisition(MD, company_id, REQ, "scorecard-approve",
                                remarks="Approved. Start sourcing.")
    log(f"{REQ:<42} internal, 3 seats, band pre-filled from {band['band_no']}")

    # -- Sourcing ---------------------------------------------------------------------
    published = await PS.create_posting(HR, company_id, {
        "jd_no": JD, "requires_assessment": False, "expiry_date": day(30),
        "notes": "Internal vacancy -- careers page and the referral channel."})
    code = published["posting"]["posting_code"]

    people = ctx["people"]
    candidates = {}
    for key, _why in INTERNAL_OUTCOMES:
        person = people.next()
        applied = await PS.submit_application(code, {
            "candidate_name": person["name"],
            "can_email": person["email"],
            "can_contact": person["phone"],
            "declaration": True,
            "referral_source": "Job Portal",
            # ── SOP §11 ── the two acknowledgements the INTERNAL track requires. Without
            # them the application is refused, which is the point of seeding them here.
            "eeo_ack": True,
            "data_use_ack": True,
            # One of the three also consents to being kept for future roles, so the talent
            # pool has a real entry with a real expiry rather than an empty screen.
            "consent_to_retain": key == "exception",
            "current_location": person["city"],
            "total_experience": person["experience"],
            "qualification": "B.Com",
            "current_company": person["employer"],
            "expected_ctc": "5.5 LPA",
            "notice_period": person["notice"],
        })
        candidates[key] = {"uk": applied["reference"], "person": person}
        log(f"{'application':<42} {person['name']}  ({applied['reference']})")

    uks = {k: v["uk"] for k, v in candidates.items()}

    # -- Screening, and a scorecard evaluation on each ---------------------------------
    await CS.screen_candidates(HR, company_id, {
        "uks": list(uks.values()), "action": "shortlist"})
    for key, uk in uks.items():
        base = {"confirmed": 5, "blocked": 4, "exception": 3}[key]
        await SC.evaluate_candidate(HR, company_id, uk, {
            "scores": {"Service handling": base, "Written communication": base,
                       "Relevant experience": max(1, base - 1), "Team fit": base},
            "signature": HR["full_name"],
            "remarks": "Scored against the approved bar."})

    # -- The shortlisting committee (SOP §5) -------------------------------------------
    # TWO sittings, deliberately: one FINALISED covering the two who progress normally,
    # and one left PENDING so the governance screen shows an undecided sitting. The third
    # candidate is covered by an approved exception instead.
    committee = [
        {"user_id": HR["_id"], "decision": "Agree", "remarks": "Both meet the bar."},
        {"user_id": HOD["_id"], "decision": "Agree",
         "remarks": "Agreed -- take both to the final round."},
    ]
    finalised = await SL.create_shortlist_review(HR, company_id, {
        "request_no": REQ,
        "candidate_uks": [uks["confirmed"], uks["blocked"]],
        "committee_members": committee,
        "outcome": "Finalised",
        "notes": "Reviewed against the approved scorecard."})
    log(f"{finalised['slr_no']:<42} finalised, 2 candidate(s)")

    pending_sitting = await SL.create_shortlist_review(HR, company_id, {
        "request_no": REQ,
        "candidate_uks": [uks["exception"]],
        "committee_members": [committee[0]],
        "outcome": "Pending",
        "notes": "Convened; the Department Head could not attend."})
    log(f"{pending_sitting['slr_no']:<42} convened, awaiting the Department Head")

    # -- The exception that RELEASES the third candidate -------------------------------
    raised = await EX.raise_exception(HR, company_id, {
        "request_no": REQ, "uk": uks["exception"],
        "exception_type": "Relaxed Scorecard",
        "reason": ("The Department Head is on leave for three weeks and the desk cannot "
                   "wait. HR has reviewed the scorecard and recommends proceeding.")})
    await EX.decide_exception(MD, company_id, raised["exc_no"], {
        "decision": "Approved", "signature": MD["full_name"],
        "remarks": "Accepted. Record the committee's view on their return."})
    log(f"{raised['exc_no']:<42} APPROVED -- lifts the committee gate for one candidate")

    # -- Interviews, with a panel composed per SOP §5 -----------------------------------
    panel = [{"user_id": HR["_id"]}, {"user_id": HOD["_id"]}]
    for key, uk in uks.items():
        hr_round = await IV.schedule_interview(HR, company_id, {
            "uk": uk, "round": "HR Round", "mode": "Virtual",
            "scheduled_at": at(1, 15), "duration_min": 45,
            "interviewer_id": HR["_id"],
            "meeting_link": "https://meet.example.com/ops-panel",
            "panel": panel,
            "notes": "Panel: HR and the Department Head, per SOP section 5."})
        await IV.evaluate_interview(
            HR, company_id, hr_round["interview_no"],
            scorecard("Pass", HR["full_name"], 4,
                      "Handles a difficult conversation calmly."))

        md_round = await IV.schedule_interview(HR, company_id, {
            "uk": uk, "round": "MD Round", "mode": "Virtual",
            "scheduled_at": at(2, 16), "duration_min": 30,
            "interviewer_id": MD["_id"],
            "meeting_link": "https://meet.example.com/ops-final",
            "panel": panel + [{"user_id": MD["_id"]}],
            "notes": "Final conversation with Management."})
        await IV.evaluate_interview(
            MD, company_id, md_round["interview_no"],
            scorecard("Pass", MD["full_name"], 4, "Happy to proceed."))
    log(f"{'interviews':<42} 6 rounds, panel of HR + the Department Head")

    # -- Reference checks (mandatory before an internal offer, SOP §6) ------------------
    for key, uk in uks.items():
        await RC.create_reference_check(HR, company_id, {
            "uk": uk, "referee_name": "Former Reporting Manager",
            "referee_designation": "Operations Lead",
            "referee_organisation": "Previous Employer Pvt Ltd",
            "relationship": "Reported to them for two years",
            "referee_contact": "+91 00000 33333",
            "mode": "Phone", "checked_on": day(-2),
            "responses": "Reliable, good with clients, left on good terms.",
            "outcome": "Positive", "remarks": "No concerns raised."})
    log(f"{'reference checks':<42} 3 recorded, all Positive")

    # -- Offers: raise, Management approves, then send. Never in one call. ---------------
    for key, uk in uks.items():
        # The written offer summary the SOP asks for, ahead of the formal letter. The seed
        # muzzle suppresses the send itself, so this records the intent without mailing.
        await CM.send_template(HR, company_id, uk, "offer_summary")
        made = await OF.create_offer(HR, company_id, {
            "uk": uk, "ctc": 520000, "joining_date": day(2),
            "designation": INTERNAL_ROLE, "location": "Office"})
        await OF.approve_offer(MD, company_id, made["offer_no"], {
            "signature": MD["full_name"], "remarks": "Inside the approved band."})
        await OF.send_offer(HR, company_id, made["offer_no"],
                            {"signature": f"{MD['full_name']}, Managing Director"})
        offer_doc = await mongo.get_collection("hrms_offers").find_one(
            {"offer_no": made["offer_no"]})
        await OF.respond_to_offer(offer_doc["access_code"], {
            "action": "accept", "signature": candidates[key]["person"]["name"],
            "note": "Delighted to accept."})
    log(f"{'offers':<42} 3 raised, approved, sent and accepted")

    # -- Pre-boarding engagement (SOP §6). Tracking, not a gate. ------------------------
    await PBT.record_touchpoint(HR, company_id, {
        "candidate_uk": uks["confirmed"], "mode": "Call", "sentiment": "Positive",
        "contacted_at": day(-4),
        "notes": "Confirmed the start date and the paperwork they still owe us."})
    await PBT.record_touchpoint(HR, company_id, {
        "candidate_uk": uks["exception"], "mode": "WhatsApp", "sentiment": "At Risk",
        "contacted_at": day(-3), "counter_offer_disclosed": True,
        "notes": ("Has a competing offer at a higher band and is deciding this week. "
                  "The Ops lead is calling them tomorrow.")})
    log(f"{'pre-boarding':<42} 2 touchpoints, 1 flagged At Risk")

    # -- Onboarding through to an employee record ---------------------------------------
    employee_codes = {}
    for key, uk in uks.items():
        person = candidates[key]["person"]
        i = person["index"]
        started = await OB.start_onboarding(HR, company_id, {
            "uk": uk, "joining_date": day(2), "reporting_manager_id": HOD["_id"]})
        ONB = started["onb_no"]
        onb_doc = await mongo.get_collection("hrms_onboarding").find_one({"onb_no": ONB})
        await OB.submit_public_onboarding(onb_doc["access_code"], {
            # Structurally valid, deliberately impossible: no Aadhaar begins with 0.
            "pan": f"AAAPZ{1000 + i % 9000}A",
            "aadhaar": f"0000 {1000 + i % 9000} {2000 + i % 7000}",
            "date_of_birth": "1996-04-12",
            "gender": ("Female", "Male", "Other")[i % 3],
            "address": f"{10 + i} Example Road, {person['city']}",
            "bank_name": "Example Bank", "bank_account": f"0000{i:010d}",
            "bank_ifsc": "EXMP0000001",
            "emergency_contact_name": "Emergency Contact",
            "emergency_contact_phone": f"+91 00000 9{i:04d}",
            "emergency_contact_relation": "Parent",
            "references": [{"name": "Former Manager", "relation": "Reporting manager",
                            "phone": f"+91 00000 8{i:04d}"}],
            "documents": []})
        await OB.verify_documents(HR, company_id, ONB)
        # THE STATUTORY CHECK (SOP §11). One of the three is left with the background
        # verification still in progress, and that is what blocks their confirmation later.
        await OB.update_bg(HR, company_id, ONB, {
            "bg_verification": ("In Progress" if key == "blocked"
                                else M.BgVerification.CLEARED.value),
            "note": ("The agency has not come back yet." if key == "blocked"
                     else "Cleared with no adverse findings.")})
        handover = await OB.generate_employee_id(HR, company_id, ONB)
        employee_codes[key] = handover["employee_id"]
        ctx["employee_codes"].append(handover["employee_id"])

        # Work the checklist, INCLUDING the five Day-1 induction items an internal-track
        # onboarding carries. Completing those issues the induction experience survey.
        fresh = await mongo.get_collection("hrms_onboarding").find_one({"onb_no": ONB})
        for item in (fresh.get("checklist") or []):
            if item["key"] in M.SYSTEM_CHECKLIST_KEYS or item.get("done"):
                continue
            await OB.set_checklist(HR, company_id, ONB,
                                   {"key": item["key"], "done": True})
        log(f"{'':<42} {handover['employee_id']} joined ({person['name']})")

    # -- Probation: one confirmed, one BLOCKED by the statutory gate --------------------
    confirmed_count = blocked_count = 0
    for key, employee_code in employee_codes.items():
        review = await PB.open_probation(HR, company_id, {
            "employee_code": employee_code, "request_no": REQ,
            "started_on": day(-1), "duration_months": 6, "reviewer_id": HOD["_id"],
            "notes": "Opened at joining."}, silent=True)
        if not review:
            continue
        # Bring the end date forward so the review is genuinely DUE in the seeded data --
        # a probation ending in six months shows nothing on today's due list.
        await mongo.get_collection("hrms_probation_reviews").update_one(
            {"prb_no": review["prb_no"]}, {"$set": {"ends_on": day(-2)}})

        if key == "blocked":
            # LEFT BLOCKED on purpose. The background check is still in progress, so
            # `assert_statutory_checks_complete` refuses -- and the seeded database then
            # shows a real open control rather than a screen where everything is green.
            try:
                await PB.confirm_probation(HOD, company_id, review["prb_no"], {
                    "outcome": "Confirmed", "rating": 4.0,
                    "signature": HOD["full_name"],
                    "remarks": "Doing well on the desk."})
                log(f"{'probation':<42} WARNING: the statutory gate did not fire")
            except Exception:
                blocked_count += 1
                log(f"{review['prb_no']:<42} BLOCKED -- statutory check incomplete")
            continue

        await PB.confirm_probation(HOD, company_id, review["prb_no"], {
            "outcome": "Confirmed", "rating": 4.2, "signature": HOD["full_name"],
            "remarks": "Met the bar on every criterion."})
        confirmed_count += 1
        await PB.close_personnel_file(HR, company_id, {
            "employee_code": employee_code,
            "closure_note": ("Offer, joining documents, verification report and the "
                             "probation confirmation are all on file.")})
    log(f"{'probation':<42} {confirmed_count} confirmed, {blocked_count} blocked")

    # -- The talent pool (Annexure C) ---------------------------------------------------
    # Only candidates who actually consented go in. Pooling anybody else is refused, which
    # is exactly the behaviour worth having visible in a seeded dataset.
    pooled = 0
    consenting = await mongo.get_collection("hrms_candidates").find(
        {"company_id": company_id, "consent_to_retain": True,
         "talent_pool": {"$ne": True}}).to_list(5)
    for row in consenting[:2]:
        try:
            await CS.set_talent_pool(HR, company_id, row["uk"], {
                "talent_pool": True,
                "talent_pool_tags": ["client ops", "service desk"]})
            pooled += 1
        except Exception as e:
            log(f"{'talent pool':<42} skipped {row['uk']}: {e}")
    log(f"{'talent pool':<42} {pooled} candidate(s) with recorded consent")

    # -- The registers that seed on first read ------------------------------------------
    # Touched here so a seeded database has them populated rather than only after somebody
    # opens the screen.
    register = await PO.list_policies(company_id)
    templates = await CM.list_templates(company_id)
    instruments = await SV.list_surveys(company_id)
    log(f"{'registers':<42} {len(register['policies'])} policies, "
        f"{len(templates)} templates, {len(instruments)} survey instruments")

    return {"request_no": REQ, "candidates": len(uks),
            "confirmed": confirmed_count, "blocked": blocked_count,
            "exception": raised["exc_no"], "band": band["band_no"]}


# ═══════════════════════════════════════════════════════════════════════════
# Stamping and undo
# ═══════════════════════════════════════════════════════════════════════════
async def stamp(company_id: str, since: datetime) -> int:
    """Mark everything this run created, so `--undo` removes exactly that.

    Documents written by the recruitment demo already carry `demo_seed`, so the
    `$exists: false` guard means the two datasets can never claim each other's rows.
    """
    total = 0
    for name in SEEDED_COLLECTIONS:
        result = await mongo.get_collection(name).update_many(
            {"company_id": company_id, "created_at": {"$gte": since},
             "demo_seed": {"$exists": False}},
            {"$set": {"demo_seed": MARKER}})
        total += result.modified_count
    return total


async def marked_total(company_id: str) -> int:
    """How many documents currently carry this script's marker."""
    total = 0
    for name in SEEDED_COLLECTIONS:
        total += await mongo.get_collection(name).count_documents(
            {"company_id": company_id, "demo_seed": MARKER})
    return total


async def undo(company_id: str) -> None:
    print(f"\nRemoving `{MARKER}` records for company {company_id}\n")
    total = 0
    for name in SEEDED_COLLECTIONS:
        result = await mongo.get_collection(name).delete_many(
            {"company_id": company_id, "demo_seed": MARKER})
        if result.deleted_count:
            log(f"{result.deleted_count:>5}  removed from {name}")
        total += result.deleted_count
    print(f"\nDone. {total} document(s) removed.")
    print("Business-id counters are left alone on purpose -- resetting them could reissue "
          "an id that a surviving record already holds.\n")


# ═══════════════════════════════════════════════════════════════════════════
# Entry points
# ═══════════════════════════════════════════════════════════════════════════
async def seed(company_id: str) -> None:
    RS, PS, CS, ASM, IV, OF, AP, OB = silence_side_effects()
    from app.models import hrms as M
    import app.services.hrms_masters_service as MS
    import app.services.hrms_sanction_service as SANC

    actors = await pick_actors(company_id)
    started_at = datetime.now(timezone.utc)

    ctx = {"company_id": company_id, "M": M, "people": People(), "employee_codes": [],
           "RS": RS, "PS": PS, "CS": CS, "ASM": ASM, "IV": IV, "OF": OF,
           "AP": AP, "OB": OB,
           "HR": actors["HR"], "MD": actors["MD"], "HOD": actors["HOD"]}

    print(f"\nSeeding a realistic recruitment book into company {company_id}\n")
    log(f"raiser / hiring manager : {actors['HOD']['full_name']}")
    log(f"HR recruiter            : {actors['HR']['full_name']}"
        + ("" if actors["hr_is_real"] else "   (role supplied by this script only)"))
    log(f"MD approver             : {actors['MD']['full_name']}")

    print("\n1. Masters and sanctioned strength")
    departments, designations = await build_masters(MS, SANC, actors["HR"], company_id)
    # Stamped as we go, not once at the end. A run that dies halfway through engagement six
    # would otherwise leave five engagements' worth of unmarked records that `--undo` could
    # not find -- the exact situation a cleanup flag exists to prevent.
    await stamp(company_id, started_at)

    print("\n2. Client companies (read from the Companies section)")
    clients = await pick_clients(company_id, 5)

    print("\n3. Requisitions, postings and pipelines")
    hires = 0
    postings = 0
    candidates = 0
    # The whole loop is guarded so that a failure ANYWHERE still leaves every record it
    # created carrying the marker. Without this, a crash mid-engagement strands unmarked
    # records that `--undo` cannot see and somebody has to delete by hand.
    try:
        for spec in engagements(clients):
            raised = await raise_requisition(ctx, spec, departments, designations)
            published = await PS.create_posting(actors["HR"], company_id, {
                "jd_no": raised["jd_no"],
                "requires_assessment": spec["assessment"],
                "expiry_date": day(45),
                "notes": "Shared on the job boards and the referral channel."})
            postings += 1
            code = published["posting"]["posting_code"]

            grouped = await apply_candidates(ctx, code, raised["request_no"], spec["mix"])
            candidates += sum(len(v) for v in grouped.values())
            await screen(ctx, grouped)
            await share_with_client(ctx, grouped)
            await assess(ctx, grouped)
            await interview(ctx, grouped)
            hires += await offer_and_join(ctx, grouped, spec["desig"])

            if spec["closing"] != "Open":
                await RS.close_requisition(actors["MD"], company_id,
                                           raised["request_no"], spec["closing"])
                log(f"{'':<42} requisition closed as {spec['closing']}")
            await stamp(company_id, started_at)
    except BaseException:
        marked = await stamp(company_id, started_at)
        print(f"\nFAILED. {marked} partial record(s) stamped `{MARKER}` on the way out.")
        print(f"Remove them with:  python scripts/seed_hrms_realistic_ops.py "
              f"--company {company_id} --undo\n")
        raise

    print("\n4. The internal track -- Sparsh Magic hiring for itself")
    # Wrapped in the same guard as the client loop above, so a failure here still
    # leaves every record it created carrying the marker for `--undo`.
    try:
        internal = await seed_internal_track(ctx, departments, designations)
    except BaseException:
        marked = await stamp(company_id, started_at)
        print(f"\nFAILED in the internal track. {marked} partial record(s) "
              f"stamped `{MARKER}` on the way out.")
        print(f"Remove them with:  python scripts/seed_hrms_realistic_ops.py "
              f"--company {company_id} --undo\n")
        raise
    await stamp(company_id, started_at)

    print("\n5. Stamping")
    await stamp(company_id, started_at)
    stamped = await marked_total(company_id)

    print(f"\nDone. {stamped} document(s) stamped `demo_seed: \"{MARKER}\"`.")
    print(f"  {len(engagements(clients))} requisitions across {len(clients)} clients "
          f"plus in-house")
    print(f"  {postings} job postings, {candidates} candidates, {hires} joined")
    print(f"  internal: {internal['request_no']} -- "
          f"{internal['candidates']} candidates, "
          f"{internal['confirmed']} confirmed, "
          f"{internal['blocked']} blocked by the statutory check")
    print(f"  one candidate released past the shortlisting committee "
          f"by {internal['exception']}")
    print(f"\nRemove them with:  python scripts/seed_hrms_realistic_ops.py "
          f"--company {company_id} --undo\n")
    print("NOTE: `--undo` deletes documents created during this run's time window that "
          "carry the marker. Avoid using the HRMS module in another window while this "
          "script is running, or genuine records created in the same seconds would be "
          "stamped alongside it.\n")


async def preview(company_id: str) -> None:
    actors = await pick_actors(company_id)
    clients = await pick_clients(company_id, 5)
    specs = engagements(clients)
    total = sum(sum(s["mix"].values()) for s in specs)

    print(f"\nDry run for company {company_id} -- nothing was written.\n")
    print(f"  raiser / hiring manager : {actors['HOD']['full_name']}")
    print(f"  HR recruiter            : {actors['HR']['full_name']}")
    print(f"  MD approver             : {actors['MD']['full_name']}")
    print(f"\n  would create {len(DEPARTMENTS)} departments, {len(DESIGNATIONS)} "
          f"designations, {len(SANCTIONED)} sanctioned figures")
    print(f"  {len(specs)} requisitions + JDs + postings, {total} candidates\n")
    for s in specs:
        who = "in-house" if not s["client"] else "client"
        print(f"    {s['desig']:<30} {s['vacancy']} seat(s)  {who:<9} "
              f"{sum(s['mix'].values()):>2} applicants  closing={s['closing']}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="company_id to seed")
    parser.add_argument("--undo", action="store_true",
                        help="delete records previously seeded by THIS script")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be created, write nothing")
    args = parser.parse_args()

    client = await connect()
    try:
        if args.undo:
            await undo(args.company)
        elif args.dry_run:
            await preview(args.company)
        else:
            await seed(args.company)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
