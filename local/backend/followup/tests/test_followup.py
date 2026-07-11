"""Follow-up Agent tests — bounded retry/escalation + initial actions.
Covers checklist C1-C4."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.followup.agent import (
    ContactOutcome,
    FollowUpAgent,
    FollowUpPolicy,
)
from backend.followup.notifications import StubNotificationClient

FIXED_NOW = datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc)  # 2pm UTC


def _agent() -> FollowUpAgent:
    return FollowUpAgent(notifier=StubNotificationClient(), now=lambda: FIXED_NOW)


# C1 — voicemail schedules a retry ~2h out, attempt incremented
def test_voicemail_retry_in_two_hours():
    action = _agent().next_attempt(1, ContactOutcome.VOICEMAIL)
    assert action.type == "callback_scheduled"
    assert action.intent == "retry"
    assert action.attempt_number == 2
    assert action.scheduled_at == FIXED_NOW + timedelta(hours=2)
    assert action.terminal is False


# C2 — no SMS response follows up next morning (9am), same day since now is 2pm...
#      2pm is after 9am so it rolls to next day
def test_sms_no_response_next_morning():
    action = _agent().next_attempt(1, ContactOutcome.SMS_NO_RESPONSE)
    assert action.type == "callback_scheduled"
    assert action.scheduled_at.hour == 9
    # 2pm now -> next morning is tomorrow 9am
    assert action.scheduled_at.date() == (FIXED_NOW + timedelta(days=1)).date()


def test_sms_no_response_same_morning_when_before_nine():
    early = datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc)
    agent = FollowUpAgent(now=lambda: early)
    action = agent.next_attempt(1, ContactOutcome.SMS_NO_RESPONSE)
    assert action.scheduled_at.date() == early.date()
    assert action.scheduled_at.hour == 9


# C3 — 3 failed attempts escalate; a 4th never schedules another retry
def test_escalates_after_three_attempts():
    agent = _agent()
    # attempts 1 and 2 still retry
    assert agent.next_attempt(1, ContactOutcome.NO_ANSWER).intent == "retry"
    assert agent.next_attempt(2, ContactOutcome.NO_ANSWER).intent == "retry"
    # the 3rd attempt failing -> escalate, terminal
    third = agent.next_attempt(3, ContactOutcome.NO_ANSWER)
    assert third.type == "escalated"
    assert third.intent == "escalation"
    assert third.terminal is True
    # nothing beyond max ever schedules a retry
    beyond = agent.next_attempt(4, ContactOutcome.NO_ANSWER)
    assert beyond.type == "escalated"
    assert beyond.terminal is True


def test_custom_policy_max_attempts_is_respected():
    agent = FollowUpAgent(policy=FollowUpPolicy(max_attempts=2), now=lambda: FIXED_NOW)
    assert agent.next_attempt(1, ContactOutcome.NO_ANSWER).intent == "retry"
    assert agent.next_attempt(2, ContactOutcome.NO_ANSWER).type == "escalated"


# delivered outcome is terminal, no further contact
def test_delivered_is_terminal():
    action = _agent().next_attempt(1, ContactOutcome.DELIVERED)
    assert action.terminal is True
    assert action.intent == "confirmation"


# C4 — runs with the stub notifier, no Twilio creds; SMS confirmation recorded
@pytest.mark.asyncio
async def test_plan_initial_accept_sends_sms_via_stub():
    notifier = StubNotificationClient()
    agent = FollowUpAgent(notifier=notifier, now=lambda: FIXED_NOW)
    state = {
        "contact": {"phone": "+15550000001", "role": "provider"},
        "eligibility": {"missing_documents": ["face_to_face_encounter"], "reasons": []},
    }
    action = await agent.plan_initial("ACCEPT", state)
    assert action.type == "sms_sent"
    assert action.intent == "confirmation"
    assert len(notifier.sent) == 1
    assert "face_to_face_encounter" in notifier.sent[0].detail["body"]


@pytest.mark.asyncio
async def test_plan_initial_decline_is_terminal():
    agent = FollowUpAgent(now=lambda: FIXED_NOW)
    state = {"contact": {"phone": "+15550000009"}, "eligibility": {"reasons": ["zip not served"]}}
    action = await agent.plan_initial("DECLINE", state)
    assert action.intent == "decline_notice"
    assert action.terminal is True


@pytest.mark.asyncio
async def test_plan_initial_needs_info_schedules_gap_chase():
    agent = FollowUpAgent(now=lambda: FIXED_NOW)
    state = {"contact": {"phone": "+15550000010"}, "gaps": ["insurance_plan"], "eligibility": {}}
    action = await agent.plan_initial("NEEDS_MORE_INFO", state)
    assert action.intent == "gap_chase"
    assert action.scheduled_at == FIXED_NOW
    assert "insurance_plan" in action.message
