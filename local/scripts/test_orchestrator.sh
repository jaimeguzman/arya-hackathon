#!/usr/bin/env bash
# Task 4 verification: run all Orchestrator + Follow-up Agent tests offline.
# No Docker, no Twilio, no DB required — everything runs against stubs.
set -euo pipefail
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LOCAL_ROOT"

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== Ensuring deps (langgraph, pytest) =="
python -m pip install -q -r requirements.txt
python -c "import langgraph" 2>/dev/null || python -m pip install -q langgraph

export PYTHONPATH="$LOCAL_ROOT"

echo "== Running Orchestrator + Follow-up tests =="
python -m pytest backend/orchestrator/tests backend/followup/tests -v

echo ""
echo "== Demo: all scenarios end-to-end =="
python -m backend.orchestrator.demo

echo ""
echo "== PASS: Task 4 orchestrator + follow-up verified offline =="
