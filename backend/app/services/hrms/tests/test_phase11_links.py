"""Phase 11-R Item 1 verification harness -- the public-link registry.

Covers: registration from the four mint sites, open/consume tracking, computed expiry,
revocation ENFORCED on the public surface, the legacy-link escape hatch, reissue delegation,
the MANAGER row scope, and the capability matrix.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_links   (from backend/)
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
OTHER = "C2"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
PAST = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD = str(ObjectId()), str(ObjectId())

    reqs = FakeCollection([
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-001", "company_id": COMPANY,
         "created_by": U_HOD, "designation_name": "Analyst"},
        {"_id": ObjectId(), "request_no": "HR-REQ-2026-002", "company_id": COMPANY,
         "created_by": U_HR, "designation_name": "Engineer"},
    ])
    links_coll = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()
    offers_coll = FakeCollection()

    store = {M.COLL_LINKS: links_coll, M.COLL_REQUISITIONS: reqs,
             M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_log,
             M.COLL_OFFERS: offers_coll, "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_link_service as LS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_public_guard as G
    for mod in (LS, AUD, IDS):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}
    EMP = {"_id": str(ObjectId()), "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}

    try:
        # =================================================================
        section("Registration")
        # =================================================================
        row = await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.OFFER, code="offercode0000000000A",
            target_type="offer", target_id="OFR-2026-001", actor=HR,
            candidate_name="Asha Rao", request_no="HR-REQ-2026-001")
        check("register_link returns the row", bool(row and row.get("link_id")))
        check("link_id uses the LNK format", str(row["link_id"]).startswith("LNK-"))
        check("path is derived from the kind", row["path"] == "/offer/offercode0000000000A")
        check("starts Active", row["status"] == M.LinkStatus.ACTIVE.value)
        check("starts with zero opens", row["open_count"] == 0)
        check("never_opened is surfaced", row["never_opened"] is True)
        check("an audit row was written",
              any(a["action"] == M.AUDIT_LINK_ISSUED for a in audit_log.docs))

        again = await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.OFFER, code="offercode0000000000A",
            target_type="offer", target_id="OFR-2026-001", actor=HR)
        check("registering the same code twice is idempotent",
              len([d for d in links_coll.docs if d["code"] == "offercode0000000000A"]) == 1
              and again["link_id"] == row["link_id"])

        bad = await LS.register_link(
            company_id=COMPANY, kind="not-a-kind", code="x", target_type="offer",
            target_id="X", actor=HR)
        check("an unknown kind is refused, not raised", bad is None)

        # The contract that matters most: a registry failure must never raise into the
        # business action that triggered it.
        broken = FakeCollection()

        async def boom(*a, **k):
            raise RuntimeError("registry is down")
        broken.find_one = boom
        store[M.COLL_LINKS] = broken
        survived = await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.ASSESSMENT, code="assess00000000000000",
            target_type="candidate", target_id="ASM-1", actor=HR)
        check("a registry outage returns None rather than raising", survived is None)
        store[M.COLL_LINKS] = links_coll

        # =================================================================
        section("Open and consume tracking")
        # =================================================================
        await LS.record_open("offercode0000000000A")
        await LS.record_open("offercode0000000000A")
        doc = await links_coll.find_one({"code": "offercode0000000000A"})
        check("opens are counted", doc["open_count"] == 2)
        check("first sighting is recorded", doc["first_opened_at"] is not None)
        check("last sighting is recorded", doc["last_opened_at"] is not None)
        first = doc["first_opened_at"]
        await LS.record_open("offercode0000000000A")
        doc = await links_coll.find_one({"code": "offercode0000000000A"})
        check("the first sighting is never overwritten", doc["first_opened_at"] == first)

        await LS.record_open("no-such-code")
        check("tracking an unknown code is silent", True)

        await LS.record_consumed("offercode0000000000A")
        doc = await links_coll.find_one({"code": "offercode0000000000A"})
        check("consumption is recorded", doc["status"] == M.LinkStatus.CONSUMED.value)
        check("consumed links stay LIVE (a candidate may re-read their page)",
              M.LinkStatus.CONSUMED in M.LIVE_LINK_STATUSES)

        # =================================================================
        section("Computed expiry -- nothing is stored")
        # =================================================================
        expired = {"status": M.LinkStatus.ACTIVE.value, "expires_at": PAST}
        check("a past-expiry Active link reads Expired",
              M.effective_link_status(expired, TODAY) == M.LinkStatus.EXPIRED.value)
        check("the stored value is untouched", expired["status"] == M.LinkStatus.ACTIVE.value)
        check("a future expiry stays Active",
              M.effective_link_status(
                  {"status": M.LinkStatus.ACTIVE.value, "expires_at": FUTURE}, TODAY)
              == M.LinkStatus.ACTIVE.value)
        check("Revoked outranks expiry (the human decision is more informative)",
              M.effective_link_status(
                  {"status": M.LinkStatus.REVOKED.value, "expires_at": PAST}, TODAY)
              == M.LinkStatus.REVOKED.value)
        check("a document with no status at all reads Active",
              M.effective_link_status({}, TODAY) == M.LinkStatus.ACTIVE.value)

        # =================================================================
        section("Revocation is ENFORCED, not merely displayed")
        # =================================================================
        live = await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.ONBOARDING, code="onbcode00000000000001",
            target_type="onboarding", target_id="ONB-2026-001", actor=HR,
            request_no="HR-REQ-2026-001")

        # The guard reads through the real get_collection, so point it at the fakes too.
        G_original = getattr(G, "get_collection", None)
        await G.assert_link_live("onbcode00000000000001")
        check("a live link passes the public guard", True)

        await LS.revoke(HR, COMPANY, live["link_id"], "sent to the wrong address")
        await expect_http("a revoked link on the public surface",
                          G.assert_link_live("onbcode00000000000001"), 410)
        revoked = await links_coll.find_one({"code": "onbcode00000000000001"})
        check("the reason is kept for the audit trail",
              revoked["revoke_reason"] == "sent to the wrong address")
        check("revoking is audited",
              any(a["action"] == M.AUDIT_LINK_REVOKED for a in audit_log.docs))

        await expect_http("revoking twice", LS.revoke(HR, COMPANY, live["link_id"]),
                          409, "already revoked")

        # The message must be the EXISTING vague one -- a revoked link must not be
        # distinguishable from a closed position.
        from fastapi import HTTPException
        try:
            await G.assert_link_live("onbcode00000000000001")
        except HTTPException as e:
            check("the refusal uses the generic CLOSED_LINK wording",
                  str(e.detail) == G.CLOSED_LINK)

        # =================================================================
        section("Legacy links are never locked out")
        # =================================================================
        await G.assert_link_live("a-code-issued-before-this-phase")
        check("an unregistered code passes (no migration required)", True)
        await G.assert_link_live("")
        check("an empty code is a no-op", True)

        # Fails OPEN when the registry is unreachable -- availability of a candidate's
        # onboarding form outranks perfect bookkeeping.
        store[M.COLL_LINKS] = broken
        await G.assert_link_live("offercode0000000000A")
        check("an unreachable registry fails OPEN", True)
        store[M.COLL_LINKS] = links_coll

        # =================================================================
        section("Listing, filters and stats")
        # =================================================================
        await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.APPLY, code="CP-AAA111",
            target_type="posting", target_id="CP-AAA111", actor=HR,
            request_no="HR-REQ-2026-002", expires_at=PAST)
        await LS.register_link(
            company_id=OTHER, kind=M.LinkKind.APPLY, code="LI-ZZZ999",
            target_type="posting", target_id="LI-ZZZ999", actor=HR)

        listing = await LS.list_links(HR, COMPANY)
        codes = {r["code"] for r in listing["links"]}
        check("another tenant's links are invisible", "LI-ZZZ999" not in codes)
        check("this company's links are listed", "CP-AAA111" in codes)
        check("the expired one is reported Expired",
              next(r for r in listing["links"] if r["code"] == "CP-AAA111")["status"]
              == M.LinkStatus.EXPIRED.value)
        check("stats count the computed statuses",
              listing["stats"]["expired"] >= 1 and listing["stats"]["revoked"] >= 1)

        by_kind = await LS.list_links(HR, COMPANY, kind="apply")
        check("the kind filter applies", all(r["kind"] == "apply" for r in by_kind["links"]))
        by_status = await LS.list_links(HR, COMPANY, status="Revoked")
        check("the status filter runs on the COMPUTED status",
              all(r["status"] == "Revoked" for r in by_status["links"])
              and by_status["total"] >= 1)
        searched = await LS.list_links(HR, COMPANY, search="Asha")
        check("search matches the denormalised candidate name", searched["total"] >= 1)

        # =================================================================
        section("MANAGER row scope -- fails closed")
        # =================================================================
        mgr = await LS.list_links(HOD, COMPANY)
        check("a manager is told their view is narrowed",
              mgr["scoped_to_own_requisitions"] is True)
        check("a manager sees only their own requisitions' links",
              all(r.get("request_no") == "HR-REQ-2026-001" for r in mgr["links"]))
        check("HR-REQ-2026-002's link is hidden from them",
              "CP-AAA111" not in {r["code"] for r in mgr["links"]})

        stranger = {"_id": str(ObjectId()), "role": "clientuser",
                    "_source_collection": "learners", "company_id": COMPANY,
                    "governance_role": "HOD"}
        none_seen = await LS.list_links(stranger, COMPANY)
        check("a manager who raised nothing sees NOTHING (fails closed)",
              none_seen["total"] == 0)

        # CP-AAA111 belongs to HR-REQ-2026-002, which HR raised — not this manager's.
        other_link = await links_coll.find_one({"code": "CP-AAA111"})
        await expect_http("a manager opening a link outside their requisitions",
                          LS.get_link(HOD, COMPANY, other_link["link_id"]), 404)

        # =================================================================
        section("Reissue delegates to the owning service")
        # =================================================================
        await offers_coll.insert_one({
            "offer_no": "OFR-2026-002", "company_id": COMPANY,
            "access_code": "reissueme00000000001", "uk": "CAN-001"})
        target = await LS.register_link(
            company_id=COMPANY, kind=M.LinkKind.OFFER, code="reissueme00000000001",
            target_type="offer", target_id="OFR-2026-002", actor=HR,
            request_no="HR-REQ-2026-001")

        out = await LS.reissue(HR, COMPANY, target["link_id"])
        owner = await offers_coll.find_one({"offer_no": "OFR-2026-002"})
        check("the OWNING record got the new code",
              owner["access_code"] != "reissueme00000000001")
        check("the new code is registered",
              out["link"]["code"] == owner["access_code"])
        old = await links_coll.find_one({"code": "reissueme00000000001"})
        check("the old link is revoked", old["status"] == M.LinkStatus.REVOKED.value)
        check("the reason says why", old["revoke_reason"] == "Reissued")
        check("reissue is audited",
              any(a["action"] == M.AUDIT_LINK_REISSUED for a in audit_log.docs))

        apply_row = await links_coll.find_one({"code": "CP-AAA111"})
        await expect_http(
            "reissuing an APPLY link (its code is on published job boards)",
            LS.reissue(HR, COMPANY, apply_row["link_id"]), 409, "job board")

        # =================================================================
        section("Capabilities")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR reads and manages",
              can(HR, M.Cap.LINK_READ) and can(HR, M.Cap.LINK_MANAGE))
        check("a manager reads but cannot manage",
              can(HOD, M.Cap.LINK_READ) and not can(HOD, M.Cap.LINK_MANAGE))
        check("a plain employee has neither",
              not can(EMP, M.Cap.LINK_READ) and not can(EMP, M.Cap.LINK_MANAGE))
        internal = {"_id": str(ObjectId()), "role": "admin", "_source_collection": "staff"}
        check("Sparsh support can operate the registry (that IS support work)",
              can(internal, M.Cap.LINK_READ) and can(internal, M.Cap.LINK_MANAGE))

        # =================================================================
        section("Declarations")
        # =================================================================
        check("every LinkKind has a path template",
              set(M.LINK_PATHS) == set(M.LinkKind))
        check("apply links are NOT reissuable",
              M.LinkKind.APPLY not in M.REISSUABLE_KINDS)
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES if c == M.COLL_LINKS]
        check("the code index is unique",
              any(n == "uniq_code" for _c, n in names))
        check("index names are unique within the collection",
              len(names) == len(set(names)))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
