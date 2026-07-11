# ponytail: sequential layers — ceiling: ~200 pages; upgrade: gather per page
"""Document processor — runs layers 1–7 with Redis checkpoints."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

from backend.models.database import get_redis, get_sessionmaker, init_all_dbs
from backend.models.schemas import IntakeRecordUpdate
from backend.models.tables import Document, DocumentPage, DocumentProcessingStatus
from backend.pipeline.classification import classify_pages
from backend.pipeline.completeness import check_completeness
from backend.pipeline.confidence import score_fields
from backend.pipeline.extraction import extract_and_normalize
from backend.pipeline.ingestion import ingest_pdf
from backend.pipeline.review_loop import run_review_loop
from backend.services.gemini_client import get_default_gemini
from backend.services.guardrail_service import GuardrailService
from backend.services.intake_service import IntakeService

logger = logging.getLogger(__name__)
CHECKPOINT_TTL = 3600
LAYER_STATUS = {
    1: DocumentProcessingStatus.preprocessing,
    2: DocumentProcessingStatus.classifying,
    3: DocumentProcessingStatus.extracting,
    4: DocumentProcessingStatus.extracting,
    5: DocumentProcessingStatus.validating,
    6: DocumentProcessingStatus.validating,
    7: DocumentProcessingStatus.validating,
}


def _ckpt_key(doc_id: UUID) -> str:
    return f"pipeline:{doc_id}"


class DocumentProcessor:
    def __init__(self, gemini=None, guardrails: GuardrailService | None = None) -> None:
        self.gemini = gemini or get_default_gemini()
        self.guardrails = guardrails or GuardrailService()
        self.intake_svc = IntakeService(self.guardrails)

    async def process(self, document_id: UUID) -> None:
        """Async entry for FastAPI BackgroundTasks (same event loop as app).

        # ponytail: prefer await on app loop — sync wrapper below for CLI only.
        """
        await self._process_async(document_id)

    def process_sync(self, document_id: UUID) -> None:
        """Sync CLI entry — fresh engine for a new asyncio.run loop."""
        import asyncio

        asyncio.run(self._process_with_fresh_clients(document_id))

    async def _process_with_fresh_clients(self, document_id: UUID) -> None:
        from redis.asyncio import Redis
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.sqlalchemy_database_uri, pool_pre_ping=True
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await self._process_async(
                document_id, session_factory=Session, redis_client=redis
            )
        finally:
            await engine.dispose()
            await redis.aclose()

    async def _process_async(
        self,
        document_id: UUID,
        *,
        session_factory=None,
        redis_client=None,
    ) -> None:
        if session_factory is None:
            try:
                get_sessionmaker()
            except RuntimeError:
                await init_all_dbs()
            session_factory = get_sessionmaker()

        async with session_factory() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                logger.error("document %s not found", document_id)
                return

            redis = redis_client if redis_client is not None else get_redis()
            pages: list[dict[str, Any]] = []
            start_layer = 1
            raw = await redis.get(_ckpt_key(document_id))
            if raw and doc.processing_status == DocumentProcessingStatus.failed:
                try:
                    ck = json.loads(raw)
                    pages = ck.get("pages") or []
                    start_layer = int(doc.failed_at_layer or ck.get("current_layer") or 1)
                except json.JSONDecodeError:
                    start_layer = 1

            try:
                if start_layer <= 1:
                    await self._set_status(session, doc, 1)
                    pages = ingest_pdf(doc.file_path, document_id)
                    doc.page_count = len(pages)
                    await self._checkpoint(redis, document_id, 1, pages)
                    await session.commit()

                if start_layer <= 2:
                    await self._set_status(session, doc, 2)
                    pages = classify_pages(pages, self.gemini)
                    await self._persist_pages(session, doc, pages, layer=2)
                    await self._checkpoint(redis, document_id, 2, pages)
                    await session.commit()

                if start_layer <= 4:
                    await self._set_status(session, doc, 3)
                    pages = extract_and_normalize(pages, self.gemini)
                    await self._checkpoint(redis, document_id, 4, pages)
                    await session.commit()

                gaps: list[dict[str, Any]] = []
                issues: list[dict[str, Any]] = []
                if start_layer <= 5:
                    await self._set_status(session, doc, 5)
                    pages, gaps, issues = run_review_loop(
                        pages, self.gemini, self.guardrails
                    )
                    await self._checkpoint(redis, document_id, 5, pages, meta={"gaps": gaps})
                    await session.commit()

                merged: dict[str, Any] = {}
                scores: dict[str, float] = {}
                routing: dict[str, str] = {}
                if start_layer <= 7:
                    await self._set_status(session, doc, 6)
                    # merge normalized for completeness
                    for p in pages:
                        for k, v in (p.get("normalized") or {}).items():
                            if v not in (None, "", []):
                                merged[k] = v
                    gaps = gaps + check_completeness(merged)
                    await self._set_status(session, doc, 7)
                    merged, scores, routing = score_fields(
                        pages,
                        cross_issues=issues,
                        guardrails=self.guardrails,
                    )
                    # filter REJECT
                    for field, decision in list(routing.items()):
                        if decision == "REJECT":
                            gaps.append(
                                {
                                    "field_name": field,
                                    "reason": "confidence rejected",
                                    "priority": "high",
                                    "suggested_action": "Verify on phone call",
                                }
                            )
                            merged.pop(field, None)

                result = {
                    "fields": merged,
                    "confidence_scores": scores,
                    "gaps": gaps,
                    "routing": routing,
                }
                doc.extraction_result = result
                doc.processing_status = DocumentProcessingStatus.complete
                doc.failed_at_layer = None
                await self._persist_pages(session, doc, pages, layer=7, final=True)
                await self._checkpoint(redis, document_id, 7, pages, meta=result)

                if doc.intake_record_id:
                    await self._merge_intake(session, doc, merged, gaps)
                await session.commit()

                logger.info(
                    "orchestrator_notify document_complete %s intake=%s",
                    document_id,
                    doc.intake_record_id,
                )
            except Exception:
                logger.exception("pipeline failed for %s", document_id)
                # determine layer from status
                layer = {
                    DocumentProcessingStatus.preprocessing: 1,
                    DocumentProcessingStatus.classifying: 2,
                    DocumentProcessingStatus.extracting: 3,
                    DocumentProcessingStatus.validating: 5,
                }.get(doc.processing_status, 1)
                doc.processing_status = DocumentProcessingStatus.failed
                doc.failed_at_layer = layer
                await session.commit()
                await self._checkpoint(redis, document_id, layer, pages)
                # no auto-retry

    async def _set_status(self, session, doc: Document, layer: int) -> None:
        doc.processing_status = LAYER_STATUS[layer]
        await session.flush()

    async def _checkpoint(
        self,
        redis,
        document_id: UUID,
        layer: int,
        pages: list[dict[str, Any]],
        meta: dict | None = None,
    ) -> None:
        payload = {"current_layer": layer, "pages": pages, "meta": meta or {}}
        await redis.set(
            _ckpt_key(document_id),
            json.dumps(payload, default=str),
            ex=CHECKPOINT_TTL,
        )

    async def _persist_pages(
        self,
        session,
        doc: Document,
        pages: list[dict[str, Any]],
        *,
        layer: int,
        final: bool = False,
    ) -> None:
        await session.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
        for p in pages:
            session.add(
                DocumentPage(
                    document_id=doc.id,
                    page_number=p["page_number"],
                    classification=p.get("classification"),
                    extraction_path=p.get("extraction_path"),
                    raw_extraction=p.get("raw_extraction") or {},
                    validated_extraction=p.get("normalized") or {},
                    confidence_scores={},
                    validation_errors=p.get("validation_errors") or [],
                )
            )
        await session.flush()

    async def _merge_intake(
        self,
        session,
        doc: Document,
        fields: dict[str, Any],
        gaps: list[dict[str, Any]],
    ) -> None:
        from backend.models.tables import IntakeRecord

        intake = await session.get(IntakeRecord, doc.intake_record_id)
        if intake is None:
            return
        patient: dict[str, Any] = {}
        clinical: dict[str, Any] = {}
        insurance: dict[str, Any] = {}
        physician: dict[str, Any] = {}
        care: dict[str, Any] = {}

        mapping = {
            "patient_name": ("patient", "patient_name"),
            "date_of_birth": ("patient", "date_of_birth"),
            "zip_code": ("patient", "zip_code"),
            "patient_phone": ("patient", "patient_phone"),
            "icd_codes": ("clinical", "icd_codes"),
            "primary_diagnosis": ("clinical", "primary_diagnosis"),
            "discharge_date": ("clinical", "discharge_date"),
            "payer_name": ("insurance", "payer_name"),
            "plan_name": ("insurance", "plan_name"),
            "member_id": ("insurance", "member_id"),
            "physician_name": ("physician", "physician_name"),
            "physician_npi": ("physician", "physician_npi"),
        }
        buckets = {
            "patient": patient,
            "clinical": clinical,
            "insurance": insurance,
            "physician": physician,
            "care": care,
        }
        for src, (bucket, key) in mapping.items():
            if src in fields and fields[src] not in (None, "", []):
                buckets[bucket][key] = fields[src]

        update = IntakeRecordUpdate(
            patient_data=patient or None,
            clinical_data=clinical or None,
            insurance_data=insurance or None,
            physician_data=physician or None,
            care_request=care or None,
            gaps=(list(intake.gaps or []) + gaps) or None,
        )
        await self.intake_svc.update_data(session, intake.id, update)
        # eligibility watcher runs inside IntakeService.update_data
