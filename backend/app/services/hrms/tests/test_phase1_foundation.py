"""Phase 1 verification harness -- HRMS foundation.

Covers: role translation, the capability model, tenant scoping, the collection/index
registry, atomic id generation, the audit trail, and the router's access gates.

Follows the house test convention (app/assistant/tests/*): self-contained, no pytest, no
new dependencies, fake collections instead of a live database, non-zero exit on failure.

Run:  python -m app.services.hrms.tests.test_phase1_foundation   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    # ASCII only: the Windows console defaults to cp1252 and cannot encode box-drawing
    # characters, which would abort the run before a single check executed.
    print(f"\n-- {title} --")


# -------------------------------------------------------------
# Fakes
# -------------------------------------------------------------
class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, n):
        return self._docs[:n]


class FakeCollection:
    """Minimal in-memory stand-in for a motor collection."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.indexes = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc.get("_id")})()

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        out = [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]
        return FakeCursor(out)

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        doc = await self.find_one(query)
        if doc is None:
            if not upsert:
                return None
            doc = dict(query)
            doc.update(update.get("$setOnInsert", {}))
            doc["seq"] = 0
            self.docs.append(doc)
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v
        return doc

    async def create_index(self, keys, **options):
        self.indexes.append((tuple(keys), options))
        return options.get("name")

    async def count_documents(self, _q):
        return len(self.docs)


class FakeDB:
    def __init__(self):
        self.collections = {}
        self.created = []

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())

    async def list_collection_names(self):
        return list(self.collections.keys())

    async def create_collection(self, name):
        self.created.append(name)
        self.collections.setdefault(name, FakeCollection())


# -------------------------------------------------------------
# Users
# -------------------------------------------------------------
SUPERADMIN = {"_id": "u1", "role": "superadmin", "_source_collection": "staff", "email": "sa@x.com"}
STAFF_ADMIN = {"_id": "u2", "role": "admin", "_source_collection": "staff"}
COACH = {"_id": "u3", "role": "coach", "_source_collection": "staff"}
CLIENT_MD = {"_id": "u4", "role": "clientadmin", "_source_collection": "learners", "company_id": "C1"}
CLIENT_HR = {"_id": "u5", "role": "clientuser", "_source_collection": "learners",
             "company_id": "C1", "governance_role": "HR"}
CLIENT_HOD = {"_id": "u6", "role": "clientuser", "_source_collection": "learners",
              "company_id": "C1", "governance_role": "HOD"}
CLIENT_EMP = {"_id": "u7", "role": "clientuser", "_source_collection": "learners",
              "company_id": "C1", "governance_role": "IMPLEMENTOR"}
CLIENT_BARE = {"_id": "u8", "role": "clientuser", "_source_collection": "learners", "company_id": "C2"}
OTHER_CO_HR = {"_id": "u9", "role": "clientuser", "_source_collection": "learners",
               "company_id": "C2", "governance_role": "HR"}


async def main() -> None:
    from app.models import hrms as M
    from app.utils import hrms_access as A

    # ---------------------------------------------------------
    section("Role translation (positive)")
    # ---------------------------------------------------------
    check("superadmin  -> ADMIN",    A.hrms_role(SUPERADMIN) == M.HrmsRole.ADMIN)
    check("staff admin -> INTERNAL", A.hrms_role(STAFF_ADMIN) == M.HrmsRole.INTERNAL)
    check("coach       -> INTERNAL", A.hrms_role(COACH) == M.HrmsRole.INTERNAL)
    check("clientadmin -> MD",       A.hrms_role(CLIENT_MD) == M.HrmsRole.MD)
    check("gov HR      -> HR",       A.hrms_role(CLIENT_HR) == M.HrmsRole.HR)
    check("gov HOD     -> MANAGER",  A.hrms_role(CLIENT_HOD) == M.HrmsRole.MANAGER)
    check("gov IMPL    -> EMPLOYEE", A.hrms_role(CLIENT_EMP) == M.HrmsRole.EMPLOYEE)

    section("Role translation (negative / edge)")
    check("no governance_role -> EMPLOYEE (lowest rank)", A.hrms_role(CLIENT_BARE) == M.HrmsRole.EMPLOYEE)
    check("None user -> None", A.hrms_role(None) is None)
    check("empty dict -> None", A.hrms_role({}) is None)
    check("unknown role -> None", A.hrms_role({"role": "wat", "_source_collection": "learners"}) is None
          or A.hrms_role({"role": "wat", "_source_collection": "learners"}) == M.HrmsRole.EMPLOYEE)
    check("governance case-insensitive",
          A.hrms_role({**CLIENT_HR, "governance_role": "hr"}) == M.HrmsRole.HR)
    check("governance whitespace tolerated",
          A.hrms_role({**CLIENT_HR, "governance_role": "  HOD "}) == M.HrmsRole.MANAGER)
    # The phantom "MD" role string the source accepted but never created must NOT grant access.
    check("bare 'MD' role string is not a back door",
          A.hrms_role({"role": "MD", "_source_collection": "learners"}) is None)

    section("Identity precedence (source collection > tag > role)")
    check("_source_collection wins over role",
          A.is_internal_user({"role": "clientuser", "_source_collection": "staff"}) is True)
    check("tag used when collection absent",
          A.is_internal_user({"role": "clientuser", "tag": "staff"}) is True)
    check("role used as last resort",
          A.is_internal_user({"role": "admin"}) is True)
    check("client is not internal", A.is_internal_user(CLIENT_HR) is False)

    # ---------------------------------------------------------
    section("Capabilities")
    # ---------------------------------------------------------
    # ADMIN is resolved as "all of Cap" rather than a maintained list, so a capability
    # added in a later phase can never lock the module owner out -- MINUS the five
    # decisions PRO-fit gives the client company, which are theirs alone. Administrative
    # access and decision authority are different things; see CLIENT_DECISION_CAPS and
    # test_client_decision_exclusivity.
    check("ADMIN holds every capability implicitly, bar the client's own",
          A.capabilities_for(SUPERADMIN)
          == set(M.Cap) - M.CLIENT_DECISION_CAPS - M.CLIENT_OWNED_CAPS)
    check("...and what is withheld is exactly the client's decisions and their own forms",
          set(M.Cap) - A.capabilities_for(SUPERADMIN)
          == M.CLIENT_DECISION_CAPS | M.CLIENT_OWNED_CAPS)
    check("no user -> no capabilities", A.capabilities_for(None) == set())
    check("employee CAN access module", A.can(CLIENT_EMP, M.Cap.MODULE_ACCESS))
    check("employee CANNOT read audit", not A.can(CLIENT_EMP, M.Cap.AUDIT_READ))
    check("manager CANNOT read audit", not A.can(CLIENT_HOD, M.Cap.AUDIT_READ))
    check("HR CAN read audit", A.can(CLIENT_HR, M.Cap.AUDIT_READ))
    check("MD CAN administer", A.can(CLIENT_MD, M.Cap.MODULE_ADMIN))
    check("HR CANNOT administer", not A.can(CLIENT_HR, M.Cap.MODULE_ADMIN))
    check("None user is refused everything", not A.can(None, M.Cap.MODULE_ACCESS))
    # A future capability must never lock the owner out -- this is why ADMIN is implicit.
    # The client's five decisions are the one deliberate exception.
    check("ADMIN would hold a capability added later",
          all(A.can(SUPERADMIN, c) for c in M.Cap
              if c not in (M.CLIENT_DECISION_CAPS | M.CLIENT_OWNED_CAPS)))
    check("...but never the client's five, however ADMIN is resolved",
          not any(A.can(SUPERADMIN, c) for c in M.CLIENT_DECISION_CAPS))

    section("Toggle authorization")
    check("superadmin may toggle", A.can_toggle_module(SUPERADMIN))
    check("staff admin may toggle", A.can_toggle_module(STAFF_ADMIN))
    check("coach may NOT toggle", not A.can_toggle_module(COACH))
    check("client MD may NOT toggle", not A.can_toggle_module(CLIENT_MD))
    check("None may NOT toggle", not A.can_toggle_module(None))

    # ---------------------------------------------------------
    section("Tenant scoping (multi-tenant isolation)")
    # ---------------------------------------------------------
    check("client pinned to own company", A.scope_company_id(CLIENT_HR) == "C1")
    check("client CANNOT target another company via query param",
          A.scope_company_id(CLIENT_HR, "C2") == "C1")
    check("other-company user pins to their own", A.scope_company_id(OTHER_CO_HR, "C1") == "C2")
    check("internal may target any company", A.scope_company_id(STAFF_ADMIN, "C9") == "C9")
    check("internal unscoped when unspecified", A.scope_company_id(STAFF_ADMIN) is None)
    check("filter pins client", A.company_filter(CLIENT_HR, "C2") == {"company_id": "C1"})
    check("filter open for internal", A.company_filter(STAFF_ADMIN) == {})

    # ---------------------------------------------------------
    section("Business-id formats (pure)")
    # ---------------------------------------------------------
    check("requisition format", M.format_business_id("requisition", 1, 2026) == "HR-REQ-2026-001")
    check("candidate format (not year-scoped)", M.format_business_id("candidate", 7) == "CAN-007")
    check("employee format", M.format_business_id("employee", 42, 2026) == "EMP-2026-042")
    check("zero-pad holds past 999", M.format_business_id("candidate", 1234) == "CAN-1234")
    check("counter key is company-scoped", M.counter_key("requisition", "C1", 2026) == "C1:requisition:2026")
    check("counter key differs per company",
          M.counter_key("candidate", "C1") != M.counter_key("candidate", "C2"))

    ok = False
    try:
        M.format_business_id("nonsense", 1)
    except ValueError:
        ok = True
    check("unknown id kind raises ValueError", ok)

    ok = False
    try:
        M.format_business_id("requisition", 1)  # year-scoped, year omitted
    except ValueError:
        ok = True
    check("missing year on year-scoped kind raises ValueError", ok)

    # ---------------------------------------------------------
    section("Index registry")
    # ---------------------------------------------------------
    names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
    check("every index is named", all(n for _c, n in names))
    check("index names unique per collection", len(names) == len(set(names)))
    check("audit log indexed by entity",
          any(c == M.COLL_AUDIT_LOG and n == "by_entity" for c, n in names))
    check("audit log indexed for company recency",
          any(c == M.COLL_AUDIT_LOG and n == "by_company_recent" for c, n in names))
    # Invariant, not a snapshot: every provisioned collection must be a declared COLL_*
    # constant. Asserting an exact set here would fail every time a later phase legitimately
    # adds a collection, training us to edit the test instead of reading it.
    declared = {v for k, v in vars(M).items() if k.startswith("COLL_") and isinstance(v, str)}
    check("every provisioned collection is a declared COLL_* constant",
          {c for c, _k, _o in M.HRMS_INDEXES} <= declared)
    check("Phase 1's own collections are still provisioned",
          {M.COLL_AUDIT_LOG, M.COLL_COUNTERS} <= {c for c, _k, _o in M.HRMS_INDEXES})
    check("all collection names are hrms_-prefixed",
          all(v.startswith("hrms_") for k, v in vars(M).items()
              if k.startswith("COLL_") and isinstance(v, str)))

    section("Idempotent provisioning")
    from app.db.mongodb import _ensure_hrms_collections
    db = FakeDB()
    await _ensure_hrms_collections(db)
    first_created = list(db.created)
    first_index_count = sum(len(c.indexes) for c in db.collections.values())
    await _ensure_hrms_collections(db)   # second startup
    check("collections created once only", db.created == first_created)
    check("re-running does not duplicate collections",
          len(set(db.created)) == len(db.created))
    check("indexes re-declared idempotently (create_index is upsert-like)",
          sum(len(c.indexes) for c in db.collections.values()) == first_index_count * 2)

    # A provisioning failure must never take startup down.
    class ExplodingDB(FakeDB):
        async def list_collection_names(self):
            raise RuntimeError("mongo is having a day")

    await _ensure_hrms_collections(ExplodingDB())
    check("provisioning failure is swallowed, never blocks startup", True)

    # ---------------------------------------------------------
    section("Atomic id generation")
    # ---------------------------------------------------------
    import app.services.hrms_id_service as ids
    import app.db.mongodb as mongo

    counters = FakeCollection()
    audit_coll = FakeCollection()
    fake_map = {M.COLL_COUNTERS: counters, M.COLL_AUDIT_LOG: audit_coll}
    original_get_collection = mongo.get_collection
    mongo.get_collection = lambda name: fake_map.setdefault(name, FakeCollection())
    ids.get_collection = mongo.get_collection

    try:
        seqs = [await ids.next_sequence("requisition", "C1", 2026) for _ in range(5)]
        check("sequence increments 1..5", seqs == [1, 2, 3, 4, 5])

        # 50 concurrent allocations must produce 50 distinct numbers -- the exact race the
        # source's scan-for-max approach lost (BACKEND_ANALYSIS Risk #12).
        concurrent = await asyncio.gather(
            *[ids.next_sequence("candidate", "C1") for _ in range(50)]
        )
        check("50 concurrent allocations are all distinct", len(set(concurrent)) == 50)
        check("concurrent allocations are contiguous", sorted(concurrent) == list(range(1, 51)))

        other = await ids.next_sequence("requisition", "C2", 2026)
        check("a second company starts its own sequence at 1", other == 1)
        year2 = await ids.next_sequence("requisition", "C1", 2027)
        check("a new year starts its own sequence at 1", year2 == 1)

        bid = await ids.next_business_id("requisition", "C1", 2026)
        check("business id renders from the atomic sequence", bid == "HR-REQ-2026-006")
        check("peek does not consume", await ids.peek_sequence("requisition", "C1", 2026) == 6)
        check("peek on a missing counter returns 0",
              await ids.peek_sequence("offer", "C-none", 2026) == 0)

        ok = False
        try:
            await ids.next_sequence("requisition", "", 2026)
        except ValueError:
            ok = True
        check("missing company_id refuses to mint an id", ok)

        # -----------------------------------------------------
        section("Audit trail")
        # -----------------------------------------------------
        import app.services.hrms_audit_service as aud
        aud.get_collection = mongo.get_collection

        await aud.audit(SUPERADMIN, "test action", M.ENTITY_COMPANY, "C1", "detail", "C1")
        check("audit row written", len(audit_coll.docs) == 1)
        row = audit_coll.docs[0]
        check("actor id recorded", row["actor_id"] == "u1")
        check("action recorded", row["action"] == "test action")
        check("company recorded", row["company_id"] == "C1")
        check("timestamp recorded", row.get("created_at") is not None)

        await aud.audit(CLIENT_HR, "inherits company", M.ENTITY_LEAVE, "L1")
        check("company falls back to the actor's own",
              audit_coll.docs[1]["company_id"] == "C1")

        await aud.audit(None, "system action", M.ENTITY_CANDIDATE, "CAN-001")
        check("public/system action allowed with no actor",
              audit_coll.docs[2]["actor_name"] == "system")

        # A failing audit must never propagate into the business write.
        class BrokenCollection(FakeCollection):
            async def insert_one(self, doc):
                raise RuntimeError("disk on fire")

        fake_map[M.COLL_AUDIT_LOG] = BrokenCollection()
        await aud.audit(SUPERADMIN, "boom", M.ENTITY_COMPANY, "C1")
        check("audit failure is swallowed (never blocks the caller)", True)
        fake_map[M.COLL_AUDIT_LOG] = audit_coll

        rows = await aud.read_audit(company_id="C1", limit=10)
        check("audit read returns rows", len(rows) >= 2)
        check("audit read caps limit at 500", len(await aud.read_audit(limit=99999)) <= 500)
    finally:
        mongo.get_collection = original_get_collection

    # ---------------------------------------------------------
    section("Company gate")
    # ---------------------------------------------------------
    from fastapi import HTTPException

    async def fake_enabled(company_id):
        return company_id == "C1"

    original_is_enabled = A.is_hrms_enabled
    A.is_hrms_enabled = fake_enabled
    try:
        await A.ensure_hrms_enabled(CLIENT_HR)
        check("enabled company passes the gate", True)

        raised = False
        try:
            await A.ensure_hrms_enabled(OTHER_CO_HR)
        except HTTPException as e:
            raised = e.status_code == 403 and "not enabled" in e.detail.lower()
        check("disabled company is refused with an actionable 403", raised)

        await A.ensure_hrms_enabled(STAFF_ADMIN)
        check("internal staff always pass the gate", True)

        raised = False
        try:
            await A.ensure_hrms_enabled({"role": "clientuser", "_source_collection": "learners"})
        except HTTPException as e:
            raised = e.status_code == 403
        check("client user with no company is refused", raised)
    finally:
        A.is_hrms_enabled = original_is_enabled

    section("Route registration")
    import main as app_main
    paths = {r.path for r in app_main.app.routes if hasattr(r, "path")}
    check("GET /api/hrms/health registered", "/api/hrms/health" in paths)
    check("GET /api/hrms/audit registered", "/api/hrms/audit" in paths)
    check("PATCH /api/companies/{id}/hrms-access registered",
          "/api/companies/{company_id}/hrms-access" in paths)
    # Regression guard: HRMS must not have disturbed any existing router.
    for p in ("/api/tpms/activities", "/api/tasks", "/api/users/me",
              "/api/companies/{company_id}/tpms-access", "/api/holidays",
              "/api/companies/{company_id}/delegation-access", "/api/auth/token"):
        check(f"pre-existing route intact: {p}", p in paths)

    section("Response-model serialisation (regression guard)")
    from app.models.user import UserResponse
    declared = set(UserResponse.model_fields.keys())
    # Pydantic v2 DROPS undeclared fields on a response_model, so every flag the frontend
    # gates on must be declared or it silently never reaches the client.
    check("hrms_enabled survives /users/me serialisation", "hrms_enabled" in declared)
    check("governance_role survives /users/me serialisation", "governance_role" in declared)
    # Every module flag on this response model, asserted together. Phase 10 found the two
    # HRMS lines had been removed by an unrelated edit, which silently locked every client
    # user out of the module -- exactly the failure this guard exists to catch. Listing the
    # other modules' flags too means the next such edit fails here rather than in the field.
    for flag in ("orm_enabled", "tpms_enabled", "delegation_enabled", "hrms_enabled",
                 # Client Hiring's own flag. `hrms_enabled` requires `is_internal`, so a
                 # client company's user is told about their track through this one alone;
                 # dropping it makes Client Hiring invisible to the people it is for, which
                 # is how it shipped once already.
                 "client_hiring_enabled"):
        check(f"module flag `{flag}` is declared on UserResponse", flag in declared)
    check("tpms_enabled still declared", "tpms_enabled" in declared)
    check("orm_enabled still declared", "orm_enabled" in declared)

    # ---------------------------------------------------------
    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
