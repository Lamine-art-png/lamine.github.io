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


def _stored(tmp_path, *, tenant="org-one", connection="conn-one", prefix="raw"):
    payload = b"timestamp,value\n2026-07-05,42\n"
    path = tmp_path / "sample.csv"
    path.write_bytes(payload)
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix=prefix, client=client)
    stored = store.put_path(
        path,
        tenant_id=tenant,
        connection_id=connection,
        filename="sample.csv",
        content_type="text/csv",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_size=len(payload),
    )
    return payload, store, stored, client


def test_durable_store_verifies_and_namespaces(tmp_path):
    payload, store, stored, _client = _stored(tmp_path)
    assert stored.uri.startswith("s3://agroai-test/raw/tenants/org-one-")
    assert "/connectors/conn-one-" in stored.uri
    assert store.read_bytes(
        stored.uri,
        max_bytes=1024,
        tenant_id="org-one",
        connection_id="conn-one",
    ) == payload


def test_durable_store_scope_hash_prevents_sanitized_namespace_collisions(tmp_path):
    payload = b"collision-proof"
    path = tmp_path / "payload.bin"
    path.write_bytes(payload)
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", client=client)
    digest = hashlib.sha256(payload).hexdigest()

    first = store.put_path(
        path,
        tenant_id="org/a",
        connection_id="conn/a",
        filename="payload.bin",
        content_type=None,
        expected_sha256=digest,
        expected_size=len(payload),
    )
    second = store.put_path(
        path,
        tenant_id="org_a",
        connection_id="conn_a",
        filename="payload.bin",
        content_type=None,
        expected_sha256=digest,
        expected_size=len(payload),
    )

    assert first.key != second.key
    with pytest.raises(ValueError, match="tenant namespace"):
        store.read_bytes(
            first.uri,
            max_bytes=1024,
            tenant_id="org_a",
            connection_id="conn_a",
        )
    assert store.read_bytes(
        first.uri,
        max_bytes=1024,
        tenant_id="org/a",
        connection_id="conn/a",
    ) == payload


def test_durable_store_requires_exact_scope_metadata_for_scoped_reads(tmp_path):
    payload, store, stored, client = _stored(tmp_path)
    body, metadata = client.items[(store.bucket, stored.key)]
    metadata.pop("tenant-scope", None)
    client.items[(store.bucket, stored.key)] = (body, metadata)

    with pytest.raises(RuntimeError, match="tenant metadata mismatch"):
        store.read_bytes(
            stored.uri,
            max_bytes=1024,
            tenant_id="org-one",
            connection_id="conn-one",
        )


def test_durable_store_enforces_read_limit(tmp_path):
    payload = b"x" * 100
    path = tmp_path / "payload.bin"
    path.write_bytes(payload)
    store = S3ObjectStore(bucket="agroai-test", client=FakeStoreClient())
    stored = store.put_path(
        path,
        tenant_id="org",
        connection_id="conn",
        filename="payload.bin",
        content_type=None,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_size=len(payload),
    )
    with pytest.raises(RuntimeError):
        store.read_bytes(stored.uri, max_bytes=50)


def test_durable_store_rejects_other_bucket():
    store = S3ObjectStore(bucket="agroai-test", client=FakeStoreClient())
    with pytest.raises(ValueError):
        store.read_bytes("s3://other-bucket/path", max_bytes=100)


def test_durable_store_rejects_other_prefix_and_tenant_namespace(tmp_path):
    _payload, store, stored, _client = _stored(tmp_path)
    with pytest.raises(ValueError, match="tenant namespace"):
        store.read_bytes(
            stored.uri,
            max_bytes=1024,
            tenant_id="org-two",
            connection_id="conn-one",
        )
    with pytest.raises(ValueError, match="connector prefix"):
        store.read_bytes("s3://agroai-test/other/tenants/org-one/object", max_bytes=1024)


def test_durable_store_detects_missing_or_tampered_checksum_metadata(tmp_path):
    payload, store, stored, client = _stored(tmp_path)
    key = stored.key
    client.items[(store.bucket, key)] = (payload, {})
    with pytest.raises(RuntimeError, match="checksum metadata"):
        store.read_bytes(stored.uri, max_bytes=1024)

    client.items[(store.bucket, key)] = (payload + b"tampered", {"sha256": stored.sha256})
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        store.read_bytes(stored.uri, max_bytes=1024)


def test_durable_store_rejects_spool_mutation_before_upload(tmp_path):
    payload = b"original"
    path = tmp_path / "payload.bin"
    path.write_bytes(b"mutated!")
    store = S3ObjectStore(bucket="agroai-test", client=FakeStoreClient())
    with pytest.raises(RuntimeError, match="checksum changed"):
        store.put_path(
            path,
            tenant_id="org",
            connection_id="conn",
            filename="payload.bin",
            content_type=None,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_size=len(payload),
        )
