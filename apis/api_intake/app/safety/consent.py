"""Guarantee 4: consent gather is the first node of every call flow.

The consent node is the only node wired to the incoming-call trigger, and
every data-collection function reads consent_given from the persisted call
record and refuses to run when it is not True.
"""

import functools
from collections.abc import Callable

from pydantic import BaseModel

CONSENT_DISCLOSURE = (
    "This call is handled by an AI assistant and may be recorded for quality "
    "purposes. Do I have your consent to continue? Please answer yes or no."
)

# The single node wired to the incoming-call trigger.
INCOMING_CALL_ENTRY_NODE = "consent_gather"


class CallRecord(BaseModel):
    """Persisted per-call state read by every data-collection function."""

    call_sid: str
    consent_given: bool = False
    handoff_requested: bool = False


class ConsentRequiredError(RuntimeError):
    """Raised when data collection is attempted without recorded consent."""


def requires_consent(func: Callable) -> Callable:
    """Decorator for every data-collection function: refuses without consent."""

    @functools.wraps(func)
    def wrapper(call: CallRecord, *args, **kwargs):
        if call.consent_given is not True:
            raise ConsentRequiredError(
                f"Refusing to run {func.__name__}: consent_given is not True "
                f"for call {call.call_sid}."
            )
        return func(call, *args, **kwargs)

    return wrapper


def handle_consent_answer(call: CallRecord, answer_is_yes: bool) -> CallRecord:
    """'Yes' unlocks data collection; 'no' routes to human handoff with zero
    data collection."""
    if answer_is_yes:
        return call.model_copy(update={"consent_given": True})
    return call.model_copy(update={"consent_given": False, "handoff_requested": True})
