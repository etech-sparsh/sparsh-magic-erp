"""Client Hiring -- delivery analytics, and the client-wise breakdown.

Three properties this file pins:

  1. THE BREAKDOWN IS FOR SPARSH ONLY. A cross-client comparison is exactly what one
     client must never see: their own row is their business, everybody else's is not.
  2. "WHOSE MOVE IS IT" SPLITS CORRECTLY. The PRO-fit flow alternates between the two
     sides, so a backlog number is only useful when it says who owes what.
  3. IT COUNTS THE CLIENT TRACK AND NOTHING ELSE. No internal requisition, candidate or
     employee reaches these figures.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_analytics   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)
    ACME, GLOBEX = ObjectId(), ObjectId()
    A, G = str(ACME), str(GLOBEX)

    def row(company, status, **extra):
        return {"company_id": company, "status": status, "created_at": NOW, **extra}

    store = {
        "companies": FakeCollection([
            {"_id": ACME, "name": "Acme Industries"},
            {"_id": GLOBEX, "name": "Globex Corp"},
        ]),
        M.COLL_CLIENT_REQUISITIONS: FakeCollection([
            row(A, M.ClientReqStatus.APPROVED.value),
            row(A, M.ClientReqStatus.CLOSED.value),
            row(A, M.ClientReqStatus.PENDING_FEASIBILITY.value),
            row(G, M.ClientReqStatus.APPROVED.value),
        ]),
        M.COLL_CLIENT_CANDIDATES: FakeCollection([
            row(A, M.ClientCandidateStatus.SOURCED.value),
            row(A, M.ClientCandidateStatus.SHARED_WITH_CLIENT.value),
            row(A, M.ClientCandidateStatus.SHARED_WITH_CLIENT.value),
            row(A, M.ClientCandidateStatus.JOINED.value),
            row(G, M.ClientCandidateStatus.SHORTLISTED.value),
        ]),
        M.COLL_CLIENT_SCORECARDS: FakeCollection([
            row(A, M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value),
            row(G, M.ClientScorecardStatus.DRAFT.value),
        ]),
        M.COLL_CLIENT_ASSESSMENTS: FakeCollection([
            row(A, M.ClientAssessmentStatus.SUBMITTED.value),
        ]),
        M.COLL_CLIENT_INTERVIEWS: FakeCollection([
            row(A, M.ClientInterviewStatus.SHARED.value),
        ]),
        M.COLL_CLIENT_OFFERS: FakeCollection([
            row(A, M.ClientOfferStatus.ACCEPTED.value),
            row(A, M.ClientOfferStatus.ACCEPTED.value),
            row(A, M.ClientOfferStatus.DECLINED.value),
            row(A, M.ClientOfferStatus.PENDING_CLIENT_APPROVAL.value),
        ]),
        M.COLL_CLIENT_JOININGS: FakeCollection([
            row(A, M.ClientJoiningStatus.PRE_BOARDING.value, at_risk=True),
        ]),
        # Populated on purpose: these must NOT reach a single figure below.
        M.COLL_REQUISITIONS: FakeCollection([row(A, "Approved"), row(G, "Approved")]),
        M.COLL_CANDIDATES: FakeCollection([row(A, "Selected")]),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_analytics_service as AN
    import app.utils.hrms_access as HA
    for mod in (AN, HA):
        mod.get_collection = mongo.get_collection

    def sparsh():
        return {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff",
                "governance_role": "HR", "full_name": "Sparsh Person"}

    def client(company):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company,
                "full_name": "Client Person", M.CLIENT_TRACK_FLAG: True}

    try:
        # =================================================================
        section("One client — the engagement board")
        # =================================================================
        one = await AN.client_recruitment_analytics(sparsh(), A)
        check("scope says one client", one["scope"] == "one_client")
        check("no cross-client breakdown when a client is selected",
              one["by_client"] == [])
        check("requisitions counted for that client only",
              one["headline"]["requisitions_raised"] == 3)
        check("candidates too", one["headline"]["candidates_sourced"] == 4)
        check("joined counted", one["headline"]["joined"] == 1)

        # =================================================================
        section("Whose move is it")
        # =================================================================
        # Acme: 2 CVs + 1 scorecard + 1 recording + 1 offer + 1 pre-boarding = 6
        check("waiting on the client adds up", one["waiting_on_client_total"] == 6)
        check("and names the actual work, not a status",
              one["waiting_on_client"].get("CV verdicts") == 2)
        # Acme: 1 feasibility + 1 assessment to mark = 2
        check("waiting on Sparsh adds up", one["waiting_on_sparsh_total"] == 2)
        check("empty piles are left out entirely",
              all(v for v in one["waiting_on_client"].values())
              and all(v for v in one["waiting_on_sparsh"].values()))

        # =================================================================
        section("Outcomes")
        # =================================================================
        o = one["outcomes"]
        check("acceptance counts only answered offers (2 of 3)",
              o["offer_acceptance_rate"] == 66.7)
        check("a live offer is not in the denominator",
              o["offers_accepted"] == 2 and o["offers_declined"] == 1)

        # =================================================================
        section("All clients — the comparison")
        # =================================================================
        every = await AN.client_recruitment_analytics(sparsh(), None)
        check("scope says all clients", every["scope"] == "all_clients")
        rows = {r["company_name"]: r for r in every["by_client"]}
        check("one row per client with activity", set(rows) == {"Acme Industries",
                                                                "Globex Corp"})
        check("company names are resolved, not ids",
              rows["Acme Industries"]["company_id"] == A)
        check("Acme's figures are Acme's",
              rows["Acme Industries"]["requisitions_live"] == 1
              and rows["Acme Industries"]["candidates"] == 4
              and rows["Acme Industries"]["joined"] == 1)
        check("Globex's are Globex's",
              rows["Globex Corp"]["candidates"] == 1
              and rows["Globex Corp"]["joined"] == 0)
        check("the split is per client too",
              rows["Acme Industries"]["waiting_on_client"] == 6
              and rows["Globex Corp"]["waiting_on_sparsh"] == 1)
        check("acceptance is per client, and None when nobody has answered",
              rows["Acme Industries"]["offer_acceptance_rate"] == 66.7
              and rows["Globex Corp"]["offer_acceptance_rate"] is None)
        check("busiest engagement first",
              every["by_client"][0]["company_name"] == "Acme Industries")
        check("headline across all clients sums both",
              every["headline"]["requisitions_raised"] == 4
              and every["headline"]["candidates_sourced"] == 5)

        # =================================================================
        section("A client company never gets the comparison")
        # =================================================================
        theirs = await AN.client_recruitment_analytics(client(A), A)
        check("a client sees no breakdown", theirs["by_client"] == [])
        # Even if their company somehow arrived unscoped, they are not internal, so the
        # breakdown stays empty. The route pins them regardless; this is the second lock.
        unscoped = await AN.client_recruitment_analytics(client(A), None)
        check("...not even with no company in scope", unscoped["by_client"] == [])

        # =================================================================
        section("Internal Hiring never reaches these figures")
        # =================================================================
        # The internal collections above hold rows for both companies. If any leaked in,
        # these counts would be higher than the client-track rows alone.
        check("internal requisitions are not counted",
              every["headline"]["requisitions_raised"] == 4)
        check("internal candidates are not counted",
              every["headline"]["candidates_sourced"] == 5)
        check("the board reads only client-track collections",
              M.COLL_CLIENT_REQUISITIONS != M.COLL_REQUISITIONS
              and M.COLL_CLIENT_CANDIDATES != M.COLL_CANDIDATES)
    finally:
        mongo.get_collection = original

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
