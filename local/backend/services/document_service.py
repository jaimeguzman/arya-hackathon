# ponytail: disk upload only — ceiling: no virus scan / S3; upgrade: object storage
"""Document upload and status — processing is Phase 4."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from backend.models.tables import Document, DocumentPage, DocumentProcessingStatus

logger = logging.getLogger(__name__)
_UPLOADS = Path(__file__).resolve().parents[2] / "uploads"


class DocumentService:
    def __init__(self) -> None:
        _UPLOADS.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        session: AsyncSession,
        file: UploadFile,
        intake_record_id: UUID | None = None,
    ) -> Document:
        raw_name = file.filename or "upload.bin"
        safe = Path(raw_name).name
        doc_id = uuid.uuid4()
        dest = _UPLOADS / f"{doc_id}_{safe}"
        content = await file.read()
        dest.write_bytes(content)

        row = Document(
            id=doc_id,
            intake_record_id=intake_record_id,
            file_path=str(dest),
            file_name=safe,
            page_count=None,
            processing_status=DocumentProcessingStatus.uploaded,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @staticmethod
    def notify_processor(document_id: UUID) -> None:
        # kept for compatibility — prefer DocumentProcessor.process via BackgroundTasks
        from backend.workers.document_processor import DocumentProcessor

        DocumentProcessor().process_sync(document_id)

    async def get(self, session: AsyncSession, document_id: UUID) -> Document:
        row = await session.get(Document, document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return row

    async def get_with_pages(self, session: AsyncSession, document_id: UUID) -> Document:
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.pages))
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return row
