"""Real-KnowledgeBase (RAG) validation for the ERP AI Assistant.

Measures retrieval quality and access control against the ACTUAL KnowledgeBase,
via the running assistant. Standalone HTTP client (requests only).

What it captures per prompt (from meta.attributions of the search_knowledge tool):
    * number of sources returned (0 => empty retrieval)
    * cited document titles (for manual relevance / false-positive review)

Access control:
    * Run the SAME knowledge prompt as two different learner tokens and confirm
      they do not receive each other's restricted documents (manual title diff +
      automated overlap report).

Prerequisites:
    * Backend running with a populated KnowledgeBase.
    * Two learner JWTs in different cohorts/companies.

Usage (PowerShell):
    $env:ASSISTANT_BASE_URL  = "http://localhost:8000"
    $env:ASSISTANT_TOKEN     = "<learner_A_jwt>"
    $env:ASSISTANT_TOKEN_ALT = "<learner_B_jwt>"   # optional, for access-control test
    python scripts/validate_knowledge.py
"""
from __future__ import annotations

import json
import os

import requests

BASE = os.environ.get("ASSISTANT_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("ASSISTANT_TOKEN", "")
TOKEN_ALT = os.environ.get("ASSISTANT_TOKEN_ALT", "")
TIMEOUT = int(os.environ.get("ASSISTANT_TIMEOUT", "60"))

# Conceptual prompts. Mark `expect_coverage=False` for topics you believe are NOT
# in the KnowledgeBase — those should ideally return 0 sources (a non-empty result
# there is a potential false positive to review).
PROMPTS = [
    ("what is polymorphism", True),
    ("explain database normalization", True),
    ("summarize the onboarding process", True),
    ("what is the airspeed velocity of an unladen swallow", False),
]


def knowledge_sources(token: str, prompt: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"message": prompt, "stream": False}
    r = requests.post(f"{BASE}/api/assistant/ask", json=body, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    titles = []
    for attr in data.get("meta", {}).get("attributions", []):
        if attr.get("tool") == "search_knowledge":
            titles = [s for s in attr.get("sources", []) if s != "KnowledgeBase"]
    return titles, (data.get("answer") or "")[:300]


def main():
    if not TOKEN:
        raise SystemExit("Set ASSISTANT_TOKEN first.")

    rows, empties, false_positives = [], 0, 0
    print(f"\nKnowledgeBase validation against {BASE} ...\n")

    for prompt, expect_coverage in PROMPTS:
        titles, answer = knowledge_sources(TOKEN, prompt)
        is_empty = len(titles) == 0
        empties += int(is_empty)
        if (not expect_coverage) and not is_empty:
            false_positives += 1
        rows.append({"prompt": prompt, "expect_coverage": expect_coverage,
                     "sources": titles, "source_count": len(titles), "answer": answer})
        print(f"  [{'EMPTY' if is_empty else 'HIT  '}] {len(titles)} src | {prompt!r}")

    access = None
    if TOKEN_ALT:
        probe = "what is polymorphism"
        a_titles, _ = knowledge_sources(TOKEN, probe)
        b_titles, _ = knowledge_sources(TOKEN_ALT, probe)
        overlap = sorted(set(a_titles) & set(b_titles))
        access = {"probe": probe, "user_a_sources": a_titles, "user_b_sources": b_titles,
                  "shared": overlap}
        print(f"\n  Access-control probe — A:{a_titles} | B:{b_titles} | shared:{overlap}")
        print("  REVIEW: 'shared' must contain only documents BOTH users are legitimately entitled to.")

    summary = {
        "prompts": len(PROMPTS),
        "empty_retrievals": empties,
        "empty_rate": round(empties / len(PROMPTS), 3),
        "potential_false_positives": false_positives,
        "access_control": access,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))

    with open("validate_knowledge_report.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print("\nFull report -> validate_knowledge_report.json (review source relevance manually).")


if __name__ == "__main__":
    main()
