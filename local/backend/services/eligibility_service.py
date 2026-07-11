# ponytail: sequential steps — ceiling: production parallel queries; upgrade: asyncio.gather
"""Eligibility engine: service area → insurance → Neo4j clinical → caregivers → guardrails."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_neo4j
from backend.models.schemas import (
    CaregiverMatchItem,
    CaregiverMatchRequest,
    CoverageDetail,
    EligibilityCheckRequest,
    EligibilityCheckResponse,
    EligibilityReason,
)
from backend.models.tables import Document, InsuranceContract, IntakeRecord, ServiceArea
from backend.services.caregiver_match_service import CaregiverMatchService
from backend.services.guardrail_service import GuardrailService

CONF_DECLINE = 0.0
CONF_NEEDS_INFO = 0.5
CONF_ACCEPT_EXACT = 0.9
CONF_ACCEPT_PAYER_ONLY = 0.75

_LOCAL_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _plan_name_to_code() -> dict[str, str]:
    path = _LOCAL_ROOT / "data" / "insurance_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {p["name"].strip().lower(): p["code"] for p in data.get("plans", [])}


class EligibilityService:
    def __init__(
        self,
        guardrails: GuardrailService | None = None,
        matcher: CaregiverMatchService | None = None,
    ) -> None:
        self._guardrails = guardrails or GuardrailService()
        self._matcher = matcher or CaregiverMatchService()

    async def check(
        self, session: AsyncSession, req: EligibilityCheckRequest
    ) -> EligibilityCheckResponse:
        reasons: list[EligibilityReason] = []

        # Step 1: service area
        area = await session.get(ServiceArea, req.zip_code.strip())
        if area is None or not area.active:
            return await self._finalize(
                session,
                req,
                decision="DECLINE",
                reasons=[
                    EligibilityReason(
                        code="out_of_area",
                        message=f"We do not serve zip code {req.zip_code}.",
                    )
                ],
                matched=[],
                coverage=[],
                exact_plan=False,
            )

        # Step 2: insurance
        contract, exact_plan = await self._match_insurance(session, req)
        if contract is None:
            return await self._finalize(
                session,
                req,
                decision="DECLINE",
                reasons=[
                    EligibilityReason(
                        code="insurance_not_accepted",
                        message=(
                            f"We do not accept {req.insurance_payer}"
                            + (f" {req.insurance_plan}" if req.insurance_plan else "")
                            + "."
                        ),
                    )
                ],
                matched=[],
                coverage=[],
                exact_plan=False,
            )
        reasons.append(
            EligibilityReason(
                code="insurance_ok",
                message=f"Accepted plan: {contract.plan_name}",
            )
        )
        coverage = await self._neo4j_coverage(contract.plan_name)

        # Step 3: clinical
        if not req.icd_code:
            return await self._finalize(
                session,
                req,
                decision="NEEDS_MORE_INFO",
                reasons=reasons
                + [
                    EligibilityReason(
                        code="diagnosis_unknown",
                        message="Unable to determine service requirements for this diagnosis. Coordinator review needed.",
                    )
                ],
                matched=[],
                coverage=coverage,
                exact_plan=exact_plan,
            )

        services, specialty, cert_groups = await self._neo4j_clinical(req.icd_code.strip())
        if not services:
            return await self._finalize(
                session,
                req,
                decision="NEEDS_MORE_INFO",
                reasons=reasons
                + [
                    EligibilityReason(
                        code="diagnosis_unknown",
                        message="Unable to determine service requirements for this diagnosis. Coordinator review needed.",
                    )
                ],
                matched=[],
                coverage=coverage,
                exact_plan=exact_plan,
            )
        reasons.append(
            EligibilityReason(
                code="clinical_ok",
                message=f"Services required: {', '.join(services)}",
            )
        )

        if req.service_types_needed:
            # filter coverage to requested if provided
            pass

        # Step 4: caregivers — match per cert group (OR within either-group);
        # ACCEPT if every required group has ≥1 caregiver (union of matches).
        all_matched: list[CaregiverMatchItem] = []
        seen: set[UUID] = set()
        uncovered: list[str] = []
        for group in cert_groups or [["RN"]]:
            match_req = CaregiverMatchRequest(
                certification_types=group + ([specialty] if specialty else []),
                zip_code=req.zip_code.strip(),
            )
            batch = await self._matcher.match(
                session,
                match_req,
                specialty_bonus=specialty,
                required_cert_groups=[group],
            )
            if not batch:
                uncovered.append("|".join(group))
            for m in batch:
                if m.id not in seen:
                    seen.add(m.id)
                    all_matched.append(m)

        matched = sorted(all_matched, key=lambda x: x.match_score, reverse=True)
        if uncovered or not matched:
            return await self._finalize(
                session,
                req,
                decision="NEEDS_MORE_INFO",
                reasons=reasons
                + [
                    EligibilityReason(
                        code="no_caregivers",
                        message="No available caregivers with required certifications in that area. Coordinator will check for alternatives.",
                    )
                ],
                matched=matched,
                coverage=coverage,
                exact_plan=exact_plan,
            )
        reasons.append(
            EligibilityReason(
                code="caregivers_ok",
                message=f"{len(matched)} caregiver(s) matched",
            )
        )

        flat_certs = sorted({c for g in cert_groups for c in g})
        missing = await self._missing_docs(session, req, coverage, services)
        return await self._finalize(
            session,
            req,
            decision="ACCEPT",
            reasons=reasons,
            matched=matched,
            coverage=coverage,
            exact_plan=exact_plan,
            missing=missing,
            required_cert_names=set(flat_certs),
        )

    async def _match_insurance(
        self, session: AsyncSession, req: EligibilityCheckRequest
    ) -> tuple[Optional[InsuranceContract], bool]:
        payer = req.insurance_payer.strip()
        stmt = select(InsuranceContract).where(
            InsuranceContract.accepted.is_(True),
            func.lower(InsuranceContract.payer_name) == payer.lower(),
        )
        if req.insurance_plan:
            plan = req.insurance_plan.strip()
            stmt = stmt.where(func.lower(InsuranceContract.plan_name) == plan.lower())
            row = (await session.execute(stmt)).scalars().first()
            return row, row is not None
        row = (await session.execute(stmt)).scalars().first()
        return row, False

    async def _neo4j_coverage(self, plan_name: str) -> list[CoverageDetail]:
        code = _plan_name_to_code().get(plan_name.strip().lower())
        if not code:
            return []
        driver = get_neo4j()
        details: list[CoverageDetail] = []
        async with driver.session() as neo:
            result = await neo.run(
                """
                MATCH (i:InsurancePlan {code: $code})-[cov:COVERS]->(s:ServiceType)
                RETURN s.name AS service,
                       cov.priorAuthRequired AS prior_auth,
                       cov.requiredDocs AS required_docs,
                       cov.visitLimit AS visit_limit,
                       cov.episodeDays AS episode_days
                """,
                code=code,
            )
            async for rec in result:
                docs = rec["required_docs"] or []
                if not isinstance(docs, list):
                    docs = list(docs) if docs else []
                details.append(
                    CoverageDetail(
                        service_type=rec["service"],
                        prior_auth_required=bool(rec["prior_auth"]),
                        required_docs=[str(d) for d in docs],
                        visit_limit=rec["visit_limit"],
                        episode_days=rec["episode_days"],
                    )
                )
        return details

    async def _neo4j_clinical(
        self, icd: str
    ) -> tuple[list[str], Optional[str], list[list[str]]]:
        driver = get_neo4j()
        services: list[str] = []
        specialty: Optional[str] = None
        cert_groups: list[list[str]] = []
        async with driver.session() as neo:
            result = await neo.run(
                """
                MATCH (d:Diagnosis {icdCode: $icd})-[r:REQUIRES]->(s:ServiceType)
                RETURN s.name AS service, r.priority AS priority, r.specialization AS specialization
                """,
                icd=icd,
            )
            rows = [rec async for rec in result]
            if not rows:
                return [], None, []
            for rec in rows:
                services.append(rec["service"])
                if rec["specialization"]:
                    specialty = rec["specialization"]

            for svc in services:
                cres = await neo.run(
                    """
                    MATCH (s:ServiceType {name: $service})-[n:NEEDS_CERTIFICATION]->(c:CertificationType)
                    RETURN c.name AS cert, n.either AS either
                    """,
                    service=svc,
                )
                either_group: list[str] = []
                async for crec in cres:
                    cert = crec["cert"]
                    if crec["either"]:
                        either_group.append(cert)
                    else:
                        cert_groups.append([cert])
                if either_group:
                    cert_groups.append(either_group)
        return services, specialty, cert_groups

    async def _missing_docs(
        self,
        session: AsyncSession,
        req: EligibilityCheckRequest,
        coverage: list[CoverageDetail],
        services: list[str],
    ) -> list[str]:
        needed: set[str] = set()
        svc_set = set(services)
        for c in coverage:
            if not svc_set or c.service_type in svc_set:
                needed.update(c.required_docs)
        if not req.intake_record_id:
            return sorted(needed)
        stmt = select(Document).where(Document.intake_record_id == req.intake_record_id)
        docs = list((await session.execute(stmt)).scalars().all())
        present: set[str] = set()
        for d in docs:
            present.update((d.extraction_result or {}).keys())
            if d.file_name:
                present.add(d.file_name.lower())
        return sorted(n for n in needed if n not in present and n.lower() not in present)

    async def _finalize(
        self,
        session: AsyncSession,
        req: EligibilityCheckRequest,
        *,
        decision: str,
        reasons: list[EligibilityReason],
        matched: list[CaregiverMatchItem],
        coverage: list[CoverageDetail],
        exact_plan: bool,
        missing: Optional[list[str]] = None,
        required_cert_names: Optional[set[str]] = None,
    ) -> EligibilityCheckResponse:
        if decision == "DECLINE":
            confidence = CONF_DECLINE
        elif decision == "NEEDS_MORE_INFO":
            confidence = CONF_NEEDS_INFO
        elif exact_plan and matched:
            confidence = CONF_ACCEPT_EXACT
        else:
            confidence = CONF_ACCEPT_PAYER_ONLY

        near = CaregiverMatchService.near_capacity(matched)
        # cert days: approximate from match list — null if unknown
        cert_days = None

        voice = self._guardrails.check_eligibility_confidence(
            {
                "confidence": confidence,
                "exact_plan_match": exact_plan,
                "caregiver_cert_days_remaining": cert_days,
                "caregiver_near_capacity": near,
            }
        )

        resp = EligibilityCheckResponse(
            decision=decision,
            reasons=reasons,
            matched_caregivers=matched,
            coverage_details=coverage,
            missing_documents=missing or [],
            confidence_score=confidence,
            voice_guidance=voice,
        )

        if req.persist and req.intake_record_id:
            row = await session.get(IntakeRecord, req.intake_record_id)
            if row is not None:
                row.eligibility_decision = decision
                row.eligibility_reasons = [r.model_dump() for r in reasons]
                row.matched_caregivers = [m.model_dump(mode="json") for m in matched]

        return resp

    async def list_service_areas(self, session: AsyncSession) -> list[ServiceArea]:
        stmt = select(ServiceArea).where(ServiceArea.active.is_(True)).order_by(ServiceArea.zip_code)
        return list((await session.execute(stmt)).scalars().all())

    async def list_insurance(self, session: AsyncSession) -> list[InsuranceContract]:
        stmt = (
            select(InsuranceContract)
            .where(InsuranceContract.accepted.is_(True))
            .order_by(InsuranceContract.payer_name, InsuranceContract.plan_name)
        )
        return list((await session.execute(stmt)).scalars().all())
