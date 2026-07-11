"""Provider mode: clinical structured intake with real-time mid-call
eligibility (feature 45)."""

import pytest
from fastapi.testclient import TestClient

from app.agents.eligibility_agent import EligibilityDecision
from app.agents.provider_intake import (
    PROVIDER_FIELD_QUESTIONS,
    build_eligibility_request,
    extract_diagnosis,
    extract_dob,
    extract_patient_name,
    service_for_diagnosis,
)
from app.main import app
from app.routes import twilio as twilio_routes
from app.safety.safe_response import BANNED_PHRASES

client = TestClient(app)

PROVIDER_OPENING = (
    "Hi, I'm the discharge planner at Mercy General, I have a referral for a patient."
)


def _start(ws, call_sid: str) -> None:
    ws.send_json({"type": "setup", "callSid": call_sid})
    ws.receive_json()


def _say(ws, utterance: str) -> str:
    ws.send_json({"type": "prompt", "voicePrompt": utterance})
    return ws.receive_json()["token"]


def _consented_provider_call(ws, call_sid: str) -> str:
    """Setup -> consent yes -> provider self-identification. Returns the reply."""
    _start(ws, call_sid)
    _say(ws, "yes")
    return _say(ws, PROVIDER_OPENING)


class TestExtraction:
    def test_patient_name_extracted_from_spoken_phrases(self):
        assert extract_patient_name("The patient's name is Jane Doe") == "Jane Doe"
        assert extract_patient_name("This is a referral for John Smith") == "John Smith"
        assert extract_patient_name("What a lovely day") is None

    def test_dob_extracted_in_numeric_and_month_name_forms(self):
        assert extract_dob("date of birth is 03/12/1950") == "03/12/1950"
        assert extract_dob("she was born 1950-03-12") == "1950-03-12"
        assert extract_dob("born on March 12, 1950") == "March 12, 1950"
        assert extract_dob("no date here") is None

    def test_diagnosis_extracted_as_code_or_spoken_description(self):
        assert extract_diagnosis("the diagnosis is I50.9") == "I50.9"
        assert extract_diagnosis("she has congestive heart failure") == "I50.9"
        assert extract_diagnosis("nothing clinical here") is None

    def test_diagnosis_maps_to_a_service_type(self):
        assert service_for_diagnosis("I50.9") == "skilled_nursing"
        assert service_for_diagnosis("Z99.99") is None


class TestTokenizationBoundary:
    def test_eligibility_request_carries_no_identifier_fields(self):
        """Feature 45 step 6: only tokenized structured fields reach the loop."""
        request = build_eligibility_request(
            patient_zip="11201",
            insurance_plan="Humana Gold Plus HMO",
            service_type=None,
            diagnosis_code="I50.9",
        )
        dumped = request.model_dump()
        assert "name" not in str(sorted(dumped)).lower()
        assert "dob" not in dumped and "patient_name" not in dumped
        assert dumped["patient_zip"] == "11201"
        assert dumped["service_type"] == "skilled_nursing"

    def test_build_request_rejects_identifier_kwargs(self):
        with pytest.raises(TypeError):
            build_eligibility_request(
                patient_zip="11201",
                insurance_plan="Humana Gold Plus HMO",
                service_type=None,
                diagnosis_code="I50.9",
                patient_name="Jane Doe",
            )


class TestStructuredFlow:
    def test_provider_mode_asks_fields_in_clinical_order(self):
        """Feature 45 step 1: name -> DOB -> diagnosis -> insurance -> zip."""
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _consented_provider_call(ws, "CA-f45-order")
            reply = _say(ws, "sure, go ahead")  # zero-progress turn
            assert "name" in reply.lower()
            reply = _say(ws, "The patient's name is Jane Doe")
            assert "birth" in reply.lower()
            reply = _say(ws, "date of birth is 03/12/1950")
            assert "diagnosis" in reply.lower()
            reply = _say(ws, "the diagnosis is I50.9, congestive heart failure")
            assert "insurance" in reply.lower()
            reply = _say(ws, "she has Humana Gold Plus HMO")
            assert "zip" in reply.lower()

    def test_fields_accumulate_and_decision_arrives_mid_call(self, monkeypatch):
        """Feature 45 steps 2, 8, 9: state accumulates across turns and the
        eligibility result shapes the utterance the moment fields complete."""
        captured = {}
        real_decide = twilio_routes.decide

        def capturing_decide(request):
            captured["request"] = request
            return real_decide(request)

        monkeypatch.setattr(twilio_routes, "decide", capturing_decide)
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _consented_provider_call(ws, "CA-f45-accumulate")
            _say(ws, "The patient's name is Jane Doe")
            _say(ws, "born 03/12/1950")
            _say(ws, "she has congestive heart failure")
            _say(ws, "insurance is Humana Gold Plus HMO")
            reply = _say(ws, "zip code is 11201")
        # Real-time ACCEPT before hangup, shaped by the decision.
        assert "we can take this referral" in reply.lower()
        # Feature 45 step 3: ACCEPT with an F2F requirement asks for the note.
        assert "face-to-face encounter note" in reply.lower()
        # The request the agent saw held every accumulated structured field —
        # and nothing else (no identifiers).
        request = captured["request"].model_dump()
        assert request["patient_zip"] == "11201"
        assert request["insurance_plan"] == "Humana Gold Plus HMO"
        assert request["service_type"] == "skilled_nursing"
        assert "Jane" not in str(request.values())
        assert "03/12/1950" not in str(request.values())

    def test_decline_is_spoken_honestly_and_immediately(self):
        """Feature 45 step 4: out-of-area zip -> immediate honest DECLINE."""
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _consented_provider_call(ws, "CA-f45-decline")
            reply = _say(
                ws,
                "Referral for John Smith, born 01/01/1945, heart failure, "
                "Humana Gold Plus HMO, zip 90210",
            )
        assert "not able to take this referral" in reply.lower()
        assert "zip not served" in reply.lower()

    def test_needs_more_info_asks_for_the_specific_missing_fields(self, monkeypatch):
        """Feature 45 step 5: NEEDS_MORE_INFO names what is missing."""
        monkeypatch.setattr(
            twilio_routes,
            "decide",
            lambda request: EligibilityDecision(
                status="NEEDS_MORE_INFO",
                reasons=["insurance plan could not be verified"],
            ),
        )
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            _consented_provider_call(ws, "CA-f45-nmi")
            reply = _say(
                ws,
                "Referral for John Smith, born 01/01/1945, heart failure, "
                "Humana Gold Plus HMO, zip 11201",
            )
        assert "more information" in reply.lower()
        assert "insurance plan could not be verified" in reply.lower()

    def test_every_provider_utterance_passes_the_banned_phrase_filter(self):
        """Feature 45 step 7: no reply ever contains a banned phrase."""
        replies = []
        with client.websocket_connect("/twilio/conversation-relay") as ws:
            replies.append(_consented_provider_call(ws, "CA-f45-banned"))
            for utterance in (
                "The patient's name is Jane Doe",
                "born 03/12/1950",
                "congestive heart failure",
                "Humana Gold Plus HMO",
                "zip 11201",
            ):
                replies.append(_say(ws, utterance))
        for reply in replies:
            for phrase in BANNED_PHRASES:
                assert phrase.lower() not in reply.lower()

    def test_question_order_constant_matches_the_session_fields(self):
        session = twilio_routes.CallSession("CA-f45-fields")
        for field, _question in PROVIDER_FIELD_QUESTIONS:
            assert hasattr(session, field)
