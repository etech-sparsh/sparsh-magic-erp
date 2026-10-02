"""Cross-language capability parity guard.

Asserts that the backend `Cap` enum and the frontend `CAP` map in
frontend/src/features/hrms/access.js describe exactly the same capability set.

-- Why this test exists ------------------------------------------------------------
Phase 2 shipped a real defect this would have caught immediately: eight capabilities were
added to the backend `Cap` enum, the components were written against `CAP.EMPLOYEE_WRITE`
and friends, but the JS `CAP` map still held only Phase 1's three entries. Every lookup
resolved to `undefined`, `hasCap(caps, undefined)` returned false, and so every Phase 2
write control was invisible -- even to HR, who holds all of them.

It is silent by construction: no crash, no console error, no failing backend test. The
frontend simply renders less than it should, which reads as a permissions problem rather
than a bug.

The two lists are inherently duplicated (one per language). Duplication is fine; *silent
divergence* is not. This test makes divergence loud, and costs one regex.

Run:  python -m app.services.hrms.tests.test_capability_parity   (from backend/)
"""
from __future__ import annotations

import re
from pathlib import Path

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


# .../backend/app/services/hrms/tests/this.py -> parents[5] is the repo root.
ACCESS_JS = (Path(__file__).resolve().parents[5]
             / "frontend" / "src" / "features" / "hrms" / "access.js")


def main() -> None:
    from app.models.hrms import Cap

    print("\n-- Capability parity: backend Cap <-> frontend CAP --")

    if not ACCESS_JS.exists():
        check(f"access.js found at {ACCESS_JS}", False)
        raise SystemExit(1)

    source = ACCESS_JS.read_text(encoding="utf-8")

    # Isolate the `export const CAP = { ... };` block so unrelated string literals in the
    # file cannot be mistaken for capability values.
    block = re.search(r"export const CAP\s*=\s*\{(.*?)\n\};", source, re.S)
    if not block:
        check("CAP map located in access.js", False)
        raise SystemExit(1)
    check("CAP map located in access.js", True)

    js_values = set(re.findall(r"['\"]([a-z_]+\.[a-z_.]+)['\"]", block.group(1)))
    py_values = {c.value for c in Cap}

    missing_in_js = sorted(py_values - js_values)
    extra_in_js = sorted(js_values - py_values)

    check(f"backend declares {len(py_values)} capabilities", len(py_values) > 0)
    check(f"frontend declares {len(js_values)} capabilities", len(js_values) > 0)

    if missing_in_js:
        print(f"     MISSING from frontend CAP: {', '.join(missing_in_js)}")
    check("every backend capability exists in the frontend CAP map", not missing_in_js)

    if extra_in_js:
        print(f"     UNKNOWN in frontend CAP (no backend Cap): {', '.join(extra_in_js)}")
    check("frontend declares no capability the backend does not have", not extra_in_js)

    # The components look capabilities up as CAP.SOMETHING. A key whose value is a typo
    # would still be `undefined` at the call site, so verify the KEY names line up with the
    # enum member names too, not only the string values.
    js_keys = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*:", block.group(1), re.M))
    py_keys = {c.name for c in Cap}
    key_gap = sorted(py_keys - js_keys)
    if key_gap:
        print(f"     MISSING keys in frontend CAP: {', '.join(key_gap)}")
    check("every backend Cap member name has a matching frontend CAP key", not key_gap)

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
