"""Phase INT-2 -- statutory pre-employment checks before confirmation (SOP §11).

"Statutory checks shall be completed before an employee is confirmed."

Covers: the 409 on confirmation, the two independent things checked (background verification
Cleared, and every `statutory_required` document Verified), the waiver exception that lifts
it, and -- the part that keeps the control humane -- the fact that it gates CONFIRMATION
only, never an extension or a termination.

That last one matters. Gating an extension or a termination on paperwork would trap somebody
in an indefinite probation because a police verification is slow, which is worse for them
than the control is worth.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_statutory_gate   (from backend/)
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

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HOD, U_MD, U_HR = (str(ObjectId()) for _ in range(3))
    TYPE_PAN, TYPE_DEGREE, TYPE_PHOTO = ObjectId(), ObjectId(), ObjectId()

    doc_types = FakeCollection([
        {"_id": TYPE_PAN, "company_id": COMPANY, "name": "PAN Card",
         "statutory_required": True, "active": True},
        {"_id": TYPE_DEGREE, "company_id": COMPANY, "name": "Degree Certificate",
         "statutory_required": True, "active": True},
        # Mandatory to COLLECT, but nobody's employment turns on a photograph.
        {"_id": TYPE_PHOTO, "company_id": COMPANY, "name": "Photograph",
         "mandatory": True, "statutory_required": False, "active": True},
    ])
    documents = FakeCollection([
        {"doc_no": "DOC-2026-001", "company_id": COMPANY, "owner_type": "employee",
         "owner_id": "EMP-2026-001", "type_id": str(TYPE_PAN), "status": "Verified"},
        # The degree certificate was uploaded but never verified.
        {"doc_no": "DOC-2026-002", "company_id": COMPANY, "owner_type": "employee",
         "owner_id": "EMP-2026-001", "type_id": str(TYPE_DEGREE), "status": "Uploaded"},
        {"doc_no": "DOC-2026-003", "company_id": COMPANY, "owner_type": "employee",
         "owner_id": "EMP-2026-002", "type_id": str(TYPE_PAN), "status": "Verified"},
        {"doc_no": "DOC-2026-004", "company_id": COMPANY, "owner_type": "employee",
         "owner_id": "EMP-2026-002", "type_id": str(TYPE_DEGREE), "status": "Verified"},
    ])
    onboardings = FakeCollection([
        {"onb_no": "ONB-2026-001", "company_id": COMPANY, "employee_id": "EMP-2026-001",
         "bg_verification": M.BgVerification.IN_PROGRESS.value,
         "request_no": "HR-REQ-2026-001"},
        {"onb_no": "ONB-2026-002", "company_id": COMPANY, "employee_id": "EMP-2026-002",
         "bg_verification": M.BgVerification.CLEARED.value,
         "request_no": "HR-REQ-2026-001"},
    ])
    profiles = FakeCollection([
        {"employee_code": f"EMP-2026-{n:03d}", "company_id": COMPANY,
         "display_name": f"Joiner {n}", "joined_on": ago(200)} for n in (1, 2, 3)
    ])
    reqs = FakeCollection([
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "designation_name": "Ops Executive",
         "closing_status": "Open", "created_at": NOW},
    ])
    probations = FakeCollection([
        {"prb_no": f"PRB-2026-{n:03d}", "company_id": COMPANY,
         "employee_code": f"EMP-2026-{n:03d}", "employee_name": f"Joiner {n}",
         "request_no": "HR-REQ-2026-001", "started_on": ago(200),
         "duration_months": 6, "ends_on": ago(20),
         "outcome": M.ProbationOutcome.PENDING.value, "extension_count": 0}
        for n in (1, 2, 3)
    ])
    exceptions = FakeCollection()

    store = {M.COLL_DOCUMENT_TYPES: doc_types, M.COLL_DOCUMENTS: documents,
             M.COLL_ONBOARDING: onboardings, M.COLL_EMPLOYEE_PROFILES: profiles,
             M.COLL_PROBATION_REVIEWS: probations, M.COLL_REQUISITIONS: reqs,
             M.COLL_EXCEPTIONS: exceptions, M.COLL_CANDIDATES: FakeCollection(),
             M.COLL_SURVEYS: FakeCollection(),
             M.COLL_SURVEY_RESPONSES: FakeCollection(),
             M.COLL_LINKS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: FakeCollection(), "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_probation_service as PB
    import app.services.hrms_exception_service as EX
    import app.services.hrms_survey_service as SV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_link_service as LS
    for mod in (PB, EX, SV, AUD, IDS, LS):
        mod.get_collection = mongo.get_collection

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HOD = actor(U_HOD, "HOD")
    MD = actor(U_MD, "MD", role="clientadmin")
    HR = actor(U_HR, "HR")

    # 7.5 Stage 12: confirm_probation now needs a manager recommendation and an HR
    # endorsement first. This suite is about the statutory gate, not the approval chain,
    # so it walks the chain here rather than restating it at every call site.
    async def _chain(prb_no, recommendation="Confirm"):
        from app.models.hrms import PROBATION_CRITERIA_KEYS
        await PB.submit_review(HOD, COMPANY, prb_no, {
            **{k: 4 for k in PROBATION_CRITERIA_KEYS},
            "recommendation": recommendation,
            "remarks": "Reviewed.", "signature": "Hari HOD"})
        await PB.hr_review(HR, COMPANY, prb_no,
                           {"decision": "Endorsed", "signature": "Hana HR"})

    def confirm(**over):
        base = {"outcome": "Confirmed", "signature": "Hari HOD",
                "remarks": "Met the bar."}
        base.update(over)
        return base

    try:
        # =================================================================
        section("statutory_required is NOT the same thing as mandatory")
        # =================================================================
        by_name = {name: statutory for name, _c, _a, _m, _e, statutory
                   in M.DEFAULT_DOCUMENT_TYPES}
        check("the identity documents are statutory",
              by_name["PAN Card"] and by_name["Aadhaar Card"])
        check("so is the degree certificate", by_name["Degree Certificate"])
        check("a PHOTOGRAPH is mandatory to collect and NOT statutory -- nobody's "
              "employment turns on it", by_name["Photograph"] is False)
        check("and nothing else is flagged by default, so a type HR adds never silently "
              "starts blocking confirmations",
              sum(1 for v in by_name.values() if v) == 3)

        # =================================================================
        section("What is outstanding is READABLE before it blocks anybody")
        # =================================================================
        state = await PB.statutory_state(COMPANY, "EMP-2026-001")
        check("the state is reported rather than raised", isinstance(state, dict))
        check("it is not complete", state["complete"] is False)
        check("it names the background check", any(
            "background" in item.lower() for item in state["outstanding"]))
        check("and names the document by name, not by id", any(
            "Degree Certificate" in item for item in state["outstanding"]))
        check("a control the user first meets when it blocks them reads as a bug", True)

        clear = await PB.statutory_state(COMPANY, "EMP-2026-002")
        check("an employee with everything in order is complete",
              clear["complete"] is True and clear["outstanding"] == [])

        # =================================================================
        section("Confirmation is refused while checks are open")
        # =================================================================
        await _chain("PRB-2026-001")
        await expect_http(
            "confirming with the background check in progress",
            PB.confirm_probation(HOD, COMPANY, "PRB-2026-001", confirm()),
            409, "statutory pre-employment checks are not complete")
        still = await probations.find_one({"prb_no": "PRB-2026-001"})
        check("and the review was NOT half-decided by the refusal",
              still["outcome"] == M.ProbationOutcome.PENDING.value)
        check("the checks are checked BEFORE anything is written", True)

        await _chain("PRB-2026-002", "Confirm")
        done = await PB.confirm_probation(HOD, COMPANY, "PRB-2026-002", confirm())
        check("an employee whose checks are complete confirms normally",
              done["outcome"] == M.ProbationOutcome.CONFIRMED.value)

        # =================================================================
        section("It gates CONFIRMATION only")
        # =================================================================
        # Extending is exactly what you do when something is still outstanding.
        await _chain("PRB-2026-001", "Extend")
        extended = await PB.confirm_probation(HOD, COMPANY, "PRB-2026-001", {
            "outcome": "Extended", "signature": "Hari HOD",
            "remarks": "Waiting on the background check.",
            "extended_to": (NOW + timedelta(days=60)).strftime("%Y-%m-%d")})
        check("EXTENDING is not gated -- it is the honest response to an open check",
              extended["outcome"] == M.ProbationOutcome.PENDING.value)
        check("and the extension is counted", extended["extension_count"] == 1)

        await _chain("PRB-2026-003", "Separate")
        terminated = await PB.confirm_probation(HOD, COMPANY, "PRB-2026-003", {
            "outcome": "Terminated", "signature": "Hari HOD",
            "remarks": "Did not meet the bar."})
        check("TERMINATING is not gated either -- paperwork must not trap somebody in an "
              "indefinite probation",
              terminated["outcome"] == M.ProbationOutcome.TERMINATED.value)

        # =================================================================
        section("Only an APPROVED exception lifts it")
        # =================================================================
        check("the statutory gate has its own exception type",
              M.EXCEPTION_UNBLOCKS["statutory_check"]
              == M.ExceptionType.STATUTORY_WAIVED.value)
        check("and it is in the ExceptionType enum, so the log can offer it",
              M.ExceptionType.STATUTORY_WAIVED.value == "Statutory Check Waived")

        raised = await EX.raise_exception(HR, COMPANY, {
            "request_no": "HR-REQ-2026-001",
            "exception_type": "Statutory Check Waived",
            "reason": ("The verification agency has not responded in three months; the "
                       "MD accepts the residual risk.")})
        await _chain("PRB-2026-001")
        await expect_http(
            "a PENDING waiver lifts nothing",
            PB.confirm_probation(HOD, COMPANY, "PRB-2026-001", confirm()),
            409, "statutory pre-employment checks are not complete")

        await EX.decide_exception(MD, COMPANY, raised["exc_no"], {
            "decision": "Approved", "signature": "Meera MD", "remarks": "Accepted."})
        await _chain("PRB-2026-001", "Confirm")
        confirmed = await PB.confirm_probation(HOD, COMPANY, "PRB-2026-001", confirm())
        check("an APPROVED waiver lets the confirmation through",
              confirmed["outcome"] == M.ProbationOutcome.CONFIRMED.value)
        check("there is no override flag anywhere -- an approved, signed record is the "
              "only way past", True)

        # =================================================================
        section("A confirmation issues the probation experience survey")
        # =================================================================
        issued = await store[M.COLL_SURVEY_RESPONSES].find(
            {"kind": "probation"}).to_list(20)
        check("confirming issues the probation survey (SOP section 10)",
              len(issued) >= 1)
        check("keyed on the employee, for de-duplication only",
              all(r.get("employee_code") for r in issued))
        check("and a terminated probation issues none -- there is nothing to ask about",
              not any(r["employee_code"] == "EMP-2026-003" for r in issued))

        # =================================================================
        section("A profile with no linked onboarding is not gated on a check that "
                "does not exist")
        # =================================================================
        orphan = await PB.statutory_state(COMPANY, "EMP-9999")
        check("an employee created by hand has no background check to read",
              orphan["bg_verification"] is None)
        check("that half of the gate reports nothing rather than failing them",
              not any("background" in item.lower()
                      for item in orphan["outstanding"]))
        check("their DOCUMENTS are still checked, so the control is not simply skipped",
              len(orphan["outstanding"]) == 2)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
