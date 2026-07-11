"""Tests for caller-type detection routing (feature: WORKFLOW Path A Step 3)."""

import pytest
from fastapi.testclient import TestClient

from app.agents import mode_router
from app.agents.mode_router import (
    CAUTIOUS_DEFAULT_MODE,
    INBOUND_MODES,
    MODE_CLARIFYING_QUESTION,
    MODE_CONFIDENCE_THRESHOLD,
    CallerMode,
    CallModeStore,
    classify_utterance,
    detect_caller_mode,
    load_mode_prompt,
)
from app.main import app
from app.routes import twilio as twilio_routes
from app.safety.consent import CallRecord, ConsentRequiredError

client = TestClient(app)


class FakeRedisClient:
    """Minimal Redis hash-command double (bytes-returning, like redis-py)."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.lists: dict[str, list[bytes]] = {}

    def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value.encode()

    def hget(self, key: str, field: str) -> bytes | None:
        return self.hashes.get(key, {}).get(field)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value.encode())

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]


class TestClassification:
    @pytest.mark.parametrize(
        ("utterance", "expected"),
        [
            ("Hi, I'm the discharge planner at Mercy General.", CallerMode.PROVIDER),
            ("We have a patient ready for discharge, I have a referral.", CallerMode.PROVIDER),
            ("I'm calling because my mother just got out of surgery.", CallerMode.FAMILY),
            ("I'm his daughter and he needs help at home.", CallerMode.FAMILY),
            ("I need care for myself after my hip replacement.", CallerMode.PATIENT),
            ("My doctor said I should look into home nursing.", CallerMode.PATIENT),
        ],
    )
    def test_representative_utterances_map_to_the_correct_mode(self, utterance, expected):
        classification = classify_utterance(utterance)
        assert classification.mode == expected
        assert classification.confidence > 0
        assert classification.matched_phrases

    def test_unrecognizable_utterance_yields_no_mode(self):
        classification = classify_utterance("mumble mumble static")
        assert classification.mode is None
        assert classification.confidence == 0.0

    def test_inbound_classification_never_returns_outbound(self):
        # No phrase evidence exists for OUTBOUND at all — exhaustive check.
        assert CallerMode.OUTBOUND not in mode_router._MODE_PHRASES
        assert CallerMode.OUTBOUND not in INBOUND_MODES
        for phrases in mode_router._MODE_PHRASES.values():
            for phrase in phrases:
                assert classify_utterance(phrase).mode in INBOUND_MODES | {None}


class TestConsentGate:
    def test_detection_refuses_to_run_without_consent(self):
        call = CallRecord(call_sid="CA-mode-1", consent_given=False)
        with pytest.raises(ConsentRequiredError):
            detect_caller_mode(call, "I'm the discharge planner")

    def test_detection_runs_after_consent(self):
        call = CallRecord(call_sid="CA-mode-1", consent_given=True)
        assert detect_caller_mode(call, "I'm the discharge planner").mode == CallerMode.PROVIDER


class TestPromptSelection:
    @pytest.mark.parametrize("mode", [CallerMode.PROVIDER, CallerMode.FAMILY, CallerMode.PATIENT])
    def test_each_inbound_mode_loads_a_nonempty_system_prompt(self, mode):
        prompt = load_mode_prompt(mode)
        assert "System prompt" in prompt
        assert "never" in prompt.lower()  # guardrails restated in every prompt

    def test_provider_and_family_prompts_differ(self):
        assert load_mode_prompt(CallerMode.PROVIDER) != load_mode_prompt(CallerMode.FAMILY)


class TestModeStore:
    def test_mode_round_trips_through_redis_hash(self):
        store = CallModeStore(FakeRedisClient())
        store.set_mode("CA-1", CallerMode.FAMILY)
        assert store.get_mode("CA-1") == CallerMode.FAMILY

    def test_missing_call_has_no_mode(self):
        assert CallModeStore(FakeRedisClient()).get_mode("CA-none") is None


class TestCallFlowRouting:
    """End-to-end over the ConversationRelay WebSocket."""

    @pytest.fixture()
    def fake_store(self, monkeypatch):
        store = CallModeStore(FakeRedisClient())
        monkeypatch.setattr(twilio_routes, "get_mode_store", lambda: store)
        return store

    def _start(self, ws, call_sid: str) -> None:
        ws.send_json({"type": "setup", "callSid": call_sid})
        ws.receive_json()

    def _say(self, ws, utterance: str) -> dict:
        ws.send_json({"type": "prompt", "voicePrompt": utterance})
        return ws.receive_json()

    def test_no_classification_before_consent(self, fake_store):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            self._start(ws, "CA-preconsent")
            # Caller self-identifies before answering the consent question.
            self._say(ws, "I'm the discharge planner at Mercy, I have a referral")
            assert fake_store.get_mode("CA-preconsent") is None

    @pytest.mark.parametrize(
        ("utterance", "expected"),
        [
            ("I'm the discharge planner calling with a referral.", CallerMode.PROVIDER),
            ("I'm his daughter, my father needs help.", CallerMode.FAMILY),
            ("I need care for myself.", CallerMode.PATIENT),
        ],
    )
    def test_self_identification_after_consent_persists_mode(
        self, fake_store, utterance, expected
    ):
        call_sid = f"CA-{expected.value}"
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            self._start(ws, call_sid)
            self._say(ws, "yes")
            self._say(ws, utterance)
            assert fake_store.get_mode(call_sid) == expected


AMBIGUOUS_UTTERANCE = "Hello, I'd like some information please."
# PROVIDER wins 2 phrases to FAMILY's 1 -> confidence 2/3, below threshold.
LOW_CONFIDENCE_UTTERANCE = "I'm a nurse, we have a patient — well, my mother."


class TestAmbiguousDetection:
    """Feature: ambiguous / low-confidence caller-type handling (unit level)."""

    @pytest.fixture(autouse=True)
    def no_store(self, monkeypatch):
        monkeypatch.setattr(twilio_routes, "get_mode_store", lambda: None)

    def _session(self) -> twilio_routes.CallSession:
        session = twilio_routes.CallSession("CA-ambiguous")
        session.record = session.record.model_copy(update={"consent_given": True})
        return session

    def test_ambiguous_opening_asks_one_neutral_clarifying_question(self):
        session = self._session()
        question = twilio_routes._assign_mode(session, AMBIGUOUS_UTTERANCE)
        assert question == MODE_CLARIFYING_QUESTION
        assert session.mode is None  # no guessing
        assert session.clarification_attempts == 1
        assert session.record.mode_confidence == 0.0

    def test_still_unresolved_after_clarification_gets_cautious_default(self):
        session = self._session()
        twilio_routes._assign_mode(session, AMBIGUOUS_UTTERANCE)
        question = twilio_routes._assign_mode(session, AMBIGUOUS_UTTERANCE)
        assert question is None  # only ONE clarifying question is ever asked
        assert session.mode == CAUTIOUS_DEFAULT_MODE == CallerMode.FAMILY
        # Only the clarifying-question turn incremented here; zero-progress
        # turns are counted once per turn by the intake turn itself.
        assert session.clarification_attempts == 1

    def test_low_confidence_match_keeps_cautious_default_not_classified_mode(self):
        classification = classify_utterance(LOW_CONFIDENCE_UTTERANCE)
        assert classification.mode == CallerMode.PROVIDER
        assert 0 < classification.confidence < MODE_CONFIDENCE_THRESHOLD
        session = self._session()
        twilio_routes._assign_mode(session, LOW_CONFIDENCE_UTTERANCE)
        assert session.mode == CAUTIOUS_DEFAULT_MODE
        assert session.record.mode_confidence == classification.confidence

    def test_confident_match_records_confidence_and_assigns_mode(self):
        session = self._session()
        question = twilio_routes._assign_mode(
            session, "I'm the discharge planner with a referral for a patient."
        )
        assert question is None
        assert session.mode == CallerMode.PROVIDER
        assert session.clarification_attempts == 0
        assert session.record.mode_confidence == 1.0

    def test_clarifying_answer_resolves_to_the_stated_mode(self):
        session = self._session()
        twilio_routes._assign_mode(session, AMBIGUOUS_UTTERANCE)
        twilio_routes._assign_mode(session, "I'm his daughter, calling about my father.")
        assert session.mode == CallerMode.FAMILY
        assert session.record.mode_confidence == 1.0


class TestAmbiguousCallFlow:
    """Feature: ambiguous handling end-to-end over the WebSocket."""

    @pytest.fixture()
    def fake_store(self, monkeypatch):
        store = CallModeStore(FakeRedisClient())
        monkeypatch.setattr(twilio_routes, "get_mode_store", lambda: store)
        return store

    def _consented(self, ws, call_sid: str) -> None:
        ws.send_json({"type": "setup", "callSid": call_sid})
        ws.receive_json()
        ws.send_json({"type": "prompt", "voicePrompt": "yes"})
        ws.receive_json()

    def _say(self, ws, utterance: str) -> dict:
        ws.send_json({"type": "prompt", "voicePrompt": utterance})
        return ws.receive_json()

    def test_ambiguous_flow_clarifies_then_defaults_then_hands_off(self, fake_store):
        call_sid = "CA-amb-flow"
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            self._consented(ws, call_sid)
            # Turn 1: ambiguous -> one neutral clarifying question, no mode.
            reply = self._say(ws, AMBIGUOUS_UTTERANCE)
            assert MODE_CLARIFYING_QUESTION in reply["token"]
            assert fake_store.get_mode(call_sid) is None
            # Turn 2: still ambiguous -> cautious Family default persisted.
            reply = self._say(ws, AMBIGUOUS_UTTERANCE)
            assert MODE_CLARIFYING_QUESTION not in reply["token"]
            assert fake_store.get_mode(call_sid) == CAUTIOUS_DEFAULT_MODE
            # Turns 3-4: zero-progress turns keep incrementing
            # clarification_attempts until the human handoff path fires
            # (guarantee 6 — never a silent drop).
            self._say(ws, AMBIGUOUS_UTTERANCE)
            reply = self._say(ws, AMBIGUOUS_UTTERANCE)
            assert reply["token"]  # spoken fallback, not silence
            assert ws.receive_json() == {"type": "end"}


PROVIDER_UTTERANCE = "Actually, I'm the discharge planner and I have a referral."


class TestMidCallModeSwitch:
    """Feature 44: mid-call mode switch when the caller type becomes clearer."""

    @pytest.fixture()
    def fake_store(self, monkeypatch):
        store = CallModeStore(FakeRedisClient())
        monkeypatch.setattr(twilio_routes, "get_mode_store", lambda: store)
        return store

    def _family_session(self, turn: int = 1) -> twilio_routes.CallSession:
        session = twilio_routes.CallSession("CA-switch")
        session.record = session.record.model_copy(update={"consent_given": True})
        session.turn_count = turn
        twilio_routes._set_mode(session, CallerMode.FAMILY)
        return session

    def test_confident_later_turn_switches_mode_and_prompt(self, fake_store):
        session = self._family_session(turn=3)
        family_prompt = session.mode_prompt
        twilio_routes._maybe_switch_mode(session, PROVIDER_UTTERANCE)
        assert session.mode == CallerMode.PROVIDER
        assert session.mode_prompt == load_mode_prompt(CallerMode.PROVIDER)
        assert session.mode_prompt != family_prompt
        assert fake_store.get_mode("CA-switch") == CallerMode.PROVIDER

    def test_switch_preserves_collected_fields(self, fake_store):
        session = self._family_session()
        session.patient_zip = "60601"
        session.insurance_plan = "Medicare"
        session.service_type = "skilled_nursing"
        twilio_routes._maybe_switch_mode(session, PROVIDER_UTTERANCE)
        assert session.mode == CallerMode.PROVIDER
        assert session.patient_zip == "60601"
        assert session.insurance_plan == "Medicare"
        assert session.service_type == "skilled_nursing"

    def test_transition_logged_with_old_new_and_turn(self, fake_store):
        session = self._family_session(turn=2)
        twilio_routes._maybe_switch_mode(session, PROVIDER_UTTERANCE)
        assert len(session.mode_transitions) == 1
        transition = session.mode_transitions[0]
        assert transition.old_mode == CallerMode.FAMILY
        assert transition.new_mode == CallerMode.PROVIDER
        assert transition.turn == 2
        assert fake_store.get_transitions("CA-switch") == [transition]

    def test_low_confidence_or_same_mode_does_not_switch(self, fake_store):
        session = self._family_session()
        twilio_routes._maybe_switch_mode(session, LOW_CONFIDENCE_UTTERANCE)
        assert session.mode == CallerMode.FAMILY
        assert session.mode_transitions == []
        twilio_routes._maybe_switch_mode(session, "It's for my mother.")
        assert session.mode == CallerMode.FAMILY
        assert session.mode_transitions == []
        assert fake_store.get_transitions("CA-switch") == []

    def test_ws_family_to_provider_switch_keeps_fields_and_gates(self, fake_store):
        """Full flow: family opening, then a provider reveal — fields kept,
        transition persisted, and the reply still comes through the safety
        boundary (spoken text, no silent drop)."""
        call_sid = "CA-ws-switch"
        flow = TestAmbiguousCallFlow()
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            flow._consented(ws, call_sid)
            flow._say(ws, "I'm his daughter, my father needs help. Zip is 60601.")
            assert fake_store.get_mode(call_sid) == CallerMode.FAMILY
            reply = flow._say(
                ws, "Actually I'm the discharge planner and I have a referral."
            )
            assert reply["token"]  # gated spoken reply, never silence
            assert fake_store.get_mode(call_sid) == CallerMode.PROVIDER
            transitions = fake_store.get_transitions(call_sid)
            assert len(transitions) == 1
            assert transitions[0].old_mode == CallerMode.FAMILY
            assert transitions[0].new_mode == CallerMode.PROVIDER
            assert transitions[0].turn == 2
