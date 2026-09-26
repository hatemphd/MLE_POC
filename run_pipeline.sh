#!/usr/bin/env bash
# Build the TrustGate candidate table from public SWE-bench Verified submissions.
#
# Runs every pipeline step in order and leaves the result at
# data/trustgate_candidate_results.csv, which the notebook picks up automatically.
#
# Usage:
#   ./run_pipeline.sh                      # all 500 issues, the 8 default submissions
#   ./run_pipeline.sh --n 200              # stratified sample of 200 issues
#   ./run_pipeline.sh --auto 12            # pick 12 submissions from the catalog
#   ./run_pipeline.sh --submissions "A B"  # explicit submission folder names
#   ./run_pipeline.sh --static             # also run static_checks.py (clones 12 repos)
#   ./run_pipeline.sh --workers 32         # download concurrency (default 16)
#   ./run_pipeline.sh --skip-fetch         # reuse data/candidates_raw.jsonl as is
#   ./run_pipeline.sh --split full         # the 2,294-issue full test set; outputs go to data/full/
#   ./run_pipeline.sh --split lite         # the 300-issue Lite set; outputs go to data/lite/

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"

N=0
AUTO=0
SUBMISSIONS=""
STATIC=0
WORKERS=16
SKIP_FETCH=0
SEED=42
SPLIT="${TRUSTGATE_SPLIT:-verified}"

while [ $# -gt 0 ]; do
  case "$1" in
    --n)           N="$2"; shift 2 ;;
    --seed)        SEED="$2"; shift 2 ;;
    --auto)        AUTO="$2"; shift 2 ;;
    --submissions) SUBMISSIONS="$2"; shift 2 ;;
    --static)      STATIC=1; shift ;;
    --workers)     WORKERS="$2"; shift 2 ;;
    --skip-fetch)  SKIP_FETCH=1; shift ;;
    --split)       SPLIT="$2"; shift 2 ;;
    -h|--help)     sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

export TRUSTGATE_SPLIT="$SPLIT"
if [ "$SPLIT" = "verified" ]; then DATA_SUB="data"; else DATA_SUB="data/$SPLIT"; fi
echo "==> Split: $SPLIT (outputs under $DATA_SUB/)"

# 0. Environment. setup_and_run.sh creates .venv and installs everything.
if [ ! -x "$PY" ]; then
  echo "==> No .venv found, running setup_and_run.sh --no-run"
  ./setup_and_run.sh --no-run
fi

echo "==> Step 1: select issues"
"$PY" pipeline/select_issues.py --n "$N" --seed "$SEED"

echo
echo "==> Step 2a: catalog public submissions"
if [ ! -f "$DATA_SUB/submissions_catalog.csv" ] || [ "$AUTO" -gt 0 ]; then
  "$PY" pipeline/list_submissions.py --check-logs --workers "$WORKERS"
else
  echo "$DATA_SUB/submissions_catalog.csv exists, skipping (delete it to refresh)"
fi

echo
echo "==> Step 2b: fetch candidate patches and official grading reports"
if [ "$SKIP_FETCH" -eq 1 ]; then
  echo "--skip-fetch given, reusing $DATA_SUB/candidates_raw.jsonl"
elif [ -n "$SUBMISSIONS" ]; then
  # shellcheck disable=SC2086
  "$PY" pipeline/fetch_candidates.py --workers "$WORKERS" --submissions $SUBMISSIONS
elif [ "$AUTO" -gt 0 ]; then
  "$PY" pipeline/fetch_candidates.py --workers "$WORKERS" --auto "$AUTO"
else
  "$PY" pipeline/fetch_candidates.py --workers "$WORKERS"
fi

echo
echo "==> Step 3: write harness-format prediction files (for optional regrading)"
"$PY" pipeline/build_predictions.py

STATIC_ARGS=()
if [ "$STATIC" -eq 1 ]; then
  echo
  echo "==> Step 5a: static code-health checks (clones repositories under data/repos)"
  "$PY" pipeline/static_checks.py --workers 4
  STATIC_ARGS=(--static "$DATA_SUB/static_features.csv")
fi

echo
echo "==> Step 5: build the candidate table"
"$PY" pipeline/build_candidate_table.py ${STATIC_ARGS[@]+"${STATIC_ARGS[@]}"}

echo
echo "==> Done. Candidate table: $DATA_SUB/trustgate_candidate_results.csv"
if [ "$SPLIT" = "verified" ]; then
  echo "    Open the notebook with ./setup_and_run.sh and run all cells."
else
  echo "    Open the notebook with TRUSTGATE_SPLIT=$SPLIT ./setup_and_run.sh so it loads this split."
fi
