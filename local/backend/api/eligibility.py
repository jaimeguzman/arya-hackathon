"""Thin eligibility API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    EligibilityCheckRequest,
    EligibilityCheckResponse,
    InsuranceContractItem,
    ServiceAreaItem,
)
from backend.services.eligibility_service import EligibilityService

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])
_service = EligibilityService()


@router.post("/check", response_model=EligibilityCheckResponse)
async def check_eligibility(
    body: EligibilityCheckRequest, session: AsyncSession = Depends(get_db)
) -> EligibilityCheckResponse:
    return await _service.check(session, body)


@router.get("/service-areas", response_model=list[ServiceAreaItem])
async def list_service_areas(
    session: AsyncSession = Depends(get_db),
) -> list[ServiceAreaItem]:
    rows = await _service.list_service_areas(session)
    return [ServiceAreaItem.model_validate(r) for r in rows]


@router.get("/insurance", response_model=list[InsuranceContractItem])
async def list_insurance(
    session: AsyncSession = Depends(get_db),
) -> list[InsuranceContractItem]:
    rows = await _service.list_insurance(session)
    return [InsuranceContractItem.model_validate(r) for r in rows]
