"""Step 5a (optional) - compute code-health features by applying each patch locally.

These are the notebook's "Stage 2" features: does the patch apply, does the
changed Python still parse and compile, and what does a linter say. They need
the repository at the issue's base commit, so this step clones the 12 SWE-bench
repositories (blob-less partial clones, a few hundred MB each).

What it executes, per repository:
  1. git clone --filter=blob:none https://github.com/<repo>.git data/repos/<owner>__<name>
  2. For each selected issue in that repo: git checkout --force <base_commit>; git clean -fdq
  3. For each candidate patch of that issue:
       a. git apply --check (fallback: patch --dry-run --fuzz=5)  -> patch_apply_ok
       b. git apply, then for every modified/added .py file:
            ast.parse                                            -> syntax_ok
            compile()                                            -> compile_ok
            pyflakes                                             -> lint_warning_count,
                                                                    static_error_count,
                                                                    undefined_name_count,
                                                                    import_error_count
       c. git checkout -- . ; git clean -fdq  (restore the tree)
  4. Appends results to data/static_features.csv. Reruns skip candidates already done.

Repositories run in parallel (one thread each); work inside a repository is
sequential because it shares one working tree.

Usage:
  python pipeline/static_checks.py
  python pipeline/static_checks.py --workers 4 --repos django/django
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures as cf
import csv
import subprocess
import tempfile
import threading
from pathlib import Path

import pandas as pd
from pyflakes import api as pyflakes_api
from pyflakes import messages as pfm

from common import (
    CANDIDATES_RAW_PATH,
    REPOS_DIR,
    STATIC_FEATURES_PATH,
    load_swebench,
    log,
    read_jsonl,
)

FIELDS = [
    "candidate_id", "instance_id", "patch_apply_ok", "apply_method", "syntax_ok", "compile_ok",
    "lint_warning_count", "static_error_count", "undefined_name_count", "import_error_count",
    "python_files_checked", "static_error",
]

UNDEFINED = tuple(getattr(pfm, n) for n in ("UndefinedName", "UndefinedLocal", "UndefinedExport") if hasattr(pfm, n))
IMPORTS = tuple(getattr(pfm, n) for n in ("UnusedImport", "ImportStarUsed", "ImportStarUsage", "ImportShadowedByLoopVar") if hasattr(pfm, n))
ERRORS = tuple(getattr(pfm, n) for n in (
    "UndefinedName", "UndefinedLocal", "UndefinedExport", "ReturnOutsideFunction", "YieldOutsideFunction",
    "ContinueOutsideLoop", "BreakOutsideLoop", "DefaultExceptNotLast", "DuplicateArgument",
    "TwoStarredExpressions", "TooManyExpressionsInStarredAssignment", "StringDotFormatMissingArgument",
    "PercentFormatMissingArgument", "RaiseNotImplemented", "ForwardAnnotationSyntaxError",
) if hasattr(pfm, n))


class _Collector:
    """pyflakes reporter that just counts messages by category."""

    def __init__(self) -> None:
        self.messages: list = []
        self.syntax_errors = 0

    def unexpectedError(self, filename, msg):  # noqa: N802
        self.syntax_errors += 1

    def syntaxError(self, filename, msg, lineno, offset, text):  # noqa: N802
        self.syntax_errors += 1

    def flake(self, message):
        self.messages.append(message)


def git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True, check=check)


def ensure_clone(repo: str) -> Path:
    dest = REPOS_DIR / repo.replace("/", "__")
    if not (dest / ".git").exists():
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        log(f"  cloning {repo} (blob-less)")
        subprocess.run(
            ["git", "clone", "--quiet", "--filter=blob:none", f"https://github.com/{repo}.git", str(dest)],
            check=True, capture_output=True, text=True,
        )
    return dest


def reset_tree(repo_dir: Path, commit: str) -> None:
    git(repo_dir, "checkout", "--quiet", "--force", commit)
    git(repo_dir, "clean", "-fdq")


def try_apply(repo_dir: Path, patch_path: Path) -> tuple[bool, str]:
    """Mirror the harness: git apply first, GNU patch with fuzz as a fallback."""
    if git(repo_dir, "apply", "--check", "--whitespace=nowarn", str(patch_path), check=False).returncode == 0:
        git(repo_dir, "apply", "--whitespace=nowarn", str(patch_path))
        return True, "git_apply"
    dry = subprocess.run(
        ["patch", "--dry-run", "--batch", "--fuzz=5", "-p1", "-i", str(patch_path)],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if dry.returncode == 0:
        subprocess.run(["patch", "--batch", "--fuzz=5", "-p1", "-i", str(patch_path)],
                       cwd=repo_dir, capture_output=True, text=True)
        return True, "patch_fuzz"
    return False, "failed"


def changed_python_files(repo_dir: Path) -> list[Path]:
    tracked = git(repo_dir, "diff", "--name-only", "HEAD").stdout.split()
    untracked = git(repo_dir, "ls-files", "--others", "--exclude-standard").stdout.split()
    files = []
    for rel in tracked + untracked:
        p = repo_dir / rel
        if rel.endswith(".py") and p.is_file():
            files.append(p)
    return files


def analyse_python(files: list[Path]) -> dict:
    out = {"syntax_ok": 1, "compile_ok": 1, "lint_warning_count": 0, "static_error_count": 0,
           "undefined_name_count": 0, "import_error_count": 0, "python_files_checked": len(files)}
    for path in files:
        source = path.read_text(errors="replace")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError:
            out["syntax_ok"] = 0
            out["compile_ok"] = 0
            out["static_error_count"] += 1
            continue
        try:
            compile(source, str(path), "exec")
        except Exception:  # noqa: BLE001 - e.g. ValueError on null bytes
            out["compile_ok"] = 0
            out["static_error_count"] += 1
        rep = _Collector()
        pyflakes_api.check(source, str(path), rep)
        out["lint_warning_count"] += len(rep.messages) + rep.syntax_errors
        out["static_error_count"] += rep.syntax_errors
        for m in rep.messages:
            if isinstance(m, UNDEFINED):
                out["undefined_name_count"] += 1
            if isinstance(m, IMPORTS):
                out["import_error_count"] += 1
            if isinstance(m, ERRORS):
                out["static_error_count"] += 1
    return out


def process_repo(repo: str, instances: pd.DataFrame, cands: dict[str, list[dict]], writer, lock) -> int:
    repo_dir = ensure_clone(repo)
    done = 0
    for _, inst in instances.iterrows():
        iid = inst["instance_id"]
        todo = cands.get(iid, [])
        if not todo:
            continue
        try:
            reset_tree(repo_dir, inst["base_commit"])
        except subprocess.CalledProcessError as exc:
            for c in todo:
                with lock:
                    writer.writerow({"candidate_id": c["candidate_id"], "instance_id": iid,
                                     "static_error": f"checkout failed: {exc.stderr[:120]}"})
            continue
        for c in todo:
            row = {"candidate_id": c["candidate_id"], "instance_id": iid}
            with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
                fh.write(c["patch"])
                patch_path = Path(fh.name)
            try:
                ok, method = try_apply(repo_dir, patch_path)
                row.update({"patch_apply_ok": int(ok), "apply_method": method})
                if ok:
                    row.update(analyse_python(changed_python_files(repo_dir)))
            except Exception as exc:  # noqa: BLE001
                row["static_error"] = str(exc)[:200]
            finally:
                patch_path.unlink(missing_ok=True)
                try:
                    git(repo_dir, "checkout", "--quiet", "--", ".")
                    git(repo_dir, "clean", "-fdq")
                except subprocess.CalledProcessError:
                    reset_tree(repo_dir, inst["base_commit"])
            with lock:
                writer.writerow(row)
            done += 1
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=str(CANDIDATES_RAW_PATH))
    ap.add_argument("--out", default=str(STATIC_FEATURES_PATH))
    ap.add_argument("--workers", type=int, default=4, help="repositories processed in parallel")
    ap.add_argument("--repos", nargs="*", default=None, help="only these repositories")
    args = ap.parse_args()

    swe = load_swebench()[["instance_id", "repo", "base_commit"]]
    rows = [r for r in read_jsonl(Path(args.inp)) if (r.get("patch") or "").strip()]

    out = Path(args.out)
    already: set[str] = set()
    if out.exists():
        already = set(pd.read_csv(out)["candidate_id"].astype(str))
        log(f"{len(already)} candidates already checked; resuming")

    cands: dict[str, list[dict]] = {}
    for r in rows:
        if r["candidate_id"] in already:
            continue
        cands.setdefault(r["instance_id"], []).append(r)
    log(f"{sum(len(v) for v in cands.values())} candidates across {len(cands)} issues to check")

    inst = swe[swe["instance_id"].isin(cands)]
    if args.repos:
        inst = inst[inst["repo"].isin(args.repos)]

    lock = threading.Lock()
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with open(out, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        with cf.ThreadPoolExecutor(args.workers) as pool:
            futures = {
                pool.submit(process_repo, repo, grp, cands, writer, lock): repo
                for repo, grp in inst.groupby("repo")
            }
            for fut in cf.as_completed(futures):
                repo = futures[fut]
                try:
                    log(f"  {repo}: {fut.result()} candidates checked")
                except Exception as exc:  # noqa: BLE001
                    log(f"  {repo}: FAILED ({exc})")

    df = pd.read_csv(out)
    log(f"\n{len(df)} rows in {out}")
    if "patch_apply_ok" in df:
        log(f"patch_apply_ok rate: {df['patch_apply_ok'].mean():.3f}")
        log(f"syntax_ok rate (applied): {df.loc[df['patch_apply_ok'] == 1, 'syntax_ok'].mean():.3f}")


if __name__ == "__main__":
    main()
