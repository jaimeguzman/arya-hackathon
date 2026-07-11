"""CI safety suite — one section per must-have.md Part 1 guarantee (1-6).

If any test here fails, the build fails (see apis/api_intake/Makefile `safety` target).
"""

import pytest

from app.safety.consent import (
    INCOMING_CALL_ENTRY_NODE,
    CallRecord,
    ConsentRequiredError,
    handle_consent_answer,
    requires_consent,
)
from app.safety.db_guard import (
    DisallowedDatabaseError,
    SyntheticDataViolation,
    assert_synthetic,
    validate_database_url,
)
from app.safety.eligibility import (
    EligibilityResult,
    EligibilityStatus,
    check_eligibility,
    generate_eligibility_response,
)
from app.safety.handoff import HANDOFF_FALLBACK_MESSAGE, run_call_turn
from app.safety.llm_gateway import (
    IdentifierLeakError,
    call_llm,
    rehydrate,
    scan_for_identifiers,
    tokenize,
)
from app.safety.safe_response import BANNED_PHRASES, SafeResponse, speak

SERVICE_AREA = {"10001", "10002"}
ACCEPTED_PLANS = {"Medicare Part A", "Aetna PPO"}


# --- Guarantee 1: fake data only -------------------------------------------


def test_non_synthetic_write_raises():
    with pytest.raises(SyntheticDataViolation):
        assert_synthetic({"patient": "x"})
    with pytest.raises(SyntheticDataViolation):
        assert_synthetic({"patient": "x", "is_synthetic": False})


def test_synthetic_write_passes():
    record = {"patient": "x", "is_synthetic": True}
    assert assert_synthetic(record) is record


def test_boot_aborts_on_non_allowlisted_db():
    with pytest.raises(DisallowedDatabaseError):
        validate_database_url("postgresql://u:p@localhost:5432/production_phi")


def test_boot_accepts_demo_db():
    url = "postgresql://u:p@localhost:5432/intakeai_demo"
    assert validate_database_url(url) == url


def test_create_app_aborts_on_non_allowlisted_db(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/production_phi")
    try:
        with pytest.raises(DisallowedDatabaseError):
            create_app()
    finally:
        get_settings.cache_clear()


# --- Guarantee 2: tokenize -> LLM -> rehydrate ------------------------------


def test_tokenize_replaces_identifiers():
    record = {
        "name": "Jane Doe",
        "dob": "1950-03-12",
        "phone": "(212) 555-0187",
        "address": "12 Main Street",
        "member_id": "ABC12345678",
        "diagnosis": "hip replacement",
    }
    tokenized, token_map = tokenize(record)
    assert tokenized["name"] == "{{PATIENT_NAME}}"
    assert tokenized["phone"] == "{{PATIENT_PHONE}}"
    assert tokenized["diagnosis"] == "hip replacement"
    assert token_map["{{PATIENT_DOB}}"] == "1950-03-12"


def test_payload_with_raw_phone_is_rejected():
    with pytest.raises(IdentifierLeakError):
        call_llm("call the patient at (212) 555-0187", transport=lambda p: p)


@pytest.mark.parametrize(
    "payload",
    [
        "DOB is 03/12/1950",
        "lives at 12 Main Street",
        "member id ABC12345678",
    ],
)
def test_dob_address_member_id_patterns_are_scanned(payload):
    assert scan_for_identifiers(payload)


def test_tokenized_round_trip_restores_values():
    record = {"name": "Jane Doe", "phone": "(212) 555-0187"}
    tokenized, token_map = tokenize(record)
    payload = f"Summarize intake for {tokenized['name']}"
    response = call_llm(payload, token_map=token_map, transport=lambda p: p)
    assert rehydrate(response, token_map) == "Summarize intake for Jane Doe"
    assert "Jane Doe" not in payload


def test_no_other_module_imports_llm_sdk():
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path
        for path in app_dir.rglob("*.py")
        if path.name != "llm_gateway.py"
        and ("google.generativeai" in path.read_text() or "from google import genai" in path.read_text())
    ]
    assert offenders == []


# --- Guarantee 3: deterministic eligibility ---------------------------------


def test_clear_yes_returns_accept():
    result = check_eligibility("10001", "Aetna PPO", SERVICE_AREA, ACCEPTED_PLANS, True)
    assert result.status is EligibilityStatus.ACCEPT


def test_clear_no_returns_decline_with_reasons():
    result = check_eligibility("99999", "Cash", SERVICE_AREA, ACCEPTED_PLANS, False)
    assert result.status is EligibilityStatus.DECLINE
    assert len(result.reasons) == 3


def test_ambiguous_returns_needs_more_info():
    result = check_eligibility(None, "Aetna PPO", SERVICE_AREA, ACCEPTED_PLANS, True)
    assert result.status is EligibilityStatus.NEEDS_MORE_INFO


def test_response_generation_requires_result_object():
    with pytest.raises(TypeError):
        generate_eligibility_response()  # type: ignore[call-arg]
    result = EligibilityResult(status=EligibilityStatus.ACCEPT, reasons=["ok"])
    assert "ok" in generate_eligibility_response(result)


# --- Guarantee 4: consent first --------------------------------------------


@requires_consent
def _collect_patient_data(call: CallRecord) -> str:
    return "collected"


def test_data_collection_without_consent_raises():
    call = CallRecord(call_sid="CA1")
    with pytest.raises(ConsentRequiredError):
        _collect_patient_data(call)


def test_consent_yes_unlocks_collection():
    call = handle_consent_answer(CallRecord(call_sid="CA1"), answer_is_yes=True)
    assert _collect_patient_data(call) == "collected"


def test_consent_no_routes_to_handoff_with_zero_collection():
    call = handle_consent_answer(CallRecord(call_sid="CA1"), answer_is_yes=False)
    assert call.handoff_requested is True
    with pytest.raises(ConsentRequiredError):
        _collect_patient_data(call)


def test_consent_is_the_entry_node():
    assert INCOMING_CALL_ENTRY_NODE == "consent_gather"


# --- Guarantee 5: banned-phrase filter --------------------------------------


@pytest.mark.parametrize("phrase", BANNED_PHRASES)
def test_banned_phrases_never_reach_output(phrase):
    spoken = speak(SafeResponse(f"We {phrase} a nurse will arrive."))
    assert phrase not in spoken.lower()


def test_speak_rejects_raw_text():
    with pytest.raises(TypeError):
        speak("I guarantee a visit tomorrow")  # type: ignore[arg-type]


# --- Guarantee 6: no silent call drop ---------------------------------------


def test_forced_error_mid_turn_produces_spoken_handoff(caplog):
    call = CallRecord(call_sid="CA1", consent_given=True)

    def exploding_turn(_: CallRecord) -> str:
        raise RuntimeError("boom")

    with caplog.at_level("WARNING", logger="intakeai.safety.handoff"):
        result = run_call_turn(call, exploding_turn)
    assert result.handoff is True
    assert result.spoken_text == HANDOFF_FALLBACK_MESSAGE
    assert any("safety.handoff.triggered" in r.message for r in caplog.records)


def test_clarification_threshold_triggers_handoff():
    call = CallRecord(call_sid="CA1", consent_given=True)
    result = run_call_turn(call, lambda c: "ok", clarification_attempts=3)
    assert result.handoff is True


def test_successful_turn_speaks_filtered_response():
    call = CallRecord(call_sid="CA1", consent_given=True)
    result = run_call_turn(call, lambda c: "I guarantee a nurse today")
    assert result.handoff is False
    assert "guarantee" not in result.spoken_text
