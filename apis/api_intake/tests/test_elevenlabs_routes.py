"""Tests for the ElevenLabs Custom LLM voice transport (feature 40) and
webhook signature validation (feature 76).

Mirrors the ConversationRelay scenarios in test_twilio_routes.py over the
OpenAI-compatible HTTP contract.
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routes.elevenlabs import SESSIONS, verify_elevenlabs_signature
from app.safety.consent import CONSENT_DISCLOSURE
from app.safety.handoff import HANDOFF_FALLBACK_MESSAGE
from app.safety.safe_response import BANNED_PHRASES

client = TestClient(app)

SERVED_ZIP = "11201"
TOKEN = "test-custom-llm-token"
WEBHOOK_SECRET = "test-webhook-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configured_settings():
    get_settings.cache_clear()
    settings = get_settings()
    object.__setattr__(settings, "elevenlabs_custom_llm_token", TOKEN)
    object.__setattr__(settings, "elevenlabs_webhook_secret", WEBHOOK_SECRET)
    SESSIONS.clear()
    yield
    SESSIONS.clear()
    get_settings.cache_clear()


def _body(conv_id: str, text: str, *, stream: bool = False, use_user_field: bool = False) -> dict:
    body: dict = {
        "model": "gpt-4o",
        "messages": [
            {"role": "assistant", "content": CONSENT_DISCLOSURE},
            {"role": "user", "content": text},
        ],
    }
    if stream:
        body["stream"] = True
    if use_user_field:
        body["user"] = conv_id
    else:
        body["elevenlabs_extra_body"] = {"conversation_id": conv_id}
    return body


def turn(conv_id: str, text: str) -> str:
    response = client.post(
        "/elevenlabs/custom-llm/v1/chat/completions",
        json=_body(conv_id, text),
        headers=AUTH,
    )
    assert response.status_code == 200
    return response.json()["choices"][0]["message"]["content"]


def _signed_headers(payload: bytes, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> dict:
    ts = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"ElevenLabs-Signature": f"t={ts},v0={digest}", "Content-Type": "application/json"}


class TestCustomLlmAuth:
    def test_rejects_missing_bearer(self):
        response = client.post(
            "/elevenlabs/custom-llm/v1/chat/completions", json=_body("c1", "yes")
        )
        assert response.status_code == 403

    def test_rejects_wrong_bearer(self):
        response = client.post(
            "/elevenlabs/custom-llm/v1/chat/completions",
            json=_body("c1", "yes"),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 403

    def test_rejects_missing_conversation_id(self):
        body = _body("c1", "yes")
        del body["elevenlabs_extra_body"]
        response = client.post(
            "/elevenlabs/custom-llm/v1/chat/completions", json=body, headers=AUTH
        )
        assert response.status_code == 400


class TestConsentGate:
    def test_first_turn_consent_yes_then_greeting(self):
        reply = turn("consent-yes", "Yes, go ahead.")
        assert "How can I help you today" in reply

    def test_consent_no_triggers_handoff_and_session_removed(self):
        reply = turn("consent-no", "No, I do not consent.")
        assert HANDOFF_FALLBACK_MESSAGE in reply
        assert "consent-no" not in SESSIONS

    def test_consent_ambiguous_repeats_disclosure(self):
        reply = turn("consent-ambiguous", "what is this about")
        assert reply == CONSENT_DISCLOSURE

    def test_no_data_collection_before_consent(self):
        conv = "no-collect"
        turn(conv, f"Referral for zip {SERVED_ZIP}, Medicare Part A, nursing")
        assert SESSIONS[conv].patient_zip is None


class TestProviderFlow:
    def test_provider_flow_reaches_decision(self):
        conv = "provider-happy"
        turn(conv, "Yes, go ahead.")
        reply = turn(
            conv,
            "This is the discharge planner at Brooklyn Methodist. Referral: "
            f"zip {SERVED_ZIP}, insurance Medicare Part A, needs skilled nursing.",
        )
        assert "accept" in reply.lower() or "coordinator" in reply.lower()

    def test_repeated_confusion_triggers_handoff(self):
        conv = "confused"
        turn(conv, "yes")
        turn(conv, "mumble mumble")
        turn(conv, "static noise")
        turn(conv, "cough")
        reply = turn(conv, "more static")
        assert HANDOFF_FALLBACK_MESSAGE in reply
        assert conv not in SESSIONS

    def test_banned_phrases_never_in_output(self):
        conv = "banned-check"
        replies = [
            turn(conv, "yes"),
            turn(conv, f"zip {SERVED_ZIP} Medicare Part A skilled nursing"),
        ]
        for reply in replies:
            lowered = reply.lower()
            for phrase in BANNED_PHRASES:
                assert phrase.lower() not in lowered

    def test_conversation_id_from_user_field_fallback(self):
        response = client.post(
            "/elevenlabs/custom-llm/v1/chat/completions",
            json=_body("user-field-conv", "yes", use_user_field=True),
            headers=AUTH,
        )
        assert response.status_code == 200
        assert "user-field-conv" in SESSIONS


class TestStreaming:
    def test_streaming_true_returns_sse_single_chunk(self):
        response = client.post(
            "/elevenlabs/custom-llm/v1/chat/completions",
            json=_body("stream-conv", "yes", stream=True),
            headers=AUTH,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [l for l in response.text.split("\n") if l.startswith("data: ")]
        assert lines[-1] == "data: [DONE]"
        first_chunk = json.loads(lines[0].removeprefix("data: "))
        assert "How can I help you today" in first_chunk["choices"][0]["delta"]["content"]
        finish_chunk = json.loads(lines[1].removeprefix("data: "))
        assert finish_chunk["choices"][0]["finish_reason"] == "stop"


class TestPostCallWebhook:
    def test_valid_hmac_accepted(self):
        payload = json.dumps({"type": "post_call_transcription"}).encode()
        response = client.post(
            "/elevenlabs/webhooks/post-call", content=payload, headers=_signed_headers(payload)
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_invalid_hmac_rejected_403(self):
        payload = b'{"type": "post_call_transcription"}'
        response = client.post(
            "/elevenlabs/webhooks/post-call",
            content=payload,
            headers=_signed_headers(payload, secret="attacker-secret"),
        )
        assert response.status_code == 403

    def test_missing_signature_rejected_403(self):
        response = client.post("/elevenlabs/webhooks/post-call", content=b"{}")
        assert response.status_code == 403

    def test_stale_timestamp_rejected(self):
        payload = b"{}"
        stale = int(time.time()) - 60 * 60
        headers = _signed_headers(payload, timestamp=stale)
        response = client.post("/elevenlabs/webhooks/post-call", content=payload, headers=headers)
        assert response.status_code == 403

    def test_verify_signature_helper_rejects_malformed_header(self):
        assert verify_elevenlabs_signature(b"{}", "garbage", WEBHOOK_SECRET) is False
        assert verify_elevenlabs_signature(b"{}", "t=abc,v0=def", WEBHOOK_SECRET) is False
