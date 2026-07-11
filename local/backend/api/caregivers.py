"""Thin caregiver API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    CaregiverDetailResponse,
    CaregiverListResponse,
    CaregiverMatchRequest,
    CaregiverMatchResponse,
)
from backend.services.caregiver_match_service import CaregiverMatchService

router = APIRouter(prefix="/api/caregivers", tags=["caregivers"])
_service = CaregiverMatchService()


def _detail(cg) -> CaregiverDetailResponse:
    return CaregiverDetailResponse(
        id=cg.id,
        name=cg.name,
        type=cg.type.value if hasattr(cg.type, "value") else str(cg.type),
        status=cg.status.value if hasattr(cg.status, "value") else str(cg.status),
        languages=list(cg.languages or []),
        current_patient_load=cg.current_patient_load,
        max_patient_capacity=cg.max_patient_capacity,
        phone=cg.phone,
        email=cg.email,
        certifications=[
            {
                "name": c.certification_name,
                "issued_date": str(c.issued_date) if c.issued_date else None,
                "expiry_date": str(c.expiry_date) if c.expiry_date else None,
            }
            for c in cg.certifications
        ],
        service_areas=[a.zip_code for a in cg.service_areas],
        availability=[
            {
                "day_of_week": a.day_of_week,
                "start_time": a.start_time.isoformat(),
                "end_time": a.end_time.isoformat(),
            }
            for a in cg.availability
        ],
    )


@router.post("/match", response_model=CaregiverMatchResponse)
async def match_caregivers(
    body: CaregiverMatchRequest, session: AsyncSession = Depends(get_db)
) -> CaregiverMatchResponse:
    items = await _service.match(session, body)
    return CaregiverMatchResponse(caregivers=items, count=len(items))


@router.get("", response_model=CaregiverListResponse)
async def list_caregivers(
    session: AsyncSession = Depends(get_db),
) -> CaregiverListResponse:
    rows = await _service.list_all(session)
    items = [_detail(r) for r in rows]
    return CaregiverListResponse(items=items, count=len(items))


@router.get("/{caregiver_id}", response_model=CaregiverDetailResponse)
async def get_caregiver(
    caregiver_id: UUID, session: AsyncSession = Depends(get_db)
) -> CaregiverDetailResponse:
    row = await _service.get(session, caregiver_id)
    return _detail(row)
