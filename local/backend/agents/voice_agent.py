# ponytail: in-memory CallSid sessions — ceiling: restart drops calls; upgrade: Redis-primary
"""Voice Agent — ConversationRelay handler; Orchestrator decides."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from backend.agents.orchestrator import get_orchestrator, map_extracted_to_buckets
from backend.models.database import get_redis, get_sessionmaker
from backend.voice import consent as consent_gate
from backend.voice.guardrails import rehydrate, tokenize

# must-have.md #2 names exactly these as identifiers — NOT clinical/operational
# fields like zip_code, icd_codes, or diagnosis text. Tokenizing those too
# confused Gemini (it saw literal "{{ZIP_CODE}}" tokens with no explanation
# and asked the caller to repeat already-given info) — caught during Task 1
# end-to-end testing 2026-07-11.
_IDENTIFIER_FIELDS = {
    "patient_name",
    "date_of_birth",
    "dob",
    "patient_phone",
    "phone",
    "patient_address",
    "address",
    "insurance_member_id",
    "member_id",
    "ssn",
}


def _identifier_subset(accumulated_data: dict[str, Any]) -> dict[str, str]:
    return {k: v for k, v in accumulated_data.items() if k in _IDENTIFIER_FIELDS and v}
from backend.models.schemas import (
    EligibilityCheckRequest,
    FollowUpActionCreate,
    IntakeRecordCreate,
    IntakeRecordUpdate,
)
from backend.models.tables import (
    CallDirection,
    CallMode,
    CallStatus,
    FollowUpType,
    IntakeSource,
    ReferralSource,
)
from backend.prompts import load_prompt
from backend.services.call_service import CallService
from backend.services.eligibility_service import EligibilityService
from backend.services.followup_service import FollowUpService
from backend.services.gemini_client import FakeGeminiClient, get_default_gemini
from backend.services.guardrail_service import GuardrailService
from backend.services.intake_service import IntakeService
from sqlalchemy import select

logger = logging.getLogger(__name__)
CALL_REDIS_TTL = 3600
MAX_CALL_MINUTES = 14
FILLER = "Let me check our availability for that area... one moment."
MODE_PROMPTS = {
    "provider": "provider_inbound",
    "family": "family_inbound",
    "patient": "patient_inbound",
    "outbound_followup": "outbound_followup",
}


def _parse_json_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {
        "response": text or "I'm sorry, could you repeat that?",
        "extracted": {},
        "needs_clarification": [],
        "ready_for_eligibility": False,
        "caller_distress": False,
        "clinical_question": False,
    }


def _merge_last_wins(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    for k, v in (incoming or {}).items():
        if v is None or v == "" or v == []:
            continue
        out[k] = v
    return out


def _normalize_phone(p: str | None) -> str:
    if not p:
        return ""
    digits = re.sub(r"\D", "", p)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


@dataclass
class CallSession:
    call_sid: str
    caller_number: str | None = None
    conversation_mode: str | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    accumulated_data: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""
    intake_record_id: UUID | None = None
    eligibility_checked: bool = False
    last_elig_fingerprint: str | None = None
    turn_count: int = 0
    call_start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    direction: str = "inbound"
    mission: dict[str, Any] = field(default_factory=dict)
    voicemail: bool = False
    pending_task: asyncio.Task | None = None
    call_record_created: bool = False
    eligibility_result: dict[str, Any] | None = None
    consent_given: bool = False  # must-have.md #4 — no data collection before this is True


class VoiceAgent:
    def __init__(
        self,
        gemini=None,
        guardrails: GuardrailService | None = None,
        eligibility: EligibilityService | None = None,
        intake: IntakeService | None = None,
        followup: FollowUpService | None = None,
        calls: CallService | None = None,
    ) -> None:
        self.gemini = gemini or get_default_gemini()
        self.guardrails = guardrails or GuardrailService()
        self.elig = eligibility or EligibilityService()
        self.intake_svc = intake or IntakeService()
        self.follow_svc = followup or FollowUpService()
        self.call_svc = calls or CallService()
        self.sessions: dict[str, CallSession] = {}

    def get_session(self, call_sid: str) -> CallSession | None:
        return self.sessions.get(call_sid)

    async def on_setup(self, payload: dict[str, Any]) -> CallSession:
        call_sid = (
            payload.get("callSid")
            or payload.get("CallSid")
            or payload.get("call_sid")
            or "unknown"
        )
        caller = payload.get("from") or payload.get("From") or payload.get("caller")
        custom = payload.get("customParameters") or payload.get("custom_parameters") or {}
        if isinstance(custom, str):
            try:
                custom = json.loads(custom)
            except json.JSONDecodeError:
                custom = {}
        session = CallSession(
            call_sid=call_sid,
            caller_number=caller,
            direction="outbound" if custom.get("mission") else "inbound",
            mission=dict(custom) if custom else {},
        )
        answered_by = (payload.get("answeredBy") or payload.get("AnsweredBy") or "").lower()
        if "machine" in answered_by or custom.get("voicemail"):
            session.voicemail = True
            session.conversation_mode = "outbound_followup"
        # known referral source → provider mode
        if caller and not session.conversation_mode:
            mode = await self._lookup_referral_source(caller)
            if mode:
                session.conversation_mode = "provider"
                session.system_prompt = load_prompt(MODE_PROMPTS["provider"])
                await self._ensure_call_record(session)
        if session.mission.get("mission") and not session.conversation_mode:
            session.conversation_mode = "outbound_followup"
            base = load_prompt("outbound_followup")
            session.system_prompt = (
                f"{base}\n\nMISSION CONTEXT:\n"
                f"You are calling {session.mission.get('person_name')} "
                f"at {session.mission.get('facility_name')} about referral for "
                f"patient {session.mission.get('patient_name')}. "
                f"You need to: {session.mission.get('gaps')}. "
                f"You already know: {session.mission.get('known_data')}."
            )
            if session.mission.get("intake_record_id"):
                try:
                    session.intake_record_id = UUID(str(session.mission["intake_record_id"]))
                except ValueError:
                    pass
            await self._ensure_call_record(session)
        self.sessions[call_sid] = session
        await self._redis_save(session)
        return session

    async def _lookup_referral_source(self, phone: str) -> bool:
        want = _normalize_phone(phone)
        if not want:
            return False
        try:
            Session = get_sessionmaker()
            async with Session() as session:
                rows = (await session.execute(select(ReferralSource))).scalars().all()
                for r in rows:
                    if _normalize_phone(r.phone) == want:
                        return True
        except Exception:
            logger.exception("referral source lookup failed")
        return False

    async def handle_turn(self, call_sid: str, user_text: str) -> dict[str, Any]:
        session = self.sessions.get(call_sid)
        if session is None:
            session = await self.on_setup({"callSid": call_sid})
        if session.voicemail:
            msg = (
                "Hello, this is ABC Home Health. Please call us back or fax the "
                "requested referral documentation. Thank you."
            )
            return {
                "response": msg,
                "extracted": {},
                "accumulated_data": session.accumulated_data,
                "ready_for_eligibility": False,
                "eligibility_result": None,
                "guardrail_violations": [],
                "conversation_mode": session.conversation_mode,
            }

        # must-have.md #4 — consent gather is the literal first gate, before
        # any data collection begins. No exceptions except voicemail above
        # (a pre-scripted message that collects nothing).
        if not session.consent_given:
            if consent_gate.is_negative(user_text):
                return {
                    "response": "No problem — thank you for calling. Goodbye.",
                    "extracted": {},
                    "accumulated_data": session.accumulated_data,
                    "ready_for_eligibility": False,
                    "eligibility_result": None,
                    "guardrail_violations": [],
                    "conversation_mode": session.conversation_mode,
                }
            if consent_gate.is_affirmative(user_text):
                session.consent_given = True
                return {
                    "response": "Thank you. How can I help you today?",
                    "extracted": {},
                    "accumulated_data": session.accumulated_data,
                    "ready_for_eligibility": False,
                    "eligibility_result": None,
                    "guardrail_violations": [],
                    "conversation_mode": session.conversation_mode,
                }
            # Ambiguous reply to the consent question — re-ask, never guess.
            return {
                "response": consent_gate.CONSENT_QUESTION,
                "extracted": {},
                "accumulated_data": session.accumulated_data,
                "ready_for_eligibility": False,
                "eligibility_result": None,
                "guardrail_violations": [],
                "conversation_mode": session.conversation_mode,
            }

        session.turn_count += 1
        guardrail_violations: list[Any] = []
        eligibility_result = None

        # Identify mode on first turn
        if session.conversation_mode is None:
            id_prompt = (
                "Based on what the caller said, determine caller_type: "
                "'provider', 'family', or 'patient'. Include this in your JSON output "
                "as caller_type, plus response and extracted fields.\n"
                f"Caller said: {user_text}"
            )
            raw = self.gemini.chat(
                "You identify home health referral callers. Reply JSON only.",
                [],
                id_prompt,
            )
            parsed = _parse_json_response(raw)
            ctype = (parsed.get("caller_type") or "provider").lower()
            if ctype not in MODE_PROMPTS:
                ctype = "provider"
            session.conversation_mode = ctype if ctype != "outbound_followup" else "provider"
            session.system_prompt = load_prompt(MODE_PROMPTS[session.conversation_mode])
            await self._ensure_call_record(session)
            # continue with same turn using extracted from ID response
        else:
            parsed = None

        user_msg = user_text
        if parsed is None:
            raw = await self._gemini_turn(session, user_msg)
            parsed = _parse_json_response(raw)
        else:
            # already have ID parse — still may need normal extract from same utterance
            if not parsed.get("extracted"):
                raw2 = await self._gemini_turn(session, user_msg)
                parsed2 = _parse_json_response(raw2)
                parsed["extracted"] = parsed2.get("extracted") or {}
                if parsed2.get("response"):
                    parsed["response"] = parsed2["response"]
                parsed["ready_for_eligibility"] = parsed2.get("ready_for_eligibility", False)

        session.conversation_history.append({"role": "user", "content": user_text})
        extracted = parsed.get("extracted") or {}
        session.accumulated_data = _merge_last_wins(session.accumulated_data, extracted)

        response_text = parsed.get("response") or "Could you tell me a bit more?"
        response_text, guardrail_violations = await self._guardrail_loop(
            session, response_text
        )

        # Escalation
        esc = self.guardrails.check_escalation(
            {
                "caller_text": user_text,
                "caller_distress": parsed.get("caller_distress"),
                "clinical_question": parsed.get("clinical_question"),
                "turn_count": session.turn_count,
                "call_duration_minutes": (
                    datetime.now(timezone.utc) - session.call_start_time
                ).total_seconds()
                / 60.0,
                "misunderstanding_count": 0,
            }
        )
        if isinstance(esc, dict) and esc.get("action") in ("ESCALATE", "WRAP_UP", "END_CALL"):
            response_text = (
                esc.get("message")
                or "I'll have a care coordinator follow up with you shortly. Thank you."
            )

        # Mid-call eligibility
        ready = bool(parsed.get("ready_for_eligibility"))
        fp = self._elig_fingerprint(session.accumulated_data)
        elapsed_min = (
            datetime.now(timezone.utc) - session.call_start_time
        ).total_seconds() / 60.0
        if ready and (not session.eligibility_checked or fp != session.last_elig_fingerprint):
            if elapsed_min >= MAX_CALL_MINUTES:
                response_text = (
                    "We've gathered a lot — a coordinator will follow up on eligibility. "
                    "Thank you for your patience."
                )
            else:
                filler_used = FILLER
                eligibility_result, response_text, more_v = await self._mid_call_eligibility(
                    session, filler_used
                )
                guardrail_violations.extend(more_v)
                session.eligibility_checked = True
                session.last_elig_fingerprint = fp
                session.eligibility_result = eligibility_result

        session.conversation_history.append({"role": "model", "content": response_text})

        # Create intake after first useful data
        if session.intake_record_id is None and session.accumulated_data:
            await self._ensure_intake(session)

        await self._redis_save(session)
        return {
            "response": response_text,
            "extracted": extracted,
            "accumulated_data": session.accumulated_data,
            "ready_for_eligibility": ready,
            "eligibility_result": eligibility_result,
            "guardrail_violations": guardrail_violations,
            "conversation_mode": session.conversation_mode,
        }

    async def _gemini_turn(self, session: CallSession, user_msg: str) -> str:
        # must-have.md #2 — tokenize known identifiers out of history + the
        # current message before they reach the LLM; rehydrate the raw
        # response afterward, backend-only, before it's parsed/used.
        prompt = session.system_prompt or load_prompt("provider_inbound")
        identifiers = _identifier_subset(session.accumulated_data)
        hist = [
            {**h, "content": tokenize(h.get("content", ""), identifiers)}
            for h in session.conversation_history
        ]
        tokenized_msg = tokenize(user_msg, identifiers)
        loop = asyncio.get_event_loop()
        task = loop.create_task(
            asyncio.to_thread(self.gemini.chat, prompt, hist, tokenized_msg)
        )
        session.pending_task = task
        try:
            raw = await task
            return rehydrate(raw, identifiers)
        except asyncio.CancelledError:
            return json.dumps(
                {
                    "response": "Go ahead, I'm listening.",
                    "extracted": {},
                    "ready_for_eligibility": False,
                }
            )
        finally:
            session.pending_task = None

    async def interrupt(self, call_sid: str) -> None:
        session = self.sessions.get(call_sid)
        if session and session.pending_task and not session.pending_task.done():
            session.pending_task.cancel()

    async def _guardrail_loop(
        self, session: CallSession, response_text: str
    ) -> tuple[str, list[Any]]:
        mode = session.conversation_mode or "provider"
        violations_all: list[Any] = []
        for _ in range(2):
            check = self.guardrails.check_outgoing_message(response_text, mode)
            if check.get("status") != "BLOCKED":
                return response_text, violations_all
            violations_all.extend(check.get("violations") or [])
            feedback = self.guardrails.format_guardrail_feedback(
                check.get("violations") or []
            )
            raw = self.gemini.chat(
                session.system_prompt or load_prompt("provider_inbound"),
                session.conversation_history,
                feedback,
            )
            parsed = _parse_json_response(raw)
            response_text = parsed.get("response") or response_text
        # fallback
        return (
            "Thank you for that information. A coordinator will follow up with you.",
            violations_all,
        )

    def _elig_fingerprint(self, data: dict[str, Any]) -> str:
        keys = ("zip_code", "payer_name", "plan_name", "icd_codes", "primary_diagnosis")
        return json.dumps({k: data.get(k) for k in keys}, sort_keys=True, default=str)

    async def _mid_call_eligibility(
        self, session: CallSession, filler: str
    ) -> tuple[dict[str, Any] | None, str, list[Any]]:
        data = session.accumulated_data
        zip_code = data.get("zip_code")
        payer = data.get("payer_name")
        if not zip_code or not payer:
            return None, filler + " We'll need zip and insurance before we can check.", []
        icds = data.get("icd_codes")
        icd = icds[0] if isinstance(icds, list) and icds else icds
        Session = get_sessionmaker()
        async with Session() as db:
            req = EligibilityCheckRequest(
                icd_code=str(icd) if icd else None,
                insurance_payer=str(payer),
                insurance_plan=data.get("plan_name"),
                zip_code=str(zip_code),
                intake_record_id=session.intake_record_id,
                persist=False,
            )
            result = await self.elig.check(db, req)
        er = {
            "decision": result.decision,
            "reasons": [r.model_dump() if hasattr(r, "model_dump") else r for r in (result.reasons or [])],
            "voice_guidance": result.voice_guidance,
            "missing_documents": result.missing_documents,
            "matched_caregivers": len(result.matched_caregivers or []),
        }
        inject = (
            f"[SYSTEM — NOT FROM CALLER] Eligibility check result: {result.decision}. "
            f"Reasons: {er['reasons']}. Missing: {er['missing_documents']}. "
            f"Matched caregivers: {er['matched_caregivers']}. "
            "Communicate this to the caller naturally."
        )
        # must-have.md #2 — same tokenize-before/rehydrate-after treatment
        # as _gemini_turn; the eligibility injection itself (decision/reasons/
        # missing docs) is operational data, not caller PHI, so it isn't tokenized.
        identifiers = _identifier_subset(session.accumulated_data)
        tokenized_hist = [
            {**h, "content": tokenize(h.get("content", ""), identifiers)}
            for h in session.conversation_history
        ]
        raw = self.gemini.chat(
            session.system_prompt or load_prompt("provider_inbound"),
            tokenized_hist + [{"role": "user", "content": inject}],
            "Please speak the eligibility result to the caller.",
        )
        raw = rehydrate(raw, identifiers)
        parsed = _parse_json_response(raw)
        text = parsed.get("response") or filler
        text, viol = await self._guardrail_loop(session, text)
        return er, text, viol

    async def _ensure_call_record(self, session: CallSession) -> None:
        if session.call_record_created or not session.conversation_mode:
            return
        mode_map = {
            "provider": CallMode.provider,
            "family": CallMode.family,
            "patient": CallMode.patient,
            "outbound_followup": CallMode.outbound_followup,
        }
        mode = mode_map.get(session.conversation_mode, CallMode.provider)
        direction = (
            CallDirection.outbound
            if session.direction == "outbound"
            else CallDirection.inbound
        )
        try:
            Session = get_sessionmaker()
            async with Session() as db:
                await self.call_svc.create(
                    db,
                    twilio_call_sid=session.call_sid,
                    direction=direction,
                    mode=mode,
                    caller_number=session.caller_number,
                    intake_record_id=session.intake_record_id,
                )
                await db.commit()
            session.call_record_created = True
        except Exception:
            logger.exception("call record create failed")

    async def _ensure_intake(self, session: CallSession) -> None:
        src = IntakeSource.inbound_call_provider
        if session.conversation_mode == "family":
            src = IntakeSource.inbound_call_family
        elif session.conversation_mode == "patient":
            src = IntakeSource.inbound_call_patient
        buckets = map_extracted_to_buckets(session.accumulated_data)
        try:
            Session = get_sessionmaker()
            async with Session() as db:
                row = await self.intake_svc.create(
                    db,
                    IntakeRecordCreate(
                        source=src,
                        patient_data=buckets.get("patient_data") or {},
                        clinical_data=buckets.get("clinical_data") or {},
                        insurance_data=buckets.get("insurance_data") or {},
                        physician_data=buckets.get("physician_data") or {},
                        care_request=buckets.get("care_request") or {},
                    ),
                )
                await db.commit()
                session.intake_record_id = row.id
            orch = get_orchestrator()
            await orch.start(source=src.value, intake_id=session.intake_record_id)
        except Exception:
            logger.exception("intake create from call failed")

    async def on_disconnect(self, call_sid: str) -> dict[str, Any]:
        session = self.sessions.pop(call_sid, None)
        if session is None:
            return {}
        transcript = "\n".join(
            f"{m['role']}: {m['content']}" for m in session.conversation_history
        )
        status = CallStatus.voicemail if session.voicemail else CallStatus.completed
        duration = int(
            (datetime.now(timezone.utc) - session.call_start_time).total_seconds()
        )
        try:
            Session = get_sessionmaker()
            async with Session() as db:
                if not session.call_record_created and session.conversation_mode:
                    await self._ensure_call_record(session)
                await self.call_svc.complete(
                    db,
                    call_sid,
                    transcript=transcript,
                    extracted_data=session.accumulated_data,
                    status=status,
                    duration_seconds=duration,
                )
                if session.intake_record_id:
                    buckets = map_extracted_to_buckets(session.accumulated_data)
                    await self.intake_svc.update_data(
                        db,
                        session.intake_record_id,
                        IntakeRecordUpdate(
                            patient_data=buckets.get("patient_data") or None,
                            clinical_data=buckets.get("clinical_data") or None,
                            insurance_data=buckets.get("insurance_data") or None,
                            physician_data=buckets.get("physician_data") or None,
                            care_request=buckets.get("care_request") or None,
                        ),
                    )
                    phone = session.caller_number or session.accumulated_data.get(
                        "patient_phone"
                    )
                    if phone:
                        await self.follow_svc.create(
                            db,
                            FollowUpActionCreate(
                                intake_record_id=session.intake_record_id,
                                type=FollowUpType.sms_sent,
                                target_phone=str(phone),
                                message=(
                                    "Thank you for calling ABC Home Health. "
                                    "A coordinator may follow up."
                                ),
                                scheduled_at=datetime.now(timezone.utc),
                            ),
                        )
                await db.commit()
        except Exception:
            logger.exception("disconnect persistence failed")

        if session.intake_record_id:
            try:
                orch = get_orchestrator()
                await orch.resume(
                    session.intake_record_id,
                    event="call_ended",
                    incoming_data=session.accumulated_data,
                    incoming_source="voice",
                )
            except Exception:
                logger.exception("orchestrator resume on disconnect failed")

        try:
            redis = get_redis()
            await redis.delete(f"call:{call_sid}")
        except Exception:
            pass

        return {
            "answered": not session.voicemail,
            "voicemail": session.voicemail,
            "extracted": session.accumulated_data,
            "gaps_remaining": [],
            "call_status": status.value,
            "intake_record_id": str(session.intake_record_id)
            if session.intake_record_id
            else None,
        }

    async def _redis_save(self, session: CallSession) -> None:
        try:
            redis = get_redis()
            payload = {
                "call_sid": session.call_sid,
                "mode": session.conversation_mode,
                "direction": session.direction,
                "caller_number": session.caller_number,
                "started_at": session.call_start_time.isoformat(),
                "turn_count": session.turn_count,
                "intake_record_id": str(session.intake_record_id)
                if session.intake_record_id
                else None,
                "accumulated_data": session.accumulated_data,
                "eligibility_result": session.eligibility_result,
                "last_turns": session.conversation_history[-3:],
            }
            await redis.set(
                f"call:{session.call_sid}",
                json.dumps(payload, default=str),
                ex=CALL_REDIS_TTL,
            )
        except Exception:
            logger.debug("redis call state save skipped", exc_info=True)


_voice_agent: VoiceAgent | None = None


def get_voice_agent() -> VoiceAgent:
    global _voice_agent
    if _voice_agent is None:
        _voice_agent = VoiceAgent()
    return _voice_agent
