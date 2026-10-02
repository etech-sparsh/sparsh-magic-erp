"""Client Hiring step 7 -- reference check and the offer.

PRO-fit SOP sections 15, 16, 17 and the section 8 approval matrix.

Four properties this file pins:

  1. SECTION 16'S CHECKPOINT IS ENFORCED, not printed. The client's selection, the figure
     against the range THEY approved, and section 15's reference for managerial roles.
  2. THE CLIENT ISSUES THE LETTER. No Sparsh role holds the release capability, so
     "Client: Approve & Issue" cannot quietly become something the supplier does.
  3. NO VERBAL OFFER IS VALID. Acceptance needs a written date and a joining date, both
     recorded against an offer that was actually released.
  4. REFERENCE CHECKS NEVER REACH A CLIENT. Section 15 shares the background check after
     joining; a referee's candid remarks are not part of that.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_offer   (from backend/)
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

    reqs = FakeCollection([
        # A mid-level role: no pre-offer reference required.
        {"cr_no": "CR-2026-001", "company_id": ACME, "role_title": "Backend Engineer",
         "role_level": M.ClientRoleLevel.MID.value,
         "salary_range_min": 900000, "salary_range_max": 1400000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
        # A managerial role: section 15's reference applies.
        {"cr_no": "CR-2026-002", "company_id": ACME, "role_title": "Delivery Manager",
         "role_level": M.ClientRoleLevel.MANAGERIAL.value,
         "salary_range_min": 2000000, "salary_range_max": 2600000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
        {"cr_no": "CR-2026-001", "company_id": GLOBEX, "role_title": "Support Lead",
         "role_level": M.ClientRoleLevel.MID.value,
         "salary_range_min": 500000, "salary_range_max": 800000,
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
    ])

    def cand(ccn, company, cr, name, status):
        return {"ccn_no": ccn, "company_id": company, "cr_no": cr,
                "candidate_name": name, "status": status, "created_at": NOW}

    candidates = FakeCollection([
        cand("CCN-2026-001", ACME, "CR-2026-001", "Nita Selected",
             M.ClientCandidateStatus.SELECTED.value),
        cand("CCN-2026-002", ACME, "CR-2026-001", "Dev Interviewing",
             M.ClientCandidateStatus.INTERVIEW.value),
        cand("CCN-2026-003", ACME, "CR-2026-002", "Maya Manager",
             M.ClientCandidateStatus.SELECTED.value),
        cand("CCN-2026-001", GLOBEX, "CR-2026-001", "Globex Person",
             M.ClientCandidateStatus.SELECTED.value),
    ])
    store = {M.COLL_CLIENT_REQUISITIONS: reqs,
             M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_CLIENT_OFFERS: FakeCollection(),
             M.COLL_CLIENT_REFERENCE_CHECKS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_offer_service as OF
    import app.services.hrms_client_interview_service as IV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (OF, IV, AUD, IDS, HA):
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
        check("the recruiter prepares the offer",
              HA.can(RECRUITER, M.Cap.CLIENT_OFFER_WRITE))
        check("...but does not verify it",
              not HA.can(RECRUITER, M.Cap.CLIENT_OFFER_VERIFY))
        check("the Team Lead verifies the paperwork",
              HA.can(TEAM_LEAD, M.Cap.CLIENT_OFFER_VERIFY))
        check("...and does not prepare it",
              not HA.can(TEAM_LEAD, M.Cap.CLIENT_OFFER_WRITE))
        check("the client issues the letter",
              HA.can(ACME_CLIENT, M.Cap.CLIENT_OFFER_RELEASE))
        check("NO Sparsh role can issue it",
              not any(M.Cap.CLIENT_OFFER_RELEASE in caps
                      for caps in M.ROLE_CAPABILITIES.values()))

        # =================================================================
        section("Reference checks never reach a client")
        # =================================================================
        check("the recruiter takes references",
              HA.can(RECRUITER, M.Cap.CLIENT_REFERENCE_WRITE))
        check("the client cannot read them",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_REFERENCE_READ))
        check("...nor record one",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_REFERENCE_WRITE))
        check("neither capability is on the ceiling",
              M.Cap.CLIENT_REFERENCE_READ not in M.CLIENT_TRACK_CAPS
              and M.Cap.CLIENT_REFERENCE_WRITE not in M.CLIENT_TRACK_CAPS)
        await expect_http(
            "a reference with no referee named",
            OF.record_client_reference(RECRUITER, ACME, {"ccn_no": "CCN-2026-003"}),
            422, "anonymous reference")
        await expect_http(
            "a negative reference with no note",
            OF.record_client_reference(RECRUITER, ACME,
                                       {"ccn_no": "CCN-2026-003",
                                        "referee_name": "A Referee",
                                        "outcome": "Negative"}),
            422, "record what was said")

        # =================================================================
        section("The client's selection is the gate in")
        # =================================================================
        await expect_http(
            "an offer for somebody still interviewing",
            OF.create_client_offer(RECRUITER, ACME,
                                   {"ccn_no": "CCN-2026-002", "offered_ctc": 1000000}),
            409, "section 16")

        made = await OF.create_client_offer(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-001", "offered_ctc": 1200000,
                              "joining_date": "2026-11-01",
                              "terms": "Standard terms."})
        COF = made["cof_no"]
        check("prepared for a selected candidate",
              made["status"] == M.ClientOfferStatus.DRAFT.value)
        check("the client's approved range is stamped on it",
              made["salary_range_min"] == 900000
              and made["salary_range_max"] == 1400000)
        await expect_http(
            "a second live offer for the same candidate",
            OF.create_client_offer(RECRUITER, ACME,
                                   {"ccn_no": "CCN-2026-001", "offered_ctc": 1}),
            409, "already has an offer")

        # =================================================================
        section("Section 16 -- the figure must sit inside the client's own range")
        # =================================================================
        state = await OF.offer_checkpoint(ACME, made)
        check("a figure inside the range passes the checkpoint", state["ready"])
        check("and no reference is required at mid level",
              state["reference"]["required"] is False)

        await OF.update_client_offer(RECRUITER, ACME, COF, {"offered_ctc": 1800000})
        over = await OF.get_client_offer(RECRUITER, ACME, COF)
        state = await OF.offer_checkpoint(ACME, over)
        check("a figure above it does not", not state["ready"])
        await expect_http(
            "submitting an offer outside the approved range",
            OF.act_on_client_offer(RECRUITER, ACME, COF, "submit-for-verification", {}),
            409, "outside the range the client approved")
        await OF.update_client_offer(RECRUITER, ACME, COF, {"offered_ctc": 1200000})

        # =================================================================
        section("Recruiter prepares, Team Lead verifies, client issues")
        # =================================================================
        await OF.act_on_client_offer(RECRUITER, ACME, COF, "submit-for-verification", {})
        row = await OF.get_client_offer(RECRUITER, ACME, COF)
        check("it goes to the Team Lead",
              row["status"] == M.ClientOfferStatus.PENDING_VERIFICATION.value)
        await expect_http(
            "...and can no longer be edited",
            OF.update_client_offer(RECRUITER, ACME, COF, {"offered_ctc": 1}),
            409, "cannot be edited")
        await expect_http(
            "the recruiter verifying their own paperwork",
            OF.act_on_client_offer(RECRUITER, ACME, COF, "verify", {}),
            403, "client_offer.verify")
        await expect_http(
            "the client opening an offer still inside Sparsh",
            OF.get_client_offer(ACME_CLIENT, ACME, COF), 404, "not found")

        await OF.act_on_client_offer(TEAM_LEAD, ACME, COF, "verify", {})
        row = await OF.get_client_offer(RECRUITER, ACME, COF)
        check("the Team Lead passes it to the client",
              row["status"] == M.ClientOfferStatus.PENDING_CLIENT_APPROVAL.value)
        seen = await OF.get_client_offer(ACME_CLIENT, ACME, COF)
        check("now the client can see it", seen["cof_no"] == COF)
        check("but not Sparsh's negotiation notes",
              "negotiation_notes" not in seen)

        await expect_http(
            "the Operations Head issuing the letter",
            OF.act_on_client_offer(OPS_HEAD, ACME, COF, "client-release", {}),
            403, "client_offer.release")

        released = await OF.act_on_client_offer(
            ACME_CLIENT, ACME, COF, "client-release", {})
        check("the client issues it",
              released["status"] == M.ClientOfferStatus.RELEASED.value)
        check("attributed to them",
              released["client_release"]["by_name"] == "Acme Talent Lead")
        moved = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                            "company_id": ACME})
        check("and the candidate shows Offer Released",
              moved["status"] == M.ClientCandidateStatus.OFFER_RELEASED.value)

        # =================================================================
        section("Section 17 -- no verbal offer is valid")
        # =================================================================
        await expect_http(
            "pre-boarding before an acceptance is on record",
            OF.assert_preboarding_allowed(ACME, "CCN-2026-001"), 409, "no verbal offer")
        await expect_http(
            "recording acceptance with no dates",
            OF.act_on_client_offer(RECRUITER, ACME, COF, "record-acceptance", {}),
            422, "verbal offer is not valid")
        await expect_http(
            "an acceptance date that is not a date",
            OF.act_on_client_offer(RECRUITER, ACME, COF, "record-acceptance",
                                   {"accepted_on": "soon",
                                    "joining_date": "2026-11-01"}),
            422, "valid yyyy-mm-dd")

        accepted = await OF.act_on_client_offer(
            RECRUITER, ACME, COF, "record-acceptance",
            {"accepted_on": "2026-10-10", "joining_date": "2026-11-03"})
        check("the recruiter records the written acceptance",
              accepted["status"] == M.ClientOfferStatus.ACCEPTED.value)
        check("with both dates",
              accepted["acceptance"]["accepted_on"] == "2026-10-10"
              and accepted["joining_date"] == "2026-11-03")
        opened = await OF.assert_preboarding_allowed(ACME, "CCN-2026-001")
        check("pre-boarding is now open", opened["cof_no"] == COF)
        after = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                            "company_id": ACME})
        check("and the candidate shows Offer Accepted",
              after["status"] == M.ClientCandidateStatus.OFFER_ACCEPTED.value)
        await expect_http(
            "a closed offer refuses further moves",
            OF.act_on_client_offer(RECRUITER, ACME, COF, "record-decline",
                                   {"remarks": "changed my mind"}),
            409, "closed")

        # =================================================================
        section("Section 15 -- a managerial role needs a reference first")
        # =================================================================
        mgr = await OF.create_client_offer(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-003", "offered_ctc": 2200000})
        MGR = mgr["cof_no"]
        state = await OF.offer_checkpoint(ACME, mgr)
        check("the checkpoint asks for a reference on a managerial role",
              state["reference"]["required"] is True and not state["ready"])
        await expect_http(
            "submitting it without one",
            OF.act_on_client_offer(RECRUITER, ACME, MGR, "submit-for-verification", {}),
            409, "reference check")

        await OF.record_client_reference(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-003", "referee_name": "Prior Boss",
                              "referee_organisation": "Previous Ltd",
                              "outcome": "Unable to Verify",
                              "remarks": "Company has closed; nobody to ask."})
        state = await OF.offer_checkpoint(ACME, mgr)
        check("an Unable to Verify reference does NOT clear it", not state["ready"])

        await OF.record_client_reference(
            RECRUITER, ACME, {"ccn_no": "CCN-2026-003", "referee_name": "Second Boss",
                              "outcome": "Positive", "remarks": "Would rehire."})
        state = await OF.offer_checkpoint(ACME, mgr)
        check("a positive one does", state["ready"])
        await OF.act_on_client_offer(RECRUITER, ACME, MGR, "submit-for-verification", {})
        row = await OF.get_client_offer(RECRUITER, ACME, MGR)
        check("and the offer moves on",
              row["status"] == M.ClientOfferStatus.PENDING_VERIFICATION.value)

        # =================================================================
        section("Returning clears the stamps")
        # =================================================================
        back = await OF.act_on_client_offer(
            TEAM_LEAD, ACME, MGR, "return",
            {"remarks": "Designation does not match the requisition."})
        check("the Team Lead returns it to draft",
              back["status"] == M.ClientOfferStatus.DRAFT.value)
        check("the reason survives, because it is the instruction to act on",
              back["verification"]["remarks"].startswith("Designation does not match"))
        check("and no stale client approval is left standing",
              back["client_release"] is None)
        check("the recruiter may edit it again",
              back["status"] in M.CLIENT_OFFER_EDITABLE)

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        elsewhere = await OF.create_client_offer(
            RECRUITER, GLOBEX, {"ccn_no": "CCN-2026-001", "offered_ctc": 600000})
        same_number = await OF.get_client_offer(RECRUITER, ACME, elsewhere["cof_no"])
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)
        mine = await OF.list_client_offers(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_offers"]))
        await expect_http(
            "a client-side caller with no company in scope",
            OF.list_client_offers(ACME_CLIENT, None), 403, "no company in scope")
        check("naming another company in the query is ignored",
              HA.scope_company_id(ACME_CLIENT, GLOBEX) == ACME)

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection", M.COLL_CLIENT_OFFERS != M.COLL_OFFERS)
        check("every action names a client-offer capability",
              all(spec[2].startswith("CLIENT_OFFER_")
                  for spec in M.CLIENT_OFFER_TRANSITIONS.values()))
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
