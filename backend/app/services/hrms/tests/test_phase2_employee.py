"""Phase 2 verification harness -- HRMS employee master, departments, designations.

Covers: the capability matrix, validation (salary, dates, identity documents, referential
integrity), employee composition + salary redaction, manager row scoping, master
name normalisation and delete-protection, and the index registry.

House convention (app/assistant/tests/*): self-contained, no pytest, no new dependencies,
fake collections instead of a live database, non-zero exit on failure, ASCII output only.

Run:  python -m app.services.hrms.tests.test_phase2_employee   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    """Assert a call raises HTTPException with the given status (and message fragment)."""
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


# -------------------------------------------------------------
# Fakes
# -------------------------------------------------------------
class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_k):
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, n=None):
        return self._docs[:n] if n else self._docs


def _dotted_get(doc, key, default=None):
    """Read `a.b.c` out of a nested document, the way Mongo resolves a dotted field path.

    Added in Phase 11-R: the candidate's `client_share` sub-document is queried and grouped
    on `client_share.status`. A fake that only did `doc.get("client_share.status")` would
    return None for every real document and let a broken aggregation pass its tests.
    """
    if "." not in key:
        return doc.get(key, default)
    cursor = doc
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _dotted_set(doc, key, value):
    """Write `a.b.c` into a nested document, creating intermediate dicts as Mongo does."""
    if "." not in key:
        doc[key] = value
        return
    parts = key.split(".")
    cursor = doc
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _dotted_has(doc, key):
    """Whether a dotted path is PRESENT (as distinct from present-and-null)."""
    if "." not in key:
        return key in doc
    cursor = doc
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    return True


def _matches(doc, query):
    """Support the operator subset the service actually uses."""
    for key, cond in query.items():
        if key == "$and":
            if not all(_matches(doc, c) for c in cond):
                return False
            continue
        if key == "$or":
            if not any(_matches(doc, c) for c in cond):
                return False
            continue
        val = _dotted_get(doc, key)
        if isinstance(cond, dict):
            # $exists compares against key PRESENCE, not value -- an onboarding-created
            # employee profile omits `user_id` entirely rather than storing null, and the
            # two must not be conflated (a null value is still indexed in Mongo).
            if "$exists" in cond and _dotted_has(doc, key) != bool(cond["$exists"]):
                return False
            # Mongo matches a query against an ARRAY field element-wise: {"tags": "x"}
            # means "the array contains x", and $in means "shares any element". Without
            # this the fake silently answers "no match" for every array-membership query
            # -- which is how a client-scope resolver reading `member_user_ids` can look
            # broken when it is correct, or look correct when it is broken.
            if "$ne" in cond:
                if isinstance(val, list):
                    if cond["$ne"] in val:
                        return False
                elif val == cond["$ne"]:
                    return False
            if "$in" in cond:
                if isinstance(val, list):
                    if not set(map(str, val)) & set(map(str, cond["$in"])):
                        return False
                elif val not in cond["$in"]:
                    return False
            if "$nin" in cond and val in cond["$nin"]:
                return False
            # Range operators, for the Phase 10 date windows.
            for op, ok in (("$gte", lambda a, b: a >= b), ("$lte", lambda a, b: a <= b),
                           ("$gt", lambda a, b: a > b), ("$lt", lambda a, b: a < b)):
                if op in cond:
                    if val is None:
                        return False
                    try:
                        if not ok(val, cond[op]):
                            return False
                    except TypeError:      # comparing a str date to a datetime, say
                        return False
            if "$regex" in cond:
                import re
                flags = re.I if "i" in cond.get("$options", "") else 0
                if not re.search(cond["$regex"], str(val or ""), flags):
                    return False
        elif isinstance(val, list):
            # Mongo matches {field: <literal>} against an ARRAY field two ways: the array
            # CONTAINS the literal, or the array EQUALS it outright. The equality arm was
            # added for the INT-9 compare-and-swap on the scorecard's approvals list -- a
            # fake with only the contains arm made every equality-CAS on a list field
            # match nothing, which reads as a phantom write conflict.
            if val != cond and cond not in val:
                return False
        elif val != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def insert_one(self, doc):
        from bson import ObjectId
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def insert_many(self, docs):
        from bson import ObjectId
        ids = []
        for doc in docs:
            doc.setdefault("_id", ObjectId())
            self.docs.append(doc)
            ids.append(doc["_id"])
        return type("R", (), {"inserted_ids": ids})()

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if _matches(d, query):
                return d
        return None

    def find(self, query=None, projection=None):
        return FakeCursor([d for d in self.docs if _matches(d, query or {})])

    def aggregate(self, pipeline):
        """The $match/$group/$sort/$limit subset the services actually use.

        Phase 10's breakdowns are real aggregations, so a stub returning [] would let a
        broken pipeline pass its tests. Only the operators in use are supported -- anything
        else raises rather than silently returning nothing.
        """
        docs = list(self.docs)
        for stage in pipeline:
            (op, spec), = stage.items()
            if op == "$match":
                docs = [d for d in docs if _matches(d, spec)]
            elif op == "$group":
                key = spec["_id"]
                if not (isinstance(key, str) and key.startswith("$")):
                    raise NotImplementedError(f"FakeCollection $group by {key!r}")
                field = key[1:]
                buckets = {}
                for d in docs:
                    value = _dotted_get(d, field)
                    bucket = buckets.setdefault(value, {"_id": value})
                    for out, acc in spec.items():
                        if out == "_id":
                            continue
                        if "$sum" not in acc:
                            raise NotImplementedError(f"FakeCollection accumulator {acc!r}")
                        amount = acc["$sum"]
                        amount = (_dotted_get(d, amount[1:]) or 0)                             if isinstance(amount, str) else amount
                        bucket[out] = bucket.get(out, 0) + amount
                docs = list(buckets.values())
            elif op == "$sort":
                for field, direction in reversed(list(spec.items())):
                    docs.sort(key=lambda d, f=field: (d.get(f) is None, d.get(f)),
                              reverse=direction < 0)
            elif op == "$limit":
                docs = docs[:spec]
            else:
                raise NotImplementedError(f"FakeCollection aggregate stage {op}")
        return FakeCursor(docs)

    async def count_documents(self, query=None):
        return len([d for d in self.docs if _matches(d, query or {})])

    async def distinct(self, key, query=None):
        """Distinct values of one field. Mongo skips documents where the key is absent and
        flattens array values; both matter, so neither is faked away."""
        seen = []
        for d in self.docs:
            if not _matches(d, query or {}):
                continue
            if not _dotted_has(d, key):
                continue
            value = _dotted_get(d, key)
            for item in (value if isinstance(value, list) else [value]):
                if item not in seen:
                    seen.append(item)
        return seen

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if doc is None:
            if not upsert:
                return type("R", (), {"matched_count": 0, "modified_count": 0})()
            doc = {}
            doc.update(update.get("$setOnInsert", {}))
            self.docs.append(doc)
        for field, value in (update.get("$set") or {}).items():
            _dotted_set(doc, field, value)
        for field, value in (update.get("$push") or {}).items():
            target = doc.setdefault(field, [])
            if isinstance(value, dict) and "$each" in value:
                target.extend(value["$each"])
            else:
                target.append(value)
        # Added for the SLA escalation guard: "notify once per breach" is expressed as an
        # $addToSet, and a fake that silently ignored it would let a test pass while the
        # guard did nothing -- which is exactly the bug it exists to prevent.
        for field, value in (update.get("$addToSet") or {}).items():
            target = doc.setdefault(field, [])
            values = value["$each"] if isinstance(value, dict) and "$each" in value \
                else [value]
            for item in values:
                if item not in target:
                    target.append(item)
        # Revoking a client-engagement membership is a $pull. A fake that ignored it would
        # let a "member removed" test pass while the member kept their access -- the same
        # silent-no-op trap $addToSet had.
        for field, value in (update.get("$pull") or {}).items():
            target = doc.get(field)
            if isinstance(target, list):
                doc[field] = [item for item in target if item != value]
        for field in (update.get("$unset") or {}):
            doc.pop(field, None)
        return type("R", (), {"matched_count": 1, "modified_count": 1})()

    async def update_many(self, query, update):
        """Added in Phase 11-R: a rename on a master must follow through to every row that
        denormalised it (document types, clients). Without this the fake would silently do
        nothing and the propagation would look correct in tests but not in production."""
        matched = [d for d in self.docs if _matches(d, query)]
        for doc in matched:
            for field, value in (update.get("$set") or {}).items():
                _dotted_set(doc, field, value)
            for field in (update.get("$unset") or {}):
                doc.pop(field, None)
        return type("R", (), {"matched_count": len(matched),
                              "modified_count": len(matched)})()

    async def delete_one(self, query):
        doc = await self.find_one(query)
        if doc:
            self.docs.remove(doc)
        return type("R", (), {"deleted_count": 1 if doc else 0})()

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
        # Real Mongo applies $set in the same atomic operation as $inc; a fake that
        # silently dropped it would let a service that combines the two pass here and fail
        # in production. Added in Phase 11-R, when hrms_link_service.record_open became the
        # first caller to use both together.
        for field, value in (update.get("$set") or {}).items():
            _dotted_set(doc, field, value)
        return doc


COMPANY = "C1"
OTHER_COMPANY = "C2"


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    from app.utils import hrms_access as A
    import app.db.mongodb as mongo

    # ---- Wire fakes -------------------------------------------------------
    U_HR, U_HOD, U_EMP, U_PEER, U_OTHER, U_STAFF = (str(ObjectId()) for _ in range(6))
    DEPT_A, DEPT_B = str(ObjectId()), str(ObjectId())
    DESIG_A = str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR", "is_active": True},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HOD", "is_active": True},
        {"_id": ObjectId(U_EMP), "full_name": "Eve Emp", "email": "emp@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "IMPLEMENTOR",
         "is_active": True, "reporting_manager": U_HOD, "department": "Accounts",
         "designation": "Analyst"},
        {"_id": ObjectId(U_PEER), "full_name": "Peer Person", "email": "peer@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "IMPLEMENTOR",
         "is_active": True},
        {"_id": ObjectId(U_OTHER), "full_name": "Otto Other", "email": "o@c2.com",
         "company_id": OTHER_COMPANY, "role": "clientuser", "is_active": True},
    ])
    staff = FakeCollection([
        {"_id": ObjectId(U_STAFF), "full_name": "Sam Staff", "email": "s@sparsh.com",
         "role": "admin", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT_A), "company_id": COMPANY, "name": "Accounts", "active": True},
        {"_id": ObjectId(DEPT_B), "company_id": OTHER_COMPANY, "name": "Ops", "active": True},
    ])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG_A), "company_id": COMPANY, "name": "Analyst", "active": True},
    ])
    profiles = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {
        "learners": learners, "staff": staff,
        M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
        M.COLL_EMPLOYEE_PROFILES: profiles, M.COLL_COUNTERS: counters,
        M.COLL_AUDIT_LOG: audit_log,
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_employee_service as ES
    import app.services.hrms_masters_service as MS
    import app.services.hrms_audit_service as AS
    import app.services.hrms_id_service as IS
    for mod in (ES, MS, AS, IS):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": U_EMP, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}
    INTERNAL = {"_id": U_STAFF, "role": "admin", "_source_collection": "staff"}
    SUPER = {"_id": "sa", "role": "superadmin", "_source_collection": "staff"}

    try:
        # =================================================================
        section("Capability matrix (Phase 2)")
        # =================================================================
        check("HR can read employees", A.can(HR, M.Cap.EMPLOYEE_READ))
        check("HR can write employees", A.can(HR, M.Cap.EMPLOYEE_WRITE))
        check("HR can read salary", A.can(HR, M.Cap.EMPLOYEE_SALARY_READ))
        check("HR can write salary", A.can(HR, M.Cap.EMPLOYEE_SALARY_WRITE))
        check("HOD can read employees", A.can(HOD, M.Cap.EMPLOYEE_READ))
        check("HOD CANNOT write employees", not A.can(HOD, M.Cap.EMPLOYEE_WRITE))
        check("HOD CANNOT read salary", not A.can(HOD, M.Cap.EMPLOYEE_SALARY_READ))
        check("HOD can read departments", A.can(HOD, M.Cap.DEPARTMENT_READ))
        check("HOD CANNOT write departments", not A.can(HOD, M.Cap.DEPARTMENT_WRITE))
        check("Employee CANNOT read directory", not A.can(EMP, M.Cap.EMPLOYEE_READ))
        check("Employee CANNOT read salary", not A.can(EMP, M.Cap.EMPLOYEE_SALARY_READ))
        # Sparsh support staff administer HRMS but have no business seeing client pay.
        check("INTERNAL can read employees", A.can(INTERNAL, M.Cap.EMPLOYEE_READ))
        check("INTERNAL CANNOT read client salary", not A.can(INTERNAL, M.Cap.EMPLOYEE_SALARY_READ))
        check("INTERNAL CANNOT write client salary", not A.can(INTERNAL, M.Cap.EMPLOYEE_SALARY_WRITE))
        check("superadmin sees everything (implicit ADMIN)", A.can(SUPER, M.Cap.EMPLOYEE_SALARY_WRITE))

        # =================================================================
        section("Masters -- create, normalise, duplicate")
        # =================================================================
        d = await MS.create_master("department", COMPANY, {"name": "Sales"}, HR)
        check("department created", d["name"] == "Sales")
        check("scoped to the company", d["company_id"] == COMPANY)
        check("create is audited", any(r["action"] == M.AUDIT_DEPARTMENT_CREATED
                                       for r in audit_log.docs))

        d2 = await MS.create_master("department", COMPANY, {"name": "  Field   Ops  "}, HR)
        check("whitespace trimmed and collapsed", d2["name"] == "Field Ops")

        await expect_http("duplicate name", MS.create_master(
            "department", COMPANY, {"name": "Sales"}, HR), 409, "already exists")
        await expect_http("duplicate differing only in case", MS.create_master(
            "department", COMPANY, {"name": "sales"}, HR), 409, "already exists")
        await expect_http("duplicate differing only in spacing", MS.create_master(
            "department", COMPANY, {"name": " Sales "}, HR), 409, "already exists")
        await expect_http("empty name", MS.create_master(
            "department", COMPANY, {"name": "   "}, HR), 422, "required")
        await expect_http("over-long name", MS.create_master(
            "department", COMPANY, {"name": "x" * 121}, HR), 422, "120")

        # Same name in a DIFFERENT company must be allowed - masters are per-tenant.
        other = await MS.create_master("department", OTHER_COMPANY, {"name": "Sales"}, HR)
        check("same name allowed in another company", other["name"] == "Sales")

        section("Masters -- read scoping")
        rows = await MS.list_masters("department", COMPANY)
        names = {r["name"] for r in rows}
        check("company sees its own masters", {"Sales", "Field Ops", "Accounts"} <= names)
        check("company does NOT see another tenant's master",
              all(r["company_id"] == COMPANY for r in rows))
        check("get_master is tenant-scoped",
              await MS.get_master("department", COMPANY, other["id"]) is None)

        section("Masters -- update and delete protection")
        renamed = await MS.update_master("department", COMPANY, d["id"], {"name": "Sales & BD"}, HR)
        check("rename applied", renamed["name"] == "Sales & BD")
        await expect_http("rename onto an existing name", MS.update_master(
            "department", COMPANY, d["id"], {"name": "Field Ops"}, HR), 409)
        await expect_http("update with no fields", MS.update_master(
            "department", COMPANY, d["id"], {}, HR), 400)
        await expect_http("update a missing master", MS.update_master(
            "department", COMPANY, str(ObjectId()), {"name": "X"}, HR), 404)
        await expect_http("malformed master id", MS.update_master(
            "department", COMPANY, "not-an-oid", {"name": "X"}, HR), 400)

        deactivated = await MS.update_master("department", COMPANY, d["id"], {"active": False}, HR)
        check("deactivate works", deactivated["active"] is False)
        check("inactive hidden by default",
              d["id"] not in {r["id"] for r in await MS.list_masters("department", COMPANY)})
        check("inactive shown when asked",
              d["id"] in {r["id"] for r in await MS.list_masters("department", COMPANY, True)})

        # =================================================================
        section("Employee -- create")
        # =================================================================
        emp = await ES.create_profile(HR, COMPANY, {
            "user_id": U_EMP, "department_id": DEPT_A, "designation_id": DESIG_A,
            "joined_on": "2024-04-01", "base_salary": 50000,
        })
        check("profile created", emp["user_id"] == U_EMP)
        check("employee code auto-minted", emp["employee_code"].startswith("EMP-"))
        check("identity composed from the user record", emp["name"] == "Eve Emp")
        check("department name resolved", emp["department"] == "Accounts")
        check("designation name resolved", emp["designation"] == "Analyst")
        check("has_profile true", emp["has_profile"] is True)
        check("salary visible to HR", emp.get("base_salary") == 50000)
        check("create is audited", any(r["action"] == M.AUDIT_EMPLOYEE_CREATED
                                       for r in audit_log.docs))
        check("identity NOT duplicated into the profile",
              "name" not in profiles.docs[0] and "email" not in profiles.docs[0])

        await expect_http("duplicate profile", ES.create_profile(
            HR, COMPANY, {"user_id": U_EMP}), 409, "already has")
        await expect_http("unknown user", ES.create_profile(
            HR, COMPANY, {"user_id": str(ObjectId())}), 404)
        await expect_http("user from another company", ES.create_profile(
            HR, COMPANY, {"user_id": U_OTHER}), 403, "another company")
        await expect_http("Sparsh staff cannot be a client employee", ES.create_profile(
            HR, COMPANY, {"user_id": U_STAFF}), 422, "company users")
        await expect_http("missing user_id", ES.create_profile(HR, COMPANY, {}), 422)

        section("Employee -- validation")
        await expect_http("negative salary", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "base_salary": -1}), 422, "negative")
        await expect_http("non-numeric salary", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "base_salary": "lots"}), 422, "number")
        await expect_http("absurd salary", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "base_salary": 10 ** 12}), 422, "implausibly")
        await expect_http("malformed date", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "joined_on": "01-04-2024"}), 422, "YYYY-MM-DD")
        await expect_http("impossible date (Feb 30)", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "joined_on": "2024-02-30"}), 422)
        await expect_http("joined after resigned", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "joined_on": "2025-01-01",
                          "resigned_on": "2024-01-01"}), 422, "after")
        await expect_http("bad PAN", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "pan": "ABC123"}), 422, "PAN")
        await expect_http("bad Aadhaar", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "aadhaar": "1234"}), 422, "Aadhaar")
        await expect_http("bad IFSC", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "bank_ifsc": "HDFC123"}), 422, "IFSC")
        await expect_http("non-numeric bank account", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "bank_account": "12AB34"}), 422, "digits")
        await expect_http("department from another company", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "department_id": DEPT_B}), 422, "does not exist")
        await expect_http("non-existent designation", ES.create_profile(
            HR, COMPANY, {"user_id": U_PEER, "designation_id": str(ObjectId())}), 422)

        ok = await ES.create_profile(HR, COMPANY, {
            "user_id": U_PEER, "pan": "abcde1234f", "aadhaar": "123456789012",
            "bank_ifsc": "hdfc0001234", "department_id": DEPT_A,
        })
        check("lowercase PAN accepted and uppercased", ok["pan"] == "ABCDE1234F")
        check("lowercase IFSC uppercased", ok["bank_ifsc"] == "HDFC0001234")
        check("valid Aadhaar stored", ok["aadhaar"] == "123456789012")
        check("leap day is a valid date", M.is_iso_date("2024-02-29"))
        check("Feb 29 in a non-leap year is rejected", not M.is_iso_date("2023-02-29"))

        section("Employee -- salary permissions")
        await expect_http("HOD cannot set salary on create", ES.create_profile(
            HOD, COMPANY, {"user_id": U_HR, "base_salary": 1}), 403, "may not set salary")
        await expect_http("INTERNAL cannot set client salary", ES.create_profile(
            INTERNAL, COMPANY, {"user_id": U_HR, "base_salary": 1}), 403)

        # Regression (found during the Phase 6 audit): the gate must be on INTENT TO WRITE,
        # not on a value delta. With no salary stored, writing 0 compared equal to the
        # `or 0` fallback and skipped the capability check entirely.
        await expect_http("HOD cannot write salary 0 onto an employee with none set",
                          ES.update_profile(HOD, U_HR, {"base_salary": 0}, COMPANY),
                          403, "may not change salary")
        await expect_http("HOD cannot re-write the SAME salary a candidate already has",
                          ES.update_profile(HOD, U_EMP, {"base_salary": 50000}, COMPANY),
                          403, "may not change salary")

        as_hod = await ES.get_employee(HOD, U_EMP, company_id=COMPANY)
        check("salary OMITTED (not nulled) for HOD", "base_salary" not in as_hod)
        as_hr = await ES.get_employee(HR, U_EMP, company_id=COMPANY)
        check("salary present for HR", as_hr.get("base_salary") == 50000)
        as_self = await ES.get_employee(EMP, U_EMP, force_salary=True)
        check("you always see your own salary", as_self.get("base_salary") == 50000)

        section("Employee -- update")
        upd = await ES.update_profile(HR, U_EMP, {"employment_status": "On Notice"}, COMPANY)
        check("status updated", upd["employment_status"] == "On Notice")
        upd = await ES.update_profile(HR, U_EMP, {"base_salary": 60000}, COMPANY)
        check("salary updated", upd["base_salary"] == 60000)
        check("salary change gets its own audit line",
              any(r["action"] == M.AUDIT_SALARY_CHANGED for r in audit_log.docs))
        await expect_http("HOD cannot change salary", ES.update_profile(
            HOD, U_EMP, {"base_salary": 1}, COMPANY), 403, "may not change salary")
        await expect_http("update with no fields", ES.update_profile(
            HR, U_EMP, {}, COMPANY), 400)
        await expect_http("update across tenants", ES.update_profile(
            HR, U_OTHER, {"employment_status": "Active"}, COMPANY), 404)
        # Existing joined_on must be considered, not just the incoming field.
        await expect_http("resigned before existing joined_on", ES.update_profile(
            HR, U_EMP, {"resigned_on": "2020-01-01"}, COMPANY), 422, "after")

        # Upsert: a user with no profile row is created on first write.
        created = await ES.update_profile(HR, U_HOD, {"employment_type": "Contract"}, COMPANY)
        check("update upserts a missing profile", created["employment_type"] == "Contract")

        section("Employee -- duplicate employee_code")
        await expect_http("employee code collision", ES.update_profile(
            HR, U_PEER, {"employee_code": emp["employee_code"]}, COMPANY), 409, "already in use")

        # =================================================================
        section("Row scoping -- manager sees only their corner")
        # =================================================================
        await ES.update_profile(HR, U_HOD, {"department_id": DEPT_A}, COMPANY)
        listing = await ES.list_employees(HOD, COMPANY)
        visible = {e["user_id"] for e in listing["employees"]}
        check("HOD sees their direct report", U_EMP in visible)
        check("HOD sees themselves", U_HOD in visible)
        check("HOD sees a department peer", U_PEER in visible)
        check("HOD does NOT see an unrelated colleague", U_HR not in visible)
        check("salary_visible false for HOD", listing["salary_visible"] is False)
        check("no salary key on any listed row",
              all("base_salary" not in e for e in listing["employees"]))

        hr_listing = await ES.list_employees(HR, COMPANY)
        check("HR sees the whole company", len(hr_listing["employees"]) >= 4)
        check("salary_visible true for HR", hr_listing["salary_visible"] is True)

        check("listing never leaks another tenant",
              all(e["company_id"] == COMPANY for e in hr_listing["employees"]))

        section("Row scoping -- get_employee")
        await expect_http("HOD cannot open an out-of-scope employee (404, not 403)",
                          ES.get_employee(HOD, U_HR, company_id=COMPANY), 404)
        await expect_http("cross-tenant read is 404, not 403",
                          ES.get_employee(HR, U_OTHER, company_id=COMPANY), 404)
        await expect_http("plain employee cannot read a colleague",
                          ES.get_employee(EMP, U_PEER, company_id=COMPANY), 403, "your own")
        self_view = await ES.get_employee(EMP, U_EMP)
        check("plain employee CAN read themselves", self_view["user_id"] == U_EMP)

        section("Filters and pagination")
        filtered = await ES.list_employees(HR, COMPANY, department_id=DEPT_A)
        check("department filter applied",
              all(e["department_id"] == DEPT_A for e in filtered["employees"]))
        check("department filter is non-empty", len(filtered["employees"]) >= 2)
        none_match = await ES.list_employees(HR, COMPANY, department_id=str(ObjectId()))
        check("unmatched filter returns empty, not everything", none_match["total"] == 0)
        searched = await ES.list_employees(HR, COMPANY, search="Eve")
        check("search matches by name", any(e["name"] == "Eve Emp" for e in searched["employees"]))
        # A regex metacharacter in the search box must not blow up or match everything.
        safe = await ES.list_employees(HR, COMPANY, search="Eve(")
        check("regex metacharacters in search are escaped", safe["total"] == 0)
        paged = await ES.list_employees(HR, COMPANY, limit=1)
        check("limit honoured", len(paged["employees"]) == 1)
        check("total reflects the full set, not the page", paged["total"] >= 4)
        await expect_http("company is required", ES.list_employees(HR, ""), 400)

        # =================================================================
        section("Hierarchy")
        # =================================================================
        h = await ES.get_hierarchy(HR, U_EMP, COMPANY)
        check("manager chain resolved", h["manager_chain"][0]["name"] == "Hari HOD")
        check("direct reports counted", h["report_count"] == 0)
        h2 = await ES.get_hierarchy(HR, U_HOD, COMPANY)
        check("HOD has a direct report", h2["report_count"] == 1)
        check("report is the right person", h2["direct_reports"][0]["name"] == "Eve Emp")

        # Cycle guard: reporting_manager has no DB constraint against A -> B -> A.
        for doc in learners.docs:
            if str(doc["_id"]) == U_HOD:
                doc["reporting_manager"] = U_EMP
        h3 = await ES.get_hierarchy(HR, U_EMP, COMPANY)
        check("circular reporting chain terminates",
              any(m.get("circular") for m in h3["manager_chain"]))
        check("cycle does not hang or overflow", len(h3["manager_chain"]) < 12)

        section("Linkable users")
        linkable = await ES.list_linkable_users(HR, COMPANY)
        ids = {u["user_id"] for u in linkable}
        check("users WITH a profile are excluded", U_EMP not in ids and U_PEER not in ids)
        check("users WITHOUT a profile are offered", U_HR in ids)
        check("another tenant's users are never offered", U_OTHER not in ids)

        # =================================================================
        section("Delete protection (referential integrity)")
        # =================================================================
        await expect_http("cannot delete a department in use", MS.delete_master(
            "department", COMPANY, DEPT_A, HR), 409, "assigned to")
        free = await MS.create_master("department", COMPANY, {"name": "Temp"}, HR)
        gone = await MS.delete_master("department", COMPANY, free["id"], HR)
        check("unused department deletes", gone["deleted"] is True)
        check("delete is audited", any(r["action"] == M.AUDIT_DEPARTMENT_DELETED
                                       for r in audit_log.docs))
        await expect_http("delete a missing master", MS.delete_master(
            "department", COMPANY, str(ObjectId()), HR), 404)

        # =================================================================
        section("Index registry (Phase 2 additions)")
        # =================================================================
        names = [(c, o.get("name")) for c, _k, o in M.HRMS_INDEXES]
        check("one profile per user is enforced by a unique index",
              any(c == M.COLL_EMPLOYEE_PROFILES and n == "uniq_user" for c, n in names))
        check("employee code unique per company (sparse)",
              any(c == M.COLL_EMPLOYEE_PROFILES and n == "uniq_company_code" for c, n in names))
        check("department name unique per company",
              any(c == M.COLL_DEPARTMENTS and n == "uniq_company_name" for c, n in names))
        check("designation name unique per company",
              any(c == M.COLL_DESIGNATIONS and n == "uniq_company_name" for c, n in names))
        check("index names still unique per collection", len(names) == len(set(names)))
        check("all indexed collections are hrms_-prefixed",
              all(c.startswith("hrms_") for c, _k, _o in M.HRMS_INDEXES))

        section("Identity collections are never written")
        check("learners untouched (no HR fields injected)",
              all("base_salary" not in d and "employee_code" not in d for d in learners.docs))
        check("staff untouched",
              all("base_salary" not in d and "employee_code" not in d for d in staff.docs))
    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
