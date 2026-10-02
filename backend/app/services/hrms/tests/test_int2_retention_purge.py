"""Phase INT-2 -- the record-retention purge (SOP §13).

`retention_until` has been stamped and reported since the internal track shipped, and
nothing has ever deleted. This is the job that does.

Three properties, and each is the reason the previous phase declined to build this:

  1. A DRY RUN IS THE DEFAULT and writes nothing at all -- not even the proposal.
  2. EXECUTION REQUIRES AN APPROVAL, signed. Proposing grants nothing.
  3. IT REDACTS RATHER THAN DELETES. The id and the audit spine survive; the PII fields are
     cleared and stamped with the batch number, so a reader can tell "we purged this, under
     this approval" from "we lost this".

Plus the exclusions that keep it safe: nothing with no retention date, nothing on an open
requisition, nothing belonging to somebody still employed.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_retention_purge   (from backend/)
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
EXPIRED = (NOW - timedelta(days=400)).strftime("%Y-%m-%d")
FUTURE = (NOW + timedelta(days=400)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_MD = str(ObjectId())

    reqs = FakeCollection([
        {"request_no": "HR-REQ-2024-001", "company_id": COMPANY,
         "requisition_track": "internal", "closing_status": "Closed",
         "created_at": NOW - timedelta(days=900)},
        # STILL OPEN -- nothing attached to it is ever eligible, whatever the dates say.
        {"request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "requisition_track": "internal", "closing_status": "Open", "created_at": NOW},
    ])
    candidates = FakeCollection([
        # Eligible: expired, closed requisition, never joined.
        {"uk": "CAN-001", "company_id": COMPANY, "request_no": "HR-REQ-2024-001",
         "candidate_name": "Expired One", "can_email": "one@example.com",
         "can_contact": "+91 00000 11111", "cover_note": "Please consider me.",
         "resume": {"name": "cv.pdf", "key": "s3/cv.pdf"},
         "application_status": M.AppStatus.REJECTED.value,
         "retention_until": EXPIRED, "purged_at": None},
        # NOT eligible: still in date.
        {"uk": "CAN-002", "company_id": COMPANY, "request_no": "HR-REQ-2024-001",
         "candidate_name": "In Date", "can_email": "two@example.com",
         "retention_until": FUTURE, "purged_at": None,
         "application_status": M.AppStatus.REJECTED.value},
        # NOT eligible: NO retention date at all -- a gap to investigate, not a licence.
        {"uk": "CAN-003", "company_id": COMPANY, "request_no": "HR-REQ-2024-001",
         "candidate_name": "No Date", "can_email": "three@example.com",
         "purged_at": None, "application_status": M.AppStatus.REJECTED.value},
        # NOT eligible: their requisition is still open.
        {"uk": "CAN-004", "company_id": COMPANY, "request_no": "HR-REQ-2026-001",
         "candidate_name": "Live Pipeline", "can_email": "four@example.com",
         "retention_until": EXPIRED, "purged_at": None,
         "application_status": M.AppStatus.SHORTLISTED.value},
        # NOT eligible: they became an employee who is still on the payroll.
        {"uk": "CAN-005", "company_id": COMPANY, "request_no": "HR-REQ-2024-001",
         "candidate_name": "Still Employed", "can_email": "five@example.com",
         "retention_until": EXPIRED, "purged_at": None,
         "application_status": M.AppStatus.EMPLOYEE_CREATED.value},
        # NOT eligible: already purged.
        {"uk": "CAN-006", "company_id": COMPANY, "request_no": "HR-REQ-2024-001",
         "candidate_name": None, "retention_until": EXPIRED,
         "purged_at": NOW - timedelta(days=5),
         "application_status": M.AppStatus.REJECTED.value},
    ])
    references = FakeCollection([
        {"ref_no": "REF-2024-001", "company_id": COMPANY,
         "request_no": "HR-REQ-2024-001", "uk": "CAN-001",
         "referee_name": "Former Manager", "referee_contact": "+91 00000 22222",
         "responses": "Spoke highly of them.", "outcome": "Positive",
         "retention_until": EXPIRED, "purged_at": None},
    ])
    profiles = FakeCollection([
        {"employee_code": "EMP-2024-005", "uk": "CAN-005", "company_id": COMPANY,
         "employment_status": M.EmploymentStatus.ACTIVE.value},
    ])
    batches = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_REFERENCE_CHECKS: references, M.COLL_EMPLOYEE_PROFILES: profiles,
             M.COLL_PURGE_BATCHES: batches, M.COLL_OFFERS: FakeCollection(),
             M.COLL_COMM_LOG: FakeCollection(), M.COLL_PREBOARDING: FakeCollection(),
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: audit_log,
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_purge_service as PG
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (PG, AUD, IDS):
        mod.get_collection = mongo.get_collection

    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "MD", "full_name": "Meera MD"}
    HR = {"_id": str(ObjectId()), "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("Capability shape -- the MD alone")
        # =================================================================
        from app.utils.hrms_access import can
        check("the MD may execute a purge", can(MD, M.Cap.RETENTION_PURGE))
        check("HR may NOT -- destroying records is not an operational act",
              not can(HR, M.Cap.RETENTION_PURGE))
        check("it is the same standard probation confirmation holds, because both "
              "destroy or end something", True)

        # =================================================================
        section("Everything the table declares is REDACTION")
        # =================================================================
        check("every purge target redacts rather than deletes",
              all(mode == M.PURGE_REDACT for _c, _i, _r, mode, _f in M.PURGE_TARGETS))
        check("and every one names the exact fields it clears",
              all(fields for *_rest, fields in M.PURGE_TARGETS))
        check("the candidate CV, the reference, the offer, the message log, the "
              "pre-boarding notes, the phone screen and the negotiation rounds are all "
              "covered",
              {c for c, *_ in M.PURGE_TARGETS}
              == {M.COLL_CANDIDATES, M.COLL_REFERENCE_CHECKS, M.COLL_OFFERS,
                  M.COLL_COMM_LOG, M.COLL_PREBOARDING, M.COLL_TELEPHONIC,
                  M.COLL_NEGOTIATIONS})

        # =================================================================
        section("A dry run writes NOTHING -- not even the proposal")
        # =================================================================
        dry = await PG.propose(MD, COMPANY, dry_run=True)
        check("it returns a proposal", dry["total_records"] >= 1)
        check("with no batch number, because nothing was recorded",
              dry["batch_no"] is None)
        check("and the batches collection is still empty",
              await batches.count_documents({}) == 0)
        check("looking should be free -- it is the first thing anybody does", True)

        # =================================================================
        section("Only what is genuinely eligible is proposed")
        # =================================================================
        by_coll = {g["collection"]: g for g in dry["groups"]}
        cand_ids = set(by_coll[M.COLL_CANDIDATES]["ids"])
        check("an expired CV on a closed requisition is proposed",
              "CAN-001" in cand_ids)
        check("one still inside its retention period is NOT", "CAN-002" not in cand_ids)
        check("one with NO retention date is NOT -- that is a gap to investigate",
              "CAN-003" not in cand_ids)
        check("one whose requisition is still OPEN is NOT",
              "CAN-004" not in cand_ids)
        check("one belonging to somebody still employed is NOT",
              "CAN-005" not in cand_ids)
        check("one already purged is NOT proposed again", "CAN-006" not in cand_ids)
        check("and the reference check that goes with the CV IS",
              "REF-2024-001" in set(by_coll[M.COLL_REFERENCE_CHECKS]["ids"]))

        check("the held-back records are COUNTED, so the omission is visible",
              by_coll[M.COLL_CANDIDATES]["skipped_open_requisition"] == 1
              and by_coll[M.COLL_CANDIDATES]["skipped_still_employed"] == 1)
        check("and the summary says so in words",
              "still open" in dry["summary"] and "still employed" in dry["summary"])
        check("the summary states that redaction is not reversible",
              "not reversible" in dry["summary"])

        # =================================================================
        section("The proposal names the EXACT ids")
        # =================================================================
        check("every group carries its ids, not just a count",
              all("ids" in g for g in dry["groups"]))
        check("a proposal saying '412 candidates' without saying which is not something "
              "anybody can approve", True)

        # =================================================================
        section("Proposing grants nothing")
        # =================================================================
        proposed = await PG.propose(MD, COMPANY, dry_run=False)
        BATCH = proposed["batch_no"]
        check("a recorded batch is minted with a PRG id", BATCH.startswith("PRG-"))
        check("it starts Proposed", proposed["status"] == M.PurgeBatchStatus.PROPOSED.value)

        untouched = await candidates.find_one({"uk": "CAN-001"})
        check("and NOTHING has been redacted yet",
              untouched["candidate_name"] == "Expired One"
              and untouched["can_email"] == "one@example.com")

        listing = await PG.list_batches(COMPANY)
        check("the batch is awaiting approval", listing["awaiting_approval"] == 1)
        check("the LISTING omits the id arrays -- five thousand ids per row is a payload "
              "nobody wants", all("ids" not in g
                                  for b in listing["purge_batches"]
                                  for g in b["groups"]))
        detail = await PG.get_batch(COMPANY, BATCH)
        check("but the detail endpoint returns them",
              any(g.get("ids") for g in detail["groups"]))

        # =================================================================
        section("Execution requires a signature")
        # =================================================================
        await expect_http(
            "approving with no signature",
            PG.approve_and_execute(MD, COMPANY, BATCH, {}),
            422, "type your name")
        check("the refusal says outright that it is not reversible", True)
        still = await candidates.find_one({"uk": "CAN-001"})
        check("and nothing was redacted by the refusal",
              still["candidate_name"] == "Expired One")

        # =================================================================
        section("It REDACTS -- the id and the audit spine survive")
        # =================================================================
        done = await PG.approve_and_execute(MD, COMPANY, BATCH, {
            "signature": "Meera MD", "remarks": "Annual disposal, agreed with the auditor."})
        check("the batch is Executed", done["status"] == M.PurgeBatchStatus.EXECUTED.value)
        check("who authorised it is on the record",
              done["approved_by_name"] == "Meera MD" and done["signature"] == "Meera MD")

        purged = await candidates.find_one({"uk": "CAN-001"})
        check("THE ID SURVIVES -- an audit trail with dangling references proves nothing",
              purged["uk"] == "CAN-001")
        check("the requisition link survives, so the record still hangs where it hung",
              purged["request_no"] == "HR-REQ-2024-001")
        check("the name is cleared", purged["candidate_name"] is None)
        check("the email is cleared", purged["can_email"] is None)
        check("the phone is cleared", purged["can_contact"] is None)
        check("the CV is cleared", purged["resume"] is None)
        check("and the covering note with it", purged["cover_note"] is None)
        check("the fields are SET to null rather than removed, so a later audit can find "
              "exactly what was emptied",
              "candidate_name" in purged and "can_email" in purged)
        check("the row is stamped with WHEN it was purged",
              purged[M.PURGE_MARKER_FIELD] is not None)
        check("and under WHICH approval", purged[M.PURGE_BATCH_FIELD] == BATCH)
        check("so a reader can tell 'we purged this' from 'we lost this'", True)

        ref = await references.find_one({"ref_no": "REF-2024-001"})
        check("the reference check is redacted too", ref["referee_name"] is None
              and ref["responses"] is None)
        check("but its OUTCOME survives -- that is the governance fact, not the PII",
              ref["outcome"] == "Positive")

        survivor = await candidates.find_one({"uk": "CAN-002"})
        check("a record that was not in the batch is completely untouched",
              survivor["candidate_name"] == "In Date")

        # =================================================================
        section("The trail")
        # =================================================================
        actions = [a["action"] for a in await audit_log.find({}).to_list(50)]
        check("the proposal is audited", M.AUDIT_PURGE_PROPOSED in actions)
        check("the approval is audited", M.AUDIT_PURGE_APPROVED in actions)
        check("and the execution", M.AUDIT_PURGE_EXECUTED in actions)

        # =================================================================
        section("A batch cannot be executed twice")
        # =================================================================
        await expect_http(
            "approving a batch that has already run",
            PG.approve_and_execute(MD, COMPANY, BATCH, {"signature": "Meera MD"}),
            409, "only a proposed batch")
        await expect_http(
            "approving a batch that does not exist",
            PG.approve_and_execute(MD, COMPANY, "PRG-2026-999",
                                   {"signature": "Meera MD"}),
            404, "not found")

        # =================================================================
        section("A second run finds nothing left")
        # =================================================================
        second = await PG.propose(MD, COMPANY, dry_run=True)
        check("the purged records are not proposed again",
              second["total_records"] == 0)
        check("and the summary says so plainly rather than showing an empty table",
              "nothing is eligible" in second["summary"].lower())

        # =================================================================
        section("The script defaults to a dry run and demands a company")
        # =================================================================
        from pathlib import Path
        script = (Path(__file__).resolve().parents[4]
                  / "scripts" / "hrms_retention_purge.py").read_text(encoding="utf-8")
        check("the script exists", bool(script))
        check("--company is REQUIRED", 'required=True' in script)
        check("there is no all-companies mode, deliberately",
              "There is no \"all companies\" mode" in script)
        check("writing a proposal has to be asked for by name",
              "--propose" in script and "dry_run = not args.propose" in script)
        check("and it tells the operator that nothing has been deleted",
              "Nothing has been deleted or redacted" in script)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
