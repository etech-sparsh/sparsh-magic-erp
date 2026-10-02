"""Delete-cycle validator — what it removes, and what it must refuse to remove.

Deleting a cycle is the one Leadership action that leaves nothing behind to inspect, so
its two refusals matter more than the delete itself:

  • any submitted feedback — responses carry no giver identity, so a deleted response
    cannot be traced back and asked for again;
  • a published cycle — its leaders and their managers were emailed that a score was
    ready, and an RRO conversation may already reference it.

Runs against an in-memory fake Mongo. No real database, no email.

Usage (from backend/):
    python scripts/validate_leadership_cycle_delete.py
"""
import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_spec = importlib.util.spec_from_file_location(
    "anon", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "validate_leadership_anonymity.py"))
_anon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_anon)
Harness = _anon.Harness

from app.services import leadership_service as svc
from app.models import leadership as M

P, F = [], []


def ok(label, cond, detail=""):
    (P if cond else F).append(label)
    print(("  [PASS] " if cond else "  [FAIL] ") + label + (("  -> " + str(detail)) if detail else ""))


CID, CYC = "c1", "2027-C1"


def mount(status=M.CYCLE_DRAFT, subjects=0, responses=0, scores=0, other_cycle=True):
    """A company holding one cycle under test, plus an untouched neighbour."""
    rows = {
        M.COLL_LS_CYCLES: [{"company_id": CID, "cycle": CYC, "status": status,
                            "degree": M.DEGREE_360, "min_responses": 3}],
        M.COLL_LS_SUBJECTS: [{"company_id": CID, "cycle": CYC, "subject_id": "s%d" % i,
                              "level": "L6"} for i in range(subjects)],
        M.COLL_LS_ASSIGNMENTS: [{"company_id": CID, "cycle": CYC, "subject_id": "s0",
                                 "giver_id": "g%d" % i} for i in range(subjects * 2)],
        M.COLL_LS_RESPONSES: [{"company_id": CID, "cycle": CYC, "subject_id": "s0",
                               "relation": "peer"} for _ in range(responses)],
        M.COLL_LS_SCORES: [{"company_id": CID, "cycle": CYC, "subject_id": "s%d" % i}
                           for i in range(scores)],
        M.COLL_LS_DISCUSSIONS: [], M.COLL_LS_BRIEFINGS: [],
    }
    if other_cycle:
        rows[M.COLL_LS_CYCLES].append({"company_id": CID, "cycle": "2026-C6",
                                       "status": M.CYCLE_PUBLISHED})
        rows[M.COLL_LS_SUBJECTS].append({"company_id": CID, "cycle": "2026-C6",
                                         "subject_id": "keep-me", "level": "L5"})
        rows[M.COLL_LS_RESPONSES].append({"company_id": CID, "cycle": "2026-C6",
                                          "subject_id": "keep-me", "relation": "peer"})
    h = Harness(**rows)
    svc.get_collection = h.collection
    return h


async def main():
    print("1. THE ORDINARY CASE — a cycle opened by mistake")
    h = mount(subjects=2)
    res = await svc.delete_cycle(CID, CYC)
    ok("the cycle is gone", res["deleted"] is True and res["removed"]["cycle"] == 1)
    ok("its enrolled leaders go with it", res["removed"]["subjects"] == 2, res["removed"])
    ok("its panel links go with it", res["removed"]["links"] == 4)
    ok("the result names the cycle for the message", bool(res["label"]), res["label"])
    left = [c["cycle"] for c in h.collection(M.COLL_LS_CYCLES).docs]
    ok("a DIFFERENT cycle is untouched", left == ["2026-C6"], left)
    kept = [s["subject_id"] for s in h.collection(M.COLL_LS_SUBJECTS).docs]
    ok("and so are its subjects", kept == ["keep-me"], kept)

    print("\n2. REFUSED — feedback has been submitted")
    mount(subjects=1, responses=1)
    try:
        await svc.delete_cycle(CID, CYC)
        ok("a cycle holding feedback cannot be deleted", False, "it deleted")
    except ValueError as e:
        ok("a cycle holding feedback cannot be deleted", "cannot be collected again" in str(e),
           str(e)[:74])
    h2 = mount(subjects=1, responses=3)
    try:
        await svc.delete_cycle(CID, CYC)
        ok("the refusal says how many responses", False)
    except ValueError as e:
        ok("the refusal says how many responses", "3 submitted responses" in str(e), str(e)[:52])
    ok("nothing was removed on a refusal",
       len(h2.collection(M.COLL_LS_SUBJECTS).docs) == 2
       and len(h2.collection(M.COLL_LS_RESPONSES).docs) == 4,
       "subjects and responses both intact")

    print("\n3. REFUSED — the cycle was published")
    h3 = mount(status=M.CYCLE_PUBLISHED, subjects=1)
    try:
        await svc.delete_cycle(CID, CYC)
        ok("a published cycle cannot be deleted", False, "it deleted")
    except ValueError as e:
        ok("a published cycle cannot be deleted", "has been published" in str(e), str(e)[:66])
    ok("and it is still there", len(h3.collection(M.COLL_LS_CYCLES).docs) == 2)

    print("\n4. THE STATES IN BETWEEN ARE DELETABLE WHILE EMPTY")
    for status in (M.CYCLE_DRAFT, M.CYCLE_OPEN, M.CYCLE_CLOSED, M.CYCLE_COMPUTED):
        mount(status=status, subjects=1, scores=1)
        res = await svc.delete_cycle(CID, CYC)
        ok("a %s cycle with no feedback can be deleted" % status,
           res["removed"]["cycle"] == 1 and res["removed"]["scores"] == 1,
           "frozen score rows cleared too")

    print("\n5. A CYCLE THAT DOES NOT EXIST")
    mount()
    try:
        await svc.delete_cycle(CID, "1999-C1")
        ok("an unknown cycle is refused, not silently ignored", False)
    except ValueError as e:
        ok("an unknown cycle is refused, not silently ignored",
           "does not exist" in str(e), str(e))

    print("\n" + "=" * 68)
    print("%d passed, %d failed%s" % (len(P), len(F), ("  <-- " + "; ".join(F)) if F else ""))
    print("=" * 68)
    return 1 if F else 0


sys.exit(asyncio.run(main()))
