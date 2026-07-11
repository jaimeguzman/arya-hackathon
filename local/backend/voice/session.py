"""Per-call session state.

# ponytail: in-memory dict keyed by call_sid, not Redis — docs/ARCHITECTURE.md's
# call-state store is Redis. Ceiling: state is lost on process restart and
# doesn't scale past one worker. Upgrade: swap get_or_create()/drop() for
# Redis-backed reads/writes behind the same function signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CallSession:
    call_sid: str
    consent_given: bool = False
    mode: str | None = None  # "provider" | "family" | "outbound"
    known_fields: dict[str, str] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)
    clarification_attempts: int = 0
    caller_number: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_sessions: dict[str, CallSession] = {}


def get_or_create(call_sid: str) -> CallSession:
    if call_sid not in _sessions:
        _sessions[call_sid] = CallSession(call_sid=call_sid)
    return _sessions[call_sid]


def drop(call_sid: str) -> None:
    _sessions.pop(call_sid, None)
