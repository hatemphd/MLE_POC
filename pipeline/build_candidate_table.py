"""Step 5 - turn raw candidates and grading reports into the notebook's candidate table.

What it executes:
  1. Reads data/candidates_raw.jsonl (patch + official report per candidate).
  2. Optionally replaces reports with ones you regraded locally (--local-reports).
  3. Optionally joins code-health features from static_checks.py (--static).
  4. Derives, per candidate:
       resolved_status     FULL / PARTIAL / NO, using the harness definition:
                           FULL    = every FAIL_TO_PASS and PASS_TO_PASS test passed
                           PARTIAL = some FAIL_TO_PASS passed and all PASS_TO_PASS passed
                           NO      = anything else, including a patch that did not apply
       label               1 only for FULL, else 0
       fail_to_pass_rate   passed / total over the issue's FAIL_TO_PASS tests
       pass_to_pass_rate   passed / total over the issue's PASS_TO_PASS tests
       patch_apply_ok      from the report (or from static_checks.py when available)
       self_consistency    mean similarity of this patch to the other candidates for the
                           same issue: 0.5 * Jaccard(touched files) + 0.5 * line-level ratio
       evaluation_error    set when no report exists (log folder missing or unparseable);
                           these rows are kept OUT of the training CSV by default
  5. Drops candidates with an empty patch (they are not PR candidates) unless --keep-empty.
  6. Writes data/trustgate_candidate_results.csv with exactly the notebook's
     CANDIDATE_COLUMNS, and data/trustgate_candidate_evaluation_errors.csv for the
     rows that could not be graded.
  7. Prints the label balance, per-agent resolve rate, and whether the notebook's
     training gate (>=100 rows, >=50 issues, both labels) is satisfied.

Columns intentionally left empty (NaN) because the public data does not carry them:
  temperature, visible_test_pass_rate, visible_test_fail_count, ci_job_failure_count,
  ci_job_success_rate, model_confidence

Usage:
  python pipeline/build_candidate_table.py
  python pipeline/build_candidate_table.py --static data/static_features.csv
  python pipeline/build_candidate_table.py --local-reports logs/run_evaluation/trustgate-v1
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
    CANDIDATE_COLUMNS,
    CANDIDATE_TABLE_PATH,
    CANDIDATES_RAW_PATH,
    EVAL_ERRORS_PATH,
    added_lines,
    load_swebench,
    log,
    patch_touched_files,
    read_jsonl,
)


def rate(bucket: dict | None):
    if not bucket:
        return np.nan, 0
    ok, bad = len(bucket.get("success", [])), len(bucket.get("failure", []))
    total = ok + bad
    return (ok / total if total else np.nan), total


def grade(report: dict | None, patch_nonempty: bool) -> dict:
    """Map one harness report.json entry to status, label and diagnostic rates."""
    out = {"patch_apply_ok": np.nan, "resolved_status": None, "fail_to_pass_rate": np.nan,
           "pass_to_pass_rate": np.nan, "evaluation_error": None, "label": np.nan}
    if report is None:
        out["evaluation_error"] = "missing_report"
        return out

    applied = bool(report.get("patch_successfully_applied"))
    out["patch_apply_ok"] = int(applied)
    tests = report.get("tests_status") or {}
    f2p, f2p_total = rate(tests.get("FAIL_TO_PASS"))
    p2p, p2p_total = rate(tests.get("PASS_TO_PASS"))
    out["fail_to_pass_rate"], out["pass_to_pass_rate"] = f2p, p2p

    if not applied:
        out["resolved_status"], out["label"] = "NO", 0
        return out
    if report.get("resolved"):
        out["resolved_status"], out["label"] = "FULL", 1
        return out
    p2p_clean = (p2p_total == 0) or (p2p == 1.0)
    if f2p_total and 0 < f2p < 1 and p2p_clean:
        out["resolved_status"] = "PARTIAL"
    else:
        out["resolved_status"] = "NO"
    out["label"] = 0
    return out


def self_consistency(patches: list[str]) -> list[float]:
    """For each patch, the mean similarity to the other patches of the same issue."""
    n = len(patches)
    if n < 2:
        return [np.nan] * n
    files = [patch_touched_files(p) for p in patches]
    lines = [added_lines(p) for p in patches]
    sims = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            jac = len(files[i] & files[j]) / len(files[i] | files[j]) if (files[i] | files[j]) else 0.0
            ratio = difflib.SequenceMatcher(None, lines[i], lines[j], autojunk=False).ratio()
            sims[i, j] = sims[j, i] = 0.5 * jac + 0.5 * ratio
    return [float(sims[i].sum() / (n - 1)) for i in range(n)]


def load_local_reports(root: Path) -> dict[str, dict]:
    """Read report.json files written by `swebench eval` under logs/run_evaluation/<run_id>/."""
    found: dict[str, dict] = {}
    for path in root.rglob("report.json"):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        model = path.parent.parent.name
        for iid, rep in data.items():
            found[f"{model}::{iid}"] = rep
    log(f"Loaded {len(found)} local reports from {root}")
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=str(CANDIDATES_RAW_PATH))
    ap.add_argument("--out", default=str(CANDIDATE_TABLE_PATH))
    ap.add_argument("--errors-out", default=str(EVAL_ERRORS_PATH))
    ap.add_argument("--static", default=None, help="static_features.csv from static_checks.py")
    ap.add_argument("--local-reports", default=None, help="logs/run_evaluation/<run_id> from your own harness run")
    ap.add_argument("--keep-empty", action="store_true", help="keep candidates whose patch is empty")
    ap.add_argument("--include-errors", action="store_true", help="keep ungraded rows in the main CSV")
    args = ap.parse_args()

    raw = read_jsonl(Path(args.inp))
    log(f"Read {len(raw)} raw candidates")

    local = load_local_reports(Path(args.local_reports)) if args.local_reports else {}

    records = []
    empty = 0
    for r in raw:
        patch = r.get("patch") or ""
        if not patch.strip() and not args.keep_empty:
            empty += 1
            continue
        report = local.get(r["candidate_id"], r.get("report"))
        rec = {
            "instance_id": r["instance_id"],
            "candidate_id": r["candidate_id"],
            "agent_name": r.get("agent_name"),
            "model_name": r.get("model_name"),
            "temperature": np.nan,
            "patch": patch,
            "syntax_ok": np.nan, "compile_ok": np.nan, "lint_warning_count": np.nan,
            "static_error_count": np.nan, "undefined_name_count": np.nan, "import_error_count": np.nan,
            "visible_test_pass_rate": np.nan, "visible_test_fail_count": np.nan,
            "ci_job_failure_count": np.nan, "ci_job_success_rate": np.nan,
            "self_consistency": np.nan, "model_confidence": np.nan,
        }
        rec.update(grade(report, bool(patch.strip())))
        if r.get("fetch_error") and rec["evaluation_error"]:
            rec["evaluation_error"] = f"fetch_error: {r['fetch_error']}"
        records.append(rec)
    log(f"Dropped {empty} candidates with empty patches")

    df = pd.DataFrame(records)

    # Agreement between independent attempts on the same issue.
    for iid, grp in df.groupby("instance_id"):
        df.loc[grp.index, "self_consistency"] = self_consistency(grp["patch"].tolist())

    # Code-health features from static_checks.py, when available.
    if args.static and Path(args.static).exists():
        st = pd.read_csv(args.static).drop_duplicates("candidate_id", keep="last").set_index("candidate_id")
        cols = ["syntax_ok", "compile_ok", "lint_warning_count", "static_error_count",
                "undefined_name_count", "import_error_count"]
        joined = df["candidate_id"].map(lambda c: st[cols].loc[c] if c in st.index else pd.Series(index=cols, dtype=float))
        for c in cols:
            df[c] = [row[c] for row in joined]
        # Prefer the local apply check where the report had nothing to say.
        local_apply = df["candidate_id"].map(st["patch_apply_ok"] if "patch_apply_ok" in st else {})
        df["patch_apply_ok"] = df["patch_apply_ok"].fillna(local_apply)
        log(f"Joined static features for {df['syntax_ok'].notna().sum()} candidates")

    errors = df[df["evaluation_error"].notna()]
    main_df = df if args.include_errors else df[df["evaluation_error"].isna()]

    main_df = main_df[CANDIDATE_COLUMNS]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    main_df.to_csv(args.out, index=False)
    errors[CANDIDATE_COLUMNS].to_csv(args.errors_out, index=False)

    # ---------------------------------------------------------------- summary
    swe = load_swebench()[["instance_id", "repo", "difficulty"]]
    m = main_df.merge(swe, on="instance_id", how="left")
    log(f"\nWrote {len(main_df)} graded candidates to {args.out}")
    log(f"Wrote {len(errors)} ungraded candidates to {args.errors_out}")
    log(f"Issues covered: {main_df['instance_id'].nunique()}  repositories: {m['repo'].nunique()}")
    log("\nLabel balance:")
    log(main_df["label"].value_counts(dropna=False).rename({0: "0 (not resolved)", 1: "1 (FULL)"}).to_string())
    log("\nresolved_status:")
    log(main_df["resolved_status"].value_counts(dropna=False).to_string())
    log("\nResolve rate by agent:")
    log(main_df.groupby("agent_name")["label"].agg(["count", "mean"]).sort_values("mean").to_string())
    log("\nResolve rate by difficulty:")
    log(m.groupby("difficulty")["label"].agg(["count", "mean"]).to_string())

    ok = (len(main_df) >= 100 and main_df["instance_id"].nunique() >= 50
          and main_df["label"].notna().all() and main_df["label"].nunique() == 2)
    log("\nNotebook training gate (>=100 rows, >=50 issues, both labels): " + ("PASS" if ok else "NOT MET"))


if __name__ == "__main__":
    main()
