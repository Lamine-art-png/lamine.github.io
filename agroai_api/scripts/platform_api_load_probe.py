#!/usr/bin/env python3
"""Bounded, read-only Platform API latency and availability probe.

Credentials are read only from AGROAI_PLATFORM_LOAD_TEST_KEY. Response bodies
are never stored. Production safeguards prevent accidental high-volume runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from urllib.parse import urlparse

import httpx

ALLOWED_PATHS = {"/v1/health", "/v1/readiness", "/v1/platform/health", "/v1/platform/me"}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


async def run(args: argparse.Namespace) -> dict[str, object]:
    parsed = urlparse(args.base_url)
    if parsed.scheme != "https":
        raise SystemExit("base URL must use HTTPS")
    if args.path not in ALLOWED_PATHS:
        raise SystemExit(f"path is not in the read-only allowlist: {args.path}")
    is_production = parsed.hostname in {"api.agroai-pilot.com", "platform.agroai-pilot.com"}
    if is_production and (args.requests > 200 or args.concurrency > 10) and not args.confirm_production:
        raise SystemExit("production runs above 200 requests or concurrency 10 require --confirm-production")
    if args.requests < 1 or args.requests > 10000:
        raise SystemExit("requests must be between 1 and 10000")
    if args.concurrency < 1 or args.concurrency > 200:
        raise SystemExit("concurrency must be between 1 and 200")

    headers = {"User-Agent": "agroai-enterprise-load-probe/1.0"}
    key = os.getenv("AGROAI_PLATFORM_LOAD_TEST_KEY", "").strip()
    if args.path == "/v1/platform/me":
        if not key:
            raise SystemExit("AGROAI_PLATFORM_LOAD_TEST_KEY is required for /v1/platform/me")
        headers["Authorization"] = f"Bearer {key}"

    queue: asyncio.Queue[int] = asyncio.Queue()
    for item in range(args.requests):
        queue.put_nowait(item)
    latencies: list[float] = []
    status_counts: dict[str, int] = {}

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=httpx.Timeout(args.timeout),
        follow_redirects=False,
        headers=headers,
        limits=httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency),
    ) as client:
        async def worker() -> None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                started = time.perf_counter()
                try:
                    response = await client.get(args.path)
                    code = str(response.status_code)
                except httpx.HTTPError:
                    code = "transport_error"
                elapsed = (time.perf_counter() - started) * 1000
                latencies.append(elapsed)
                status_counts[code] = status_counts.get(code, 0) + 1
                queue.task_done()

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        duration = max(time.perf_counter() - started, 0.000001)

    success = sum(count for code, count in status_counts.items() if code.startswith("2"))
    errors = args.requests - success
    latency_summary = {
        "min": round(min(latencies), 3),
        "mean": round(statistics.fmean(latencies), 3),
        "p50": round(percentile(latencies, 0.50), 3),
        "p95": round(percentile(latencies, 0.95), 3),
        "p99": round(percentile(latencies, 0.99), 3),
        "max": round(max(latencies), 3),
    }
    error_rate = errors / args.requests
    result: dict[str, object] = {
        "base_url_host": parsed.hostname,
        "path": args.path,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(args.requests / duration, 3),
        "success_rate": round(success / args.requests, 6),
        "error_rate": round(error_rate, 6),
        "latency_ms": latency_summary,
        "status_counts": status_counts,
        "thresholds": {"max_error_rate": args.max_error_rate, "max_p95_ms": args.max_p95_ms},
    }
    result["passed"] = error_rate <= args.max_error_rate and latency_summary["p95"] <= args.max_p95_ms
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://api-preview.agroai-pilot.com")
    parser.add_argument("--path", default="/v1/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
