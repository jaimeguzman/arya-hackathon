"""Thin document API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    DocumentExtractionResponse,
    DocumentPageResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from backend.models.tables import DocumentProcessingStatus
from backend.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])
_service = DocumentService()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    intake_record_id: UUID | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    row = await _service.save_upload(session, file, intake_record_id)
    background_tasks.add_task(DocumentService.notify_processor, row.id)
    return DocumentUploadResponse(
        id=row.id,
        file_name=row.file_name,
        page_count=row.page_count,
        processing_status=row.processing_status,
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def document_status(
    document_id: UUID, session: AsyncSession = Depends(get_db)
) -> DocumentStatusResponse:
    row = await _service.get(session, document_id)
    return DocumentStatusResponse(
        id=row.id,
        status=row.processing_status,
        current_layer=None,
        extraction_result=row.extraction_result or {},
        confidence_scores={},
        gaps=[],
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
