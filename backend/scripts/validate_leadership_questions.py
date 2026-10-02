"""Leadership question validator - the seed is used exactly as the document prints it.

Runs entirely against an IN-MEMORY fake Mongo. No real database is opened, no existing
TPMS document is read or written, and no email is sent. Safe to run at any time.

The instruction this enforces: "Key insights of Leadership Score" is the single source of
truth for the questions and their options. Whatever the document prints is what leaders
are scored on - unusual, duplicated or inverted items included. Nothing is corrected,
nothing is flagged, and nobody - HR, MD or anyone else - is asked to confirm any of it.

What it proves:

  verbatim       Every question, option, letter and SCORE matches the printed document
                 exactly - including its typos, its duplicated option sets and L7 Q6's
                 inverted scoring. Nothing is corrected in code.
  fingerprint    Each subject is stamped with a digest of the exact rubric that scored
                 them, so a published number stays traceable after a later edit.
                 Retitling, reweighting or restating changes it; reordering does not.
  no review      No register, no severity, no flags on any row served to the screen, and
                 no sign-off call anywhere in the model or the service.
  no gate        A score freezes with nothing approved by anyone. Setting up, opening,
                 collecting and closing are all unchanged.

Usage (PowerShell, from backend/):
    python scripts/validate_leadership_questions.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD = "[PASS]", "[FAIL]"
_results: list = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    _results.append(bool(condition))
    print(f"{OK if condition else BAD} {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} " + "-" * max(0, 62 - len(title)))


# ─────────────────────────────────────────────────────────────
# In-memory Mongo stand-in
# ─────────────────────────────────────────────────────────────
class FakeCollection:
    def __init__(self, docs=None):
        # Mongo stamps `_id` on insert and the service relies on it; seed the same way so
        # a missing id cannot fail a check for a reason unrelated to sign-off.
        self.docs = []
        for d in (docs or []):
            self.docs.append({"_id": ObjectId(), **dict(d)})

    @staticmethod
    def _match(doc, query):
        for k, cond in (query or {}).items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if "$ne" in cond and v == cond["$ne"]:
                    return False
                if "$in" in cond and v not in cond["$in"]:
                    return False
            elif v != cond:
                return False
        return True

    def find(self, query=None, *a, **k):
        rows = [d for d in self.docs if self._match(d, query or {})]

        class _C:
            def sort(self, *a, **k):
                return self

            async def to_list(self, n=None):
                return rows
        return _C()

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def count_documents(self, query):
        return len([d for d in self.docs if self._match(d, query)])

    async def update_one(self, query, update, upsert=False):
        # Mirrors pymongo's return shape - update_cycle branches on `matched_count`, so a
        # bare None here would fail a check for a harness reason, not a code one.
        class _R:
            def __init__(self, matched):
                self.matched_count = matched
                self.modified_count = matched

        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return _R(1)
        if upsert:
            self.docs.append({"_id": ObjectId(), **query, **update.get("$set", {}),
                              **update.get("$setOnInsert", {})})
            return _R(0)
        return _R(0)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def insert_many(self, docs, ordered=True):
        self.docs.extend(dict(d) for d in docs)

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs.pop(i)

                class _R:
                    deleted_count = 1
                return _R()

        class _R0:
            deleted_count = 0
        return _R0()


class Harness:
    """Fake collections wired under leadership_service."""

    def __init__(self, *, questions=None, subjects=None, cycles=None):
        self.questions = FakeCollection(questions or [])
        self.subjects = FakeCollection(subjects or [])
        self.cycles = FakeCollection(cycles or [])
        self.signoff = FakeCollection()
        self.empty = FakeCollection()

    def collection(self, name):
        return {
            "tpms_leadership_questions": self.questions,
            "tpms_leadership_subjects": self.subjects,
            "tpms_leadership_cycles": self.cycles,
            "tpms_leadership_level_signoff": self.signoff,
        }.get(name, self.empty)


HR = {"_id": "u-hr", "full_name": "Priya (HR)"}


async def main() -> int:
    from app.models import leadership as M
    from app.services import leadership_service as svc

    # ── verbatim fidelity ─────────────────────────────────────
    section("Verbatim fidelity to the HR document")

    def opts(level, item_id):
        q = next(q for q in M.LEADERSHIP_QUESTION_SEED[level] if q["item_id"] == item_id)
        return [(o["option_id"], o["label"], o["score"]) for o in q["options"]]

    # L7 Q6 as PRINTED: a=1 (best answer, lowest score) ... d=5. Reproduced, not repaired.
    check("L7 Q6 keeps the document's inverted scoring",
          opts("L7", "L7Q6") == [
              ("a", "Goals are aligned and largely executed", 1),
              ("b", "Goals are embedded and strategy drives action", 2),
              ("c", "Goals are unclear and execution is inconsistent", 4),
              ("d", "Goals are communicated, execution is uneven", 5),
          ], "best answer still scores 1, exactly as printed")

    check("the document's typo is preserved",
          any("delf-driven" in o[1] for o in opts("L4", "L4Q1")))
    check("L4 Q5's ungrammatical option is preserved",
          opts("L4", "L4Q5")[3][1] == "Accountable for Teams self-track")
    check("L4 Q5 keeps the option imported from L7",
          opts("L4", "L4Q5")[0][1] == "Loses accountability under scale")
    check("L6 Q6 keeps its lowercase lettering",
          [o[0] for o in opts("L6", "L6Q6")] == ["a", "b", "c", "d"])
    check("L5 Q3 keeps priority options under a communication heading",
          opts("L5", "L5Q3")[0][1] == "Everything feels urgent.")
    check("L7 Q1 keeps team-structure options under a counselling heading",
          opts("L7", "L7Q1")[0][1] == "Team depends heavily on leader")

    every = [(lv, q["item_id"], o["score"])
             for lv, qs in M.LEADERSHIP_QUESTION_SEED.items()
             for q in qs for o in q["options"]]
    check("no option is ever worth 3, on any level",
          all(sc in (1, 2, 4, 5) for _, _, sc in every), f"{len(every)} options checked")
    check("question counts match the document (5/5/6/6)",
          [len(M.LEADERSHIP_QUESTION_SEED[lv]) for lv in M.LEVELS] == [5, 5, 6, 6])

    # ── fingerprint ───────────────────────────────────────────
    section("Rubric fingerprint")

    base = M.seed_rows_for_level("L7")
    fp = M.rubric_fingerprint(base)

    retitled = M.seed_rows_for_level("L7")
    retitled[0]["title"] = "Team structure / building"
    check("retitling a question changes the fingerprint",
          M.rubric_fingerprint(retitled) != fp)

    reweighted = M.seed_rows_for_level("L7")
    reweighted[0]["weightage"] = 30.0
    check("moving a weightage changes it", M.rubric_fingerprint(reweighted) != fp)

    restated = M.seed_rows_for_level("L7")
    restated[0]["options"][0]["label"] = "Reworded"
    check("restating an option changes it", M.rubric_fingerprint(restated) != fp)

    rescored = M.seed_rows_for_level("L7")
    rescored[0]["options"][0]["score"] = 3
    check("rescoring an option changes it", M.rubric_fingerprint(rescored) != fp)

    reordered = list(reversed(M.seed_rows_for_level("L7")))
    check("reordering the form does NOT change it",
          M.rubric_fingerprint(reordered) == fp, "no score depends on order")

    # ── no review machinery anywhere ──────────────────────────
    section("Nothing reviews, flags or approves a question")

    check("the model exposes no review register",
          not any(hasattr(M, n) for n in
                  ("QUESTION_REVIEW", "LEVEL_REVIEW", "GLOBAL_REVIEW",
                   "question_review", "level_review", "source_drift")))
    check("the model exposes no sign-off payload", not hasattr(M, "LevelSignOff"))
    check("the service exposes no sign-off or review call",
          not any(hasattr(svc, n) for n in
                  ("level_signoff", "set_level_signoff", "clear_level_signoff",
                   "review_summary", "unsigned_levels", "describe_unsigned")))

    review_keys = {"needs_review", "review_code", "review_note", "review_severity",
                   "source_drift"}
    check("seeded rows carry no review field",
          not any(review_keys & set(r) for r in M.all_seed_rows()))

    h = Harness(questions=M.all_seed_rows())
    svc.get_collection = h.collection
    served = await svc.get_questions("L5")
    check("rows served to the screen carry no review field",
          not any(review_keys & set(r) for r in served), f"{len(served)} rows checked")
    check("served options keep the printed scores",
          sorted({o["score"] for r in served for o in r["options"]}) == [1, 2, 4, 5])

    # ── nothing is gated ──────────────────────────────────────
    section("No approval gates a cycle")

    cycle = {"company_id": "c1", "cycle": "2026-C1", "status": M.CYCLE_CLOSED,
             "degree": M.DEGREE_360, "min_responses": 3, "quorum": 5}
    subjects = [{"company_id": "c1", "cycle": "2026-C1", "subject_id": "s1", "level": "L5"},
                {"company_id": "c1", "cycle": "2026-C1", "subject_id": "s2", "level": "L6"}]
    h4 = Harness(questions=M.all_seed_rows(), subjects=subjects, cycles=[cycle])
    svc.get_collection = h4.collection

    computed = await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_COMPUTED}, HR)
    check("a score freezes with no approval of any kind",
          computed.get("status") == M.CYCLE_COMPUTED,
          "two levels enrolled, nothing signed off by anyone")

    section("The rest of the flow is unchanged")

    draft = {**cycle, "status": M.CYCLE_DRAFT}
    h5 = Harness(questions=M.all_seed_rows(), cycles=[draft])
    svc.get_collection = h5.collection
    updated = await svc.update_cycle("c1", "2026-C1", {"notes": "still editable"}, HR)
    check("a cycle can still be edited", updated.get("notes") == "still editable")
    check("and it can still be opened",
          (await svc.update_cycle("c1", "2026-C1",
                                  {"status": M.CYCLE_OPEN}, HR)).get("status") == M.CYCLE_OPEN)
    check("and closed",
          (await svc.update_cycle("c1", "2026-C1",
                                  {"status": M.CYCLE_CLOSED}, HR)).get("status") == M.CYCLE_CLOSED)

    # ── summary ───────────────────────────────────────────────
    passed, total = sum(_results), len(_results)
    print(f"\n{'=' * 66}\n{passed}/{total} checks passed"
          f"{'' if passed == total else '  <-- FAILURES ABOVE'}\n{'=' * 66}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
