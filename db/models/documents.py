"""Database models for durable source-document storage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.storage import R2StorageError, get_r2_client
from db.models.core import Base


class DocumentModel(Base):
    """Persisted source document with tenant isolation and version history."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("document_group_id", "version_number", name="uq_documents_group_version"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    property_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    document_group_id = Column(PGUUID(as_uuid=True), nullable=False, default=uuid4, index=True)
    scope_type = Column(String(20), nullable=False, default="property")  # property | portfolio
    version_number = Column(Integer, nullable=False, default=1)

    # Document info
    document_type = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # R2 object key
    storage_backend = Column(String(20), nullable=False, default="r2")
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    content_hash = Column(String(64), nullable=True)
    upload_method = Column(String(50), nullable=False, default="operator_upload")

    # Extraction status
    extraction_status = Column(String(20), default="pending")  # pending, processing, completed, failed
    extraction_error = Column(Text, nullable=True)
    extracted_fields = Column(JSONB, default=dict)

    # Metadata
    uploaded_by = Column(String(100), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)

    def _storage_version(self) -> Optional[int]:
        return None if self.version_number == 1 else self.version_number

    async def get_storage_url(self, *, expires_in: int = 3600) -> str:
        """Return a temporary URL for the stored document."""
        if self.storage_backend != "r2":
            raise R2StorageError(f"Unsupported storage backend: {self.storage_backend}")
        client = get_r2_client()
        return await client.get_presigned_url(
            str(self.tenant_id),
            str(self.document_group_id),
            self.filename,
            expires_in=expires_in,
            version=self._storage_version(),
        )

    async def get_content(self) -> bytes:
        """Fetch the raw source document bytes."""
        if self.storage_backend != "r2":
            raise R2StorageError(f"Unsupported storage backend: {self.storage_backend}")
        client = get_r2_client()
        return await client.get_file(
            str(self.tenant_id),
            str(self.document_group_id),
            self.filename,
            version=self._storage_version(),
        )

    async def create_version(
        self,
        session: AsyncSession,
        new_content: bytes,
        *,
        mime_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        content_hash: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> "DocumentModel":
        """Store a new version row under the same logical document group."""
        if self.storage_backend != "r2":
            raise R2StorageError(f"Unsupported storage backend: {self.storage_backend}")

        root_version = (
            select(DocumentModel.version_number)
            .where(DocumentModel.document_group_id == self.document_group_id)
            .order_by(DocumentModel.version_number.desc())
            .limit(1)
        )
        current_max = await session.scalar(root_version)
        next_version = int(current_max or self.version_number) + 1

        client = get_r2_client()
        stored = await client.upload_file(
            str(self.tenant_id),
            str(self.document_group_id),
            self.filename,
            new_content,
            version=next_version,
            content_type=mime_type or self.mime_type,
        )

        new_row = DocumentModel(
            tenant_id=self.tenant_id,
            property_id=self.property_id,
            document_group_id=self.document_group_id,
            scope_type=self.scope_type,
            version_number=next_version,
            document_type=self.document_type,
            filename=self.filename,
            file_path=stored.key,
            storage_backend=self.storage_backend,
            file_size=file_size if file_size is not None else len(new_content),
            mime_type=mime_type or self.mime_type,
            content_hash=content_hash,
            upload_method=self.upload_method,
            extraction_status="pending",
            extraction_error=None,
            extracted_fields={},
            uploaded_by=uploaded_by,
        )
        session.add(new_row)
        await session.flush()
        return new_row


class ExtractedFieldModel(Base):
    """Individual extracted field attached to a durable source document."""

    __tablename__ = "extracted_fields"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    property_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    field_name = Column(String(100), nullable=False)
    field_value = Column(JSONB, nullable=True)
    confidence = Column(String(20), default="medium")

    source_page = Column(Integer, nullable=True)
    source_text = Column(Text, nullable=True)

    verified = Column(String(20), default="unverified")
    verified_by = Column(String(100), nullable=True)
    extracted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
