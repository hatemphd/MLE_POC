#!/usr/bin/env bash
# Step 4 (optional) - regrade the downloaded patches with the official SWE-bench harness.
#
# The public report.json files already carry the official grades, so this step is
# only needed if you want to reproduce them, grade patches from a new source, or
# audit a disagreement. It is expensive: the harness builds one Docker image per
# issue and runs the repository's test suite inside it.
#
# What it executes:
#   1. Checks Docker is running and warns if RAM/disk are below the harness
#      recommendations (16 GB RAM, ~120 GB free disk).
#   2. Installs the `swebench` package into .venv if missing (needs Python >= 3.10).
#   3. For each data/predictions/<submission>.jsonl runs
#        swebench eval verified -p <file> --run-id trustgate-<submission> -j <workers> -t <timeout>
#      Per-instance results land in logs/run_evaluation/trustgate-<submission>/<submission>/<instance_id>/report.json
#      and a summary JSON is written to the current directory.
#   4. Prints how to feed those reports back into build_candidate_table.py.
#
# Usage:
#   ./pipeline/run_harness.sh                         # all prediction files, 2 workers
#   ./pipeline/run_harness.sh -j 4 -t 1800            # more parallelism / per-instance timeout
#   ./pipeline/run_harness.sh --only 20250522_tools_claude-4-sonnet
#   ./pipeline/run_harness.sh --instances "django__django-11099 sympy__sympy-20590"
#   ./pipeline/run_harness.sh --modal                 # run on Modal instead of local Docker
#   ./pipeline/run_harness.sh --gold -i django__django-11099   # sanity-check the environment
#
# Afterwards:
#   .venv/bin/python pipeline/build_candidate_table.py --local-reports logs/run_evaluation

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"

WORKERS=2
TIMEOUT=1800
ONLY=""
INSTANCES=""
MODAL=0
GOLD=0
GOLD_INSTANCE=""

while [ $# -gt 0 ]; do
  case "$1" in
    -j|--workers)  WORKERS="$2"; shift 2 ;;
    -t|--timeout)  TIMEOUT="$2"; shift 2 ;;
    --only)        ONLY="$2"; shift 2 ;;
    --instances)   INSTANCES="$2"; shift 2 ;;
    --modal)       MODAL=1; shift ;;
    --gold)        GOLD=1; shift ;;
    -i)            GOLD_INSTANCE="$2"; shift 2 ;;
    -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# 1. Resource checks.
if [ "$MODAL" -eq 0 ]; then
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop or pass --modal." >&2
    exit 1
  fi
  if [ "$(uname)" = "Darwin" ]; then
    MEM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
  else
    MEM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
  fi
  FREE_GB=$(df -g "$PROJECT_DIR" | awk 'NR==2 {print $4}')
  echo "Host: ${MEM_GB} GB RAM, ${FREE_GB} GB free disk"
  [ "$MEM_GB" -lt 16 ] && echo "WARNING: the harness recommends 16 GB+ RAM. Keep -j at 1 or 2." >&2
  [ "$FREE_GB" -lt 120 ] && echo "WARNING: the harness recommends ~120 GB free disk for a full run. Use --instances or --only to limit scope." >&2
fi

# 2. Harness package.
if ! "$PY" -c "import swebench" 2>/dev/null; then
  echo "==> Installing swebench into .venv"
  uv pip install --python "$PY" swebench
fi
SWEBENCH="$PROJECT_DIR/.venv/bin/swebench"

EXTRA=()
[ "$MODAL" -eq 1 ] && EXTRA+=(--modal)
for iid in $INSTANCES; do EXTRA+=(-i "$iid"); done

# 3a. Gold sanity check: proves Docker + the harness work before spending hours.
if [ "$GOLD" -eq 1 ]; then
  [ -n "$GOLD_INSTANCE" ] && EXTRA+=(-i "$GOLD_INSTANCE")
  echo "==> swebench eval verified --gold --run-id validate-gold -j $WORKERS -t $TIMEOUT ${EXTRA[*]+"${EXTRA[*]}"}"
  "$SWEBENCH" eval verified --gold --run-id validate-gold -j "$WORKERS" -t "$TIMEOUT" ${EXTRA[@]+"${EXTRA[@]}"}
  exit 0
fi

# 3b. Regrade each prediction file. One file = one candidate per instance.
shopt -s nullglob
FILES=(data/predictions/*.jsonl)
if [ ${#FILES[@]} -eq 0 ]; then
  echo "No files in data/predictions/. Run pipeline/build_predictions.py first." >&2
  exit 1
fi
for f in "${FILES[@]}"; do
  sub="$(basename "$f" .jsonl)"
  if [ -n "$ONLY" ] && [ "$sub" != "$ONLY" ]; then continue; fi
  echo
  echo "==> swebench eval verified -p $f --run-id trustgate-$sub -j $WORKERS -t $TIMEOUT ${EXTRA[*]+"${EXTRA[*]}"}"
  "$SWEBENCH" eval verified -p "$f" --run-id "trustgate-$sub" -j "$WORKERS" -t "$TIMEOUT" ${EXTRA[@]+"${EXTRA[@]}"}
done

# 4. Next step.
echo
echo "==> Reports are under logs/run_evaluation/trustgate-*/. Rebuild the table with:"
echo "    $PY pipeline/build_candidate_table.py --local-reports logs/run_evaluation"
