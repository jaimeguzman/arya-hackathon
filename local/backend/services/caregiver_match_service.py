# ponytail: exact-zip only — ceiling: no adjacent zip graph; upgrade: zip adjacency table
"""Caregiver matching with locked scoring weights."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.schemas import CaregiverMatchItem, CaregiverMatchRequest
from backend.models.tables import (
    Caregiver,
    CaregiverAvailability,
    CaregiverCertification,
    CaregiverServiceArea,
    CaregiverStatus,
)

SCORE_SPECIALTY_CERT = 0.40
SCORE_BASE_CERT = 0.25
SCORE_EXACT_ZIP = 0.20
SCORE_LOAD_WEIGHT = 0.10
SCORE_AVAILABILITY = 0.05
SCORE_LANGUAGE = 0.05
NEAR_CAPACITY_RATIO = 0.85


class CaregiverMatchService:
    async def match(
        self,
        session: AsyncSession,
        req: CaregiverMatchRequest,
        *,
        specialty_bonus: Optional[str] = None,
        required_cert_groups: Optional[list[list[str]]] = None,
    ) -> list[CaregiverMatchItem]:
        """Match caregivers. required_cert_groups: each inner list is OR (either); outer AND."""
        stmt = (
            select(Caregiver)
            .where(Caregiver.status == CaregiverStatus.active)
            .options(
                selectinload(Caregiver.certifications),
                selectinload(Caregiver.service_areas),
                selectinload(Caregiver.availability),
            )
        )
        caregivers = list((await session.execute(stmt)).scalars().unique().all())
        today = date.today()
        results: list[CaregiverMatchItem] = []

        groups = required_cert_groups
        if groups is None:
            groups = [[c] for c in req.certification_types]

        for cg in caregivers:
            if cg.current_patient_load >= cg.max_patient_capacity:
                continue
            zips = [a.zip_code for a in cg.service_areas]
            if req.zip_code not in zips:
                continue

            active_certs = [
                c
                for c in cg.certifications
                if c.expiry_date is None or c.expiry_date >= today
            ]
            cert_names = {c.certification_name for c in active_certs}
            if not self._meets_cert_groups(cert_names, groups):
                continue

            score, reasons = self._score(
                cg,
                cert_names,
                req,
                specialty_bonus=specialty_bonus,
                active_certs=active_certs,
            )
            results.append(
                CaregiverMatchItem(
                    id=cg.id,
                    name=cg.name,
                    type=cg.type.value if hasattr(cg.type, "value") else str(cg.type),
                    certifications=sorted(cert_names),
                    zip_codes=zips,
                    current_load=cg.current_patient_load,
                    max_capacity=cg.max_patient_capacity,
                    match_score=round(score, 4),
                    reasons=reasons,
                )
            )

        results.sort(key=lambda x: x.match_score, reverse=True)
        return results

    @staticmethod
    def _meets_cert_groups(cert_names: set[str], groups: list[list[str]]) -> bool:
        for group in groups:
            lowered = {g.lower() for g in group}
            if not any(c.lower() in lowered for c in cert_names):
                # also allow case-insensitive partial: RN in "RN"
                if not any(
                    any(c.lower() == g.lower() for c in cert_names) for g in group
                ):
                    return False
        return True

    def _score(
        self,
        cg: Caregiver,
        cert_names: set[str],
        req: CaregiverMatchRequest,
        *,
        specialty_bonus: Optional[str],
        active_certs: list[CaregiverCertification],
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        cert_lower = {c.lower() for c in cert_names}

        if specialty_bonus and specialty_bonus.lower() in cert_lower:
            score += SCORE_SPECIALTY_CERT
            reasons.append(f"specialty:{specialty_bonus}")
        elif any(t.lower() in cert_lower for t in req.certification_types):
            score += SCORE_BASE_CERT
            reasons.append("base_cert")

        score += SCORE_EXACT_ZIP
        reasons.append("exact_zip")

        capacity = max(cg.max_patient_capacity, 1)
        score += (1 - cg.current_patient_load / capacity) * SCORE_LOAD_WEIGHT
        reasons.append("load")

        if req.day_of_week is not None and self._availability_match(cg, req):
            score += SCORE_AVAILABILITY
            reasons.append("availability")

        if req.language and any(
            req.language.lower() == lang.lower() for lang in (cg.languages or [])
        ):
            score += SCORE_LANGUAGE
            reasons.append("language")

        return score, reasons

    @staticmethod
    def _availability_match(cg: Caregiver, req: CaregiverMatchRequest) -> bool:
        assert req.day_of_week is not None
        slots = [a for a in cg.availability if a.day_of_week == req.day_of_week]
        if not slots:
            return False
        if not req.time:
            return True
        hh, mm = map(int, req.time.split(":")[:2])
        t = time(hh, mm)
        return any(a.start_time <= t <= a.end_time for a in slots)

    async def get(self, session: AsyncSession, caregiver_id: UUID) -> Caregiver:
        stmt = (
            select(Caregiver)
            .where(Caregiver.id == caregiver_id)
            .options(
                selectinload(Caregiver.certifications),
                selectinload(Caregiver.service_areas),
                selectinload(Caregiver.availability),
            )
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Caregiver not found")
        return row

    async def list_all(self, session: AsyncSession) -> list[Caregiver]:
        stmt = (
            select(Caregiver)
            .options(
                selectinload(Caregiver.certifications),
                selectinload(Caregiver.service_areas),
                selectinload(Caregiver.availability),
            )
            .order_by(Caregiver.name)
        )
        return list((await session.execute(stmt)).scalars().unique().all())

    @staticmethod
    def near_capacity(matches: list[CaregiverMatchItem]) -> bool:
        for m in matches:
            if m.max_capacity <= 0:
                continue
            if m.current_load / m.max_capacity >= NEAR_CAPACITY_RATIO:
                return True
        return False

    @staticmethod
    def min_cert_days_remaining(
        caregivers: list[Caregiver], required_names: set[str]
    ) -> Optional[int]:
        today = date.today()
        days: list[int] = []
        for cg in caregivers:
            for c in cg.certifications:
                if c.certification_name.lower() not in {n.lower() for n in required_names}:
                    continue
                if c.expiry_date is None:
                    continue
                days.append((c.expiry_date - today).days)
        return min(days) if days else None
