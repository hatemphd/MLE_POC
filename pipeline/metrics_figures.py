"""Score the exported gate on the notebook's test split and draw the metric figures for METRICS.md.

What it executes:
  1. Loads data/<split>/trustgate_candidate_results.csv and reproduces the notebook's
     issue-grouped 60/20/20 split (same seeds), keeping the test part.
  2. Loads models/trustgate_gate_<split>.joblib, rebuilds the features the bundle
     expects (diff shape, TF-IDF similarity via the saved vectorizer, text flags),
     and produces calibrated probabilities.
  3. Computes the confusion matrix at 0.5, accuracy, precision, recall, specificity,
     F1, ROC-AUC, PR-AUC, Brier, ECE, and the approve/reject bucket precisions.
  4. Writes docs/figures/metrics_<split>_test.json and six PNGs.

Usage:
  python pipeline/metrics_figures.py
  TRUSTGATE_SPLIT=full python pipeline/metrics_figures.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score, brier_score_loss, confusion_matrix, precision_recall_curve, roc_auc_score, roc_curve,
)
from sklearn.model_selection import GroupShuffleSplit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CANDIDATE_TABLE_PATH, ROOT, SPLIT, SWEBENCH_CACHE, log, unified_diff_stats  # noqa: E402

FIG_DIR = ROOT / "docs" / "figures"
TEAL, CORAL, PURPLE, INK, GRID, MUTED = "#1D9E75", "#D85A30", "#7F77DD", "#1B2A2F", "#E3E8EA", "#888780"
plt.rcParams.update({
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "figure.dpi": 150,
})


def notebook_test_split(df: pd.DataFrame) -> pd.DataFrame:
    g1 = GroupShuffleSplit(n_splits=1, train_size=0.6, random_state=42)
    _, tmp = next(g1.split(df, groups=df["instance_id"]))
    temp = df.iloc[tmp]
    g2 = GroupShuffleSplit(n_splits=1, train_size=0.5, random_state=43)
    _, te = next(g2.split(temp, groups=temp["instance_id"]))
    return temp.iloc[te].copy().reset_index(drop=True)


def added_text(patch: str) -> str:
    return "\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))


def ece_bins(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    total, rows = 0.0, []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
            rows.append({"lo": float(edges[i]), "hi": float(edges[i + 1]), "n": int(m.sum()),
                         "mean_p": float(p[m].mean()), "observed": float(y[m].mean())})
    return total, rows


def main() -> None:
    df = pd.read_csv(CANDIDATE_TABLE_PATH)
    test = notebook_test_split(df)
    test = pd.concat([test, pd.DataFrame([unified_diff_stats(x) for x in test["patch"].fillna("")])], axis=1)

    bundle = joblib.load(ROOT / "models" / f"trustgate_gate_{SPLIT}.joblib")
    swe = pd.read_parquet(SWEBENCH_CACHE).set_index("instance_id")
    issue = test["instance_id"].map(swe["problem_statement"]).fillna("")
    if bundle.get("vectorizer") is not None:
        a = bundle["vectorizer"].transform(issue)
        b = bundle["vectorizer"].transform(test["patch"].fillna("").map(added_text))
        test["issue_patch_tfidf_sim"] = np.asarray(a.multiply(b).sum(axis=1)).ravel()
    test["issue_chars_log"] = np.log1p(issue.str.len().values)
    test["patch_touches_test_file"] = test["patch"].fillna("").str.contains(r"^\+\+\+ b/.*test", flags=re.M, regex=True).astype(int)

    y = test["label"].astype(int).values
    p = bundle["model"].predict_proba(test[bundle["features"]])[:, 1]
    if bundle.get("calibrator") is not None:
        p = bundle["calibrator"].predict(p)
    appr, rej = bundle["approve_threshold"], bundle["reject_threshold"]

    def cm(th):
        tn, fp, fn, tp = confusion_matrix(y, (p >= th).astype(int), labels=[0, 1]).ravel()
        return tp, fp, fn, tn

    tp, fp, fn, tn = cm(0.5)
    prec, rec, spec = tp / (tp + fp), tp / (tp + fn), tn / (tn + fp)
    ece, bins = ece_bins(y, p)
    approved, rejected = p >= appr, p <= rej
    reviewed = ~approved & ~rejected
    gate = {
        "approve": {"share": float(approved.mean()), "precision": float(y[approved].mean()) if approved.any() else None,
                    "n": int(approved.sum()), "correct": int(y[approved].sum()), "wrong": int((1 - y[approved]).sum())},
        "reject": {"share": float(rejected.mean()), "precision": float(1 - y[rejected].mean()) if rejected.any() else None,
                   "n": int(rejected.sum()), "correct": int((1 - y[rejected]).sum()), "wrong": int(y[rejected].sum())},
        "human_review": {"share": float(reviewed.mean()), "n": int(reviewed.sum()), "works": int(y[reviewed].sum()),
                         "broken": int((1 - y[reviewed]).sum())},
        "automatic_decision_coverage": float((approved | rejected).mean()),
        "false_approval_rate": float(1 - y[approved].mean()) if approved.any() else None,
        "false_rejection_rate": float(y[rejected].mean()) if rejected.any() else None,
    }
    metrics = {
        "split": SPLIT, "n": int(len(y)), "positives": int(y.sum()), "positive_rate": float(y.mean()),
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "accuracy": float((tp + tn) / len(y)), "precision": float(prec), "recall": float(rec),
        "specificity": float(spec), "f1": float(2 * prec * rec / (prec + rec)),
        "roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)), "brier_constant_baseline": float(np.mean((y - y.mean()) ** 2)),
        "ece": float(ece), "approve_threshold": float(appr), "reject_threshold": float(rej), "gate": gate,
        "majority_class_accuracy": float(max(y.mean(), 1 - y.mean())), "bins": bins,
    }
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    (FIG_DIR / f"metrics_{SPLIT}_test.json").write_text(json.dumps(metrics, indent=2))
    log(json.dumps({k: v for k, v in metrics.items() if k != "bins"}, indent=1))

    # Confusion matrix
    fig, ax = plt.subplots(figsize=(5.4, 4.3)); ax.grid(False)
    mat = np.array([[tp, fn], [fp, tn]])
    labels = [["True positive\napproved, and it works", "False negative\nrejected, but it works"],
              ["False positive\napproved, but it is broken", "True negative\nrejected, and it is broken"]]
    for i in range(2):
        for j in range(2):
            col = TEAL if i == j else CORAL
            ax.add_patch(plt.Rectangle((j, 1 - i), 1, 1, facecolor=col, alpha=0.18 + 0.55 * mat[i, j] / mat.max(), edgecolor="white", lw=3))
            ax.text(j + 0.5, 1 - i + 0.62, f"{mat[i, j]}", ha="center", va="center", fontsize=21, color=INK, fontweight="bold")
            ax.text(j + 0.5, 1 - i + 0.27, labels[i][j], ha="center", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, 2); ax.set_ylim(0, 2)
    ax.set_xticks([0.5, 1.5]); ax.set_xticklabels(["Model says: works (p ≥ 0.5)", "Model says: broken (p < 0.5)"])
    ax.set_yticks([1.5, 0.5]); ax.set_yticklabels(["Truly works", "Truly broken"], rotation=90, va="center")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Confusion matrix at threshold 0.5, {SPLIT} test split, {len(y)} patches", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "confusion_matrix.png"); plt.close(fig)

    # Threshold sweep
    ths = np.linspace(0.05, 0.95, 91); P, R, S = [], [], []
    for t in ths:
        a, b_, c, d = cm(t)
        P.append(a / (a + b_) if a + b_ else np.nan); R.append(a / (a + c)); S.append(d / (d + b_))
    fig, ax = plt.subplots(figsize=(6.6, 3.9))
    ax.plot(ths, P, color=TEAL, lw=2, label="Precision"); ax.plot(ths, R, color=CORAL, lw=2, label="Recall"); ax.plot(ths, S, color=PURPLE, lw=2, label="Specificity")
    for t, lab in ((rej, f"reject ≤ {rej:.2f}"), (appr, f"approve ≥ {appr:.2f}")):
        ax.axvline(t, color=INK, lw=0.8, ls=":"); ax.text(t, 1.03, lab, ha="center", fontsize=8, color=INK)
    ax.set_xlabel("Decision threshold on P(patch works)"); ax.set_ylabel("Rate"); ax.set_ylim(0, 1.1); ax.set_xlim(0.05, 0.97)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    ax.set_title("Precision, recall and specificity as the threshold moves", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "threshold_sweep.png"); plt.close(fig)

    # ROC
    fpr, tpr, thr = roc_curve(y, p)
    fig, ax = plt.subplots(figsize=(4.8, 4.5))
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls="--", label="Coin flip, AUC 0.50")
    ax.plot(fpr, tpr, color=TEAL, lw=2, label=f"TrustGate, AUC {metrics['roc_auc']:.2f}")
    i5 = int(np.argmin(np.abs(thr - 0.5))); ax.plot(fpr[i5], tpr[i5], "o", color=CORAL, ms=8, zorder=3)
    ax.annotate("threshold 0.5", (fpr[i5], tpr[i5]), textcoords="offset points", xytext=(10, -12), fontsize=8, color=INK)
    ax.set_xlabel("False positive rate = 1 − specificity"); ax.set_ylabel("True positive rate = recall")
    ax.legend(frameon=False, fontsize=9, loc="lower right"); ax.set_title("ROC curve: every threshold at once", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "roc_curve.png"); plt.close(fig)

    # PR
    pr, rc, _ = precision_recall_curve(y, p)
    fig, ax = plt.subplots(figsize=(4.8, 4.5))
    ax.axhline(y.mean(), color=MUTED, lw=1, ls="--", label=f"Random guessing, precision {y.mean():.2f}")
    ax.plot(rc, pr, color=TEAL, lw=2, label=f"TrustGate, PR-AUC {metrics['pr_auc']:.2f}")
    ax.set_xlabel("Recall"); ax.set_ylabel("Precision"); ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=9, loc="lower left"); ax.set_title("Precision-recall curve", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "pr_curve.png"); plt.close(fig)

    # Reliability
    fig, ax = plt.subplots(figsize=(4.8, 4.5))
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls="--", label="Perfect calibration")
    xs = [r["mean_p"] for r in bins]; ys = [r["observed"] for r in bins]; ns = [r["n"] for r in bins]
    ax.plot(xs, ys, "-", color=TEAL, lw=2)
    ax.scatter(xs, ys, s=[25 + n / 3 for n in ns], color=TEAL, edgecolor="white", zorder=3, label="Observed, size = patches in bin")
    for x_, y_, n in zip(xs, ys, ns):
        ax.annotate(str(n), (x_, y_), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=7, color=INK)
    ax.set_xlabel("Mean predicted probability in the bin"); ax.set_ylabel("Share of patches that actually worked")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.set_title(f"Reliability diagram, ECE {ece:.3f}, Brier {metrics['brier']:.3f}", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "reliability.png"); plt.close(fig)

    # Probability histogram, side-by-side bars
    fig, ax = plt.subplots(figsize=(6.6, 3.7)); edges = np.linspace(0, 1, 21)
    ax.hist([p[y == 1], p[y == 0]], bins=edges, color=[TEAL, CORAL],
            label=[f"Patches that work, n={int(y.sum())}", f"Patches that fail, n={int((1 - y).sum())}"], rwidth=0.9)
    top = ax.get_ylim()[1]
    for t in (rej, appr):
        ax.axvline(t, color=INK, lw=0.8, ls=":")
    ax.text(rej - 0.01, top * 0.95, "auto-reject", ha="right", fontsize=8, color=INK)
    ax.text((rej + appr) / 2, top * 0.95, "human review", ha="center", fontsize=8, color=INK)
    ax.text(appr + 0.01, top * 0.95, "auto-approve", ha="left", fontsize=8, color=INK)
    ax.set_xlabel("Predicted P(patch works)"); ax.set_ylabel("Patches"); ax.legend(frameon=False, fontsize=9)
    ax.set_title("Where the two classes land, and where the gate cuts", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "probability_histogram.png"); plt.close(fig)
    # Gate outcomes: the three buckets and what was inside each
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    buckets = [("Auto-approve\n(p ≥ %.2f)" % appr, gate["approve"]["correct"], gate["approve"]["wrong"]),
               ("Human review", gate["human_review"]["works"], gate["human_review"]["broken"]),
               ("Auto-reject\n(p ≤ %.2f)" % rej, gate["reject"]["correct"], gate["reject"]["wrong"])]
    xs = np.arange(3); w = 0.38
    good = [b[1] for b in buckets]; bad = [b[2] for b in buckets]
    # For approve, "good" = correct approvals (patch works); for reject, "good" = correct rejections (patch broken).
    # For review there is no decision, so show the mix of what a human would see.
    ax.bar(xs - w / 2, good, w, color=TEAL, label="decision correct  /  works (review)")
    ax.bar(xs + w / 2, bad, w, color=CORAL, label="decision wrong  /  broken (review)")
    for x_, g_, b_ in zip(xs, good, bad):
        ax.text(x_ - w / 2, g_ + 4, str(g_), ha="center", fontsize=8, color=INK); ax.text(x_ + w / 2, b_ + 4, str(b_), ha="center", fontsize=8, color=INK)
    shares = [gate["approve"]["share"], gate["human_review"]["share"], gate["reject"]["share"]]
    ax.set_xticks(xs); ax.set_xticklabels([f"{b[0]}\n{s_:.0%} of patches" for b, s_ in zip(buckets, shares)], fontsize=8.5)
    ax.set_ylabel("Patches"); ax.legend(frameon=False, fontsize=8.5)
    ax.set_title(f"What the gate did with {len(y)} test patches", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(FIG_DIR / "gate_outcomes.png"); plt.close(fig)
    log(f"figures written to {FIG_DIR}")


if __name__ == "__main__":
    main()
