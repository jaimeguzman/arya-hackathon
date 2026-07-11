"""Notification contract + a stub.

The seam between the Follow-up Agent (Task 4) and real Twilio wiring (Task 1).
The Follow-up Agent depends only on the `NotificationClient` protocol, so the
real Twilio-backed client drops in without touching agent logic.

Twilio is mandatory for telephony (PROJECT.md Official Challenge Brief) — the
real client MUST be Twilio Programmable SMS / Voice. This stub sends nothing;
it records intended sends so the agent is testable offline with no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class DeliveryResult:
    channel: str  # "sms" | "voice"
    to: str
    status: str  # "queued" | "delivered" | "failed" (stub always "queued")
    reference: str  # provider message/call SID
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class NotificationClient(Protocol):
    async def send_sms(self, *, to: str, body: str) -> DeliveryResult: ...

    async def place_call(self, *, to: str, mode: str, mission: str) -> DeliveryResult: ...


class StubNotificationClient:
    """Records intended sends instead of contacting Twilio. Task 1 replaces this."""

    def __init__(self) -> None:
        self.sent: list[DeliveryResult] = []

    async def send_sms(self, *, to: str, body: str) -> DeliveryResult:
        result = DeliveryResult(
            channel="sms",
            to=to,
            status="queued",
            reference=f"STUB-SMS-{len(self.sent) + 1}",
            detail={"body": body},
        )
        self.sent.append(result)
        return result

    async def place_call(self, *, to: str, mode: str, mission: str) -> DeliveryResult:
        result = DeliveryResult(
            channel="voice",
            to=to,
            status="queued",
            reference=f"STUB-CALL-{len(self.sent) + 1}",
            detail={"mode": mode, "mission": mission},
        )
        self.sent.append(result)
        return result
