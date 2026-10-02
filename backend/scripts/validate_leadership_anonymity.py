"""Leadership Score validator - anonymity, scoring and the cycle state machine.

Runs entirely against an IN-MEMORY fake Mongo. No real database is opened, no existing
TPMS document is read or written, and no email is sent. Safe to run at any time.

The promise this module makes to every employee is "ye feedback completely confidential
hoga". A UI-level hide does not keep it: one aggregation, one export, one support query
and the promise is gone. These checks prove the join does not exist to begin with, and
that the arithmetic cannot be used to recover it either.

What it proves:

  no identity    A stored response carries no giver id and no field that can be joined to
                 one.
  digital only   Collection is by emailed link. There is no manual entry path and no way
                 to delete a response by hand, so no feedback can be authored or removed
                 by an administrator.
  single use     Duplicate submission is stopped by an ATOMIC claim on the invitation, so
                 uniqueness never needs a rater id on the answers. Two concurrent submits
                 produce exactly one response.
  token at rest  Only a hash is stored. The credential is unset on submit, so a used link
                 is dead in the database rather than merely refused.
  panel opacity  A panel row hands back no link. HR resends instead, which mints a new one.
  index specs    A unique index over a field the code leaves unset is SPARSE, and an index
                 whose options changed is dropped before being recreated - MongoDB refuses
                 to alter one in place and silently keeps the old options.
  publish gate   A leader sees NOTHING until the cycle is published - not a partial score,
                 not a response count, not a trend. This is what stops them differencing
                 the average after each submission to recover one person's rating. Checked
                 through the ROUTE handlers, because a gate the routes never pass is a
                 gate that does nothing.
  group weighted A group that responds twice as often does not get twice the say. Averaged
                 within a relation first, then across relations.
  frozen history A weightage edited after computing does not move a published score.
  whole forms    A part-filled form is refused rather than counted as a whole response.
  state machine  Only the legal transitions are allowed; published is terminal.
  panel lock     A panel cannot be changed once any feedback has arrived.
  eligibility    A leader cannot be enrolled at a level their user record does not hold.

Usage (PowerShell, from backend/):
    python scripts/validate_leadership_anonymity.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

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


class FakeCollection:
    def __init__(self, docs=None):
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
                if "$nin" in cond and v in cond["$nin"]:
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
        class _R:
            def __init__(self, m):
                self.matched_count = m
                self.modified_count = m

        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                for f in (update.get("$unset") or {}):
                    d.pop(f, None)
                for f, v in (update.get("$addToSet") or {}).items():
                    d.setdefault(f, [])
                    if v not in d[f]:
                        d[f].append(v)
                for f, v in (update.get("$push") or {}).items():
                    d.setdefault(f, []).append(v)
                return _R(1)
        if upsert:
            self.docs.append({"_id": ObjectId(), **query, **update.get("$set", {}),
                              **update.get("$setOnInsert", {})})
        return _R(0)

    async def insert_one(self, doc):
        row = {"_id": ObjectId(), **dict(doc)}
        self.docs.append(row)

        class _R:
            inserted_id = row["_id"]
        return _R()

    async def insert_many(self, docs, ordered=True):
        for d in docs:
            self.docs.append({"_id": ObjectId(), **dict(d)})

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

    async def delete_many(self, query):
        keep = [d for d in self.docs if not self._match(d, query)]
        n = len(self.docs) - len(keep)
        self.docs = keep

        class _R:
            deleted_count = n
        return _R()


class Harness:
    def __init__(self, **named):
        self.cols = {}
        for name, docs in named.items():
            self.cols[name] = FakeCollection(docs)

    def collection(self, name):
        return self.cols.setdefault(name, FakeCollection())


HR = {"_id": "u-hr", "full_name": "Priya (HR)"}


class Ans:
    def __init__(self, qid, oid):
        self.question_id = qid
        self.option_id = oid


def answers_for(questions, score=4):
    """A complete form - every active question answered, as the API now requires.

    Picks by SCORE, not by letter. L6 Q6 and L7 Q6 are lettered a-d in lowercase while
    every other question uses A-D (a defect carried in from the source document), so
    selecting "D" would silently fall through to a different option on those two and make
    a scoring assertion mean something other than it says.
    """
    out = []
    for q in questions:
        opt = next(o for o in q["options"] if float(o["score"]) == float(score))
        out.append(Ans(q["item_id"], opt["option_id"]))
    return out


async def main() -> int:
    from app.models import leadership as M
    from app.services import leadership_service as svc
    from app.services import leadership_link_service as links

    LEVEL = "L6"
    qs = M.seed_rows_for_level(LEVEL)

    def fresh(all_levels=False, **extra):
        cycle = {"company_id": "c1", "cycle": "2026-C1", "status": M.CYCLE_OPEN,
                 "degree": M.DEGREE_360, "min_responses": 3, "quorum": 5, **extra}
        subject = {"company_id": "c1", "cycle": "2026-C1", "subject_id": "s1",
                   "subject_name": "Rahul", "level": LEVEL, "department": "Ops",
                   "reporting_manager": "m1",
                   "rubric": [dict(q) for q in qs]}
        h = Harness(tpms_leadership_questions=(M.all_seed_rows() if all_levels else qs),
                    tpms_leadership_cycles=[cycle],
                    tpms_leadership_subjects=[subject])
        svc.get_collection = h.collection
        links.get_collection = h.collection
        # Route handlers import get_collection locally (inside the function body), so the
        # module itself has to be patched or those imports reach the real database.
        import app.db.mongodb as mongo
        mongo.get_collection = h.collection
        return h

    def assignment(gid, relation="peer"):
        return {"_id": ObjectId(), "company_id": "c1", "cycle": "2026-C1",
                "subject_id": "s1", "giver_id": gid, "relation": relation,
                "subject_level": LEVEL, "subject_name": "Rahul", "period": "2026-02",
                "status": M.LINK_SENT, "giver_email": f"{gid}@x.com"}

    # ── no identity on a response ─────────────────────────────
    section("A response carries no rater identity")

    h = fresh()
    a = assignment("g1")
    h.collection("tpms_leadership_assignments").docs.append(a)
    await svc.record_response(a, answers_for(qs))

    stored = h.collection("tpms_leadership_responses").docs
    check("one response was written", len(stored) == 1)
    row = stored[0]
    check("it has no giver_id", "giver_id" not in row)
    forbidden = {"giver_id", "giver_name", "giver_email", "token", "token_hash", "user_id",
                 "phone", "mobile"}
    check("it has no field naming the giver at all",
          not (forbidden & set(row)), sorted(set(row) & forbidden) or "none present")
    check("it keeps only the relation group", row.get("relation") == "peer")
    # Was: "assignment_ref points at the invitation, not the person". That reference was
    # still a join — assignment_ref -> assignment -> giver_id — so the header's own promise
    # ("no field that can be joined to one") was not actually kept. It is no longer stored.
    check("it carries no reference back to the invitation either",
          "assignment_ref" not in row)

    # Collection is digital only. There must be no way for an administrator to key in or
    # delete a response by hand: a hand-entered form is feedback nobody can trace, and a
    # deletable one lets an admin quietly drop feedback they did not like.
    check("no manual paper-entry path exists",
          not hasattr(svc, "record_paper_response"))
    check("no response can be deleted by hand",
          not hasattr(svc, "withdraw_response"))
    check("responses carry no intake-source field", "source" not in row,
          "one channel, so there is nothing to distinguish")

    # ── single use without a rater id ─────────────────────────
    section("Duplicate submission is stopped on the invitation")

    h3 = fresh()
    a3 = assignment("g1")
    h3.collection("tpms_leadership_assignments").docs.append(a3)
    first = await links.claim_for_submission(a3)
    second = await links.claim_for_submission(a3)
    check("the first claim wins", first is True)
    check("the second claim loses", second is False,
          "so uniqueness never needs a giver id on the answers")

    stored_a = h3.collection("tpms_leadership_assignments").docs[0]
    check("the credential is destroyed on submit",
          "token_hash" not in stored_a and "token" not in stored_a,
          "a used link is dead in the database, not merely refused")

    await links.release_claim(a3)
    check("a failed write releases the claim",
          h3.collection("tpms_leadership_assignments").docs[0]["status"] == M.LINK_OPENED)

    # ── token at rest ─────────────────────────────────────────
    section("Tokens at rest")

    h4 = fresh()
    doc = await links.create_assignment(
        company_id="c1", company_name="Acme", cycle="2026-C1",
        subject={"subject_id": "s1", "subject_name": "Rahul", "level": LEVEL},
        giver={"_id": "g9", "email": "g9@x.com", "full_name": "Asha"},
        relation="peer", assigned_by=HR)
    raw = doc["_issued_token"]
    row = h4.collection("tpms_leadership_assignments").docs[0]
    check("the raw token is never stored", row.get("token") is None)
    check("only its hash is stored", row.get("token_hash") == links.token_hash(raw))
    check("no resolvable URL is stored", row.get("link") is None)
    check("the hash does not reveal the token", links.token_hash(raw) != raw)
    check("a lookup by raw token still resolves",
          (await links.resolve_token(raw)) is not None)
    check("a wrong token resolves to nothing",
          (await links.resolve_token("not-the-token")) is None)

    panel = links.panel_row(row)
    check("a panel row hands back no link", "link" not in panel,
          "HR resends instead, which mints a fresh one")

    rotated = await links.rotate_token(row)
    check("rotating issues a different credential", rotated != raw)
    check("the old link stops working",
          (await links.resolve_token(raw)) is None, "single-use, as the resend says")

    # ── index specs ───────────────────────────────────────────
    #
    # A unique index over a field the code deliberately leaves unset must be SPARSE.
    # MongoDB indexes a missing field as null, so a non-sparse unique index accepts the
    # first such document and rejects every one after it as a duplicate key. Both token
    # fields are unset in normal operation - `token` on every new row, `token_hash` the
    # moment a form is submitted - so both indexes have to be sparse or the second panel
    # member cannot be created.
    section("Index specifications")

    by_name = {(c, o.get("name")): (k, o) for c, k, o in M.LEADERSHIP_INDEXES}
    for field in ("token", "token_hash"):
        name = "uniq_token" if field == "token" else "uniq_token_hash"
        _, opts = by_name[(M.COLL_LS_ASSIGNMENTS, name)]
        check(f"the unique index on {field} is sparse",
              opts.get("unique") and opts.get("sparse"),
              "the field is unset in normal operation")

    resp = [o.get("name") for c, k, o in M.LEADERSHIP_INDEXES
            if c == M.COLL_LS_RESPONSES and o.get("unique")]
    check("no unique index remains on responses", not resp,
          "a response carries nothing unique to key on")

    # An index whose OPTIONS changed must be dropped first: createIndex with the same name
    # and different options raises IndexKeySpecsConflict and the new options are silently
    # never applied.
    obsolete = set(M.LEADERSHIP_OBSOLETE_INDEXES)
    recreated = {(c, o.get("name")) for c, k, o in M.LEADERSHIP_INDEXES}
    check("uniq_token is dropped before being recreated sparse",
          (M.COLL_LS_ASSIGNMENTS, "uniq_token") in obsolete
          and (M.COLL_LS_ASSIGNMENTS, "uniq_token") in recreated)
    check("the old response index is dropped and not recreated",
          (M.COLL_LS_RESPONSES, "uniq_cycle_subject_giver") in obsolete
          and (M.COLL_LS_RESPONSES, "uniq_cycle_subject_giver") not in recreated)

    dupes = [k for k in recreated
             if len([1 for c, _, o in M.LEADERSHIP_INDEXES
                     if (c, o.get("name")) == k]) > 1]
    check("no two indexes on one collection share a name", not dupes, str(dupes) or "none")

    # ── publish gate ──────────────────────────────────────────
    section("A leader sees nothing until publication")

    h5 = fresh(status=M.CYCLE_OPEN)
    for i, rel in enumerate(["superior", "superior", "peer", "peer", "direct_report"]):
        aa = assignment(f"g{i}", rel)
        h5.collection("tpms_leadership_assignments").docs.append(aa)
        await svc.record_response(aa, answers_for(qs))

    hr_view = await svc.subject_score("c1", "2026-C1", "s1", include_relations=True)
    check("HR can see the score while collecting",
          hr_view["leadership_score"] is not None)

    leader_view = await svc.subject_score("c1", "2026-C1", "s1", for_leader=True)
    check("the leader sees no score", leader_view["leadership_score"] is None)
    check("and is told why", leader_view["state"] == "not_published")
    check("no response count leaks to them", "response_count" not in leader_view,
          "a count watched daily says when each of eight people replied")
    check("no parameters leak either", leader_view["parameters"] == [])

    # ── the gate must be applied by the ROUTE, not merely available ──
    #
    # The service grew a `for_leader` switch and no route passed it, so the gate existed
    # and did nothing. Testing the service alone could never have caught that: these
    # checks go through the request handlers, which is where the decision actually lives.
    section("The publish gate is applied by the route handlers")

    from app.routes import leadership as api

    leader = {"_id": "s1", "role": "clientuser", "company_id": "c1", "full_name": "Rahul"}
    manager = {"_id": "m1", "role": "clientuser", "company_id": "c1", "full_name": "Meera"}
    hr = {"_id": "u-hr", "role": "clientuser", "department": "hr", "company_id": "c1",
          "full_name": "Priya (HR)"}

    one = await api.read_subject_score("s1", cycle="2026-C1", company_id=None,
                                       current_user=leader)
    check("the route withholds a leader's own score pre-publication",
          one["leadership_score"] is None and one["state"] == "not_published")
    check("and withholds the trend with it", one["history"] == [],
          "otherwise this cycle's number arrives through the history instead")

    mgr = await api.read_subject_score("s1", cycle="2026-C1", company_id=None,
                                       current_user=manager)
    check("the reporting manager is gated too", mgr["leadership_score"] is None,
          "publication releases to leaders AND managers, so neither sees it earlier")

    hr_row = await api.read_subject_score("s1", cycle="2026-C1", company_id=None,
                                          current_user=hr)
    check("HR still sees it while collecting", hr_row["leadership_score"] is not None)

    listing = await api.read_scores(cycle="2026-C1", company_id=None, current_user=leader)
    check("the cycle listing is gated the same way",
          all(r["leadership_score"] is None for r in listing["rows"]),
          "a list endpoint is the easy way to forget a gate")

    # ── group weighting ───────────────────────────────────────
    section("Group-weighted, not rater-weighted")

    h6 = fresh()
    # Four superiors rate top (D=5); one junior rates bottom (A=1).
    for i in range(4):
        aa = assignment(f"sup{i}", "superior")
        h6.collection("tpms_leadership_assignments").docs.append(aa)
        await svc.record_response(aa, answers_for(qs, 5))
    aa = assignment("jr1", "direct_report")
    h6.collection("tpms_leadership_assignments").docs.append(aa)
    await svc.record_response(aa, answers_for(qs, 1))

    score = await svc.subject_score("c1", "2026-C1", "s1", include_relations=True)
    flat = (4 * 100 + 1 * 20) / 5          # what a flat rater average would give
    # Superiors all top (5 -> 100%), the lone junior all bottom (1 -> 20%).
    # Group-weighted: (100 + 20) / 2 = 60. Rater-weighted would be 84.
    check("the four-to-one split does not dominate",
          abs(score["leadership_score"] - 60.0) < 0.5,
          f"got {score['leadership_score']}, a flat rater average would be {flat}")
    check("both groups counted once each",
          score["groups_scored"] == 2 and score["groups_expected"] == 4)
    check("the default split is reported as a default",
          score["group_weightage_is_default"] is True)

    by_rel = {g["relation"]: g for g in score["by_relation"]}
    check("a group of one is withheld", by_rel["direct_report"]["withheld"] is True,
          "a group of one names its author")
    check("a group of four is shown", by_rel["superior"]["withheld"] is False)
    check("the two weakest parameters are named", len(score["focus_areas"]) == 2)

    # ── whole forms only ──────────────────────────────────────
    section("Part-filled forms are refused")

    h7 = fresh()
    a7 = assignment("g1")
    h7.collection("tpms_leadership_assignments").docs.append(a7)
    try:
        await svc.record_response(a7, answers_for(qs)[:2])
        check("a part-filled form is refused", False)
    except ValueError as e:
        check("a part-filled form is refused", True, str(e)[:48])
    check("and nothing was stored",
          len(h7.collection("tpms_leadership_responses").docs) == 0,
          "it used to count toward quorum while scoring out of less than 100")

    # ── frozen history ────────────────────────────────────────
    section("A published score cannot move")

    h8 = fresh(status=M.CYCLE_CLOSED, all_levels=True)
    for i, rel in enumerate(["superior", "superior", "peer", "peer", "direct_report"]):
        aa = assignment(f"g{i}", rel)
        h8.collection("tpms_leadership_assignments").docs.append(aa)
        await svc.record_response(aa, answers_for(qs, 4))
    await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_COMPUTED}, HR)
    before = (await svc.subject_score("c1", "2026-C1", "s1"))["leadership_score"]

    # Move a weightage after the freeze — the classic way history used to shift.
    await h8.collection("tpms_leadership_questions").update_one(
        {"level": LEVEL, "item_id": "L6Q1"}, {"$set": {"weightage": 90.0}})
    after = (await svc.subject_score("c1", "2026-C1", "s1"))["leadership_score"]
    check("editing a weightage does not move a frozen score", before == after,
          f"{before} before, {after} after")
    check("the score is reported as frozen",
          (await svc.subject_score("c1", "2026-C1", "s1")).get("frozen") is True)

    await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_PUBLISHED}, HR)
    published = await svc.subject_score("c1", "2026-C1", "s1", for_leader=True)
    check("once published the leader sees it", published["leadership_score"] == before)

    # ── state machine ─────────────────────────────────────────
    section("Cycle state machine")

    check("draft -> open is allowed", M.can_transition(M.CYCLE_DRAFT, M.CYCLE_OPEN))
    check("draft -> published is refused",
          not M.can_transition(M.CYCLE_DRAFT, M.CYCLE_PUBLISHED),
          "a score cannot be released without ever being computed")
    check("closed -> open is allowed", M.can_transition(M.CYCLE_CLOSED, M.CYCLE_OPEN),
          "so HR can extend a window when quorum is not met")
    check("published is terminal",
          not any(M.can_transition(M.CYCLE_PUBLISHED, t) for t in M.CYCLE_STATUSES))

    try:
        await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_OPEN}, HR)
        check("a published cycle cannot be reopened", False)
    except ValueError as e:
        check("a published cycle cannot be reopened", True, str(e)[:46])

    # ── panel lock ────────────────────────────────────────────
    section("Panel lock and eligibility")

    h9 = fresh()
    a9 = assignment("g1")
    h9.collection("tpms_leadership_assignments").docs.append(a9)
    await svc.record_response(a9, answers_for(qs))

    class G:
        def __init__(self, gid, rel):
            self.giver_id, self.relation = gid, rel
    try:
        await svc.set_panel("c1", "2026-C1", "s1", [G("g2", "peer")], HR)
        check("the panel is locked once feedback arrives", False)
    except ValueError as e:
        check("the panel is locked once feedback arrives", True, str(e)[:46])

    check("an unlevelled person is not eligible", not svc.is_eligible({"designation": "Sr. Manager"}))
    check("a levelled person is", svc.is_eligible({"leadership_level": "L5"}))
    check("the level is never guessed from the designation",
          svc.leadership_level_of({"designation": "Senior Manager"}) == "",
          "'Sr. Manager' vs 'Senior Manager' would silently split the same job")

    # ── resend is not a back door around the panel rule ───────
    section("Resend cannot invite an incomplete panel")

    # Found in production: a 360 cycle whose panel held two superiors and nothing else,
    # yet both givers had been emailed. Dispatch refuses that (409) because a score built
    # from two superiors is still labelled 360. Resend had no such check, so the panel
    # could be invited one person at a time through the per-row button.
    from app.routes import leadership as R
    import app.db.mongodb as mongodb
    from fastapi import HTTPException

    HRU = {"_id": "hr", "role": "clientuser", "department": "HR", "company_id": "c1"}
    CYC = {"company_id": "c1", "cycle": "2027-C1", "status": M.CYCLE_OPEN,
           "degree": M.DEGREE_360, "min_responses": 3, "quorum": 5}
    SUB = {"company_id": "c1", "cycle": "2027-C1", "subject_id": "s1", "level": "L6"}

    def _row(gid, relation, sent_at=None, status=M.LINK_PENDING):
        return {"_id": ObjectId(), "company_id": "c1", "cycle": "2027-C1",
                "subject_id": "s1", "giver_id": gid, "giver_name": gid,
                "giver_email": f"{gid}@x.invalid", "relation": relation, "status": status,
                "wa_status": M.WA_PENDING, "sent_at": sent_at, "subject_level": "L6",
                "expires_at": links.cycle_expiry_utc("2027-C1")}

    def _mount(rows, degree=M.DEGREE_360):
        harness = Harness(**{M.COLL_LS_CYCLES: [{**CYC, "degree": degree}],
                             M.COLL_LS_SUBJECTS: [dict(SUB)],
                             M.COLL_LS_ASSIGNMENTS: rows,
                             M.COLL_LS_QUESTIONS: M.all_seed_rows()})
        for mod in (svc, links, R, mongodb):
            mod.get_collection = harness.collection
        posted = []

        # Stubs the WHATSAPP send, because that is the only channel Leadership has now.
        # `posted` still collects one entry per invitation actually dispatched, so every
        # assertion below reads the same as it did on the email path.
        async def _fake_send(doc):
            posted.append(doc.get("giver_id"))
            return {"ok": True, "status": M.WA_SENT, "entry_id": "stub"}

        links.send_assignment_whatsapp = _fake_send
        R.links.send_assignment_whatsapp = _fake_send
        return harness, posted

    hh, posted = _mount([_row("g1", "superior"), _row("g2", "superior")])
    try:
        await R.resend(str(hh.collection(M.COLL_LS_ASSIGNMENTS).docs[0]["_id"]), HRU)
        check("a first invitation on an incomplete panel is refused", False, "it sent")
    except HTTPException as e:
        check("a first invitation on an incomplete panel is refused", e.status_code == 409,
              str(e.detail)[:52])
    check("and nothing was dispatched", posted == [])

    # The escape hatch must survive: chasing someone already delivered to is the whole
    # point of the button, and a panel that changed afterwards must not strand them.
    hh, posted = _mount([_row("g1", "superior", sent_at=datetime.utcnow(), status=M.LINK_SENT),
                         _row("g2", "superior")])
    res = await R.resend(str(hh.collection(M.COLL_LS_ASSIGNMENTS).docs[0]["_id"]), HRU)
    check("chasing an already-invited giver still works", res.get("ok") is True)
    check("their invitation went out", posted == ["g1"], str(posted))

    full = []
    for rel in M.RELATIONS:
        full += [_row(f"{rel}-a", rel), _row(f"{rel}-b", rel)]
    hh, posted = _mount(full)
    res = await R.resend(str(hh.collection(M.COLL_LS_ASSIGNMENTS).docs[0]["_id"]), HRU)
    check("a complete 360 panel invites normally", res.get("ok") is True and len(posted) == 1)

    hh, posted = _mount([_row("s-a", "superior"), _row("s-b", "superior"),
                         _row("p-a", "peer"), _row("p-b", "peer")], degree=M.DEGREE_180)
    res = await R.resend(str(hh.collection(M.COLL_LS_ASSIGNMENTS).docs[0]["_id"]), HRU)
    check("the rule follows the DEGREE - 4 completes a 180 panel", res.get("ok") is True)

    passed, total = sum(_results), len(_results)
    print(f"\n{'=' * 66}\n{passed}/{total} checks passed"
          f"{'' if passed == total else '  <-- FAILURES ABOVE'}\n{'=' * 66}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
