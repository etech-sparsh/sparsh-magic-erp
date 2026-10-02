"""Phase INT-9 -- record-level notifications (spec §38, Annexure B).

The requisition approval chain always notified (25 call sites); the scorecard, reference,
probation and exception services emitted NOTHING -- so "scorecard approval required",
"probation confirmation required" and "exception approval required" never reached anybody,
and a gate could stay shut with no visible reason.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. THE RIGHT PEOPLE, PER ANNEXURE B. The HOD is addressed as the requisition's raiser (a
     person), Management and HR as roles. "I" in the RACI is in-app; a decision awaited is
     email.
  2. ONE EVENT, ONE NOTIFICATION. Signing twice, editing remarks, re-deciding -- none of
     them fire twice.
  3. NON-EVENTS ARE SILENT. A Positive reference notifies nobody; a partial approval does
     not announce completion.
  4. AN EXTENSION RE-ARMS THE SCHEDULER'S TIERS. The INT-3 reminder tiers are recorded as
     fired on the record; without clearing them an extended probation would never be
     reminded about its new end date.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int9_notifications   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402


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

C1 = "COMPANY-ONE"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    HOD_ID = str(ObjectId())
    HR_USER = {"_id": ObjectId(), "full_name": "Priya HR", "email": "hr@example.com",
               "_source_collection": "learners", "role": "clientuser",
               "governance_role": "HR", "company_id": C1}
    HOD_USER = {"_id": ObjectId(HOD_ID), "full_name": "Meera HOD",
                "_source_collection": "learners", "role": "clientuser",
                "governance_role": "HOD", "company_id": C1}
    MD_USER = {"_id": ObjectId(), "full_name": "Anita MD",
               "_source_collection": "learners", "role": "clientadmin",
               "company_id": C1}

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_reference_service as RF
    import app.services.hrms_probation_service as PR
    import app.services.hrms_exception_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_config_service as CFG
    for mod in (SC, RF, PR, EX, AUD, CFG):
        mod.get_collection = mongo.get_collection

    seq = {"n": 0}

    async def fake_id(kind, company_id, year=None):
        seq["n"] += 1
        return f"{kind.upper()[:3]}-2026-{seq['n']:03d}"

    for mod in (SC, RF, PR, EX):
        mod.next_business_id = fake_id

    # ── Notification capture: patch the FACADE, which every service imports late ──
    sent: list = []

    async def fake_user(user_id, title, message, kind="info", link=None, email=False):
        sent.append({"to": ("user", str(user_id)), "title": title, "message": message,
                     "kind": kind, "email": email})

    async def fake_role(company_id, roles, title, message, kind="info", link=None,
                        email=False, exclude_user_ids=None):
        sent.append({"to": ("role", ",".join(roles)), "title": title, "message": message,
                     "kind": kind, "email": email,
                     "excluded": [str(u) for u in (exclude_user_ids or [])]})

    import app.services.hrms_notify_service as NOTIFY
    NOTIFY.notify_user = fake_user
    NOTIFY.notify_hrms_role = fake_role

    def to_roles():
        return [n["to"][1] for n in sent if n["to"][0] == "role"]

    def to_users():
        return [n["to"][1] for n in sent if n["to"][0] == "user"]

    # ── Fixtures ─────────────────────────────────────────────────────────────
    INT = "internal"
    DESIG_MGR, DESIG_PLAIN = str(ObjectId()), str(ObjectId())
    store.setdefault(M.COLL_DESIGNATIONS, FakeCollection()).docs.extend([
        {"_id": DESIG_MGR, "company_id": C1, "name": "Ops Head",
         "designation_level": M.DesignationLevel.MANAGERIAL.value},
        {"_id": DESIG_PLAIN, "company_id": C1, "name": "Ops Executive"},
    ])
    store.setdefault(M.COLL_REQUISITIONS, FakeCollection()).docs.extend([
        {"request_no": "R-PLAIN", "company_id": C1, "requisition_track": INT,
         "designation_name": "Ops Executive", "designation_id": DESIG_PLAIN,
         "created_by": HOD_ID, "closing_status": "Open", "created_at": NOW},
        {"request_no": "R-MGR", "company_id": C1, "requisition_track": INT,
         "designation_name": "Ops Head", "designation_id": DESIG_MGR,
         "created_by": HOD_ID, "closing_status": "Open", "created_at": NOW},
        {"request_no": "R-MGR2", "company_id": C1, "requisition_track": INT,
         "designation_name": "Ops Director", "designation_id": DESIG_MGR,
         "created_by": HOD_ID, "closing_status": "Open", "created_at": NOW},
    ])
    # The scorecard service resolves the raiser's ROLE before asking them to approve
    # (verification finding D6): an approval request sent to somebody who cannot approve
    # is a dead letter. So the HOD must exist as a resolvable learner.
    store.setdefault("learners", FakeCollection()).docs.append(dict(HOD_USER))

    store.setdefault(M.COLL_CANDIDATES, FakeCollection()).docs.append(
        {"uk": "CAN-001", "company_id": C1, "candidate_name": "Asha K",
         "request_no": "R-PLAIN", "application_status": M.AppStatus.SELECTED.value})
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-001", "display_name": "Asha K",
         "joined_on": "2026-08-01", "request_no": "R-PLAIN"})

    # =========================================================================
    section("1. Scorecard -- approval required reaches the HOD (and MD when managerial)")
    # =========================================================================
    sent.clear()
    plain = await SC.create_scorecard(HR_USER, C1, {
        "request_no": "R-PLAIN",
        "criteria": [{"label": "Process", "category": "skill", "weight": 3}]})
    check("the HOD (the requisition's raiser) is told, as a person, by email",
          to_users() == [HOD_ID] and sent[0]["email"] is True)
    check("Management is NOT told about an ordinary role's scorecard",
          not any("MD" in r for r in to_roles()))

    sent.clear()
    mgr = await SC.create_scorecard(HR_USER, C1, {
        "request_no": "R-MGR", "managerial": True,
        "criteria": [{"label": "Leadership", "category": "culture_fit", "weight": 3}]})
    check("a MANAGERIAL scorecard also tells Management, as a role",
          to_users() == [HOD_ID] and "MD" in ",".join(to_roles()))

    # -- Partial approval chases who is still owed; completion announces to HR --
    sent.clear()
    await SC.approve_scorecard(HOD_USER, C1, mgr["scr_no"],
                               {"signature": "Meera HOD", "decision": "Pass"})
    check("the hiring manager's signature on a managerial card chases MANAGEMENT, and "
          "announces completion to nobody",
          to_roles() == ["MD"]
          and not any("fully approved" in n["title"] for n in sent))

    sent.clear()
    await SC.approve_scorecard(MD_USER, C1, mgr["scr_no"],
                               {"signature": "Anita MD", "decision": "Pass"})
    check("the completing signature announces to HR, once, by email",
          to_roles() == ["HR"]
          and sum(1 for n in sent if "fully approved" in n["title"]) == 1
          and sent[0]["email"] is True)

    # -- A RE-SIGN that changes nothing says nothing (verification finding D1) --
    sent.clear()
    await expect_http(
        "signing an already-approved card",
        SC.approve_scorecard(HOD_USER, C1, mgr["scr_no"],
                             {"signature": "Meera HOD", "decision": "Pass"}),
        409, "already approved")
    check("and the refusal notified nobody", sent == [])
    # The re-sign case that matters is the PARTIAL one, on a fresh managerial card.
    mgr2 = await SC.create_scorecard(HR_USER, C1, {
        "request_no": "R-MGR2", "managerial": True,
        "criteria": [{"label": "Judgement", "category": "culture_fit", "weight": 2}]})
    sent.clear()
    await SC.approve_scorecard(HOD_USER, C1, mgr2["scr_no"],
                               {"signature": "Meera HOD", "decision": "Pass"})
    check("the FIRST partial signature chases Management", to_roles() == ["MD"])
    sent.clear()
    await SC.approve_scorecard(HOD_USER, C1, mgr2["scr_no"],
                               {"signature": "Meera HOD", "decision": "Pass"})
    check("RE-SIGNING the same partial card says NOTHING -- the state did not move, so "
          "the chase does not repeat (the property the docstring promises)", sent == [])

    # -- Rejection tells the drafter and HR --
    sent.clear()
    await SC.approve_scorecard(HOD_USER, C1, plain["scr_no"],
                               {"signature": "Meera HOD", "decision": "Fail",
                                "remarks": "Weights ignore process discipline."})
    check("sent back: the drafter is told directly and HR as a role, with the reason",
          str(HR_USER["_id"]) in to_users() and "HR" in to_roles()
          and all("Weights ignore" in n["message"] for n in sent))
    check("the drafter is EXCLUDED from the HR fan-out -- told by name, not twice",
          any(str(HR_USER["_id"]) in n.get("excluded", []) for n in sent
              if n["to"][0] == "role"))

    # -- A second Fail is refused, so nothing can repeat (verification finding D1) --
    sent.clear()
    await expect_http(
        "failing an already-rejected scorecard",
        SC.approve_scorecard(MD_USER, C1, plain["scr_no"],
                             {"signature": "Anita MD", "decision": "Fail",
                              "remarks": "Still wrong."}),
        409, "already sent back")
    check("and the refusal notified nobody", sent == [])

    # -- Editing the sent-back card RE-QUEUES it, and says so (finding D7) --
    sent.clear()
    await SC.update_scorecard(HR_USER, C1, plain["scr_no"],
                              {"notes": "Weights rebalanced per feedback."})
    check("answering the feedback puts the card back in the queue and re-asks the "
          "approver -- a silent re-queue strands it exactly as staying Rejected would",
          to_users() == [HOD_ID]
          and any("again" in n["title"] for n in sent))

    # =========================================================================
    section("2. Reference -- only a NON-clearing outcome says anything")
    # =========================================================================
    sent.clear()
    await RF.create_reference_check(HR_USER, C1, {
        "uk": "CAN-001", "referee_name": "Former Manager", "outcome": "Positive"})
    check("a Positive reference is silent -- the recorder is HR and the gate opens "
          "without ceremony", sent == [])

    sent.clear()
    neg = await RF.create_reference_check(HR_USER, C1, {
        "uk": "CAN-001", "referee_name": "Second Referee", "outcome": "Negative",
        "remarks": "Would not rehire."})
    check("a Negative one warns HR, in-app only, and names the way forward",
          to_roles() == ["HR"] and sent[0]["email"] is False
          and "exception" in sent[0]["message"].lower())

    sent.clear()
    await RF.update_reference_check(HR_USER, C1, neg["ref_no"],
                                    {"remarks": "Would not rehire; confirmed twice."})
    check("editing REMARKS on an already-negative reference does not nag again",
          sent == [])

    sent.clear()
    await RF.update_reference_check(HR_USER, C1, neg["ref_no"],
                                    {"outcome": "Unable to Verify",
                                     "remarks": "Number now unreachable."})
    check("flipping the outcome to another non-clearing one fires once",
          len(sent) == 1 and to_roles() == ["HR"])

    # -- The warning is INTERNAL-track only (verification finding D2): a client-track
    # candidate has no internal offer gate, and the waiver the message recommends would
    # be refused by raise_exception. Warning HR about a consequence that does not exist,
    # with a remedy the system rejects, is worse than silence.
    store[M.COLL_REQUISITIONS].docs.append(
        {"request_no": "R-CLIENT", "company_id": C1, "designation_name": "Client Role",
         "created_at": NOW, "closing_status": "Open"})
    store[M.COLL_CANDIDATES].docs.append(
        {"uk": "CAN-CLI", "company_id": C1, "candidate_name": "Client Candidate",
         "request_no": "R-CLIENT", "application_status": M.AppStatus.SELECTED.value})
    sent.clear()
    await RF.create_reference_check(HR_USER, C1, {
        "uk": "CAN-CLI", "referee_name": "Somebody", "outcome": "Negative",
        "remarks": "Poor feedback."})
    check("a Negative reference on a CLIENT-track candidate notifies nobody",
          sent == [])

    # =========================================================================
    section("3. Probation -- opened, decided, and the extension re-arms the tiers")
    # =========================================================================
    async def no_statutory(company_id, employee):
        return None
    PR.assert_statutory_checks_complete = no_statutory

    # 7.5 Stage 12: confirm_probation now needs a manager recommendation and an HR
    # endorsement first. This suite is about which notifications fire, so the chain's own
    # notifications are trimmed back off `sent` -- otherwise every assertion below would
    # be measuring this helper rather than the thing it is testing.
    async def _chain(prb_no, recommendation="Confirm"):
        from app.models.hrms import PROBATION_CRITERIA_KEYS
        mark = len(sent)
        await PR.submit_review(HOD_USER, C1, prb_no, {
            **{k: 4 for k in PROBATION_CRITERIA_KEYS},
            "recommendation": recommendation,
            "remarks": "Reviewed.", "signature": "Meera HOD"})
        await PR.hr_review(HR_USER, C1, prb_no,
                           {"decision": "Endorsed", "signature": "Priya HR"})
        del sent[mark:]

    async def no_survey(actor, company_id, kind, **kw):
        return None
    import app.services.hrms_survey_service as SV
    SV.issue_survey = no_survey

    sent.clear()
    prb = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-001", "started_on": "2026-08-01",
        "duration_months": 6, "reviewer_id": HOD_ID})
    check("opening tells the reviewer they own it, in-app only -- the scheduler's tiers "
          "are the ones that email",
          to_users() == [HOD_ID] and sent[0]["email"] is False)

    # -- Extension: back to Pending, tiers cleared, HR informed --
    prb_coll = store[M.COLL_PROBATION_REVIEWS]
    await prb_coll.update_one({"prb_no": prb["prb_no"]},
                              {"$set": {M.PROBATION_REMINDED_FIELD: [30, 15]}})
    sent.clear()
    await _chain(prb["prb_no"], "Extend")
    await PR.confirm_probation(HOD_USER, C1, prb["prb_no"], {
        "signature": "Meera HOD", "outcome": "Extended",
        "extended_to": "2027-05-01", "remarks": "Targets need one more quarter."})
    row = await prb_coll.find_one({"prb_no": prb["prb_no"]})
    check("an extension re-arms the INT-3 reminder tiers -- without this the new end date "
          "would never be reminded about, its tiers already burned",
          row.get(M.PROBATION_REMINDED_FIELD) == [])
    check("and HR is told the review returns to Pending",
          to_roles() == ["HR"] and "Pending" in sent[0]["message"])
    check("Management hears nothing about an extension -- it is not a standing decision",
          not any("MD" in r for r in to_roles()))

    # -- Confirmation: HR by email; MD informed only when managerial --
    sent.clear()
    await _chain(prb["prb_no"], "Confirm")
    await PR.confirm_probation(HOD_USER, C1, prb["prb_no"], {
        "signature": "Meera HOD", "outcome": "Confirmed"})
    check("confirmation (non-managerial role) tells HR by email, and NOT Management",
          to_roles() == ["HR"] and sent[0]["email"] is True)

    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-002", "display_name": "Vikram S",
         "joined_on": "2026-08-01", "request_no": "R-MGR"})
    prb2 = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-002", "started_on": "2026-08-01",
        "duration_months": 6})
    sent.clear()
    await _chain(prb2["prb_no"], "Confirm")
    await PR.confirm_probation(HOD_USER, C1, prb2["prb_no"], {
        "signature": "Meera HOD", "outcome": "Confirmed"})
    md_notes = [n for n in sent if "MD" in n["to"][1]]
    check("a MANAGERIAL confirmation additionally INFORMS Management -- in-app, no email, "
          "which is what 'I' in the RACI means",
          len(md_notes) == 1 and md_notes[0]["email"] is False)
    check("HR is still the one told by email",
          any(n["to"][1] == "HR" and n["email"] for n in sent))

    # -- Termination: HR warned by email --
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-003", "display_name": "Rahul T",
         "joined_on": "2026-08-01", "request_no": "R-PLAIN"})
    prb3 = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-003", "started_on": "2026-08-01",
        "duration_months": 3})
    sent.clear()
    await _chain(prb3["prb_no"], "Separate")
    await PR.confirm_probation(HOD_USER, C1, prb3["prb_no"], {
        "signature": "Meera HOD", "outcome": "Terminated",
        "remarks": "Did not meet the agreed targets."})
    check("a termination warns HR by email, carrying the reason",
          to_roles() == ["HR"] and sent[0]["email"] is True
          and "Did not meet" in sent[0]["message"])
    check("a NON-managerial termination does not reach Management",
          not any("MD" in r for r in to_roles()))

    # -- A MANAGERIAL termination informs Management too (finding D3): it stands just as
    # a confirmation does, and ending a managerial hire is not less their business.
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-004", "display_name": "Kiran M",
         "joined_on": "2026-08-01", "request_no": "R-MGR"})
    prb4 = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-004", "started_on": "2026-08-01",
        "duration_months": 6})
    sent.clear()
    await _chain(prb4["prb_no"], "Separate")
    await PR.confirm_probation(HOD_USER, C1, prb4["prb_no"], {
        "signature": "Meera HOD", "outcome": "Terminated",
        "remarks": "Leadership expectations not met."})
    md_term = [n for n in sent if "MD" in n["to"][1]]
    check("a MANAGERIAL termination additionally informs Management, in-app",
          len(md_term) == 1 and md_term[0]["email"] is False)

    # -- The confirmed message states only what happened (finding D4) --
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-005", "display_name": "No Req",
         "joined_on": "2026-08-01"})
    prb5 = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-005", "started_on": "2026-08-01",
        "duration_months": 3})
    sent.clear()
    await _chain(prb5["prb_no"], "Confirm")
    await PR.confirm_probation(HOD_USER, C1, prb5["prb_no"], {
        "signature": "Meera HOD", "outcome": "Confirmed"})
    hr_note = next(n for n in sent if n["to"][1] == "HR")
    check("confirming a review with NO requisition omits 'the requisition is closed' -- "
          "the message must not describe a write that never happened",
          "requisition is closed" not in hr_note["message"])

    # -- Moving the end date through PATCH re-arms the tiers (finding D8) --
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": C1, "employee_code": "EMP-2026-006", "display_name": "Patched",
         "joined_on": "2026-08-01", "request_no": "R-PLAIN"})
    prb6 = await PR.open_probation(HR_USER, C1, {
        "employee_code": "EMP-2026-006", "started_on": "2026-08-01",
        "duration_months": 3})
    await prb_coll.update_one({"prb_no": prb6["prb_no"]},
                              {"$set": {M.PROBATION_REMINDED_FIELD: [30, 15]}})
    await PR.update_probation(HR_USER, C1, prb6["prb_no"], {"duration_months": 6})
    row6 = await prb_coll.find_one({"prb_no": prb6["prb_no"]})
    check("a PATCH that moves ends_on re-arms the reminder tiers -- the sibling path of "
          "the extension fix, reachable without a decision",
          row6.get(M.PROBATION_REMINDED_FIELD) == [])
    before = dict(row6)
    await PR.update_probation(HR_USER, C1, prb6["prb_no"], {"notes": "No date change."})
    row6b = await prb_coll.find_one({"prb_no": prb6["prb_no"]})
    check("a PATCH that does NOT move ends_on leaves the tiers alone",
          M.PROBATION_REMINDED_FIELD in row6b
          and row6b.get("ends_on") == before.get("ends_on"))

    # -- Handing the review to a new reviewer tells them (finding D11) --
    NEW_REVIEWER = str(ObjectId())
    sent.clear()
    await PR.update_probation(HR_USER, C1, prb6["prb_no"],
                              {"reviewer_id": NEW_REVIEWER})
    check("a reassigned review tells the NEW reviewer it is now theirs, in-app",
          to_users() == [NEW_REVIEWER] and sent[0]["email"] is False)
    sent.clear()
    await PR.update_probation(HR_USER, C1, prb6["prb_no"],
                              {"reviewer_id": NEW_REVIEWER})
    check("re-saving the same reviewer says nothing", sent == [])

    # =========================================================================
    section("4. Exceptions -- the approvers are told, then the raiser")
    # =========================================================================
    sent.clear()
    exc = await EX.raise_exception(HR_USER, C1, {
        "request_no": "R-PLAIN", "uk": "CAN-001",
        "exception_type": "Reference Check Waived",
        "reason": "Referee organisation has closed; two attempts made."})
    check("raising tells BOTH roles that hold exception.approve, by email",
          to_roles() == ["MD,FINANCE"] and sent[0]["email"] is True)
    check("and the message carries the type, the scope and the reason",
          "Reference Check Waived" in sent[0]["message"]
          and "Asha K" in sent[0]["message"]
          and "organisation has closed" in sent[0]["message"])

    sent.clear()
    await EX.decide_exception(MD_USER, C1, exc["exc_no"], {
        "signature": "Anita MD", "decision": "Approved"})
    check("approval tells the raiser, by email, naming the gate it lifts",
          to_users() == [str(HR_USER["_id"])] and sent[0]["email"] is True
          and "reference check" in sent[0]["message"].lower())

    sent.clear()
    exc2 = await EX.raise_exception(HR_USER, C1, {
        "request_no": "R-PLAIN", "exception_type": "Extended TAT",
        "reason": "Niche skill set; the market is thin."})
    sent.clear()
    await EX.decide_exception(MD_USER, C1, exc2["exc_no"], {
        "signature": "Anita MD", "decision": "Rejected",
        "remarks": "Re-scope the role instead."})
    check("rejection tells the raiser WHY, which the validation insisted on recording",
          to_users() == [str(HR_USER["_id"])]
          and "Re-scope the role" in sent[0]["message"])

    # =========================================================================
    section("5. The concurrency filters the verification workflow demanded")
    # =========================================================================
    import inspect as _insp
    sc_src = _insp.getsource(SC.approve_scorecard)
    check("the scorecard approval write is a compare-and-swap on the approvals array it "
          "merged from -- two simultaneous signatures cannot silently drop one",
          '"approvals": current.get("approvals")' in sc_src
          and "matched_count == 0" in sc_src)
    pr_src = _insp.getsource(PR.confirm_probation)
    check("the probation decision write is a compare-and-swap on the Pending state -- "
          "two deciders cannot both land",
          "ProbationOutcome.PENDING.value" in pr_src.split("$set")[0].rsplit(
              "update_one", 1)[-1] or '"outcome": ProbationOutcome.PENDING.value' in pr_src)
    import app.services.hrms_scheduler_service as SCH
    sch_src = _insp.getsource(SCH.run_probation_reminders)
    check("the scheduler's tier burn is conditioned on the end date and Pending state it "
          "computed from -- a concurrent extension's re-arm survives the sweep",
          '"ends_on": row.get("ends_on")' in sch_src
          and "ProbationOutcome.PENDING.value" in sch_src)

    # =========================================================================
    section("6. Structure -- late imports, so seeds and tests can silence everything")
    # =========================================================================
    import inspect
    for mod, name in ((SC, "scorecard"), (RF, "reference"), (PR, "probation"),
                      (EX, "exception")):
        src = inspect.getsource(mod)
        head = src[:src.index("\nasync def")]
        check(f"the {name} service imports the notify facade INSIDE functions, not at "
              f"module top -- the pattern that lets seed scripts patch it out",
              "hrms_notify_service" not in head)

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
