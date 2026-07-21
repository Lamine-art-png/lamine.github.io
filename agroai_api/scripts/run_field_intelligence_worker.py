"""Dedicated Field Intelligence worker process.

Production topology: run one or more instances of this process alongside the
API. It drains the durable processing, deletion and orphan-reconciliation
queues on an interval, records SHA-bearing heartbeats, honors the emergency
kill switch, and shuts down gracefully on SIGTERM/SIGINT (finishing the tick
in flight, never abandoning a leased job mid-transaction).

Usage:
    python -m scripts.run_field_intelligence_worker            # loop
    python -m scripts.run_field_intelligence_worker --once     # single tick
    python -m scripts.run_field_intelligence_worker --liveness-file /tmp/fi-worker-alive

Liveness: with ``--liveness-file`` the file's mtime is refreshed on every
successful tick — point a container liveness probe at its age. Readiness is
the same signal plus a fresh row in ``field_worker_heartbeats``.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.field_intelligence_worker import (  # noqa: E402
    _WORKER_INSTANCE_ID,
    drain_once,
)

logging.basicConfig(
    level=getattr(logging, str(getattr(settings, "LOG_LEVEL", "INFO")).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("agroai.field_intelligence.worker")

_shutdown = {"requested": False}


def _request_shutdown(signum, _frame) -> None:  # pragma: no cover - signal path
    logger.info("field-intelligence worker received signal %s; finishing current tick", signum)
    _shutdown["requested"] = True


def _touch(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).touch()
    except OSError:  # pragma: no cover - liveness is best-effort
        logger.warning("could not refresh liveness file %s", path)


def main() -> int:
    parser = argparse.ArgumentParser(description="AGRO-AI Field Intelligence worker")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    parser.add_argument("--interval", type=float, default=None,
                        help="seconds between ticks (default: FIELD_WORKER_INTERVAL_SECONDS)")
    parser.add_argument("--liveness-file", default=os.getenv("FIELD_WORKER_LIVENESS_FILE") or None)
    parser.add_argument("--reconcile-every", type=int, default=None,
                        help="run the pending-object reconciler every N ticks "
                             "(default derives from FIELD_RECONCILER_INTERVAL_SECONDS)")
    args = parser.parse_args()

    interval = float(args.interval if args.interval is not None
                     else getattr(settings, "FIELD_WORKER_INTERVAL_SECONDS", 15))
    reconcile_interval = int(getattr(settings, "FIELD_RECONCILER_INTERVAL_SECONDS", 900))
    reconcile_every = max(1, int(args.reconcile_every if args.reconcile_every is not None
                                 else max(1, reconcile_interval // max(interval, 1))))

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    logger.info(
        "field-intelligence worker starting (id=%s interval=%.1fs reconcile_every=%d ticks)",
        _WORKER_INSTANCE_ID, interval, reconcile_every,
    )
    tick_count = 0
    exit_code = 0
    while True:
        tick_count += 1
        result = drain_once()
        if "error" in result:
            exit_code = 0  # transient; the loop continues, liveness not refreshed
        else:
            _touch(args.liveness_file)
        if tick_count % reconcile_every == 0:
            from app.services.field_intelligence_worker import reconcile_once

            reconcile_once()
        if args.once or _shutdown["requested"]:
            break
        deadline = time.monotonic() + interval
        while time.monotonic() < deadline and not _shutdown["requested"]:
            time.sleep(min(1.0, deadline - time.monotonic()))
        if _shutdown["requested"]:
            break
    logger.info("field-intelligence worker stopped cleanly (ticks=%d)", tick_count)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
