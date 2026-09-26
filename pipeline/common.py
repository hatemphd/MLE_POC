"""Shared helpers for the TrustGate candidate-label pipeline.

Every step imports from this module so that paths, network helpers, and the
candidate schema are defined exactly once.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ----------------------------------------------------------------- which benchmark split
# TRUSTGATE_SPLIT selects the SWE-bench variant. "verified" (500 issues, default) keeps
# its outputs directly under data/; the others get their own sub-folder so runs never
# overwrite each other. The notebook reads the same variable.
SPLIT = os.environ.get("TRUSTGATE_SPLIT", "verified").lower()
SPLIT_CONFIG = {
    "verified": {
        "datasets": ["SWE-bench/SWE-bench_Verified", "princeton-nlp/SWE-bench_Verified"],
        "experiments_dir": "verified",
        "data_subdir": "",
    },
    "full": {
        "datasets": ["SWE-bench/SWE-bench", "princeton-nlp/SWE-bench"],
        "experiments_dir": "test",
        "data_subdir": "full",
    },
    "lite": {
        "datasets": ["SWE-bench/SWE-bench_Lite", "princeton-nlp/SWE-bench_Lite"],
        "experiments_dir": "lite",
        "data_subdir": "lite",
    },
}
if SPLIT not in SPLIT_CONFIG:
    raise SystemExit(f"TRUSTGATE_SPLIT must be one of {sorted(SPLIT_CONFIG)}, got {SPLIT!r}")
DATASET_NAMES = SPLIT_CONFIG[SPLIT]["datasets"]
EXPERIMENTS_SPLIT_DIR = SPLIT_CONFIG[SPLIT]["experiments_dir"]

# ----------------------------------------------------------------- local paths
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / SPLIT_CONFIG[SPLIT]["data_subdir"] if SPLIT_CONFIG[SPLIT]["data_subdir"] else ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                 # per-submission, per-instance download cache
REPOS_DIR = ROOT / "data" / "repos"        # git clones used only by static_checks.py; shared across splits
PREDICTIONS_DIR = DATA_DIR / "predictions"  # harness-format JSONL, one file per submission

SWEBENCH_CACHE = DATA_DIR / f"swebench_{SPLIT}.parquet"
SELECTED_PATH = DATA_DIR / "selected_instances.json"
CATALOG_PATH = DATA_DIR / "submissions_catalog.csv"
CANDIDATES_RAW_PATH = DATA_DIR / "candidates_raw.jsonl"
STATIC_FEATURES_PATH = DATA_DIR / "static_features.csv"
CANDIDATE_TABLE_PATH = DATA_DIR / "trustgate_candidate_results.csv"
EVAL_ERRORS_PATH = DATA_DIR / "trustgate_candidate_evaluation_errors.csv"

# ----------------------------------------------------------------- remote sources
EXPERIMENTS_RAW = "https://raw.githubusercontent.com/SWE-bench/experiments/main"
EXPERIMENTS_API = "https://api.github.com/repos/SWE-bench/experiments/contents"
EXPERIMENTS_GIT = "https://github.com/SWE-bench/experiments.git"
S3_BUCKET = "swe-bench-submissions"
S3_BASE = f"https://{S3_BUCKET}.s3.amazonaws.com"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# Identical to CANDIDATE_COLUMNS in the notebook. The CSV is written in exactly
# this order so the notebook's schema check passes without edits.
CANDIDATE_COLUMNS = [
    "instance_id",
    "candidate_id",
    "agent_name",
    "model_name",
    "temperature",
    "patch",
    "patch_apply_ok",
    "syntax_ok",
    "compile_ok",
    "lint_warning_count",
    "static_error_count",
    "undefined_name_count",
    "import_error_count",
    "visible_test_pass_rate",
    "visible_test_fail_count",
    "ci_job_failure_count",
    "ci_job_success_rate",
    "self_consistency",
    "model_confidence",
    "resolved_status",
    "fail_to_pass_rate",
    "pass_to_pass_rate",
    "evaluation_error",
    "label",
]


def log(msg: str) -> None:
    print(msg, flush=True)


# ----------------------------------------------------------------- HTTP
def make_session(total_retries: int = 5) -> requests.Session:
    """A requests session with retries and a larger connection pool."""
    retry = Retry(
        total=total_retries,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = "trustgate-pipeline/1.0"
    return session


# ----------------------------------------------------------------- SWE-bench dataset
def load_swebench(force: bool = False) -> pd.DataFrame:
    """Load SWE-bench Verified (500 rows) and cache a parquet copy under data/."""
    if SWEBENCH_CACHE.exists() and not force:
        return pd.read_parquet(SWEBENCH_CACHE)
    log(f"Downloading SWE-bench split '{SPLIT}' ({DATASET_NAMES[0]})")

    from datasets import load_dataset

    last_error: Exception | None = None
    for name in DATASET_NAMES:
        try:
            ds = load_dataset(name, split="test")
            break
        except Exception as exc:  # noqa: BLE001 - try the mirror next
            last_error = exc
            log(f"load_dataset({name}) failed: {exc}")
    else:
        raise RuntimeError(f"Could not load SWE-bench Verified: {last_error}")

    df = ds.to_pandas()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SWEBENCH_CACHE, index=False)
    log(f"Cached SWE-bench {SPLIT} ({len(df)} rows) at {SWEBENCH_CACHE}")
    return df


def load_selected_instances(path: Path = SELECTED_PATH) -> list[str] | None:
    """Return the instance ids chosen by select_issues.py, or None if not run."""
    if not Path(path).exists():
        return None
    return list(json.loads(Path(path).read_text())["instance_ids"])


# ----------------------------------------------------------------- diff helpers
def unified_diff_stats(patch_text: str | None) -> dict:
    """Same definition as the notebook so features agree across both."""
    patch_text = patch_text or ""
    lines = patch_text.splitlines()
    additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    files = re.findall(r"^\+\+\+ b/(.+)$", patch_text, flags=re.MULTILINE)
    hunks = len(re.findall(r"^@@", patch_text, flags=re.MULTILINE))
    return {
        "patch_additions": additions,
        "patch_deletions": deletions,
        "patch_files": len(set(files)),
        "patch_hunks": hunks,
        "patch_chars": len(patch_text),
    }


def patch_touched_files(patch_text: str) -> set[str]:
    files = set(re.findall(r"^\+\+\+ b/(.+)$", patch_text, flags=re.MULTILINE))
    files |= {
        m.group(2)
        for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch_text, flags=re.MULTILINE)
    }
    return files


def added_lines(patch_text: str) -> list[str]:
    return [
        l[1:].strip()
        for l in patch_text.splitlines()
        if l.startswith("+") and not l.startswith("+++") and l[1:].strip()
    ]


# ----------------------------------------------------------------- S3 (public bucket, no credentials)
def s3_prefix_from_uri(uri: str) -> str:
    m = re.match(rf"^s3://{S3_BUCKET}/(.+?)/?$", uri.strip())
    if not m:
        raise ValueError(f"Not a {S3_BUCKET} URI: {uri}")
    return m.group(1)


def s3_list(session: requests.Session, prefix: str, delimiter: str | None = None):
    """List a public S3 prefix over plain HTTPS. Returns (keys, common_prefixes)."""
    keys: list[tuple[str, int]] = []
    prefixes: list[str] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if delimiter:
            params["delimiter"] = delimiter
        if token:
            params["continuation-token"] = token
        resp = session.get(f"{S3_BASE}/", params=params, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        for c in root.findall(f"{S3_NS}Contents"):
            keys.append((c.findtext(f"{S3_NS}Key"), int(c.findtext(f"{S3_NS}Size") or 0)))
        for p in root.findall(f"{S3_NS}CommonPrefixes"):
            prefixes.append(p.findtext(f"{S3_NS}Prefix"))
        if (root.findtext(f"{S3_NS}IsTruncated") or "false") != "true":
            break
        token = root.findtext(f"{S3_NS}NextContinuationToken")
    return keys, prefixes


def s3_get_text(session: requests.Session, key: str) -> str | None:
    resp = session.get(f"{S3_BASE}/{key}", timeout=120)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


# ----------------------------------------------------------------- submissions metadata
def read_submission_metadata(session: requests.Session, name: str) -> dict:
    local = DATA_DIR / "_experiments" / "evaluation" / EXPERIMENTS_SPLIT_DIR / name / "metadata.yaml"
    if local.exists():
        return yaml.safe_load(local.read_text()) or {}
    for fn in ("metadata.yaml", "metadata.yml"):
        resp = session.get(f"{EXPERIMENTS_RAW}/evaluation/{EXPERIMENTS_SPLIT_DIR}/{name}/{fn}", timeout=60)
        if resp.status_code == 200:
            return yaml.safe_load(resp.text) or {}
    return {}


def summarize_metadata(name: str, meta: dict) -> dict:
    """Flatten a submission's metadata.yaml into one catalog row."""
    tags = meta.get("tags") or {}
    info = meta.get("info") or {}
    assets = meta.get("assets") or {}

    model = tags.get("model")
    if isinstance(model, list):
        model = "+".join(str(m) for m in model)
    model = model or tags.get("model_display") or "undisclosed"

    logs = str(assets.get("logs") or "")
    repo = str(assets.get("repo") or "")
    if logs.startswith("s3://"):
        source = "s3"
    elif repo or logs.startswith("https://github.com"):
        source = "repo"
    else:
        source = "none"
    if source == "repo" and not repo:
        repo = logs.split("/tree/")[0]

    attempts = (tags.get("system") or {}).get("attempts")
    return {
        "submission": name,
        "date": name[:8],
        "name": info.get("name") or name,
        "agent": tags.get("agent") or info.get("name") or name,
        "model": model,
        "org": tags.get("org") or tags.get("model_org") or "",
        "attempts": "" if attempts is None else str(attempts),
        "os_system": tags.get("os_system"),
        "logs_source": source,
        "logs_uri": logs or repo,
        "repo_uri": repo,
        "resolved_pct": info.get("resolved") if isinstance(info.get("resolved"), (int, float)) else None,
    }


# ----------------------------------------------------------------- JSONL
def read_jsonl(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
            n += 1
    return n
