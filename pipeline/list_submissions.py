"""Step 2a - catalog the public SWE-bench Verified leaderboard submissions.

The SWE-bench/experiments repository holds one folder per submitted system. Each
folder has a metadata.yaml that names the system and points at its logs, which
live in the public S3 bucket swe-bench-submissions (older entries) or in the
submitter's own GitHub repository (entries from mid-2026 on).

What it executes:
  1. Lists evaluation/verified/ in github.com/SWE-bench/experiments through the
     GitHub API (one request). If the API is rate limited it falls back to a
     sparse, blob-less git clone under data/_experiments/.
  2. Downloads each submission's metadata.yaml from raw.githubusercontent.com.
  3. Reads the resolve rate from metadata, or from results/results.json, or from
     per_instance_details.json, whichever the submission provides.
  4. With --check-logs, lists each S3 log folder to count instances that have logs.
  5. Writes data/submissions_catalog.csv sorted by resolve rate.

Usage:
  python pipeline/list_submissions.py
  python pipeline/list_submissions.py --check-logs --workers 16
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import subprocess

import pandas as pd

from common import (
    CATALOG_PATH,
    DATA_DIR,
    EXPERIMENTS_API,
    EXPERIMENTS_GIT,
    EXPERIMENTS_RAW,
    EXPERIMENTS_SPLIT_DIR,
    SPLIT,
    load_swebench,
    log,
    make_session,
    read_submission_metadata,
    s3_list,
    s3_prefix_from_uri,
    summarize_metadata,
)


def list_names_api(session) -> list[str]:
    resp = session.get(f"{EXPERIMENTS_API}/evaluation/{EXPERIMENTS_SPLIT_DIR}", timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API returned {resp.status_code}: {resp.text[:200]}")
    return sorted(x["name"] for x in resp.json() if x["type"] == "dir")


def list_names_git() -> list[str]:
    clone = DATA_DIR / "_experiments"
    if not clone.exists():
        log("Falling back to a sparse git clone of SWE-bench/experiments")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", EXPERIMENTS_GIT, str(clone)],
            check=True,
        )
        subprocess.run(["git", "-C", str(clone), "sparse-checkout", "set", f"evaluation/{EXPERIMENTS_SPLIT_DIR}"], check=True)
    return sorted(p.name for p in (clone / "evaluation" / EXPERIMENTS_SPLIT_DIR).iterdir() if p.is_dir())


def fetch_resolved_pct(session, name: str, meta_pct, n_total: int) -> float:
    if meta_pct is not None:
        return float(meta_pct)
    base = f"{EXPERIMENTS_RAW}/evaluation/{EXPERIMENTS_SPLIT_DIR}/{name}"
    resp = session.get(f"{base}/results/results.json", timeout=60)
    if resp.status_code == 200:
        try:
            return 100.0 * len(resp.json().get("resolved", [])) / n_total
        except ValueError:
            pass
    resp = session.get(f"{base}/per_instance_details.json", timeout=60)
    if resp.status_code == 200:
        try:
            details = resp.json()
            return 100.0 * sum(1 for v in details.values() if v.get("resolved")) / n_total
        except (ValueError, AttributeError):
            pass
    return float("nan")


def catalog_row(session, name: str, check_logs: bool, n_total: int) -> dict:
    meta = read_submission_metadata(session, name)
    row = summarize_metadata(name, meta)
    row["resolved_pct"] = fetch_resolved_pct(session, name, row["resolved_pct"], n_total)
    row["logs_instances"] = None
    if check_logs and row["logs_source"] == "s3":
        try:
            _, prefixes = s3_list(session, s3_prefix_from_uri(row["logs_uri"]) + "/", delimiter="/")
            row["logs_instances"] = len(prefixes)
        except Exception as exc:  # noqa: BLE001
            row["logs_instances"] = 0
            row["logs_error"] = str(exc)[:200]
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(CATALOG_PATH))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--check-logs", action="store_true", help="count instances with logs in S3 (slower)")
    args = ap.parse_args()

    session = make_session()
    try:
        names = list_names_api(session)
    except Exception as exc:  # noqa: BLE001
        log(f"GitHub API listing failed: {exc}")
        names = list_names_git()
    n_total = len(load_swebench())
    log(f"Found {len(names)} submissions under evaluation/{EXPERIMENTS_SPLIT_DIR}/ (split '{SPLIT}', {n_total} issues)")

    rows = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(catalog_row, session, n, args.check_logs, n_total): n for n in names}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            try:
                rows.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log(f"  {futures[fut]}: failed ({exc})")
            if i % 25 == 0:
                log(f"  {i}/{len(names)} submissions processed")

    cat = pd.DataFrame(rows).sort_values("resolved_pct", ascending=False).reset_index(drop=True)
    CATALOG_PATH.__class__(args.out).parent.mkdir(parents=True, exist_ok=True)
    cat.to_csv(args.out, index=False)

    show = ["submission", "agent", "model", "resolved_pct", "logs_source"]
    if args.check_logs:
        show.append("logs_instances")
    log("\nStrongest 10 submissions:")
    log(cat[show].head(10).to_string(index=False))
    log("\nWeakest 10 submissions:")
    log(cat[show].tail(10).to_string(index=False))
    log(f"\nLog sources: {cat['logs_source'].value_counts().to_dict()}")
    log(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
