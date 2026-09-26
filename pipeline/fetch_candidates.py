"""Step 2b - download candidate patches and their official grading reports.

Instead of generating patches with a coding agent and grading them ourselves, this
step reuses the patches that leaderboard systems submitted for SWE-bench Verified,
together with the report.json the official harness produced for each one. Every
submission contributes one candidate per issue, so eight submissions give up to
eight independently generated candidates per issue.

What it executes, per submission:
  1. Reads metadata.yaml to find where the logs live (S3 bucket or GitHub repo).
  2. Lists logs/ to learn which instances have artifacts, then intersects with the
     issues chosen by select_issues.py.
  3. Downloads logs/<instance_id>/patch.diff and logs/<instance_id>/report.json
     over HTTPS (no AWS credentials needed) into data/raw/<submission>/<instance_id>/.
     Already-downloaded instances are skipped, so reruns are cheap.
  4. Appends one row per (submission, instance) to data/candidates_raw.jsonl with
     the patch text and the parsed report.

Choosing submissions:
  --submissions A B C      explicit folder names from evaluation/verified/
  --auto K                 pick K submissions from data/submissions_catalog.csv spread
                           across weak-to-strong resolve rates and distinct agent families
  (neither)                use DEFAULT_SUBMISSIONS below

Usage:
  python pipeline/fetch_candidates.py
  python pipeline/fetch_candidates.py --auto 10 --workers 24
  python pipeline/fetch_candidates.py --submissions 20250522_tools_claude-4-sonnet 20241028_agentless-1.5_gpt4o
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
    SPLIT,
    CANDIDATES_RAW_PATH,
    CATALOG_PATH,
    RAW_DIR,
    SELECTED_PATH,
    load_selected_instances,
    load_swebench,
    log,
    make_session,
    read_submission_metadata,
    s3_get_text,
    s3_list,
    s3_prefix_from_uri,
    summarize_metadata,
    write_jsonl,
)

# Default submissions per split. Verified: ten systems chosen to balance model
# families (Claude, GPT, Gemini, Qwen, Kimi, GLM, Llama, undisclosed) and to span
# weak to strong. Full (2,294 issues): every system that published logs for the
# full test set; there are far fewer because a full run is expensive.
DEFAULT_SUBMISSIONS_BY_SPLIT = {
    "verified": [
        "20240620_sweagent_claude3.5sonnet",
        "20250522_tools_claude-4-sonnet",
        "20241028_agentless-1.5_gpt4o",
        "20250807_openhands_gpt5",
        "20251120_livesweagent_gemini-3-pro-preview",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20251014_Lingxi_kimi_k2",
        "20241202_amazon-q-developer-agent-20241202-dev",
        "20250930_zai_glm4-6",
        "20250720_mini-v0.0.0-Llama-4-Scout-17B-Instruct",
    ],
    "full": [
        "20251219_sonar-foundation-agent_claude-opus-4-5",
        "20251027_salesforce_SAGE",
        "20250605_atlassian-rovo-dev",
        "20250227_sweagent-claude-3-7-20250219",
        "20250131_amazon-q-developer-agent-20241202-dev",
        "20241103_OpenHands-CodeAct-2.1-sonnet-20241022",
        "20241121_autocoderover-v2.0-claude-3-5-sonnet-20241022",
        "20240820_honeycomb",
        "20240620_sweagent_claude3.5sonnet",
        "20240728_sweagent_gpt4o",
    ],
    "lite": [],
}


def choose_auto(catalog: pd.DataFrame, k: int) -> list[str]:
    """Pick k submissions spread across resolve-rate quantiles with distinct agent families."""
    c = catalog[catalog["logs_source"].isin(["s3", "repo"])].dropna(subset=["resolved_pct"])
    if "logs_instances" in c.columns:
        c = c[c["logs_instances"].isna() | (c["logs_instances"] > 0)]
    c = c.sort_values("resolved_pct").reset_index(drop=True)
    chosen: list[str] = []
    families: set[tuple] = set()
    for chunk in np.array_split(c.index.values, min(k, len(c))):
        block = c.loc[chunk].sort_values("date", ascending=False)
        pick = next((r for _, r in block.iterrows() if (r["agent"], r["org"]) not in families), None)
        if pick is None:
            pick = block.iloc[0]
        chosen.append(pick["submission"])
        families.add((pick["agent"], pick["org"]))
    return chosen


def resolve_logs(session, name: str):
    """Return (catalog_row, ("s3", prefix) | ("local", path) | None)."""
    meta = read_submission_metadata(session, name)
    if not meta:
        log(f"  {name}: no metadata.yaml found, skipping")
        return None, None
    row = summarize_metadata(name, meta)
    if row["logs_source"] == "s3":
        return row, ("s3", s3_prefix_from_uri(row["logs_uri"]))
    if row["logs_source"] == "repo":
        clone = RAW_DIR / "_repos" / name
        if not clone.exists():
            log(f"  {name}: cloning {row['repo_uri']}")
            clone.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", row["repo_uri"], str(clone)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                log(f"  {name}: clone failed: {proc.stderr.strip()[:200]}")
                return row, None
        return row, ("local", clone / "logs")
    log(f"  {name}: logs are not publicly hosted, skipping")
    return row, None


def available_instances(session, source) -> set[str]:
    kind, base = source
    if kind == "s3":
        _, prefixes = s3_list(session, f"{base}/", delimiter="/")
        return {p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes}
    return {p.name for p in Path(base).iterdir() if p.is_dir()}


def fetch_one(session, source, iid: str, dest: Path) -> dict:
    """Download patch.diff and report.json for one instance, caching on disk."""
    meta_path = dest / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    dest.mkdir(parents=True, exist_ok=True)
    kind, base = source
    got = {}
    for fn in ("patch.diff", "report.json"):
        if kind == "s3":
            text = s3_get_text(session, f"{base}/{iid}/{fn}")
        else:
            p = Path(base) / iid / fn
            text = p.read_text(errors="replace") if p.exists() else None
        if text is not None:
            (dest / fn).write_text(text)
        got[fn] = text is not None
    meta = {"instance_id": iid, "has_patch": got["patch.diff"], "has_report": got["report.json"]}
    meta_path.write_text(json.dumps(meta))
    return meta


def parse_report(text: str | None, iid: str):
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        if iid in data:
            return data[iid]
        if len(data) == 1 and isinstance(next(iter(data.values())), dict):
            return next(iter(data.values()))
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submissions", nargs="*", default=None)
    ap.add_argument("--auto", type=int, default=0, help="pick this many submissions from the catalog")
    ap.add_argument("--catalog", default=str(CATALOG_PATH))
    ap.add_argument("--instances", default=str(SELECTED_PATH))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=str(CANDIDATES_RAW_PATH))
    args = ap.parse_args()

    session = make_session()

    selected = load_selected_instances(Path(args.instances))
    if selected is None:
        selected = sorted(load_swebench()["instance_id"].tolist())
        log(f"No {args.instances}; using all {len(selected)} instances")
    else:
        log(f"Using {len(selected)} selected instances from {args.instances}")
    selected_set = set(selected)

    if args.submissions:
        names = args.submissions
    elif args.auto > 0:
        if not Path(args.catalog).exists():
            raise SystemExit(f"--auto needs {args.catalog}; run list_submissions.py first")
        names = choose_auto(pd.read_csv(args.catalog), args.auto)
        log(f"Auto-selected {len(names)} submissions: {names}")
    else:
        names = DEFAULT_SUBMISSIONS_BY_SPLIT.get(SPLIT) or []
        if not names:
            raise SystemExit(f"No default submissions for split '{SPLIT}'; pass --submissions or --auto K")
        log(f"Using {len(names)} default submissions for split '{SPLIT}'")

    # Resolve each submission and enumerate the download tasks.
    plan = []  # (row, source, [instance_ids])
    for name in names:
        row, source = resolve_logs(session, name)
        if source is None:
            continue
        avail = available_instances(session, source)
        targets = sorted(selected_set & avail)
        log(f"  {name}: {len(avail)} instances with logs, {len(targets)} selected")
        plan.append((row, source, targets))

    tasks = [(row["submission"], source, iid) for row, source, targets in plan for iid in targets]
    log(f"\nFetching {len(tasks)} instance folders with {args.workers} workers")

    failures: dict[tuple, str] = {}
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {
            pool.submit(fetch_one, session, source, iid, RAW_DIR / sub / iid): (sub, iid)
            for sub, source, iid in tasks
        }
        for i, fut in enumerate(cf.as_completed(futures), 1):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                failures[futures[fut]] = str(exc)[:200]
            if i % 250 == 0 or i == len(futures):
                log(f"  {i}/{len(futures)} fetched")
    if failures:
        log(f"  {len(failures)} downloads failed (recorded as fetch_error)")

    # Assemble the raw candidate rows from the on-disk cache.
    rows = []
    summary = []
    for row, source, targets in plan:
        sub = row["submission"]
        n_patch = n_report = n_resolved = 0
        for iid in targets:
            d = RAW_DIR / sub / iid
            patch_path, report_path = d / "patch.diff", d / "report.json"
            patch = patch_path.read_text(errors="replace") if patch_path.exists() else None
            report = parse_report(report_path.read_text() if report_path.exists() else None, iid)
            n_patch += bool(patch and patch.strip())
            n_report += report is not None
            n_resolved += bool(report and report.get("resolved"))
            rows.append({
                "instance_id": iid,
                "candidate_id": f"{sub}::{iid}",
                "submission": sub,
                "agent_name": row["agent"],
                "model_name": row["model"],
                "org": row["org"],
                "attempts": row["attempts"],
                "patch": patch,
                "report": report,
                "fetch_error": failures.get((sub, iid)),
            })
        summary.append({"submission": sub, "rows": len(targets), "with_patch": n_patch,
                        "with_report": n_report, "resolved": n_resolved})

    n = write_jsonl(Path(args.out), rows)
    log("\nPer-submission summary:")
    log(pd.DataFrame(summary).to_string(index=False))
    log(f"\nWrote {n} candidate rows to {args.out}")


if __name__ == "__main__":
    main()
