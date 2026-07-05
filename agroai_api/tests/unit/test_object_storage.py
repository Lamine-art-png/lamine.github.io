from io import BytesIO
import hashlib

import pytest

from app.services.object_storage import S3ObjectStore


class FakeStoreClient:
    def __init__(self):
        self.items = {}

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        self.items[(bucket, key)] = (handle.read(), dict((ExtraArgs or {}).get("Metadata") or {}))

    def head_object(self, Bucket, Key):
        body, metadata = self.items[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, Bucket, Key):
        body, metadata = self.items[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata, "Body": BytesIO(body)}

    def delete_object(self, Bucket, Key):
        self.items.pop((Bucket, Key), None)


def test_durable_store_verifies_and_namespaces(tmp_path):
    payload = b"timestamp,value\n2026-07-05,42\n"
    path = tmp_path / "sample.csv"
    path.write_bytes(payload)
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix="raw", client=client)
    stored = store.put_path(path, tenant_id="org-one", connection_id="conn-one", filename="sample.csv", content_type="text/csv", expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size=len(payload))
    assert stored.uri.startswith("s3://agroai-test/raw/tenants/org-one/connectors/conn-one/raw/")
    assert store.read_bytes(stored.uri, max_bytes=1024) == payload


def test_durable_store_enforces_read_limit(tmp_path):
    payload = b"x" * 100
    path = tmp_path / "payload.bin"
    path.write_bytes(payload)
    store = S3ObjectStore(bucket="agroai-test", client=FakeStoreClient())
    stored = store.put_path(path, tenant_id="org", connection_id="conn", filename="payload.bin", content_type=None, expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size=len(payload))
    with pytest.raises(RuntimeError):
        store.read_bytes(stored.uri, max_bytes=50)


def test_durable_store_rejects_other_bucket():
    store = S3ObjectStore(bucket="agroai-test", client=FakeStoreClient())
    with pytest.raises(ValueError):
        store.read_bytes("s3://other-bucket/path", max_bytes=100)
