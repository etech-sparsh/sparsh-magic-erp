"""Client Hiring step 2b -- the job posting, the applications, and the available pool.

An approved Position Scorecard is a benchmark, not an advert. This stage turns one into
the other, and adds the two things the flow asked for that the track did not have: a place
for people to apply, and somewhere for a rejected candidate to go that is neither deletion
nor a dead end.

Five properties this file pins:

  1. NO ADVERT WITHOUT AN AGREED BENCHMARK. A posting hangs off a requisition whose
     scorecard the CLIENT approved -- re-checked at publish, not only at draft, because a
     scorecard can be sent back in between.
  2. AN APPLICANT IS A CANDIDATE. A public submission creates an ordinary client candidate
     at SOURCED, so the existing chain carries it. No parallel pipeline to drift.
  3. THE PUBLIC SURFACE LEAKS NOTHING. The advert behind a link is the advert -- not the
     requisition, not the company, not the internal numbering. A bad code is an opaque 404.
  4. A REJECTED CANDIDATE IS NOT DELETED AND NOT CLOSED FOREVER. Their record stays with
     the client who rejected them. Sparsh sees the PERSON in a pool spanning engagements.
  5. RE-SOURCING CREATES A NEW RECORD IN THE NEW TENANT. Client B never sees Client A's
     row and never learns who passed on them. This is the only reading of "reusable" that
     does not breach tenant isolation.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_posting_and_pool   (from backend/)
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
        hrms_client_posting_service as POST,
    )
    for mod in (REQ, SC, CAND, POST, HA):
        mod.get_collection = mongo.get_collection

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

    RECRUITER, LEAD = sparsh("HR", name="Recruiter"), sparsh("HOD", name="Team Lead")
    ACME_USER, GLOBEX_USER = client(ACME), client(GLOBEX)

    async def requisition(company, title="Warehouse Lead"):
        r = await REQ.create_client_requisition(client(company), company, {
            "business_context": "Expansion.", "role_need": f"{title}.",
            "engagement_expectations": "Three weeks."})
        cr = r["cr_no"]
        u = client(company)
        await REQ.act_on_client_requisition(u, company, cr, "submit-need-mapping")
        await REQ.update_client_requisition(u, company, cr, {
            "role_title": title, "department_name": "Operations",
            "reporting_line": "Head of Operations",
            "salary_range_min": 600000, "salary_range_max": 900000,
            "employment_type": "Permanent", "urgency": "High", "vacancies": 1,
            "role_level": "Mid-level / Specialist"})
        await REQ.act_on_client_requisition(u, company, cr, "submit-requisition")
        await REQ.act_on_client_requisition(
            LEAD, company, cr, "feasibility-approve",
            {"role_clarity": True, "compensation_competitive": True,
             "timeline_realistic": True})
        return cr

    async def scorecard(company, cr, approve=True):
        s = await SC.create_client_scorecard(RECRUITER, company, {
            "cr_no": cr, "responsibilities": "Owns throughput.", "skills": "WMS.",
            "experience": "6+ years.", "cultural_expectations": "Calm.",
            "success_indicators": "99% accuracy."})
        psc = s["psc_no"]
        await SC.act_on_client_scorecard(RECRUITER, company, psc, "submit-for-review")
        await SC.act_on_client_scorecard(LEAD, company, psc, "internal-approve")
        if approve:
            await SC.act_on_client_scorecard(client(company), company, psc,
                                             "client-approve")
        return psc

    try:
        # =================================================================
        section("1. No advert without an agreed benchmark")
        # =================================================================
        cr = await requisition(ACME)
        await expect_http(
            "posting before any scorecard exists",
            POST.create_client_posting(RECRUITER, ACME, {"cr_no": cr}),
            409)
        psc = await scorecard(ACME, cr, approve=False)
        await expect_http(
            "posting while the scorecard is still with the client",
            POST.create_client_posting(RECRUITER, ACME, {"cr_no": cr}),
            409)
        await SC.act_on_client_scorecard(ACME_USER, ACME, psc, "client-approve")

        posting = await POST.create_client_posting(RECRUITER, ACME, {
            "cr_no": cr, "location": "Indore",
            "summary": "Own dispatch accuracy across the western hub."})
        pno = posting["posting_no"]
        check("the posting takes its title from the requisition",
              posting["title"] == "Warehouse Lead")
        check("it starts as a draft",
              posting["status"] == M.ClientPostingStatus.DRAFT.value)
        check("and the salary band is hidden until the client says otherwise",
              posting["show_salary"] is False)

        # =================================================================
        section("Publishing needs an advert somebody can actually read")
        # =================================================================
        await expect_http("publish with no responsibilities or requirements",
                          POST.act_on_client_posting(LEAD, ACME, pno, "publish"),
                          422, "still needed")
        await POST.update_client_posting(RECRUITER, ACME, pno, {
            "responsibilities": "Shift planning, shrinkage, safety.",
            "requirements": "6+ years, 2 leading a shift."})
        for label, actor in (("the client", ACME_USER),):
            await expect_http(f"{label} cannot publish a Sparsh advert",
                              POST.act_on_client_posting(actor, ACME, pno, "publish"),
                              403)
        await POST.act_on_client_posting(LEAD, ACME, pno, "publish")
        live = await POST.get_client_posting(RECRUITER, ACME, pno)
        check("published", live["status"] == M.ClientPostingStatus.PUBLISHED.value)
        check("and it carries a public code", bool(live.get("posting_code")))

        await expect_http("editing a published advert people have answered",
                          POST.update_client_posting(RECRUITER, ACME, pno,
                                                     {"summary": "changed"}),
                          409)

        # =================================================================
        section("3. The public surface leaks nothing")
        # =================================================================
        code = live["posting_code"]
        await expect_http("a code that does not exist", POST.get_public_client_posting("CJ-ZZZZZZ"),
                          404)
        ad = await POST.get_public_client_posting(code)
        for hidden in ("cr_no", "company_id", "posting_no", "posting_code",
                       "salary_range_min", "created_by_name"):
            check(f"the advert does not expose {hidden}", hidden not in ad)
        check("it does carry what an applicant needs",
              ad["title"] == "Warehouse Lead" and ad["location"] == "Indore"
              and bool(ad["requirements"]))

        # The band appears only when the client chose to disclose it.
        cr2 = await requisition(ACME, title="Open Band Role")
        await scorecard(ACME, cr2)
        p2 = await POST.create_client_posting(RECRUITER, ACME, {
            "cr_no": cr2, "show_salary": True, "summary": "s",
            "responsibilities": "r", "requirements": "q"})
        await POST.act_on_client_posting(LEAD, ACME, p2["posting_no"], "publish")
        ad2 = await POST.get_public_client_posting(
            (await POST.get_client_posting(RECRUITER, ACME, p2["posting_no"]))
            ["posting_code"])
        check("with show_salary the band IS advertised",
              ad2.get("salary_range_min") == 600000)

        # =================================================================
        section("2. An applicant becomes an ordinary candidate")
        # =================================================================
        BAD = [("no name", {"candidate_name": "", "email": "a@b.co", "phone": "9000000000",
                            "cv_reference": "cv", "declaration": True}, "full name"),
               ("a malformed email", {"candidate_name": "A", "email": "nope",
                                      "phone": "9000000000", "cv_reference": "cv",
                                      "declaration": True}, "email"),
               ("a malformed phone", {"candidate_name": "A", "email": "a@b.co",
                                      "phone": "x", "cv_reference": "cv",
                                      "declaration": True}, "phone"),
               ("no CV", {"candidate_name": "A", "email": "a@b.co",
                          "phone": "9000000000", "declaration": True}, "cv"),
               ("no declaration", {"candidate_name": "A", "email": "a@b.co",
                                   "phone": "9000000000", "cv_reference": "cv"},
                "accurate")]
        for label, payload, fragment in BAD:
            await expect_http(f"application with {label}",
                              POST.submit_client_application(code, payload),
                              422, fragment)

        applied = await POST.submit_client_application(code, {
            "candidate_name": "Ritu Sharma", "email": "ritu@example.com",
            "phone": "9000000001", "cv_reference": "ritu-cv.pdf",
            "current_employer": "Kuehne", "notice_period": "30 days",
            "declaration": True})
        ccn = applied["ccn_no"]
        check("the application created a candidate", bool(ccn))
        row = await CAND.get_client_candidate(RECRUITER, ACME, ccn)
        check("...at SOURCED, where the ordinary chain begins",
              row["status"] == M.ClientCandidateStatus.SOURCED.value)
        check("...against the posting's own requisition", row["cr_no"] == cr)
        check("...stamped with how they arrived",
              row["source"] == "Job posting" and row["posting_no"] == pno)

        again = await POST.submit_client_application(code, {
            "candidate_name": "Ritu Sharma", "email": "ritu@example.com",
            "phone": "9000000001", "cv_reference": "ritu-cv.pdf",
            "declaration": True})
        check("a double submit returns the same candidate, not a second one",
              again["ccn_no"] == ccn and again["already_applied"] is True)

        apps = await POST.list_applications(RECRUITER, ACME, posting_no=pno)
        check("the applicant shows against their posting",
              [a["ccn_no"] for a in apps["client_applications"]] == [ccn])
        check("the posting counts them",
              (await POST.get_client_posting(RECRUITER, ACME, pno))["applications"] == 1)

        # A closed vacancy stops accepting, and what already arrived stays.
        await expect_http("closing with no reason",
                          POST.act_on_client_posting(RECRUITER, ACME, pno, "close"), 422)
        await POST.act_on_client_posting(RECRUITER, ACME, pno, "close",
                                         {"remarks": "Filled from the shortlist."})
        await expect_http("applying to a closed vacancy",
                          POST.submit_client_application(code, {
                              "candidate_name": "Late", "email": "late@example.com",
                              "phone": "9000000002", "cv_reference": "cv",
                              "declaration": True}),
                          410)
        still = await CAND.get_client_candidate(RECRUITER, ACME, ccn)
        check("...and the candidate is still there",
              still["status"] == M.ClientCandidateStatus.SOURCED.value)

        # =================================================================
        section("4. A client rejection pools the candidate, it does not delete them")
        # =================================================================
        await CAND.update_client_candidate(RECRUITER, ACME, ccn,
                                           {"tfs_score": 4.4, "competency_score": 4.2,
                                            "pi_score": 4.2})
        for act in ("screen", "telephonic-pass", "shortlist"):
            await CAND.act_on_client_candidate(RECRUITER, ACME, ccn, act)
        await CAND.act_on_client_candidate(LEAD, ACME, ccn, "share")
        await CAND.act_on_client_candidate(ACME_USER, ACME, ccn, "client-reject",
                                           {"remarks": "Wanted more shift leadership."})

        rejected = await CAND.get_client_candidate(RECRUITER, ACME, ccn)
        check("the record still exists after rejection", rejected["ccn_no"] == ccn)
        check("...in the rejecting client's own tenant",
              rejected["company_id"] == ACME)
        check("...and the client can still see their own decision",
              (await CAND.get_client_candidate(ACME_USER, ACME, ccn))["status"]
              == M.ClientCandidateStatus.CLIENT_REJECTED.value)
        check("rejected is a POOL state as well as a closed one",
              M.ClientCandidateStatus.CLIENT_REJECTED.value in M.CLIENT_CANDIDATE_POOL)

        pool = await CAND.list_candidate_pool(RECRUITER)
        person = next((p for p in pool["client_candidate_pool"]
                       if p["ccn_no"] == ccn), None)
        check("the person is in Sparsh's pool", person is not None)
        check("...carrying their CV forward",
              person is not None and person["cv_reference"] == "ritu-cv.pdf")
        # The pool carries the ENGAGEMENT (Sparsh-only, and needed to identify the row,
        # since ccn_no is minted per company) but not the rejection: no requisition, no
        # reason, no client decision.
        check("...keyed by tenant AND number, because ccn_no repeats across engagements",
              person is not None and person["from_company_id"] == ACME)
        check("...but NOT the rejection itself",
              person is not None
              and "cr_no" not in person and "client_decision" not in person)

        await expect_http("a client reading the cross-tenant pool",
                          CAND.list_candidate_pool(ACME_USER), 403)
        await expect_http("...even their own admin",
                          CAND.list_candidate_pool(client(GLOBEX)), 403)

        # =================================================================
        section("5. Re-sourcing creates a NEW record in the NEW tenant")
        # =================================================================
        gcr = await requisition(GLOBEX, title="Hub Supervisor")
        await scorecard(GLOBEX, gcr)

        await expect_http("re-sourcing by a client",
                          CAND.resource_from_pool(GLOBEX_USER, GLOBEX,
                                                  {"ccn_no": ccn, "from_company_id": ACME,
                                                   "cr_no": gcr}),
                          403)
        await expect_http("re-sourcing on a number alone, with no engagement named",
                          CAND.resource_from_pool(RECRUITER, GLOBEX,
                                                  {"ccn_no": ccn, "cr_no": gcr}),
                          422)
        fresh = await CAND.resource_from_pool(RECRUITER, GLOBEX,
                                              {"ccn_no": ccn, "from_company_id": ACME,
                                               "cr_no": gcr})
        # NOT `ccn_no != ccn`: business ids are minted per COMPANY, so Globex's first
        # candidate is legitimately CCN-2026-001 too. Identity here is (tenant, number).
        check("a NEW record was created, not the old one re-pointed",
              (fresh["ccn_no"], fresh["company_id"]) != (ccn, ACME))
        check("...in Globex's tenant", fresh["company_id"] == GLOBEX)
        check("...against Globex's requisition", fresh["cr_no"] == gcr)
        check("...at SOURCED, starting the chain again",
              fresh["status"] == M.ClientCandidateStatus.SOURCED.value)
        check("...with the CV carried across", fresh["cv_reference"] == "ritu-cv.pdf")
        check("...and the scores NOT carried across -- a different benchmark",
              fresh["tfs_score"] is None and fresh["average_score"] is None)

        check("Acme's original is untouched",
              (await CAND.get_client_candidate(RECRUITER, ACME, ccn))["status"]
              == M.ClientCandidateStatus.CLIENT_REJECTED.value)
        # The re-sourced candidate is at SOURCED, so the ordinary visibility rule applies
        # to them too: Globex cannot see them yet either. Sparsh screens and shares first.
        await expect_http("Globex cannot see them before they are shared",
                          CAND.get_client_candidate(GLOBEX_USER, GLOBEX,
                                                    fresh["ccn_no"]), 404)
        await CAND.update_client_candidate(RECRUITER, GLOBEX, fresh["ccn_no"],
                                           {"tfs_score": 4.1, "competency_score": 4.0,
                                            "pi_score": 4.0})
        for act in ("screen", "telephonic-pass", "shortlist"):
            await CAND.act_on_client_candidate(RECRUITER, GLOBEX, fresh["ccn_no"], act)
        await CAND.act_on_client_candidate(LEAD, GLOBEX, fresh["ccn_no"], "share")
        globex_view = await CAND.get_client_candidate(GLOBEX_USER, GLOBEX,
                                                      fresh["ccn_no"])
        check("once shared, Globex sees their own row",
              globex_view["ccn_no"] == fresh["ccn_no"])
        check("...and cannot learn that anybody rejected this person",
              "sourced_from_ccn" not in globex_view)
        check("...nor read Acme's scores, which were never carried across",
              globex_view.get("tfs_score") == 4.1)
        # Both engagements legitimately hold a CCN-2026-001. Asking as Globex returns
        # GLOBEX's row -- which IS the isolation working, not a leak: the number is scoped
        # by the caller's tenant before it ever reaches the database.
        as_globex = await CAND.get_client_candidate(RECRUITER, GLOBEX, fresh["ccn_no"])
        as_acme = await CAND.get_client_candidate(RECRUITER, ACME, ccn)
        check("the same number in two tenants resolves to two different people's rows",
              as_globex["company_id"] == GLOBEX and as_acme["company_id"] == ACME)
        check("...at their own separate stages",
              as_globex["status"] != as_acme["status"])

        await expect_http("re-sourcing somebody still live on an engagement",
                          CAND.resource_from_pool(RECRUITER, GLOBEX,
                                                  {"ccn_no": fresh["ccn_no"],
                                                   "from_company_id": GLOBEX,
                                                   "cr_no": gcr}),
                          409, "still live")

        # =================================================================
        section("Tenant isolation on the posting itself")
        # =================================================================
        await expect_http("Globex cannot read Acme's posting",
                          POST.get_client_posting(GLOBEX_USER, GLOBEX, pno), 404)
        gl = await POST.list_client_postings(GLOBEX_USER, GLOBEX)
        check("nor does it appear in their list", gl["client_postings"] == [])
        check("every posting row carries a company_id",
              all(r.get("company_id")
                  for r in await store[M.COLL_CLIENT_POSTINGS].find({}).to_list(50)))
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
