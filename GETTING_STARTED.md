# Getting started from scratch

A step-by-step guide for someone who has just found this repository on GitHub
and has nothing set up. Total time is about 15 minutes, most of it downloads.

## What you are about to build

1. A Python environment with Jupyter and the ML libraries.
2. A data table of about 3,500 candidate bug-fix patches, each labeled with
   whether it actually fixed the bug. This is downloaded from public
   SWE-bench leaderboard results, not generated.
3. A running notebook that explores the benchmark, trains a baseline model on
   that table, and turns its predictions into approve / human-review / reject
   decisions.

No API keys, no Docker, and no GPU are needed for the default path.

## Prerequisites

- macOS or Linux with a terminal
- `git` and `curl` installed (both ship with macOS)
- An internet connection. Expect roughly 150 MB of downloads.
- About 1 GB of free disk for the environment and data

Python does not need to be installed. The setup script downloads Python 3.11
through the uv package manager.

## Step 1: clone the repository

```bash
git clone <repository-url> trustgate
cd trustgate
```

Replace `<repository-url>` with the GitHub URL. You should see the notebook,
a `pipeline/` folder, and several shell scripts and markdown files. There is
no `data/` folder yet; it is created in step 3.

## Step 2: create the Python environment

```bash
./setup_and_run.sh --no-run
```

What this does:

- Installs uv if it is missing, by downloading it from astral.sh.
- Creates a `.venv/` folder with Python 3.11, downloading Python if needed.
- Installs Jupyter, pandas, scikit-learn, matplotlib, the Hugging Face
  `datasets` library, and the pipeline's helper packages into that folder.
- Prints the installed versions as a check.

The `--no-run` flag stops it from opening Jupyter right away. It takes one to
three minutes. If it ends with a version list and no error, it worked.

## Step 3: build the candidate data

```bash
./run_pipeline.sh
```

What this does, in order:

1. Downloads the SWE-bench Verified benchmark from Hugging Face: 500 real
   GitHub bugs across 12 Python projects. Saved as
   `data/swebench_verified.parquet`.
2. Reads the public SWE-bench leaderboard on GitHub and catalogs the 182
   systems that have submitted results. Saved as `data/submissions_catalog.csv`.
3. For 10 chosen systems, spanning seven model families and weak to strong,
   downloads the patch each one wrote for each bug and
   the official pass/fail report, about 3,500 small files from a public S3
   bucket. Cached under `data/raw/`.
4. Writes harness-format prediction files under `data/predictions/`. These are
   only needed if you ever want to regrade patches yourself, so ignore them
   for now.
5. Combines the patches and reports into `data/trustgate_candidate_results.csv`,
   one row per candidate with a label of 1 (fixed the bug) or 0 (did not).

It takes about five minutes. The last lines print the label balance and the
sentence `Notebook training gate ... PASS`. That sentence is what you are
looking for.

Options you might want later:

```bash
./run_pipeline.sh --n 200          # only 200 bugs, sampled across projects and difficulty
./run_pipeline.sh --auto 12        # pick 12 systems automatically instead of the 8 defaults
./run_pipeline.sh --static         # add code-health features (slow, clones 12 repositories; recommended once)
./run_pipeline.sh --skip-fetch     # rebuild the CSV from what is already downloaded
./run_pipeline.sh --split full     # all 2,294 issues of the full test set; outputs under data/full/
```

## Step 4: open the notebook

```bash
./setup_and_run.sh
```

This time the script finds the existing environment and launches Jupyter in
your browser with the notebook open. Choose **Run All** from the Cell or Run
menu.

### Running on Google Colab instead

Upload the notebook to Colab. The cell right after the pip install detects
Colab. Set `REPO_URL` in it to this repository's GitHub URL and run it: it
clones the repo, installs the helper packages, and runs steps 1 to 3 of the
pipeline inside Colab, about five minutes. Nothing needs to be uploaded. If you
already have the CSV, the same cell shows how to mount Google Drive and point
`TRUSTGATE_CANDIDATES` at it instead.

## Step 5: read the notebook top to bottom

The notebook is written as a report, so read the markdown cells as you go.
Here is what happens in each part.

**Sections 1 and 2: what SWE-bench is.** Text only. Explains the 500 bugs and
why the model should judge candidate patches, not the bugs themselves.

**Sections 3 and 4: benchmark EDA.** The notebook loads the 500 bugs and
draws bar charts of bugs per project and per difficulty, histograms of patch
size and bug-report length, a correlation heatmap, and a missing-value
heatmap. This describes the benchmark; none of it is training data.

**Sections 5 to 7: what counts as a feature.** Text. The key rule is that the
model may only use signals available before the tests run. The gold fix, the
test names, and the outcome are never features.

**Section 8: candidate EDA.** The notebook loads
`data/trustgate_candidate_results.csv` automatically. You should see
`Loaded candidate results from data/trustgate_candidate_results.csv` and a
row count in the thousands. Then a label-balance bar chart, success rate by
patch-size bucket, and a heatmap of the candidate features.

**Section 9: splitting.** Candidates are split into train, validation and
test by bug, so all candidates for the same bug land in the same split.

**Sections 10 to 13: the model.** A logistic-regression baseline trains on
five patch-shape features and prints accuracy, precision, recall, ROC-AUC,
PR-AUC and Brier score, then draws ROC, precision-recall and calibration
curves. Expect a weak result around 0.55 to 0.60 AUC. That is the honest
starting point; the point is that the whole chain runs on real labels.

**Section 14: the three-way gate.** Probabilities become approve, human
review, or reject. A grid of thresholds is evaluated on the validation set so
you can see the trade-off between automation coverage and mistakes.

**Sections 15 to 18: confidence intervals, roadmap, architecture.** Mostly
text, with a bootstrap helper that resamples by bug.

**Section 19: experiments.** Semantic features, a feature ablation across two
models, leave-one-repository-out evaluation, bootstrap intervals, the gate
with the best model, a stronger tree with monotonic constraints and
calibration, cross-validated thresholds, and an export cell that saves the
final model to `models/`.
These are the cells that turn the weak baseline into a real comparison. In the
reference run the best model reached 0.74 test AUC against 0.53 for the
patch-shape baseline.

**Section 20: production data.** Schema and loader for real pull requests
imported with `pipeline/import_github_prs.py`. Prints instructions if no PR
file exists yet.

## Step 6: score a new patch

After Run All, cell 19.8 has written `models/trustgate_gate_verified.joblib`. Score any
diff from the terminal:

```bash
.venv/bin/python pipeline/score_patch.py --patch my_fix.diff --issue issue.txt
```

Pass `--sibling other.diff` for each other candidate you have for the same
issue; agreement between attempts is the model's strongest signal.

## Step 7: where to go next

- Run `./run_pipeline.sh --static` once so section 19's code-health feature
  set is populated. It clones the 12 repositories and takes a while.
- Import your own pull requests with `pipeline/import_github_prs.py` and rerun
  the notebook on production labels through section 20.
- Widen the candidate pool with `./run_pipeline.sh --auto 12`, then rerun
  from section 8.
- Scale up to the full test set: `./run_pipeline.sh --split full`, then open
  the notebook with `TRUSTGATE_SPLIT=full ./setup_and_run.sh`. Four and a half
  times the issues, which is what makes the approve threshold trustworthy.
- Read `PIPELINE.md` for exactly what each pipeline script executes, and
  `PIPELINE_EXPLAINED.md` for the plain-English version.

## If something goes wrong

**`./setup_and_run.sh` says permission denied.** Run `chmod +x *.sh pipeline/*.sh` once.

**Step 3 fails on the GitHub API.** The catalog step falls back to a git
clone automatically. If it still fails, wait an hour; the unauthenticated
GitHub API allows 60 requests per hour and the pipeline uses one.

**Step 3 says a submission has no public logs.** Normal. Some leaderboard
entries never uploaded their patches. The script skips them and continues.

**The notebook says `No candidate results found`.** Step 3 did not finish, or
Jupyter was started from a different folder. Start it with
`./setup_and_run.sh` from the repository root.

**The notebook's first cell runs `!pip install` and fails.** The environment
already has everything, so skip that cell.

## Cleaning up

```bash
./cleanup.sh            # removes the environment and notebook checkpoints
./cleanup.sh --data     # also removes the downloaded patch cache
./cleanup.sh --dry-run  # shows what would be removed
```

The final CSV under `data/` is never deleted by the cleanup script.
