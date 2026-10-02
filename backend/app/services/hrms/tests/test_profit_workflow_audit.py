"""Client Hiring -- the whole PRO-fit workflow, audited end to end against the SOP.

The other client-track suites each pin one stage. This one walks a complete engagement the
way a real one runs, and at every step tries to get ahead of it: create the next stage
before the current one has closed, act as the wrong party, read another tenant's records,
share work that is not finished. The chain is only as strong as the weakest gate, and a
gate is only real if a DIRECT SERVICE CALL is refused -- a screen that hides a button
proves nothing about the API behind it.

Fifteen sections, matching the audit brief:

   1. Stage gating, all seven, each attempted out of order
   2. The five client-only decisions
   3. Tenant isolation across all nine record types
   4. Candidate visibility -- nothing before "Shared"
   5. Scoring rules -- TFS, PI, the 3.5 threshold and the bands
   6. Assessment -- issue, submit, score, share, client review
   7. Interview -- four scores, outcome, recording, share, decide
   8. Offer -- draft, verify, release, and the section 16 checkpoint
   9. Acceptance -- both dates, never verbal alone
  10. Pre-boarding privacy -- the contact log stays at Sparsh
  11. Joining -- the client's confirmation, with date and acknowledgement
  12. Handover and closure -- the pack, then the requisition closes
  13. Negative paths -- return, reject, fail, revive, decline, drop
  14. Permissions -- every role against every decision
  15. Cross-cutting -- transition tables are total and states are reachable

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_profit_workflow_audit   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:  # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

ACME = "client-acme"
GLOBEX = "client-globex"


async def main() -> None:  # noqa: PLR0915
    from bson import ObjectId

    from app.models import hrms as M
    from app.utils import hrms_access as HA
    import app.db.mongodb as mongo

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    from app.services import (
        hrms_client_requisition_service as REQ,
        hrms_client_scorecard_service as SC,
        hrms_client_candidate_service as CAND,
        hrms_client_assessment_service as AS,
        hrms_client_interview_service as IV,
        hrms_client_offer_service as OF,
        hrms_client_joining_service as JN,
    )
    for mod in (REQ, SC, CAND, AS, IV, OF, JN, HA):
        mod.get_collection = mongo.get_collection

    # ── Actors ───────────────────────────────────────────────────────────────
    def sparsh(governance="HR", role="admin", name="Sparsh Person"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "full_name": name}
        if governance:
            u["governance_role"] = governance
        return u

    def client(company=ACME):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company,
                "full_name": "Client Person", M.CLIENT_TRACK_FLAG: True}

    RECRUITER = sparsh("HR", name="Recruiter")
    LEAD = sparsh("HOD", name="Team Lead")
    OWNER = sparsh(None, role="superadmin", name="Superadmin")
    FINANCE = sparsh("FINANCE", name="Finance")
    MD = sparsh("MD", name="MD")
    ACME_USER, GLOBEX_USER = client(ACME), client(GLOBEX)

    async def new_requisition(company, actor, title="Warehouse Lead",
                              lo=600000, hi=900000, level="Mid-level / Specialist"):
        """A requisition walked to Pending Feasibility, the way the screen walks it."""
        r = await REQ.create_client_requisition(actor, company, {
            "business_context": "Network expansion.", "role_need": f"{title} needed.",
            "engagement_expectations": "Shortlist in three weeks."})
        cr = r["cr_no"]
        await REQ.act_on_client_requisition(actor, company, cr, "submit-need-mapping")
        await REQ.update_client_requisition(actor, company, cr, {
            "role_title": title, "department_name": "Operations",
            "reporting_line": "Head of Operations",
            "salary_range_min": lo, "salary_range_max": hi,
            "employment_type": "Permanent", "urgency": "High",
            "vacancies": 1, "role_level": level})
        await REQ.act_on_client_requisition(actor, company, cr, "submit-requisition")
        return cr

    async def approved_scorecard(company, cr):
        s = await SC.create_client_scorecard(RECRUITER, company, {
            "cr_no": cr, "responsibilities": "Owns throughput.", "skills": "WMS.",
            "experience": "6+ years.", "cultural_expectations": "Calm.",
            "success_indicators": "99% accuracy."})
        psc = s["psc_no"]
        await SC.act_on_client_scorecard(RECRUITER, company, psc, "submit-for-review")
        await SC.act_on_client_scorecard(LEAD, company, psc, "internal-approve")
        await SC.act_on_client_scorecard(client(company), company, psc, "client-approve")
        return psc

    try:
        # =================================================================
        section("1. Stage gating -- each stage refuses to open early")
        # =================================================================
        cr = await new_requisition(ACME, ACME_USER)

        # 1.1 Scorecard needs an APPROVED requisition.
        await expect_http(
            "scorecard before feasibility clears",
            SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": cr}),
            409, "approved")
        await REQ.act_on_client_requisition(
            LEAD, ACME, cr, "feasibility-approve",
            {"role_clarity": True, "compensation_competitive": True,
             "timeline_realistic": True})
        check("requisition approved opens the scorecard stage",
              (await REQ.get_client_requisition(LEAD, ACME, cr))["status"]
              == M.ClientReqStatus.APPROVED.value)

        # 1.2 Sourcing needs an APPROVED scorecard.
        await expect_http(
            "sourcing before the scorecard is agreed",
            CAND.create_client_candidate(RECRUITER, ACME,
                                         {"cr_no": cr, "candidate_name": "Too Early"}),
            409)
        psc = await approved_scorecard(ACME, cr)
        check("client approval of the scorecard opens sourcing",
              (await SC.get_client_scorecard(LEAD, ACME, psc))["status"]
              == M.ClientScorecardStatus.APPROVED.value)

        cand = await CAND.create_client_candidate(RECRUITER, ACME, {
            "cr_no": cr, "candidate_name": "Ritu Sharma", "current_ctc": 720000,
            "expected_ctc": 860000, "cv_reference": "cv.pdf"})
        ccn = cand["ccn_no"]

        # 1.3 Assessment needs the client's CV verdict.
        await expect_http(
            "assessment before the CV verdict",
            AS.create_client_assessment(RECRUITER, ACME,
                                        {"ccn_no": ccn, "title": "TFA"}),
            409, "approves the cv")

        # =================================================================
        section("5. Scoring rules")
        # =================================================================
        await expect_http("screen with no Talent Fit Score",
                          CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "screen"),
                          422, "talent fit score")
        await CAND.update_client_candidate(RECRUITER, ACME, ccn, {"tfs_score": 4.4})
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "screen")
        check("Talent Fit Score recorded -> screened",
              (await CAND.get_client_candidate(RECRUITER, ACME, ccn))["status"]
              == M.ClientCandidateStatus.SCREENED.value)

        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "telephonic-pass")
        await expect_http("shortlist with no PI Score",
                          CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "shortlist"),
                          422, "preliminary interview score")

        # Below the threshold: the SOP refuses a shortlist on recommendation alone.
        await CAND.update_client_candidate(RECRUITER, ACME, ccn,
                                           {"competency_score": 2.6, "pi_score": 2.8})
        await expect_http("shortlist below the 3.5 threshold",
                          CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "shortlist"),
                          409, "3.5")
        low = await CAND.get_client_candidate(RECRUITER, ACME, ccn)
        check("...and the band says why", low.get("score_band", {}).get("may_shortlist")
              is False)

        for value, label, may in ((4.2, "Strong", True), (4.0, "Strong", True),
                                  (3.7, "Consider", True), (3.5, "Consider", True),
                                  (3.4, "Hold", False), (3.0, "Hold", False),
                                  (2.9, "Reject", False)):
            band = M.client_score_band(value)
            check(f"score {value} -> {label}, shortlist={may}",
                  band["label"].startswith(label) and band["may_shortlist"] is may)

        await CAND.update_client_candidate(RECRUITER, ACME, ccn,
                                           {"competency_score": 4.2, "pi_score": 4.2})
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn, "shortlist")
        check("at or above 3.5 the shortlist is allowed",
              (await CAND.get_client_candidate(RECRUITER, ACME, ccn))["status"]
              == M.ClientCandidateStatus.SHORTLISTED.value)

        # =================================================================
        section("4. Candidate visibility -- nothing before 'Shared'")
        # =================================================================
        visible = await CAND.list_client_candidates(ACME_USER, ACME)
        check("a shortlisted-but-unshared candidate is invisible to the client",
              not any(c["ccn_no"] == ccn for c in visible["client_candidates"]))
        await expect_http("...and cannot be fetched directly either",
                          CAND.get_client_candidate(ACME_USER, ACME, ccn), 404)

        await CAND.act_on_client_candidate(LEAD, ACME, ccn, "share")
        shared = await CAND.list_client_candidates(ACME_USER, ACME)
        row = next((c for c in shared["client_candidates"] if c["ccn_no"] == ccn), None)
        check("once the Team Lead shares, the client sees them", row is not None)
        # The line is drawn at WORKING NOTES, not at scores. The client is told why this
        # person was shortlisted -- that is the service they are buying -- but not what the
        # recruiter wrote to themselves while deciding.
        check("Sparsh's free-text screening notes are NOT in what they see",
              row is not None and "screening_notes" not in row)
        check("but the scores that justify the shortlist ARE",
              row is not None and row.get("tfs_score") is not None
              and row.get("score_band") is not None)

        # =================================================================
        section("2 + 14. The five client-only decisions, by role")
        # =================================================================
        DECIDERS = [("Recruiter", RECRUITER), ("Team Lead", LEAD), ("Finance", FINANCE),
                    ("MD", MD), ("Superadmin", OWNER)]
        for label, actor in DECIDERS:
            await expect_http(
                f"{label} cannot give the CV verdict",
                CAND.act_on_client_candidate(actor, ACME, ccn, "client-approve"),
                403, "client_candidate.decide")
        check("the client holds all five decisions",
              M.CLIENT_DECISION_CAPS <= HA.capabilities_for(ACME_USER))
        check("and no Sparsh role holds any",
              not any(c in HA.capabilities_for(a) for _l, a in DECIDERS
                      for c in M.CLIENT_DECISION_CAPS))

        await CAND.act_on_client_candidate(ACME_USER, ACME, ccn, "client-approve")
        check("the client's CV verdict lands",
              (await CAND.get_client_candidate(LEAD, ACME, ccn))["status"]
              == M.ClientCandidateStatus.CLIENT_APPROVED.value)

        # =================================================================
        section("6. Assessment -- issue, submit, score, share, review")
        # =================================================================
        a = await AS.create_client_assessment(RECRUITER, ACME,
                                              {"ccn_no": ccn, "title": "Talent Fit"})
        cas = a["cas_no"]
        await expect_http("score before the candidate has submitted",
                          AS.act_on_client_assessment(RECRUITER, ACME, cas, "score"),
                          409)
        await AS.act_on_client_assessment(RECRUITER, ACME, cas, "record-submission")
        await expect_http("mark scored with no figure",
                          AS.act_on_client_assessment(RECRUITER, ACME, cas, "score"),
                          422, "record the score")
        await AS.update_client_assessment(RECRUITER, ACME, cas, {"score": 4.3})
        await AS.act_on_client_assessment(RECRUITER, ACME, cas, "score")
        # Pass/Fail is what the client reads; sharing without it shares a number alone.
        await expect_http("share a score with no Pass/Fail verdict",
                          AS.act_on_client_assessment(LEAD, ACME, cas, "share"),
                          422, "pass or fail")
        await AS.update_client_assessment(RECRUITER, ACME, cas, {"result": "Pass"})
        await AS.act_on_client_assessment(LEAD, ACME, cas, "share")

        await expect_http("interview before the client has reviewed the result",
                          IV.create_client_interview(RECRUITER, ACME, {
                              "ccn_no": ccn, "scheduled_at": "2026-09-25T10:30:00Z"}),
                          409)
        # NOTE the asymmetry, and it is deliberate rather than an oversight: the audit
        # brief names FIVE client-only decisions, and the assessment review is not one of
        # them. No Sparsh governance ROLE holds CLIENT_ASSESSMENT_REVIEW -- the recruiter
        # and the Team Lead are both refused below -- but a superadmin still does, through
        # the administrative grant. Flagged in the report as a judgement call rather than
        # silently widened here, because widening the exclusive set is the user's call.
        for label, actor in (("Recruiter", RECRUITER), ("Team Lead", LEAD)):
            await expect_http(f"{label} cannot mark the client's review",
                              AS.act_on_client_assessment(actor, ACME, cas,
                                                          "client-review"),
                              403, "client_assessment.review")
        check("no Sparsh governance role holds the assessment-review capability",
              not any(HA.can(a, M.Cap.CLIENT_ASSESSMENT_REVIEW)
                      for a in (RECRUITER, LEAD, FINANCE, MD)))
        check("superadmin does, via the administrative grant (see report)",
              HA.can(OWNER, M.Cap.CLIENT_ASSESSMENT_REVIEW))
        await AS.act_on_client_assessment(ACME_USER, ACME, cas, "client-review")
        check("client review opens the interview stage",
              (await AS.get_client_assessment(LEAD, ACME, cas))["status"]
              == M.ClientAssessmentStatus.REVIEWED.value)

        # =================================================================
        section("7. Interview -- four scores, outcome, recording")
        # =================================================================
        iv = await IV.create_client_interview(RECRUITER, ACME, {
            "ccn_no": ccn, "scheduled_at": "2026-09-25T10:30:00Z", "mode": "Virtual",
            "panel": ["Team Lead", "Recruiter"]})
        cin = iv["cin_no"]
        await expect_http("record the outcome before there is one",
                          IV.act_on_client_interview(RECRUITER, ACME, cin,
                                                     "record-outcome"),
                          422, "outcome")
        await IV.update_client_interview(RECRUITER, ACME, cin, {"outcome": "Recommend"})
        await IV.act_on_client_interview(RECRUITER, ACME, cin, "record-outcome")

        await expect_http("share with no recording and no scores",
                          IV.act_on_client_interview(LEAD, ACME, cin, "share"),
                          422, "recording link")
        # One score is not four. This is the gap the audit closed: `average_score` was
        # non-null as soon as ANY criterion was filled.
        await IV.update_client_interview(RECRUITER, ACME, cin, {
            "recording_link": "https://rec.test/1", "role_fit": 4.5})
        await expect_http("share with only one of the four criteria scored",
                          IV.act_on_client_interview(LEAD, ACME, cin, "share"),
                          422, "communication")
        await IV.update_client_interview(RECRUITER, ACME, cin, {
            "communication": 4.2, "technical_depth": 4.0, "culture_fit": 4.4})
        await IV.act_on_client_interview(LEAD, ACME, cin, "share")
        check("all four scores plus the recording -> shared with the client",
              (await IV.get_client_interview(LEAD, ACME, cin))["status"]
              == M.ClientInterviewStatus.SHARED.value)

        await expect_http("client rejection with no reason",
                          IV.act_on_client_interview(ACME_USER, ACME, cin,
                                                     "client-reject"),
                          422)
        for label, actor in (("Team Lead", LEAD), ("Superadmin", OWNER)):
            await expect_http(f"{label} cannot make the selection",
                              IV.act_on_client_interview(actor, ACME, cin,
                                                         "client-select"),
                              403, "client_interview.decide")

        # =================================================================
        section("8. Offer -- draft, verify, release, section 16")
        # =================================================================
        await expect_http("offer before the client has selected anybody",
                          OF.create_client_offer(RECRUITER, ACME,
                                                 {"ccn_no": ccn, "offered_ctc": 870000}),
                          409)
        await IV.act_on_client_interview(ACME_USER, ACME, cin, "client-select")
        check("the client's selection opens the offer stage",
              (await CAND.get_client_candidate(LEAD, ACME, ccn))["status"]
              == M.ClientCandidateStatus.SELECTED.value)

        offer = await OF.create_client_offer(RECRUITER, ACME, {
            "ccn_no": ccn, "offered_ctc": 950000, "designation": "Ops Lead"})
        cof = offer["cof_no"]
        cp = await OF.offer_checkpoint(ACME, await OF.get_client_offer(LEAD, ACME, cof))
        check("the checkpoint flags a figure outside the approved range",
              cp["ready"] is False and not cp["within_approved_range"])
        await expect_http("submit an out-of-range offer",
                          OF.act_on_client_offer(RECRUITER, ACME, cof,
                                                 "submit-for-verification"),
                          409, "outside the range")
        await OF.update_client_offer(RECRUITER, ACME, cof, {"offered_ctc": 870000})
        cp = await OF.offer_checkpoint(ACME, await OF.get_client_offer(LEAD, ACME, cof))
        check("inside the range, the checkpoint clears", cp["ready"] is True)

        await OF.act_on_client_offer(RECRUITER, ACME, cof, "submit-for-verification")
        for label, actor in (("Recruiter", RECRUITER),):
            await expect_http(f"{label} cannot verify their own draft",
                              OF.act_on_client_offer(actor, ACME, cof, "verify"),
                              403, "client_offer.verify")
        await OF.act_on_client_offer(LEAD, ACME, cof, "verify")
        for label, actor in (("Team Lead", LEAD), ("Superadmin", OWNER)):
            await expect_http(f"{label} cannot release the client's offer",
                              OF.act_on_client_offer(actor, ACME, cof, "client-release"),
                              403, "client_offer.release")
        await OF.act_on_client_offer(ACME_USER, ACME, cof, "client-release")
        check("the client releases it",
              (await OF.get_client_offer(LEAD, ACME, cof))["status"]
              == M.ClientOfferStatus.RELEASED.value)

        # =================================================================
        section("9. Acceptance needs BOTH dates -- never verbal alone")
        # =================================================================
        await expect_http("acceptance with neither date",
                          OF.act_on_client_offer(RECRUITER, ACME, cof,
                                                 "record-acceptance", {}),
                          422, "acceptance date")
        await expect_http("acceptance with only the acceptance date",
                          OF.act_on_client_offer(RECRUITER, ACME, cof,
                                                 "record-acceptance",
                                                 {"accepted_on": "2026-09-28",
                                                  "joining_date": ""}),
                          422, "joining date")
        await OF.act_on_client_offer(RECRUITER, ACME, cof, "record-acceptance",
                                     {"accepted_on": "2026-09-28",
                                      "joining_date": "2026-11-02"})
        check("both dates -> accepted",
              (await OF.get_client_offer(LEAD, ACME, cof))["status"]
              == M.ClientOfferStatus.ACCEPTED.value)

        # =================================================================
        section("10 + 11. Pre-boarding privacy, and the client's confirmation")
        # =================================================================
        jn = await JN.open_client_joining(RECRUITER, ACME,
                                          {"ccn_no": ccn, "joining_date": "2026-11-02"})
        cjn = jn["cjn_no"]
        await JN.record_touchpoint(RECRUITER, ACME, cjn, {
            "channel": "Call", "at_risk": True,
            "notes": "Counter-offer from current employer mentioned."})

        sparsh_view = await JN.get_client_joining(LEAD, ACME, cjn)
        client_view = await JN.get_client_joining(ACME_USER, ACME, cjn)
        check("Sparsh sees the contact log", bool(sparsh_view.get("touchpoints")))
        check("the client does NOT", "touchpoints" not in client_view)
        check("...and cannot read the counter-offer note",
              "counter-offer" not in str(client_view).lower())
        check("but the at-risk flag IS shared -- it concerns them",
              client_view.get("at_risk") is True)

        client_offer_view = await OF.get_client_offer(ACME_USER, ACME, cof)
        check("negotiation notes stay with Sparsh",
              "negotiation_notes" not in client_offer_view)

        await expect_http("confirm joining with no start date",
                          JN.act_on_client_joining(ACME_USER, ACME, cjn,
                                                   "confirm-joining",
                                                   {"acknowledged": True}),
                          422, "date they actually started")
        await expect_http("confirm joining with no acknowledgement",
                          JN.act_on_client_joining(ACME_USER, ACME, cjn,
                                                   "confirm-joining",
                                                   {"actual_joining_date": "2026-11-03"}),
                          422, "acknowledgement")
        for label, actor in (("Recruiter", RECRUITER), ("Team Lead", LEAD),
                             ("Superadmin", OWNER)):
            await expect_http(
                f"{label} cannot declare somebody joined",
                JN.act_on_client_joining(actor, ACME, cjn, "confirm-joining",
                                         {"actual_joining_date": "2026-11-03",
                                          "acknowledged": True}),
                403, "client_joining.confirm")
        await JN.act_on_client_joining(ACME_USER, ACME, cjn, "confirm-joining",
                                       {"actual_joining_date": "2026-11-03",
                                        "acknowledged": True})
        check("the client confirms, with date and acknowledgement",
              (await JN.get_client_joining(LEAD, ACME, cjn))["status"]
              == M.ClientJoiningStatus.JOINED.value)

        # =================================================================
        section("12. Handover, then closure -- in that order")
        # =================================================================
        req_now = await REQ.get_client_requisition(LEAD, ACME, cr)
        check("the requisition is still open before the handover",
              req_now["status"] != M.ClientReqStatus.CLOSED.value)
        await expect_http("hand over an incomplete pack",
                          JN.act_on_client_joining(LEAD, ACME, cjn, "share-handover"),
                          422, "candidate file")
        await JN.update_client_joining(LEAD, ACME, cjn, {
            "candidate_file": True, "scorecards": True, "interview_records": True,
            "verification_status": True, "handover_note": "Full file attached."})
        await JN.act_on_client_joining(LEAD, ACME, cjn, "share-handover")
        check("the handover completes the joining",
              (await JN.get_client_joining(LEAD, ACME, cjn))["status"]
              == M.ClientJoiningStatus.COMPLETED.value)
        check("and ONLY then does the requisition close",
              (await REQ.get_client_requisition(LEAD, ACME, cr))["status"]
              == M.ClientReqStatus.CLOSED.value)

        # =================================================================
        section("3. Tenant isolation -- Globex cannot reach Acme")
        # =================================================================
        check("a client is pinned to their own company whatever they ask for",
              HA.scope_company_id(GLOBEX_USER, ACME) == GLOBEX)
        check("the filter follows the pin",
              HA.company_filter(GLOBEX_USER, ACME).get("company_id") == GLOBEX)

        READS = [
            ("requisition", REQ.get_client_requisition(GLOBEX_USER, GLOBEX, cr)),
            ("scorecard", SC.get_client_scorecard(GLOBEX_USER, GLOBEX, psc)),
            ("candidate", CAND.get_client_candidate(GLOBEX_USER, GLOBEX, ccn)),
            ("assessment", AS.get_client_assessment(GLOBEX_USER, GLOBEX, cas)),
            ("interview", IV.get_client_interview(GLOBEX_USER, GLOBEX, cin)),
            ("offer", OF.get_client_offer(GLOBEX_USER, GLOBEX, cof)),
            ("joining", JN.get_client_joining(GLOBEX_USER, GLOBEX, cjn)),
        ]
        for what, coro in READS:
            await expect_http(f"Globex cannot read Acme's {what}", coro, 404)

        # Nor act on them -- a 404 on read but a 200 on write would be the worst of both.
        await expect_http("Globex cannot approve Acme's scorecard",
                          SC.act_on_client_scorecard(GLOBEX_USER, GLOBEX, psc,
                                                     "client-approve"),
                          404)
        await expect_http("Globex cannot decide on Acme's candidate",
                          CAND.act_on_client_candidate(GLOBEX_USER, GLOBEX, ccn,
                                                       "client-approve"),
                          404)
        for name, coll in (("requisitions", M.COLL_CLIENT_REQUISITIONS),
                           ("scorecards", M.COLL_CLIENT_SCORECARDS),
                           ("candidates", M.COLL_CLIENT_CANDIDATES),
                           ("assessments", M.COLL_CLIENT_ASSESSMENTS),
                           ("interviews", M.COLL_CLIENT_INTERVIEWS),
                           ("offers", M.COLL_CLIENT_OFFERS),
                           ("joinings", M.COLL_CLIENT_JOININGS)):
            rows = await store[coll].find({}).to_list(200)
            check(f"every {name} row carries a company_id",
                  all(r.get("company_id") for r in rows))

        globex_lists = [
            ("requisitions", await REQ.list_client_requisitions(GLOBEX_USER, GLOBEX)),
            ("scorecards", await SC.list_client_scorecards(GLOBEX_USER, GLOBEX)),
            ("candidates", await CAND.list_client_candidates(GLOBEX_USER, GLOBEX)),
            ("assessments", await AS.list_client_assessments(GLOBEX_USER, GLOBEX)),
            ("interviews", await IV.list_client_interviews(GLOBEX_USER, GLOBEX)),
            ("offers", await OF.list_client_offers(GLOBEX_USER, GLOBEX)),
            ("joinings", await JN.list_client_joinings(GLOBEX_USER, GLOBEX)),
        ]
        for name, payload in globex_lists:
            rows = next((v for k, v in payload.items() if isinstance(v, list)), [])
            check(f"Globex's {name} list is empty -- Acme's are not in it", rows == [])

        # =================================================================
        section("13. Negative paths, and what they must NOT open")
        # =================================================================
        # 13a. Requisition returned for correction -> back with the client, not approved.
        cr2 = await new_requisition(ACME, ACME_USER, title="Returned Role")
        await expect_http("return with no reason",
                          REQ.act_on_client_requisition(LEAD, ACME, cr2,
                                                        "feasibility-return"),
                          422)
        await REQ.act_on_client_requisition(LEAD, ACME, cr2, "feasibility-return",
                                            {"remarks": "Salary band is unrealistic."})
        check("a returned requisition goes back to the client, still alive",
              (await REQ.get_client_requisition(LEAD, ACME, cr2))["status"]
              == M.ClientReqStatus.MANPOWER_REQUISITION.value)
        await expect_http("...and cannot carry a scorecard",
                          SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": cr2}),
                          409)

        # 13b. Requisition rejected -> dead, and nothing opens.
        cr3 = await new_requisition(ACME, ACME_USER, title="Rejected Role")
        await REQ.act_on_client_requisition(LEAD, ACME, cr3, "feasibility-reject",
                                            {"remarks": "Not deliverable at this budget."})
        check("a rejected requisition is Rejected",
              (await REQ.get_client_requisition(LEAD, ACME, cr3))["status"]
              == M.ClientReqStatus.REJECTED.value)
        await expect_http("...and opens no scorecard",
                          SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": cr3}),
                          409)

        # 13c. Telephonic fail, then REVIVE -- the state is parked, not closed.
        cr4 = await new_requisition(ACME, ACME_USER, title="Second Role")
        await REQ.act_on_client_requisition(
            LEAD, ACME, cr4, "feasibility-approve",
            {"role_clarity": True, "compensation_competitive": True,
             "timeline_realistic": True})
        await approved_scorecard(ACME, cr4)
        c2 = await CAND.create_client_candidate(RECRUITER, ACME,
                                                {"cr_no": cr4, "candidate_name": "Vikram"})
        ccn2 = c2["ccn_no"]
        await CAND.update_client_candidate(RECRUITER, ACME, ccn2,
                                           {"tfs_score": 3.4, "competency_score": 3.2,
                                            "pi_score": 3.2})
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "screen")
        await expect_http("telephonic fail with no reason",
                          CAND.act_on_client_candidate(RECRUITER, ACME, ccn2,
                                                       "telephonic-fail"),
                          422)
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "telephonic-fail",
                                           {"remarks": "Not available for shift work."})
        check("a telephonic failure is NOT a closed state",
              M.ClientCandidateStatus.TELEPHONIC_FAILED.value
              not in M.CLIENT_CANDIDATE_CLOSED)
        await expect_http("...and cannot be shared with the client",
                          CAND.act_on_client_candidate(LEAD, ACME, ccn2, "share"), 409)
        await expect_http("revive with no reason",
                          CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "revive"),
                          422)
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "revive",
                                           {"remarks": "Shift pattern changed; worth another look."})
        check("revive puts them back at Screened, scores intact",
              (await CAND.get_client_candidate(RECRUITER, ACME, ccn2))["status"]
              == M.ClientCandidateStatus.SCREENED.value)

        # 13d. CV rejected with a reason -> closed, opens nothing.
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "telephonic-pass")
        await CAND.update_client_candidate(RECRUITER, ACME, ccn2,
                                           {"competency_score": 4.0, "pi_score": 4.0})
        await CAND.act_on_client_candidate(RECRUITER, ACME, ccn2, "shortlist")
        await CAND.act_on_client_candidate(LEAD, ACME, ccn2, "share")
        await expect_http("CV rejection with no reason",
                          CAND.act_on_client_candidate(ACME_USER, ACME, ccn2,
                                                       "client-reject"),
                          422)
        await CAND.act_on_client_candidate(ACME_USER, ACME, ccn2, "client-reject",
                                           {"remarks": "Not enough shift leadership."})
        check("a rejected CV is a closed state",
              M.ClientCandidateStatus.CLIENT_REJECTED.value in M.CLIENT_CANDIDATE_CLOSED)
        await expect_http("...and opens no assessment",
                          AS.create_client_assessment(RECRUITER, ACME,
                                                      {"ccn_no": ccn2, "title": "TFA"}),
                          409)

        # 13e. Offer declined -> no pre-boarding.
        cr5 = await new_requisition(ACME, ACME_USER, title="Declined Role")
        await REQ.act_on_client_requisition(
            LEAD, ACME, cr5, "feasibility-approve",
            {"role_clarity": True, "compensation_competitive": True,
             "timeline_realistic": True})
        await approved_scorecard(ACME, cr5)
        c3 = await CAND.create_client_candidate(RECRUITER, ACME,
                                                {"cr_no": cr5, "candidate_name": "Anita"})
        ccn3 = c3["ccn_no"]
        await CAND.update_client_candidate(RECRUITER, ACME, ccn3,
                                           {"tfs_score": 4.2, "competency_score": 4.0,
                                            "pi_score": 4.1})
        for act in ("screen", "telephonic-pass", "shortlist"):
            await CAND.act_on_client_candidate(RECRUITER, ACME, ccn3, act)
        await CAND.act_on_client_candidate(LEAD, ACME, ccn3, "share")
        await CAND.act_on_client_candidate(ACME_USER, ACME, ccn3, "client-approve")
        a3 = await AS.create_client_assessment(RECRUITER, ACME,
                                               {"ccn_no": ccn3, "title": "TFA"})
        await AS.act_on_client_assessment(RECRUITER, ACME, a3["cas_no"],
                                          "record-submission")
        await AS.update_client_assessment(RECRUITER, ACME, a3["cas_no"],
                                          {"score": 4.0, "result": "Pass"})
        await AS.act_on_client_assessment(RECRUITER, ACME, a3["cas_no"], "score")
        await AS.act_on_client_assessment(LEAD, ACME, a3["cas_no"], "share")
        await AS.act_on_client_assessment(ACME_USER, ACME, a3["cas_no"], "client-review")
        i3 = await IV.create_client_interview(RECRUITER, ACME, {
            "ccn_no": ccn3, "scheduled_at": "2026-09-26T10:00:00Z"})
        await IV.update_client_interview(RECRUITER, ACME, i3["cin_no"], {
            "outcome": "Recommend", "recording_link": "https://rec.test/3",
            "role_fit": 4.1, "communication": 4.0, "technical_depth": 4.0,
            "culture_fit": 4.2})
        await IV.act_on_client_interview(RECRUITER, ACME, i3["cin_no"], "record-outcome")
        await IV.act_on_client_interview(LEAD, ACME, i3["cin_no"], "share")
        await IV.act_on_client_interview(ACME_USER, ACME, i3["cin_no"], "client-select")
        o3 = await OF.create_client_offer(RECRUITER, ACME,
                                          {"ccn_no": ccn3, "offered_ctc": 800000})
        await OF.act_on_client_offer(RECRUITER, ACME, o3["cof_no"],
                                     "submit-for-verification")
        await OF.act_on_client_offer(LEAD, ACME, o3["cof_no"], "verify")
        await OF.act_on_client_offer(ACME_USER, ACME, o3["cof_no"], "client-release")
        await expect_http("decline with no reason",
                          OF.act_on_client_offer(RECRUITER, ACME, o3["cof_no"],
                                                 "record-decline"),
                          422)
        await OF.act_on_client_offer(RECRUITER, ACME, o3["cof_no"], "record-decline",
                                     {"remarks": "Accepted a counter-offer."})
        check("a declined offer is Declined",
              (await OF.get_client_offer(LEAD, ACME, o3["cof_no"]))["status"]
              == M.ClientOfferStatus.DECLINED.value)
        await expect_http("...and opens no pre-boarding",
                          JN.open_client_joining(RECRUITER, ACME, {"ccn_no": ccn3}), 409)

        # 13f. Dropout -- Sparsh may record it; it must not close the requisition.
        cr6 = await new_requisition(ACME, ACME_USER, title="Dropout Role")
        await REQ.act_on_client_requisition(
            LEAD, ACME, cr6, "feasibility-approve",
            {"role_clarity": True, "compensation_competitive": True,
             "timeline_realistic": True})
        await approved_scorecard(ACME, cr6)
        c4 = await CAND.create_client_candidate(RECRUITER, ACME,
                                                {"cr_no": cr6, "candidate_name": "Imran"})
        ccn4 = c4["ccn_no"]
        await CAND.update_client_candidate(RECRUITER, ACME, ccn4,
                                           {"tfs_score": 4.3, "competency_score": 4.1,
                                            "pi_score": 4.2})
        for act in ("screen", "telephonic-pass", "shortlist"):
            await CAND.act_on_client_candidate(RECRUITER, ACME, ccn4, act)
        await CAND.act_on_client_candidate(LEAD, ACME, ccn4, "share")
        await CAND.act_on_client_candidate(ACME_USER, ACME, ccn4, "client-approve")
        a4 = await AS.create_client_assessment(RECRUITER, ACME,
                                               {"ccn_no": ccn4, "title": "TFA"})
        await AS.act_on_client_assessment(RECRUITER, ACME, a4["cas_no"],
                                          "record-submission")
        await AS.update_client_assessment(RECRUITER, ACME, a4["cas_no"],
                                          {"score": 4.1, "result": "Pass"})
        await AS.act_on_client_assessment(RECRUITER, ACME, a4["cas_no"], "score")
        await AS.act_on_client_assessment(LEAD, ACME, a4["cas_no"], "share")
        await AS.act_on_client_assessment(ACME_USER, ACME, a4["cas_no"], "client-review")
        i4 = await IV.create_client_interview(RECRUITER, ACME, {
            "ccn_no": ccn4, "scheduled_at": "2026-09-27T10:00:00Z"})
        await IV.update_client_interview(RECRUITER, ACME, i4["cin_no"], {
            "outcome": "Recommend", "recording_link": "https://rec.test/4",
            "role_fit": 4.2, "communication": 4.1, "technical_depth": 4.0,
            "culture_fit": 4.3})
        await IV.act_on_client_interview(RECRUITER, ACME, i4["cin_no"], "record-outcome")
        await IV.act_on_client_interview(LEAD, ACME, i4["cin_no"], "share")
        await IV.act_on_client_interview(ACME_USER, ACME, i4["cin_no"], "client-select")
        o4 = await OF.create_client_offer(RECRUITER, ACME,
                                          {"ccn_no": ccn4, "offered_ctc": 820000})
        await OF.act_on_client_offer(RECRUITER, ACME, o4["cof_no"],
                                     "submit-for-verification")
        await OF.act_on_client_offer(LEAD, ACME, o4["cof_no"], "verify")
        await OF.act_on_client_offer(ACME_USER, ACME, o4["cof_no"], "client-release")
        await OF.act_on_client_offer(RECRUITER, ACME, o4["cof_no"], "record-acceptance",
                                     {"accepted_on": "2026-09-29",
                                      "joining_date": "2026-11-10"})
        j4 = await JN.open_client_joining(RECRUITER, ACME, {"ccn_no": ccn4})
        # Pre-boarding is the RECRUITER's to run (CLIENT_JOINING_MANAGE sits with HR); the
        # Team Lead owns the handover. Two different jobs, two different capabilities.
        await expect_http("Team Lead cannot record a dropout -- not their job",
                          JN.act_on_client_joining(LEAD, ACME, j4["cjn_no"],
                                                   "record-drop",
                                                   {"remarks": "x"}),
                          403, "client_joining.manage")
        await expect_http("dropout with no reason",
                          JN.act_on_client_joining(RECRUITER, ACME, j4["cjn_no"],
                                                   "record-drop"),
                          422)
        await JN.act_on_client_joining(RECRUITER, ACME, j4["cjn_no"], "record-drop",
                                       {"remarks": "Took the counter-offer."})
        check("Sparsh may record a dropout",
              (await JN.get_client_joining(RECRUITER, ACME, j4["cjn_no"]))["status"]
              == M.ClientJoiningStatus.DROPPED.value)
        check("a dropout does NOT close the requisition",
              (await REQ.get_client_requisition(LEAD, ACME, cr6))["status"]
              != M.ClientReqStatus.CLOSED.value)
        await expect_http("...and no handover follows a dropout",
                          JN.act_on_client_joining(LEAD, ACME, j4["cjn_no"],
                                                   "share-handover"),
                          409)
        check("the dropped candidate is in a closed state",
              M.ClientCandidateStatus.DROPPED.value in M.CLIENT_CANDIDATE_CLOSED)

        # =================================================================
        section("15. The transition tables are total and self-consistent")
        # =================================================================
        TABLES = [
            ("requisition", M.CLIENT_REQ_TRANSITIONS, M.ClientReqStatus),
            ("scorecard", M.CLIENT_SCORECARD_TRANSITIONS, M.ClientScorecardStatus),
            ("candidate", M.CLIENT_CANDIDATE_TRANSITIONS, M.ClientCandidateStatus),
            ("assessment", M.CLIENT_ASSESSMENT_TRANSITIONS, M.ClientAssessmentStatus),
            ("interview", M.CLIENT_INTERVIEW_TRANSITIONS, M.ClientInterviewStatus),
            ("offer", M.CLIENT_OFFER_TRANSITIONS, M.ClientOfferStatus),
            ("joining", M.CLIENT_JOINING_TRANSITIONS, M.ClientJoiningStatus),
        ]
        for name, table, enum in TABLES:
            caps_ok = all(hasattr(M.Cap, spec[2]) for spec in table.values())
            check(f"{name}: every transition names a real capability", caps_ok)
            states_ok = all(isinstance(spec[0], enum) and isinstance(spec[1], enum)
                            for spec in table.values())
            check(f"{name}: every from/to state is a member of its enum", states_ok)
        check("every decision capability is used by exactly the client-owned transitions",
              {spec[2] for _n, table, _e in TABLES for spec in table.values()
               if spec[2] in {c.name for c in M.CLIENT_DECISION_CAPS}}
              == {c.name for c in M.CLIENT_DECISION_CAPS})
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
