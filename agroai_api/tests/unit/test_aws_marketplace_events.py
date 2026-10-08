from datetime import datetime
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.aws_marketplace import AwsMarketplaceLicenseEvent, AwsMarketplaceRegistration
from app.platform_api.aws_marketplace_events import (
    InvalidLicenseEvent, LICENSE_DEPROVISIONED, LICENSE_UPDATED,
    consume_license_messages, process_license_event,
)

SELLER = "111111111111"
BUYER = "222222222222"
PRODUCT = "synthetic-product"
LICENSE = "arn:aws:license-manager:us-east-1:111111111111:license:l-synthetic"
CONFIG = dict(seller_account_id=SELLER, product_code=PRODUCT, region="us-east-1")


def event(kind=LICENSE_UPDATED, time="2026-01-01T00:00:00Z", **changes):
    payload = {
        "id": str(uuid4()), "source": "aws.agreement-marketplace",
        "account": SELLER, "region": "us-east-1", "time": time,
        "detail-type": kind,
        "detail": {"catalog": "AWSMarketplace", "product": {"code": PRODUCT},
                   "acceptor": {"accountId": BUYER}, "license": {"arn": LICENSE}},
    }
    payload.update(changes)
    return json.dumps(payload)


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://")
    AwsMarketplaceRegistration.__table__.create(engine)
    AwsMarketplaceLicenseEvent.__table__.create(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def test_events_before_registration_are_persisted_and_replay_is_idempotent(sessions):
    body = event()
    with sessions() as db:
        assert process_license_event(db, body, **CONFIG) == "processed"
        assert process_license_event(db, body, **CONFIG) == "duplicate"
        assert db.query(AwsMarketplaceLicenseEvent).count() == 1
        row = db.query(AwsMarketplaceRegistration).one()
        assert row.status == "license_confirmed"
        assert row.license_updated_at == datetime(2026, 1, 1)
        assert row.organization_id is None  # Confirmation does not grant access.


def test_same_event_id_with_different_content_is_rejected(sessions):
    body = event()
    with sessions() as db:
        process_license_event(db, body, **CONFIG)
        payload = json.loads(body)
        payload["detail-type"] = LICENSE_DEPROVISIONED
        with pytest.raises(InvalidLicenseEvent):
            process_license_event(db, json.dumps(payload), **CONFIG)
        assert db.query(AwsMarketplaceRegistration).one().status == "license_confirmed"


def test_old_and_equal_timestamp_updates_cannot_undo_revocation(sessions):
    with sessions() as db:
        process_license_event(db, event(LICENSE_DEPROVISIONED, time="2026-01-02T00:00:00Z"), **CONFIG)
        process_license_event(db, event(time="2026-01-01T00:00:00Z"), **CONFIG)
        process_license_event(db, event(time="2026-01-02T00:00:00Z"), **CONFIG)
        assert db.query(AwsMarketplaceRegistration).one().status == "revoked"


def test_revocation_wins_equal_timestamp_after_update(sessions):
    with sessions() as db:
        process_license_event(db, event(), **CONFIG)
        process_license_event(db, event(LICENSE_DEPROVISIONED), **CONFIG)
        assert db.query(AwsMarketplaceRegistration).one().status == "revoked"


@pytest.mark.parametrize("changes", [
    {"source": "untrusted"}, {"account": BUYER}, {"region": "eu-west-1"},
    {"detail-type": "Purchase Agreement Created"}, {"id": "invalid"},
    {"time": "2099-01-01T00:00:00Z"}, {"time": "2026-01-01T00:00:00"},
    {"detail": {}},
])
def test_invalid_events_are_not_persisted(sessions, changes):
    with sessions() as db:
        with pytest.raises(InvalidLicenseEvent):
            process_license_event(db, event(**changes), **CONFIG)
        assert db.query(AwsMarketplaceRegistration).count() == 0
        assert db.query(AwsMarketplaceLicenseEvent).count() == 0


def test_wrong_product_and_conflicting_account_are_rejected(sessions):
    with sessions() as db:
        process_license_event(db, event(), **CONFIG)
        for key, value in [("product", {"code": "wrong"}), ("acceptor", {"accountId": SELLER})]:
            payload = json.loads(event())
            payload["detail"][key] = value
            with pytest.raises(InvalidLicenseEvent):
                process_license_event(db, json.dumps(payload), **CONFIG)
        assert db.query(AwsMarketplaceLicenseEvent).count() == 1


def test_multiple_licenses_on_same_account_remain_separate(sessions):
    with sessions() as db:
        process_license_event(db, event(), **CONFIG)
        payload = json.loads(event())
        payload["detail"]["license"]["arn"] = LICENSE + "-two"
        process_license_event(db, json.dumps(payload), **CONFIG)
        assert db.query(AwsMarketplaceRegistration).count() == 2


def test_queue_ack_only_after_commit_failed_events_are_retried(sessions):
    class Queue:
        deleted = []
        def receive_message(self, **kwargs):
            return {"Messages": [
                {"Body": event(), "ReceiptHandle": "good"},
                {"Body": event(account=BUYER), "ReceiptHandle": "bad"},
            ]}
        def delete_message(self, **kwargs):
            with sessions() as db:
                assert db.query(AwsMarketplaceLicenseEvent).count() == 1
            self.deleted.append(kwargs["ReceiptHandle"])
    queue = Queue()
    assert consume_license_messages(queue, sessions, queue_url="synthetic", **CONFIG) == {
        "processed": 1,
        "failed": 1,
        "failure_stages": {"parse": 1},
    }
    assert queue.deleted == ["good"]


def test_delete_failure_retries_without_applying_event_again(sessions):
    body = event()
    class Queue:
        attempts = 0
        def receive_message(self, **kwargs):
            return {"Messages": [{"Body": body, "ReceiptHandle": "synthetic"}]}
        def delete_message(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("simulated SQS outage")
    queue = Queue()
    assert consume_license_messages(queue, sessions, queue_url="synthetic", **CONFIG) == {
        "processed": 0,
        "failed": 1,
        "failure_stages": {"ack": 1},
    }
    assert consume_license_messages(queue, sessions, queue_url="synthetic", **CONFIG) == {
        "processed": 1,
        "failed": 0,
        "failure_stages": {},
    }
    with sessions() as db:
        assert db.query(AwsMarketplaceLicenseEvent).count() == 1


def test_commit_failure_never_acknowledges_or_persists_event(sessions):
    class Queue:
        def receive_message(self, **kwargs):
            return {"Messages": [{"Body": event(), "ReceiptHandle": "synthetic"}]}
        def delete_message(self, **kwargs):
            pytest.fail("Uncommitted event must remain in SQS")
    def failing_session():
        db = sessions()
        def fail_commit():
            raise RuntimeError("simulated database outage")
        db.commit = fail_commit
        return db
    assert consume_license_messages(Queue(), failing_session, queue_url="synthetic", **CONFIG) == {
        "processed": 0,
        "failed": 1,
        "failure_stages": {"persist": 1},
    }
    with sessions() as db:
        assert db.query(AwsMarketplaceLicenseEvent).count() == 0
        assert db.query(AwsMarketplaceRegistration).count() == 0
