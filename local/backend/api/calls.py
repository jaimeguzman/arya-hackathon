"""Active call Redis state + CallRecord history for dashboard."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import CallRecordResponse
from backend.services.call_service import CallService

router = APIRouter(prefix="/api/calls", tags=["calls"])
_service = CallService()


@router.get("/active")
async def list_active_calls() -> list[dict]:
    return await CallService.list_active_from_redis()


@router.get("/by-intake/{intake_id}", response_model=list[CallRecordResponse])
async def calls_by_intake(
    intake_id: UUID, session: AsyncSession = Depends(get_db)
) -> list[CallRecordResponse]:
    rows = await _service.list_by_intake(session, intake_id)
    return [CallRecordResponse.model_validate(r) for r in rows]
