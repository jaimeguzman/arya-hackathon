"""Thin intake API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    IntakeRecordCreate,
    IntakeRecordList,
    IntakeRecordResponse,
    IntakeRecordUpdate,
    StatusUpdate,
)
from backend.models.tables import IntakeStatus
from backend.services.intake_service import IntakeService

router = APIRouter(prefix="/api/intake", tags=["intake"])
_service = IntakeService()


@router.post("", response_model=IntakeRecordResponse)
async def create_intake(
    body: IntakeRecordCreate, session: AsyncSession = Depends(get_db)
) -> IntakeRecordResponse:
    row = await _service.create(session, body)
    return IntakeRecordResponse.model_validate(row)


@router.get("", response_model=IntakeRecordList)
async def list_intake(
    status: Optional[IntakeStatus] = None,
    since: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> IntakeRecordList:
    rows, count = await _service.list(
        session, status=status, since=since, limit=limit, offset=offset
    )
    return IntakeRecordList(
        items=[IntakeRecordResponse.model_validate(r) for r in rows],
        count=count,
    )


@router.get("/{intake_id}", response_model=IntakeRecordResponse)
async def get_intake(
    intake_id: UUID, session: AsyncSession = Depends(get_db)
) -> IntakeRecordResponse:
    row = await _service.get(session, intake_id)
    return IntakeRecordResponse.model_validate(row)


@router.put("/{intake_id}", response_model=IntakeRecordResponse)
async def update_intake(
    intake_id: UUID,
    body: IntakeRecordUpdate,
    session: AsyncSession = Depends(get_db),
) -> IntakeRecordResponse:
    row = await _service.update_data(session, intake_id, body)
    return IntakeRecordResponse.model_validate(row)


@router.put("/{intake_id}/status", response_model=IntakeRecordResponse)
async def update_intake_status(
    intake_id: UUID,
    body: StatusUpdate,
    session: AsyncSession = Depends(get_db),
) -> IntakeRecordResponse:
    row = await _service.update_status(session, intake_id, body)
    return IntakeRecordResponse.model_validate(row)
