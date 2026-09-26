#!/usr/bin/env bash
# Experiment 2 end to end: LLM judge as the ceiling.
#
# What it executes:
#   1. Checks that an API key for the chosen provider is exported in this shell.
#   2. Prints the token and cost estimate and asks for confirmation (skip with --yes).
#   3. Submits one batch of the validation + test candidates, waits, writes
#      data/<split>/llm_judge/<split>_scores.jsonl.
#   4. Re-executes TrustGateExperimentation.ipynb headlessly so experiment 2 cells run,
#      saves the executed copy to docs/TrustGateExperimentation_executed.ipynb, and
#      prints the experiment 2 verdict.
#
# Usage:
#   export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY for --provider anthropic
#   ./pipeline/run_experiment2.sh --provider openai --model gpt-5
#   ./pipeline/run_experiment2.sh --provider anthropic --model claude-opus-5
#   ./pipeline/run_experiment2.sh --provider openai --model gpt-5 --price-in 1.25 --price-out 10 --yes
#   TRUSTGATE_SPLIT=full ./pipeline/run_experiment2.sh --provider openai      # full 2,294-issue split

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || { echo "No .venv; run ./setup_and_run.sh --no-run first" >&2; exit 1; }

PROVIDER="openai"; MODEL=""; YES=0; PRICE_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --model)    MODEL="$2"; shift 2 ;;
    --price-in) PRICE_ARGS+=(--price-in "$2"); shift 2 ;;
    --price-out) PRICE_ARGS+=(--price-out "$2"); shift 2 ;;
    --yes|-y)   YES=1; shift ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
[ -n "$MODEL" ] || MODEL=$([ "$PROVIDER" = "openai" ] && echo gpt-5 || echo claude-opus-5)
SPLIT="${TRUSTGATE_SPLIT:-verified}"

# 1. Credentials.
if [ "$PROVIDER" = "openai" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is not set in this shell. Run:  export OPENAI_API_KEY=...   then rerun." >&2; exit 1
fi
if [ "$PROVIDER" = "anthropic" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo "ANTHROPIC_API_KEY is not set in this shell. Run:  export ANTHROPIC_API_KEY=...   then rerun." >&2; exit 1
fi
echo "==> Provider $PROVIDER, model $MODEL, split $SPLIT"

# 2. Estimate and confirm.
"$PY" pipeline/llm_judge.py estimate --provider "$PROVIDER" --model "$MODEL" ${PRICE_ARGS[@]+"${PRICE_ARGS[@]}"}
if [ "$YES" -ne 1 ]; then
  read -r -p "Submit this batch to $PROVIDER and spend the money? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Aborted; nothing submitted."; exit 0; }
fi

# 3. Submit, wait, collect.
"$PY" pipeline/llm_judge.py run --provider "$PROVIDER" --model "$MODEL"

# 4. Re-execute the experimentation notebook and show the verdict.
mkdir -p docs
echo "==> Re-executing TrustGateExperimentation.ipynb"
"$ROOT/.venv/bin/jupyter" nbconvert --to notebook --execute TrustGateExperimentation.ipynb \
  --output "$ROOT/docs/TrustGateExperimentation_executed.ipynb" --ExecutePreprocessor.timeout=3600 >/dev/null 2>&1
"$PY" - <<'PYEOF'
import json
nb = json.load(open("docs/TrustGateExperimentation_executed.ipynb"))
for c in nb["cells"]:
    src = "".join(c["source"])
    if c["cell_type"] == "code" and src.startswith("# Experiment 2b"):
        for o in c.get("outputs", []):
            if o.get("output_type") == "error":
                print("ERROR", o["ename"], o["evalue"][:300])
            elif "text" in o:
                print("".join(o["text"]))
            elif "data" in o and "text/plain" in o["data"]:
                print("".join(o["data"]["text/plain"]))
print("\nFull executed notebook: docs/TrustGateExperimentation_executed.ipynb")
print("Results JSON: docs/experiments_<split>.json")
PYEOF
