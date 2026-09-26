"""Score a candidate patch with the exported TrustGate model.

Notebook cell 19.6 saves the best model, its feature list, the frozen thresholds
and (if used) the TF-IDF vectorizer to models/trustgate_gate.joblib. This script
loads that bundle, computes the same features for a new patch, and prints the
probability and the three-way decision.

What it executes:
  1. Loads the joblib bundle.
  2. Computes patch-shape features from the diff text (same function as the notebook).
  3. If sibling patches are given, computes self_consistency against them
     (agreement between independent attempts at the same issue).
  4. If the issue text is given and the model uses semantic features, computes the
     TF-IDF similarity with the saved vectorizer.
  5. Any feature it cannot compute (code health, CI) is left NaN; gradient boosting
     handles NaN natively and the logistic pipeline imputes the median.
  6. Prints p_correct and approve / human_review / reject.

Usage:
  python pipeline/score_patch.py --patch fix.diff
  python pipeline/score_patch.py --patch fix.diff --issue issue.txt --sibling a.diff --sibling b.diff
  python pipeline/score_patch.py --patch fix.diff --feature syntax_ok=1 --feature lint_warning_count=0 --json

From Python:
  from score_patch import load_bundle, score_patch
  result = score_patch(open("fix.diff").read(), issue_text="...", siblings=[...])
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_candidate_table import self_consistency  # noqa: E402
from common import ROOT, SPLIT, unified_diff_stats  # noqa: E402

# One bundle per benchmark split; TRUSTGATE_SPLIT picks it (default verified).
DEFAULT_BUNDLE = ROOT / "models" / f"trustgate_gate_{SPLIT}.joblib"


def load_bundle(path: Path = DEFAULT_BUNDLE) -> dict:
    if not Path(path).exists():
        raise SystemExit(f"No model bundle at {path}. Run the notebook through cell 19.8 first (TRUSTGATE_SPLIT={SPLIT}).")
    return joblib.load(path)


def added_text(patch: str) -> str:
    return "\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))


def features_for(patch: str, bundle: dict, issue_text: str | None = None,
                 siblings: list[str] | None = None, overrides: dict | None = None) -> pd.DataFrame:
    feats: dict = {f: np.nan for f in bundle["features"]}
    feats.update(unified_diff_stats(patch))
    if siblings:
        feats["self_consistency"] = self_consistency([patch] + list(siblings))[0]
    if issue_text is not None:
        feats["issue_chars_log"] = math.log1p(len(issue_text))
        vec = bundle.get("vectorizer")
        if vec is not None:
            a = vec.transform([issue_text])
            b = vec.transform([added_text(patch)])
            feats["issue_patch_tfidf_sim"] = float(a.multiply(b).sum())
    feats["patch_touches_test_file"] = int(bool(re.search(r"^\+\+\+ b/.*test", patch, flags=re.MULTILINE)))
    feats["patch_apply_ok"] = feats.get("patch_apply_ok", np.nan)
    if overrides:
        feats.update(overrides)
    return pd.DataFrame([{f: feats.get(f, np.nan) for f in bundle["features"]}])


def score_patch(patch: str, issue_text: str | None = None, siblings: list[str] | None = None,
                overrides: dict | None = None, bundle: dict | None = None) -> dict:
    bundle = bundle or load_bundle()
    X = features_for(patch, bundle, issue_text, siblings, overrides)
    p = float(bundle["model"].predict_proba(X)[0, 1])
    if bundle.get("calibrator") is not None:
        p = float(bundle["calibrator"].predict([p])[0])
    if p >= bundle["approve_threshold"]:
        decision = "approve"
    elif p <= bundle["reject_threshold"]:
        decision = "reject"
    else:
        decision = "human_review"
    return {
        "p_correct": round(p, 4),
        "decision": decision,
        "approve_threshold": bundle["approve_threshold"],
        "reject_threshold": bundle["reject_threshold"],
        "model": f"{bundle['model_type']} on '{bundle['feature_set']}'",
        "features": {k: (None if pd.isna(v) else float(v)) for k, v in X.iloc[0].items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", required=True, help="unified diff file")
    ap.add_argument("--issue", help="text file with the issue / bug report")
    ap.add_argument("--sibling", action="append", default=[], help="other candidate diffs for the same issue (repeatable)")
    ap.add_argument("--feature", action="append", default=[], help="override a feature, e.g. syntax_ok=1")
    ap.add_argument("--model", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--json", action="store_true", help="print JSON only")
    args = ap.parse_args()

    bundle = load_bundle(Path(args.model))
    patch = Path(args.patch).read_text(errors="replace")
    issue = Path(args.issue).read_text(errors="replace") if args.issue else None
    siblings = [Path(s).read_text(errors="replace") for s in args.sibling]
    overrides = {}
    for kv in args.feature:
        k, v = kv.split("=", 1)
        overrides[k] = float(v)

    result = score_patch(patch, issue, siblings, overrides, bundle)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"model      : {result['model']}")
    print(f"p_correct  : {result['p_correct']:.3f}")
    print(f"decision   : {result['decision'].upper()}   "
          f"(approve >= {result['approve_threshold']:.2f}, reject <= {result['reject_threshold']:.2f})")
    print("features   :")
    for k, v in result["features"].items():
        print(f"  {k:<26} {'NaN' if v is None else round(v, 4)}")
    if not siblings:
        print("note: no --sibling patches given, so self_consistency is NaN; "
              "pass the other candidates for the same issue for the strongest signal.")


if __name__ == "__main__":
    main()
