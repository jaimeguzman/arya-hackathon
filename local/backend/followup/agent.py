"""Follow-up Agent — turns an eligibility decision into contact actions, and
owns the bounded retry / escalation policy.

Two responsibilities:
  1. plan_initial(): decision -> the first follow-up action (send confirmation,
     notify decline, or schedule an outbound call to fill gaps).
  2. next_attempt(): given a failed contact attempt, decide retry-or-escalate.

Safety (must-have.md #6): retries are BOUNDED. After `max_attempts` the agent
escalates to a human coordinator — it never retries forever, and there is no
path that silently drops a referral.

Config note (per folder CLAUDE.md: no magic numbers): intervals/limits live in
`FollowUpPolicy` and are injectable, not hardcoded in the logic below.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional

from backend.followup.notifications import NotificationClient, StubNotificationClient


class ContactOutcome(str, Enum):
    """Result of a single outbound contact attempt."""

    DELIVERED = "delivered"  # SMS delivered / call answered — done
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    SMS_NO_RESPONSE = "sms_no_response"
    FAILED = "failed"  # transient failure (network, provider error)


@dataclass
class FollowUpPolicy:
    max_attempts: int = 3
    retry_after_voicemail: timedelta = timedelta(hours=2)
    # "next morning" target hour (local) for an unanswered SMS
    next_morning_hour: int = 9


@dataclass
class FollowUpAction:
    """A single planned/taken follow-up action.

    `type` values align with the follow_up_type enum in postgres_init.sql so the
    Follow-up service can persist these directly. `terminal` marks an escalation
    or a completed contact — nothing further is scheduled after a terminal action.
    """

    type: str  # sms_sent | outbound_call_attempted | callback_scheduled | escalated | document_requested
    intent: str  # confirmation | decline_notice | gap_chase | retry | escalation
    target: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    scheduled_at: Optional[datetime] = None
    attempt_number: int = 1
    terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.scheduled_at is not None:
            data["scheduled_at"] = self.scheduled_at.isoformat()
        return data


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FollowUpAgent:
    def __init__(
        self,
        notifier: Optional[NotificationClient] = None,
        policy: Optional[FollowUpPolicy] = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        # default to the offline stub so the agent runs with no Twilio creds
        self.notifier: NotificationClient = notifier or StubNotificationClient()
        self.policy = policy or FollowUpPolicy()
        self._now = now

    # ----------------------------------------------------------------- #
    # Initial action from a decision                                     #
    # ----------------------------------------------------------------- #
    async def plan_initial(
        self, decision: str, state: dict[str, Any]
    ) -> FollowUpAction:
        """Map an eligibility decision to the first follow-up action.

        Sends immediately where the action is "notify now" (SMS confirmation /
        decline notice); schedules where the action is an outbound call.
        """
        contact = state.get("contact") or {}
        to = contact.get("phone", "")
        elig = state.get("eligibility") or {}
        missing_docs = elig.get("missing_documents") or []

        if decision == "ACCEPT":
            if missing_docs:
                body = (
                    "We can accept this referral. We still need: "
                    f"{', '.join(missing_docs)}. A coordinator will confirm shortly."
                )
            else:
                body = (
                    "We can accept this referral and a caregiver is available. "
                    "A coordinator will confirm the details shortly."
                )
            if to:
                await self.notifier.send_sms(to=to, body=body)
            return FollowUpAction(
                type="sms_sent",
                intent="confirmation",
                target=contact,
                message=body,
            )

        if decision == "DECLINE":
            reasons = elig.get("reasons") or []
            body = (
                "We're unable to take this referral at this time"
                + (f" ({reasons[0]})" if reasons else "")
                + ". We wanted to let you know quickly so you can place the patient elsewhere."
            )
            if to:
                await self.notifier.send_sms(to=to, body=body)
            return FollowUpAction(
                type="sms_sent",
                intent="decline_notice",
                target=contact,
                message=body,
                terminal=True,
            )

        # NEEDS_MORE_INFO -> schedule an outbound call to fill the gaps.
        mission = "collect missing referral details"
        if state.get("gaps"):
            mission = f"collect: {', '.join(state['gaps'])}"
        return FollowUpAction(
            type="callback_scheduled",
            intent="gap_chase",
            target=contact,
            message=mission,
            scheduled_at=self._now(),
            attempt_number=1,
        )

    # ----------------------------------------------------------------- #
    # Retry / escalation for a failed contact attempt (must-have.md #6) #
    # ----------------------------------------------------------------- #
    def next_attempt(
        self, attempt_number: int, outcome: ContactOutcome
    ) -> FollowUpAction:
        """Given the attempt that just finished, decide what happens next.

        Bounded: once `attempt_number` reaches `max_attempts`, escalate to a
        human — never schedule a further retry.
        """
        if outcome == ContactOutcome.DELIVERED:
            return FollowUpAction(
                type="outbound_call_attempted",
                intent="confirmation",
                attempt_number=attempt_number,
                terminal=True,
            )

        if attempt_number >= self.policy.max_attempts:
            return FollowUpAction(
                type="escalated",
                intent="escalation",
                message=(
                    f"Escalating to a human coordinator after {attempt_number} "
                    "failed contact attempts."
                ),
                attempt_number=attempt_number,
                terminal=True,
            )

        next_number = attempt_number + 1
        now = self._now()
        if outcome in (ContactOutcome.VOICEMAIL, ContactOutcome.NO_ANSWER, ContactOutcome.FAILED):
            scheduled = now + self.policy.retry_after_voicemail
        else:  # SMS_NO_RESPONSE -> next morning
            scheduled = self._next_morning(now)

        return FollowUpAction(
            type="callback_scheduled",
            intent="retry",
            scheduled_at=scheduled,
            attempt_number=next_number,
        )

    def _next_morning(self, now: datetime) -> datetime:
        target = datetime.combine(
            now.date(), time(hour=self.policy.next_morning_hour), tzinfo=now.tzinfo
        )
        if now >= target:
            target += timedelta(days=1)
        return target
