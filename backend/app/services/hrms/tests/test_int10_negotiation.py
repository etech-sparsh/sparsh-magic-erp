"""Phase INT-10 -- salary negotiation record (Gap 5, SOP step 9, spec §16) and interview
notice (Gap 9, Annexure C).

The RULE was always enforced: `assert_within_band` refuses an offer outside the band stamped
at the budget gate. This phase adds the RECORD -- the rounds -- and the comparison surface
spec §16 asks to display. It also makes the candidate's interview confirmation automatic and
records short notice.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. THE GATE DOES NOT MOVE. Recording an above-band round is allowed; the offer at that
     figure is still refused by `assert_within_band`, which this file calls directly to prove
     the two agree.
  2. ONE COMPARISON. `negotiation_verdict` and `assert_within_band` read the same numbers the
     same way, so a round's verdict and the offer's refusal can never disagree.
  3. THE BAND IS STAMPED ON THE ROUND. A later budget re-approval does not rewrite what round
     2 was judged against -- and the comparison surface shows both the stamped band and the
     band in force now.
  4. INTERNAL TRACK, AFTER THE BUDGET GATE, OR 409. A round against no band is a number with
     no meaning.
  5. SHORT NOTICE WARNS AND NEVER BLOCKS -- the rule interview windows already follow.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int10_negotiation   (from backend/)
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

C1 = "COMPANY-ONE"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    HR = {"_id": ObjectId(), "full_name": "Priya HR", "email": "hr@example.com",
          "_source_collection": "learners", "role": "clientuser",
          "governance_role": "HR", "company_id": C1}
    HOD_ID = str(ObjectId())
    HOD = {"_id": ObjectId(HOD_ID), "full_name": "Meera HOD", "email": "hod@example.com",
           "_source_collection": "learners", "role": "clientuser",
           "governance_role": "HOD", "company_id": C1}
    OTHER_HOD = str(ObjectId())

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_negotiation_service as NG
    import app.services.hrms_offer_service as OF
    import app.services.hrms_exception_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_config_service as CFG
    for mod in (NG, OF, EX, AUD, CFG):
        mod.get_collection = mongo.get_collection

    seq = {"n": 0}

    async def fake_id(kind, company_id, year=None):
        seq["n"] += 1
        return f"NEG-2026-{seq['n']:03d}"
    NG.next_business_id = fake_id

    sent: list = []

    async def fake_role(company_id, roles, title, message, **kw):
        sent.append({"roles": roles, "title": title, "message": message,
                     "email": kw.get("email")})

    async def fake_user(user_id, title, message, **kw):
        sent.append({"user": str(user_id), "title": title, "message": message,
                     "email": kw.get("email")})

    import app.services.hrms_notify_service as NOTIFY
    NOTIFY.notify_hrms_role = fake_role
    NOTIFY.notify_user = fake_user

    INT = "internal"
    store.setdefault(M.COLL_REQUISITIONS, FakeCollection()).docs.extend([
        {"request_no": "R-BANDED", "company_id": C1, "requisition_track": INT,
         "designation_name": "Ops Executive", "closing_status": "Open",
         "created_by": HOD_ID,
         "approved_salary_band_min": 400000, "approved_salary_band_max": 700000,
         "budget_approved_at": NOW - timedelta(days=10),
         "budget_approved_by_name": "Anita MD"},
        # Raised by a DIFFERENT hiring manager -- the HOD above must not see its rounds.
        {"request_no": "R-OTHER", "company_id": C1, "requisition_track": INT,
         "designation_name": "Finance Lead", "closing_status": "Open",
         "created_by": OTHER_HOD,
         "approved_salary_band_min": 900000, "approved_salary_band_max": 1200000},
        {"request_no": "R-UNBANDED", "company_id": C1, "requisition_track": INT,
         "designation_name": "Analyst", "closing_status": "Open",
         "approved_salary_band_min": None, "approved_salary_band_max": None},
        {"request_no": "R-CLIENT", "company_id": C1, "designation_name": "Client Role",
         "closing_status": "Open"},
    ])
    store.setdefault(M.COLL_CANDIDATES, FakeCollection()).docs.extend([
        {"uk": "CAN-001", "company_id": C1, "candidate_name": "Asha K",
         "request_no": "R-BANDED", "application_status": M.AppStatus.SELECTED.value},
        {"uk": "CAN-002", "company_id": C1, "candidate_name": "Early Bird",
         "request_no": "R-UNBANDED", "application_status": M.AppStatus.SHORTLISTED.value},
        {"uk": "CAN-003", "company_id": C1, "candidate_name": "Client Candidate",
         "request_no": "R-CLIENT", "application_status": M.AppStatus.SELECTED.value},
        {"uk": "CAN-004", "company_id": C1, "candidate_name": "Other Dept",
         "request_no": "R-OTHER", "application_status": M.AppStatus.SELECTED.value},
    ])

    # =========================================================================
    section("1. One comparison -- the verdict and the offer gate read the same numbers")
    # =========================================================================
    check("within", M.negotiation_verdict(500000, 400000, 700000) == M.NEGOTIATION_WITHIN)
    check("above", M.negotiation_verdict(750000, 400000, 700000) == M.NEGOTIATION_ABOVE)
    check("below", M.negotiation_verdict(300000, 400000, 700000) == M.NEGOTIATION_BELOW)
    check("the band edges are INSIDE the band, exactly as assert_within_band reads them",
          M.negotiation_verdict(400000, 400000, 700000) == M.NEGOTIATION_WITHIN
          and M.negotiation_verdict(700000, 400000, 700000) == M.NEGOTIATION_WITHIN)
    check("unbanded is None, not a verdict", M.negotiation_verdict(5, None, 7) is None)

    req = await store[M.COLL_REQUISITIONS].find_one({"request_no": "R-BANDED"})
    cand = await store[M.COLL_CANDIDATES].find_one({"uk": "CAN-001"})
    for figure in (400000, 550000, 700000):
        await OF.assert_within_band(C1, figure, cand, req)
    check("every figure the verdict calls 'within' passes the offer gate", True)
    await expect_http("and the figure the verdict calls 'above' is refused by the gate",
                      OF.assert_within_band(C1, 750000, cand, req), 409, "above")
    await expect_http("and 'below' is refused too",
                      OF.assert_within_band(C1, 300000, cand, req), 409, "below")

    # =========================================================================
    section("2. Recording rounds")
    # =========================================================================
    sent.clear()
    r1 = await NG.record_round(HR, C1, {
        "uk": "CAN-001", "candidate_expectation": 800000, "proposed_ctc": 600000,
        "notes": "Opened inside the band."})
    check("round 1 minted, numbered, stamped with the band as it stood",
          r1["neg_no"] == "NEG-2026-001" and r1["round"] == 1
          and r1["band_min"] == 400000 and r1["band_max"] == 700000)
    check("request_no and uk are carried", r1["request_no"] == "R-BANDED"
          and r1["uk"] == "CAN-001")
    check("the verdict is within", r1["verdict"] == M.NEGOTIATION_WITHIN)
    check("a within-band round tells NOBODY -- it is HR's business", sent == [])
    check("a retention floor is stamped, on the OFFER's three-year basis",
          r1["retention_until"].startswith(str(NOW.year + 3)))
    check("the act was audited",
          any(r.get("action") == M.AUDIT_NEGOTIATION_RECORDED
              for r in store[M.COLL_AUDIT_LOG].docs))

    sent.clear()
    r2 = await NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": 750000,
                                        "notes": "Candidate held firm; HR proposed above."})
    check("round 2 is numbered 2", r2["round"] == 2)
    check("and its verdict is above", r2["verdict"] == M.NEGOTIATION_ABOVE)
    check("an above-band round is RECORDED, not refused -- the conversation is allowed",
          r2["neg_no"] == "NEG-2026-002")
    check("and it tells Management AND Finance, by email -- spec §38 'salary deviation'",
          len(sent) == 1 and sent[0]["roles"] == ["MD", "FINANCE"]
          and sent[0]["email"] is True and "above" in sent[0]["title"])
    check("the message names the figure, the band and the way forward",
          "750,000" in sent[0]["message"] and "400,000" in sent[0]["message"]
          and "Offer Outside Budget" in sent[0]["message"])

    # =========================================================================
    section("3. THE GATE DOES NOT MOVE")
    # =========================================================================
    await expect_http("an offer at round 2's figure is STILL refused by the band gate -- "
                      "recording the round decided nothing",
                      OF.assert_within_band(C1, 750000, cand, req), 409, "above")
    store.setdefault(M.COLL_EXCEPTIONS, FakeCollection()).docs.append(
        {"exc_no": "EXC-001", "company_id": C1, "request_no": "R-BANDED", "uk": "CAN-001",
         "exception_type": M.ExceptionType.OFFER_OUTSIDE_BUDGET.value,
         "status": M.ExceptionStatus.APPROVED.value})
    await OF.assert_within_band(C1, 750000, cand, req)
    check("an approved Offer Outside Budget exception is what opens it -- the same path "
          "as before this phase", True)

    # =========================================================================
    section("4. The comparison surface (spec §16)")
    # =========================================================================
    view = await NG.negotiation_for(HR, C1, "CAN-001")
    check("the band, the latest round and the verdict are all there",
          view["band"]["min"] == 400000 and view["latest_round"]["round"] == 2
          and view["latest_verdict_now"] == M.NEGOTIATION_ABOVE)
    check("the candidate's expectation is carried forward from the round that stated it",
          view["candidate_expectation"] == 800000)
    check("the approved waiver is shown, and the offer-would-pass preview says YES because "
          "of it", view["waiver"]["exc_no"] == "EXC-001"
          and view["offer_would_pass"] is True and "EXC-001" in view["offer_gate_note"])
    check("the full history is there, in round order",
          [r["round"] for r in view["rounds"]] == [1, 2])
    # The shared FakeCursor.sort is a no-op, so reverse the stored order to prove the
    # service orders in Python too -- "latest" is positional and must not depend on the
    # cursor.
    store[M.COLL_NEGOTIATIONS].docs.reverse()
    view = await NG.negotiation_for(HR, C1, "CAN-001")
    check("with the stored order reversed, the latest round is STILL round 2",
          view["latest_round"]["round"] == 2
          and [r["round"] for r in view["rounds"]] == [1, 2])
    store[M.COLL_NEGOTIATIONS].docs.reverse()

    # -- Without the waiver, the preview says NO and names the remedies --
    store[M.COLL_EXCEPTIONS].docs.clear()
    view = await NG.negotiation_for(HR, C1, "CAN-001")
    check("without the waiver the preview says NO, with the two remedies the gate accepts",
          view["offer_would_pass"] is False
          and "re-approve" in view["offer_gate_note"].lower()
          and "Offer Outside Budget" in view["offer_gate_note"])

    # -- The band is stamped on the round; the surface shows the band NOW --
    await store[M.COLL_REQUISITIONS].update_one(
        {"request_no": "R-BANDED"}, {"$set": {"approved_salary_band_max": 800000}})
    view = await NG.negotiation_for(HR, C1, "CAN-001")
    check("after a budget re-approval the ROUND still carries the band it was judged "
          "against", view["rounds"][1]["band_max"] == 700000)
    check("while the surface judges the latest figure against the band IN FORCE NOW -- "
          "within, and the offer would pass",
          view["band"]["max"] == 800000
          and view["latest_verdict_now"] == M.NEGOTIATION_WITHIN
          and view["offer_would_pass"] is True)
    await store[M.COLL_REQUISITIONS].update_one(
        {"request_no": "R-BANDED"}, {"$set": {"approved_salary_band_max": 700000}})

    # =========================================================================
    section("5. Internal track, after the budget gate, or 409")
    # =========================================================================
    await expect_http("a round for a candidate on an UNBANDED requisition",
                      NG.record_round(HR, C1, {"uk": "CAN-002", "proposed_ctc": 500000}),
                      409, "no approved salary band")
    await expect_http("a round for a CLIENT-track candidate",
                      NG.record_round(HR, C1, {"uk": "CAN-003", "proposed_ctc": 500000}),
                      409, "legacy client-track")
    await expect_http("an unknown candidate",
                      NG.record_round(HR, C1, {"uk": "CAN-NOPE", "proposed_ctc": 1}), 404)
    await expect_http("no figure",
                      NG.record_round(HR, C1, {"uk": "CAN-001"}), 422, "proposed ctc")
    await expect_http("a zero figure",
                      NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": 0}),
                      422, "greater than zero")
    await expect_http("a boolean figure",
                      NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": True}),
                      422, "must be a number")
    # A NaN compares False to everything: it would read as "within", skip the Management
    # notice, and break every read of the board (it is not JSON). The one input on which
    # the verdict and the gate could disagree -- refused at the service AND the boundary.
    await expect_http("NaN", NG.record_round(HR, C1, {"uk": "CAN-001",
                                                      "proposed_ctc": float("nan")}),
                      422, "finite")
    await expect_http("infinity", NG.record_round(HR, C1, {"uk": "CAN-001",
                                                           "proposed_ctc": float("inf")}),
                      422, "finite")
    await expect_http("an implausible figure",
                      NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": 5e12}),
                      422, "implausibly large")
    check("negotiation_verdict never calls NaN 'within'",
          M.negotiation_verdict(float("nan"), 400000, 700000) is None)
    try:
        M.NegotiationRoundIn(uk="CAN-001", proposed_ctc=float("nan"))
        check("the Pydantic boundary refuses NaN too", False)
    except Exception:
        check("the Pydantic boundary refuses NaN too", True)
    check("no refusal wrote a round", (await NG.list_rounds(HR, C1))["total"] == 2)
    preview = await NG.negotiation_for(HR, C1, "CAN-003")
    check("the comparison surface on a legacy client-track candidate says it is out of scope, "
          "rather than inventing a band",
          preview["offer_would_pass"] is False and "legacy" in preview["offer_gate_note"].lower())
    preview = await NG.negotiation_for(HR, C1, "CAN-002")
    # The gate FAILS OPEN on an internal requisition with no band (a pre-band-gate row);
    # the surface must say the same, or it diverges from the thing it previews.
    req2 = await store[M.COLL_REQUISITIONS].find_one({"request_no": "R-UNBANDED"})
    cand2 = await store[M.COLL_CANDIDATES].find_one({"uk": "CAN-002"})
    await OF.assert_within_band(C1, 999999, cand2, req2)
    check("the offer gate does not refuse an unbanded internal requisition", True)
    check("and the surface MIRRORS that -- would pass, with the gap named -- rather than "
          "saying NO while the offer would go through",
          preview["offer_would_pass"] is True
          and "no approved salary band" in preview["offer_gate_note"].lower())

    # -- The round cap --
    for _ in range(M.MAX_NEGOTIATION_ROUNDS - 2):
        await NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": 600000})
    await expect_http("the thirteenth round is refused -- a negotiation that long is a "
                      "decision nobody is taking",
                      NG.record_round(HR, C1, {"uk": "CAN-001", "proposed_ctc": 600000}),
                      409, "escalate")

    listing = await NG.list_rounds(HR, C1, uk="CAN-001")
    check("the list counts the above-band rounds", listing["above_band"] == 1)

    # =========================================================================
    section("6. Capabilities follow Annexure B (HR R, HOD C, Management A)")
    # =========================================================================
    R = M.ROLE_CAPABILITIES
    check("HR writes rounds", M.Cap.NEGOTIATION_WRITE in R[M.HrmsRole.HR])
    check("the HOD is consulted: reads, never writes",
          M.Cap.NEGOTIATION_READ in R[M.HrmsRole.MANAGER]
          and M.Cap.NEGOTIATION_WRITE not in R[M.HrmsRole.MANAGER])
    check("FINANCE is accountable for the figure: reads every round -- the one "
          "candidate-level record it sees, because it is about money and nothing else",
          M.Cap.NEGOTIATION_READ in R[M.HrmsRole.FINANCE]
          and M.Cap.NEGOTIATION_WRITE not in R[M.HrmsRole.FINANCE])
    check("the MD holds both", M.Cap.NEGOTIATION_WRITE in R[M.HrmsRole.MD])
    check("an EMPLOYEE holds neither", M.Cap.NEGOTIATION_READ not in R[M.HrmsRole.EMPLOYEE])
    check("Sparsh support staff (INTERNAL) hold NEITHER -- per-candidate pay is the same "
          "class as the offer CTC and the salary bands already withheld from them",
          M.Cap.NEGOTIATION_READ not in R[M.HrmsRole.INTERNAL])

    # -- Row scoping: a hiring manager sees only the requisitions they raised --
    await NG.record_round(HR, C1, {"uk": "CAN-004", "proposed_ctc": 1000000})
    mine = await NG.list_rounds(HOD, C1)
    check("the HOD's list is narrowed to their own requisitions, and says so",
          {r["request_no"] for r in mine["rounds"]} == {"R-BANDED"}
          and mine["scoped_to_own_requisitions"] is True)
    check("HR's list is not narrowed",
          "R-OTHER" in {r["request_no"] for r in (await NG.list_rounds(HR, C1))["rounds"]}
          and (await NG.list_rounds(HR, C1))["scoped_to_own_requisitions"] is False)
    await expect_http("the HOD asking for another department's candidate gets 404, not a "
                      "salary figure -- and not a 403 that confirms the record exists",
                      NG.negotiation_for(HOD, C1, "CAN-004"), 404)
    view = await NG.negotiation_for(HOD, C1, "CAN-001")
    check("but sees their own candidate's comparison surface",
          view["request_no"] == "R-BANDED")

    # =========================================================================
    section("7. Retention, purge and the declared shape")
    # =========================================================================
    check("retention follows the OFFER (employment + 3)", M.RETENTION_YEARS["negotiation"] == 3)
    target = next((t for t in M.PURGE_TARGETS if t[0] == M.COLL_NEGOTIATIONS), None)
    check("the collection is a purge target that REDACTS the figures and notes",
          target is not None and target[3] == M.PURGE_REDACT
          and {"proposed_ctc", "candidate_expectation", "notes"} <= set(target[4]))
    neg_idx = [(k, o) for c, k, o in M.HRMS_INDEXES if c == M.COLL_NEGOTIATIONS]
    check("the business id is unique PER COMPANY -- sequences are minted per company and "
          "rendered without one, so two tenants' first rounds share NEG-2026-001",
          any(k == [("company_id", 1), ("neg_no", 1)] and o.get("unique")
              for k, o in neg_idx)
          and not any(k == [("neg_no", 1)] for k, _o in neg_idx))
    check("(company, candidate, round) is UNIQUE -- two simultaneous round-3s become one "
          "winner and one retry, not two round 3s",
          any(k == [("company_id", 1), ("uk", 1), ("round", 1)] and o.get("unique")
              for k, o in neg_idx))
    import inspect as _insp
    check("the service catches the duplicate and renumbers rather than 500ing",
          "DuplicateKeyError" in _insp.getsource(NG.record_round))
    check("candidate_name is purged from EVERY candidate-linked target, not just this one "
          "-- an anonymised candidate whose name survives in four sibling rows is not "
          "anonymised",
          all("candidate_name" in fields for coll, _i, _r, _m, fields in M.PURGE_TARGETS
              if coll in (M.COLL_REFERENCE_CHECKS, M.COLL_OFFERS, M.COLL_COMM_LOG,
                          M.COLL_PREBOARDING, M.COLL_TELEPHONIC, M.COLL_NEGOTIATIONS)))
    check("retention clamps only 29 February, like every sibling",
          "min(now.day, 28)" not in _insp.getsource(NG.record_round))
    check("the id format is NEG-", M.ID_FORMATS["negotiation"][0] == "NEG")

    # =========================================================================
    section("8. Gap 9 -- the candidate is told, and short notice is recorded")
    # =========================================================================
    import app.services.hrms_interview_service as IV
    check("interview_scheduled is now an AUTOMATIC communication event",
          M.AUTO_COMM_EVENTS.get("interview_scheduled") == "interview_scheduled")
    check("the 24-hour figure is the model's, not a literal in the service",
          M.INTERVIEW_NOTICE_HOURS == 24)
    soon = NOW + timedelta(hours=3)
    later = NOW + timedelta(hours=48)
    check("three hours ahead is short notice",
          IV._notice_hours(soon, NOW) < M.INTERVIEW_NOTICE_HOURS)
    check("two days ahead is not", IV._notice_hours(later, NOW) >= M.INTERVIEW_NOTICE_HOURS)
    check("short notice WARNS -- and, told nothing about the send, says the candidate has "
          "NOT been emailed rather than claiming they were",
          "NOT been emailed" in (IV._short_notice_warning(
              {"short_notice": True, "notice_hours": 3.0}) or ""))
    check("and says they HAVE been emailed only when the send reported Sent",
          "has been emailed" in (IV._short_notice_warning(
              {"short_notice": True, "notice_hours": 3.0}, "Sent") or ""))
    check("and is silent when notice is adequate",
          IV._short_notice_warning({"short_notice": False, "notice_hours": 48.0}) is None)

    # ── Behavioural, end to end through the real service against the shared fakes ──
    import app.services.hrms_audit_service as AUD2
    import app.services.hrms_id_service as IDS
    for mod in (IV, AUD2, IDS):
        mod.get_collection = mongo.get_collection
    ids = {"n": 0}

    async def fake_iv_id(kind, company_id, year=None):
        ids["n"] += 1
        return f"INT-2026-{ids['n']:03d}"
    IV.next_business_id = fake_iv_id

    async def quiet(*a, **k):
        return None
    IV.notify_user = quiet

    # `_tell_candidate` imports fire_event LATE, so the module attribute is what it calls.
    import app.services.hrms_comm_service as CM
    told: list = []
    reply = {"status": "Sent"}

    async def fake_fire(actor, company_id, uk, event, *, variables=None):
        told.append({"uk": uk, "event": event, "variables": dict(variables or {})})
        return dict(reply)
    CM.fire_event = fake_fire

    U_HR, U_HOD = str(ObjectId()), str(ObjectId())
    store.setdefault("learners", FakeCollection()).docs.extend([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": C1, "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": C1, "role": "clientuser", "governance_role": "HOD"},
    ])
    DESIG = ObjectId()
    store.setdefault(M.COLL_DESIGNATIONS, FakeCollection()).docs.append(
        {"_id": DESIG, "company_id": C1, "name": "Ops Executive", "designation_level": "mid"})
    for r in store[M.COLL_REQUISITIONS].docs:
        r.setdefault("designation_id", str(DESIG))
        r.setdefault("department_id", "D1")
    store[M.COLL_CANDIDATES].docs.extend([
        {"uk": "CAN-INT", "company_id": C1, "candidate_name": "Internal Hire",
         "can_email": "int@example.com", "request_no": "R-BANDED",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"uk": "CAN-EXT", "company_id": C1, "candidate_name": "Client Hire",
         "can_email": "ext@example.com", "request_no": "R-CLIENT",
         "application_status": M.AppStatus.SHORTLISTED.value},
    ])
    # The INT-4 telephonic gate sits ahead of every internal booking.
    store.setdefault(M.COLL_TELEPHONIC, FakeCollection()).docs.append(
        {"tel_no": "TEL-1", "company_id": C1, "uk": "CAN-INT", "request_no": "R-BANDED",
         "outcome": M.TelephonicOutcome.PASSED.value})
    store.setdefault(M.COLL_INTERVIEW_WINDOWS, FakeCollection())

    HR_ACTOR = {**HR, "_id": ObjectId(U_HR)}

    def booking(uk, when):
        return {"uk": uk, "round": M.InterviewRound.HR.value, "scheduled_at": when,
                "duration_min": 45, "mode": M.InterviewMode.VIRTUAL.value,
                "meeting_link": "https://meet.example.com/room", "interviewer_id": U_HR,
                "panel": [{"user_id": U_HR, "role": "hr"},
                          {"user_id": U_HOD, "role": "manager"}]}

    # -- Internal, three hours ahead: told, stamped, warned, NOT blocked --
    told.clear()
    booked = await IV.schedule_interview(HR_ACTOR, C1, booking("CAN-INT", soon.isoformat()))
    check("short notice does NOT block: the booking was made",
          booked["interview_no"] == "INT-2026-001")
    check("the candidate was told, through the comms log, with the interview event",
          len(told) == 1 and told[0]["event"] == "interview_scheduled"
          and told[0]["uk"] == "CAN-INT")
    check("and the variables carry the round, a time LABELLED in the operating zone, and "
          "the place",
          told[0]["variables"]["round"] == M.InterviewRound.HR.value
          and told[0]["variables"]["when"].endswith("IST")
          and "meet.example.com" in told[0]["variables"]["where"])
    check("notice_hours / short_notice are stamped on the booking",
          booked.get("short_notice") is True and 0 < booked.get("notice_hours") < 24)
    check("the response WARNS, and says the candidate was emailed -- because the send "
          "reported Sent", "Short notice" in (booked.get("warning") or "")
          and "has been emailed" in booked["warning"])
    check("what the send reported is stamped on the booking",
          booked.get("candidate_notified") == "Sent")

    # -- The warning tells the truth when the send did NOT happen --
    reply["status"] = "Skipped"
    told.clear()
    booked2 = await IV.schedule_interview(HR_ACTOR, C1, booking("CAN-INT", soon.isoformat()))
    check("when the send was skipped the warning says the candidate has NOT been emailed "
          "-- a claim nobody checked is how a warning becomes a lie",
          "NOT been emailed" in (booked2.get("warning") or "")
          and "skipped" in booked2["warning"].lower())
    reply["status"] = "Sent"

    # -- Adequate notice: told, no warning --
    told.clear()
    booked3 = await IV.schedule_interview(HR_ACTOR, C1, booking("CAN-INT", later.isoformat()))
    check("two days ahead: the candidate is still told", len(told) == 1)
    check("and there is no short-notice warning",
          "Short notice" not in (booked3.get("warning") or ""))

    # -- CLIENT track: nothing new happens at all --
    told.clear()
    ext = await IV.schedule_interview(HR_ACTOR, C1, booking("CAN-EXT", soon.isoformat()))
    check("a CLIENT-track booking does NOT email the candidate from Sparsh's template",
          told == [])
    check("and carries none of the new keys -- byte-for-byte the booking it always was",
          "notice_hours" not in ext and "short_notice" not in ext
          and "candidate_notified" not in ext and "warning" not in ext)

    # -- Reschedule: re-told on a real time change only --
    told.clear()
    moved = await IV.update_interview(HR_ACTOR, C1, booked3["interview_no"],
                                      {"scheduled_at": (later + timedelta(days=1)).isoformat()})
    check("moving the time re-tells the candidate -- new logistics",
          len(told) == 1 and moved.get("ics_sequence") == 1)
    told.clear()
    await IV.update_interview(HR_ACTOR, C1, booked3["interview_no"], {"notes": "Bring ID."})
    check("editing NOTES does not re-tell anybody", told == [])

    # Mongo hands back NAIVE UTC; the API hands in AWARE IST. Echoing the unchanged time
    # must not read as a reschedule.
    stored = await store[M.COLL_INTERVIEWS].find_one({"interview_no": booked3["interview_no"]})
    aware = stored["scheduled_at"]
    stored["scheduled_at"] = aware.astimezone(timezone.utc).replace(tzinfo=None)
    from app.services.hrms_ics import IST
    told.clear()
    echoed = await IV.update_interview(HR_ACTOR, C1, booked3["interview_no"],
                                       {"scheduled_at": aware.astimezone(IST).isoformat(),
                                        "notes": "Same time, just re-saved."})
    check("a PATCH that echoes the SAME instant (in another zone, against a naive stored "
          "value) is not a reschedule: no re-tell, no ICS bump",
          told == [] and echoed.get("ics_sequence") == 1)

    check("short notice never BLOCKS -- every booking above landed, including the three-hour "
          "one", sum(1 for d in store[M.COLL_INTERVIEWS].docs) == 4)

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed, total = sum(results), len(results)
    print(f"  {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
