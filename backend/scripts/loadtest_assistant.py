from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = os.environ.get("ASSISTANT_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("ASSISTANT_TOKEN", "")
ADMIN_TOKEN = os.environ.get("ASSISTANT_ADMIN_TOKEN", "")
TIMEOUT = int(os.environ.get("ASSISTANT_TIMEOUT", "60"))

PROMPTS = [
    "How am I performing overall?",
    "What sessions do I have coming up?",
    "What should I study today?",
    "What is polymorphism?",
    "How did I do on my last quiz?",
]

def one_request(i: int):
    prompt = PROMPTS[i % len(PROMPTS)]
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    body = {"message": prompt, "stream": False}
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{BASE}/api/assistant/ask", json=body, headers=headers, timeout=TIMEOUT)
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"status": r.status_code, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        return {"status": "exc", "latency_ms": (time.perf_counter() - t0) * 1000, "error": str(exc)}


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return round(values[k], 1)


def fetch_metrics():
    if not ADMIN_TOKEN:
        return None
    try:
        r = requests.get(f"{BASE}/api/assistant/metrics",
                         headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}, timeout=TIMEOUT)
        return r.json() if r.ok else None
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--total", type=int, default=100)
    args = ap.parse_args()
    if not TOKEN:
        raise SystemExit("Set ASSISTANT_TOKEN first.")

    print(f"\nLoad test: {args.total} requests @ concurrency {args.concurrency} -> {BASE}\n")
    metrics_before = fetch_metrics()

    started = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one_request, i) for i in range(args.total)]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall = time.perf_counter() - started

    ok = [r for r in results if r["status"] == 200]
    rate_limited = [r for r in results if r["status"] == 429]
    errors = [r for r in results if r["status"] not in (200, 429)]
    lat = [r["latency_ms"] for r in ok]

    metrics_after = fetch_metrics()

    summary = {
        "total": len(results),
        "ok": len(ok),
        "rate_limited_429": len(rate_limited),
        "errors": len(errors),
        "error_rate": round(len(errors) / len(results), 3) if results else 0,
        "throughput_rps": round(len(results) / wall, 2) if wall else 0,
        "latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99), "max": pct(lat, 100)},
    }
    print("=== SUMMARY ===")
    print(json.dumps(summary, indent=2))

    report = {"summary": summary, "metrics_before": metrics_before, "metrics_after": metrics_after}
    if metrics_after:
        print("\nServer tool/request metrics + cache stats captured (see report).")
    with open("loadtest_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("Full report -> loadtest_report.json")


if __name__ == "__main__":
    main()
