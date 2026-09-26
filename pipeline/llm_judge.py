"""LLM judge for the ceiling experiment (TrustGateExperimentation.ipynb, experiment 2).

Asks a foundation model to read the bug report and a candidate patch and give a
probability that the patch fully resolves the issue, BEFORE any test result is
known. The score is then evaluated exactly like any other feature. This is a
one-off ceiling measurement, not the production method: it costs money, needs an
API key, and the judge may recognise patches written by its own model family or
repositories it saw in training.

Design choices that keep it honest and cheap:
  - Only the validation and test candidates are scored (about 2,000 on Verified).
    The judge is evaluated on test, and any combination with TrustGate is fitted on
    validation only. Training rows are never needed.
  - Requests go through the Message Batches API at half price.
  - Structured JSON output, effort "low", no sampling parameters (Claude Opus 5 rules).
  - Scores are cached on disk so the API is called once.

Usage (from the repository root, with ANTHROPIC_API_KEY set or `ant auth login` done):
  python pipeline/llm_judge.py estimate                       # cost table, no API call
  python pipeline/llm_judge.py submit --model claude-opus-5   # creates the batch, writes ids
  python pipeline/llm_judge.py collect                        # polls, writes scores
  python pipeline/llm_judge.py status                         # batch progress
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CANDIDATE_TABLE_PATH, DATA_DIR, SPLIT, SWEBENCH_CACHE, log  # noqa: E402

JUDGE_DIR = DATA_DIR / "llm_judge"
BATCHES_PATH = JUDGE_DIR / f"{SPLIT}_batches.json"
SCORES_PATH = JUDGE_DIR / f"{SPLIT}_scores.jsonl"

DEFAULT_MODEL = "claude-opus-5"
# USD per million tokens, standard price; the Batches API charges half.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
MAX_ISSUE_CHARS = 6000
MAX_PATCH_CHARS = 14000
MAX_OUTPUT_TOKENS = 400

SYSTEM = (
    "You are a senior software engineer reviewing a proposed patch for a GitHub issue. "
    "Judge only from the issue text and the diff. Do not rely on recognising the repository, "
    "the issue, or the eventual accepted fix. Estimate the probability that this exact patch fully "
    "resolves the issue and would pass the maintainers' tests, without breaking existing behaviour. "
    "Be calibrated: 0.5 means genuinely unsure."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "p_correct": {"type": "number", "description": "Probability in [0, 1] that the patch fully resolves the issue."},
        "main_reason": {"type": "string", "description": "One sentence, at most 200 characters."},
    },
    "required": ["p_correct", "main_reason"],
    "additionalProperties": False,
}


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated, {len(text) - limit} more characters]"


def build_prompt(issue_text: str, patch: str) -> str:
    return (
        "## Issue\n" + _truncate(issue_text, MAX_ISSUE_CHARS)
        + "\n\n## Proposed patch (unified diff)\n```diff\n" + _truncate(patch, MAX_PATCH_CHARS) + "\n```\n\n"
        "Return JSON with p_correct and main_reason."
    )


def scope_rows(scope: str = "val_test") -> pd.DataFrame:
    """Candidates to score: the notebook's validation + test issues by default."""
    from sklearn.model_selection import GroupShuffleSplit

    df = pd.read_csv(CANDIDATE_TABLE_PATH)
    if scope == "all":
        rows = df
    else:
        g1 = GroupShuffleSplit(n_splits=1, train_size=0.6, random_state=42)
        _, tmp = next(g1.split(df, groups=df["instance_id"]))
        rows = df.iloc[tmp]
    swe = pd.read_parquet(SWEBENCH_CACHE).set_index("instance_id")
    rows = rows.copy()
    rows["issue_text"] = rows["instance_id"].map(swe["problem_statement"]).fillna("")
    return rows.reset_index(drop=True)


def estimate_cost(rows: pd.DataFrame) -> pd.DataFrame:
    prompts = [build_prompt(i, p) for i, p in zip(rows["issue_text"], rows["patch"].fillna(""))]
    in_tokens = sum(len(SYSTEM) + len(p) for p in prompts) / 3.5  # rough chars-per-token for code-heavy text
    out_tokens = len(rows) * 120
    table = []
    for model, (pin, pout) in PRICES.items():
        std = in_tokens / 1e6 * pin + out_tokens / 1e6 * pout
        table.append({"model": model, "candidates": len(rows), "input_tokens_est": int(in_tokens),
                      "standard_usd": round(std, 2), "batch_usd": round(std / 2, 2)})
    return pd.DataFrame(table)


def _client():
    import anthropic

    try:
        return anthropic.Anthropic()
    except anthropic.AnthropicError as exc:  # missing credentials surfaces here or on first call
        raise SystemExit(f"Anthropic client could not be created: {exc}\nSet ANTHROPIC_API_KEY or run `ant auth login`.")


def submit(rows: pd.DataFrame, model: str = DEFAULT_MODEL, chunk: int = 5000) -> list[str]:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = _client()
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    already = set()
    if SCORES_PATH.exists():
        already = {json.loads(l)["candidate_id"] for l in open(SCORES_PATH) if l.strip()}
    todo = rows[~rows["candidate_id"].isin(already)]
    log(f"{len(todo)} candidates to score with {model} ({len(already)} already cached)")
    ids: list[str] = []
    for start in range(0, len(todo), chunk):
        part = todo.iloc[start:start + chunk]
        requests = [
            Request(
                custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=SYSTEM,
                    messages=[{"role": "user", "content": build_prompt(issue, patch or "")}],
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                ),
            )
            for cid, issue, patch in zip(part["candidate_id"], part["issue_text"], part["patch"])
        ]
        batch = client.messages.batches.create(requests=requests)
        ids.append(batch.id)
        log(f"  batch {batch.id}: {len(requests)} requests, status {batch.processing_status}")
    meta = {"model": model, "batch_ids": ids, "submitted": time.strftime("%Y-%m-%d %H:%M:%S")}
    if BATCHES_PATH.exists():
        old = json.loads(BATCHES_PATH.read_text())
        meta["batch_ids"] = old.get("batch_ids", []) + ids
    BATCHES_PATH.write_text(json.dumps(meta, indent=2))
    return ids


def status() -> None:
    client = _client()
    meta = json.loads(BATCHES_PATH.read_text())
    for bid in meta["batch_ids"]:
        b = client.messages.batches.retrieve(bid)
        c = b.request_counts
        log(f"{bid}: {b.processing_status}  processing={c.processing} succeeded={c.succeeded} errored={c.errored}")


def collect(wait: bool = True, poll_seconds: int = 60) -> pd.DataFrame:
    client = _client()
    meta = json.loads(BATCHES_PATH.read_text())
    scores: dict[str, dict] = {}
    if SCORES_PATH.exists():
        for l in open(SCORES_PATH):
            if l.strip():
                r = json.loads(l)
                scores[r["candidate_id"]] = r
    for bid in meta["batch_ids"]:
        while True:
            b = client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                break
            if not wait:
                log(f"{bid} still {b.processing_status}; rerun collect later")
                return pd.DataFrame(scores.values())
            log(f"{bid}: {b.processing_status}, {b.request_counts.processing} processing; waiting {poll_seconds}s")
            time.sleep(poll_seconds)
        for res in client.messages.batches.results(bid):
            cid = res.custom_id
            rec = {"candidate_id": cid, "model": meta["model"], "p_judge": None, "reason": None, "status": res.result.type}
            if res.result.type == "succeeded":
                msg = res.result.message
                if msg.stop_reason == "refusal":
                    rec["status"] = "refusal"
                else:
                    text = next((blk.text for blk in msg.content if blk.type == "text"), "")
                    try:
                        data = json.loads(text)
                        rec["p_judge"] = float(min(1.0, max(0.0, data["p_correct"])))
                        rec["reason"] = str(data.get("main_reason", ""))[:300]
                    except (ValueError, KeyError, TypeError):
                        rec["status"] = "unparseable"
                        rec["reason"] = text[:300]
            scores[cid] = rec
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCORES_PATH, "w") as fh:
        for r in scores.values():
            fh.write(json.dumps(r) + "\n")
    out = pd.DataFrame(scores.values())
    log(f"{len(out)} scores written to {SCORES_PATH}; usable: {int(out['p_judge'].notna().sum())}")
    return out


def load_scores() -> pd.DataFrame | None:
    if not SCORES_PATH.exists():
        return None
    return pd.DataFrame([json.loads(l) for l in open(SCORES_PATH) if l.strip()])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["estimate", "submit", "status", "collect"])
    ap.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(PRICES))
    ap.add_argument("--scope", default="val_test", choices=["val_test", "all"])
    ap.add_argument("--no-wait", action="store_true")
    args = ap.parse_args()
    if args.action == "estimate":
        print(estimate_cost(scope_rows(args.scope)).to_string(index=False))
    elif args.action == "submit":
        submit(scope_rows(args.scope), args.model)
    elif args.action == "status":
        status()
    else:
        collect(wait=not args.no_wait)


if __name__ == "__main__":
    main()
