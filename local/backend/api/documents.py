"""Thin document API routes."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db, get_redis
from backend.models.schemas import (
    DocumentExtractionResponse,
    DocumentPageResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from backend.models.tables import Document, DocumentProcessingStatus
from backend.services.document_service import DocumentService
from backend.workers.document_processor import DocumentProcessor

router = APIRouter(prefix="/api/documents", tags=["documents"])
_service = DocumentService()
_processor = DocumentProcessor()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    intake_record_id: UUID | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    row = await _service.save_upload(session, file, intake_record_id)
    background_tasks.add_task(_processor.process, row.id)
    return DocumentUploadResponse(
        id=row.id,
        file_name=row.file_name,
        page_count=row.page_count,
        processing_status=row.processing_status,
    )


@router.get("/by-intake/{intake_id}")
async def documents_by_intake(
    intake_id: UUID, session: AsyncSession = Depends(get_db)
) -> list[dict]:
    stmt = (
        select(Document)
        .where(Document.intake_record_id == intake_id)
        .order_by(Document.created_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [
        {
            "id": str(r.id),
            "file_name": r.file_name,
            "processing_status": r.processing_status.value
            if hasattr(r.processing_status, "value")
            else r.processing_status,
            "page_count": r.page_count,
        }
        for r in rows
    ]


@router.get("/{document_id}/file")
async def document_file(
    document_id: UUID, session: AsyncSession = Depends(get_db)
) -> FileResponse:
    row = await _service.get(session, document_id)
    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        path,
        filename=row.file_name,
        media_type="application/pdf",
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def document_status(
    document_id: UUID, session: AsyncSession = Depends(get_db)
) -> DocumentStatusResponse:
    row = await _service.get(session, document_id)
    current_layer = None
    try:
        redis = get_redis()
        raw = await redis.get(f"pipeline:{document_id}")
        if raw:
            import json

            current_layer = json.loads(raw).get("current_layer")
    except Exception:
        current_layer = None
    er = row.extraction_result or {}
    return DocumentStatusResponse(
        id=row.id,
        status=row.processing_status,
        current_layer=current_layer,
        extraction_result=er,
        confidence_scores=er.get("confidence_scores") or {},
        gaps=er.get("gaps") or [],
    )


@router.get("/{document_id}/extraction", response_model=DocumentExtractionResponse)
async def document_extraction(
    document_id: UUID, session: AsyncSession = Depends(get_db)
) -> DocumentExtractionResponse:
    row = await _service.get_with_pages(session, document_id)
    if row.processing_status != DocumentProcessingStatus.complete:
        raise HTTPException(status_code=409, detail="Extraction not complete")
    return DocumentExtractionResponse(
        id=row.id,
        processing_status=row.processing_status,
        extraction_result=row.extraction_result or {},
        pages=[DocumentPageResponse.model_validate(p) for p in row.pages],
    )
