from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from app.services.storage.r2_client import R2Client, R2StorageError, get_r2_client


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    def __init__(self) -> None:
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = {"Body": Body, **kwargs}
        return {}

    def get_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": _Body(self.objects[(Bucket, Key)]["Body"])}

    def generate_presigned_url(self, operation_name, *, Params, ExpiresIn):
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"

    def list_objects_v2(self, *, Bucket, Prefix):
        contents = []
        for (bucket, key), payload in self.objects.items():
            if bucket == Bucket and key.startswith(Prefix):
                contents.append(
                    {
                        "Key": key,
                        "Size": len(payload["Body"]),
                        "LastModified": datetime(2026, 5, 9, tzinfo=timezone.utc),
                    }
                )
        return {"Contents": contents}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}


def test_upload_and_get_round_trip():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    stored = asyncio.run(client.upload_file("tenant-a", "doc-1", "agreement.pdf", b"hello"))

    assert stored.key == "tenant-a/doc-1/original/agreement.pdf"
    assert asyncio.run(client.get_file("tenant-a", "doc-1", "agreement.pdf")) == b"hello"


def test_upload_artifact_uses_extracted_prefix():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    stored = asyncio.run(
        client.upload_artifact(
            "tenant-a",
            "doc-1",
            "page_3362.html",
            b"<html></html>",
            content_type="text/html; charset=utf-8",
        )
    )

    assert stored.key == "tenant-a/doc-1/extracted/page_3362.html"


def test_get_artifact_round_trip():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    asyncio.run(
        client.upload_artifact(
            "tenant-a",
            "doc-1",
            "page_3362.html",
            b"<html>guide</html>",
            content_type="text/html; charset=utf-8",
        )
    )

    assert asyncio.run(client.get_artifact("tenant-a", "doc-1", "page_3362.html")) == b"<html>guide</html>"
    assert asyncio.run(client.get_extracted_content("tenant-a", "doc-1", "page_3362.html")) == b"<html>guide</html>"


def test_versioned_artifact_round_trip():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    stored = asyncio.run(
        client.upload_artifact(
            "tenant-a",
            "doc-1",
            "page_3362.html",
            b"<html>v2</html>",
            version=2,
            content_type="text/html; charset=utf-8",
        )
    )

    assert stored.key == "tenant-a/doc-1/versions/2/extracted/page_3362.html"
    assert asyncio.run(client.get_artifact("tenant-a", "doc-1", "page_3362.html", version=2)) == b"<html>v2</html>"


def test_versioning_and_listing():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    asyncio.run(client.upload_file("tenant-a", "doc-1", "agreement.pdf", b"v1", version=1))
    asyncio.run(client.upload_file("tenant-a", "doc-1", "agreement.pdf", b"v2", version=2))

    assert asyncio.run(client.get_file("tenant-a", "doc-1", "agreement.pdf", version=1)) == b"v1"
    assert asyncio.run(client.get_file("tenant-a", "doc-1", "agreement.pdf", version=2)) == b"v2"
    assert asyncio.run(client.list_versions("tenant-a", "doc-1")) == [
        {
            "version": 1,
            "filename": "agreement.pdf",
            "key": "tenant-a/doc-1/versions/1/agreement.pdf",
            "size": 2,
            "last_modified": datetime(2026, 5, 9, tzinfo=timezone.utc),
        },
        {
            "version": 2,
            "filename": "agreement.pdf",
            "key": "tenant-a/doc-1/versions/2/agreement.pdf",
            "size": 2,
            "last_modified": datetime(2026, 5, 9, tzinfo=timezone.utc),
        },
    ]


def test_list_artifacts_for_current_and_versioned_content():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    asyncio.run(client.upload_artifact("tenant-a", "doc-1", "guide_manifest.json", b"{}", content_type="application/json"))
    asyncio.run(client.upload_artifact("tenant-a", "doc-1", "page_3362.html", b"<html></html>", version=2))

    assert asyncio.run(client.list_artifacts("tenant-a", "doc-1")) == [
        {
            "artifact_name": "guide_manifest.json",
            "key": "tenant-a/doc-1/extracted/guide_manifest.json",
            "size": 2,
            "last_modified": datetime(2026, 5, 9, tzinfo=timezone.utc),
            "version": None,
        }
    ]
    assert asyncio.run(client.list_artifacts("tenant-a", "doc-1", version=2)) == [
        {
            "artifact_name": "page_3362.html",
            "key": "tenant-a/doc-1/versions/2/extracted/page_3362.html",
            "size": 13,
            "last_modified": datetime(2026, 5, 9, tzinfo=timezone.utc),
            "version": 2,
        }
    ]


def test_tenant_isolation_is_key_scoped():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    asyncio.run(client.upload_file("tenant-a", "doc-1", "manual.pdf", b"a-data"))
    asyncio.run(client.upload_file("tenant-b", "doc-1", "manual.pdf", b"b-data"))

    assert asyncio.run(client.get_file("tenant-a", "doc-1", "manual.pdf")) == b"a-data"
    assert asyncio.run(client.get_file("tenant-b", "doc-1", "manual.pdf")) == b"b-data"


def test_presigned_url_generation():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    url = asyncio.run(client.get_presigned_url("tenant-a", "doc-1", "manual.pdf", expires_in=600))

    assert url == "https://example.test/bucket/tenant-a/doc-1/original/manual.pdf?exp=600"


def test_missing_file_raises_storage_error():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    with pytest.raises(R2StorageError):
        asyncio.run(client.get_file("tenant-a", "doc-1", "missing.pdf"))


def test_missing_artifact_raises_storage_error():
    client = R2Client(
        endpoint_url="https://example.test",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="bucket",
        client=FakeS3Client(),
    )

    with pytest.raises(R2StorageError):
        asyncio.run(client.get_artifact("tenant-a", "doc-1", "missing.html"))


def test_get_r2_client_requires_configuration(monkeypatch):
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("R2_BUCKET_NAME", raising=False)
    get_r2_client.cache_clear()
    from app.core.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(R2StorageError):
        get_r2_client()
    get_settings.cache_clear()


def test_bucket_appended_endpoint_is_normalized():
    client = R2Client(
        endpoint_url="https://accountid.r2.cloudflarestorage.com/oyvoda-documents-prod",
        access_key_id="key",
        secret_access_key="secret",
        bucket_name="oyvoda-documents-prod",
        client=FakeS3Client(),
    )

    assert client.endpoint_url == "https://accountid.r2.cloudflarestorage.com"
