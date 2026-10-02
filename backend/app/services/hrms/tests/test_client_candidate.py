"""Client Hiring steps 3-4 -- sourcing, screening, the CV share, the client's verdict.

PRO-fit SOP sections 6, 10, 11, 13 and 14.

Four properties this file pins:

  1. NO SOURCING WITHOUT AN AGREED BENCHMARK. Section 6. Every score below is a
     measurement against the Position Scorecard, so sourcing before one is approved
     produces numbers that mean nothing.
  2. THE SCORE THRESHOLD IS ENFORCED, NOT PRINTED. Section 13 says no candidate is
     shortlisted on recommendation alone without meeting it, so a candidate below it
     cannot be shortlisted however strongly somebody feels.
  3. THE CLIENT'S CV VERDICT IS THE GATE INTO ASSESSMENT, and no Sparsh role can give it.
  4. A CLIENT SEES A SHARED CANDIDATE, AND ONLY WHAT SECTION 14 SHARES. Not the ones still
     being screened, and not the recruiter's own notes about the ones they can see.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_candidate   (from backend/)
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
    scorecards = FakeCollection([
        {"psc_no": "PSC-2026-001", "company_id": ACME, "cr_no": "CR-2026-001",
         "status": M.ClientScorecardStatus.APPROVED.value, "created_at": NOW},
        # Drafted but never agreed -- section 6 must refuse sourcing against it.
        {"psc_no": "PSC-2026-002", "company_id": ACME, "cr_no": "CR-2026-002",
         "status": M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value,
         "created_at": NOW},
        {"psc_no": "PSC-2026-001", "company_id": GLOBEX, "cr_no": "CR-2026-001",
         "status": M.ClientScorecardStatus.APPROVED.value, "created_at": NOW},
    ])
    store = {M.COLL_CLIENT_SCORECARDS: scorecards,
             M.COLL_CLIENT_CANDIDATES: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_candidate_service as CC
    import app.services.hrms_client_scorecard_service as SC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (CC, SC, AUD, IDS, HA):
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

    async def add(name, company=ACME, cr="CR-2026-001"):
        return await CC.create_client_candidate(
            RECRUITER, company, {"cr_no": cr, "candidate_name": name,
                                 "email": f"{name.split()[0].lower()}@example.com",
                                 "phone": "+91 90000 00000", "source": "LinkedIn"})

    async def carry(ccn, tfs, comp, pi, company=ACME):
        await CC.update_client_candidate(RECRUITER, company, ccn, {
            "tfs_score": tfs, "competency_score": comp, "pi_score": pi,
            "screening_notes": "Internal note: pushy about title."})
        await CC.act_on_client_candidate(RECRUITER, company, ccn, "screen", {})
        await CC.act_on_client_candidate(RECRUITER, company, ccn, "telephonic-pass", {})

    try:
        # =================================================================
        section("Who may do what")
        # =================================================================
        check("the recruiter sources and screens",
              HA.can(RECRUITER, M.Cap.CLIENT_CANDIDATE_WRITE))
        check("...but does not deliver the shortlist",
              not HA.can(RECRUITER, M.Cap.CLIENT_CANDIDATE_SHARE))
        check("the Team Lead delivers it",
              HA.can(TEAM_LEAD, M.Cap.CLIENT_CANDIDATE_SHARE))
        check("...but does not source",
              not HA.can(TEAM_LEAD, M.Cap.CLIENT_CANDIDATE_WRITE))
        check("the client decides on a CV",
              HA.can(ACME_CLIENT, M.Cap.CLIENT_CANDIDATE_DECIDE))
        check("...and can neither source nor share",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_CANDIDATE_WRITE)
              and not HA.can(ACME_CLIENT, M.Cap.CLIENT_CANDIDATE_SHARE))
        check("NO Sparsh role can give the client's CV verdict",
              not any(M.Cap.CLIENT_CANDIDATE_DECIDE in caps
                      for caps in M.ROLE_CAPABILITIES.values()))

        # =================================================================
        section("Section 6 -- no sourcing without an agreed benchmark")
        # =================================================================
        await expect_http(
            "sourcing against a scorecard the client has not approved",
            CC.create_client_candidate(RECRUITER, ACME,
                                       {"cr_no": "CR-2026-002",
                                        "candidate_name": "Too Early"}),
            409, "section 6")
        await expect_http(
            "sourcing against a role with no scorecard at all",
            CC.create_client_candidate(RECRUITER, ACME,
                                       {"cr_no": "CR-9999-999",
                                        "candidate_name": "Nowhere"}),
            409, "section 6")

        strong = await add("Asha Strong")
        check("a candidate is sourced against the approved role",
              strong["status"] == M.ClientCandidateStatus.SOURCED.value)
        check("and stamped with the benchmark they will be measured against",
              strong["psc_no"] == "PSC-2026-001")

        # =================================================================
        section("Screening is a measurement (section 11)")
        # =================================================================
        await expect_http(
            "a telephonic pass out of order, before any screen",
            CC.act_on_client_candidate(RECRUITER, ACME, strong["ccn_no"],
                                       "telephonic-pass", {}),
            409, "does not apply")
        # THE SCORE IS WHAT MAKES IT A SCREEN. This used to be demanded one step later, at
        # telephonic-pass, which let a candidate sit in "Screened" -- a status asserting a
        # measurement happened -- with nothing measured. Section 11 screens a CV by
        # validating it against the Position Scorecard, so the validation comes first.
        await expect_http(
            "screening before a Talent Fit Score exists",
            CC.act_on_client_candidate(RECRUITER, ACME, strong["ccn_no"], "screen", {}),
            422, "talent fit score")

        await CC.update_client_candidate(RECRUITER, ACME, strong["ccn_no"],
                                         {"tfs_score": 4.5, "competency_score": 4.0})
        await CC.act_on_client_candidate(RECRUITER, ACME, strong["ccn_no"], "screen", {})
        check("with the score recorded, the screen goes through",
              (await CC.get_client_candidate(
                  RECRUITER, ACME, strong["ccn_no"]))["status"]
              == M.ClientCandidateStatus.SCREENED.value)
        row = await CC.get_client_candidate(RECRUITER, ACME, strong["ccn_no"])
        check("the average and its band are derived, not typed",
              row["average_score"] == 4.25
              and row["score_band"]["may_shortlist"] is True)
        await expect_http(
            "a score outside the five-point scale",
            CC.update_client_candidate(RECRUITER, ACME, strong["ccn_no"],
                                       {"pi_score": 9}),
            422, "0 to 5")

        # =================================================================
        section("Section 13 -- the threshold is enforced")
        # =================================================================
        weak = await add("Ravi Marginal")
        await carry(weak["ccn_no"], 3.0, 3.0, 3.0)
        await expect_http(
            "shortlisting somebody below the threshold",
            CC.act_on_client_candidate(RECRUITER, ACME, weak["ccn_no"], "shortlist", {}),
            409, "threshold")

        await CC.act_on_client_candidate(RECRUITER, ACME, strong["ccn_no"],
                                         "telephonic-pass", {})
        await expect_http(
            "shortlisting before the Preliminary Interview Score",
            CC.act_on_client_candidate(RECRUITER, ACME, strong["ccn_no"],
                                       "shortlist", {}),
            422, "preliminary interview score")

        good = await add("Nita Solid")
        await carry(good["ccn_no"], 4.4, 4.2, 4.0)
        await CC.act_on_client_candidate(RECRUITER, ACME, good["ccn_no"], "shortlist", {})
        row = await CC.get_client_candidate(RECRUITER, ACME, good["ccn_no"])
        check("a candidate above the threshold is shortlisted",
              row["status"] == M.ClientCandidateStatus.SHORTLISTED.value)

        # =================================================================
        section("Delivery is the Team Lead's, and the client sees nothing before it")
        # =================================================================
        await expect_http(
            "the client opening a candidate still being screened",
            CC.get_client_candidate(ACME_CLIENT, ACME, good["ccn_no"]), 404, "not found")
        theirs = await CC.list_client_candidates(ACME_CLIENT, ACME)
        check("...and their list is empty", theirs["total"] == 0)
        await expect_http(
            "the recruiter delivering their own shortlist",
            CC.act_on_client_candidate(RECRUITER, ACME, good["ccn_no"], "share", {}),
            403, "client_candidate.share")

        await CC.act_on_client_candidate(TEAM_LEAD, ACME, good["ccn_no"], "share", {})
        shared = await CC.get_client_candidate(ACME_CLIENT, ACME, good["ccn_no"])
        check("once delivered, the client can see them",
              shared["ccn_no"] == good["ccn_no"])
        check("they get the scores section 14 promises",
              shared["tfs_score"] == 4.4 and shared["pi_score"] == 4.0
              and shared["average_score"] is not None)
        check("but NOT the recruiter's internal notes",
              "screening_notes" not in shared)
        check("nor who inside Sparsh sourced them",
              "sourced_by" not in shared and "sourced_by_name" not in shared)
        full = await CC.get_client_candidate(RECRUITER, ACME, good["ccn_no"])
        check("Sparsh still sees the whole record",
              full.get("screening_notes") is not None)

        await expect_http(
            "amending a CV the client is reading",
            CC.update_client_candidate(RECRUITER, ACME, good["ccn_no"],
                                       {"expected_ctc": 100}),
            409, "with the client")

        # =================================================================
        section("The client's verdict is the gate into assessment")
        # =================================================================
        await expect_http(
            "assessment before the client has decided",
            CC.assert_assessment_allowed(ACME, good["ccn_no"]), 409, "approves the cv")
        await expect_http(
            "the Team Lead approving the CV on the client's behalf",
            CC.act_on_client_candidate(TEAM_LEAD, ACME, good["ccn_no"],
                                       "client-approve", {}),
            403, "client_candidate.decide")

        approved = await CC.act_on_client_candidate(
            ACME_CLIENT, ACME, good["ccn_no"], "client-approve", {})
        check("the client approves the CV",
              approved["status"] == M.ClientCandidateStatus.CLIENT_APPROVED.value)
        check("and the verdict is attributed to them",
              approved["client_decision"]["by_name"] == "Acme Talent Lead")
        opened = await CC.assert_assessment_allowed(ACME, good["ccn_no"])
        check("the assessment stage is now open", opened["ccn_no"] == good["ccn_no"])

        # =================================================================
        section("A rejected CV ends the run")
        # =================================================================
        other = await add("Dev Passedover")
        await carry(other["ccn_no"], 4.0, 4.0, 4.0)
        await CC.act_on_client_candidate(RECRUITER, ACME, other["ccn_no"], "shortlist", {})
        await CC.act_on_client_candidate(TEAM_LEAD, ACME, other["ccn_no"], "share", {})
        await expect_http(
            "rejecting a CV with no reason",
            CC.act_on_client_candidate(ACME_CLIENT, ACME, other["ccn_no"],
                                       "client-reject", {}),
            422, "say why")
        rejected = await CC.act_on_client_candidate(
            ACME_CLIENT, ACME, other["ccn_no"], "client-reject",
            {"remarks": "Not enough exposure to payments."})
        check("the client rejects them",
              rejected["status"] == M.ClientCandidateStatus.CLIENT_REJECTED.value)
        await expect_http(
            "...and assessment stays shut",
            CC.assert_assessment_allowed(ACME, other["ccn_no"]), 409, "approves the cv")
        for action in M.CLIENT_CANDIDATE_TRANSITIONS:
            mover = {"CLIENT_CANDIDATE_WRITE": RECRUITER,
                     "CLIENT_CANDIDATE_SHARE": TEAM_LEAD,
                     "CLIENT_CANDIDATE_DECIDE": ACME_CLIENT}[
                         M.CLIENT_CANDIDATE_TRANSITIONS[action][2]]
            await expect_http(
                f'a rejected candidate refuses "{action}"',
                CC.act_on_client_candidate(mover, ACME, other["ccn_no"], action,
                                           {"remarks": "trying anyway"}),
                409, "cannot progress")

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        elsewhere = await add("Globex Person", company=GLOBEX)
        mine = await CC.list_client_candidates(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_candidates"]))
        check("...and none of Globex's",
              not any(r["company_id"] == GLOBEX for r in mine["client_candidates"]))
        await expect_http(
            "Acme opening a Globex candidate by number",
            CC.get_client_candidate(ACME_CLIENT, ACME, elsewhere["ccn_no"]),
            404, "not found")
        check("naming another company in the query is ignored",
              HA.scope_company_id(ACME_CLIENT, GLOBEX) == ACME)
        await expect_http(
            "a client-side caller with no company in scope",
            CC.list_client_candidates(ACME_CLIENT, None), 403, "no company in scope")

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection",
              M.COLL_CLIENT_CANDIDATES != M.COLL_CANDIDATES)
        check("its own status vocabulary for the stages that differ",
              {M.ClientCandidateStatus.SHARED_WITH_CLIENT.value,
               M.ClientCandidateStatus.CLIENT_APPROVED.value}
              .isdisjoint({s.value for s in M.AppStatus}))
        check("its own transition table",
              set(M.CLIENT_CANDIDATE_TRANSITIONS)
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
