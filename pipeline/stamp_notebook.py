"""Stamp the notebook with a version, release date and branch.

Called by .githooks/pre-commit on every commit, so the first cell of the
notebook and its metadata always show which version of the project it belongs
to. Uses only the standard library so it runs with any Python 3.

What it executes:
  1. Reads Major.Minor from the VERSION file (or --version).
  2. Takes today's date (or --date) and the current git branch, if any.
  3. Rewrites the line marked <!-- version-stamp --> in the badge cell at the top
     of the notebook, creating it if absent.
  4. Records the same values in notebook metadata under "trustgate".

Usage:
  python pipeline/stamp_notebook.py                 # VERSION file + today
  python pipeline/stamp_notebook.py --version 1.1 --date 2026-10-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "TrustGate_SWEBench_PoC_ML_v3.ipynb"
VERSION_FILE = ROOT / "VERSION"
MARK = "<!-- version-stamp -->"


def git_branch() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="Major.Minor; default from the VERSION file")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; default today")
    ap.add_argument("--notebook", default=str(NOTEBOOK))
    args = ap.parse_args()

    version = args.version or (VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "0.0")
    released = args.date or dt.date.today().isoformat()
    branch = git_branch()

    nb_path = Path(args.notebook)
    nb = json.loads(nb_path.read_text())
    line = f"{MARK} **Version** {version} · **Released** {released}" + (f" · **Branch** {branch}" if branch else "") + "\n"

    cells = nb["cells"]
    target = next((c for c in cells if c["cell_type"] == "markdown" and "colab-badge" in "".join(c["source"])), None)
    if target is None:
        target = {"cell_type": "markdown", "id": "verstamp", "metadata": {}, "source": []}
        cells.insert(0, target)
    src = "".join(target["source"]).splitlines(keepends=True)
    src = [l for l in src if MARK not in l]
    # Stamp goes right under the badge lines, before the first blank line.
    insert_at = next((i for i, l in enumerate(src) if l.strip() == ""), len(src))
    src.insert(insert_at, line)
    target["source"] = src

    nb.setdefault("metadata", {})["trustgate"] = {"version": version, "released": released, "branch": branch}
    nb_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    print(f"stamped {nb_path.name}: version {version}, released {released}" + (f", branch {branch}" if branch else ""))


if __name__ == "__main__":
    main()
