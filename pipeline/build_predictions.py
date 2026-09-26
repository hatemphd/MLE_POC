"""Step 3 - write harness-format prediction files.

The official SWE-bench harness reads a JSONL file with one object per line:

    {"instance_id": "...", "model_patch": "diff --git ...", "model_name_or_path": "..."}

It keys predictions by instance_id, so a single file can hold only one candidate
per issue. This step therefore writes one file per submission under
data/predictions/. The files are only needed if you want to regrade the public
patches yourself with run_harness.sh; the public report.json files already carry
the official grades.

What it executes:
  1. Reads data/candidates_raw.jsonl.
  2. Drops candidates with an empty patch (the harness would mark them as no-patch anyway).
  3. Writes data/predictions/<submission>.jsonl and prints the counts.

Usage:
  python pipeline/build_predictions.py
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from common import CANDIDATES_RAW_PATH, PREDICTIONS_DIR, log, read_jsonl, write_jsonl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=str(CANDIDATES_RAW_PATH))
    ap.add_argument("--out-dir", default=str(PREDICTIONS_DIR))
    args = ap.parse_args()

    rows = read_jsonl(Path(args.inp))
    by_sub: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for r in rows:
        if not (r.get("patch") or "").strip():
            skipped += 1
            continue
        by_sub[r["submission"]].append({
            "instance_id": r["instance_id"],
            "model_patch": r["patch"],
            "model_name_or_path": r["submission"],
        })

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub, preds in sorted(by_sub.items()):
        n = write_jsonl(out_dir / f"{sub}.jsonl", preds)
        log(f"  {sub}: {n} predictions")
    log(f"Skipped {skipped} candidates with empty patches")
    log(f"Wrote {len(by_sub)} prediction files to {out_dir}/")


if __name__ == "__main__":
    main()
