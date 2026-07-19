from agroai_platform import verify_webhook_signature
import hashlib
import hmac


def test_webhook_signature_and_replay_window():
    body = b'{"event":"field.updated"}'
    timestamp = "1000"
    secret = "whsec_test"
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(secret=secret, body=body, timestamp=timestamp, signature=f"v1={signature}", now=1001)
    assert not verify_webhook_signature(secret=secret, body=body, timestamp=timestamp, signature=f"v1={signature}", now=2000)
    assert not verify_webhook_signature(secret=secret, body=body + b"x", timestamp=timestamp, signature=f"v1={signature}", now=1001)
