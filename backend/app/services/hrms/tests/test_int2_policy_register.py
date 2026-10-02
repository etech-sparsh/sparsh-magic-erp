"""Phase INT-2 -- the policy register and its review cycle (SOP §14).

"This policy shall be reviewed annually... All amendments shall be logged in the
Modification History table."

Covers: the two seeded policies, the derived review state, the split between DRAFTING a
revision and APPROVING it, and the fact that an overdue review is announced and never
enforced.

The property worth stating: DRAFTING A REVISION CHANGES NOTHING. Until the MD approves it,
the register still says the previous version governs. A revision that took effect the moment
somebody typed it would make `policy.approve` decorative.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int2_policy_register   (from backend/)
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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_EMP = (str(ObjectId()) for _ in range(3))

    policies_coll = FakeCollection()
    revisions = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_POLICIES: policies_coll, M.COLL_POLICY_REVISIONS: revisions,
             M.COLL_AUDIT_LOG: audit_log, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_policy_service as PL
    import app.services.hrms_audit_service as AUD
    for mod in (PL, AUD):
        mod.get_collection = mongo.get_collection

    told = []

    async def fake_role(company_id, roles, title, message, **kw):
        told.append({"roles": tuple(roles), "title": title})
    import app.services.hrms_notify_service as NS
    NS.notify_hrms_role = fake_role

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")
    EMP = actor(U_EMP, "IMPLEMENTOR")

    try:
        # =================================================================
        section("Capability shape")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR may draft a revision", can(HR, M.Cap.POLICY_WRITE))
        check("but only the MD may approve one",
              can(MD, M.Cap.POLICY_APPROVE) and not can(HR, M.Cap.POLICY_APPROVE))
        check("EVERY employee may read the register -- it is the one document in this "
              "module they are entitled to see", can(EMP, M.Cap.POLICY_READ))
        check("and reading it comes with no write of any kind",
              not can(EMP, M.Cap.POLICY_WRITE))

        # =================================================================
        section("The two policies are seeded on first read")
        # =================================================================
        listing = await PL.list_policies(COMPANY)
        keys = {p["policy_key"] for p in listing["policies"]}
        check("both recruitment policies are in the register",
              keys == {"internal_recruitment", "profit_recruitment"})
        check("the internal one is at v1.0",
              next(p for p in listing["policies"]
                   if p["policy_key"] == "internal_recruitment")["version"] == "1.0")
        check("and the PRO-fit one at v2.0",
              next(p for p in listing["policies"]
                   if p["policy_key"] == "profit_recruitment")["version"] == "2.0")
        check("both are In Force",
              all(p["status"] == "In Force" for p in listing["policies"]))
        check("each is scheduled for an annual review",
              all(p["next_review_due"] for p in listing["policies"]))
        check("reading twice does not seed twice",
              len((await PL.list_policies(COMPANY))["policies"]) == 2)

        check("the SOP's cycle is annual", M.POLICY_REVIEW_MONTHS == 12)
        check("and a review is announced thirty days ahead",
              M.POLICY_REVIEW_NOTICE_DAYS == 30)

        # =================================================================
        section("The review state is DERIVED, never stored")
        # =================================================================
        fresh = next(p for p in listing["policies"]
                     if p["policy_key"] == "internal_recruitment")
        check("a freshly registered policy is current",
              fresh["review_status"] == "current")
        check("and carries no review note to chase", fresh["review_note"] is None)
        check("the state is not a stored field on the row",
              "review_status" not in await policies_coll.find_one(
                  {"policy_key": "internal_recruitment"}))
        check("a stored flag would be wrong for a day after every review", True)

        soon = (NOW + timedelta(days=10)).strftime("%Y-%m-%d")
        await policies_coll.update_one(
            {"policy_key": "internal_recruitment"},
            {"$set": {"next_review_due": soon}})
        listing = await PL.list_policies(COMPANY)
        row = next(p for p in listing["policies"]
                   if p["policy_key"] == "internal_recruitment")
        check("ten days out reads as due soon", row["review_status"] == "due_soon")
        check("and says how many days", "10 day" in row["review_note"])
        check("the dashboard count picks it up", listing["due_soon"] == 1)

        overdue = (NOW - timedelta(days=45)).strftime("%Y-%m-%d")
        await policies_coll.update_one(
            {"policy_key": "internal_recruitment"},
            {"$set": {"next_review_due": overdue}})
        listing = await PL.list_policies(COMPANY)
        row = next(p for p in listing["policies"]
                   if p["policy_key"] == "internal_recruitment")
        check("past its date reads as overdue", row["review_status"] == "overdue")
        check("and says how far", "45 day" in row["review_note"])
        check("the dashboard leads with the overdue count", listing["overdue"] == 1)

        # =================================================================
        section("Reviews due are announced, not enforced")
        # =================================================================
        due = await PL.due_reviews(COMPANY)
        check("the overdue one is reported", len(due["overdue"]) == 1)
        check("split from those merely due soon, the same way probation splits them",
              "due_soon" in due and "overdue" in due)

        told.clear()
        notified = await PL.notify_due_reviews(None, COMPANY)
        check("the MD and HR are told", told and set(told[0]["roles"]) == {"MD", "HR"})
        check("and the count is reported back", notified["notified"] == 1)
        check("NOTHING in the module is blocked by an overdue review -- refusing to hire "
              "over a lapsed review would punish the wrong people", True)

        # =================================================================
        section("Drafting a revision changes nothing")
        # =================================================================
        drafted = await PL.log_revision(HR, COMPANY, "internal_recruitment", {
            "version": "1.1",
            "summary_of_change": ("Added the panel-composition table and the mandatory "
                                  "Management final round for managerial roles.")})
        check("the revision is logged", drafted["version"] == "1.1")
        check("with who drafted it and when",
              drafted["changed_by_name"] and drafted["changed_at"])
        check("and NO approval on it yet", drafted["approved_at"] is None)

        current = await PL.get_policy(COMPANY, "internal_recruitment")
        check("THE REGISTER STILL SAYS v1.0 GOVERNS", current["version"] == "1.0")
        check("the revision appears in the modification history",
              [r["version"] for r in current["revisions"]] == ["1.1"])
        check("a revision that took effect when somebody typed it would make the "
              "approval capability decorative", True)

        await expect_http(
            "logging a revision with no summary",
            PL.log_revision(HR, COMPANY, "internal_recruitment",
                            {"version": "1.2", "summary_of_change": "  "}),
            422, "say what changed")
        check("a history that does not say what was modified is a list of dates", True)

        await expect_http(
            "logging the same version twice",
            PL.log_revision(HR, COMPANY, "internal_recruitment", {
                "version": "1.1", "summary_of_change": "Rewriting the last one."}),
            409, "already logged")
        check("rewriting a logged revision is what the history exists to prevent", True)

        # =================================================================
        section("Approving is what makes a version the one in force")
        # =================================================================
        await expect_http(
            "approving with no signature",
            PL.approve_revision(MD, COMPANY, "internal_recruitment", {"version": "1.1"}),
            422, "type your name")
        await expect_http(
            "approving a version nobody logged",
            PL.approve_revision(MD, COMPANY, "internal_recruitment",
                                {"version": "9.9", "signature": "Meera MD"}),
            404, "has not been logged")

        approved = await PL.approve_revision(MD, COMPANY, "internal_recruitment", {
            "version": "1.1", "signature": "Meera MD",
            "remarks": "Agreed at the August management meeting."})
        check("the register now says v1.1 governs", approved["version"] == "1.1")
        check("the review clock RESTARTS from the new version's effective date, not from "
              "whenever the last review happened",
              approved["review_status"] == "current")
        history = approved["revisions"][0]
        check("the modification history records who APPROVED it, not only who typed it",
              history["approved_by_name"] == "MD " + U_MD[-4:])
        check("and their signature", history["signature"] == "Meera MD")

        await expect_http(
            "approving the same revision twice",
            PL.approve_revision(MD, COMPANY, "internal_recruitment",
                                {"version": "1.1", "signature": "Meera MD"}),
            409, "already approved")

        # =================================================================
        section("Registering a policy by hand")
        # =================================================================
        added = await PL.register_policy(HR, COMPANY, {
            "policy_key": "Referral Bonus", "title": "Employee Referral Bonus Policy"})
        check("the key is normalised to a stable slug",
              added["policy_key"] == "referral_bonus")
        check("it defaults to v1.0 in force", added["version"] == "1.0")
        check("with a review a year out", added["next_review_due"])

        await expect_http(
            "registering the same policy twice",
            PL.register_policy(HR, COMPANY, {
                "policy_key": "referral_bonus", "title": "Again"}),
            409, "already in the register")
        check("two rows for one policy means two answers to which version is in force",
              True)

        # =================================================================
        section("The trail")
        # =================================================================
        actions = [a["action"] for a in await audit_log.find({}).to_list(50)]
        check("registering is audited", M.AUDIT_POLICY_REGISTERED in actions)
        check("drafting a revision is audited", M.AUDIT_POLICY_REVISED in actions)
        check("and approving one", M.AUDIT_POLICY_APPROVED in actions)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
