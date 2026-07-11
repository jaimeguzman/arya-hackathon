"""Feature #26: only the Eligibility Agent writes eligibility/acceptance decisions."""

import pytest

from app.agents.eligibility_agent import EligibilityDecision, apply_decision
from app.eligibility.status_writer import (
    DECISION_STATUSES,
    UnauthorizedDecisionWrite,
    set_intake_status,
)


def _call_from_module(module_name: str, intake: dict, status: str) -> dict:
    """Invoke set_intake_status as if from another module (voice, pipeline)."""
    namespace = {
        "__name__": module_name,
        "set_intake_status": set_intake_status,
        "intake": intake,
        "status": status,
    }
    exec("result = set_intake_status(intake, status)", namespace)
    return namespace["result"]


class TestDecisionWriteOwnership:
    @pytest.mark.parametrize("status", sorted(DECISION_STATUSES))
    @pytest.mark.parametrize(
        "module_name",
        ["app.routes.twilio", "app.routes.eligibility", "app.pipeline.fax", "__main__"],
    )
    def test_non_agent_modules_are_rejected(self, module_name: str, status: str):
        intake = {"status": "collecting", "is_synthetic": True}
        with pytest.raises(UnauthorizedDecisionWrite):
            _call_from_module(module_name, intake, status)
        assert intake["status"] == "collecting"  # unchanged

    def test_direct_test_call_is_rejected(self):
        with pytest.raises(UnauthorizedDecisionWrite):
            set_intake_status({"status": "collecting"}, "accepted")

    @pytest.mark.parametrize("status", ["collecting", "pending_review", "needs_more_info"])
    def test_non_decision_statuses_allowed_from_anywhere(self, status: str):
        intake = _call_from_module("app.routes.twilio", {"status": "new"}, status)
        assert intake["status"] == status


class TestAgentWritePath:
    def test_accept_decision_transitions_to_accepted(self):
        decision = EligibilityDecision(status="ACCEPT", reasons=["all checks pass"])
        intake = apply_decision({"status": "collecting"}, decision)
        assert intake["status"] == "accepted"

    def test_decline_decision_transitions_to_declined(self):
        decision = EligibilityDecision(status="DECLINE", reasons=["zip not served"])
        intake = apply_decision({"status": "collecting"}, decision)
        assert intake["status"] == "declined"

    def test_needs_more_info_transitions_accordingly(self):
        decision = EligibilityDecision(status="NEEDS_MORE_INFO", reasons=["zip missing"])
        intake = apply_decision({"status": "collecting"}, decision)
        assert intake["status"] == "needs_more_info"
