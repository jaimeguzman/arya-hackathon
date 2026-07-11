.PHONY: test safety

# Full backend test suite with coverage.
test:
	python -m pytest --cov=app

# CI safety gate: must-have.md Part 1 guarantees (1-6).
# Exits non-zero on any failure — the build must not proceed.
safety:
	python -m pytest tests/test_safety_layer.py -q
