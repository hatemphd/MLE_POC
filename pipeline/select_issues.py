"""Step 1 - choose which SWE-bench Verified issues to include.

What it executes:
  1. Loads SWE-bench Verified (500 rows) from Hugging Face, cached as parquet under data/.
  2. Optionally filters to specific repositories (--repos).
  3. Draws a stratified sample of --n issues across (repo, difficulty) so every
     stratum keeps at least one issue. --n 0 (the default) keeps all 500.
  4. Writes data/selected_instances.json with the chosen instance_ids and coverage
     tables, and prints the coverage by repository and by difficulty.

Usage:
  python pipeline/select_issues.py                 # all 500 issues
  python pipeline/select_issues.py --n 200 --seed 7
  python pipeline/select_issues.py --repos django/django sympy/sympy
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd

from common import DATASET_NAMES, SELECTED_PATH, load_swebench, log


def stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Proportional allocation across (repo, difficulty) with a floor of one per stratum."""
    strata = df.groupby(["repo", "difficulty"], dropna=False)
    sizes = strata.size()
    raw = sizes * n / sizes.sum()
    alloc = raw.apply(math.floor).clip(lower=1)
    alloc = pd.Series(np.minimum(alloc.values, sizes.values), index=sizes.index)

    diff = n - int(alloc.sum())
    remainders = (raw - raw.apply(math.floor)).sort_values(ascending=False)
    for key in remainders.index:
        if diff == 0:
            break
        if diff > 0 and alloc[key] < sizes[key]:
            alloc[key] += 1
            diff -= 1
        elif diff < 0 and alloc[key] > 1:
            alloc[key] -= 1
            diff += 1
    while diff < 0:  # n smaller than the number of strata
        key = alloc.idxmax()
        alloc[key] -= 1
        diff += 1

    rng = np.random.default_rng(seed)
    parts = []
    for key, group in strata:
        k = int(alloc[key])
        if k > 0:
            idx = rng.choice(group.index.values, size=k, replace=False)
            parts.append(df.loc[idx])
    return pd.concat(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=0, help="number of issues to select (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--repos", nargs="*", default=None, help="restrict to these repositories")
    ap.add_argument("--out", default=str(SELECTED_PATH))
    args = ap.parse_args()

    df = load_swebench()
    log(f"Loaded {len(df)} SWE-bench Verified tasks, {df['repo'].nunique()} repositories")

    if args.repos:
        df = df[df["repo"].isin(args.repos)]
        log(f"Filtered to {len(df)} tasks in {args.repos}")

    if args.n <= 0 or args.n >= len(df):
        chosen = df
        log(f"Selecting all {len(chosen)} tasks")
    else:
        chosen = stratified_sample(df, args.n, args.seed)
        log(f"Selected {len(chosen)} tasks with a stratified sample (seed={args.seed})")

    by_repo = chosen["repo"].value_counts().sort_index()
    by_diff = chosen["difficulty"].astype(str).value_counts().sort_index()

    payload = {
        "dataset": DATASET_NAMES[0],
        "n": int(len(chosen)),
        "seed": args.seed,
        "repos_filter": args.repos,
        "instance_ids": sorted(chosen["instance_id"].tolist()),
        "coverage_by_repo": by_repo.to_dict(),
        "coverage_by_difficulty": by_diff.to_dict(),
    }
    out = SELECTED_PATH.__class__(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    log("\nCoverage by repository:")
    log(by_repo.to_string())
    log("\nCoverage by difficulty:")
    log(by_diff.to_string())
    log(f"\nWrote {out}")


if __name__ == "__main__":
    main()
