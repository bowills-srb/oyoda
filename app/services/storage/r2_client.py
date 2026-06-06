"""Cloudflare R2 storage wrapper for source documents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings


class R2StorageError(RuntimeError):
    """Raised when document storage operations fail."""


@dataclass(frozen=True)
class StoredObject:
    """Metadata returned after storing a file."""

    bucket: str
    key: str
    version: int


class R2Client:
    """Small async wrapper around R2's S3-compatible API."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        client: Optional[BaseClient] = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.endpoint_url = self._normalize_endpoint_url(endpoint_url, bucket_name)
        self._client = client or boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

    @staticmethod
    def _normalize_endpoint_url(endpoint_url: str, bucket_name: str) -> str:
        parsed = urlparse(endpoint_url)
        path = (parsed.path or "").rstrip("/")
        bucket_path = f"/{bucket_name}".rstrip("/")
        if path == bucket_path:
            parsed = parsed._replace(path="")
        return urlunparse(parsed).rstrip("/")

    @staticmethod
    def build_key(
        tenant_id: str,
        document_id: str,
        filename: str,
        *,
        version: Optional[int] = None,
        artifact_name: Optional[str] = None,
    ) -> str:
        safe_filename = filename.strip().replace("\\", "/").split("/")[-1] or "document"
        if artifact_name:
            if version is not None:
                return f"{tenant_id}/{document_id}/versions/{version}/extracted/{artifact_name}"
            return f"{tenant_id}/{document_id}/extracted/{artifact_name}"
        if version is None:
            return f"{tenant_id}/{document_id}/original/{safe_filename}"
        return f"{tenant_id}/{document_id}/versions/{version}/{safe_filename}"

    async def upload_file(
        self,
        tenant_id: str,
        document_id: str,
        filename: str,
        content: bytes,
        *,
        version: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> StoredObject:
        key = self.build_key(tenant_id, document_id, filename, version=version)
        extra_args: Dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        await self._run(
            self._client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=content,
            **extra_args,
        )
        return StoredObject(bucket=self.bucket_name, key=key, version=version or 1)

    async def upload_artifact(
        self,
        tenant_id: str,
        document_id: str,
        artifact_name: str,
        content: bytes,
        *,
        version: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> StoredObject:
        key = self.build_key(
            tenant_id,
            document_id,
            artifact_name,
            version=version,
            artifact_name=artifact_name,
        )
        extra_args: Dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        await self._run(
            self._client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=content,
            **extra_args,
        )
        return StoredObject(bucket=self.bucket_name, key=key, version=version or 1)

    async def get_file(
        self,
        tenant_id: str,
        document_id: str,
        filename: str,
        *,
        version: Optional[int] = None,
    ) -> bytes:
        key = self.build_key(tenant_id, document_id, filename, version=version)
        response = await self._run(
            self._client.get_object,
            Bucket=self.bucket_name,
            Key=key,
        )
        body = response["Body"]
        return await self._run(body.read)

    async def get_artifact(
        self,
        tenant_id: str,
        document_id: str,
        artifact_name: str,
        *,
        version: Optional[int] = None,
    ) -> bytes:
        key = self.build_key(
            tenant_id,
            document_id,
            artifact_name,
            version=version,
            artifact_name=artifact_name,
        )
        response = await self._run(
            self._client.get_object,
            Bucket=self.bucket_name,
            Key=key,
        )
        body = response["Body"]
        return await self._run(body.read)

    async def get_extracted_content(
        self,
        tenant_id: str,
        document_id: str,
        artifact_name: str,
        *,
        version: Optional[int] = None,
    ) -> bytes:
        return await self.get_artifact(
            tenant_id,
            document_id,
            artifact_name,
            version=version,
        )

    async def get_presigned_url(
        self,
        tenant_id: str,
        document_id: str,
        filename: str,
        *,
        expires_in: int = 3600,
        version: Optional[int] = None,
    ) -> str:
        key = self.build_key(tenant_id, document_id, filename, version=version)
        return await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )

    async def list_versions(self, tenant_id: str, document_id: str) -> List[Dict[str, Any]]:
        prefix = f"{tenant_id}/{document_id}/versions/"
        response = await self._run(
            self._client.list_objects_v2,
            Bucket=self.bucket_name,
            Prefix=prefix,
        )
        contents = sorted(response.get("Contents", []), key=lambda item: item["Key"])
        versions: List[Dict[str, Any]] = []
        for item in contents:
            suffix = item["Key"][len(prefix):]
            parts = suffix.split("/", 1)
            if len(parts) != 2:
                continue
            version_str, filename = parts
            if not version_str.isdigit():
                continue
            versions.append(
                {
                    "version": int(version_str),
                    "filename": filename,
                    "key": item["Key"],
                    "size": item.get("Size"),
                    "last_modified": item.get("LastModified"),
                }
            )
        return versions

    async def list_artifacts(
        self,
        tenant_id: str,
        document_id: str,
        *,
        version: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if version is None:
            prefix = f"{tenant_id}/{document_id}/extracted/"
        else:
            prefix = f"{tenant_id}/{document_id}/versions/{version}/extracted/"

        response = await self._run(
            self._client.list_objects_v2,
            Bucket=self.bucket_name,
            Prefix=prefix,
        )
        contents = sorted(response.get("Contents", []), key=lambda item: item["Key"])
        artifacts: List[Dict[str, Any]] = []
        for item in contents:
            artifact_name = item["Key"][len(prefix):]
            if not artifact_name:
                continue
            artifacts.append(
                {
                    "artifact_name": artifact_name,
                    "key": item["Key"],
                    "size": item.get("Size"),
                    "last_modified": item.get("LastModified"),
                    "version": version,
                }
            )
        return artifacts

    async def delete_file(
        self,
        tenant_id: str,
        document_id: str,
        filename: str,
        *,
        version: Optional[int] = None,
    ) -> None:
        key = self.build_key(tenant_id, document_id, filename, version=version)
        await self._run(
            self._client.delete_object,
            Bucket=self.bucket_name,
            Key=key,
        )

    async def _run(self, func, *args, **kwargs):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            raise R2StorageError(f"R2 operation failed ({code})") from exc
        except BotoCoreError as exc:
            raise R2StorageError("R2 client error") from exc


@lru_cache()
def get_r2_client() -> R2Client:
    """Build the configured R2 client."""
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL", settings.r2_endpoint_url),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_BUCKET_NAME", settings.r2_bucket_name),
        )
        if not value
    ]
    if missing:
        raise R2StorageError(f"Missing R2 configuration: {', '.join(missing)}")
    return R2Client(
        endpoint_url=str(settings.r2_endpoint_url),
        access_key_id=str(settings.r2_access_key_id),
        secret_access_key=str(settings.r2_secret_access_key),
        bucket_name=str(settings.r2_bucket_name),
    )
