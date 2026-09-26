# TrustGate × SWE-bench: PR Approval Gate ML Study

A machine-learning proof of concept for **TrustGate**, a system that looks at a
GitHub issue and a candidate PR patch and decides whether the patch should be
**auto-approved**, **auto-rejected**, or sent for **human review**.

The study uses [SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified),
500 human-validated GitHub issues across 12 Python repositories, as a source of
real issues with an objective way to grade candidate patches.

## How it works

```text
GitHub issue + codebase + candidate patch
                  |
                  v
        TrustGate features
    (patch shape, static checks, CI signals, agent agreement)
                  |
                  v
      P(candidate correctly resolves the issue)
                  |
        +---------+---------+
        |         |         |
     APPROVE   HUMAN      REJECT
      p >= a   REVIEW     p <= r
```

The model outputs a calibrated probability. Approve and reject thresholds are
chosen on validation data, then frozen before the test set is touched.

## Repository contents

| File | Purpose |
|---|---|
| `TrustGate_SWEBench_PoC_ML_v3.ipynb` | The study notebook: EDA, feature design, label schema, modeling, calibration, three-way policy |
| `setup_and_run.sh` | Creates a uv-managed Python environment and launches Jupyter |
| `run_pipeline.sh` | Builds `data/trustgate_candidate_results.csv` from public leaderboard submissions |
| `pipeline/` | The individual pipeline steps, documented in `PIPELINE.md` |
| `pipeline/import_github_prs.py` | Imports real pull requests from GitHub for the production experiment in notebook section 20 |
| `pipeline/score_patch.py` | Scores a new patch with the model the notebook exports to `models/` |
| `pipeline/metrics_figures.py` | Regenerates the metric figures under `docs/figures/` from the exported gate |
| `TrustGate_Notebook_and_Pipeline.pptx` | Slide deck explaining the notebook, the scripts, and how data flows between them |
| `VALUE_PROP.md` | Plain-language value proposition for the general reader: analogies, how the data is used, why it complements patch writers |
| `GETTING_STARTED.md` | Step-by-step guide for a fresh clone |
| `COLAB.md` | Running on Google Colab: what it downloads, what it lacks, session limits |
| `LOCAL.md` | Running locally: what each step does and costs, where files live, multiple splits |
| `GIT.md` | Git workflow: what to commit, when to bump the version, how to cut a release |
| `DOCKER.md` | The one optional step that needs Docker, and how to run it |
| `PIPELINE.md` | What every pipeline step executes and why |
| `PIPELINE_EXPLAINED.md` | Plain-English version of the pipeline |
| `METRICS.md` | Every evaluation metric explained with formulas, worked examples and TrustGate's own figures |
| `MLReview.md` | Ablation explained, and the machine learning algorithm landscape: what is used, what to consider, what does not fit |
| `SWEBench_TrustGate.md` | What the SWE-bench organisation provides, who has built patch judges before, how ours differs, and what to read to compare findings |
| `setup_and_run.md` | What the setup script does |
| `cleanup.sh` | Removes the environment, caches, downloads, and harness output |
| `VERSION`, `.githooks/pre-commit`, `pipeline/stamp_notebook.py` | Major.Minor version and the hook that stamps it, with the date and branch, into the notebook on every commit |
| `.gitignore` | Keeps venvs, data, and harness logs out of git |

## Quick start

**New to the project?** Follow [GETTING_STARTED.md](GETTING_STARTED.md). It walks
through a fresh clone to a running notebook in six steps, with a troubleshooting
section. The summary below assumes you already know the layout.

### Prerequisites

- macOS or Linux
- `curl` (used to install uv if it is missing)
- Docker, only needed later for generating labels with the SWE-bench harness

Python 3.11 is downloaded automatically by uv. The system Python 3.9 is too old
for recent `datasets` and `matplotlib` releases.

### Run the notebook

```bash
./setup_and_run.sh
```

This will:

1. Install [uv](https://docs.astral.sh/uv/) if it is not on your PATH.
2. Create `.venv` with Python 3.11.
3. Install `jupyter`, `datasets`, `scikit-learn`, `pandas`, `numpy`, `matplotlib`,
   `pip`, and the pipeline's `pyarrow`, `pyyaml`, `requests`, `pyflakes`.
4. Print the installed versions as a sanity check.
5. Open the notebook in Jupyter.

Then choose **Run All** in Jupyter. The first cell's `!pip install` is a no-op
inside the venv because everything is already installed.

Options:

```bash
./setup_and_run.sh --no-run    # set up the environment without launching Jupyter
./setup_and_run.sh --harness   # also install the swebench evaluation harness
```

To work in the environment manually:

```bash
source .venv/bin/activate
jupyter notebook TrustGate_SWEBench_PoC_ML_v3.ipynb
```

### Alternative: Google Colab

Upload the notebook to [colab.research.google.com](https://colab.research.google.com).
The cell right after the pip install detects Colab, clones this repository
when `REPO_URL` is set, and runs the pipeline in place to build the candidate
table, so nothing has to be uploaded by hand. If you prefer to upload the CSV,
the same cell has two commented lines that mount Google Drive and point
`TRUSTGATE_CANDIDATES` at it. Locally the cell does nothing. Details in
[COLAB.md](COLAB.md).

## What runs today and what does not

The notebook has two halves.

**Benchmark EDA (runs immediately).** Downloads the 500 SWE-bench Verified
rows and produces repository and difficulty distributions, patch-size
histograms, issue and test complexity plots, a correlation heatmap, and a
missing-value heatmap. Needs only internet access.

**Candidate-level ML (gated).** Defines the candidate table schema, issue-grouped
train/validation/test split, logistic and gradient-boosting baselines, ROC and
PR curves, calibration with Expected Calibration Error, the three-way
approve/review/reject policy with a threshold grid, and issue-level bootstrap
confidence intervals.

These cells are guarded by a data check and will print a "not enough data"
message until a candidate results file is provided. This is intentional. The
500 SWE-bench rows are gold patches that all succeed, so there is no label
variance to learn from. Labels have to come from grading your own candidate
patches.

## Producing candidate labels

The modeling cells need a CSV matching the notebook's `CANDIDATE_COLUMNS`
schema with at least 100 rows across 50 or more issues and both label values.
One command builds it:

```bash
./run_pipeline.sh
```

It reuses the SWE-bench Verified leaderboard. Every submitted system produced
one patch per issue, and the maintainers graded those patches with the
official harness and published both the patches and the `report.json` grades.
The pipeline downloads ten systems' submissions over HTTPS, chosen to balance
model families, so each issue gets up to ten independently generated
candidates with official labels. No LLM calls, no Docker, about five minutes.
Add `--static` once to also compute code-health features; it clones the 12
repositories and takes longer, and it is what lifts the best model to 0.74 AUC.

The reference run produced 4,908 graded candidates over all 500 issues from
ten systems chosen to balance model families, split 2,830 resolved to 2,078
not resolved.

Steps, each its own script under `pipeline/`:

1. **Select issues** with a stratified sample across repository and difficulty
   (`select_issues.py`). Defaults to all 500.
2. **Catalog submissions** from the SWE-bench/experiments repository
   (`list_submissions.py`), then **fetch patches and grading reports** from the
   public S3 bucket (`fetch_candidates.py`).
3. **Write harness-format prediction files** (`build_predictions.py`), needed
   only if you regrade.
4. **Regrade with the official harness**, optional (`run_harness.sh`). Needs
   Docker, 16 GB RAM and about 120 GB disk.
5. **Build the candidate table** (`build_candidate_table.py`), with optional
   code-health features from applying each patch locally (`static_checks.py`).
6. **Open the notebook.** The candidate-loading cell finds
   `data/trustgate_candidate_results.csv` automatically.

To work on the full 2,294-issue test set instead of the 500 Verified issues,
run `./run_pipeline.sh --split full` and open the notebook with
`TRUSTGATE_SPLIT=full ./setup_and_run.sh`. Outputs go to `data/full/`. On the
reference run this halved the uncertainty on the model's score (0.69 AUC, plus
or minus 0.03) at the cost of a harder, lower-base-rate problem; see the
results section of `PIPELINE.md`.

`PIPELINE.md` explains what each step executes, its inputs and outputs, and
the flags.

## Scoring a new patch

Running the notebook through cell 19.8 writes `models/trustgate_gate_verified.joblib`:
the final calibrated model, its feature list, the cross-validated approve and
reject thresholds, and the text vectorizer if one was used. Score any diff from the terminal:

```bash
.venv/bin/python pipeline/score_patch.py --patch fix.diff --issue issue.txt --sibling other1.diff
```

Pass one `--sibling` per other candidate for the same issue; agreement between
independent attempts is the model's strongest feature. `--json` gives
machine-readable output and `--feature name=value` overrides any feature, for
example with results from your own CI. The same function is importable as
`from score_patch import score_patch`.

## Leakage rules

Never use these as model features. They contain the answer or information too
close to it:

- the gold `patch` or its touched files
- `FAIL_TO_PASS` and `PASS_TO_PASS`
- hidden SWE-bench test outcomes
- `resolved_status`
- any confidence value assigned after knowing the outcome

Split by `instance_id`, never by row. All candidates for one issue must land in
the same split.

## Cleanup

```bash
./cleanup.sh              # remove .venv, notebook checkpoints, __pycache__, harness logs
./cleanup.sh --data       # also delete pipeline downloads (data/raw, data/repos, data/predictions)
./cleanup.sh --hf-cache   # also delete the Hugging Face datasets cache
./cleanup.sh --docker     # also remove SWE-bench Docker images and containers
./cleanup.sh --all        # everything above
./cleanup.sh --dry-run    # preview without deleting
```

The final outputs under `data/` (`trustgate_candidate_results.csv`,
`candidates_raw.jsonl`, `submissions_catalog.csv`, `selected_instances.json`)
are never removed by the cleanup script.

## References

- [SWE-bench Verified dataset card](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
- [SWE-bench evaluation tutorial](https://github.com/SWE-bench/SWE-bench/blob/main/docs/assets/evaluation.md)
- [SWE-bench harness reference](https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/harness.md)
- [SWE-bench quick start](https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/quickstart.md)
- [SWE-bench Docker setup](https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/docker_setup.md)
