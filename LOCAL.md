# Running locally

The local path builds everything on your own machine and keeps it between
sessions. Nothing needs to be downloaded by hand: the scripts fetch what they
need from Hugging Face, GitHub and a public S3 bucket. Docker is not required
for any default step; see [DOCKER.md](DOCKER.md) for the one optional step
that uses it.

For a first-time, step-by-step walkthrough see
[GETTING_STARTED.md](GETTING_STARTED.md). This file explains what each part
does, what it costs, and where things end up.

## Prerequisites

- macOS or Linux, a terminal, `git` and `curl`
- Internet access
- Disk: about 1.5 GB for the default Verified run, about 8 GB if you also run
  the full split and the static checks
- No Python install needed; `uv` downloads Python 3.11 into `.venv/`

## What happens locally, in order

1. **`./setup_and_run.sh --no-run`** installs `uv` if missing, creates
   `.venv/` with Python 3.11, and installs Jupyter, pandas, scikit-learn,
   matplotlib, `datasets` and the pipeline helpers. One to three minutes,
   once.

2. **`./run_pipeline.sh`** runs the pipeline steps in order:
   - `select_issues.py` downloads the 500 SWE-bench Verified issues from
     Hugging Face and caches them as `data/swebench_verified.parquet`.
   - `list_submissions.py` reads the 182 leaderboard entries from GitHub and
     writes `data/submissions_catalog.csv`.
   - `fetch_candidates.py` downloads about 5,000 patches and their official
     grading reports from the public S3 bucket into `data/raw/`.
   - `build_predictions.py` writes harness-format files under
     `data/predictions/`, only needed for the optional Docker regrade.
   - `build_candidate_table.py` writes `data/trustgate_candidate_results.csv`.

   About five minutes on a normal connection. Reruns skip anything already
   downloaded.

3. **`./setup_and_run.sh`** opens the notebook in Jupyter from the repository
   root, so the notebook's default path `data/trustgate_candidate_results.csv`
   resolves. Choose **Run All**. The imports cell downloads the SWE-bench
   issues from Hugging Face for the EDA; from section 8 onward the notebook
   reads the CSV. A full execution takes about one minute on the Verified
   split.

4. **Cell 19.8** writes `models/trustgate_gate_verified.joblib`. Score any diff
   with `pipeline/score_patch.py`.

## Optional steps and what they cost

| Step | Command | Time on this Mac | Disk |
|---|---|---|---|
| Code-health features, Verified | `./run_pipeline.sh --static` | about 45 minutes | about 1 GB of repository clones under `data/repos/` |
| Full 2,294-issue split | `./run_pipeline.sh --split full` | about 6 minutes to download and build | about 1 GB under `data/full/` |
| Code-health features, full | `./run_pipeline.sh --split full --static` | just over two hours | clones are shared with Verified |
| Notebook on the full split | `TRUSTGATE_SPLIT=full ./setup_and_run.sh` | several minutes per Run All | writes `models/trustgate_gate_full.joblib` |

The static checks apply every patch at its base commit and run the parser,
compiler and pyflakes on the changed files. They run one thread per
repository and are resumable: rerunning skips candidates already recorded in
`static_features.csv`.

## Where everything lives

| Path | What | Kept in git |
|---|---|---|
| `.venv/` | Python environment | no |
| `data/` | Verified outputs: parquet cache, catalog, raw patch cache, candidate CSV | no |
| `data/full/`, `data/lite/` | The same for other splits | no |
| `data/repos/` | Blob-less git clones used by the static checks, shared across splits | no |
| `models/` | Exported gate bundles, one per split, about 3 MB each | yes, so `score_patch.py` works without running the notebook first |
| `logs/` | Only if the Docker regrade is run | no |

Nothing under `data/` is unique. Deleting it and rerunning the pipeline
reproduces it exactly, because the labels come from published grading reports.

## Working with more than one split

`TRUSTGATE_SPLIT` selects the benchmark variant and is read by every script
and by the notebook. Leave it unset for Verified. Outputs for other splits go
to their own folder, so the two never overwrite each other:

```bash
./run_pipeline.sh --split full
TRUSTGATE_SPLIT=full ./setup_and_run.sh
TRUSTGATE_SPLIT=full .venv/bin/python pipeline/score_patch.py --patch fix.diff
```

## Versioning the notebook

The first cell of the notebook carries a stamp such as
`Version 1.0 · Released 2026-09-26 · Branch main`, and the same values sit in
the notebook metadata under `trustgate`. A git pre-commit hook writes it, so
it is always current without editing the notebook by hand.

- `VERSION` holds Major.Minor. Edit it when you cut a release; the hook does
  not bump it for you.
- The date and branch are taken at commit time.
- The hook lives in `.githooks/pre-commit` and is versioned with the code.
  Enable it once per clone with `git config core.hooksPath .githooks`;
  `setup_and_run.sh` does this automatically when run inside a git checkout.
- Skip it for one commit with `git commit --no-verify`, or run the stamp by
  hand with `python pipeline/stamp_notebook.py --version 1.1`.

## Keeping the machine responsive

The static checks and the full-split download are the only long jobs. They
run in the terminal and stop if the terminal closes or the machine sleeps,
but both resume from where they were. To run them detached:

```bash
nohup ./run_pipeline.sh --split full --static > full_run.log 2>&1 &
tail -f full_run.log
```

## Cleaning up

```bash
./cleanup.sh              # .venv, notebook checkpoints, __pycache__, harness logs
./cleanup.sh --data       # also data/raw, data/repos, data/_experiments, data/predictions
./cleanup.sh --all        # also the Hugging Face cache and SWE-bench Docker images
./cleanup.sh --dry-run    # preview
```

The final CSVs, the catalog and the selected-issues file are never deleted.

## Troubleshooting

- **Permission denied on a script**: `chmod +x *.sh pipeline/*.sh` once.
- **GitHub API rate limit during the catalog step**: the script falls back to
  a sparse git clone; if that also fails, wait an hour. Unauthenticated
  GitHub allows 60 requests per hour and the pipeline uses one.
- **A submission reports no public logs**: normal, it is skipped.
- **Notebook says no candidate results found**: Jupyter was not started from
  the repository root, or the pipeline has not been run. Use
  `./setup_and_run.sh`, which starts it in the right place.
- **Static checks stopped part way**: rerun the same command; it resumes.

## Related documents

- [GETTING_STARTED.md](GETTING_STARTED.md), first-time walkthrough
- [COLAB.md](COLAB.md), the browser alternative
- [DOCKER.md](DOCKER.md), the optional regrade step
- [PIPELINE.md](PIPELINE.md), what every pipeline step executes
