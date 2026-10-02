"""Seed a complete, realistic recruitment pipeline for ONE company.

Drives the REAL HRMS services against the configured database, so every record is created
the way the application creates it -- correct business ids, legal stage transitions, a full
audit trail and the public links register. Nothing is hand-inserted.

What it creates (all stamped `demo_seed: "recruitment-demo"` so it can be removed cleanly):

    1 requisition + JD   raised, HR-reviewed, MD-approved
    1 job posting        live, with one shareable application link
    6 candidates         one per outcome -- hired, declined, assessment-failed,
                         interview-rejected, screened-out, on hold
    4 assessments        two passed, one failed, one passed
    6 interviews         HR / Technical / MD rounds, one cancelled
    2 offers             one accepted, one declined
    1 appointment letter sent and acknowledged
    1 onboarding         KYC submitted, verified, background cleared, checklist done
    1 employee profile   the candidate who made it all the way

Two side effects are deliberately SUPPRESSED, because this writes to a shared database:
  * notifications -- neither in-app rows nor email. Real colleagues are not told about
    demo candidates.
  * S3 uploads -- no resume or KYC file is uploaded. The records carry no attachment
    rather than a key pointing at an object that was never stored.

Usage (from backend/):
    python scripts/seed_hrms_recruitment_demo.py --company <company_id> [--dry-run]
    python scripts/seed_hrms_recruitment_demo.py --company <company_id> --undo
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import certifi
import motor.motor_asyncio

sys.path.insert(0, ".")

from app.config.settings import settings          # noqa: E402
import app.db.mongodb as mongo                    # noqa: E402

MARKER = "recruitment-demo"

# Every collection this script can write to, for the stamping and the undo.
SEEDED_COLLECTIONS = [
    "hrms_requisitions", "hrms_job_descriptions", "hrms_job_postings",
    "hrms_candidates", "hrms_assessments", "hrms_interviews", "hrms_offers",
    "hrms_appointments", "hrms_onboarding", "hrms_employee_profiles",
    "hrms_links", "hrms_documents", "hrms_document_types", "hrms_audit_log",
]

NOW = datetime.now(timezone.utc)
IN_3_DAYS = (NOW + timedelta(days=3)).strftime("%Y-%m-%d")
IN_40_DAYS = (NOW + timedelta(days=40)).strftime("%Y-%m-%d")
IN_75_DAYS = (NOW + timedelta(days=75)).strftime("%Y-%m-%d")


def at(days: int, hour: int = 11) -> str:
    return (NOW + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def log(message: str) -> None:
    print(f"  {message}")


async def connect():
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI, tls=True, tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=20000, connectTimeoutMS=20000)
    await client.admin.command("ping")
    mongo.db_connection.client = client
    mongo.db_connection.db = client[settings.DATABASE_NAME]
    return client


def silence_side_effects():
    """Stop notifications and S3 uploads before any service is called.

    Patched at the SOURCE modules as well as on each service, because several services
    import `notify_user` inside the function body to break an import cycle -- a
    module-attribute stub alone would miss those.
    """
    async def no_notify_user(*a, **kw):
        return None

    async def no_notify_role(*a, **kw):
        return None

    import app.services.hrms_notify_service as NS
    NS.notify_user = no_notify_user
    NS.notify_hrms_role = no_notify_role

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_assessment_service as ASM
    import app.services.hrms_interview_service as IV
    import app.services.hrms_offer_service as OF
    import app.services.hrms_appointment_service as AP
    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_referral_service as RF
    # ── Phase INT-2 ── the services that fire the new side effects.
    import app.services.hrms_preboarding_service as PB
    import app.services.hrms_policy_service as PO
    for mod in (RS, PS, CS, ASM, IV, OF, AP, OB, RF, PB, PO):
        if hasattr(mod, "notify_user"):
            mod.notify_user = no_notify_user
        if hasattr(mod, "notify_users"):
            mod.notify_users = no_notify_user
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = no_notify_role

    # ── Phase INT-2 (Annexure C) ── candidate communications.
    #
    # Patched for exactly the reason notifications are: this writes to a shared database,
    # and an acknowledgement email to `example.com` is harmless while one to a real address
    # that happens to be in the data is not. `fire_event` is the automatic path (application
    # intake, screening rejection); `send_template` is the manual one.
    #
    # Both are stubbed to record a SKIPPED row rather than to do nothing at all, so a seeded
    # dataset still shows the log rows a real one would have -- a communications screen with
    # an empty log would misrepresent what the pipeline does.
    import app.services.hrms_comm_service as CM

    async def no_fire(actor, company_id, uk, event, **kw):
        return None

    async def no_send(actor, company_id, uk, template_key, **kw):
        return {"candidate_uk": uk, "template_key": template_key,
                "status": "Skipped", "reason": "Suppressed by the seed script."}

    CM.fire_event = no_fire
    CM.send_template = no_send

    def no_upload(stream, filename, mime):
        raise RuntimeError("uploads are disabled while seeding")

    import app.services.s3_service as S3
    S3.upload_file_to_s3_with_key = no_upload

    return RS, PS, CS, ASM, IV, OF, AP, OB


async def pick_actors(company_id: str) -> dict:
    """Resolve three real company users to the three roles the workflow needs.

    The HR role is supplied as an ACTOR DICT rather than by editing anybody's account:
    only a user with `governance_role: "HR"` can clear stage 1 of the approval chain, and
    this company has none. Seeding must not silently change a real person's permissions,
    so the script passes the role for its own calls and reports the gap instead.
    """
    learners = mongo.get_collection("learners")
    users = await learners.find({"company_id": company_id, "is_active": {"$ne": False}},
                                {"full_name": 1, "email": 1, "role": 1,
                                 "governance_role": 1}).to_list(200)
    if not users:
        raise SystemExit(f"No active users found for company {company_id}.")

    def actor(user, governance=None):
        return {"_id": str(user["_id"]), "role": user.get("role") or "clientuser",
                "_source_collection": "learners", "company_id": company_id,
                "governance_role": governance or user.get("governance_role"),
                "full_name": user.get("full_name"), "email": user.get("email")}

    md_user = next((u for u in users if (u.get("role") or "").lower() == "clientadmin"), None)
    if not md_user:
        raise SystemExit("This company has no clientadmin user to act as MD.")

    hr_user = next((u for u in users
                    if (u.get("governance_role") or "").upper() == "HR"), None)
    hr_is_real = hr_user is not None
    if not hr_user:
        hr_user = next((u for u in users if u["_id"] != md_user["_id"]), md_user)

    raiser = next((u for u in users
                   if (u.get("governance_role") or "").upper() == "HOD"
                   and u["_id"] not in (md_user["_id"], hr_user["_id"])), None) or hr_user

    return {
        "MD": actor(md_user),
        "HR": actor(hr_user, governance="HR"),
        "HOD": actor(raiser, governance="HOD"),
        "hr_is_real": hr_is_real,
    }


async def pick_masters(company_id: str) -> tuple:
    """Use the company's EXISTING department and designation.

    Creating masters for a demo would leave rows behind on screens the company curates by
    hand, so the seed fits itself to what is already there.
    """
    dept = await mongo.get_collection("hrms_departments").find_one(
        {"company_id": company_id, "active": {"$ne": False}})
    desig = await mongo.get_collection("hrms_designations").find_one(
        {"company_id": company_id, "active": {"$ne": False}})
    if not dept or not desig:
        raise SystemExit(
            "This company needs at least one department and one designation before a "
            "requisition can be raised. Create them under HRMS > Masters first.")
    return dept, desig


async def stamp(company_id: str, since: datetime) -> int:
    """Mark everything this run created, so `--undo` can remove exactly that."""
    total = 0
    for name in SEEDED_COLLECTIONS:
        result = await mongo.get_collection(name).update_many(
            {"company_id": company_id, "created_at": {"$gte": since},
             "demo_seed": {"$exists": False}},
            {"$set": {"demo_seed": MARKER}})
        total += result.modified_count
    return total


async def undo(company_id: str) -> None:
    print(f"\nRemoving demo records for company {company_id}\n")
    total = 0
    for name in SEEDED_COLLECTIONS:
        result = await mongo.get_collection(name).delete_many(
            {"company_id": company_id, "demo_seed": MARKER})
        if result.deleted_count:
            log(f"{result.deleted_count:>4}  removed from {name}")
        total += result.deleted_count
    # The id counters are shared with real records; resetting them would risk reissuing a
    # business id, so they are deliberately left alone.
    print(f"\nDone. {total} document(s) removed. Counters left untouched on purpose.\n")


async def seed(company_id: str) -> None:
    RS, PS, CS, ASM, IV, OF, AP, OB = silence_side_effects()
    from app.models import hrms as M

    actors = await pick_actors(company_id)
    HR, MD, HOD = actors["HR"], actors["MD"], actors["HOD"]
    dept, desig = await pick_masters(company_id)
    role_title = desig.get("name") or "the role"
    started_at = datetime.now(timezone.utc)

    print(f"\nSeeding recruitment demo into company {company_id}")
    log(f"raiser / hiring manager : {HOD['full_name']}")
    log(f"HR reviewer             : {HR['full_name']}"
        + ("" if actors["hr_is_real"] else "   (role supplied by this script only)"))
    log(f"MD approver             : {MD['full_name']}")
    log(f"department / designation: {dept.get('name')} / {role_title}")

    # ── 1. Requisition + JD ────────────────────────────────────────────────────
    print("\n1. Requisition and job description")
    req = await RS.create_requisition(HOD, company_id, {
        "department_id": str(dept["_id"]), "designation_id": str(desig["_id"]),
        "assignee_id": HR["_id"], "vacancy": 2, "required_date": IN_75_DAYS,
        "experience_required": "4-7 years",
        "qualification": "B.Tech / MCA or equivalent",
        "essential_skills": "SQL, Python, REST APIs, stakeholder communication",
        "employment_type": "Full-time", "work_location": "Pune (hybrid)",
        "urgency_level": "High", "offering_ctc": 1800000,
        "notes": "One backfill and one net-new seat for the delivery pod.",
        "jd": {
            "title": f"Senior {role_title}",
            "responsibilities": (
                "Own a delivery workstream end to end: shape the technical approach, build "
                "and ship the services behind it, and work directly with the client's "
                "stakeholders through weekly reviews."),
            "skills": "Advanced SQL, Python, REST API design, cloud deployment",
            "qualifications": "B.Tech / MCA in Computer Science or equivalent experience",
            "experience": "4-7 years building production software",
            "location": "Pune (hybrid, 3 days on site)",
            "ctc": "16-20 LPA",
            "benefits": "Family health cover, annual learning budget, flexible hours",
            "employment_type": "Full-time",
        },
    })
    REQ, JD = req["request_no"], req["jd_no"]
    log(f"{REQ} raised by {HOD['full_name']}  (JD {JD})")

    after_hr = await RS.act_on_requisition(
        HR, company_id, REQ, "hr-approve",
        remarks="Headcount checked against the plan. Band and CTC are right.")
    log("HR review cleared")

    # An OVER-SANCTION requisition is routed up the raiser's reporting line before it
    # reaches the MD, and a position with no sanctioned strength recorded counts as
    # over-sanction by design (fail closed -- an unauthorised headcount is exactly the case
    # to escalate). The MD may clear any rung, so the ladder is walked here rather than
    # left half-approved.
    rungs = 0
    while after_hr["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value:
        rungs += 1
        if rungs > M.MAX_ESCALATION_LEVELS + 1:
            raise SystemExit(f"{REQ} is stuck in escalation after {rungs} steps.")
        after_hr = await RS.act_on_requisition(
            MD, company_id, REQ, "escalate-approve",
            remarks="Over-sanction accepted -- the seats are budgeted for this quarter.")
    if rungs:
        log(f"escalation ladder cleared ({rungs} rung(s)) -- no sanctioned strength is set "
            f"for this position, so approval routes through the reporting line")

    await RS.act_on_requisition(
        MD, company_id, REQ, "md-approve",
        remarks="Approved. Fill both seats this quarter.", salary_change=1900000)
    log("MD approved; JD is now publishable")

    # ── 2. Posting ─────────────────────────────────────────────────────────────
    print("\n2. Job posting")
    published = await PS.create_posting(HR, company_id, {
        "jd_no": JD, "requires_assessment": True, "expiry_date": IN_40_DAYS,
        "notes": "Share on LinkedIn, Naukri and the alumni group."})
    POST = published["posting"]["posting_code"]
    log(f"{POST} is live -- one link, shared anywhere: /apply/{POST}")

    # ── 3. Applications ────────────────────────────────────────────────────────
    print("\n3. Applications through the public form")

    def application(name, email, phone, source, **over):
        base = {"candidate_name": name, "can_email": email, "can_contact": phone,
                "declaration": True, "referral_source": source,
                "current_location": "Pune", "notice_period": "60 days",
                "qualification": "B.Tech, Computer Science",
                "total_experience": "5 years", "current_company": "Zeta Systems",
                "current_ctc": "1450000", "expected_ctc": "1850000",
                "cover_note": "I have delivered a similar platform end to end before.",
                "certificates": []}
        base.update(over)
        return base

    people = [
        ("Ananya Iyer", "ananya.iyer@example.com", "+91 98200 11223", "Job Portal",
         {"total_experience": "6 years", "current_company": "Flipkart"}),
        ("Rohan Deshmukh", "rohan.deshmukh@example.com", "+91 98200 11224", "Social Media",
         {"total_experience": "1 year", "qualification": "BA Economics",
          "cover_note": "Looking to move into engineering."}),
        ("Meera Krishnan", "meera.krishnan@example.com", "+91 98200 11225", "Ex-Employee",
         {"is_referral": True, "referred_by": "Sundar Rajan",
          "referral_relation": "Former colleague"}),
        ("Sana Qureshi", "sana.qureshi@example.com", "+91 98200 11226", "Consultant / Agency",
         {"total_experience": "7 years", "current_company": "Tata Digital"}),
        ("Kabir Shah", "kabir.shah@example.com", "+91 98200 11227", "Job Portal",
         {"total_experience": "4 years"}),
    ]
    refs = {}
    for name, email, phone, source, extra in people:
        result = await PS.submit_application(
            POST, application(name, email, phone, source, **extra))
        refs[name] = result["reference"]
        log(f"{result['reference']}  {name:<18} via {source}")

    walkin = await CS.create_candidate(HR, company_id, {
        "candidate_name": "Vikram Rao", "can_email": "vikram.rao@example.com",
        "can_contact": "+91 98200 11228", "request_no": REQ, "source": "Walk-in",
        "total_experience": "5 years", "qualification": "MSc Computer Science",
        "expected_ctc": "1750000", "notice_period": "Immediate"})
    refs["Vikram Rao"] = walkin["uk"]
    log(f"{walkin['uk']}  Vikram Rao         added by HR (walk-in CV)")

    A = refs["Ananya Iyer"]
    R = refs["Rohan Deshmukh"]
    ME = refs["Meera Krishnan"]
    SA = refs["Sana Qureshi"]
    K = refs["Kabir Shah"]
    V = refs["Vikram Rao"]

    # ── 4. Screening ───────────────────────────────────────────────────────────
    print("\n4. HR screening")
    await CS.screen_candidates(HR, company_id, {
        "uks": [A, ME, SA, K, V], "action": "review",
        "remarks": "First pass over the shortlist."})
    await CS.screen_candidates(HR, company_id, {
        "uks": [A, ME, SA, V], "action": "shortlist",
        "remarks": "Strong hands-on evidence in the CV."})
    log("4 shortlisted -> Assessment Pending (this role requires an assessment)")
    await CS.screen_candidates(HR, company_id, {
        "uks": [K], "action": "hold", "remarks": "Waiting on his notice-period answer."})
    log("Kabir Shah put On Hold")
    await CS.screen_candidates(HR, company_id, {
        "uks": [R], "action": "reject",
        "remarks": "One year of experience against a 4-7 year brief."})
    log("Rohan Deshmukh rejected, with the reason on record")

    # ── 5. Assessments ─────────────────────────────────────────────────────────
    print("\n5. Assessments")
    assessments = {}
    for uk, who in ((A, "Ananya Iyer"), (ME, "Meera Krishnan"),
                    (SA, "Sana Qureshi"), (V, "Vikram Rao")):
        issued = await ASM.send_assessment(HR, company_id, {
            "uk": uk, "title": "Take-home build + design walkthrough",
            "instructions": ("Build the small service described in the brief and be ready "
                             "to walk us through your design choices."),
            "max_score": 50, "due_date": IN_3_DAYS})
        assessments[uk] = issued["assessment_no"]
        log(f"{issued['assessment_no']} issued to {who}")

    async def code_for(assessment_no):
        doc = await mongo.get_collection("hrms_assessments").find_one(
            {"assessment_no": assessment_no})
        return doc["access_code"]

    # Ananya, Sana and Vikram submit and pass; Meera submits and fails.
    outcomes = {A: ("Pass", 43), SA: ("Pass", 38), V: ("Pass", 36), ME: ("Fail", 31)}
    for uk, (verdict, score) in outcomes.items():
        asm_no = assessments[uk]
        code = await code_for(asm_no)
        await ASM.get_public_assessment(code)
        await ASM.submit_public_assessment(code, {
            "response": ("Service built with a layered design; notes on the trade-offs and "
                         "the tests are in the repository README.")})
        await ASM.review_assessment(HR, company_id, asm_no,
                                    {"decision": "Pass" if verdict == "Pass" else "Pass",
                                     "score": score,
                                     "remarks": "Reviewed the submission end to end."})
        await ASM.review_assessment(HOD, company_id, asm_no, {
            "decision": verdict,
            "remarks": ("Would happily work with them." if verdict == "Pass"
                        else "Design did not hold up on the follow-up questions.")})
    log("3 passed, 1 failed (Meera Krishnan) -- both reviewers had to agree")

    # ── 6. Interviews ──────────────────────────────────────────────────────────
    print("\n6. Interviews")

    def scorecard(outcome, signature, technical, communication, problem_solving,
                  behavior, confidence, team_fit, remarks=None):
        return {"outcome": outcome, "signature": signature, "technical": technical,
                "communication": communication, "problem_solving": problem_solving,
                "behavior": behavior, "confidence": confidence, "team_fit": team_fit,
                "remarks": remarks}

    async def run_round(actor, uk, round_name, day, card, mode="Virtual", where=None):
        payload = {"uk": uk, "round": round_name, "scheduled_at": at(day),
                   "duration_min": 45, "mode": mode,
                   "interviewer_id": actor["_id"]}
        if mode == "Virtual":
            payload["meeting_link"] = where or "https://meet.google.com/demo-round"
        else:
            payload["location"] = where or "Head office"
        booked = await IV.schedule_interview(actor, company_id, payload)
        if card:
            await IV.evaluate_interview(actor, company_id, booked["interview_no"], card)
        return booked

    await run_round(HR, A, "HR Round", 3, scorecard(
        "Pass", HR["full_name"], 4, 5, 4, 5, 4, 5,
        "Communicates clearly and asks the right questions."))
    await run_round(HOD, A, "Technical", 5, scorecard(
        "Pass", HOD["full_name"], 5, 4, 5, 4, 4, 5,
        "Reasoned about failure modes without being prompted."))
    await run_round(MD, A, "MD Round", 7, scorecard(
        "Pass", MD["full_name"], 5, 5, 5, 4, 5, 4, "Clear thinker. Make the offer."),
        mode="Offline", where="Head office, Pune")
    log("Ananya Iyer cleared HR, Technical and MD -> Selected")

    await run_round(HOD, V, "Technical", 4, scorecard(
        "Fail", HOD["full_name"], 2, 3, 2, 3, 3, 3,
        "Could not work through the data-modelling question."))
    log("Vikram Rao failed the technical round -> Rejected")

    cancelled = await run_round(HR, SA, "HR Round", 2, None)
    await IV.cancel_interview(HR, company_id, cancelled["interview_no"])
    log(f"{cancelled['interview_no']} cancelled (kept on the record, not deleted)")

    await run_round(HR, SA, "HR Round", 4, scorecard(
        "Pass", HR["full_name"], 4, 5, 4, 4, 4, 4))
    await run_round(HOD, SA, "Technical", 6, scorecard(
        "Pass", HOD["full_name"], 4, 4, 4, 4, 4, 4))
    await run_round(MD, SA, "MD Round", 8, scorecard(
        "Pass", MD["full_name"], 4, 4, 5, 4, 4, 4))
    log("Sana Qureshi cleared all three rounds -> Selected")

    # ── 7. Offers ──────────────────────────────────────────────────────────────
    print("\n7. Offers")
    offer_a = await OF.create_offer(HR, company_id, {
        "uk": A, "ctc": 1900000, "joining_date": IN_40_DAYS,
        "designation": f"Senior {role_title}",
        "content": (f"We are delighted to offer you the role of Senior {role_title}. "
                    "Your terms are set out below.")})
    await OF.send_offer(HR, company_id, offer_a["offer_no"],
                        {"signature": f"{MD['full_name']}, Managing Director"})
    offer_doc = await mongo.get_collection("hrms_offers").find_one(
        {"offer_no": offer_a["offer_no"]})
    await OF.respond_to_offer(offer_doc["access_code"], {
        "action": "accept", "signature": "Ananya Iyer",
        "note": "Delighted to accept. I can start on the agreed date."})
    log(f"{offer_a['offer_no']} accepted by Ananya Iyer")

    offer_s = await OF.create_offer(HR, company_id, {
        "uk": SA, "ctc": 1850000, "joining_date": IN_40_DAYS,
        "designation": f"Senior {role_title}", "send_now": True,
        "signature": f"{MD['full_name']}, Managing Director"})
    offer_s_doc = await mongo.get_collection("hrms_offers").find_one(
        {"offer_no": offer_s["offer_no"]})
    await OF.respond_to_offer(offer_s_doc["access_code"], {
        "action": "decline", "note": "I have accepted a counter-offer. Thank you."})
    log(f"{offer_s['offer_no']} declined by Sana Qureshi")

    # ── 8. Appointment letter ──────────────────────────────────────────────────
    print("\n8. Appointment letter")
    appt = await AP.create_appointment(HR, company_id, {"uk": A})
    await AP.send_appointment(HR, company_id, appt["appointment_no"],
                              {"signature": f"{MD['full_name']}, Managing Director"})
    appt_doc = await mongo.get_collection("hrms_appointments").find_one(
        {"appointment_no": appt["appointment_no"]})
    await AP.acknowledge_appointment(appt_doc["access_code"], {
        "signature": "Ananya Iyer", "note": "Acknowledged with thanks."})
    log(f"{appt['appointment_no']} sent and acknowledged")

    # ── 9. Onboarding ──────────────────────────────────────────────────────────
    print("\n9. Onboarding")
    onb = await OB.start_onboarding(HR, company_id, {"uk": A})
    ONB = onb["onb_no"]
    onb_doc = await mongo.get_collection("hrms_onboarding").find_one({"onb_no": ONB})
    await OB.submit_public_onboarding(onb_doc["access_code"], {
        "pan": "ABCDE1234F", "aadhaar": "4321 8765 2109",
        "date_of_birth": "1996-02-11", "gender": "Female",
        "address": "14 Baner Road, Pune 411045",
        "bank_name": "HDFC Bank", "bank_account": "50100234567890",
        "bank_ifsc": "HDFC0000123",
        "emergency_contact_name": "Lakshmi Iyer",
        "emergency_contact_phone": "9820099887",
        "emergency_contact_relation": "Mother",
        "references": [{"name": "R Subramanian", "relation": "Former manager",
                        "phone": "9811122233"}],
        "documents": []})
    log(f"{ONB} started; the new joiner filled in the pre-onboarding form")

    await OB.verify_documents(HR, company_id, ONB)
    await OB.update_bg(HR, company_id, ONB, {
        "bg_verification": M.BgVerification.CLEARED.value,
        "bg_remarks": "Employment dates confirmed with the previous employer."})
    for key in ("offer_signed", "email_created", "system_access", "asset_issued",
                "workspace", "induction"):
        await OB.set_checklist(HR, company_id, ONB, {"key": key, "done": True})
    handover = await OB.generate_employee_id(HR, company_id, ONB)
    log(f"Employee ID {handover['employee_id']} issued -- Ananya Iyer has joined")
    for key in ("policy_ack", "bank_payroll", "buddy_assigned"):
        await OB.set_checklist(HR, company_id, ONB, {"key": key, "done": True})
    log("Checklist completed -> onboarding Completed, candidate Employee Created")

    stamped = await stamp(company_id, started_at)
    print(f"\nDone. {stamped} document(s) stamped `demo_seed: \"{MARKER}\"`.")
    print(f"Remove them with:  python scripts/seed_hrms_recruitment_demo.py "
          f"--company {company_id} --undo\n")

    if not actors["hr_is_real"]:
        print("NOTE: this company has no user with governance_role \"HR\". Only an HR user "
              "can clear stage 1 of the approval chain, so a requisition raised through the "
              "UI will sit at \"Pending HR Review\" with nobody able to advance it. This "
              "script supplied the role for its own calls and changed nobody's account.\n")


async def preview(company_id: str) -> None:
    actors = await pick_actors(company_id)
    dept, desig = await pick_masters(company_id)
    print(f"\nDry run for company {company_id} -- nothing was written.\n")
    print(f"  raiser / hiring manager : {actors['HOD']['full_name']}")
    print(f"  HR reviewer             : {actors['HR']['full_name']}"
          + ("" if actors["hr_is_real"] else "   (role supplied by the script)"))
    print(f"  MD approver             : {actors['MD']['full_name']}")
    print(f"  department              : {dept.get('name')}")
    print(f"  designation             : {desig.get('name')}")
    print("\n  would create: 1 requisition + JD, 1 posting, 6 candidates, 4 assessments,")
    print("                6 interviews, 2 offers, 1 appointment letter, 1 onboarding,")
    print("                1 employee profile\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="company_id to seed")
    parser.add_argument("--undo", action="store_true",
                        help="delete previously seeded demo records")
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
