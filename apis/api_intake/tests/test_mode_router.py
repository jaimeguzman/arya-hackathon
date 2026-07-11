"""Tests for caller-type detection routing (feature: WORKFLOW Path A Step 3)."""

import pytest
from fastapi.testclient import TestClient

from app.agents import mode_router
from app.agents.mode_router import (
    INBOUND_MODES,
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

    def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value.encode()

    def hget(self, key: str, field: str) -> bytes | None:
        return self.hashes.get(key, {}).get(field)


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
