"""Controlled enrollment of existing AGRO-AI accounts into lifecycle email.

Existing accounts are never enrolled automatically (only new verifications
are). This script enrolls a bounded, filtered set and starts them at a chosen
step: every earlier step is recorded as skipped ("backfill_start"), so nobody
receives the historical sequence. Dry run by default.

    python scripts/lifecycle_backfill.py --created-after 2026-09-01 --start-step reactivation --limit 50
    python scripts/lifecycle_backfill.py ... --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-after", required=True, help="YYYY-MM-DD; only accounts created on/after this date")
    parser.add_argument("--start-step", default="reactivation", help="first step the enrolled accounts may receive")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--apply", action="store_true", help="write enrollments (default: dry run)")
    args = parser.parse_args()

    from app.db.base import SessionLocal
    from app.models.lifecycle_email import LifecycleEmailEnrollment, LifecycleEmailSend
    from app.models.saas import OrganizationMembership, User
    from app.services.lifecycle_emails import SEQUENCE_VERSION, STEP_BY_KEY, STEPS

    if args.start_step not in STEP_BY_KEY:
        parser.error(f"--start-step must be one of {[step.key for step in STEPS]}")
    since = datetime.strptime(args.created_after, "%Y-%m-%d")
    start = STEP_BY_KEY[args.start_step]
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        enrolled_ids = {row[0] for row in db.query(LifecycleEmailEnrollment.user_id).all()}
        candidates = (
            db.query(User)
            .filter(User.created_at >= since, User.email_verification_status == "verified", User.account_status == "active")
            .order_by(User.created_at.asc())
            .all()
        )
        selected = [user for user in candidates if user.id not in enrolled_ids][: args.limit]
        print(f"candidates={len(candidates)} already_enrolled={len(candidates) - len([u for u in candidates if u.id not in enrolled_ids])} selected={len(selected)} start_step={start.key} apply={args.apply}")
        for user in selected:
            membership = db.query(OrganizationMembership).filter_by(user_id=user.id).order_by(OrganizationMembership.created_at.asc()).first()
            print(f"  {'enroll' if args.apply else 'would enroll'} user_id={user.id} created_at={user.created_at:%Y-%m-%d}")
            if not args.apply:
                continue
            # Anchor the sequence so the start step is due now; earlier steps are skipped.
            enrolled_at = now - start.delay
            db.add(LifecycleEmailEnrollment(
                user_id=user.id, organization_id=membership.organization_id if membership else None,
                sequence_version=SEQUENCE_VERSION, source="backfill", status="active", enrolled_at=enrolled_at,
                next_action_at=now,
            ))
            for step in STEPS:
                if step.key == start.key:
                    break
                db.add(LifecycleEmailSend(
                    user_id=user.id, organization_id=membership.organization_id if membership else None, step=step.key,
                    status="skipped", reason="backfill_start", scheduled_for=enrolled_at + step.delay,
                ))
        if args.apply:
            db.commit()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
