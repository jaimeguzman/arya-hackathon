"""Eligibility Agent checks: deterministic, data-backed, never LLM-decided.

Each check returns a CheckResult that maps onto the safety layer's
EligibilityStatus semantics: PASS, hard FAIL (black-and-white fact), or
NEEDS_MORE_INFO when required input is missing.
"""
