import os
from pathlib import Path
import subprocess
import sys


def run_worker(**config):
    root = Path(__file__).parents[2]
    env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    env.update(DATABASE_URL="sqlite://", PYTHONPATH=str(root), AWS_EC2_METADATA_DISABLED="true")
    env.update(config)
    return subprocess.run([sys.executable, str(root / "scripts/process_aws_marketplace_events.py")], cwd=root, env=env, capture_output=True, text=True, timeout=15)


def test_worker_defaults_to_disabled():
    result = run_worker()
    assert result.returncode == 1
    assert "event processing is disabled" in result.stderr


def test_invalid_queue_fails_before_credential_lookup():
    result = run_worker(AWS_MARKETPLACE_EVENTS_ENABLED="true", AWS_MARKETPLACE_SELLER_ACCOUNT_ID="111111111111", AWS_MARKETPLACE_PRODUCT_CODE="synthetic", AWS_MARKETPLACE_PRODUCT_ID="prod-synthetic", AWS_MARKETPLACE_QUEUE_URL="https://untrusted.example/queue")
    assert result.returncode == 1
    assert "queue configuration is invalid" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_credentials_does_not_log_sdk_exception():
    result = run_worker(AWS_MARKETPLACE_EVENTS_ENABLED="true", AWS_MARKETPLACE_SELLER_ACCOUNT_ID="111111111111", AWS_MARKETPLACE_PRODUCT_CODE="synthetic", AWS_MARKETPLACE_PRODUCT_ID="prod-synthetic", AWS_MARKETPLACE_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/111111111111/synthetic")
    assert result.returncode == 1
    assert "event processing unavailable" in result.stderr
    assert "NoCredentialsError" not in result.stderr
    assert "Traceback" not in result.stderr
