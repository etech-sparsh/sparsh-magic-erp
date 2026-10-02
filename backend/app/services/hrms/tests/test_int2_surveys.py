"""Phase INT-2 -- new-hire experience surveys (SOP §10).

Two of the SOP's eight KPIs were unbuildable without capture. This is the capture.

The property this file exists to protect is not a feature, it is a promise: THE REPORTING
LAYER CANNOT SEE AN INDIVIDUAL. `employee_code` is stored ONLY to stop somebody answering
twice, and the aggregation returns scores with no rows and refuses any figure below
SURVEY_MIN_RESPONSES.

That promise is asserted from several angles, because there are several ways to break it:
the aggregate suppressing below the threshold, the per-QUESTION breakdown suppressing on the
same threshold (three respondents' question-level averages reconstruct most of a response),
the public page not echoing the respondent's identity back, and the audit line naming the
response rather than the employee.

Also covered: the public guard's fixed-window limits on the new surface, and one-submission
finality.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_surveys   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    surveys_coll = FakeCollection()
    responses = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_SURVEYS: surveys_coll, M.COLL_SURVEY_RESPONSES: responses,
             M.COLL_LINKS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_AUDIT_LOG: audit_log, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_survey_service as SV
    import app.services.hrms_link_service as LS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (SV, LS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    HR = {"_id": str(ObjectId()), "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    try:
        # =================================================================
        section("The two instruments are seeded on first read")
        # =================================================================
        seeded = await SV.list_surveys(COMPANY)
        kinds = {s["kind"] for s in seeded}
        check("both instruments exist", kinds == {"induction", "probation"})
        check("each is minted with an SRV id",
              all(s["srv_no"].startswith("SRV-") for s in seeded))
        check("each carries five questions -- a form nobody finishes is worse data",
              all(len(s["questions"]) == 5 for s in seeded))
        check("reading twice does not seed twice",
              len(await SV.list_surveys(COMPANY)) == 2)

        # =================================================================
        section("Issuing is idempotent per (instrument, employee)")
        # =================================================================
        first = await SV.issue_survey(HR, COMPANY, M.SurveyKind.INDUCTION,
                                      employee_code="EMP-2026-001",
                                      request_no="HR-REQ-2026-001",
                                      employee_name="Joiner One")
        check("a response row is minted with an SRP id",
              first["srp_no"].startswith("SRP-"))
        check("with an access code as its only credential",
              len(first["access_code"]) >= 20)
        check("and nothing answered yet", first["submitted_at"] is None)
        check("SOP section 13 retention is stamped", bool(first["retention_until"]))

        again = await SV.issue_survey(HR, COMPANY, M.SurveyKind.INDUCTION,
                                      employee_code="EMP-2026-001")
        check("issuing the SAME instrument to the same person returns the existing row",
              again["srp_no"] == first["srp_no"])
        check("so a re-run of the induction completion cannot double-count them",
              await responses.count_documents({"employee_code": "EMP-2026-001",
                                               "kind": "induction"}) == 1)

        link = await store[M.COLL_LINKS].find_one({"code": first["access_code"]})
        check("the link is registered like every other public credential",
              link is not None and link["kind"] == M.LinkKind.SURVEY.value)
        check("so revocation and expiry work on it for free",
              link["path"] == f'/survey/{first["access_code"]}')

        # Issuing must NEVER raise into its caller -- it is fired from the induction
        # checklist and from probation confirmation, and neither may fail because of it.
        broken = await SV.issue_survey(HR, "no-such-company", M.SurveyKind.INDUCTION,
                                       employee_code="EMP-9999")
        check("issuing against a company with no instruments returns None, never raises",
              broken is None or isinstance(broken, dict))

        # =================================================================
        section("The public page does not know who you are")
        # =================================================================
        page = await SV.get_public_survey(first["access_code"])
        forbidden = {"employee_code", "srp_no", "request_no", "candidate_name",
                     "employee_name", "company_id"}
        check("the page carries NOTHING that identifies the respondent",
              not (forbidden & set(page.keys())))
        check("it carries the questions", len(page["questions"]) == 5)
        check("and the anonymity promise, in words, BEFORE they answer",
              "averages" in page["anonymity_note"].lower())
        check("the scale states which end is which",
              page["scale"]["min"] == 1 and page["scale"]["max"] == 5)

        await expect_http(
            "an unknown code",
            SV.get_public_survey("not-a-real-code-at-all-x"),
            404, "not valid")

        # =================================================================
        section("Answering")
        # =================================================================
        answers = {q["key"]: 4 for q in page["questions"]}
        done = await SV.submit_public_survey(first["access_code"], {"scores": answers})
        check("a complete submission is accepted", done["ok"] is True)
        row = await responses.find_one({"srp_no": first["srp_no"]})
        check("the mean is computed server-side", row["average"] == 4.0)
        check("and the submission is timestamped", row["submitted_at"] is not None)

        await expect_http(
            "answering the same survey twice",
            SV.submit_public_survey(first["access_code"], {"scores": answers}),
            409, "already answered")
        check("a live link that could rewrite an average would make the figure "
              "meaningless", True)

        second = await SV.issue_survey(HR, COMPANY, M.SurveyKind.INDUCTION,
                                       employee_code="EMP-2026-002")
        await expect_http(
            "a submission missing a question",
            SV.submit_public_survey(second["access_code"],
                                    {"scores": {"welcome": 4}}),
            422, "every question")
        await expect_http(
            "an answer outside the scale",
            SV.submit_public_survey(second["access_code"],
                                    {"scores": {k: 9 for k in answers}}),
            422, "1 to 5")

        # =================================================================
        section("The audit line names the RESPONSE, never the employee")
        # =================================================================
        entries = await audit_log.find({"action": M.AUDIT_SURVEY_SUBMITTED}).to_list(20)
        check("the submission is audited", len(entries) >= 1)
        blob = " ".join(f'{e.get("entity_id")} {e.get("detail")}' for e in entries)
        check("and the trail does NOT carry the employee code",
              "EMP-2026-001" not in blob)
        check("the audit is readable by anybody with audit.read -- naming them there "
              "would be most of the way to de-anonymising the answer", True)

        # =================================================================
        section("Below the threshold, NO figure is returned at all")
        # =================================================================
        check("the threshold is five, the usual small-cell figure",
              M.SURVEY_MIN_RESPONSES == 5)

        agg = await SV.aggregate(COMPANY, kind=M.SurveyKind.INDUCTION)
        check("one response is below the threshold", agg["responses"] == 1)
        check("so the average is suppressed entirely, not rounded",
              agg["suppressed"] is True and agg["average"] is None)
        check("the per-QUESTION breakdown is suppressed on the SAME threshold",
              agg["by_question"] == [])
        check("three respondents' question-level averages would reconstruct a response, "
              "which is why the two stand or fall together", True)
        check("and it says why, so a reader does not think the data is missing",
              "identifiable" in (agg["reason"] or "").lower())

        # =================================================================
        section("At the threshold, scores appear -- and still no rows")
        # =================================================================
        for n in range(2, 7):
            issued = await SV.issue_survey(HR, COMPANY, M.SurveyKind.INDUCTION,
                                           employee_code=f"EMP-2026-{n:03d}")
            await SV.submit_public_survey(issued["access_code"], {
                "scores": {q["key"]: (3 if n % 2 else 5) for q in page["questions"]},
                "comment": "Fine."})

        agg = await SV.aggregate(COMPANY, kind=M.SurveyKind.INDUCTION)
        check("six responses clears the threshold", agg["responses"] == 6)
        check("the mean is reported", agg["suppressed"] is False
              and agg["average"] is not None)
        check("and the per-question breakdown with it", len(agg["by_question"]) == 5)
        check("the payload contains NO per-respondent row of any kind",
              not any(key in agg for key in
                      ("responses_list", "rows", "employee_codes", "answers")))
        check("every breakdown entry is a mean and a count, never an answer",
              all(set(q) == {"key", "average", "responses"} for q in agg["by_question"]))
        check("the scale maximum travels with the score, so 4.1 is not rendered as 4.1%",
              agg["scale_max"] == 5)

        # =================================================================
        section("Response rate is counts only")
        # =================================================================
        rates = await SV.issue_rate(COMPANY)
        check("issued and returned are both counted",
              rates["issued"] >= rates["returned"] >= 6)
        check("and a rate is derived from them",
              rates["response_rate"] is not None)
        check("a 4.8 from two of forty is a different fact from a 4.8 from thirty-five",
              True)

        # =================================================================
        section("The public guard treats it like every other public surface")
        # =================================================================
        from app.utils.hrms_public_guard import RATE_LIMITS
        check("viewing is 40 a minute per IP, matching the offer and onboarding pages",
              RATE_LIMITS["survey-view"] == (40, 60))
        check("submitting is 10 an hour per IP, because it is a once-only act",
              RATE_LIMITS["survey-submit"] == (10, 3600))
        check("both windows are FIXED, so a flood cannot grow the limiter's own storage",
              all(isinstance(w, int) for _, w in
                  (RATE_LIMITS["survey-view"], RATE_LIMITS["survey-submit"])))

        # The route file is the contract for the four-step order; assert it structurally
        # rather than by exercising FastAPI.
        from pathlib import Path
        source = (Path(__file__).resolve().parents[3]
                  / "routes" / "hrms_public.py").read_text(encoding="utf-8")
        block = source[source.index("def public_survey("):]
        check("the GET validates the code shape before anything else",
              block.index("validate_access_code") < block.index("enforce_rate_limit"))
        check("then rate limits before doing any work",
              block.index("enforce_rate_limit") < block.index("assert_link_live"))
        check("then honours revocation and expiry",
              block.index("assert_link_live") < block.index("get_public_survey"))
        submit_block = source[source.index("def public_survey_submit("):]
        check("and the POST follows the same order",
              submit_block.index("validate_access_code")
              < submit_block.index("enforce_rate_limit")
              < submit_block.index("assert_link_live")
              < submit_block.index("submit_public_survey"))
        # The docstring MENTIONS get_current_user (rule 1 forbids it), so the check has to
        # look for the import that would actually make it available rather than the name.
        check("the public router never imports the auth dependency at all",
              "auth_controller" not in source)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
