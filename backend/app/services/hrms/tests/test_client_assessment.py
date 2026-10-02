"""Client Hiring step 5 -- the assessment.

PRO-fit SOP section 12 and the assessment-stage responsibility table.

Four properties this file pins:

  1. THE CLIENT'S CV APPROVAL IS WHAT OPENS THIS STAGE. Issuing an assessment to anybody
     the client has not approved is refused.
  2. ADMINISTERING AND MARKING ARE DIFFERENT JOBS. The SOP separates them, so somebody
     who can run an assessment but not mark it is refused when they try to record a score.
  3. THE CLIENT READS A RESULT, NOT A WORKING PAPER. The evaluator's notes never leave
     Sparsh, and nothing is visible until it is shared.
  4. THE INTERVIEW OPENS ON THE CLIENT'S REVIEW, and not on Sparsh deciding it is time.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_assessment   (from backend/)
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

    candidates = FakeCollection([
        cand("CCN-2026-001", ACME, "Nita Approved",
             M.ClientCandidateStatus.CLIENT_APPROVED.value),
        cand("CCN-2026-002", ACME, "Dev Shared",
             M.ClientCandidateStatus.SHARED_WITH_CLIENT.value),
        cand("CCN-2026-003", ACME, "Raj Rejected",
             M.ClientCandidateStatus.CLIENT_REJECTED.value),
        cand("CCN-2026-001", GLOBEX, "Globex Person",
             M.ClientCandidateStatus.CLIENT_APPROVED.value),
    ])
    store = {M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_CLIENT_ASSESSMENTS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_assessment_service as AS
    import app.services.hrms_client_candidate_service as CC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (AS, CC, AUD, IDS, HA):
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
    SUPPORT = sparsh(None, "Sparsh Support")

    try:
        # =================================================================
        section("Who may do what")
        # =================================================================
        check("the recruiter administers", HA.can(RECRUITER, M.Cap.CLIENT_ASSESSMENT_MANAGE))
        check("and may also mark", HA.can(RECRUITER, M.Cap.CLIENT_ASSESSMENT_SCORE))
        check("...but does not deliver the result",
              not HA.can(RECRUITER, M.Cap.CLIENT_ASSESSMENT_SHARE))
        check("the Team Lead delivers", HA.can(TEAM_LEAD, M.Cap.CLIENT_ASSESSMENT_SHARE))
        check("...and does not administer",
              not HA.can(TEAM_LEAD, M.Cap.CLIENT_ASSESSMENT_MANAGE))
        check("support staff read only",
              HA.can(SUPPORT, M.Cap.CLIENT_ASSESSMENT_READ)
              and not HA.can(SUPPORT, M.Cap.CLIENT_ASSESSMENT_SCORE))
        check("the client reviews", HA.can(ACME_CLIENT, M.Cap.CLIENT_ASSESSMENT_REVIEW))
        check("...and neither administers nor marks",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_ASSESSMENT_MANAGE)
              and not HA.can(ACME_CLIENT, M.Cap.CLIENT_ASSESSMENT_SCORE))
        check("NO Sparsh role can record the client's review",
              not any(M.Cap.CLIENT_ASSESSMENT_REVIEW in caps
                      for caps in M.ROLE_CAPABILITIES.values()))

        # =================================================================
        section("The client's CV approval is the gate in")
        # =================================================================
        await expect_http(
            "issuing to a candidate the client has not decided on",
            AS.create_client_assessment(RECRUITER, ACME,
                                        {"ccn_no": "CCN-2026-002", "title": "Too early"}),
            409, "approves the cv")
        await expect_http(
            "issuing to a candidate the client rejected",
            AS.create_client_assessment(RECRUITER, ACME,
                                        {"ccn_no": "CCN-2026-003", "title": "No"}),
            409, "approves the cv")
        await expect_http(
            "issuing with no title",
            AS.create_client_assessment(RECRUITER, ACME, {"ccn_no": "CCN-2026-001"}),
            422, "name the assessment")

        made = await AS.create_client_assessment(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-001",
                              "title": "Talent Fit Assessment",
                              "instructions": "Ninety minutes, open book.",
                              "max_score": 5})
        CAS = made["cas_no"]
        check("issued to an approved candidate",
              made["status"] == M.ClientAssessmentStatus.SENT.value)
        moved = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                           "company_id": ACME})
        check("and the candidate moves to Assessment",
              moved["status"] == M.ClientCandidateStatus.ASSESSMENT.value)
        await expect_http(
            "a second assessment for the same candidate",
            AS.create_client_assessment(RECRUITER, ACME,
                                        {"ccn_no": "CCN-2026-001", "title": "Again"}),
            409, "already has an assessment")

        # =================================================================
        section("Administering is not marking")
        # =================================================================
        await AS.act_on_client_assessment(RECRUITER, ACME, CAS, "record-submission", {})
        row = await AS.get_client_assessment(RECRUITER, ACME, CAS)
        check("the submission is recorded",
              row["status"] == M.ClientAssessmentStatus.SUBMITTED.value
              and row["submitted_at"] is not None)

        await expect_http(
            "support staff recording a score",
            AS.update_client_assessment(SUPPORT, ACME, CAS, {"score": 4}),
            403, "client_assessment.score")
        await expect_http(
            "the client recording a score",
            AS.update_client_assessment(ACME_CLIENT, ACME, CAS, {"score": 5}),
            404, "not found")
        await expect_http(
            "a score above the maximum",
            AS.update_client_assessment(RECRUITER, ACME, CAS, {"score": 9}),
            422, "between 0 and 5")
        await expect_http(
            "marking it scored before a figure exists",
            AS.act_on_client_assessment(RECRUITER, ACME, CAS, "score", {}),
            422, "record the score")

        await AS.update_client_assessment(RECRUITER, ACME, CAS,
                                          {"score": 4.2, "result": "pass",
                                           "evaluator_notes": "Weak on error handling."})
        row = await AS.get_client_assessment(RECRUITER, ACME, CAS)
        check("the score and verdict are recorded",
              row["score"] == 4.2 and row["result"] == "Pass")
        check("and attributed to whoever marked it",
              row["scored_by_name"] == "Sparsh Recruiter")
        await expect_http(
            "a result that is neither Pass nor Fail",
            AS.update_client_assessment(RECRUITER, ACME, CAS, {"result": "maybe"}),
            422, "pass or fail")

        await AS.act_on_client_assessment(RECRUITER, ACME, CAS, "score", {})
        row = await AS.get_client_assessment(RECRUITER, ACME, CAS)
        check("it is marked scored",
              row["status"] == M.ClientAssessmentStatus.SCORED.value)

        # =================================================================
        section("The client reads a result, not a working paper")
        # =================================================================
        await expect_http(
            "the client opening a result not yet shared",
            AS.get_client_assessment(ACME_CLIENT, ACME, CAS), 404, "not found")
        theirs = await AS.list_client_assessments(ACME_CLIENT, ACME)
        check("...and their list is empty", theirs["total"] == 0)
        await expect_http(
            "the recruiter delivering their own result",
            AS.act_on_client_assessment(RECRUITER, ACME, CAS, "share", {}),
            403, "client_assessment.share")

        await AS.act_on_client_assessment(TEAM_LEAD, ACME, CAS, "share", {})
        shared = await AS.get_client_assessment(ACME_CLIENT, ACME, CAS)
        check("once delivered, the client sees the result",
              shared["score"] == 4.2 and shared["result"] == "Pass")
        check("but NOT the evaluator's notes", "evaluator_notes" not in shared)
        check("nor who issued it internally", "issued_by_name" not in shared)
        full = await AS.get_client_assessment(RECRUITER, ACME, CAS)
        check("Sparsh still sees the whole record",
              full.get("evaluator_notes") is not None)
        await expect_http(
            "amending a result the client is reading",
            AS.update_client_assessment(RECRUITER, ACME, CAS, {"score": 1}),
            409, "with the client")

        # =================================================================
        section("The interview opens on the client's review")
        # =================================================================
        await expect_http(
            "interviewing before the client has read the result",
            AS.assert_interview_allowed(ACME, "CCN-2026-001"), 409, "reviewed the")
        await expect_http(
            "the Team Lead reviewing on the client's behalf",
            AS.act_on_client_assessment(TEAM_LEAD, ACME, CAS, "client-review", {}),
            403, "client_assessment.review")

        reviewed = await AS.act_on_client_assessment(
            ACME_CLIENT, ACME, CAS, "client-review",
            {"remarks": "Happy to proceed to interview."})
        check("the client reviews it",
              reviewed["status"] == M.ClientAssessmentStatus.REVIEWED.value)
        check("and it is attributed to them",
              reviewed["client_review"]["by_name"] == "Acme Talent Lead")
        opened = await AS.assert_interview_allowed(ACME, "CCN-2026-001")
        check("the interview stage is now open", opened["cas_no"] == CAS)
        after = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                           "company_id": ACME})
        check("and the candidate moves to Assessment Reviewed",
              after["status"] == M.ClientCandidateStatus.ASSESSMENT_REVIEWED.value)
        check("a client still sees a candidate at that stage",
              M.ClientCandidateStatus.ASSESSMENT_REVIEWED.value
              in M.CLIENT_CANDIDATE_VISIBLE_TO_CLIENT)

        await expect_http(
            "interviewing somebody with no assessment at all",
            AS.assert_interview_allowed(ACME, "CCN-2026-002"), 409, "no assessment")

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        elsewhere = await AS.create_client_assessment(
            RECRUITER, GLOBEX, {"ccn_no": "CCN-2026-001", "title": "Globex test"})
        # Numbers are per company on purpose, so both tenants start at the same one and
        # asking for it resolves to YOUR row. That is the isolation working.
        same_number = await AS.get_client_assessment(ACME_CLIENT, ACME,
                                                     elsewhere["cas_no"])
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)
        await expect_http(
            "a number that exists in no tenant of theirs",
            AS.get_client_assessment(ACME_CLIENT, ACME, "CAS-2026-999"),
            404, "not found")
        mine = await AS.list_client_assessments(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_assessments"]))
        await expect_http(
            "a client-side caller with no company in scope",
            AS.list_client_assessments(ACME_CLIENT, None), 403, "no company in scope")
        check("naming another company in the query is ignored",
              HA.scope_company_id(ACME_CLIENT, GLOBEX) == ACME)

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection",
              M.COLL_CLIENT_ASSESSMENTS != M.COLL_ASSESSMENTS)
        # "share" appears on both the candidate and the assessment table -- same English
        # word, different documents. What must not be shared is the MACHINERY, so the test
        # is that each action resolves to an assessment capability rather than borrowing
        # one from the candidate stage.
        check("every assessment action names an assessment capability",
              all(spec[2].startswith("CLIENT_ASSESSMENT_")
                  for spec in M.CLIENT_ASSESSMENT_TRANSITIONS.values()))
        check("and none of them reaches into Internal Hiring",
              set(M.CLIENT_ASSESSMENT_TRANSITIONS)
              & set(M.INTERNAL_REQ_TRANSITIONS) == set())
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
