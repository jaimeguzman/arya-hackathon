# Arya Health — Must-Haves (Hackathon Build)

This file has two parts:
1. **Safety Layer Must-Haves** — non-negotiable, checked on every single run before demo/deploy.
2. **App-Level Feature Must-Haves** — the core product features.

---

## Part 1: Safety Layer Must-Haves (Non-Negotiable)

> **Rule: These 5 guarantees must be enforced BY THE CODE ITSELF, on every single execution — not by a human remembering to check a box before a demo.**
> A manual checklist eventually gets skipped. The correct pattern is: the system automatically fails closed (refuses to run, throws an error, blocks the call) if any guarantee isn't met — no human step required. Each item below includes the actual enforcement mechanism that must live in the codebase, not just in a developer's memory.

### 1. Fake Data Only — No Real PHI Ever Touches the System

- **Requirement:** All patient, physician, and insurance data used in the system MUST be synthetic or masked. No real patient names, DOBs, addresses, insurance IDs, or medical records are ever entered into the database, the LLM, or Twilio. The exact method (a seed script, a masking/anonymization layer, a synthetic data generator, or manually authored fake records) is a choice for the team — what matters is that whatever data flows through the system is provably not real PHI.
- **Code-enforced guarantee (not a manual check):** Whatever masking/synthetic-data approach the team picks, it must be enforced by the code itself, not just by convention. One example pattern (adapt as needed):
  - Every record inserted anywhere gets tagged `is_synthetic: true` (or equivalent, e.g. a hash-based marker) by whatever generates/masks it. A hard assertion runs on every DB write, not just at setup:
    ```python
    def save_record(record: dict):
        assert record.get("is_synthetic") is True, "Refusing to save non-synthetic record"
        db.insert(record)
    ```
  - App refuses to boot unless pointed at the designated demo/masked database — enforced in code, not by convention:
    ```python
    ALLOWED_DB_NAMES = ["arya_demo_db"]
    assert DB_NAME in ALLOWED_DB_NAMES, f"Refusing to start: DB '{DB_NAME}' is not an approved demo DB"
    ```
  - Result: even if a developer forgets, points the app at a different DB, or tries to manually insert a record without the flag, **the code itself throws and halts execution** — no human step required to catch it.

### 2. Tokenize → LLM → Rehydrate Wrapper

- **Requirement:** The LLM must never receive raw identifiers (name, DOB, phone, address, insurance member ID) directly in its prompt or conversation context. All identifiers are tokenized before being sent to the LLM, and rehydrated only inside your own backend after the LLM responds.
- **Code-enforced guarantee (not a manual check):**
  - There is exactly ONE function in the entire codebase allowed to call the LLM API. It scans its own outgoing payload for identifier patterns and refuses to send if any are found:
    ```python
    import re

    PHI_PATTERNS = [r"\b\d{3}-\d{2}-\d{4}\b", r"\b\d{10}\b", r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"]  # SSN, phone, DOB, etc.

    def call_llm(tokenized_text: str) -> str:
        for pattern in PHI_PATTERNS:
            assert not re.search(pattern, tokenized_text), "Refusing LLM call: raw identifier pattern detected in payload"
        return llm_client.send(tokenized_text)
    ```
  - No other function in the codebase is permitted to import the LLM client directly — enforce this with a lint rule or code review, so `tokenize() → call_llm() → rehydrate()` is the only path, never bypassed.
  - Result: even if a developer accidentally passes raw conversation text, the guard function catches the pattern and blocks the call before it ever reaches the LLM — automatically, not by a human spotting it in logs.

### 3. `check_eligibility()` as Deterministic Code — Never LLM-Decided

- **Requirement:** Eligibility decisions (zip match, insurance accepted, caregiver availability) are made by plain deterministic code — lookups against known tables/lists — never by asking the LLM to "decide" or "judge" eligibility.
- **Implementation:**
  ```python
  def check_eligibility(zip_code, payer, plan, service_type) -> dict:
      zip_ok = zip_code in SERVICE_AREAS
      payer_ok = (payer, plan) in ACCEPTED_INSURANCE
      caregiver_ok = caregiver_available(service_type, zip_code)

      if zip_ok and payer_ok and caregiver_ok:
          status = "provisional_yes"
      elif not zip_ok or not payer_ok:
          status = "provisional_no"
      else:
          status = "needs_review"

      return {"status": status, "zip_ok": zip_ok, "payer_ok": payer_ok, "caregiver_ok": caregiver_ok}
  ```
- **Code-enforced guarantee (not a manual check):**
  - The LLM is architecturally incapable of producing an eligibility verdict on its own — it is only ever given the *output object* of `check_eligibility()` to phrase back, never asked an open question about acceptance. Enforce this by making the response-generation function require a pre-computed status as input:
    ```python
    def generate_agent_response(eligibility_result: dict, template_set: dict) -> str:
        assert "status" in eligibility_result, "Refusing to respond: no eligibility result provided"
        assert eligibility_result["status"] in ("provisional_yes", "provisional_no", "needs_review")
        return template_set[eligibility_result["status"]]
    ```
  - This function signature makes it structurally impossible to generate an acceptance/decline response without first calling `check_eligibility()` — there's no code path where the LLM's own opinion becomes the final word.
  - Add a unit test that runs on every build/CI pass: feed in a clear-yes, a clear-no, and an ambiguous case, and assert the correct status comes back every time. If this test fails, the build fails — no manual demo-day testing required.

### 4. Consent Gather — First Node in Every Call Flow

- **Requirement:** Every call, without exception, must open with an AI + recording disclosure and a yes/no consent gather BEFORE any patient data collection begins.
- **Implementation:** In Twilio Studio/TwiML, the very first node plays:
  > "Hi, this is Arya Health's automated assistant. This call may be recorded and is handled by an AI system to help coordinate care. Is that okay with you?"

  Flow: `IncomingCall → ConsentGather → [No: TransferToHuman/EndCall] → [Yes: MainFlow]`
- **Code-enforced guarantee (not a manual check):**
  - Every function that collects or processes patient data requires a `consent_given=True` flag as an argument, and refuses to run without it:
    ```python
    def collect_patient_data(call_sid: str, consent_given: bool):
        assert consent_given, f"Refusing to collect data on call {call_sid}: consent not confirmed"
        ...
    ```
  - The consent gather node is wired as the literal entry point in the Twilio Studio flow/TwiML — not just "first by convention" but the only node connected to the incoming-call trigger. All other flows are unreachable except through it.
  - `consent_given` is written to the call record the moment it's captured, and every downstream function call reads it from that record rather than trusting an in-memory variable — so there's no code path where data collection can start before consent is logged.

### 5. Banned-Phrase Filter on Agent Output Before TTS

- **Requirement:** No response from the voice agent may reach text-to-speech without first being checked against a banned-phrase list that prevents over-promising.
- **Implementation:**
  ```python
  BANNED_PHRASES = ["guarantee", "guaranteed", "promise", "definitely will",
                     "100%", "for sure", "confirmed appointment at"]

  def filter_response(text: str) -> str:
      for phrase in BANNED_PHRASES:
          if phrase.lower() in text.lower():
              return SAFE_FALLBACK_RESPONSE  # e.g. "A coordinator will confirm this shortly."
      return text
  ```
- **Code-enforced guarantee (not a manual check):**
  - There is exactly ONE function allowed to send text to TTS/`<Say>`, and it requires the text to have already passed through `filter_response()` — enforced by only accepting a typed wrapper object, not a raw string:
    ```python
    class SafeResponse:
        def __init__(self, text: str):
            self.text = filter_response(text)  # filtering happens on construction, can't be skipped

    def speak(response: SafeResponse):
        assert isinstance(response, SafeResponse), "Refusing to speak: response was not passed through filter_response()"
        twilio_say(response.text)
    ```
  - Because `speak()` only accepts a `SafeResponse` object (not a plain string), there is no code path where unfiltered LLM output can reach the caller — the type system itself blocks the bypass.
  - Add a CI test with a deliberately over-promising input string and assert the output never contains a banned phrase. This runs automatically on every build, not just before a demo.

---

### Safety Layer — How This Stays Enforced Automatically

The design principle across all 5: **make the unsafe path impossible to reach in code, not just discouraged.**

| # | Guarantee | Enforcement mechanism |
|---|---|---|
| 1 | No real PHI in the system | `assert record["is_synthetic"]` (or equivalent masking marker) on every DB write + DB name allowlist at startup |
| 2 | LLM never sees raw identifiers | Single `call_llm()` entry point with regex guard that refuses to send if patterns match |
| 3 | Eligibility is code-decided, not LLM-decided | `generate_agent_response()` requires a pre-computed status object; can't run without it |
| 4 | Consent always comes first | `collect_patient_data()` requires `consent_given=True`; consent node is the only call entry point |
| 5 | No over-promising reaches the caller | `speak()` only accepts a `SafeResponse` type, which filters on construction — can't bypass |

Add a single CI test suite (`test_safety_layer.py`) that runs all 5 assertions/unit tests on every commit. If any fails, the build fails — this replaces any reliance on someone remembering to check before a demo.

---

## Part 2: App-Level Feature Must-Haves

| Feature | Category | Complexity | Impact |
|---|---|---|---|
| Voice agent for inbound discharge planner calls (real-time accept/decline) | Must-have | High | Very High — this is the core value prop |
| Real-time eligibility engine (zip + insurance + caregiver match) | Must-have | Medium-High | Very High — nothing else works without this |
| Confidence/quality dashboard for the agency (per-call extraction confidence, eligibility result, consent status, flagged needs-review cases, transcript log) | Must-have | Medium | High — this is both the audit trail and the human-confirmation checkpoint |
| Empathetic voice agent for family/patient calls (midnight caller) | Unique / demo-friendly | Medium-High | High — great emotional hook for a pitch |
