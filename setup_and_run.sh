#!/usr/bin/env bash
# Set up a uv-managed environment and launch the TrustGate notebook.
#
# Usage:
#   ./setup_and_run.sh            # set up env and open Jupyter
#   ./setup_and_run.sh --no-run   # set up env only
#   ./setup_and_run.sh --harness  # also install the SWE-bench evaluation harness

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTEBOOK="TrustGate_SWEBench_PoC_ML_v3.ipynb"
PYTHON_VERSION="3.11"
VENV_DIR="$PROJECT_DIR/.venv"

RUN_JUPYTER=1
INSTALL_HARNESS=0
for arg in "$@"; do
  case "$arg" in
    --no-run)  RUN_JUPYTER=0 ;;
    --harness) INSTALL_HARNESS=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

cd "$PROJECT_DIR"

# 1. Install uv if missing.
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "==> Using $(uv --version)"

# 2. Create the virtual environment with a Python new enough for
#    recent datasets/matplotlib releases (system 3.9 is too old).
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating venv with Python $PYTHON_VERSION"
  uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
else
  echo "==> Reusing existing venv at $VENV_DIR"
fi

# 3. Install dependencies. pip is included so the notebook's
#    "!pip install" cell works unmodified inside the venv.
#    pyarrow/pyyaml/requests/pyflakes are used by the pipeline/ scripts.
echo "==> Installing dependencies"
uv pip install --python "$VENV_DIR/bin/python" \
  pip jupyter datasets scikit-learn pandas numpy matplotlib \
  pyarrow pyyaml requests pyflakes anthropic openai

if [ "$INSTALL_HARNESS" -eq 1 ]; then
  echo "==> Installing SWE-bench harness"
  uv pip install --python "$VENV_DIR/bin/python" swebench
  if ! command -v docker >/dev/null 2>&1; then
    echo "WARNING: Docker not found. The harness needs Docker to grade patches." >&2
  fi
fi

# 3b. Versioned git hooks: stamp the notebook with VERSION + date on every commit.
if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ -d "$PROJECT_DIR/.githooks" ]; then
  git -C "$PROJECT_DIR" config core.hooksPath .githooks
  echo "==> Git hooks enabled (.githooks/pre-commit stamps the notebook)"
fi

# 4. Sanity check.
echo "==> Verifying imports"
"$VENV_DIR/bin/python" - <<'PY'
import sys, datasets, sklearn, pandas, numpy, matplotlib
print(f"python     {sys.version.split()[0]}")
print(f"datasets   {datasets.__version__}")
print(f"sklearn    {sklearn.__version__}")
print(f"pandas     {pandas.__version__}")
print(f"numpy      {numpy.__version__}")
print(f"matplotlib {matplotlib.__version__}")
PY

# 5. Launch.
if [ "$RUN_JUPYTER" -eq 1 ]; then
  echo "==> Launching Jupyter"
  exec "$VENV_DIR/bin/jupyter" notebook "$NOTEBOOK"
else
  echo "==> Done. Activate with: source $VENV_DIR/bin/activate"
fi
