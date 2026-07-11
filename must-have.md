# Arya Health — Must-Haves (Hackathon Build)

This file has two parts:
1. **Safety Layer Must-Haves** — non-negotiable, checked on every single run before demo/deploy.
2. **App-Level Feature Must-Haves** — the core product features.

---

## Part 1: Safety Layer Must-Haves (Non-Negotiable)

> **Rule: If any one of these 5 checks fails, the voice agent must NOT go live for that run.**
> These are not "nice to have" — they are the difference between a responsible prototype and a liability. Every developer working on the Twilio voice agent must verify all 5 before every demo, every test call, every run.

### 1. Fake Data Only — No Real PHI Ever Touches the System

- **Requirement:** All patient, physician, and insurance data used in the system MUST come from a synthetic data generator/seed script. No real patient names, DOBs, addresses, insurance IDs, or medical records are ever entered into the database, the LLM, or Twilio.
- **Implementation:** A `seed_data.py` (or equivalent) script that populates the DB with clearly fake records (e.g., names from a "fake patients" list, obviously fictional addresses).
- **Check before every run:**
  - [ ] Database contains ONLY records inserted by the seed script — run a query to confirm no unexpected records exist.
  - [ ] No developer has manually typed a real name/phone/address into a test call.
  - [ ] `.env` / config confirms the app is pointed at the seed/demo DB, not any production or real-data source.

### 2. Tokenize → LLM → Rehydrate Wrapper

- **Requirement:** The LLM must never receive raw identifiers (name, DOB, phone, address, insurance member ID) directly in its prompt or conversation context. All identifiers are tokenized before being sent to the LLM, and rehydrated only inside your own backend after the LLM responds.
- **Implementation:** A wrapper function, e.g.:
  ```python
  def tokenize(text: str) -> tuple[str, dict]:
      # replace identifiers with placeholders like {{PATIENT_NAME}}, {{DOB}}
      ...
      return tokenized_text, mapping

  def call_llm(tokenized_text: str) -> str:
      ...

  def rehydrate(response: str, mapping: dict) -> str:
      # substitute placeholders back with real values
      ...
  ```
  Every LLM call in the codebase must go through this wrapper — no direct calls to the LLM API with raw conversation text.
- **Check before every run:**
  - [ ] Print/log the exact payload sent to the LLM API and confirm it contains only tokens/placeholders, never raw identifiers.
  - [ ] Confirm rehydration happens only after the LLM response, inside your backend, not before.

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
  The LLM only ever reads back this returned object using approved phrasing — it is never prompted with "do you think we can accept this patient?"
- **Check before every run:**
  - [ ] Confirm the LLM's system prompt does NOT ask it to decide/judge eligibility — only to report the result of `check_eligibility()`.
  - [ ] Confirm `check_eligibility()` is called for every referral, and its output (not an LLM guess) drives the response.
  - [ ] Test at least one clear-yes, one clear-no, and one ambiguous case to confirm correct branching.

### 4. Consent Gather — First Node in Every Call Flow

- **Requirement:** Every call, without exception, must open with an AI + recording disclosure and a yes/no consent gather BEFORE any patient data collection begins.
- **Implementation:** In Twilio Studio/TwiML, the very first node plays:
  > "Hi, this is Arya Health's automated assistant. This call may be recorded and is handled by an AI system to help coordinate care. Is that okay with you?"

  Flow: `IncomingCall → ConsentGather → [No: TransferToHuman/EndCall] → [Yes: MainFlow]`
- **Check before every run:**
  - [ ] Place a test call and confirm the consent line plays before anything else — no data-collection prompt occurs first.
  - [ ] Confirm saying "no" routes to a safe fallback (human transfer or graceful end), not a dead end or continued data collection.
  - [ ] Confirm `consent_given` (true/false) is logged/stored against the call SID.

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
  Every LLM response destined for `<Say>` or a TTS engine must pass through `filter_response()` first — no exceptions, no bypass path.
- **Check before every run:**
  - [ ] Confirm `filter_response()` sits between LLM output and TTS in the code path — not optional, not skippable.
  - [ ] Test with a deliberately over-promising prompt to confirm the filter catches it and substitutes a safe response.
  - [ ] Confirm the approved-phrase list for acceptance responses is being used (e.g., "we can likely accept," "a coordinator will confirm within the hour").

---

### Safety Layer — Run Checklist (copy/paste before every demo or test)

```
[ ] 1. Fake data only — confirmed DB has no real PHI
[ ] 2. Tokenize/rehydrate wrapper — confirmed LLM never sees raw identifiers
[ ] 3. check_eligibility() — confirmed decision is code-driven, not LLM-driven
[ ] 4. Consent gather — confirmed it's the first node, confirmed "no" path works
[ ] 5. Banned-phrase filter — confirmed it sits before TTS and catches over-promising
```

If any box is unchecked, **do not run the demo or send the agent live** until fixed.

---

## Part 2: App-Level Feature Must-Haves

| Feature | Category | Complexity | Impact |
|---|---|---|---|
| Voice agent for inbound discharge planner calls (real-time accept/decline) | Must-have | High | Very High — this is the core value prop |
| Real-time eligibility engine (zip + insurance + caregiver match) | Must-have | Medium-High | Very High — nothing else works without this |
| Gap detection (what's missing) + auto follow-up calls/faxes | Must-have | Medium | High |
| Empathetic voice agent for family/patient calls (midnight caller) | Unique / demo-friendly | Medium-High | High — great emotional hook for a pitch |
| Live "confidence score" UI showing what the AI extracted from a fax in real time | Unique / demo-friendly | Low-Medium | High for demos, medium for actual ops |
