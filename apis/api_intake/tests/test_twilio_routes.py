"""Tests for the Twilio voice webhook and ConversationRelay WebSocket flow."""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.safety.consent import CONSENT_DISCLOSURE
from app.safety.handoff import HANDOFF_FALLBACK_MESSAGE

client = TestClient(app)

SERVED_ZIP = "11201"


def _override_public_base_url(value: str):
    get_settings.cache_clear()
    settings = get_settings()
    object.__setattr__(settings, "public_base_url", value)
    return settings


def _setup(ws, call_sid: str = "CA-test-001") -> dict:
    ws.send_json({"type": "setup", "callSid": call_sid})
    return ws.receive_json()


def _say(ws, utterance: str) -> dict:
    ws.send_json({"type": "prompt", "voicePrompt": utterance})
    return ws.receive_json()


class TestVoiceWebhook:
    def test_returns_conversation_relay_twiml_when_configured(self):
        _override_public_base_url("https://demo.ngrok.app")
        response = client.post("/twilio/voice")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        assert "<ConversationRelay" in response.text
        assert "wss://demo.ngrok.app/twilio/conversation-relay" in response.text
        get_settings.cache_clear()

    def test_degrades_gracefully_without_public_url(self):
        _override_public_base_url("")
        response = client.post("/twilio/voice")
        assert response.status_code == 200
        assert "<Hangup/>" in response.text
        assert "<ConversationRelay" not in response.text
        get_settings.cache_clear()


class TestConversationRelayFlow:
    def test_consent_is_the_first_message(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            first = _setup(ws)
            assert first["type"] == "text"
            assert first["token"] == CONSENT_DISCLOSURE

    def test_consent_no_routes_to_handoff_and_ends_call(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            reply = _say(ws, "No, I do not consent.")
            assert reply["token"] == HANDOFF_FALLBACK_MESSAGE
            assert ws.receive_json() == {"type": "end"}

    def test_no_data_collection_before_consent(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            # Caller blurts referral data without answering the consent question.
            reply = _say(ws, f"Referral for zip {SERVED_ZIP}, Medicare Part A, nursing")
            # The agent must re-ask for consent, not proceed.
            assert reply["token"] == CONSENT_DISCLOSURE

    def test_full_provider_flow_reaches_deterministic_accept(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            greeting = _say(ws, "Yes, go ahead.")
            assert "help" in greeting["token"].lower()

            reply = _say(
                ws,
                f"Patient in zip {SERVED_ZIP}, Medicare Part A, needs skilled nursing.",
            )
            text = reply["token"]
            assert "we can take this referral" in text.lower()
            assert "face-to-face encounter note" in text.lower()
            assert "coordinator" in text.lower()

    def test_interrupt_message_is_accepted_and_flow_continues(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            _say(ws, "yes")
            # ConversationRelay interrupt: caller talked over TTS. Must be
            # tolerated without crashing or emitting a response.
            ws.send_json({"type": "interrupt", "utteranceUntilInterrupt": "Good news"})
            reply = _say(ws, f"zip {SERVED_ZIP} Medicare Part A skilled nursing")
            assert "we can take this referral" in reply["token"].lower()

    def test_banned_phrases_never_reach_tts(self):
        # The ACCEPT wording is filtered by SafeResponse: even if a draft said
        # "guarantee", it cannot pass. Verify the spoken accept has none.
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            _say(ws, "yes")
            reply = _say(ws, f"zip {SERVED_ZIP} Medicare Part A skilled nursing")
            lowered = reply["token"].lower()
            for banned in ("guarantee", "100%", "definitely will", "for sure"):
                assert banned not in lowered

    def test_unintelligible_turns_degrade_to_handoff(self):
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _setup(ws)
            _say(ws, "yes")
            # Three consecutive turns with zero extractable data.
            _say(ws, "mumble mumble")
            _say(ws, "static noise")
            _say(ws, "cough")
            reply = _say(ws, "more noise")
            assert reply["token"] == HANDOFF_FALLBACK_MESSAGE
            assert ws.receive_json() == {"type": "end"}
