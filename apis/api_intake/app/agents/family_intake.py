"""Family-mode intake support (feature 46).

Implements the family-mode contract from ai-agents/voice-agent/family-mode.md:

- Preliminary eligibility wording that NEVER hard-declines a family caller and
  never promises coverage — only "we should be able to help" (likely) or
  "a coordinator will review and call you either way" (everything else).
- End-of-call wrap-up: intake record created with status NEW, a human
  follow-up flag due by the next 9 AM, and an SMS confirmation queued to the
  caller's callback number.

Status NEW is a non-decision status, so writing it here does not violate the
eligibility_agent's exclusive decision-write ownership (status_writer).
"""

from datetime import datetime, time, timedelta

from pydantic import BaseModel

from app.agents.eligibility_agent import EligibilityDecision
from app.eligibility.status_writer import set_intake_status
from app.safety.safe_response import SafeResponse

# Human follow-up service-level: a coordinator must act on every family-mode
# intake by this local hour of the morning (family-mode.md "flags the human
# follow-up ... first thing in the morning").
FOLLOW_UP_DEADLINE = time(hour=9)

INTAKE_STATUS_NEW = "NEW"

# Family-mode preliminary wording (family-mode.md "Mid-call preliminary
# check"): only two outcomes are ever relayed, both scheduling a coordinator.
FAMILY_LIKELY_SERVICEABLE_WORDING = (
    "Based on what you've told me, we should be able to help. A care "
    "coordinator will call you in the morning — it would help to have the "
    "insurance card and the doctor's contact information ready."
)
FAMILY_COORDINATOR_REVIEW_WORDING = (
    "Thank you for sharing that. A care coordinator will review everything "
    "first thing in the morning and call you either way."
)

CALLBACK_NUMBER_QUESTION = "What is the best phone number to call you back on?"

FAMILY_CLOSING_WORDING = (
    "You're all set — a care coordinator will call you back at that number "
    "in the morning. We'll also send you a short text confirmation. "
    "Take care."
)

SMS_CONFIRMATION_BODY = (
    "ABC Home Health: thank you for calling. We received your request and a "
    "care coordinator will call you back in the morning. Reply to this "
    "message if anything changes."
)


class PendingSms(BaseModel):
    """An SMS confirmation queued for sending via Twilio."""

    to_number: str
    body: str


class FamilyWrapup(BaseModel):
    """End-of-call artifacts for a family-mode intake (family-mode.md)."""

    intake: dict
    follow_up_due: datetime
    sms: PendingSms


def family_eligibility_wording(decision: EligibilityDecision) -> str:
    """Family-safe relay of a preliminary decision.

    Never a hard decline, never a promise: ACCEPT becomes "we should be able
    to help"; DECLINE and NEEDS_MORE_INFO both become a coordinator-review
    message. Every outcome schedules a coordinator follow-up.
    """
    if decision.status == "ACCEPT":
        return FAMILY_LIKELY_SERVICEABLE_WORDING
    return FAMILY_COORDINATOR_REVIEW_WORDING


def follow_up_deadline(call_time: datetime) -> datetime:
    """The next 9 AM after the call — same day for overnight calls."""
    same_day = datetime.combine(call_time.date(), FOLLOW_UP_DEADLINE, tzinfo=call_time.tzinfo)
    if call_time < same_day:
        return same_day
    return same_day + timedelta(days=1)


def create_family_wrapup(callback_number: str, call_time: datetime) -> FamilyWrapup:
    """Create the end-of-call artifacts: NEW intake, follow-up flag, SMS.

    The SMS body passes through the banned-phrase filter (SafeResponse) —
    the same guarantee-5 gate spoken replies get.
    """
    intake = set_intake_status({}, INTAKE_STATUS_NEW)
    return FamilyWrapup(
        intake=intake,
        follow_up_due=follow_up_deadline(call_time),
        sms=PendingSms(
            to_number=callback_number,
            body=SafeResponse(SMS_CONFIRMATION_BODY).text,
        ),
    )
