"""Client Hiring step 2 -- the Position Scorecard.

PRO-fit SOP sections 4, 5.2, 6 and the section 8 approval matrix: the recruiter drafts the
evaluation benchmark, the Team Lead reviews it before it leaves the building, and the
client's approval is mandatory before anyone is sourced.

Four properties this file pins:

  1. NO SPARSH ROLE CAN GIVE THE CLIENT'S APPROVAL. A mandatory client sign-off that the
     supplier can supply for themselves is not mandatory. Asserted against the whole role
     matrix, not just against the roles this test happens to use.
  2. THE DRAFTER IS NOT THE APPROVER, on either side. The recruiter cannot review; the
     reviewer cannot write; the client can do neither.
  3. A CLIENT NEVER SEES A DRAFT. Enforced on the read path, so it is not merely hidden by
     a screen that could be bypassed with a direct call.
  4. NO SOURCING WITHOUT AN AGREED BENCHMARK. Section 6, expressed as the one gate every
     later step will ask.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_scorecard   (from backend/)
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

FULL = {"responsibilities": "Own the billing service end to end.",
        "skills": "Python, FastAPI, MongoDB.",
        "experience": "Three to five years building transactional services.",
        "cultural_expectations": "Writes things down; comfortable disagreeing early.",
        "success_indicators": "Owns an on-call rotation unaided within one quarter."}


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)
    reqs = FakeCollection([
        {"cr_no": "CR-2026-001", "company_id": ACME, "role_title": "Backend Engineer",
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
        {"cr_no": "CR-2026-002", "company_id": ACME, "role_title": "Data Analyst",
         "status": M.ClientReqStatus.PENDING_FEASIBILITY.value, "created_at": NOW},
        {"cr_no": "CR-2026-001", "company_id": GLOBEX, "role_title": "Support Lead",
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
    ])
    store = {M.COLL_CLIENT_REQUISITIONS: reqs,
             M.COLL_CLIENT_SCORECARDS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_scorecard_service as SC
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (SC, AUD, IDS, HA):
        mod.get_collection = mongo.get_collection

    def client(company, name="Client Person"):
        return {"_id": str(ObjectId()), "role": "clientadmin",
                "_source_collection": "learners", "company_id": company,
                "full_name": name, M.CLIENT_TRACK_FLAG: True}

    def sparsh(governance, name="Sparsh Person"):
        return {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff",
                "company_id": SPARSH, "governance_role": governance, "full_name": name}

    ACME_CLIENT = client(ACME, "Acme Talent Lead")
    GLOBEX_CLIENT = client(GLOBEX, "Globex Talent Lead")
    RECRUITER = sparsh("HR", "Sparsh Recruiter")
    TEAM_LEAD = sparsh("HOD", "Sparsh Team Lead")
    OPS_HEAD = sparsh("MD", "Sparsh Ops Head")

    try:
        # =================================================================
        section("Who may do what to a benchmark")
        # =================================================================
        check("the recruiter drafts", HA.can(RECRUITER, M.Cap.CLIENT_SCORECARD_WRITE))
        check("...but does not review",
              not HA.can(RECRUITER, M.Cap.CLIENT_SCORECARD_REVIEW))
        check("the Team Lead reviews", HA.can(TEAM_LEAD, M.Cap.CLIENT_SCORECARD_REVIEW))
        check("...but does not write",
              not HA.can(TEAM_LEAD, M.Cap.CLIENT_SCORECARD_WRITE))
        check("the client approves", HA.can(ACME_CLIENT, M.Cap.CLIENT_SCORECARD_APPROVE))
        check("...and can neither write nor review",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_SCORECARD_WRITE)
              and not HA.can(ACME_CLIENT, M.Cap.CLIENT_SCORECARD_REVIEW))
        check("NO Sparsh role can give the client's approval",
              not any(M.Cap.CLIENT_SCORECARD_APPROVE in caps
                      for caps in M.ROLE_CAPABILITIES.values()))
        check("not even the Operations Head",
              not HA.can(OPS_HEAD, M.Cap.CLIENT_SCORECARD_APPROVE))

        # =================================================================
        section("A benchmark hangs off an approved requisition")
        # =================================================================
        await expect_http(
            "drafting against a requisition still in feasibility",
            SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": "CR-2026-002",
                                                         **FULL}),
            409, "assessed and approved")
        await expect_http(
            "drafting against a requisition that does not exist here",
            SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": "CR-9999-999"}),
            404, "not found")

        made = await SC.create_client_scorecard(
            RECRUITER, ACME, {"cr_no": "CR-2026-001", "responsibilities": "Draft only."})
        PSC = made["psc_no"]
        check("the recruiter drafts one", made["status"] ==
              M.ClientScorecardStatus.DRAFT.value)
        check("it carries the role it is for", made["role_title"] == "Backend Engineer")

        await expect_http(
            "a second scorecard for the same role",
            SC.create_client_scorecard(RECRUITER, ACME, {"cr_no": "CR-2026-001"}),
            409, "one role, one benchmark")

        # =================================================================
        section("A client never sees a draft")
        # =================================================================
        await expect_http(
            "the client opening a scorecard still being written",
            SC.get_client_scorecard(ACME_CLIENT, ACME, PSC), 404, "not found")
        listed = await SC.list_client_scorecards(ACME_CLIENT, ACME)
        check("...and it is not in their list", listed["total"] == 0)
        seen = await SC.list_client_scorecards(RECRUITER, ACME)
        check("Sparsh sees their own draft", seen["total"] == 1)

        # =================================================================
        section("Incomplete benchmarks do not go out")
        # =================================================================
        await expect_http(
            "submitting a half-written scorecard",
            SC.act_on_client_scorecard(RECRUITER, ACME, PSC, "submit-for-review", {}),
            422, "still needed")

        await SC.update_client_scorecard(RECRUITER, ACME, PSC, FULL)
        row = await SC.get_client_scorecard(RECRUITER, ACME, PSC)
        check("the recruiter completes all five sections",
              all(row.get(key) for key, _ in M.CLIENT_SCORECARD_SECTIONS))

        # =================================================================
        section("Recruiter drafts -> Team Lead reviews -> client approves")
        # =================================================================
        await SC.act_on_client_scorecard(RECRUITER, ACME, PSC, "submit-for-review", {})
        row = await SC.get_client_scorecard(RECRUITER, ACME, PSC)
        check("it goes to the Team Lead",
              row["status"] == M.ClientScorecardStatus.PENDING_INTERNAL_REVIEW.value)
        await expect_http(
            "...and the recruiter can no longer edit it",
            SC.update_client_scorecard(RECRUITER, ACME, PSC, {"skills": "changed"}),
            409, "cannot be edited")
        await expect_http(
            "the recruiter passing their own internal review",
            SC.act_on_client_scorecard(RECRUITER, ACME, PSC, "internal-approve", {}),
            403, "client_scorecard.review")
        await expect_http(
            "the CLIENT passing Sparsh's internal review",
            SC.act_on_client_scorecard(ACME_CLIENT, ACME, PSC, "internal-approve", {}),
            403, "client_scorecard.review")

        await SC.act_on_client_scorecard(TEAM_LEAD, ACME, PSC, "internal-approve", {})
        row = await SC.get_client_scorecard(RECRUITER, ACME, PSC)
        check("the Team Lead passes it to the client",
              row["status"] == M.ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value)
        check("now the client can see it",
              (await SC.get_client_scorecard(ACME_CLIENT, ACME, PSC))["psc_no"] == PSC)

        await expect_http(
            "Sparsh approving on the client's behalf",
            SC.act_on_client_scorecard(OPS_HEAD, ACME, PSC, "client-approve", {}),
            403, "client_scorecard.approve")
        check("sourcing is still shut",
              await SC.approved_scorecard_for(ACME, "CR-2026-001") is None)

        approved = await SC.act_on_client_scorecard(
            ACME_CLIENT, ACME, PSC, "client-approve", {})
        check("the client approves it",
              approved["status"] == M.ClientScorecardStatus.APPROVED.value)
        check("and the approval is attributed to them",
              approved["client_approval"]["by_name"] == "Acme Talent Lead")

        # =================================================================
        section("An approved benchmark is frozen")
        # =================================================================
        for action in M.CLIENT_SCORECARD_TRANSITIONS:
            mover = {"CLIENT_SCORECARD_WRITE": RECRUITER,
                     "CLIENT_SCORECARD_REVIEW": TEAM_LEAD,
                     "CLIENT_SCORECARD_APPROVE": ACME_CLIENT}[
                         M.CLIENT_SCORECARD_TRANSITIONS[action][2]]
            await expect_http(
                f'an approved scorecard refuses "{action}"',
                SC.act_on_client_scorecard(mover, ACME, PSC, action,
                                           {"remarks": "trying anyway"}),
                409, "move the yardstick")
        await expect_http(
            "...and cannot be edited",
            SC.update_client_scorecard(RECRUITER, ACME, PSC, {"skills": "changed"}),
            409, "cannot be edited")

        # =================================================================
        section("Section 6 -- no sourcing without an agreed benchmark")
        # =================================================================
        got = await SC.assert_sourcing_allowed(ACME, "CR-2026-001")
        check("sourcing is allowed once the client has approved", got["psc_no"] == PSC)
        await expect_http(
            "sourcing a role whose benchmark nobody agreed",
            SC.assert_sourcing_allowed(GLOBEX, "CR-2026-001"), 409, "section 6")

        # =================================================================
        section("Returned is not rejected")
        # =================================================================
        second = await SC.create_client_scorecard(
            RECRUITER, GLOBEX, {"cr_no": "CR-2026-001", **FULL})
        TWO = second["psc_no"]
        await SC.act_on_client_scorecard(RECRUITER, GLOBEX, TWO, "submit-for-review", {})
        await expect_http(
            "returning it with no reason",
            SC.act_on_client_scorecard(TEAM_LEAD, GLOBEX, TWO, "internal-return", {}),
            422, "say what needs to change")
        back = await SC.act_on_client_scorecard(
            TEAM_LEAD, GLOBEX, TWO, "internal-return",
            {"remarks": "Success indicators are activities, not outcomes."})
        check("the Team Lead sends it back to Draft",
              back["status"] == M.ClientScorecardStatus.DRAFT.value)
        check("and the recruiter may edit it again",
              back["status"] in M.CLIENT_SCORECARD_EDITABLE)

        await SC.act_on_client_scorecard(RECRUITER, GLOBEX, TWO, "submit-for-review", {})
        await SC.act_on_client_scorecard(TEAM_LEAD, GLOBEX, TWO, "internal-approve", {})
        returned = await SC.act_on_client_scorecard(
            GLOBEX_CLIENT, GLOBEX, TWO, "client-return",
            {"remarks": "We need five years, not three."})
        check("the client can send it back too",
              returned["status"] == M.ClientScorecardStatus.DRAFT.value)
        check("and the stale internal approval is cleared with it",
              returned["internal_review"] is None)

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        # Numbers are sequenced per company on purpose, so both tenants start at the same
        # one. Asking for it resolves to YOUR row, never theirs -- that is the isolation
        # working, not a collision.
        same_number = await SC.get_client_scorecard(ACME_CLIENT, ACME, TWO)
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)
        await expect_http(
            "a number that exists in no tenant of theirs",
            SC.get_client_scorecard(ACME_CLIENT, ACME, "PSC-2026-999"), 404, "not found")
        mine = await SC.list_client_scorecards(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_scorecards"]))
        check("naming another company in the query is ignored",
              HA.scope_company_id(ACME_CLIENT, GLOBEX) == ACME)
        await expect_http(
            "a client-side caller with no company in scope",
            SC.list_client_scorecards(ACME_CLIENT, None), 403, "no company in scope")

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection",
              M.COLL_CLIENT_SCORECARDS != M.COLL_POSITION_SCORECARDS)
        check("its own capabilities",
              M.Cap.CLIENT_SCORECARD_APPROVE is not M.Cap.SCORECARD_APPROVE)
        check("the internal scorecard capability is not on the client ceiling",
              M.Cap.SCORECARD_APPROVE not in M.CLIENT_TRACK_CAPS
              and M.Cap.SCORECARD_WRITE not in M.CLIENT_TRACK_CAPS)
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
