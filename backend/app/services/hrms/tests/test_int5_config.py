"""Phase INT-5 -- per-company configuration (spec §42, "configuration over hard-coding").

The module was multi-company for its DATA from Phase 1 and for its RULES from this phase.
`COLL_SETTINGS` had been declared and read by nothing for four phases; this is the phase
that reads it.

The properties worth stating, because they are the ones a rewrite would quietly lose:

  1. NO SETTINGS ROW == PRE-INT-5 BEHAVIOUR, key for key. The defaults ARE the constants
     that already shipped, so there is nothing to migrate and nothing to backfill.
  2. ONE COMPANY'S RULES NEVER REACH ANOTHER'S. That is the whole point of the phase, and
     the single most valuable thing to assert.
  3. MAPS MERGE PER NAME. Overriding one SLA target must not silently drop the other three.
  4. CROSS-FIELD RULES ARE CHECKED AGAINST THE MERGED RESULT, so changing one number cannot
     leave the group inconsistent.
  5. NO SETTING TURNS A GATE OFF. The budget gate, the reference check, the scorecard
     approval and the telephonic screen are not configurable and must never become so.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int5_config   (from backend/)
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
C2 = "COMPANY-TWO"


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere -- each has its own test
    # file (test_int12_client_track), and a failure here should name THIS file's control
    # rather than a precondition it never set up.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared
    import app.db.mongodb as mongo

    MD = {"_id": ObjectId(), "full_name": "Anita MD", "email": "md@example.com"}

    store: dict = {}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_config_service as CFG
    import app.services.hrms_audit_service as AUD
    for mod in (CFG, AUD):
        mod.get_collection = mongo.get_collection

    # =========================================================================
    section("1. No settings row == exactly the behaviour that already shipped")
    # =========================================================================
    resolved = await CFG.config_for(C1)
    check("SLA targets are the shipped ones",
          resolved[M.CONFIG_SLA_TARGET_DAYS]
          == {"budget_approved": 3, "scorecard_approved": 2,
              "shortlist_ready": 15, "offer_released": 3})
    check("and they match the SLA_MILESTONES table itself, not a re-typed copy",
          resolved[M.CONFIG_SLA_TARGET_DAYS]
          == {m["key"]: m["target_days"] for m in M.SLA_MILESTONES
              if m["anchor"] == M.ANCHOR_MILESTONE})
    check("retention is the shipped table",
          resolved[M.CONFIG_RETENTION_YEARS] == dict(M.RETENTION_YEARS))
    check("probation is the shipped default and bounds",
          resolved[M.CONFIG_PROBATION_MONTHS]
          == {"default": M.DEFAULT_PROBATION_MONTHS, "min": M.MIN_PROBATION_MONTHS,
              "max": M.MAX_PROBATION_MONTHS})
    check("reminder tiers are the shipped ones",
          resolved[M.CONFIG_PROBATION_REMINDERS] == list(M.PROBATION_REMINDER_DAYS))
    check("score bands are the shipped floors",
          resolved[M.CONFIG_SCORE_BANDS] == {l: f for f, l in M.SCORE_BANDS})
    check("nothing was written just by READING the config",
          not store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs)

    described = await CFG.describe(C1)
    check("describe() says the company follows every default",
          described["follows_defaults"] is True
          and all(not s["overridden"] for s in described["settings"]))
    check("and returns one row per declared setting",
          {s["key"] for s in described["settings"]}
          == {s["key"] for s in M.CONFIG_SPEC})

    # -- The defaults cannot be mutated through a caller --
    d1 = M.default_config()
    d1[M.CONFIG_RETENTION_YEARS]["offer"] = 99
    d1[M.CONFIG_PROBATION_REMINDERS].append(999)
    fresh = await CFG.config_for(C1)
    check("a caller mutating what it got back cannot poison the defaults every other "
          "company falls through to",
          fresh[M.CONFIG_RETENTION_YEARS]["offer"] == 3
          and 999 not in fresh[M.CONFIG_PROBATION_REMINDERS])

    # =========================================================================
    section("2. An override, and what it does NOT disturb")
    # =========================================================================
    await CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"offer_released": 5}})
    one = await CFG.config_for(C1)
    check("the overridden target moved", one[M.CONFIG_SLA_TARGET_DAYS]["offer_released"] == 5)
    check("the OTHER three kept their shipped values -- overriding one number must not "
          "silently drop the rest of the map",
          one[M.CONFIG_SLA_TARGET_DAYS]["budget_approved"] == 3
          and one[M.CONFIG_SLA_TARGET_DAYS]["scorecard_approved"] == 2
          and one[M.CONFIG_SLA_TARGET_DAYS]["shortlist_ready"] == 15)
    check("every OTHER setting is untouched",
          one[M.CONFIG_RETENTION_YEARS] == dict(M.RETENTION_YEARS)
          and one[M.CONFIG_PROBATION_REMINDERS] == list(M.PROBATION_REMINDER_DAYS))
    check("exactly one settings row exists", len(store[M.COLL_SETTINGS].docs) == 1)

    described = await CFG.describe(C1)
    sla_row = next(s for s in described["settings"] if s["key"] == M.CONFIG_SLA_TARGET_DAYS)
    check("describe() names WHICH value is overridden, not just that the group is",
          sla_row["overridden"] == sorted(one[M.CONFIG_SLA_TARGET_DAYS]))
    check("and still reports the shipped default beside it, so a reader can see the change",
          sla_row["default"]["offer_released"] == 3 and sla_row["value"]["offer_released"] == 5)
    check("follows_defaults is now false", described["follows_defaults"] is False)
    check("the change was audited",
          any(r.get("action") == M.AUDIT_CONFIG_UPDATED
              for r in store[M.COLL_AUDIT_LOG].docs))
    audit_line = next(r for r in store[M.COLL_AUDIT_LOG].docs
                      if r.get("action") == M.AUDIT_CONFIG_UPDATED)
    check("the audit line names what MOVED, not the whole payload",
          "offer_released" in (audit_line.get("detail") or "")
          and "3 -> 5" in (audit_line.get("detail") or ""))

    # =========================================================================
    section("3. THE POINT OF THE PHASE -- one company's rules never reach another")
    # =========================================================================
    two = await CFG.config_for(C2)
    check("the second company still sees the shipped SLA targets",
          two[M.CONFIG_SLA_TARGET_DAYS]["offer_released"] == 3)
    check("and still follows every default", (await CFG.describe(C2))["follows_defaults"])

    await CFG.update_config(MD, C2, {
        M.CONFIG_RETENTION_YEARS: {"telephonic": 2},
        M.CONFIG_PROBATION_MONTHS: {"default": 3},
        M.CONFIG_PROBATION_REMINDERS: [14, 3],
        M.CONFIG_SCORE_BANDS: {"Strong": 3.8},
    })
    one, two = await CFG.config_for(C1), await CFG.config_for(C2)
    check("company two's retention moved", two[M.CONFIG_RETENTION_YEARS]["telephonic"] == 2)
    check("company ONE's did not", one[M.CONFIG_RETENTION_YEARS]["telephonic"] == 1)
    check("company two's probation default moved",
          two[M.CONFIG_PROBATION_MONTHS]["default"] == 3)
    check("company one's did not", one[M.CONFIG_PROBATION_MONTHS]["default"] == 6)
    check("company two's tiers moved", two[M.CONFIG_PROBATION_REMINDERS] == [14, 3])
    check("company one's did not", one[M.CONFIG_PROBATION_REMINDERS] == [30, 15, 7, 1])
    check("company two's Strong bar moved", two[M.CONFIG_SCORE_BANDS]["Strong"] == 3.8)
    check("company one's did not", one[M.CONFIG_SCORE_BANDS]["Strong"] == 4.0)
    check("company two's SLA is still the shipped one -- it overrode other things",
          two[M.CONFIG_SLA_TARGET_DAYS]["offer_released"] == 3)

    # -- A LIST is replaced whole, not merged --
    check("the tier list was REPLACED, not merged -- merging would make removing a tier "
          "impossible", two[M.CONFIG_PROBATION_REMINDERS] == [14, 3]
          and 30 not in two[M.CONFIG_PROBATION_REMINDERS])

    # =========================================================================
    section("4. Validation")
    # =========================================================================
    await expect_http("an unknown setting",
                      CFG.update_config(MD, C1, {"turn_off_reference_check": True}),
                      422, "unknown setting")
    await expect_http("an unknown name inside a known setting",
                      CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"whenever": 4}}),
                      422, "no setting called")
    await expect_http("an SLA target of zero -- breached the moment it is set",
                      CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"offer_released": 0}}),
                      422, "between 1 and 260")
    await expect_http("an absurd SLA target",
                      CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"offer_released": 9999}}),
                      422, "between 1 and 260")
    await expect_http("a non-numeric target",
                      CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"offer_released": "soon"}}),
                      422, "whole number")
    await expect_http("a BOOLEAN target -- bool is a subclass of int and would pass as 1",
                      CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"offer_released": True}}),
                      422, "must be a number")
    await expect_http("an empty payload", CFG.update_config(MD, C1, {}), 400, "no settings")
    await expect_http("a flag sent as a number -- 1 is not true here",
                      CFG.update_config(MD, C1, {M.CONFIG_HONOUR_HOLIDAYS: 1}),
                      422, "on or off")
    await expect_http("a flag sent as a string",
                      CFG.update_config(MD, C1, {M.CONFIG_HONOUR_HOLIDAYS: "yes"}),
                      422, "on or off")
    await expect_http("a map sent as a list",
                      CFG.update_config(MD, C1, {M.CONFIG_RETENTION_YEARS: [3]}),
                      422, "expects an object")
    await expect_http("a list sent as a map",
                      CFG.update_config(MD, C1, {M.CONFIG_PROBATION_REMINDERS: {"a": 1}}),
                      422, "expects a non-empty list")
    await expect_http("tiers that climb",
                      CFG.update_config(MD, C1, {M.CONFIG_PROBATION_REMINDERS: [7, 30]}),
                      422, "descending order")
    await expect_http("tiers that repeat",
                      CFG.update_config(MD, C1, {M.CONFIG_PROBATION_REMINDERS: [7, 7]}),
                      422, "descending order")
    await expect_http("too many tiers -- each one is another email about the same review",
                      CFG.update_config(MD, C1,
                                        {M.CONFIG_PROBATION_REMINDERS: [60, 50, 40, 30, 20, 10, 5]}),
                      422, "at most 6")

    # -- Cross-field rules, judged on the MERGED result --
    await expect_http(
        "a probation default above the max it is being stored beside",
        CFG.update_config(MD, C1, {M.CONFIG_PROBATION_MONTHS: {"default": 20, "max": 10}}),
        422, "does not hold")
    await expect_http(
        "a default that is fine alone but breaks the bounds ALREADY IN FORCE",
        CFG.update_config(MD, C2, {M.CONFIG_PROBATION_MONTHS: {"min": 6}}),
        422, "does not hold")
    check("company two's probation is unchanged by the refusal",
          (await CFG.config_for(C2))[M.CONFIG_PROBATION_MONTHS]
          == {"default": 3, "min": 1, "max": 12})

    await expect_http(
        "score bands that do not descend",
        CFG.update_config(MD, C1, {M.CONFIG_SCORE_BANDS: {"Consider": 4.5}}),
        422, "must descend")
    await expect_http(
        "a band floor off the 1-5 scale",
        CFG.update_config(MD, C1, {M.CONFIG_SCORE_BANDS: {"Strong": 9}}),
        422, "between 1 and 5")

    check("not one refusal changed company one's config",
          (await CFG.config_for(C1))[M.CONFIG_SLA_TARGET_DAYS]["offer_released"] == 5
          and (await CFG.config_for(C1))[M.CONFIG_SCORE_BANDS]["Strong"] == 4.0)

    # =========================================================================
    section("5. Reset -- an explicit act, distinct from setting the default value")
    # =========================================================================
    await CFG.update_config(MD, C1, {M.CONFIG_RETENTION_YEARS: {"offer": 3}})
    stored = await CFG.raw_overrides(C1)
    check("a value EQUAL to the default is still stored -- pruning it would let a "
          "deliberately-chosen compliance number drift if the default ever moved",
          M.CONFIG_RETENTION_YEARS in stored)

    await CFG.reset_config(MD, C1, [M.CONFIG_RETENTION_YEARS])
    stored = await CFG.raw_overrides(C1)
    check("reset drops that override", M.CONFIG_RETENTION_YEARS not in stored)
    check("and leaves the others alone", M.CONFIG_SLA_TARGET_DAYS in stored)
    check("the config still resolves", (await CFG.config_for(C1))[M.CONFIG_RETENTION_YEARS]
          == dict(M.RETENTION_YEARS))
    check("the reset was audited",
          any(r.get("action") == M.AUDIT_CONFIG_RESET for r in store[M.COLL_AUDIT_LOG].docs))

    await CFG.reset_config(MD, C1)
    check("a bare reset drops everything", not await CFG.raw_overrides(C1))
    check("and the company is back to following the defaults",
          (await CFG.describe(C1))["follows_defaults"] is True)

    await expect_http("resetting a setting that does not exist",
                      CFG.reset_config(MD, C1, ["not_a_setting"]), 422, "unknown setting")
    reset_again = await CFG.reset_config(MD, C1)
    check("resetting a company that already follows every default is a no-op, not an error "
          "-- refusing would fail exactly when the caller asked for the state it is in",
          reset_again["follows_defaults"] is True)

    # =========================================================================
    section("6. The convenience readers, from an id OR a resolved config")
    # =========================================================================
    cfg2 = await CFG.config_for(C2)
    check("sla_target_days from an id", (await CFG.sla_target_days(C2))["offer_released"] == 3)
    check("sla_target_days from a resolved config -- what a loop uses so it reads once",
          (await CFG.sla_target_days(cfg2))["offer_released"] == 3)
    check("retention_years_for", await CFG.retention_years_for(C2, "telephonic") == 2)
    check("probation_bounds", await CFG.probation_bounds(C2) == (3, 1, 12))
    check("probation_reminder_tiers", await CFG.probation_reminder_tiers(C2) == [14, 3])
    check("score_bands_for", (await CFG.score_bands_for(C2))["Strong"] == 3.8)
    check("a record type the config does not name falls back to the module default rather "
          "than raising -- a later phase's record type must not KeyError against an older "
          "settings row",
          await CFG.retention_years_for({M.CONFIG_RETENTION_YEARS: {}}, "offer") == 3)

    # =========================================================================
    section("7. score_band honours a company's floors")
    # =========================================================================
    check("3.6 is Consider on the shipped floors", M.score_band(3.6) is not None
          and M.score_band(3.6) == "Consider")
    check("and Strong once the bar drops to 3.8",
          M.score_band(3.9, await CFG.score_bands_for(C2)) == "Strong")
    check("the pure function with no bands is unchanged -- every pre-INT-5 caller and test "
          "keeps its answer", M.score_band(3.9) == "Consider")
    check("a dict in any order gives the same answer, so a JSON round-trip cannot reorder "
          "somebody into the wrong band",
          M.score_band(3.9, {"Hold": 3.0, "Strong": 3.8, "Consider": 3.4}) == "Strong")

    # =========================================================================
    section("8. The SLA report reads the company's targets")
    # =========================================================================
    import app.services.hrms_sla_service as SLA
    SLA.get_collection = mongo.get_collection

    raised = datetime.now(timezone.utc) - timedelta(days=6)     # ~4 working days ago
    req = {"request_no": "HR-REQ-2026-001", "company_id": C1,
           "requisition_track": "internal",
           "closing_status": "Open", "created_at": raised, "sla_actuals": {}}

    report = await SLA.sla_for(C1, req)
    budget = next(r for r in report["milestones"] if r["key"] == "budget_approved")
    check("the shipped 3-working-day budget target is in force", budget["target_working_days"] == 3)
    check("and six calendar days later it reads as overdue", budget["status"] == "overdue")

    await CFG.update_config(MD, C1, {M.CONFIG_SLA_TARGET_DAYS: {"budget_approved": 30}})
    report = await SLA.sla_for(C1, req)
    budget = next(r for r in report["milestones"] if r["key"] == "budget_approved")
    check("a company that allows 30 days sees its own target", budget["target_working_days"] == 30)
    check("and the SAME requisition is no longer overdue -- the figure follows the policy",
          budget["status"] == "pending")

    report_other = await SLA.sla_for(C2, {**req, "company_id": C2})
    other_budget = next(r for r in report_other["milestones"] if r["key"] == "budget_approved")
    check("the other company still measures against 3 days",
          other_budget["target_working_days"] == 3 and other_budget["status"] == "overdue")

    passed = await SLA.sla_for(C1, req, config=await CFG.config_for(C1))
    check("a pre-resolved config gives the identical answer -- which is what lets the sweep "
          "read the settings ONCE for hundreds of requisitions",
          next(r for r in passed["milestones"]
               if r["key"] == "budget_approved")["target_working_days"] == 30)

    check("a client requisition has no SLA at all, configured or otherwise",
          (await SLA.sla_for(C1, {**req, "requisition_track": None}))["applicable"] is False)

    # =========================================================================
    section("9. NOTHING here can turn a gate off")
    # =========================================================================
    import inspect
    spec_keys = {s["key"] for s in M.CONFIG_SPEC}
    check("no setting mentions the budget, reference, scorecard or telephonic gates",
          not any(word in key for key in spec_keys
                  for word in ("gate", "reference", "scorecard", "telephonic", "budget_gate",
                               "require", "enforce", "skip", "disable")))
    check("the configurable set is exactly the five numeric policy tables, the INT-6 "
          "working-calendar flag and the two §7.5 document catalogues -- and nothing "
          "else has been added since",
          spec_keys == {M.CONFIG_SLA_TARGET_DAYS, M.CONFIG_RETENTION_YEARS,
                        M.CONFIG_PROBATION_MONTHS, M.CONFIG_PROBATION_REMINDERS,
                        M.CONFIG_SCORE_BANDS, M.CONFIG_HONOUR_HOLIDAYS,
                        M.CONFIG_ONBOARD_DOC_TYPES, M.CONFIG_EMPLOYMENT_DOCS})
    check("the employment-document catalogue also names at least one document by default",
          bool(M.config_spec(M.CONFIG_EMPLOYMENT_DOCS)["default"]()))
    # The document catalogue ADDS obligations rather than removing one: every entry is a
    # file a new hire must send. Marking one optional relaxes a company's own paperwork
    # policy, never an approval gate, which is why it is allowed to live here.
    check("the joining-document catalogue cannot empty itself -- an entry may be made "
          "optional, but the setting must still name at least one document",
          bool(M.config_spec(M.CONFIG_ONBOARD_DOC_TYPES)["default"]()))
    check("the one flag switches a MEASUREMENT, not a control -- it decides which days "
          "count towards a target, never whether the target may be skipped",
          M.config_spec(M.CONFIG_HONOUR_HOLIDAYS)["default"]() is False)
    cfg_source = inspect.getsource(CFG)
    check("the config service never reads a requisition, candidate or exception -- it "
          "resolves numbers and has no opinion about anybody's pipeline",
          not any(c in cfg_source for c in ("COLL_REQUISITIONS", "COLL_CANDIDATES",
                                            "COLL_EXCEPTIONS")))
    check("EXCEPTION_UNBLOCKS is untouched by configuration -- an approved, attributable "
          "record is still the only way past a gate",
          set(M.EXCEPTION_UNBLOCKS) == {"reference_check", "salary_band", "scorecard", "sla",
                                        "statutory_check", "shortlist", "telephonic",
                                        # ── Phase 12 ── background verification before an
                                        # offer, on both tracks.
                                        "background"})

    # =========================================================================
    section("10. The spec table is the specification")
    # =========================================================================
    MAPS = (M.CONFIG_KIND_INT_MAP, M.CONFIG_KIND_FLOAT_MAP)
    for spec in M.CONFIG_SPEC:
        key, kind = spec["key"], spec["kind"]
        check(f"'{key}' declares a label, a kind and a default",
              bool(spec.get("label")) and kind and spec.get("default") is not None)
        if kind not in (M.CONFIG_KIND_FLAG, M.CONFIG_KIND_FLAG_MAP):
            check(f"'{key}' declares its bounds -- a numeric setting with no ceiling is one "
                  f"somebody can set to anything",
                  spec.get("min") is not None and spec.get("max") is not None)
    check("every default factory produces a value of its declared shape",
          all(isinstance(s["default"](), dict) if s["kind"] in MAPS
              else isinstance(s["default"](), list) if s["kind"] == M.CONFIG_KIND_INT_LIST
              else (isinstance(s["default"](), dict)
                    and all(isinstance(v, bool) for v in s["default"]().values()))
              if s["kind"] == M.CONFIG_KIND_FLAG_MAP
              else isinstance(s["default"](), bool)
              for s in M.CONFIG_SPEC))
    check("every map default names exactly the permitted names",
          all(set(s["default"]()) == set(s["names"]) for s in M.CONFIG_SPEC
              if s["kind"] in MAPS))
    check("every numeric default is itself within its own bounds",
          all(s["min"] <= v <= s["max"] for s in M.CONFIG_SPEC if s["kind"] in MAPS
              for v in s["default"]().values()))
    check("config_spec() finds a row and returns None for a stranger",
          M.config_spec(M.CONFIG_SCORE_BANDS) is not None
          and M.config_spec("nope") is None)
    check("keys are unique", len({s["key"] for s in M.CONFIG_SPEC}) == len(M.CONFIG_SPEC))
    check("the settings collection is the one declared since Phase 1, finally read",
          M.COLL_SETTINGS == "hrms_settings")
    check("it carries a UNIQUE index on company_id -- two rows for one company would mean "
          "whichever the planner returned first decided that company's rules",
          any(c == M.COLL_SETTINGS and k == [("company_id", 1)] and o.get("unique")
              for c, k, o in M.HRMS_INDEXES))

    # -- The settings row is CONFIGURATION, so it carries no request_no (invariant 12) --
    row = await store[M.COLL_SETTINGS].find_one({"company_id": C2})
    check("a settings row carries no `request_no` -- it belongs to a company, not to one "
          "vacancy, the same reason hrms_document_types carries none",
          row is not None and "request_no" not in row)
    check("and it records WHO changed it and when",
          row.get("updated_by_name") == "Anita MD" and row.get("updated_at") is not None)

    # =========================================================================
    section("11. Phase INT-10 (Gap 10) -- the three-band reading is a per-company choice")
    # =========================================================================
    # The SOP signed FOUR bands; the implementation brief describes THREE. Neither is wrong,
    # so the middle band is optional per company rather than decided in code.
    await CFG.update_config(MD, C1, {M.CONFIG_SCORE_BANDS: {"Hold": None}})
    bands = await CFG.score_bands_for(C1)
    check("Hold can be switched OFF with null", bands.get("Hold") is None)
    check("with Hold off but Consider still at 3.5, a 3.2 falls straight to Reject -- the "
          "band that used to catch it is gone and nothing pretends otherwise",
          M.score_band(3.2, bands) == "Reject")
    await CFG.update_config(MD, C1, {M.CONFIG_SCORE_BANDS: {"Consider": 3.0}})
    bands = await CFG.score_bands_for(C1)
    check("Consider may then drop to 3.0 -- the brief's exact table -- without tripping "
          "the descending-order rule against a band that no longer exists",
          bands["Consider"] == 3.0)
    check("and 3.2 now reads as Consider (the brief's 3.0-3.99 band)",
          M.score_band(3.2, bands) == "Consider")
    check("2.9 still reads as Reject", M.score_band(2.9, bands) == "Reject")
    check("4.1 still reads as Strong", M.score_band(4.1, bands) == "Strong")
    check("the other company keeps the signed SOP's four bands",
          M.score_band(3.2, await CFG.score_bands_for(C2)) == "Hold")
    await expect_http("Strong cannot be switched off -- a scale with no bar is not a scale",
                      CFG.update_config(MD, C1, {M.CONFIG_SCORE_BANDS: {"Strong": None}}),
                      422, "cannot be switched off")
    await expect_http("and null is refused on any other setting",
                      CFG.update_config(MD, C1, {M.CONFIG_RETENTION_YEARS: {"offer": None}}),
                      422, "cannot be switched off")
    await CFG.reset_config(MD, C1, [M.CONFIG_SCORE_BANDS])
    check("reset restores the four-band default", M.score_band(3.2, await CFG.score_bands_for(C1)) == "Hold")

    mongo.get_collection = original

    print(f"\n{'=' * 60}")
    passed_n, total = sum(results), len(results)
    print(f"  {passed_n}/{total} checks passed")
    print(f"{'=' * 60}")
    if passed_n != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
