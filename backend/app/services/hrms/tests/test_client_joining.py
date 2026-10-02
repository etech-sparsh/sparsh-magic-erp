"""Client Hiring steps 8-9 -- pre-boarding, joining, handover, closure.

PRO-fit SOP sections 18, 19 and 20.

Four properties this file pins:

  1. PRE-BOARDING IS A LOG, NOT A GATE. Section 19 is engagement; nothing is blocked for
     want of a touchpoint. The at-risk flag is the one signal worth surfacing, and it
     tracks the LATEST contact rather than latching on forever.
  2. THE CLIENT CONFIRMS JOINING IN WRITING. Section 18. No Sparsh role can declare that
     somebody started, and the confirmation needs the real date and the candidate's own
     acknowledgement.
  3. CLOSURE FOLLOWS THE HANDOVER, AND ONLY THE HANDOVER. Section 20 closes the
     requisition "only after this handover", so closure is a consequence rather than a
     button, and the handover itself needs the four items section 20 names.
  4. THE CONTACT LOG STAYS AT SPARSH. What a candidate said about a counter-offer is a
     working note, not something to hand their future employer.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_joining   (from backend/)
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

HANDOVER = {"candidate_file": True, "scorecards": True,
            "interview_records": True, "verification_status": True,
            "handover_note": "Full file attached; BGV clear, culture score 4.2."}


async def main() -> None:
    from bson import ObjectId
    from datetime import datetime, timezone

    from app.models import hrms as M
    import app.db.mongodb as mongo

    NOW = datetime.now(timezone.utc)

    reqs = FakeCollection([
        {"cr_no": "CR-2026-001", "company_id": ACME, "role_title": "Backend Engineer",
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
        {"cr_no": "CR-2026-001", "company_id": GLOBEX, "role_title": "Support Lead",
         "status": M.ClientReqStatus.APPROVED.value, "created_at": NOW},
    ])

    def offer(cof, ccn, company, status, joining="2026-11-03"):
        return {"cof_no": cof, "ccn_no": ccn, "company_id": company,
                "cr_no": "CR-2026-001", "candidate_name": f"Person {ccn[-1]}",
                "joining_date": joining, "status": status, "created_at": NOW}

    offers = FakeCollection([
        offer("COF-2026-001", "CCN-2026-001", ACME,
              M.ClientOfferStatus.ACCEPTED.value),
        offer("COF-2026-002", "CCN-2026-002", ACME,
              M.ClientOfferStatus.RELEASED.value),
        offer("COF-2026-003", "CCN-2026-003", ACME,
              M.ClientOfferStatus.ACCEPTED.value),
        offer("COF-2026-001", "CCN-2026-001", GLOBEX,
              M.ClientOfferStatus.ACCEPTED.value),
    ])

    def cand(ccn, company):
        return {"ccn_no": ccn, "company_id": company, "cr_no": "CR-2026-001",
                "candidate_name": f"Person {ccn[-1]}",
                "status": M.ClientCandidateStatus.OFFER_ACCEPTED.value,
                "created_at": NOW}

    candidates = FakeCollection([cand("CCN-2026-001", ACME),
                                 cand("CCN-2026-002", ACME),
                                 cand("CCN-2026-003", ACME),
                                 cand("CCN-2026-001", GLOBEX)])
    store = {M.COLL_CLIENT_REQUISITIONS: reqs,
             M.COLL_CLIENT_OFFERS: offers,
             M.COLL_CLIENT_CANDIDATES: candidates,
             M.COLL_CLIENT_JOININGS: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_joining_service as JN
    import app.services.hrms_client_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (JN, OF, AUD, IDS, HA):
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

    try:
        # =================================================================
        section("Who may do what")
        # =================================================================
        check("the recruiter runs pre-boarding",
              HA.can(RECRUITER, M.Cap.CLIENT_JOINING_MANAGE))
        check("...but cannot declare somebody joined",
              not HA.can(RECRUITER, M.Cap.CLIENT_JOINING_CONFIRM))
        check("...nor sign off the handover",
              not HA.can(RECRUITER, M.Cap.CLIENT_JOINING_HANDOVER))
        check("the client confirms joining",
              HA.can(ACME_CLIENT, M.Cap.CLIENT_JOINING_CONFIRM))
        check("the Team Lead signs off the handover",
              HA.can(TEAM_LEAD, M.Cap.CLIENT_JOINING_HANDOVER))
        check("NO Sparsh role can confirm joining",
              not any(M.Cap.CLIENT_JOINING_CONFIRM in caps
                      for caps in M.ROLE_CAPABILITIES.values()))
        check("the client cannot run pre-boarding contact",
              not HA.can(ACME_CLIENT, M.Cap.CLIENT_JOINING_MANAGE))

        # =================================================================
        section("A written acceptance is the gate in")
        # =================================================================
        await expect_http(
            "opening pre-boarding on a released-but-unaccepted offer",
            JN.open_client_joining(RECRUITER, ACME, {"ccn_no": "CCN-2026-002"}),
            409, "no verbal offer")

        made = await JN.open_client_joining(RECRUITER, ACME, {"ccn_no": "CCN-2026-001"})
        CJN = made["cjn_no"]
        check("pre-boarding opens",
              made["status"] == M.ClientJoiningStatus.PRE_BOARDING.value)
        check("carrying the joining date from the accepted offer",
              made["joining_date"] == "2026-11-03")
        moved = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                            "company_id": ACME})
        check("and the candidate shows Pre-boarding",
              moved["status"] == M.ClientCandidateStatus.PRE_BOARDING.value)
        await expect_http(
            "opening it twice",
            JN.open_client_joining(RECRUITER, ACME, {"ccn_no": "CCN-2026-001"}),
            409, "already in pre-boarding")

        # =================================================================
        section("Pre-boarding is a log, and the risk flag is the latest reading")
        # =================================================================
        await expect_http(
            "flagging somebody at risk with no note",
            JN.record_touchpoint(RECRUITER, ACME, CJN, {"at_risk": True}),
            422, "say what they said")

        await JN.record_touchpoint(RECRUITER, ACME, CJN,
                                   {"channel": "Call", "notes": "All on track."})
        row = await JN.get_client_joining(RECRUITER, ACME, CJN)
        check("a touchpoint is logged", len(row["touchpoints"]) == 1)
        check("and nothing is at risk", row["at_risk"] is False)

        await JN.record_touchpoint(RECRUITER, ACME, CJN,
                                   {"channel": "Call", "at_risk": True,
                                    "notes": "Counter-offer from current employer."})
        row = await JN.get_client_joining(RECRUITER, ACME, CJN)
        check("a wobble raises the flag", row["at_risk"] is True)
        listed = await JN.list_client_joinings(RECRUITER, ACME)
        check("and the worklist counts it", listed["at_risk"] == 1)

        await JN.record_touchpoint(RECRUITER, ACME, CJN,
                                   {"channel": "Call",
                                    "notes": "Turned the counter-offer down."})
        row = await JN.get_client_joining(RECRUITER, ACME, CJN)
        check("talking them round clears it again, rather than latching",
              row["at_risk"] is False)
        check("while every contact stays on the log", len(row["touchpoints"]) == 3)

        # =================================================================
        section("The contact log stays at Sparsh")
        # =================================================================
        theirs = await JN.get_client_joining(ACME_CLIENT, ACME, CJN)
        check("the client follows their joiner", theirs["cjn_no"] == CJN)
        check("but never reads the contact log", "touchpoints" not in theirs)
        check("nor who inside Sparsh opened it", "opened_by_name" not in theirs)

        # =================================================================
        section("Section 18 -- the client confirms joining, in writing")
        # =================================================================
        await expect_http(
            "the recruiter declaring somebody joined",
            JN.act_on_client_joining(RECRUITER, ACME, CJN, "confirm-joining",
                                     {"actual_joining_date": "2026-11-03",
                                      "acknowledged": True}),
            403, "client_joining.confirm")
        await expect_http(
            "confirming with no actual start date",
            JN.act_on_client_joining(ACME_CLIENT, ACME, CJN, "confirm-joining",
                                     {"acknowledged": True}),
            422, "confirms nothing")
        await expect_http(
            "confirming without the candidate's acknowledgement",
            JN.act_on_client_joining(ACME_CLIENT, ACME, CJN, "confirm-joining",
                                     {"actual_joining_date": "2026-11-04"}),
            422, "acknowledgement")

        joined = await JN.act_on_client_joining(
            ACME_CLIENT, ACME, CJN, "confirm-joining",
            {"actual_joining_date": "2026-11-04", "acknowledged": True})
        check("the client confirms it",
              joined["status"] == M.ClientJoiningStatus.JOINED.value)
        check("with the real start date, not the planned one",
              joined["actual_joining_date"] == "2026-11-04")
        check("attributed to the client",
              joined["joining_confirmation"]["by_name"] == "Acme Talent Lead")
        after = await candidates.find_one({"ccn_no": "CCN-2026-001",
                                            "company_id": ACME})
        check("and the candidate shows Joined",
              after["status"] == M.ClientCandidateStatus.JOINED.value)

        # =================================================================
        section("Section 20 -- closure follows the handover, and only the handover")
        # =================================================================
        req = await reqs.find_one({"cr_no": "CR-2026-001", "company_id": ACME})
        check("the requisition is still open",
              req["status"] == M.ClientReqStatus.APPROVED.value)
        await expect_http(
            "handing over an empty file",
            JN.act_on_client_joining(TEAM_LEAD, ACME, CJN, "share-handover", {}),
            422, "still needed")
        await expect_http(
            "the recruiter signing off the handover",
            JN.act_on_client_joining(RECRUITER, ACME, CJN, "share-handover", {}),
            403, "client_joining.handover")

        await JN.update_client_joining(RECRUITER, ACME, CJN,
                                       {**HANDOVER, "culture_score": 4.2,
                                        "background_check_result": "Clear."})
        done = await JN.act_on_client_joining(TEAM_LEAD, ACME, CJN,
                                              "share-handover", {})
        check("the Team Lead completes the handover",
              done["status"] == M.ClientJoiningStatus.COMPLETED.value)
        closed = await reqs.find_one({"cr_no": "CR-2026-001", "company_id": ACME})
        check("and THAT is what closes the requisition",
              closed["status"] == M.ClientReqStatus.CLOSED.value)
        check("the post-joining results reached the client",
              (await JN.get_client_joining(ACME_CLIENT, ACME, CJN))["culture_score"]
              == 4.2)
        await expect_http(
            "a completed record refuses further moves",
            JN.act_on_client_joining(ACME_CLIENT, ACME, CJN, "confirm-joining",
                                     {"actual_joining_date": "2026-12-01",
                                      "acknowledged": True}),
            409, "closed")
        await expect_http(
            "...and cannot be edited",
            JN.update_client_joining(RECRUITER, ACME, CJN, {"culture_score": 1}),
            409, "closed")

        # =================================================================
        section("A drop-out ends it, with a reason")
        # =================================================================
        two = await JN.open_client_joining(RECRUITER, ACME, {"ccn_no": "CCN-2026-003"})
        await expect_http(
            "recording a drop with no reason",
            JN.act_on_client_joining(RECRUITER, ACME, two["cjn_no"],
                                     "record-drop", {}),
            422, "lesson nobody learns")
        dropped = await JN.act_on_client_joining(
            RECRUITER, ACME, two["cjn_no"], "record-drop",
            {"remarks": "Accepted a counter-offer three days before joining."})
        check("the drop is recorded",
              dropped["status"] == M.ClientJoiningStatus.DROPPED.value)
        gone = await candidates.find_one({"ccn_no": "CCN-2026-003",
                                           "company_id": ACME})
        check("the candidate shows Dropped Out",
              gone["status"] == M.ClientCandidateStatus.DROPPED.value)
        check("which is a closed candidate stage",
              M.ClientCandidateStatus.DROPPED.value in M.CLIENT_CANDIDATE_CLOSED)
        await expect_http(
            "no more touchpoints after a drop",
            JN.record_touchpoint(RECRUITER, ACME, two["cjn_no"], {"notes": "hello"}),
            409, "between acceptance and day 1")

        # =================================================================
        section("Tenant isolation")
        # =================================================================
        elsewhere = await JN.open_client_joining(RECRUITER, GLOBEX,
                                                 {"ccn_no": "CCN-2026-001"})
        same_number = await JN.get_client_joining(RECRUITER, ACME,
                                                  elsewhere["cjn_no"])
        check("the same number in another tenant resolves to your own row",
              same_number["company_id"] == ACME)
        mine = await JN.list_client_joinings(ACME_CLIENT, ACME)
        check("a client lists only their own company's",
              all(r["company_id"] == ACME for r in mine["client_joinings"]))
        await expect_http(
            "a client-side caller with no company in scope",
            JN.list_client_joinings(ACME_CLIENT, None), 403, "no company in scope")
        globex_req = await reqs.find_one({"cr_no": "CR-2026-001",
                                           "company_id": GLOBEX})
        check("closing one tenant's requisition left the other's alone",
              globex_req["status"] == M.ClientReqStatus.APPROVED.value)

        # =================================================================
        section("Internal Hiring is a different track")
        # =================================================================
        check("its own collection",
              M.COLL_CLIENT_JOININGS != M.COLL_ONBOARDING)
        check("every action names a client-joining capability",
              all(spec[2].startswith("CLIENT_JOINING_")
                  for spec in M.CLIENT_JOINING_TRANSITIONS.values()))
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
