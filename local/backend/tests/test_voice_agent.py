"""Phase 5 voice agent + text-mode tests with FakeGemini."""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from backend.agents.voice_agent import VoiceAgent, _merge_last_wins, _parse_json_response
from backend.main import app
from backend.services.gemini_client import FakeGeminiClient
from backend.services.guardrail_service import GuardrailService


class TestVoiceHelpers(unittest.TestCase):
    def test_parse_json(self) -> None:
        raw = 'Here you go: {"response": "Hi", "extracted": {"zip_code": "11201"}}'
        p = _parse_json_response(raw)
        self.assertEqual(p["response"], "Hi")
        self.assertEqual(p["extracted"]["zip_code"], "11201")

    def test_parse_plain(self) -> None:
        p = _parse_json_response("Just talking")
        self.assertIn("Just talking", p["response"])

    def test_merge_last_wins(self) -> None:
        out = _merge_last_wins({"a": "1", "b": "2"}, {"b": "3", "c": None})
        self.assertEqual(out, {"a": "1", "b": "3"})

    def test_guardrail_prefix(self) -> None:
        fb = GuardrailService().format_guardrail_feedback(
            [{"reason": "promise", "name": "guarantee"}]
        )
        self.assertTrue(fb.startswith("[GUARDRAIL — NOT FROM CALLER]"))


class TestVoiceAgentTurns(unittest.TestCase):
    def test_identify_and_accumulate(self) -> None:
        scripted = [
            json.dumps(
                {
                    "response": "Thanks, I'll take this referral.",
                    "caller_type": "provider",
                    "extracted": {"patient_name": "Maria Johnson"},
                    "ready_for_eligibility": False,
                }
            ),
            json.dumps(
                {
                    "response": "Got the zip and insurance.",
                    "extracted": {
                        "zip_code": "11201",
                        "payer_name": "Medicare",
                        "icd_codes": ["Z96.641"],
                    },
                    "ready_for_eligibility": False,
                }
            ),
        ]
        agent = VoiceAgent(gemini=FakeGeminiClient(scripted))
        # Avoid DB in unit test — monkeypatch ensure methods
        async def _noop(*_a, **_k):
            return None

        agent._ensure_call_record = _noop  # type: ignore
        agent._ensure_intake = _noop  # type: ignore
        agent._redis_save = _noop  # type: ignore

        import asyncio

        async def run() -> None:
            await agent.on_setup({"callSid": "CA_test1", "from": "+15551212"})
            # must-have.md #4 — consent gather is the literal first turn now;
            # it's deterministic keyword matching, not a Gemini call, so it
            # doesn't consume a scripted response.
            consent_reply = await agent.handle_turn("CA_test1", "yes that's fine")
            self.assertIsNone(consent_reply["conversation_mode"])
            r1 = await agent.handle_turn("CA_test1", "I'm a discharge planner")
            self.assertEqual(r1["conversation_mode"], "provider")
            r2 = await agent.handle_turn(
                "CA_test1", "Patient Maria Johnson zip 11201 Medicare Z96.641"
            )
            self.assertIn("zip_code", r2["accumulated_data"])

        asyncio.run(run())


class TestVoiceTextModeAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cm = TestClient(app)
        cls.client = cls._cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cm.__exit__(None, None, None)

    def test_text_mode_shape(self) -> None:
        import backend.agents.voice_agent as va_mod
        from backend.agents.voice_agent import VoiceAgent

        fake = FakeGeminiClient(
            [
                json.dumps(
                    {
                        "response": "Hello, how can I help?",
                        "caller_type": "family",
                        "extracted": {},
                        "ready_for_eligibility": False,
                    }
                )
            ]
        )
        agent = VoiceAgent(gemini=fake)

        async def _noop(*_a, **_k):
            return None

        agent._ensure_call_record = _noop  # type: ignore
        agent._ensure_intake = _noop  # type: ignore
        agent._redis_save = _noop  # type: ignore
        va_mod._voice_agent = agent

        r = self.client.post(
            "/voice/test",
            json={"session_id": "text-sess-1", "message": "Calling about my mom"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in (
            "session_id",
            "response",
            "extracted",
            "accumulated_data",
            "ready_for_eligibility",
            "guardrail_violations",
            "conversation_mode",
        ):
            self.assertIn(key, body)
        self.assertNotIn("reply", body)


if __name__ == "__main__":
    unittest.main()
