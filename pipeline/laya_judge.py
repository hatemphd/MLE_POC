"""Laya judge: a System One decision model scoring patches (experiment 3).

Laya (convaiinnovations/laya, Apache 2.0) is a non-autoregressive decision model:
give it a state and typed questions, get calibrated probabilities in one forward
pass. Here the state is the issue text plus the diff and the question is a single
noul (yes/no): does this patch fully fix the issue. The probability is written in
the same scores format as the LLM judges, so TrustGateExperimentation.ipynb
evaluates it identically.

Runs locally on the CPU; no API key. Needs the dedicated environment because
torch on Intel macOS is built against NumPy 1:
    ./setup_and_run.sh --laya            # creates .venv-laya once
    .venv-laya/bin/python pipeline/laya_judge.py run
    .venv-laya/bin/python pipeline/laya_judge.py run --model multilingual --max-len 4096   # slower, reads more of the diff

Checkpoints (chosen with --model):
    english          convaiinnovations/laya            ModernBERT-large, 512 tokens
    typed-decisions  laya-typed-decisions              ModernBERT-large, 1024 tokens
    multilingual     laya-multilingual                 mmBERT-base, up to 8192 tokens (default; our
                                                       issue+patch averages about 1,000 tokens)

Zero-shot is expected to be weak, by Laya's own benchmark card. The follow-up is
fine-tuning on the training issues with the published Kaggle notebook and
rescoring. `export-finetune` writes our labelled candidates in the dataset schema
that notebook consumes (data/llm_judge/finetune/laya_finetune_<split>_{train,val,test}.jsonl).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, SPLIT, log  # noqa: E402
from llm_judge import MAX_ISSUE_CHARS, MAX_PATCH_CHARS, _truncate, scope_rows  # noqa: E402

JUDGE_DIR = DATA_DIR / "llm_judge"
CHECKPOINTS = {
    "english": ("convaiinnovations/laya", None, 512),
    "typed-decisions": ("convaiinnovations/laya", "typed-decisions", 1024),
    "multilingual": ("convaiinnovations/laya", "multilingual", 8192),
}
QUESTIONS = {
    "fixes_issue": {
        "type": "noul",
        "instructions": (
            "Does the proposed patch fully and correctly fix the issue described, so that the "
            "project's tests for this issue would pass without breaking existing behaviour?"
        ),
    }
}


def scores_path(model: str) -> Path:
    return JUDGE_DIR / f"{SPLIT}_scores_laya-{model}.jsonl"


def build_state(issue: str, patch: str) -> dict:
    return {"issue": _truncate(issue, MAX_ISSUE_CHARS), "patch": _truncate(patch or "", MAX_PATCH_CHARS)}


def run(model: str, scope: str, max_len: int | None, batch: int, limit: int = 0) -> pd.DataFrame:
    from laya import Agent

    repo, subfolder, ctx = CHECKPOINTS[model]
    max_len = min(max_len or ctx, ctx)
    rows = scope_rows(scope)
    out_path = scores_path(model)
    done: dict[str, dict] = {}
    if out_path.exists():
        for l in open(out_path):
            if l.strip():
                r = json.loads(l); done[r["candidate_id"]] = r
    todo = rows[~rows["candidate_id"].isin(done)]
    if limit:
        todo = todo.head(limit)
    log(f"Laya {model} (max_len {max_len}): {len(todo)} candidates to score, {len(done)} cached -> {out_path}")
    if not len(todo):
        return pd.DataFrame(done.values())

    agent = Agent(repo, subfolder=subfolder, device="cpu")
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(out_path, "a") as fh:
        for start in range(0, len(todo), batch):
            part = todo.iloc[start:start + batch]
            states = [build_state(i, p) for i, p in zip(part["issue_text"], part["patch"])]
            try:
                results = agent.predict_batch(states, QUESTIONS, max_len=max_len)
            except Exception:  # noqa: BLE001 - fall back to one at a time
                results = [agent.predict(s, QUESTIONS, max_len=max_len) for s in states]
            for cid, res in zip(part["candidate_id"], results):
                ans = (res.get("answers") or {}).get("fixes_issue") or {}
                p = ans.get("noul")
                rec = {"candidate_id": cid, "model": f"laya-{model}", "p_judge": None if p is None else float(p),
                       "reason": None, "status": "succeeded" if p is not None else "no_answer",
                       "escalate": ans.get("escalate") if isinstance(ans, dict) else None}
                fh.write(json.dumps(rec) + "\n"); done[cid] = rec
            fh.flush()
            n = start + len(part)
            if n % (batch * 10) == 0 or n == len(todo):
                rate = n / max(1e-9, time.time() - t0)
                log(f"  {n}/{len(todo)} scored, {rate:.2f}/s, about {(len(todo) - n) / max(rate, 1e-9) / 60:.0f} min left")
    df = pd.DataFrame(done.values())
    log(f"{len(df)} scores in {out_path}; usable {int(df['p_judge'].notna().sum())}")
    return df


def export_finetune(out_dir: Path) -> dict:
    """Write our labelled candidates in the LocalLLaMA/typed-decisions schema Laya's
    Kaggle fine-tuning notebook consumes: one JSON line per case with state, questions
    and gold as JSON strings. Train rows carry the harness label as a hard noul target;
    val is for calibration; test is held out and must never be trained on."""
    from sklearn.model_selection import GroupShuffleSplit

    from common import CANDIDATE_TABLE_PATH, SWEBENCH_CACHE

    df = pd.read_csv(CANDIDATE_TABLE_PATH)
    swe = pd.read_parquet(SWEBENCH_CACHE).set_index("instance_id")
    g1 = GroupShuffleSplit(n_splits=1, train_size=0.6, random_state=42)
    tr, tmp = next(g1.split(df, groups=df["instance_id"]))
    temp = df.iloc[tmp]
    g2 = GroupShuffleSplit(n_splits=1, train_size=0.5, random_state=43)
    va, te = next(g2.split(temp, groups=temp["instance_id"]))
    parts = {"train": df.iloc[tr], "val": temp.iloc[va], "test": temp.iloc[te]}
    questions = {
        "fixes_issue": {
            "type": "noul",
            "instructions": QUESTIONS["fixes_issue"]["instructions"],
            "criteria": {"true": "The patch fully resolves the issue and the issue's tests would pass.",
                         "false": "The patch does not fully resolve the issue or breaks existing behaviour."},
        }
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, part in parts.items():
        path = out_dir / f"laya_finetune_{SPLIT}_{name}.jsonl"
        with open(path, "w") as fh:
            for r in part.itertuples(index=False):
                issue = swe["problem_statement"].get(r.instance_id, "")
                label = int(r.label)
                case = {
                    "id": r.candidate_id,
                    "workflow": "trustgate_patch_review",
                    "split": name,
                    "state": json.dumps(build_state(issue, r.patch if isinstance(r.patch, str) else "")),
                    "questions": json.dumps(questions),
                    "gold": json.dumps({"fixes_issue": {"type": "noul", "label": "true" if label else "false",
                                                        "noul": float(label), "confidence": 1.0,
                                                        "probabilities": {"true": float(label), "false": float(1 - label)}}}),
                    "factors": json.dumps({"instance_id": r.instance_id, "agent": r.agent_name}),
                    "label_agreement": 1.0,
                    "n_questions": 1,
                }
                fh.write(json.dumps(case) + "\n")
        counts[name] = len(part)
        log(f"  {name}: {len(part)} cases -> {path}")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["run", "status", "export-finetune"])
    ap.add_argument("--model", default="multilingual", choices=sorted(CHECKPOINTS))
    ap.add_argument("--scope", default="val_test", choices=["val_test", "all"])
    ap.add_argument("--max-len", type=int, default=1024, help="tokens read per state; capped by the checkpoint. "
                    "On this Intel Mac CPU: about 30 s per candidate at 4096, a few seconds at 1024")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="score only this many (smoke test)")
    args = ap.parse_args()
    if args.action == "export-finetune":
        export_finetune(JUDGE_DIR / "finetune")
        return
    if args.action == "status":
        p = scores_path(args.model)
        n = sum(1 for l in open(p) if l.strip()) if p.exists() else 0
        print(f"{p}: {n} scored")
        return
    run(args.model, args.scope, args.max_len, args.batch, args.limit)


if __name__ == "__main__":
    main()
