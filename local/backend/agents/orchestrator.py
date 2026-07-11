# ponytail: in-process LangGraph — ceiling: restart loses paused state; upgrade: Redis checkpoint
"""LangGraph Intake Orchestrator — decides; Voice Agent obeys."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional, TypedDict
from uuid import UUID

from langgraph.graph import END, StateGraph

from backend.models.database import get_sessionmaker
from backend.models.schemas import (
    EligibilityCheckRequest,
    FollowUpActionCreate,
    IntakeRecordCreate,
    IntakeRecordUpdate,
    StatusUpdate,
)
from backend.models.tables import FollowUpType, IntakeSource, IntakeStatus
from backend.services.eligibility_service import EligibilityService
from backend.services.followup_service import FollowUpService
from backend.services.guardrail_service import GuardrailService
from backend.services.intake_service import IntakeService

logger = logging.getLogger(__name__)

DOC_SOURCES = {
    IntakeSource.fax,
    IntakeSource.physician_referral,
    IntakeSource.snf_referral,
}
CALL_SOURCES = {
    IntakeSource.inbound_call_provider,
    IntakeSource.inbound_call_family,
    IntakeSource.inbound_call_patient,
}
ELIG_LEAVES = (
    ("patient_data", "zip_code"),
    ("insurance_data", "payer_name"),
    ("insurance_data", "plan_name"),
    ("clinical_data", "icd_codes"),
    ("clinical_data", "primary_diagnosis"),
    ("care_request", "service_types_needed"),
)


class IntakeState(TypedDict, total=False):
    referral_id: Optional[str]
    status: str
    source_type: str
    patient_data: dict[str, Any]
    clinical_data: dict[str, Any]
    physician_data: dict[str, Any]
    insurance_data: dict[str, Any]
    care_request: dict[str, Any]
    referral_source: dict[str, Any]
    extraction_confidence: dict[str, float]
    gaps: list[dict[str, Any]]
    data_sources: dict[str, Any]
    eligibility_decision: Optional[str]
    eligibility_reasons: list[Any]
    matched_caregivers: list[Any]
    eligibility_run_count: int
    missing_documents: list[Any]
    calls: list[dict[str, Any]]
    follow_ups: list[dict[str, Any]]
    active_call_sid: Optional[str]
    escalated: bool
    escalation_reason: Optional[str]
    human_review_required: bool
    needs_eligibility_check: bool
    needs_outbound_call: bool
    outbound_mission: Optional[dict[str, Any]]
    workflow_complete: bool
    incoming_data: dict[str, Any]
    incoming_source: str
    next_action: str
    document_id: Optional[str]
    pause: bool
    gap_attempts: int
    send_followup_event: Optional[str]


def empty_state(**kwargs: Any) -> IntakeState:
    base: IntakeState = {
        "referral_id": None,
        "status": IntakeStatus.new.value,
        "source_type": IntakeSource.fax.value,
        "patient_data": {},
        "clinical_data": {},
        "physician_data": {},
        "insurance_data": {},
        "care_request": {},
        "referral_source": {},
        "extraction_confidence": {},
        "gaps": [],
        "data_sources": {},
        "eligibility_decision": None,
        "eligibility_reasons": [],
        "matched_caregivers": [],
        "eligibility_run_count": 0,
        "missing_documents": [],
        "calls": [],
        "follow_ups": [],
        "active_call_sid": None,
        "escalated": False,
        "escalation_reason": None,
        "human_review_required": False,
        "needs_eligibility_check": False,
        "needs_outbound_call": False,
        "outbound_mission": None,
        "workflow_complete": False,
        "incoming_data": {},
        "incoming_source": "system",
        "next_action": "",
        "document_id": None,
        "pause": False,
        "gap_attempts": 0,
        "send_followup_event": None,
    }
    base.update(kwargs)  # type: ignore[typeddict-item]
    return base


def has_critical_gaps(state: IntakeState) -> bool:
    if state.get("missing_documents"):
        return True
    for g in state.get("gaps") or []:
        pri = str(g.get("priority") or "").lower()
        name = str(g.get("field_name") or "").lower()
        if pri in ("high", "critical") or "f2f" in name:
            return True
    return False


def map_extracted_to_buckets(extracted: dict[str, Any]) -> dict[str, dict[str, Any]]:
    patient, clinical, insurance, physician, care = {}, {}, {}, {}, {}
    mapping = {
        "patient_name": ("patient", "patient_name"),
        "date_of_birth": ("patient", "date_of_birth"),
        "zip_code": ("patient", "zip_code"),
        "patient_phone": ("patient", "patient_phone"),
        "icd_codes": ("clinical", "icd_codes"),
        "primary_diagnosis": ("clinical", "primary_diagnosis"),
        "diagnosis": ("clinical", "primary_diagnosis"),
        "discharge_date": ("clinical", "discharge_date"),
        "payer_name": ("insurance", "payer_name"),
        "plan_name": ("insurance", "plan_name"),
        "plan_type": ("insurance", "plan_type"),
        "member_id": ("insurance", "member_id"),
        "physician_name": ("physician", "physician_name"),
        "physician_npi": ("physician", "physician_npi"),
        "service_types_needed": ("care", "service_types_needed"),
    }
    buckets = {
        "patient": patient,
        "clinical": clinical,
        "insurance": insurance,
        "physician": physician,
        "care": care,
    }
    for k, v in (extracted or {}).items():
        if v in (None, "", []):
            continue
        if k in mapping:
            b, key = mapping[k]
            buckets[b][key] = v
    return {
        "patient_data": patient,
        "clinical_data": clinical,
        "insurance_data": insurance,
        "physician_data": physician,
        "care_request": care,
    }


class Orchestrator:
    """In-process orchestrator with in-memory state by intake id."""

    def __init__(
        self,
        *,
        intake: IntakeService | None = None,
        eligibility: EligibilityService | None = None,
        followup: FollowUpService | None = None,
        guardrails: GuardrailService | None = None,
    ) -> None:
        self.intake_svc = intake or IntakeService()
        self.elig_svc = eligibility or EligibilityService()
        self.follow_svc = followup or FollowUpService()
        self.guardrails = guardrails or GuardrailService()
        self._states: dict[str, IntakeState] = {}
        self._graph = self._build_graph()

    def get_state(self, intake_id: str | UUID) -> IntakeState | None:
        return self._states.get(str(intake_id))

    def save_state(self, state: IntakeState) -> None:
        rid = state.get("referral_id")
        if rid:
            self._states[str(rid)] = state

    async def start(
        self,
        *,
        source: str,
        intake_id: UUID | None = None,
        initial_data: dict[str, Any] | None = None,
        document_id: UUID | None = None,
    ) -> IntakeState:
        state = empty_state(
            source_type=source,
            referral_id=str(intake_id) if intake_id else None,
            document_id=str(document_id) if document_id else None,
            incoming_data=initial_data or {},
            incoming_source="system",
        )
        result = await self._graph.ainvoke(state)
        self.save_state(result)
        return result

    async def resume(
        self,
        intake_id: UUID | str,
        *,
        from_node: str | None = None,
        incoming_data: dict[str, Any] | None = None,
        incoming_source: str = "system",
        event: str | None = None,
    ) -> IntakeState:
        key = str(intake_id)
        state = self._states.get(key) or empty_state(referral_id=key)
        state = await self._hydrate_from_db(state)
        if incoming_data:
            state["incoming_data"] = incoming_data
            state["incoming_source"] = incoming_source
        state["pause"] = False
        if event == "document_complete":
            # sync only — no second EligibilityService.check
            return await self._route_after_document(state)
        if event == "eligibility_recheck":
            state["needs_eligibility_check"] = True
            state["next_action"] = "check_eligibility"
            result = await self._run_from(state, "check_eligibility")
            self.save_state(result)
            return result
        if event == "call_ended" or from_node == "merge_data":
            result = await self._run_from(state, "merge_data")
            self.save_state(result)
            return result
        if from_node:
            result = await self._run_from(state, from_node)
            self.save_state(result)
            return result
        result = await self._graph.ainvoke(state)
        self.save_state(result)
        return result

    async def on_document_complete(
        self, document_id: UUID, intake_id: UUID | None
    ) -> None:
        if intake_id is None:
            logger.info("document %s complete with no intake — skip orchestrator", document_id)
            return
        logger.info(
            "orchestrator_notify document_complete %s intake=%s",
            document_id,
            intake_id,
        )
        await self.resume(intake_id, event="document_complete")

    async def _route_after_document(self, state: IntakeState) -> IntakeState:
        decision = (state.get("eligibility_decision") or "").upper()
        if decision == "ACCEPT" and not has_critical_gaps(state):
            result = await self._run_from(state, "make_decision")
        elif decision == "DECLINE":
            result = await self._run_from(state, "make_decision")
        else:
            result = await self._run_from(state, "evaluate_gaps")
        self.save_state(result)
        return result

    async def _hydrate_from_db(self, state: IntakeState) -> IntakeState:
        rid = state.get("referral_id")
        if not rid:
            return state
        Session = get_sessionmaker()
        async with Session() as session:
            row = await self.intake_svc.get(session, UUID(rid))
            state["status"] = row.status.value
            state["patient_data"] = dict(row.patient_data or {})
            state["clinical_data"] = dict(row.clinical_data or {})
            state["physician_data"] = dict(row.physician_data or {})
            state["insurance_data"] = dict(row.insurance_data or {})
            state["care_request"] = dict(row.care_request or {})
            state["referral_source"] = dict(row.referral_source or {})
            state["gaps"] = list(row.gaps or [])
            state["eligibility_decision"] = row.eligibility_decision
            state["eligibility_reasons"] = list(row.eligibility_reasons or [])
            state["matched_caregivers"] = list(row.matched_caregivers or [])
            state["escalated"] = bool(row.escalated)
            state["escalation_reason"] = row.escalation_reason
            state["human_review_required"] = bool(row.human_review_required)
            state["source_type"] = row.source.value
        return state

    async def _run_from(self, state: IntakeState, node: str) -> IntakeState:
        # Run a linear path from a named node using conditional routers
        order = {
            "receive_referral": self.receive_referral,
            "process_document": self.process_document,
            "handle_inbound_call": self.handle_inbound_call,
            "check_eligibility": self.check_eligibility,
            "evaluate_gaps": self.evaluate_gaps,
            "initiate_outbound_call": self.initiate_outbound_call,
            "merge_data": self.merge_data,
            "send_followup": self.send_followup,
            "make_decision": self.make_decision,
            "escalate": self.escalate,
        }
        current = node
        visited = 0
        while current and current != END and visited < 12:
            visited += 1
            fn = order.get(current)
            if fn is None:
                break
            state = await fn(state)
            if state.get("pause") or state.get("workflow_complete"):
                break
            current = self._next_after(current, state)
        return state

    def _next_after(self, node: str, state: IntakeState) -> str:
        if node == "receive_referral":
            return self.route_after_receive(state)
        if node == "process_document":
            return END  # wait for callback
        if node == "handle_inbound_call":
            return self.route_after_inbound(state)
        if node == "check_eligibility":
            return self.route_after_eligibility(state)
        if node == "evaluate_gaps":
            return self.route_after_gaps(state)
        if node == "initiate_outbound_call":
            return END  # wait for call outcome
        if node == "merge_data":
            return self.route_after_merge(state)
        if node == "make_decision":
            return "send_followup"
        if node == "escalate":
            return "send_followup"
        if node == "send_followup":
            return END
        return END

    def _build_graph(self):
        g = StateGraph(IntakeState)
        g.add_node("receive_referral", self.receive_referral)
        g.add_node("process_document", self.process_document)
        g.add_node("handle_inbound_call", self.handle_inbound_call)
        g.add_node("check_eligibility", self.check_eligibility)
        g.add_node("evaluate_gaps", self.evaluate_gaps)
        g.add_node("initiate_outbound_call", self.initiate_outbound_call)
        g.add_node("merge_data", self.merge_data)
        g.add_node("send_followup", self.send_followup)
        g.add_node("make_decision", self.make_decision)
        g.add_node("escalate", self.escalate)
        g.set_entry_point("receive_referral")
        g.add_conditional_edges(
            "receive_referral",
            self.route_after_receive,
            {
                "process_document": "process_document",
                "handle_inbound_call": "handle_inbound_call",
            },
        )
        g.add_edge("process_document", END)
        g.add_conditional_edges(
            "handle_inbound_call",
            self.route_after_inbound,
            {
                "check_eligibility": "check_eligibility",
                "evaluate_gaps": "evaluate_gaps",
            },
        )
        g.add_conditional_edges(
            "check_eligibility",
            self.route_after_eligibility,
            {
                "make_decision": "make_decision",
                "evaluate_gaps": "evaluate_gaps",
            },
        )
        g.add_conditional_edges(
            "evaluate_gaps",
            self.route_after_gaps,
            {
                "initiate_outbound_call": "initiate_outbound_call",
                "send_followup": "send_followup",
                "escalate": "escalate",
                "check_eligibility": "check_eligibility",
            },
        )
        g.add_edge("initiate_outbound_call", END)
        g.add_conditional_edges(
            "merge_data",
            self.route_after_merge,
            {
                "check_eligibility": "check_eligibility",
                "evaluate_gaps": "evaluate_gaps",
            },
        )
        g.add_edge("make_decision", "send_followup")
        g.add_edge("escalate", "send_followup")
        g.add_edge("send_followup", END)
        return g.compile()

    # --- routers (no business logic) ---

    def route_after_receive(self, state: IntakeState) -> str:
        try:
            src = IntakeSource(state.get("source_type") or "fax")
        except ValueError:
            src = IntakeSource.fax
        if src in CALL_SOURCES:
            return "handle_inbound_call"
        return "process_document"

    def route_after_inbound(self, state: IntakeState) -> str:
        pd = state.get("patient_data") or {}
        ins = state.get("insurance_data") or {}
        clin = state.get("clinical_data") or {}
        enough = bool(
            (clin.get("icd_codes") or clin.get("primary_diagnosis"))
            and ins.get("payer_name")
            and pd.get("zip_code")
        )
        return "check_eligibility" if enough else "evaluate_gaps"

    def route_after_eligibility(self, state: IntakeState) -> str:
        decision = (state.get("eligibility_decision") or "").upper()
        if decision == "DECLINE":
            return "make_decision"
        if decision == "ACCEPT" and not has_critical_gaps(state):
            return "make_decision"
        return "evaluate_gaps"

    def route_after_gaps(self, state: IntakeState) -> str:
        if state.get("needs_outbound_call"):
            return "initiate_outbound_call"
        if (state.get("gap_attempts") or 0) >= 3:
            return "escalate"
        if not (state.get("gaps") or state.get("missing_documents")):
            return "check_eligibility"
        return "send_followup"

    def route_after_merge(self, state: IntakeState) -> str:
        if state.get("needs_eligibility_check"):
            return "check_eligibility"
        return "evaluate_gaps"

    # --- nodes ---

    async def receive_referral(self, state: IntakeState) -> IntakeState:
        Session = get_sessionmaker()
        async with Session() as session:
            if state.get("referral_id"):
                row = await self.intake_svc.get(session, UUID(state["referral_id"]))
            else:
                src = state.get("source_type") or IntakeSource.fax.value
                try:
                    source_enum = IntakeSource(src)
                except ValueError:
                    source_enum = IntakeSource.fax
                row = await self.intake_svc.create(
                    session, IntakeRecordCreate(source=source_enum)
                )
                state["referral_id"] = str(row.id)
            if row.status == IntakeStatus.new:
                row = await self.intake_svc.update_status(
                    session,
                    row.id,
                    StatusUpdate(new_status=IntakeStatus.processing),
                )
            state["status"] = row.status.value
            state["source_type"] = row.source.value
            await session.commit()
        self.save_state(state)
        return state

    async def process_document(self, state: IntakeState) -> IntakeState:
        # Do NOT call DocumentProcessor.process — upload owns that
        rid = state.get("referral_id")
        if rid:
            Session = get_sessionmaker()
            async with Session() as session:
                try:
                    await self.intake_svc.update_status(
                        session,
                        UUID(rid),
                        StatusUpdate(new_status=IntakeStatus.pending_documents),
                    )
                    await session.commit()
                    state["status"] = IntakeStatus.pending_documents.value
                except Exception:
                    logger.exception("could not set pending_documents")
        state["pause"] = True
        state["next_action"] = "wait_document"
        self.save_state(state)
        return state

    async def handle_inbound_call(self, state: IntakeState) -> IntakeState:
        # Voice Agent owns live turns; this node syncs post-call / attach context
        if state.get("incoming_data"):
            buckets = map_extracted_to_buckets(state["incoming_data"])
            for k, v in buckets.items():
                if v:
                    merged = dict(state.get(k) or {})  # type: ignore[arg-type]
                    merged.update(v)
                    state[k] = merged  # type: ignore[literal-required]
        state["pause"] = False
        self.save_state(state)
        return state

    async def check_eligibility(self, state: IntakeState) -> IntakeState:
        pd = state.get("patient_data") or {}
        ins = state.get("insurance_data") or {}
        clin = state.get("clinical_data") or {}
        care = state.get("care_request") or {}
        zip_code = pd.get("zip_code")
        payer = ins.get("payer_name")
        if not zip_code or not payer:
            state["eligibility_decision"] = "NEEDS_MORE_INFO"
            state["eligibility_reasons"] = [{"reason": "missing zip or payer"}]
            state["needs_eligibility_check"] = False
            self.save_state(state)
            return state
        icds = clin.get("icd_codes")
        icd = icds[0] if isinstance(icds, list) and icds else (icds if isinstance(icds, str) else None)
        if not icd:
            icd = clin.get("primary_diagnosis")
        Session = get_sessionmaker()
        async with Session() as session:
            req = EligibilityCheckRequest(
                icd_code=str(icd) if icd else None,
                insurance_payer=str(payer),
                insurance_plan=ins.get("plan_name") or ins.get("plan_type"),
                zip_code=str(zip_code),
                service_types_needed=care.get("service_types_needed"),
                intake_record_id=UUID(state["referral_id"]) if state.get("referral_id") else None,
                persist=True,
            )
            result = await self.elig_svc.check(session, req)
            await session.commit()
        state["eligibility_decision"] = result.decision
        state["eligibility_reasons"] = list(result.reasons or [])
        state["matched_caregivers"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in (result.matched_caregivers or [])]
        state["missing_documents"] = list(result.missing_documents or [])
        state["eligibility_run_count"] = int(state.get("eligibility_run_count") or 0) + 1
        state["needs_eligibility_check"] = False
        # merge missing docs into gaps
        for doc in state["missing_documents"]:
            name = doc if isinstance(doc, str) else str(doc)
            state.setdefault("gaps", []).append(
                {
                    "field_name": name,
                    "reason": f"Missing document: {name}",
                    "priority": "high",
                    "suggested_action": "Request from referring provider",
                }
            )
        self.save_state(state)
        return state

    async def evaluate_gaps(self, state: IntakeState) -> IntakeState:
        gaps = list(state.get("gaps") or [])
        missing = list(state.get("missing_documents") or [])
        attempts = int(state.get("gap_attempts") or 0)
        if not gaps and not missing:
            state["needs_outbound_call"] = False
            self.save_state(state)
            return state
        if attempts >= 3:
            state["needs_outbound_call"] = False
            state["escalation_reason"] = "gaps unresolved after 3 follow-ups"
            self.save_state(state)
            return state
        # Prefer phone for F2F / member_id / clinical gaps
        phone_fields = ("f2f", "face", "member", "npi", "physician", "orders")
        phoneable = False
        for g in gaps + [{"field_name": m} for m in missing]:
            name = str(g.get("field_name") or "").lower()
            if any(p in name for p in phone_fields):
                phoneable = True
                break
        if phoneable:
            state["needs_outbound_call"] = True
            src = state.get("referral_source") or {}
            state["outbound_mission"] = {
                "to": src.get("phone") or src.get("contact_phone"),
                "person_name": src.get("contact_name") or "referring provider",
                "role": "provider",
                "facility_name": src.get("facility_name"),
                "gaps": gaps,
                "known_data": {
                    "patient_data": state.get("patient_data"),
                    "insurance_data": state.get("insurance_data"),
                    "clinical_data": state.get("clinical_data"),
                },
                "intake_record_id": state.get("referral_id"),
            }
            state["send_followup_event"] = None
        else:
            state["needs_outbound_call"] = False
            state["send_followup_event"] = "gap_wait"
            state["gap_attempts"] = attempts + 1
        self.save_state(state)
        return state

    async def initiate_outbound_call(self, state: IntakeState) -> IntakeState:
        mission = state.get("outbound_mission") or {}
        rid = state.get("referral_id")
        to = mission.get("to")
        if rid and to:
            Session = get_sessionmaker()
            async with Session() as session:
                await self.follow_svc.create(
                    session,
                    FollowUpActionCreate(
                        intake_record_id=UUID(rid),
                        type=FollowUpType.outbound_call_attempted,
                        target_phone=str(to),
                        message=str(mission.get("person_name") or "follow-up"),
                        scheduled_at=datetime.now(timezone.utc),
                    ),
                )
                await session.commit()
        state["needs_outbound_call"] = False
        state["pause"] = True
        state["next_action"] = "wait_outbound"
        self.save_state(state)
        return state

    async def merge_data(self, state: IntakeState) -> IntakeState:
        incoming = state.get("incoming_data") or {}
        source = state.get("incoming_source") or "voice"
        buckets = map_extracted_to_buckets(incoming) if not any(
            k in incoming for k in ("patient_data", "clinical_data", "insurance_data")
        ) else {
            "patient_data": incoming.get("patient_data") or {},
            "clinical_data": incoming.get("clinical_data") or {},
            "insurance_data": incoming.get("insurance_data") or {},
            "physician_data": incoming.get("physician_data") or {},
            "care_request": incoming.get("care_request") or {},
        }
        elig_changed = False
        ts = datetime.now(timezone.utc).isoformat()
        for bucket_name, fields in buckets.items():
            existing = dict(state.get(bucket_name) or {})  # type: ignore[arg-type]
            for field, new_val in fields.items():
                if new_val in (None, "", []):
                    continue
                old = existing.get(field)
                if old not in (None, "", []) and old != new_val:
                    # fax_value=old, caller_value=new when source is voice
                    fax_v, caller_v = (old, new_val) if source in ("voice", "outbound") else (new_val, old)
                    resolved = self.guardrails.resolve_merge_conflict(field, fax_v, caller_v)
                    winner = resolved.get("winner")
                    if winner is None:
                        winner = new_val
                    existing[field] = winner
                else:
                    existing[field] = new_val
                state.setdefault("data_sources", {})[field] = {"source": source, "ts": ts}
                for b, leaf in ELIG_LEAVES:
                    if bucket_name == b and field == leaf:
                        elig_changed = True
            state[bucket_name] = existing  # type: ignore[literal-required]
        state["needs_eligibility_check"] = elig_changed or bool(state.get("needs_eligibility_check"))
        # persist
        rid = state.get("referral_id")
        if rid:
            Session = get_sessionmaker()
            async with Session() as session:
                await self.intake_svc.update_data(
                    session,
                    UUID(rid),
                    IntakeRecordUpdate(
                        patient_data=state.get("patient_data") or None,
                        clinical_data=state.get("clinical_data") or None,
                        insurance_data=state.get("insurance_data") or None,
                        physician_data=state.get("physician_data") or None,
                        care_request=state.get("care_request") or None,
                        gaps=state.get("gaps") or None,
                    ),
                )
                await session.commit()
        state["incoming_data"] = {}
        self.save_state(state)
        return state

    async def send_followup(self, state: IntakeState) -> IntakeState:
        event = state.get("send_followup_event") or (
            "accept" if (state.get("eligibility_decision") or "").upper() == "ACCEPT"
            and state.get("workflow_complete")
            else "decline" if (state.get("eligibility_decision") or "").upper() == "DECLINE"
            and state.get("workflow_complete")
            else "escalate" if state.get("escalated")
            else state.get("send_followup_event")
        )
        rid = state.get("referral_id")
        if not rid:
            return state
        Session = get_sessionmaker()
        async with Session() as session:
            if event == "gap_wait":
                await self.follow_svc.create(
                    session,
                    FollowUpActionCreate(
                        intake_record_id=UUID(rid),
                        type=FollowUpType.eligibility_recheck,
                        message="Gap wait recheck",
                        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=4),
                    ),
                )
                state["pause"] = True
            elif event == "accept" or (
                state.get("workflow_complete")
                and (state.get("eligibility_decision") or "").upper() == "ACCEPT"
            ):
                phone = (state.get("patient_data") or {}).get("patient_phone") or (
                    state.get("referral_source") or {}
                ).get("phone")
                if phone:
                    await self.follow_svc.create(
                        session,
                        FollowUpActionCreate(
                            intake_record_id=UUID(rid),
                            type=FollowUpType.sms_sent,
                            target_phone=str(phone),
                            message="ABC Home Health: your referral was accepted. A coordinator will follow up.",
                            scheduled_at=datetime.now(timezone.utc),
                        ),
                    )
            elif event == "decline" or (
                state.get("workflow_complete")
                and (state.get("eligibility_decision") or "").upper() == "DECLINE"
            ):
                phone = (state.get("referral_source") or {}).get("phone")
                if phone:
                    await self.follow_svc.create(
                        session,
                        FollowUpActionCreate(
                            intake_record_id=UUID(rid),
                            type=FollowUpType.sms_sent,
                            target_phone=str(phone),
                            message="ABC Home Health: we are unable to accept this referral at this time.",
                            scheduled_at=datetime.now(timezone.utc),
                        ),
                    )
            elif event == "escalate" or state.get("escalated"):
                await self.follow_svc.create(
                    session,
                    FollowUpActionCreate(
                        intake_record_id=UUID(rid),
                        type=FollowUpType.callback_scheduled,
                        message=state.get("escalation_reason") or "Human review required",
                        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=8),
                    ),
                )
            elif event == "call_end":
                phone = (state.get("patient_data") or {}).get("patient_phone")
                if phone:
                    await self.follow_svc.create(
                        session,
                        FollowUpActionCreate(
                            intake_record_id=UUID(rid),
                            type=FollowUpType.sms_sent,
                            target_phone=str(phone),
                            message="Thank you for calling ABC Home Health. A coordinator may follow up.",
                            scheduled_at=datetime.now(timezone.utc),
                        ),
                    )
            await session.commit()
        self.save_state(state)
        return state

    async def make_decision(self, state: IntakeState) -> IntakeState:
        rid = state.get("referral_id")
        decision = (state.get("eligibility_decision") or "").upper()
        if not rid:
            state["workflow_complete"] = True
            return state
        Session = get_sessionmaker()
        async with Session() as session:
            if decision == "ACCEPT":
                # eligible then accepted
                try:
                    await self.intake_svc.update_status(
                        session, UUID(rid), StatusUpdate(new_status=IntakeStatus.eligible)
                    )
                except Exception:
                    pass
                await self.intake_svc.update_status(
                    session, UUID(rid), StatusUpdate(new_status=IntakeStatus.accepted)
                )
                state["status"] = IntakeStatus.accepted.value
                state["send_followup_event"] = "accept"
            elif decision == "DECLINE":
                await self.intake_svc.update_status(
                    session, UUID(rid), StatusUpdate(new_status=IntakeStatus.declined)
                )
                state["status"] = IntakeStatus.declined.value
                state["send_followup_event"] = "decline"
            else:
                # needs more info exhausted → escalate path usually
                state["send_followup_event"] = "gap_wait"
            await session.commit()
        state["workflow_complete"] = decision in ("ACCEPT", "DECLINE")
        self.save_state(state)
        return state

    async def escalate(self, state: IntakeState) -> IntakeState:
        rid = state.get("referral_id")
        reason = state.get("escalation_reason") or "Escalated to human coordinator"
        state["escalated"] = True
        state["escalation_reason"] = reason
        state["human_review_required"] = True
        state["send_followup_event"] = "escalate"
        if rid:
            Session = get_sessionmaker()
            async with Session() as session:
                await self.intake_svc.update_status(
                    session,
                    UUID(rid),
                    StatusUpdate(new_status=IntakeStatus.escalated, reason=reason),
                )
                await session.commit()
            state["status"] = IntakeStatus.escalated.value
        state["workflow_complete"] = True
        self.save_state(state)
        return state


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
