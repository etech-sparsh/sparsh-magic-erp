"""Phase INT-6 -- the working calendar (spec §26).

SOP §8 states its targets in WORKING days. Weekends were always excluded; public holidays
never were, and the deferral note gave a real reason: two companies looking at the same
three-day gap would disagree about whether a requisition breached. INT-5 made rules
per-company, which is what makes the answer available -- let each entity say which days it
does not work, rather than forcing one answer on both.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. OFF BY DEFAULT, and the default answer is byte-for-byte the pre-INT-6 one. Turning it
     on changes whether EXISTING requisitions read as breached, so it is a decision with a
     date, not something that arrives with a deploy.
  2. `None` AND `set()` ARE DIFFERENT ANSWERS. None = does not honour a calendar. Empty set =
     honours one that has no dates in it. Collapsing them makes "no holidays this quarter"
     indistinguishable from "nobody set this up".
  3. THE CALENDAR IS HRMS'S OWN, NOT THE ERP'S GLOBAL MASTER. That collection has no
     company_id, so a live dependency would let one admin's edit move every entity's due
     dates. The ERP master is an IMPORT -- an adoption somebody performs, with an audit row.
  4. THE BASIS IS REPORTED, NEVER ASSUMED. A reader must not have to guess which of the two
     bases produced the number in front of them.
  5. ONE COMPANY'S CALENDAR NEVER REACHES ANOTHER'S.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int6_holidays   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

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
C2 = "COMPANY-TWO"

# A deliberately ordinary week: Mon 17 Aug 2026 .. Fri 21 Aug 2026.
MON = date(2026, 8, 17)
WED = date(2026, 8, 19)
FRI = date(2026, 8, 21)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    MD = {"_id": ObjectId(), "full_name": "Anita MD", "email": "md@example.com"}

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_holiday_service as HOL
    import app.services.hrms_config_service as CFG
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_sla_service as SLA
    for mod in (HOL, CFG, AUD, SLA):
        mod.get_collection = mongo.get_collection

    # =========================================================================
    section("1. The maths -- pure, and unchanged when nobody honours a calendar")
    # =========================================================================
    check("Mon->Fri is 4 working days", SLA.working_days_between(MON, FRI) == 4)
    check("and still 4 with an explicit EMPTY calendar -- honouring a calendar with no "
          "dates in it must not change the answer",
          SLA.working_days_between(MON, FRI, set()) == 4)
    check("a midweek holiday takes one off",
          SLA.working_days_between(MON, FRI, {"2026-08-19"}) == 3)
    check("a holiday falling on a SATURDAY changes nothing -- it was never a working day",
          SLA.working_days_between(MON, FRI, {"2026-08-22"}) == 4)
    check("Friday to Monday is still 1", SLA.working_days_between(FRI, date(2026, 8, 24)) == 1)
    check("a backwards range still reports a NEGATIVE count rather than clamping",
          SLA.working_days_between(FRI, MON) == -4)
    check("an unreadable date is still None", SLA.working_days_between("nope", FRI) is None)

    check("Mon + 3 working days is Thursday", SLA.add_working_days(MON, 3) == date(2026, 8, 20))
    check("with Wednesday off it is Friday",
          SLA.add_working_days(MON, 3, {"2026-08-19"}) == FRI)
    check("with Wednesday AND Thursday off, Mon + 2 lands on the Friday",
          SLA.add_working_days(MON, 2, {"2026-08-19", "2026-08-20"}) == FRI)
    # The property that matters, rather than one example of it: a due date nobody works must
    # never appear on a report. Counting forward already skips non-working days; the pull-back
    # loop is what covers a ZERO-day target measured from one.
    holidays = {"2026-08-19", "2026-08-20"}
    check("a due date is NEVER a non-working day, at any target from any start in the week",
          all(SLA._is_working(SLA.add_working_days(date(2026, 8, d), n, holidays), holidays)
              for d in range(15, 26) for n in range(0, 6)))
    check("and a zero-day target measured from a holiday pulls BACK to the working day "
          "before it, rather than reporting a deadline on a day nobody works",
          SLA.add_working_days(date(2026, 8, 19), 0, holidays) == date(2026, 8, 18))
    check("a zero-day target from a Saturday pulls back to the Friday",
          SLA.add_working_days(date(2026, 8, 22), 0) == date(2026, 8, 21))
    check("a calendar that marks everything non-working terminates instead of spinning",
          SLA.add_working_days(MON, 5, {(MON.replace(day=d)).isoformat()
                                        for d in range(1, 32)}) is not None)

    # =========================================================================
    section("2. holiday_set -- None and an empty set are DIFFERENT answers")
    # =========================================================================
    check("a company that has not opted in gets None, not an empty set",
          await HOL.holiday_set(C1) is None)

    await CFG.update_config(MD, C1, {M.CONFIG_HONOUR_HOLIDAYS: True})
    got = await HOL.holiday_set(C1)
    check("once opted in with no dates recorded it gets an EMPTY SET -- 'no holidays this "
          "quarter' must not read as 'nobody set this up'",
          got == set() and got is not None)

    await HOL.add_holiday(MD, C1, {"holiday_date": "2026-08-19",
                                   "holiday_name": "Founders Day"})
    check("a recorded date appears", await HOL.holiday_set(C1) == {"2026-08-19"})
    check("the flag is what decides, not the presence of dates: switching it off returns "
          "None even though the calendar still holds a date",
          (await CFG.update_config(MD, C1, {M.CONFIG_HONOUR_HOLIDAYS: False}))
          is not None and await HOL.holiday_set(C1) is None)
    await CFG.update_config(MD, C1, {M.CONFIG_HONOUR_HOLIDAYS: True})

    # =========================================================================
    section("3. THE POINT -- one company's calendar never reaches another")
    # =========================================================================
    check("the second company has not opted in, so it gets None",
          await HOL.holiday_set(C2) is None)
    await CFG.update_config(MD, C2, {M.CONFIG_HONOUR_HOLIDAYS: True})
    check("and once opted in it sees ITS OWN calendar, which is empty",
          await HOL.holiday_set(C2) == set())
    await HOL.add_holiday(MD, C2, {"holiday_date": "2026-08-20",
                                   "holiday_name": "Regional Festival"})
    check("company one is unaffected by company two's holiday",
          await HOL.holiday_set(C1) == {"2026-08-19"})
    check("and company two by company one's",
          await HOL.holiday_set(C2) == {"2026-08-20"})
    check("listing is company-scoped",
          (await HOL.list_holidays(C1))["total"] == 1
          and (await HOL.list_holidays(C2))["total"] == 1)

    # =========================================================================
    section("4. Managing the calendar")
    # =========================================================================
    await expect_http("a holiday with no date",
                      HOL.add_holiday(MD, C1, {"holiday_name": "X"}), 422, "valid date")
    await expect_http("a malformed date",
                      HOL.add_holiday(MD, C1, {"holiday_date": "19/08/2026",
                                               "holiday_name": "X"}), 422, "valid date")
    await expect_http("a date with no name -- unreviewable a year later",
                      HOL.add_holiday(MD, C1, {"holiday_date": "2026-12-25"}),
                      422, "name the holiday")
    await expect_http("the same date twice",
                      HOL.add_holiday(MD, C1, {"holiday_date": "2026-08-19",
                                               "holiday_name": "Duplicate"}),
                      409, "already a non-working day")
    check("no refusal added a row", (await HOL.list_holidays(C1))["total"] == 1)

    await expect_http("removing a date that is not on the calendar",
                      HOL.remove_holiday(MD, C1, "2026-01-01"), 404)
    removed = await HOL.remove_holiday(MD, C1, "2026-08-19")
    check("removing works and names what went", removed["holiday_name"] == "Founders Day")
    check("and the maths follows immediately", await HOL.holiday_set(C1) == set())
    await HOL.add_holiday(MD, C1, {"holiday_date": "2026-08-19",
                                   "holiday_name": "Founders Day"})

    check("adds and removals are audited",
          sum(1 for r in store[M.COLL_AUDIT_LOG].docs
              if r.get("action") in (M.AUDIT_HOLIDAY_ADDED, M.AUDIT_HOLIDAY_REMOVED)) >= 3)
    check("a year filter narrows the listing",
          (await HOL.list_holidays(C1, year=2026))["total"] == 1
          and (await HOL.list_holidays(C1, year=2025))["total"] == 0)

    # =========================================================================
    section("5. Import from the ERP master -- a copy, not a live dependency")
    # =========================================================================
    erp = store.setdefault(HOL.ERP_HOLIDAY_COLLECTION, FakeCollection())
    erp.docs.extend([
        {"holiday_date": "2026-01-26", "holiday_name": "Republic Day", "status": "active"},
        {"holiday_date": "2026-08-19", "holiday_name": "Founders Day", "status": "active"},
        {"holiday_date": "2026-10-02", "holiday_name": "Gandhi Jayanti", "status": "active"},
        # Retired by somebody -- importing it would resurrect a date they dropped.
        {"holiday_date": "2026-11-11", "holiday_name": "Withdrawn", "status": "inactive"},
        # A different year entirely.
        {"holiday_date": "2025-01-26", "holiday_name": "Republic Day", "status": "active"},
        # Unusable data must not become a calendar entry.
        {"holiday_date": "not-a-date", "holiday_name": "Broken", "status": "active"},
    ])

    result = await HOL.import_from_erp(MD, C1, year=2026)
    check("two new dates were adopted", result["imported"] == 2)
    check("the date already on the calendar is reported as present, not refused",
          result["already_present"] == 1)
    check("an INACTIVE holiday is not resurrected",
          "2026-11-11" not in await HOL.holiday_set(C1))
    check("another year is not swept in", "2025-01-26" not in await HOL.holiday_set(C1))
    check("unusable data is skipped rather than stored",
          all(r["holiday_date"] != "not-a-date"
              for r in (await HOL.list_holidays(C1))["holidays"]))
    check("the calendar now holds the three 2026 dates",
          await HOL.holiday_set(C1) == {"2026-01-26", "2026-08-19", "2026-10-02"})

    again = await HOL.import_from_erp(MD, C1, year=2026)
    check("running the import twice is SAFE -- the second run adopts nothing new rather "
          "than failing on the first collision",
          again["imported"] == 0 and again["already_present"] == 3)
    check("the import is audited",
          any(r.get("action") == M.AUDIT_HOLIDAY_IMPORTED
              for r in store[M.COLL_AUDIT_LOG].docs))
    check("the ERP master is untouched by any of this -- HRMS copies, it does not write "
          "into another module's collection", len(erp.docs) == 6)
    check("company two did NOT inherit the import", await HOL.holiday_set(C2) == {"2026-08-20"})

    # -- Structural: the ERP collection is read in exactly one place --
    import inspect
    for mod, name in ((SLA, "hrms_sla_service"), (CFG, "hrms_config_service")):
        check(f"{name} never reads the ERP's global holidays collection directly",
              '"holidays"' not in inspect.getsource(mod))

    # =========================================================================
    section("6. The SLA report -- and the basis it declares")
    # =========================================================================
    reqs = store.setdefault(M.COLL_REQUISITIONS, FakeCollection())
    raised = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)     # Monday
    req = {"request_no": "HR-REQ-2026-001", "company_id": C1,
           "requisition_track": "internal",
           "closing_status": "Open", "created_at": raised,
           # Budget approved on the Friday: 4 calendar working days later.
           "sla_actuals": {"budget_approved": datetime(2026, 8, 21, 9, 0,
                                                       tzinfo=timezone.utc)}}
    reqs.docs.append(req)

    # C3 honours nothing -- the pre-INT-6 basis.
    C3 = "COMPANY-THREE"
    report = await SLA.sla_for(C3, {**req, "company_id": C3})
    budget = next(r for r in report["milestones"] if r["key"] == "budget_approved")
    check("a company that honours no calendar reports counts_holidays FALSE",
          report["counts_holidays"] is False)
    check("and says so in plain English", "does not honour" in report["basis"])
    check("holidays_in_calendar is null rather than 0, so 'not honouring' and 'honouring "
          "nothing' stay distinguishable on the wire",
          report["holidays_in_calendar"] is None)
    check("Mon->Fri took 4 working days against a target of 3, so it BREACHED",
          budget["working_days_taken"] == 4 and budget["status"] == "breached")

    # C1 honours a calendar with the Wednesday on it.
    report = await SLA.sla_for(C1, req)
    budget = next(r for r in report["milestones"] if r["key"] == "budget_approved")
    check("the opted-in company reports counts_holidays TRUE",
          report["counts_holidays"] is True)
    check("and reports how many dates its calendar holds",
          report["holidays_in_calendar"] == 3)
    check("the same four calendar days are now 3 WORKING days, because the Wednesday is a "
          "holiday", budget["working_days_taken"] == 3)
    check("so the SAME requisition is MET rather than breached -- which is exactly why the "
          "flag ships off and turning it on is a dated decision",
          budget["status"] == "met")
    check("the due date is computed on the same basis",
          budget["due_on"] is not None)

    passed = await SLA.sla_for(C1, req, config=await CFG.config_for(C1),
                               calendar=await HOL.holiday_set(C1))
    check("a pre-resolved calendar gives the identical answer -- which is what lets the "
          "sweep read it ONCE for hundreds of requisitions",
          next(r for r in passed["milestones"]
               if r["key"] == "budget_approved")["status"] == "met")

    check("a client requisition still has no SLA at all",
          (await SLA.sla_for(C1, {**req, "requisition_track": None}))["applicable"] is False)

    # =========================================================================
    section("7. The sweep resolves the calendar once")
    # =========================================================================
    seen: list = []
    real_sla_for = SLA.sla_for

    async def spy(company_id, r, *, config=None, calendar=None):
        seen.append(calendar)
        return await real_sla_for(company_id, r, config=config, calendar=calendar)

    SLA.sla_for = spy
    reqs.docs.append({**req, "request_no": "HR-REQ-2026-002"})
    await SLA.sweep_open_breaches(None, C1, notify=False)
    SLA.sla_for = real_sla_for
    check("every requisition in one sweep was judged against the SAME calendar object -- a "
          "mid-sweep edit must not judge half the run differently",
          len(seen) >= 2 and all(c is seen[0] for c in seen))
    check("and that calendar was the company's, not None", seen[0] == {"2026-01-26",
                                                                       "2026-08-19",
                                                                       "2026-10-02"})

    # =========================================================================
    section("8. Config, capabilities and the declared shape")
    # =========================================================================
    check("the flag defaults OFF", M.default_config()[M.CONFIG_HONOUR_HOLIDAYS] is False)
    check("it is declared as a flag, not a number",
          M.config_spec(M.CONFIG_HONOUR_HOLIDAYS)["kind"] == M.CONFIG_KIND_FLAG)
    check("its note warns that turning it on moves existing breach figures",
          "breached" in M.config_spec(M.CONFIG_HONOUR_HOLIDAYS)["note"].lower())
    check("the calendar reuses the settings capabilities rather than minting its own -- a "
          "holiday moves a compliance due date, so it belongs with the numbers it moves",
          M.Cap.SETTINGS_WRITE in M.ROLE_CAPABILITIES[M.HrmsRole.MD]
          and M.Cap.SETTINGS_WRITE in M.ROLE_CAPABILITIES[M.HrmsRole.FINANCE]
          and M.Cap.SETTINGS_WRITE not in M.ROLE_CAPABILITIES[M.HrmsRole.HR])
    check("HR can still SEE the calendar it plans against",
          M.Cap.SETTINGS_READ in M.ROLE_CAPABILITIES[M.HrmsRole.HR])
    check("the collection carries a UNIQUE (company, date) index -- two rows for one day "
          "would be counted once by the maths and twice by the screen",
          any(c == M.COLL_HOLIDAYS and k == [("company_id", 1), ("holiday_date", 1)]
              and o.get("unique") for c, k, o in M.HRMS_INDEXES))
    row = await store[M.COLL_HOLIDAYS].find_one({"company_id": C1})
    check("a holiday row carries no `request_no` -- it belongs to a company, not a vacancy",
          row is not None and "request_no" not in row)
    check("the calendar is capped, so a bad import cannot turn SLA maths into a scan",
          M.MAX_HOLIDAYS == 500)

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed_n, total = sum(results), len(results)
    print(f"  {passed_n}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed_n != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
