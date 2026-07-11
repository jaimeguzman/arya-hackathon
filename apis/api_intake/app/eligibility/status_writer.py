"""Single write path for eligibility/acceptance intake statuses.

Only the Eligibility Agent module (`app.agents.eligibility_agent`) may
transition an intake to a decision status (eligible / accepted / declined).
Any other module — voice routes, pipeline code, tests posing as them —
gets an UnauthorizedDecisionWrite.

Enforcement is caller-module inspection over the call stack, so the rule
holds even if someone imports this function directly.
"""

import inspect

# Statuses that represent an eligibility/acceptance decision.
DECISION_STATUSES = frozenset({"eligible", "accepted", "declined"})

# The only module whose write path may set a decision status.
AUTHORIZED_WRITER_MODULE = "app.agents.eligibility_agent"


class UnauthorizedDecisionWrite(RuntimeError):
    """Raised when a non-Eligibility-Agent module sets a decision status."""


def _caller_module_name() -> str:
    frame = inspect.currentframe()
    # _caller_module_name -> set_intake_status -> actual caller
    caller = frame.f_back.f_back
    return caller.f_globals.get("__name__", "")


def set_intake_status(intake: dict, status: str) -> dict:
    """Set an intake's status, enforcing the decision-write ownership rule.

    Non-decision statuses (e.g. "collecting", "pending_review") may be set
    from anywhere. Decision statuses require the caller to be the
    Eligibility Agent module.
    """
    if status in DECISION_STATUSES:
        caller = _caller_module_name()
        if caller != AUTHORIZED_WRITER_MODULE:
            raise UnauthorizedDecisionWrite(
                f"Module '{caller}' attempted to set decision status "
                f"'{status}'. Only '{AUTHORIZED_WRITER_MODULE}' may write "
                "eligibility/acceptance decisions."
            )
    intake["status"] = status
    return intake
