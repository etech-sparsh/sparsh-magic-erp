"""Client Hiring -- the stage screens must offer exactly the moves the API accepts.

Each Client Hiring screen declares its actions as data:

    { id: 'client-approve', label: 'Approve CV', cap: CAP.CLIENT_CANDIDATE_DECIDE,
      from: ['Shared with Client'], remarks: true }

That declaration mirrors a row of the server's transition table. It is NOT the authority --
every route re-checks the capability and the from-state -- but a button the API would
refuse is a lie to whoever is looking at it, and a MISSING button is a stage somebody
cannot move at all with no error to explain why. Both failures are silent in the browser,
which is precisely why they belong in a test.

Four properties this file pins, per screen:

  1. EVERY ACTION EXISTS. No screen offers an id the transition table does not define.
  2. EVERY ACTION IS OFFERED. No transition is left without a control, so the flow cannot
     dead-end on a move that only exists over the API.
  3. THE CAPABILITY MATCHES. A button gated on the wrong capability either hides itself
     from the person whose job it is, or shows itself to somebody the API will refuse.
  4. THE FROM-STATE AND THE REASON MATCH. A control offered in the wrong state is a dead
     button; a move that needs remarks must ask for them, or the API rejects the click.

This is the client-track sibling of test_capability_parity, which pins the capability
NAMES across the same boundary. That one asks "do both sides know the same words"; this
one asks "do both sides agree what those words permit".

House convention: self-contained, no pytest, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_ui_contract   (from backend/)
"""
from __future__ import annotations

import asyncio
import pathlib
import re

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


# backend/app/services/hrms/tests/ -> repo root -> frontend/src/features/hrms/client
CLIENT_UI = (pathlib.Path(__file__).resolve().parents[4].parent
             / "frontend" / "src" / "features" / "hrms" / "client")

# Which declaration in which screen mirrors which server table. Adding a stage means
# adding a line here, which is the point: a new screen with no entry is a screen nobody
# checked.
SCREENS = [
    ("ClientRequisitions.jsx", None, "CLIENT_REQ_TRANSITIONS"),
    ("ClientScorecards.jsx", "MOVES", "CLIENT_SCORECARD_TRANSITIONS"),
    ("ClientPostings.jsx", "MOVES", "CLIENT_POSTING_TRANSITIONS"),
    ("ClientCandidates.jsx", "CANDIDATE_MOVES", "CLIENT_CANDIDATE_TRANSITIONS"),
    ("ClientCandidates.jsx", "ASSESSMENT_MOVES", "CLIENT_ASSESSMENT_TRANSITIONS"),
    ("ClientCandidates.jsx", "INTERVIEW_MOVES", "CLIENT_INTERVIEW_TRANSITIONS"),
    # The dedicated boards declare the same moves independently, so they are pinned too.
    ("ClientAssessments.jsx", "MOVES", "CLIENT_ASSESSMENT_TRANSITIONS"),
    ("ClientInterviews.jsx", "MOVES", "CLIENT_INTERVIEW_TRANSITIONS"),
    ("ClientOffers.jsx", "MOVES", "CLIENT_OFFER_TRANSITIONS"),
    ("ClientJoinings.jsx", "MOVES", "CLIENT_JOINING_TRANSITIONS"),
]

# The requisition screen predates the shared `Moves` helper and spells its two controls
# out inline, so there is no array to parse. Its transitions are covered by
# test_client_requisition; what is asserted here is only that the ids it posts are real.
INLINE_SCREENS = {"ClientRequisitions.jsx"}


def read_screen(name: str) -> str:
    path = CLIENT_UI / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _top_level_objects(text: str) -> list[str]:
    """Split `{...}, {...}` into its top-level objects, by counting braces.

    A regex cannot do this: a move that declares `fields: [{ name: ... }]` nests objects,
    and any non-greedy pattern stops at the first inner `}` -- which reads as a move with
    no fields at all, i.e. exactly the bug this file exists to catch, silently passing.
    """
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i])
                start = None
    return out


def parse_moves(source: str, const: str) -> list[dict]:
    """Pull one `const NAME = [ ... ];` array of move objects out of a screen.

    A deliberately small parser rather than a JS engine: the declarations are a fixed
    shape by convention, and a parser that silently accepted a shape it did not
    understand would report a passing test on an unread file. Anything it cannot read
    raises instead.
    """
    m = re.search(rf"^const {const} = \[(.*?)^\];", source, re.S | re.M)
    if not m:
        raise AssertionError(f"could not find `const {const} = [...]`")

    moves = []
    for body in _top_level_objects(m.group(1)):
        idm = re.search(r"id:\s*'([^']+)'", body)
        capm = re.search(r"cap:\s*CAP\.(\w+)", body)
        if not idm or not capm:
            continue
        froms = re.search(r"from:\s*\[(.*?)\]", body, re.S)
        # `fields` is declared last in a move, so everything after it is the field list.
        fields = re.search(r"fields:\s*\[(.*)", body, re.S)
        moves.append({
            "id": idm.group(1),
            "cap": capm.group(1),
            "from": set(re.findall(r"'([^']+)'", froms.group(1))) if froms else set(),
            "remarks": bool(re.search(r"remarks:\s*true", body)),
            "fields": set(re.findall(r"name:\s*'([^']+)'", fields.group(1)))
                      if fields else set(),
        })
    if not moves:
        raise AssertionError(f"`{const}` parsed to nothing")
    return moves


async def main() -> None:
    from app.models import hrms as M

    check("the client UI directory is where this test expects it", CLIENT_UI.is_dir())
    if not CLIENT_UI.is_dir():
        print(f"\n  looked in: {CLIENT_UI}")
        raise SystemExit(1)

    for screen, const, table_name in SCREENS:
        source = read_screen(screen)
        table = getattr(M, table_name)

        section(f"{screen}{f' :: {const}' if const else ''} vs {table_name}")

        if not check(f"{screen} exists", bool(source)):
            continue

        if screen in INLINE_SCREENS:
            # Only assert that every action id this screen posts is a real transition.
            posted = set(re.findall(r"act\((?:[^,]+),\s*'([^']+)'", source))
            posted |= set(re.findall(r"action:\s*'([^']+)'", source))
            unknown = posted - set(table)
            check(f"every posted action is a real transition ({len(posted)} found)",
                  not unknown)
            if unknown:
                print(f"      not in {table_name}: {sorted(unknown)}")
            continue

        try:
            moves = parse_moves(source, const)
        except AssertionError as e:
            check(f"{const} is readable ({e})", False)
            continue

        declared = {m["id"] for m in moves}

        # 1. Every action the screen offers exists on the server.
        unknown = declared - set(table)
        check("no screen offers an action the API does not define", not unknown)
        if unknown:
            print(f"      not in {table_name}: {sorted(unknown)}")

        # 2. Every transition the server defines has a control.
        missing = set(table) - declared
        check("every transition has a control on the screen", not missing)
        if missing:
            print(f"      no button for: {sorted(missing)}")

        # 3/4. Capability, from-state and remarks agree, move by move.
        for mv in moves:
            if mv["id"] not in table:
                continue
            frm, _to, cap_name, needs_remarks = table[mv["id"]]

            check(f"{mv['id']}: capability is {cap_name}", mv["cap"] == cap_name)

            frm_value = frm.value if hasattr(frm, "value") else str(frm)
            check(f"{mv['id']}: offered from '{frm_value}'",
                  mv["from"] == {frm_value})
            if mv["from"] != {frm_value}:
                print(f"      screen says {sorted(mv['from'])}")

            check(f"{mv['id']}: {'asks for' if needs_remarks else 'does not ask for'} "
                  f"a reason", mv["remarks"] == bool(needs_remarks))

    # =================================================================
    section("Moves that need more than a reason ask for it")
    # =================================================================
    # Two actions demand extra fields and refuse the request without them -- section 18's
    # joining confirmation wants the real start date and the candidate's acknowledgement,
    # section 17's acceptance wants both dates because a verbal offer is not valid. A
    # button that posts only `remarks` into either is a button that always 422s.
    #
    # Rather than list the two, this reads the services: any `payload.get("x")` inside an
    # `if action == "y":` block is a field that move needs, so a THIRD one added later is
    # caught by the same check instead of being found in the browser.
    SERVICES = [
        ("hrms_client_scorecard_service.py", "ClientScorecards.jsx", "MOVES"),
        ("hrms_client_posting_service.py", "ClientPostings.jsx", "MOVES"),
        ("hrms_client_candidate_service.py", "ClientCandidates.jsx", "CANDIDATE_MOVES"),
        ("hrms_client_assessment_service.py", "ClientCandidates.jsx", "ASSESSMENT_MOVES"),
        ("hrms_client_interview_service.py", "ClientCandidates.jsx", "INTERVIEW_MOVES"),
        ("hrms_client_offer_service.py", "ClientOffers.jsx", "MOVES"),
        ("hrms_client_joining_service.py", "ClientJoinings.jsx", "MOVES"),
    ]
    services_dir = pathlib.Path(__file__).resolve().parents[2]

    for service, screen, const in SERVICES:
        src = (services_dir / service).read_text(encoding="utf-8")
        needed: dict[str, set] = {}
        current_action, indent = None, None
        for line in src.splitlines():
            stripped = line.strip()
            m = re.match(r'if action == "([^"]+)":', stripped)
            if m:
                current_action = m.group(1)
                indent = len(line) - len(line.lstrip())
                needed.setdefault(current_action, set())
                continue
            if current_action is not None:
                if stripped and (len(line) - len(line.lstrip())) <= indent:
                    # Back out to the same level: this block has ended. A new `if action`
                    # is handled by the branch above on the next pass.
                    current_action = None
                    continue
                for key in re.findall(r'payload\.get\("([^"]+)"\)', line):
                    if key != "remarks":
                        needed[current_action].add(key)

        needed = {a: k for a, k in needed.items() if k}
        if not needed:
            check(f"{service}: no action needs extra fields", True)
            continue

        declared = {m["id"]: m["fields"] for m in parse_moves(read_screen(screen), const)}
        for action, keys in sorted(needed.items()):
            have = declared.get(action, set())
            ok = keys <= have
            check(f"{screen} :: {action} collects {sorted(keys)}", ok)
            if not ok:
                print(f"      screen collects {sorted(have)}; "
                      f"missing {sorted(keys - have)}")

    # =================================================================
    section("Capability names on the screens are real capabilities")
    # =================================================================
    # A CAP.X the frontend does not define reads as `undefined` at runtime, and
    # `can(undefined)` is false, so the control silently never appears.
    access = (CLIENT_UI.parent / "access.js").read_text(encoding="utf-8")
    known = set(re.findall(r"^\s*(CLIENT_\w+):\s*'", access, re.M))
    used = set()
    for screen, const, _ in SCREENS:
        if not const:
            continue
        used |= {m["cap"] for m in parse_moves(read_screen(screen), const)}
    check(f"every CAP.* used by a stage screen is defined in access.js "
          f"({len(used)} used)", used <= known)
    if used - known:
        print(f"      undefined on the frontend: {sorted(used - known)}")

    # And the same names must exist on the server, or the API would never grant them.
    server = {c.name for c in M.Cap}
    check("...and every one of them is a real server capability", used <= server)
    if used - server:
        print(f"      not in Cap: {sorted(used - server)}")

    # =================================================================
    section("A client company's user can actually reach the track")
    # =================================================================
    # The whole track was unreachable in the browser for a while because routes/user.py
    # sent the frontend ONE flag, `hrms_enabled`, computed as `hrms_enabled AND
    # is_internal` -- correct for the module, fatal for the client track. A client company
    # always got false, so the sidebar hid HRMS entirely and Client Hiring existed only for
    # Sparsh staff. Nothing failed; the menu item simply was not there.
    #
    # The fix is a second flag, and the failure mode is a NAME MISMATCH across a boundary
    # neither side type-checks. So: the server must send it and the frontend must read it.
    FLAG = "client_hiring_enabled"

    user_route = (pathlib.Path(__file__).resolve().parents[3]
                  / "routes" / "user.py").read_text(encoding="utf-8")
    check(f"routes/user.py sets `{FLAG}` on the profile",
          f'current_user["{FLAG}"]' in user_route)
    check("...as `hrms_enabled AND NOT is_internal`, never requiring is_internal",
          "_on and not _internal" in user_route)
    check("...and `hrms_enabled` still requires is_internal, so the module stays in-house",
          "_on and _internal" in user_route)

    access = (CLIENT_UI.parent / "access.js").read_text(encoding="utf-8")
    check(f"access.js reads `{FLAG}`", FLAG in access)
    check("isClientTrackUser is exported for the sidebar and the route guard",
          "export const isClientTrackUser" in access)

    sidebar = (CLIENT_UI.parents[2] / "components" / "layout"
               / "Sidebar.jsx").read_text(encoding="utf-8")
    check("the sidebar narrows to the client track for a client user",
          "isClientTrackUser" in sidebar and "clientTrack" in sidebar)

    gate = (CLIENT_UI.parent / "HrmsGate.jsx").read_text(encoding="utf-8")
    check("the route guard sends a client user to Client Hiring, not the module home",
          "isClientTrackUser" in gate and "/hrms/client-" in gate)

    total, passed = len(results), sum(results)
    print(f"\n{'=' * 64}\n  {passed}/{total} checks passed\n{'=' * 64}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
