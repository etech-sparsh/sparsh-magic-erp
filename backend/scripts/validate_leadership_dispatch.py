"""Leadership "Email All Pending" validator - resend cooldown + closed/expired cycle guard.

Runs entirely against an IN-MEMORY fake Mongo with a stubbed mailer. No real database is
opened, no existing TPMS document is read or written, and no email is sent. Safe to run at
any time.

What it proves:

  cooldown       Pressing "Email All Pending" twice in a row mails each giver ONCE. The
                 second press holds everyone already mailed and says how many it held.
  cooldown ends  After RESEND_COOLDOWN_HOURS the same button chases them again, so the
                 chase capability is delayed, never removed.
  never stuck    A giver who has never been mailed, or whose last send FAILED, is not held
                 back - a cooldown must never be the reason someone lacks their link.
  submitted      An already-submitted giver is never mailed, cooldown or not.
  manual resend  The explicit per-assignment resend still works during the cooldown - the
                 escape hatch that keeps "resend if needed" available.
  closed cycle   Dispatch is refused server-side for a CLOSED cycle.
  expired cycle  Dispatch is refused server-side once the cycle window has elapsed.
  open cycle     A live cycle still dispatches normally.
  ui flag        list_cycles reports `can_dispatch`, matching assert_dispatchable exactly,
                 so the button and the API can never disagree.

Usage (PowerShell, from backend/):
    python scripts/validate_leadership_dispatch.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

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
        self.docs = [dict(d) for d in (docs or [])]

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

    def find(self, query=None):
        rows = [d for d in self.docs if self._match(d, query or {})]
        class _C:
            def sort(self, *a, **k): return self
            async def to_list(self, n=None): return rows
        return _C()

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def count_documents(self, query):
        return len([d for d in self.docs if self._match(d, query)])

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**query, **update.get("$set", {})})

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


CYCLE_LIVE = f"{datetime.now(timezone.utc).year + 1}-C6"   # always in the future
CYCLE_PAST = "2020-C1"                                      # window long elapsed


def assignment(gid: str, *, sent_at=None, email_status="pending", status="sent",
               cycle: str = CYCLE_LIVE):
    """One panel member's link row.

    `_id` must be a real ObjectId: mark_email_result coerces it, exactly as it does against
    Mongo, so a fake string id would fail for a reason that has nothing to do with dispatch.
    """
    from bson import ObjectId
    return {
        "_id": ObjectId(),
        "company_id": "c1", "cycle": cycle, "subject_id": "s1", "giver_id": gid,
        "link": f"https://x/lf/tok-{gid}", "token": f"tok-{gid}",
        "giver_name": f"Giver {gid}", "giver_email": f"{gid}@x.com",
        "subject_name": "Rahul", "subject_level": "L6", "company_name": "Acme",
        "relation": "peer", "status": status, "email_status": email_status,
        "sent_at": sent_at, "expires_at": None,
    }


class Harness:
    """Patches the two services onto fake collections and a stub mailer."""

    def __init__(self, assignments, cycle_doc):
        self.assignments = FakeCollection(assignments)
        self.cycles = FakeCollection([cycle_doc])
        self.empty = FakeCollection()
        self.mailed: list = []

    def collection(self, name):
        if name == "tpms_leadership_assignments":
            return self.assignments
        if name == "tpms_leadership_cycles":
            return self.cycles
        return self.empty

    async def fake_send_email(self, to, subject, html, user_id=None, slug=None, cc=None, meta=None):
        self.mailed.append(to)
        return True

    async def no_template(self, company_id=None):
        """No stored template — dispatch falls back to the built-in body. Stubbed so the
        test never reaches for the real tpms_mail_templates collection.

        Takes `company_id` because the real lookup is company-scoped: a template authored
        by one client must never be mailed out by another."""
        return None

    def __enter__(self):
        from app.services import leadership_link_service as links
        from app.services import leadership_service as svc
        import app.services.notification_service as ns
        self._links, self._svc, self._ns = links, svc, ns
        self._orig = (links.get_collection, svc.get_collection,
                      ns.send_email_notification, links.get_invite_template)
        links.get_collection = self.collection
        svc.get_collection = self.collection
        ns.send_email_notification = self.fake_send_email
        links.get_invite_template = self.no_template
        return self

    def __exit__(self, *a):
        (self._links.get_collection, self._svc.get_collection,
         self._ns.send_email_notification, self._links.get_invite_template) = self._orig


def open_cycle(status="open", cycle="2026-C3"):
    return {"_id": "c-1", "company_id": "c1", "cycle": cycle, "status": status,
            "degree": "360", "min_responses": 3}


# ─────────────────────────────────────────────────────────────
# 1 — resend cooldown
# ─────────────────────────────────────────────────────────────
async def check_cooldown_blocks_double_click():
    section("Repeated clicks do not duplicate mail")
    from app.services import leadership_link_service as links
    from app.models.leadership import RESEND_COOLDOWN_HOURS

    # A live cycle far in the future so expiry never interferes with this check.
    future = CYCLE_LIVE
    rows = [assignment("g1"), assignment("g2"), assignment("g3")]
    with Harness(rows, open_cycle(cycle=future)) as h:
        r1 = await links.dispatch_pending("c1", future)
        check("first press mails everyone", r1["sent"] == 3, f"sent={r1['sent']}")
        check("nothing held on the first press", r1["skipped_recent"] == 0)

        r2 = await links.dispatch_pending("c1", future)
        check("second press mails NOBODY", r2["sent"] == 0, f"sent={r2['sent']}")
        check("second press reports what it held", r2["skipped_recent"] == 3,
              f"held={r2['skipped_recent']}")
        check("only 3 emails in total across 2 presses", len(h.mailed) == 3,
              f"emails={len(h.mailed)}")
        check("cooldown window is reported to the caller",
              r2["cooldown_hours"] == RESEND_COOLDOWN_HOURS, f"{r2['cooldown_hours']}h")
        check("caller is told when the next send is due", r2["next_resend_at"] is not None)

        r3 = await links.dispatch_pending("c1", future)
        check("a third press still mails nobody", r3["sent"] == 0 and len(h.mailed) == 3)


async def check_cooldown_expires():
    section("The chase still works once the cooldown passes")
    from app.services import leadership_link_service as links
    from app.models.leadership import RESEND_COOLDOWN_HOURS

    future = CYCLE_LIVE
    stale = datetime.now(timezone.utc) - timedelta(hours=RESEND_COOLDOWN_HOURS + 1)
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    rows = [
        assignment("old", sent_at=stale, email_status="sent"),
        assignment("new", sent_at=fresh, email_status="sent"),
    ]
    with Harness(rows, open_cycle(cycle=future)) as h:
        r = await links.dispatch_pending("c1", future)
        check("a giver mailed longer ago than the cooldown IS chased", r["sent"] == 1,
              f"sent={r['sent']}")
        check("a recently-mailed giver is still held", r["skipped_recent"] == 1)
        check("the right person was mailed", h.mailed == ["old@x.com"], str(h.mailed))


async def check_never_blocks_undelivered():
    section("A cooldown never leaves someone without their link")
    from app.services import leadership_link_service as links

    future = CYCLE_LIVE
    just_now = datetime.now(timezone.utc)
    rows = [
        assignment("never", sent_at=None, email_status="pending"),
        assignment("failed", sent_at=just_now, email_status="failed"),
        assignment("sent", sent_at=just_now, email_status="sent"),
    ]
    with Harness(rows, open_cycle(cycle=future)) as h:
        r = await links.dispatch_pending("c1", future)
        check("never-mailed giver is sent immediately", "never@x.com" in h.mailed)
        check("previously FAILED giver is retried immediately", "failed@x.com" in h.mailed)
        check("only the successfully-mailed one is held", r["skipped_recent"] == 1,
              f"held={r['skipped_recent']}")
        check("2 of 3 were mailed", r["sent"] == 2, f"sent={r['sent']}")

    # Direct predicate checks.
    check("in_resend_cooldown: never sent -> False",
          links.in_resend_cooldown(assignment("x", sent_at=None)) is False)
    check("in_resend_cooldown: failed send -> False",
          links.in_resend_cooldown(assignment("x", sent_at=just_now, email_status="failed")) is False)
    check("in_resend_cooldown: just sent -> True",
          links.in_resend_cooldown(assignment("x", sent_at=just_now, email_status="sent")) is True)


async def check_submitted_never_mailed():
    section("A submitted giver is never mailed again")
    from app.services import leadership_link_service as links

    future = CYCLE_LIVE
    rows = [assignment("done", status="submitted"), assignment("pending")]
    with Harness(rows, open_cycle(cycle=future)) as h:
        r = await links.dispatch_pending("c1", future)
        check("only the pending giver is mailed", h.mailed == ["pending@x.com"], str(h.mailed))
        check("submitted rows are not even counted as pending", r["total"] == 1,
              f"total={r['total']}")


# ─────────────────────────────────────────────────────────────
# 2 — closed / expired cycle
# ─────────────────────────────────────────────────────────────
async def check_closed_and_expired_rejected():
    section("Closed or expired cycles are refused server-side")
    from app.services import leadership_service as svc
    from app.services import leadership_link_service as links

    future, past = CYCLE_LIVE, CYCLE_PAST

    # Open + in-window -> allowed.
    with Harness([], open_cycle(cycle=future)):
        try:
            await svc.assert_dispatchable("c1", future)
            check("an open, in-window cycle is dispatchable", True)
        except ValueError as e:
            check("an open, in-window cycle is dispatchable", False, str(e))

    # Closed -> refused.
    with Harness([], open_cycle(status="closed", cycle=future)):
        try:
            await svc.assert_dispatchable("c1", future)
            check("a CLOSED cycle is refused", False, "no error raised")
        except ValueError as e:
            check("a CLOSED cycle is refused", "closed" in str(e).lower(), str(e)[:58])

    # Window elapsed -> refused even while status is 'open'.
    with Harness([], open_cycle(status="open", cycle=past)):
        try:
            await svc.assert_dispatchable("c1", past)
            check("an EXPIRED cycle is refused", False, "no error raised")
        except ValueError as e:
            check("an EXPIRED cycle is refused", "expired" in str(e).lower()
                  or "ended" in str(e).lower(), str(e)[:58])

    # Unknown cycle.
    with Harness([], open_cycle(cycle=future)):
        try:
            await svc.assert_dispatchable("c1", "2099-C1")
            check("an unknown cycle is refused", False, "no error raised")
        except ValueError as e:
            check("an unknown cycle is refused", "exist" in str(e).lower(), str(e)[:48])

    check("cycle_is_expired: past window -> True", links.cycle_is_expired(past) is True)
    check("cycle_is_expired: future window -> False", links.cycle_is_expired(future) is False)


async def check_dispatch_route_returns_409():
    section("The dispatch route answers 409, not 500")
    from fastapi import HTTPException
    from app.routes.leadership import dispatch

    hr = {"_id": "u1", "role": "clientuser", "governance_role": "hr", "company_id": "c1"}

    with Harness([], open_cycle(status="closed", cycle=CYCLE_LIVE)):
        try:
            await dispatch(CYCLE_LIVE, None, None, hr)
            check("closed cycle -> HTTP error", False, "no exception")
        except HTTPException as e:
            check("closed cycle -> HTTP 409", e.status_code == 409, f"{e.status_code}: {e.detail[:40]}")

    with Harness([], open_cycle(status="open", cycle=CYCLE_PAST)):
        try:
            await dispatch(CYCLE_PAST, None, None, hr)
            check("expired cycle -> HTTP error", False, "no exception")
        except HTTPException as e:
            check("expired cycle -> HTTP 409", e.status_code == 409, f"{e.status_code}: {e.detail[:40]}")

    # And a live one still works through the route.
    with Harness([assignment("g1")], open_cycle(cycle=CYCLE_LIVE)) as h:
        res = await dispatch(CYCLE_LIVE, None, None, hr)
        check("a live cycle still dispatches through the route", res["sent"] == 1,
              f"sent={res['sent']}")


async def check_can_dispatch_flag():
    section("list_cycles exposes can_dispatch for the UI")
    from app.services import leadership_service as svc

    cases = [
        (open_cycle(status="open", cycle=CYCLE_LIVE), True, "open + in window"),
        (open_cycle(status="draft", cycle=CYCLE_LIVE), True, "draft + in window"),
        (open_cycle(status="closed", cycle=CYCLE_LIVE), False, "closed"),
        (open_cycle(status="open", cycle=CYCLE_PAST), False, "window elapsed"),
    ]
    for doc, expected, label in cases:
        with Harness([], doc):
            rows = await svc.list_cycles("c1")
            got = rows[0].get("can_dispatch")
            check(f"can_dispatch for {label} -> {expected}", got is expected, f"got {got}")

    # The flag must agree with the server-side rule in every case.
    for doc, expected, label in cases:
        with Harness([], doc):
            rows = await svc.list_cycles("c1")
            try:
                await svc.assert_dispatchable("c1", doc["cycle"])
                allowed = True
            except ValueError:
                allowed = False
            check(f"UI flag matches the API rule for {label}",
                  rows[0]["can_dispatch"] is allowed, f"flag={rows[0]['can_dispatch']} api={allowed}")


async def check_manual_resend_bypasses_cooldown():
    section("Explicit per-person resend still works during the cooldown")
    from app.services import leadership_link_service as links

    just_now = datetime.now(timezone.utc)
    row = assignment("g1", sent_at=just_now, email_status="sent")
    with Harness([row], open_cycle()) as h:
        check("the row IS in cooldown", links.in_resend_cooldown(row) is True)
        result = await links.send_assignment_email(row)
        check("a deliberate single resend still sends", result.get("ok") is True)
        check("the mail actually went out", h.mailed == ["g1@x.com"], str(h.mailed))


async def main() -> int:
    print("Leadership dispatch validator - in-memory fake DB, no real data, no email sent.")
    await check_cooldown_blocks_double_click()
    await check_cooldown_expires()
    await check_never_blocks_undelivered()
    await check_submitted_never_mailed()
    await check_closed_and_expired_rejected()
    await check_dispatch_route_returns_409()
    await check_can_dispatch_flag()
    await check_manual_resend_bypasses_cooldown()

    passed, total = sum(1 for r in _results if r), len(_results)
    print("\n" + "=" * 68)
    print(f"{passed}/{total} checks passed")
    print("=" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
