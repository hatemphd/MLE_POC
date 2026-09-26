"""Step 8 - import real pull requests from GitHub as production TrustGate data.

The benchmark table answers "did the patch pass the tests". A production gate
needs labels from your own engineering process. This script pulls closed pull
requests from a GitHub repository and records, per PR, everything the notebook's
section 20 needs to derive a label and legitimate decision-time features:

  - the diff, size and files changed
  - who wrote it and whether the author is a bot
  - review outcome: approvals, change requests, comment count
  - CI outcome for the head commit: check-run totals, successes, failures
  - whether it was merged, and whether a revert of it landed within 30 days

What it executes:
  1. Resolves a token from GITHUB_TOKEN, or `gh auth token` if the gh CLI is logged in.
     Without a token the API allows 60 requests per hour, enough for about 12 PRs.
  2. GET /repos/<repo>/pulls?state=closed  (paginated, newest first) up to --limit PRs.
  3. Per PR: GET the diff (Accept: application/vnd.github.diff), GET /reviews,
     GET /commits/<head_sha>/check-runs.
  4. Once per repo: GET /commits on the default branch since the oldest merge in the
     batch, and scan messages for "Revert ... (#123)" or "This reverts commit <sha>"
     to flag PRs reverted within 30 days of merging.
  5. Writes data/production_prs.csv (appending and de-duplicating on pr_url if it exists).

Usage:
  export GITHUB_TOKEN=ghp_...            # or: gh auth login
  python pipeline/import_github_prs.py --repo psf/requests --limit 200
  python pipeline/import_github_prs.py --repo your-org/repo-a --repo your-org/repo-b --limit 500
  python pipeline/import_github_prs.py --repo psf/requests --limit 5 --no-diff   # cheaper smoke test
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from common import DATA_DIR, log, make_session

API = "https://api.github.com"
OUT_PATH = DATA_DIR / "production_prs.csv"

COLUMNS = [
    "repo", "pr_number", "pr_url", "title", "body", "author", "author_association", "is_bot",
    "created_at", "merged_at", "closed_at", "merged", "diff", "additions", "deletions", "changed_files",
    "review_approvals", "review_changes_requested", "review_comments",
    "ci_checks_total", "ci_checks_success", "ci_checks_failure", "ci_job_success_rate", "ci_job_failure_count",
    "reverted_within_30d", "revert_commit",
]


def resolve_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


class GitHub:
    def __init__(self, token: str | None):
        self.s = make_session()
        self.s.headers["Accept"] = "application/vnd.github+json"
        self.s.headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        self.calls = 0

    def get(self, url: str, accept: str | None = None, **params):
        headers = {"Accept": accept} if accept else {}
        for attempt in range(4):
            resp = self.s.get(url, params=params or None, headers=headers, timeout=60)
            self.calls += 1
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(5, reset - int(time.time()))
                log(f"  rate limited; sleeping {wait}s (set GITHUB_TOKEN for 5,000 requests/hour)")
                time.sleep(min(wait, 900))
                continue
            if resp.status_code in (404, 422):
                return None
            resp.raise_for_status()
            return resp.text if accept else resp.json()
        raise RuntimeError(f"gave up on {url}")

    def paginate(self, url: str, limit: int, **params):
        page, out = 1, []
        while len(out) < limit:
            batch = self.get(url, page=page, per_page=min(100, limit - len(out)), **params)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out[:limit]


def summarise_reviews(reviews: list[dict] | None) -> dict:
    reviews = reviews or []
    latest: dict[str, str] = {}
    for r in sorted(reviews, key=lambda r: r.get("submitted_at") or ""):
        if r.get("user") and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED"):
            latest[r["user"]["login"]] = r["state"]  # last word per reviewer wins
    return {
        "review_approvals": sum(1 for s in latest.values() if s == "APPROVED"),
        "review_changes_requested": sum(1 for s in latest.values() if s == "CHANGES_REQUESTED"),
        "review_comments": len(reviews),
    }


def summarise_checks(check_runs: dict | None) -> dict:
    runs = (check_runs or {}).get("check_runs", []) or []
    finished = [r for r in runs if r.get("status") == "completed"]
    success = sum(1 for r in finished if r.get("conclusion") in ("success", "neutral", "skipped"))
    failure = sum(1 for r in finished if r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required"))
    total = len(finished)
    return {
        "ci_checks_total": total,
        "ci_checks_success": success,
        "ci_checks_failure": failure,
        "ci_job_success_rate": (success / total) if total else None,
        "ci_job_failure_count": failure if total else None,
    }


REVERT_PR = re.compile(r"[Rr]evert.*?\(#(\d+)\)", re.S)
REVERT_SHA = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def find_reverts(gh: GitHub, repo: str, default_branch: str, since: datetime, until: datetime) -> tuple[dict[int, str], dict[str, str]]:
    """Map reverted PR number -> revert commit sha, and reverted commit sha -> revert commit sha."""
    by_pr: dict[int, str] = {}
    by_sha: dict[str, str] = {}
    commits = gh.paginate(
        f"{API}/repos/{repo}/commits", limit=2000, sha=default_branch,
        since=since.isoformat(), until=until.isoformat(),
    )
    for c in commits:
        msg = (c.get("commit") or {}).get("message") or ""
        if "revert" not in msg.lower():
            continue
        for m in REVERT_PR.finditer(msg):
            by_pr.setdefault(int(m.group(1)), c["sha"])
        for m in REVERT_SHA.finditer(msg):
            by_sha.setdefault(m.group(1)[:7], c["sha"])
    return by_pr, by_sha


def parse_ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def import_repo(gh: GitHub, repo: str, limit: int, with_diff: bool) -> pd.DataFrame:
    meta = gh.get(f"{API}/repos/{repo}")
    if meta is None:
        raise SystemExit(f"repository not found or not accessible: {repo}")
    default_branch = meta["default_branch"]

    log(f"==> {repo}: listing up to {limit} closed pull requests")
    pulls = gh.paginate(f"{API}/repos/{repo}/pulls", limit=limit, state="closed", sort="updated", direction="desc")
    log(f"  {len(pulls)} pull requests listed")

    rows = []
    for i, pr in enumerate(pulls, 1):
        n = pr["number"]
        row = {
            "repo": repo, "pr_number": n, "pr_url": pr["html_url"], "title": pr.get("title"),
            "body": (pr.get("body") or "")[:5000], "author": (pr.get("user") or {}).get("login"),
            "author_association": pr.get("author_association"),
            "is_bot": (pr.get("user") or {}).get("type") == "Bot",
            "created_at": pr.get("created_at"), "merged_at": pr.get("merged_at"), "closed_at": pr.get("closed_at"),
            "merged": pr.get("merged_at") is not None,
            "additions": None, "deletions": None, "changed_files": None, "diff": None,
            "reverted_within_30d": False, "revert_commit": None,
        }
        detail = gh.get(f"{API}/repos/{repo}/pulls/{n}") or {}
        row.update(additions=detail.get("additions"), deletions=detail.get("deletions"),
                   changed_files=detail.get("changed_files"))
        if with_diff:
            row["diff"] = gh.get(f"{API}/repos/{repo}/pulls/{n}", accept="application/vnd.github.diff")
        row.update(summarise_reviews(gh.get(f"{API}/repos/{repo}/pulls/{n}/reviews")))
        head_sha = (pr.get("head") or {}).get("sha")
        row.update(summarise_checks(gh.get(f"{API}/repos/{repo}/commits/{head_sha}/check-runs") if head_sha else None))
        row["_merge_sha"] = detail.get("merge_commit_sha")
        rows.append(row)
        if i % 10 == 0 or i == len(pulls):
            log(f"  {i}/{len(pulls)} pull requests fetched ({gh.calls} API calls so far)")

    df = pd.DataFrame(rows)
    merged = df[df["merged"]]
    if len(merged):
        oldest = min(parse_ts(t) for t in merged["merged_at"])
        newest = max(parse_ts(t) for t in merged["merged_at"])
        by_pr, by_sha = find_reverts(gh, repo, default_branch, oldest, newest + timedelta(days=30))
        for idx, r in merged.iterrows():
            revert = by_pr.get(int(r["pr_number"])) or (by_sha.get(str(r["_merge_sha"])[:7]) if r["_merge_sha"] else None)
            if revert:
                df.at[idx, "reverted_within_30d"] = True
                df.at[idx, "revert_commit"] = revert
        log(f"  {int(df['reverted_within_30d'].sum())} merged PRs were reverted within the window")
    return df.drop(columns=["_merge_sha"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", required=True, help="owner/name, repeatable")
    ap.add_argument("--limit", type=int, default=200, help="closed PRs per repository")
    ap.add_argument("--no-diff", action="store_true", help="skip downloading diffs (saves one call per PR)")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    token = resolve_token()
    log("Authenticated with a GitHub token" if token else
        "No GITHUB_TOKEN and gh is not logged in: unauthenticated, 60 requests/hour")
    gh = GitHub(token)

    frames = [import_repo(gh, repo, args.limit, not args.no_diff) for repo in args.repo]
    new = pd.concat(frames, ignore_index=True)

    out = Path(args.out)
    if out.exists():
        old = pd.read_csv(out)
        new = pd.concat([old, new], ignore_index=True).drop_duplicates("pr_url", keep="last")
    out.parent.mkdir(parents=True, exist_ok=True)
    new = new.reindex(columns=COLUMNS)
    new.to_csv(out, index=False)

    log(f"\nWrote {len(new)} pull requests to {out}  ({gh.calls} API calls)")
    log(f"merged: {int(new['merged'].sum())}   reverted within 30d: {int(new['reverted_within_30d'].fillna(False).sum())}")
    log(f"PRs with CI check data: {int(new['ci_checks_total'].fillna(0).gt(0).sum())}")


if __name__ == "__main__":
    main()
