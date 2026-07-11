"""Watch a referral flow through the orchestrator — offline, no DB/Twilio.

    python -m backend.orchestrator.demo                 # all scenarios
    python -m backend.orchestrator.demo --scenario decline

Prints the node trace, the eligibility result, and the chosen follow-up action
for each scenario. Useful for eyeballing routing and for demo screenshots.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from backend.followup.agent import ContactOutcome, FollowUpAgent
from backend.followup.notifications import StubNotificationClient
from backend.orchestrator.graph import run_referral
from backend.orchestrator.state import initial_state

SCENARIOS = {
    "accept": initial_state(
        referral_id="REF-1001",
        source="inbound_call_provider",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        diagnosis_code="Z96.641",
        provided_documents=["physician_orders", "face_to_face_encounter", "homebound_certification"],
        contact={"name": "Sarah Chen", "phone": "+15551110001", "role": "provider"},
    ),
    "pending": initial_state(
        referral_id="REF-1002",
        source="fax",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        diagnosis_code="Z96.641",
        provided_documents=["physician_orders"],  # F2F + homebound missing
        gaps=["face_to_face_encounter"],
        contact={"name": "Discharge Planning", "phone": "+15551110002", "role": "provider"},
    ),
    "decline": initial_state(
        referral_id="REF-9001",
        source="inbound_call_provider",
        zip_code="90210",  # out of service area
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        contact={"name": "Out-of-area Hospital", "phone": "+15551110003", "role": "provider"},
    ),
    "needs_info": initial_state(
        referral_id="REF-1004",
        source="inbound_call_family",
        zip_code="11201",
        payer="Medicare",
        plan=None,
        service_type=None,
        gaps=["insurance_plan", "service_type"],
        contact={"name": "Worried Daughter", "phone": "+15551110004", "role": "family"},
    ),
}


async def _run_one(name: str) -> None:
    inputs = SCENARIOS[name]
    result = await run_referral(inputs)
    print(f"\n=== scenario: {name}  (referral {inputs.get('referral_id')}, source {inputs.get('source')}) ===")
    print("  trace:      " + " -> ".join(result["trace"]))
    elig = result.get("eligibility") or {}
    print(f"  decision:   {result.get('decision')}")
    if elig.get("reasons"):
        print(f"  reasons:    {'; '.join(elig['reasons'])}")
    if elig.get("missing_documents"):
        print(f"  missing:    {', '.join(elig['missing_documents'])}")
    print(f"  status:     {result.get('status')}"
          + ("  [human review]" if result.get("human_review_required") else ""))
    fu = result.get("followup") or {}
    print(f"  follow-up:  {fu.get('type')} / {fu.get('intent')}"
          + (f"  @ {fu['scheduled_at']}" if fu.get("scheduled_at") else ""))


async def _retry_demo() -> None:
    """Show the bounded retry -> escalation ladder (must-have.md #6)."""
    agent = FollowUpAgent(notifier=StubNotificationClient())
    print("\n=== follow-up retry ladder (outbound call keeps hitting voicemail) ===")
    for attempt in range(1, 5):
        action = agent.next_attempt(attempt, ContactOutcome.NO_ANSWER)
        when = f" @ {action.scheduled_at.isoformat()}" if action.scheduled_at else ""
        print(f"  attempt {attempt} failed -> {action.type} ({action.intent}){when}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrator demo")
    parser.add_argument("--scenario", choices=list(SCENARIOS), help="run just one scenario")
    parser.add_argument("--retries", action="store_true", help="also show the retry/escalation ladder")
    args = parser.parse_args()

    names = [args.scenario] if args.scenario else list(SCENARIOS)
    for name in names:
        await _run_one(name)
    if args.retries or not args.scenario:
        await _retry_demo()
    print()


if __name__ == "__main__":
    asyncio.run(main())
