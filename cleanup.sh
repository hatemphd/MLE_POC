#!/usr/bin/env bash
# Remove generated files from the TrustGate project.
#
# Usage:
#   ./cleanup.sh              # remove venv, notebook checkpoints, caches, harness logs
#   ./cleanup.sh --data       # also delete pipeline downloads: data/raw, data/repos, data/_experiments
#   ./cleanup.sh --hf-cache   # also delete the Hugging Face datasets cache (~/.cache/huggingface)
#   ./cleanup.sh --docker     # also remove SWE-bench Docker images and containers
#   ./cleanup.sh --all        # everything above
#   ./cleanup.sh --dry-run    # show what would be removed without deleting
#
# The final CSVs under data/ (trustgate_candidate_results.csv, candidates_raw.jsonl,
# submissions_catalog.csv, selected_instances.json) are never touched.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

CLEAN_HF=0
CLEAN_DOCKER=0
CLEAN_DATA=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --data)     CLEAN_DATA=1 ;;
    --hf-cache) CLEAN_HF=1 ;;
    --docker)   CLEAN_DOCKER=1 ;;
    --all)      CLEAN_DATA=1; CLEAN_HF=1; CLEAN_DOCKER=1 ;;
    --dry-run)  DRY_RUN=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

remove() {
  local target="$1"
  if [ -e "$target" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "would remove: $target"
    else
      echo "removing: $target"
      rm -rf "$target"
    fi
  fi
}

echo "==> Project-local artifacts"
remove "$PROJECT_DIR/.venv"
remove "$PROJECT_DIR/logs"
remove "$PROJECT_DIR/evaluation_results"
find "$PROJECT_DIR" -path "$PROJECT_DIR/.venv" -prune -o \
  -type d \( -name ".ipynb_checkpoints" -o -name "__pycache__" \) -prune -print0 2>/dev/null \
  | while IFS= read -r -d '' dir; do remove "$dir"; done
find "$PROJECT_DIR" -maxdepth 1 -type f -name "*.run_evaluation.log" -print0 2>/dev/null \
  | while IFS= read -r -d '' f; do remove "$f"; done
find "$PROJECT_DIR" -path "$PROJECT_DIR/.venv" -prune -o \
  -type f -name ".DS_Store" -print0 2>/dev/null \
  | while IFS= read -r -d '' f; do remove "$f"; done

if [ "$CLEAN_DATA" -eq 1 ]; then
  echo "==> Pipeline downloads (patch/report cache, repo clones)"
  remove "$PROJECT_DIR/data/raw"
  remove "$PROJECT_DIR/data/repos"
  remove "$PROJECT_DIR/data/_experiments"
  remove "$PROJECT_DIR/data/predictions"
fi

if [ "$CLEAN_HF" -eq 1 ]; then
  echo "==> Hugging Face datasets cache"
  HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
  remove "$HF_HOME/datasets"
fi

if [ "$CLEAN_DOCKER" -eq 1 ]; then
  echo "==> SWE-bench Docker images and containers"
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found, skipping"
  else
    containers=$(docker ps -a --filter "name=sweb." --format '{{.ID}}' 2>/dev/null || true)
    images=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E '^sweb\.' || true)
    if [ "$DRY_RUN" -eq 1 ]; then
      [ -n "$containers" ] && echo "would remove containers:" && echo "$containers"
      [ -n "$images" ] && echo "would remove images:" && echo "$images"
    else
      [ -n "$containers" ] && echo "$containers" | xargs docker rm -f
      [ -n "$images" ] && echo "$images" | xargs docker rmi -f
    fi
    [ -z "$containers$images" ] && echo "no SWE-bench containers or images found"
  fi
fi

echo "==> Done"
