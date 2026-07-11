"""Thin follow-up API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    FollowUpActionCreate,
    FollowUpActionResponse,
    FollowUpStatusUpdate,
)
from backend.services.followup_service import FollowUpService

router = APIRouter(prefix="/api/followup", tags=["followup"])
_service = FollowUpService()


@router.post("", response_model=FollowUpActionResponse)
async def create_followup(
    body: FollowUpActionCreate, session: AsyncSession = Depends(get_db)
) -> FollowUpActionResponse:
    row = await _service.create(session, body)
    return FollowUpActionResponse.model_validate(row)


@router.get("/by-intake/{intake_id}", response_model=list[FollowUpActionResponse])
async def list_followups(
    intake_id: UUID, session: AsyncSession = Depends(get_db)
) -> list[FollowUpActionResponse]:
    rows = await _service.list_by_intake(session, intake_id)
    return [FollowUpActionResponse.model_validate(r) for r in rows]


@router.put("/{action_id}/status", response_model=FollowUpActionResponse)
async def update_followup_status(
    action_id: UUID,
    body: FollowUpStatusUpdate,
    session: AsyncSession = Depends(get_db),
) -> FollowUpActionResponse:
    row = await _service.update_status(session, action_id, body)
    return FollowUpActionResponse.model_validate(row)
