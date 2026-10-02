"""Client Hiring step 6 -- interview, recording, client selection.

PRO-fit SOP sections 12, 14 and 16.

Four properties this file pins:

  1. THE ASSESSMENT REVIEW IS THE GATE IN. An interview cannot be scheduled for somebody
     whose result the client has not read.
  2. NOTHING IS SHARED WITHOUT SOMETHING TO WATCH. Section 14 delivers a recorded
     interview and its scores, so a share with no recording link or no scores is refused.
  3. THE SELECTION IS THE CLIENT'S, and no Sparsh role can make it.
  4. THE PANEL'S PRIVATE NOTES STAY AT SPARSH, even though everything else about the
     interview goes to the client, who is being asked to decide on it.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_interview   (from backend/)
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
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

ACME, GLOBEX, SPARSH = "client-acme", "client-globex", "sparsh-magic"
SCORES = {"role_fit": 4.5, "communication": 4.0,
          "technical_depth": 4.0, "culture_fit": 4.5}


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)

    def cand(ccn, company, name, status):
        return {"ccn_no": ccn, "company_id": company, "cr_no": "CR-2026-001",
                "psc_no": "PSC-2026-001", "candidate_name": name,
                "status": status, "created_at": NOW}

    def assess(cas, ccn, company, status):
        return {"cas_no": cas, "ccn_no": ccn, "company_id": company,
                "candidate_name": "x", "status": status, "created_at": NOW}

    candidates = FakeCollection([
        cand("CCN-2026-001", ACME, "Nita Reviewed",
             M.ClientCandidateStatus.ASSESSMENT_REVIEWED.value),
        cand("CCN-2026-002", ACME, "Dev Midway",
             M.ClientCandidateStatus.ASSESSMENT.value),
        cand("CCN-2026-001", GLOBEX, "Globex Person",
             M.ClientCandidateStatus.ASSESSMENT_REVIEWED.value),
    ])
    assessments = FakeCollection([
        assess("CAS-2026-001", "CCN-2026-001", ACME,
               M.ClientAssessmentStatus.REVIEWED.value),
        assess("CAS-2026-002", "CCN-2026-002", ACME,
               M.ClientAssessmentStatus.SCORED.value),
        assess("CAS-2026-001", "CCN-2026-001", GLOBEX,
               M.ClientAssessmentStatus.REVIEWED.value),
    ])
    store = {M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_CLIENT_ASSESSMENTS: assessments,
             M.COLL_CLIENT_INTERVIEWS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_interview_service as IV
    import app.services.hrms_client_assessment_service as AS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (IV, AS, AUD, IDS, HA):
        mod.get_collection = mongo.get_collection

    def client(company, name="Client Person"):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company,
                "full_name": name, M.CLIENT_TRACK_FLAG: True}

    def sparsh(governance, name="Sparsh Person"):
        return {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff",
                "company_id": SPARSH, "governance_role": governance, "full_name": name}

    ACME_CLIENT = client(ACME, "Acme Talent Lead")
    RECRUITER = sparsh("HR", "Sparsh Recruiter")
    TEAM_LEAD = sparsh("HOD", "Sparsh Team Lead")
    OPS_HEAD = sparsh("MD", "Sparsh Ops Head")

    try:
        # =================================================================
        section("Who may do what")
        # =================================================================
        check("the recruiter schedules and conducts",
              HA.can(RECRUITER, M.Cap.CLIENT_INTERVIEW_MANAGE))
        check("...but does not deliver the recording",
              not HA.can(RECRUITER, M.Cap.CLIENT_INTERVIEW_SHARE))
        check("the Team Lead delivers",
              HA.can(TEAM_LEAD, M.Cap.CLIENT_INTERVIEW_SHARE))
        check("the client selects",
              HA.can(ACME_CLIENT, M.Cap.CLIENT_INTERVIEW_DECIDE))
        check("...and cannot schedule or score",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_INTERVIEW_MANAGE))
        check("NO Sparsh role can make the selection",
              not any(M.Cap.CLIENT_INTERVIEW_DECIDE in caps
                      for caps in M.ROLE_CAPABILITIES.values()))

        # =================================================================
        section("The assessment review is the gate in")
        # =================================================================
        await expect_http(
            "scheduling for somebody whose result the client has not read",
            IV.create_client_interview(RECRUITER, ACME,
                                       {"ccn_no": "CCN-2026-002",
                                        "scheduled_at": "2026-10-01T10:00:00Z"}),
            409, "reviewed the")
        await expect_http(
            "scheduling with no date",
            IV.create_client_interview(RECRUITER, ACME, {"ccn_no": "CCN-2026-001"}),
            422, "when the interview is")

        made = await IV.create_client_interview(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-001",
                              "scheduled_at": "2026-10-01T10:00:00Z",
                              "mode": "Virtual",
                              "meeting_link": "https://zoom.example/abc",
                              "panel": ["Sparsh Recruiter", "Sparsh Team Lead"]})
        CIN = made["cin_no"]
        check("scheduled", made["status"] == M.ClientInterviewStatus.SCHEDULED.value)
        check("the panel is recorded", made["panel"] == ["Sparsh Recruiter",
                                                         "Sparsh Team Lead"])
        moved = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                           "company_id": ACME})
        check("and the candidate moves to Interview",
              moved["status"] == M.ClientCandidateStatus.INTERVIEW.value)
        await expect_http(
            "a second live interview for the same candidate",
            IV.create_client_interview(RECRUITER, ACME,
                                       {"ccn_no": "CCN-2026-001",
                                        "scheduled_at": "2026-10-02T10:00:00Z"}),
            409, "already has an interview")

        # =================================================================
        section("Conducting it")
        # =================================================================
        await expect_http(
            "marking it conducted with no panel outcome",
            IV.act_on_client_interview(RECRUITER, ACME, CIN, "record-outcome", {}),
            422, "panel's outcome")
        await expect_http(
            "a rating outside the scale",
            IV.update_client_interview(RECRUITER, ACME, CIN, {"role_fit": 7}),
            422, "0 to 5")
        await expect_http(
            "an outcome that is neither recommendation",
            IV.update_client_interview(RECRUITER, ACME, CIN, {"outcome": "maybe"}),
            422, "recommend")

        await IV.update_client_interview(
            RECRUITER, ACME, CIN,
            {**SCORES, "outcome": "recommend",
             "panel_notes": "Internal: asked twice about remote working."})
        row = await IV.get_client_interview(RECRUITER, ACME, CIN)
        check("the average is derived from the four criteria",
              row["average_score"] == 4.25)
        await IV.act_on_client_interview(RECRUITER, ACME, CIN, "record-outcome", {})
        row = await IV.get_client_interview(RECRUITER, ACME, CIN)
        check("it is marked conducted",
              row["status"] == M.ClientInterviewStatus.CONDUCTED.value
              and row["conducted_at"] is not None)

        # =================================================================
        section("Nothing is shared without something to watch")
        # =================================================================
        await expect_http(
            "sharing with no recording link",
            IV.act_on_client_interview(TEAM_LEAD, ACME, CIN, "share", {}),
            422, "recording link")
        await expect_http(
            "the recruiter delivering their own recording",
            IV.act_on_client_interview(RECRUITER, ACME, CIN, "share", {}),
            403, "client_interview.share")

        await IV.update_client_interview(
            RECRUITER, ACME, CIN,
            {"recording_link": "https://zoom.example/rec/abc"})
        await expect_http(
            "the client opening an interview not yet shared",
            IV.get_client_interview(ACME_CLIENT, ACME, CIN), 404, "not found")

        await IV.act_on_client_interview(TEAM_LEAD, ACME, CIN, "share", {})
        shared = await IV.get_client_interview(ACME_CLIENT, ACME, CIN)
        check("the client gets the recording and the scores",
              shared["recording_link"].endswith("/rec/abc")
              and shared["average_score"] == 4.25
              and shared["outcome"] == "Recommend")
        check("but NOT the panel's private notes", "panel_notes" not in shared)
        check("nor who scheduled it internally", "scheduled_by_name" not in shared)
        full = await IV.get_client_interview(RECRUITER, ACME, CIN)
        check("Sparsh still sees the whole record",
              full.get("panel_notes") is not None)
        await expect_http(
            "amending an interview the client is deciding on",
            IV.update_client_interview(RECRUITER, ACME, CIN, {"role_fit": 1}),
            409, "with the client")

        # =================================================================
        section("The selection is the client's")
        # =================================================================
        await expect_http(
            "the offer stage before any selection",
            IV.assert_offer_stage_allowed(ACME, "CCN-2026-001"), 409, "section 16")
        await expect_http(
            "the Operations Head selecting on the client's behalf",
            IV.act_on_client_interview(OPS_HEAD, ACME, CIN, "client-select", {}),
            403, "client_interview.decide")

        picked = await IV.act_on_client_interview(
            ACME_CLIENT, ACME, CIN, "client-select", {"remarks": "Strong fit."})
        check("the client selects them",
              picked["status"] == M.ClientInterviewStatus.CLIENT_SELECTED.value)
        check("and it is attributed to them",
              picked["client_decision"]["by_name"] == "Acme Talent Lead")
        after = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                           "company_id": ACME})
        check("the candidate is Selected",
              after["status"] == M.ClientCandidateStatus.SELECTED.value)
        opened = await IV.assert_offer_stage_allowed(ACME, "CCN-2026-001")
        check("the offer stage is now open", opened["ccn_no"] == "CCN-2026-001")

        # =================================================================
        section("A rejection after the interview ends the run")
        # =================================================================
        await candidates.insert_one(cand("CCN-2026-004", ACME, "Sam Passedover",
                                          M.ClientCandidateStatus.ASSESSMENT_REVIEWED.value))
        await assessments.insert_one(assess("CAS-2026-004", "CCN-2026-004", ACME,
                                             M.ClientAssessmentStatus.REVIEWED.value))
        two = await IV.create_client_interview(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-004",
                              "scheduled_at": "2026-10-03T10:00:00Z"})
        await IV.update_client_interview(
            RECRUITER, ACME, two["cin_no"],
            {**SCORES, "outcome": "Do Not Recommend",
             "recording_link": "https://zoom.example/rec/two"})
        await IV.act_on_client_interview(RECRUITER, ACME, two["cin_no"],
                                         "record-outcome", {})
        await IV.act_on_client_interview(TEAM_LEAD, ACME, two["cin_no"], "share", {})
        await expect_http(
            "rejecting after a full interview with no reason",
            IV.act_on_client_interview(ACME_CLIENT, ACME, two["cin_no"],
                                       "client-reject", {}),
            422, "owed one")
        turned = await IV.act_on_client_interview(
            ACME_CLIENT, ACME, two["cin_no"], "client-reject",
            {"remarks": "Went with the other candidate."})
        check("the client rejects them",
              turned["status"] == M.ClientInterviewStatus.CLIENT_REJECTED.value)
        rej = await candidates.find_one({"ccn_no": "CCN-2026-004",
                                          "company_id": ACME})
        check("and the candidate is Client Rejected",
              rej["status"] == M.ClientCandidateStatus.CLIENT_REJECTED.value)
        await expect_http(
            "...so the offer stage stays shut",
            IV.assert_offer_stage_allowed(ACME, "CCN-2026-004"), 409, "section 16")

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        elsewhere = await IV.create_client_interview(
            RECRUITER, GLOBEX, {"ccn_no": "CCN-2026-001",
                                "scheduled_at": "2026-10-05T10:00:00Z"})
        same_number = await IV.get_client_interview(RECRUITER, ACME, elsewhere["cin_no"])
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)
        await expect_http(
            "a number that exists in no tenant of theirs",
            IV.get_client_interview(ACME_CLIENT, ACME, "CIN-2026-999"),
            404, "not found")
        mine = await IV.list_client_interviews(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_interviews"]))
        await expect_http(
            "a client-side caller with no company in scope",
            IV.list_client_interviews(ACME_CLIENT, None), 403, "no company in scope")

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection",
              M.COLL_CLIENT_INTERVIEWS != M.COLL_INTERVIEWS)
        check("every action names a client-interview capability",
              all(spec[2].startswith("CLIENT_INTERVIEW_")
                  for spec in M.CLIENT_INTERVIEW_TRANSITIONS.values()))
        check("the ceiling still holds nothing outside Client Hiring",
              all(c.value.startswith("client_") or c is M.Cap.MODULE_ACCESS
                  for c in M.CLIENT_TRACK_CAPS))
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 66}\n  {passed}/{total} checks passed\n{'=' * 66}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
