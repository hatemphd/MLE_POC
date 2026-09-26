# Candidate-label pipeline

This document explains how `data/trustgate_candidate_results.csv` is produced,
step by step, and what each command executes. The CSV is the input the
notebook's modeling cells need: one row per candidate patch with a real
pass/fail label from the official SWE-bench harness.

## The idea in one paragraph

The notebook's original plan was to run a coding agent several times per issue
and grade every attempt in Docker. That needs an LLM budget plus 16 GB of RAM
and about 120 GB of disk. Instead, this pipeline reuses work the community has
already done. Every system on the SWE-bench Verified leaderboard submitted one
patch per issue, and the maintainers graded those patches with the official
harness and published both the patches and the grading reports. Downloading
ten systems' submissions therefore gives up to ten independently generated
candidates per issue, each with an official FULL / PARTIAL / NO outcome, in a
few minutes and with no Docker.

```text
github.com/SWE-bench/experiments          s3://swe-bench-submissions (public)
  evaluation/verified/<submission>/          <split>/<submission>/logs/<instance_id>/
    metadata.yaml  -- points to logs -->        patch.diff     (the candidate)
                                                report.json    (official grade)
                        |
                        v
             pipeline/fetch_candidates.py
                        |
                        v
             data/candidates_raw.jsonl
                        |
                        v
          pipeline/build_candidate_table.py
                        |
                        v
        data/trustgate_candidate_results.csv  -->  notebook
```

## Quick start

```bash
./run_pipeline.sh
```

That runs steps 1, 2a, 2b, 3 and 5 below with defaults: all 500 issues and
ten default submissions balanced across model families. It takes about five minutes on a normal connection.
Then open the notebook with `./setup_and_run.sh` and run all cells. The
candidate-loading cell finds the CSV automatically.

Useful variants:

```bash
./run_pipeline.sh --n 200                 # stratified sample of 200 issues
./run_pipeline.sh --auto 12               # let the catalog pick 12 diverse submissions
./run_pipeline.sh --static                # add code-health features (clones 12 repos); do this once
./run_pipeline.sh --skip-fetch            # rebuild the CSV from the existing download
```

## Results from the reference run

| Measure | Value |
|---|---|
| Submissions | 10, spanning Claude, GPT, Gemini, Qwen, Kimi, GLM, Llama and one undisclosed |
| Candidates downloaded | 4,975 |
| Graded candidates in the CSV | 4,908 |
| Issues covered | 500 of 500 |
| Repositories covered | 12 of 12 |
| Label 1 (FULL) | 2,830 |
| Label 0 (PARTIAL or NO) | 2,078 |
| Ungraded (no report) | 10 |
| Empty patches dropped | 57 |

Resolve rate ranges from 9 percent for the weakest system to 78 percent for the
strongest, and from 20 percent on issues rated over four hours to 72 percent on
issues rated under 15 minutes. Both spreads are useful signal for the model.
These ten systems are now the `DEFAULT_SUBMISSIONS` in `fetch_candidates.py`.

## Choosing the benchmark split

`TRUSTGATE_SPLIT` selects which SWE-bench variant everything works on. The
pipeline and the notebook read the same variable, so they always agree.

| Split | Issues | Outputs | Leaderboard systems with full logs |
|---|---|---|---|
| `verified` (default) | 500 | `data/` | about 170 |
| `full` | 2,294 | `data/full/` | 10 |
| `lite` | 300 | `data/lite/` | many; no defaults set |

```bash
./run_pipeline.sh --split full            # build data/full/trustgate_candidate_results.csv
TRUSTGATE_SPLIT=full ./setup_and_run.sh   # open the notebook on that table
```

**Why the full set.** The effective sample size of this study is the number
of issues, not the number of candidates, because candidates for one issue are
correlated. With 500 issues the validation split holds 100, and thresholds
chosen on 100 issues are noisy: on Verified, an approve threshold tuned to 90
percent precision on validation gave 76 percent on test. The full set has
4.6 times as many issues. Its leaderboard is older and smaller (a full run is
expensive), so the ten default systems are Claude-heavy and weaker, resolving
12 to 53 percent of issues; the label balance is roughly one third positive.

Repository clones for `static_checks.py` are shared across splits under
`data/repos/`.

## Step 1: select issues

```bash
.venv/bin/python pipeline/select_issues.py            # all 500
.venv/bin/python pipeline/select_issues.py --n 200    # stratified sample
```

**What is executed.** The script downloads SWE-bench Verified from Hugging
Face on first use and caches it as `data/swebench_verified.parquet`. With
`--n 0`, the default, it keeps all 500 issues. With a positive `--n`, it groups
issues by repository and difficulty, allocates the sample proportionally with a
floor of one issue per group, and draws randomly within each group using the
seed. It writes `data/selected_instances.json` containing the instance ids and
two coverage tables, and prints both tables.

**Output.** `data/selected_instances.json`.

## Step 2a: catalog the public submissions

```bash
.venv/bin/python pipeline/list_submissions.py --check-logs
```

**What is executed.** One GitHub API call lists the 182 folders under
`evaluation/verified/` in the SWE-bench/experiments repository. If the API is
rate limited, the script falls back to a sparse, blob-less git clone. It then
downloads each folder's `metadata.yaml`, which names the agent, model and
organisation and points to where the logs live. The resolve rate comes from the
metadata when present, otherwise from `results/results.json` or
`per_instance_details.json`. With `--check-logs`, it also lists each S3 log
folder to count how many instances actually have artifacts, which catches
submissions whose logs were never uploaded.

**Output.** `data/submissions_catalog.csv` with one row per submission. In the
reference run 169 submissions had S3 logs, one used a self-hosted GitHub
repository, and 12 had no public logs.

## Step 2b: fetch candidate patches and official grades

```bash
.venv/bin/python pipeline/fetch_candidates.py
.venv/bin/python pipeline/fetch_candidates.py --auto 10
.venv/bin/python pipeline/fetch_candidates.py --submissions 20250522_tools_claude-4-sonnet 20241028_agentless-1.5_gpt4o
```

**What is executed.** For each chosen submission the script reads
`metadata.yaml` to find the log location. Older entries point to the public S3
bucket `swe-bench-submissions`, which the script reads over plain HTTPS with no
AWS credentials. Entries from mid-2026 point to a GitHub repository, which the
script shallow-clones. It lists the `logs/` folder once to learn which
instances exist, intersects that with the selected issues, and downloads two
files per instance:

- `patch.diff`, the candidate patch the system produced
- `report.json`, the official harness result for that patch

Downloads run in a thread pool and are cached under
`data/raw/<submission>/<instance_id>/`. A `meta.json` marker records what was
fetched, so rerunning the script skips finished instances.

Finally it writes one JSON line per (submission, instance) with the patch text
and the parsed report, plus the agent, model and organisation from the
metadata.

**Choosing submissions.** Three modes:

- No flag uses `DEFAULT_SUBMISSIONS`, ten systems chosen to balance model
  families (Claude, GPT, Gemini, Qwen, Kimi, GLM, Llama, undisclosed) and to
  span weak to strong. Systems without public logs are skipped with a message.
- `--auto K` reads the catalog, sorts by resolve rate, splits into K
  quantiles, and takes the most recent entry with a new agent and organisation
  from each. This gives both weak and strong systems.
- `--submissions` takes explicit folder names.

**Output.** `data/candidates_raw.jsonl`, roughly 5,000 rows for the defaults.

## Step 3: write harness-format prediction files

```bash
.venv/bin/python pipeline/build_predictions.py
```

**What is executed.** The official harness reads a JSONL file of
`{"instance_id", "model_patch", "model_name_or_path"}` objects and keys them by
instance id, so one file can hold only one candidate per issue. The script
groups the raw candidates by submission, drops empty patches, and writes one
file per submission to `data/predictions/`.

These files are only needed for step 4. The public `report.json` files already
contain the official grades, so most runs never use them.

## Step 4 (optional): regrade with the official harness

```bash
./pipeline/run_harness.sh --gold -i django__django-11099      # environment sanity check
./pipeline/run_harness.sh --only 20250522_tools_claude-4-sonnet --instances "django__django-11099"
./pipeline/run_harness.sh -j 2                                # everything, slowly
```

**What is executed.** The script checks Docker is running and warns if the
host is below the harness recommendations of 16 GB RAM and about 120 GB free
disk. It installs the `swebench` package into `.venv` if missing, then for each
prediction file runs:

```bash
swebench eval verified -p data/predictions/<submission>.jsonl --run-id trustgate-<submission> -j 2 -t 1800
```

The harness pulls or builds a Docker image per issue, applies the patch, runs
the issue's tests, and writes
`logs/run_evaluation/trustgate-<submission>/<submission>/<instance_id>/report.json`
in exactly the same format as the public reports. `--modal` sends the work to
Modal's cloud instead of local Docker.

**Why you would run it.** To reproduce the public grades, to grade patches
from a new source, or to audit a disagreement. This Mac has 8 GB of RAM, which
is below the recommendation, so keep `-j` at 1 or 2 and limit scope with
`--instances` or `--only`.

**Feeding results back.**

```bash
.venv/bin/python pipeline/build_candidate_table.py --local-reports logs/run_evaluation
```

Local reports override the public ones for the candidates they cover.

## Step 5a (optional): static code-health features

```bash
.venv/bin/python pipeline/static_checks.py
.venv/bin/python pipeline/static_checks.py --repos psf/requests --workers 1
```

**What is executed.** The notebook lists `syntax_ok`, `compile_ok` and the
lint counts as high-value features, but they need the code at the issue's base
commit. The script clones each of the 12 repositories with
`git clone --filter=blob:none`, which fetches history but downloads file
contents lazily. For each issue it checks out `base_commit`, and for each
candidate patch of that issue:

1. `git apply --check`, falling back to GNU `patch --fuzz=5` exactly as the
   harness does, gives `patch_apply_ok`.
2. If the patch applies, every changed or added `.py` file is parsed with
   `ast.parse` (`syntax_ok`), compiled with `compile()` (`compile_ok`), and run
   through pyflakes. Message counts become `lint_warning_count`,
   `static_error_count`, `undefined_name_count` and `import_error_count`.
3. `git checkout -- .` and `git clean -fdq` restore the tree.

Repositories run in parallel, one thread each; work inside a repository is
sequential because it shares one working tree. Results append to
`data/static_features.csv`, and reruns skip candidates already present.

**Cost.** The three smallest repositories took 25 seconds for 76 candidates.
The full run is dominated by Django's 231 issues and will take a while, and
the clones use a few gigabytes under `data/repos/`.

## Step 5: build the candidate table

```bash
.venv/bin/python pipeline/build_candidate_table.py
.venv/bin/python pipeline/build_candidate_table.py --static data/static_features.csv
```

**What is executed.** For each raw candidate the script:

1. Drops it if the patch is empty. An empty patch is not a PR candidate.
2. Reads the harness report and derives:
   - `patch_apply_ok` from `patch_successfully_applied`
   - `fail_to_pass_rate` and `pass_to_pass_rate` as passed over total for the
     issue's two test lists
   - `resolved_status` using the harness definition. FULL means every
     FAIL_TO_PASS and PASS_TO_PASS test passed. PARTIAL means some FAIL_TO_PASS
     passed and all PASS_TO_PASS passed. NO covers everything else, including a
     patch that failed to apply.
   - `label` as 1 for FULL and 0 otherwise
   - `evaluation_error` set to `missing_report` when there is no report at all
3. Computes `self_consistency` per candidate: the mean similarity to the other
   candidates for the same issue, defined as half the Jaccard overlap of
   touched files plus half the line-level sequence ratio of added lines. Issues
   with a single candidate get NaN.
4. Joins the static features if `--static` is given.
5. Writes the main CSV with exactly the notebook's `CANDIDATE_COLUMNS`, in
   order, and a separate CSV for ungraded rows.
6. Prints the label balance, resolve rate by agent and by difficulty, and
   whether the notebook's training gate is met.

**Output.**

- `data/trustgate_candidate_results.csv`, the file the notebook loads
- `data/trustgate_candidate_evaluation_errors.csv`, the rows with no grade

Ungraded rows are kept out of the main CSV by default because the notebook
requires every label to be present before it trains. `--include-errors` keeps
them in.

**Columns left empty.** `temperature`, `visible_test_pass_rate`,
`visible_test_fail_count`, `ci_job_failure_count`, `ci_job_success_rate` and
`model_confidence` are NaN. The public submissions do not record them. The
notebook's imputer fills NaN with the median, so the baseline still trains on
the patch-shape features.

## Step 6: point the notebook at the file

Nothing to do by hand. The candidate-loading cell now reads
`data/trustgate_candidate_results.csv` relative to the notebook, or the path
in the `TRUSTGATE_CANDIDATES` environment variable. On Colab, the bootstrap
cell after the pip install runs steps 1 to 3 of this pipeline in place, or
mounts Drive and points the variable at an uploaded CSV. Rerun from that cell onward and the split,
baseline, ROC and PR curves, calibration, threshold grid and bootstrap cells
all activate.

## Step 8: production pull requests

```bash
export GITHUB_TOKEN=ghp_...        # or: gh auth login
.venv/bin/python pipeline/import_github_prs.py --repo your-org/your-repo --limit 500
```

**What is executed.** The script resolves a GitHub token from `GITHUB_TOKEN` or
the `gh` CLI (without one the API allows 60 requests per hour, enough for about
12 PRs). It lists closed pull requests newest first, and for each one fetches
the PR detail (additions, deletions, files changed), the unified diff, the
reviews, and the check runs on the head commit. Reviews collapse to one verdict
per reviewer, so approvals and change requests are counted per person. Check
runs become success and failure counts and a success rate. Once per repository
it scans the default branch's commits from the oldest merge in the batch to 30
days after the newest, looking for "Revert ... (#123)" or "This reverts commit
<sha>", and flags merged PRs that were reverted.

**Output.** `data/production_prs.csv` with one row per PR. Reruns append and
de-duplicate on the PR URL.

**Using it.** Notebook section 20 maps that file onto `CANDIDATE_COLUMNS` with
one of three label rules (merged and not reverted, merged, or approved) and
writes `data/production_candidates.csv`. Point `TRUSTGATE_CANDIDATES` at it and
rerun from section 8. Never mix benchmark and production rows in one run; they
answer different questions.

## Experiment results from the reference run

Test split of 100 issues, 981 candidates, issue-grouped. Columns are ROC-AUC.

| Feature set | Features | Logistic | Gradient boosting |
|---|---|---|---|
| 1. Patch shape | 5 | 0.528 | 0.612 |
| 2. + agreement (`self_consistency`) | 6 | 0.687 | 0.726 |
| 3. + code health (static checks) | 13 | 0.705 | **0.737** |
| 4. + semantic (TF-IDF, issue length) | 16 | 0.724 | 0.734 |

Issue-level bootstrap, 500 resamples: baseline 0.53 (0.47 to 0.59), best 0.74
(0.69 to 0.79). Leave-one-repository-out with the best model ranges from 0.62
(requests) to 0.80 (matplotlib), row-weighted mean 0.74, so the model transfers
to unseen codebases about as well as to unseen issues.

Three-way gate with the best model, thresholds chosen on validation to reach
90 percent approve and reject precision: approve at p >= 0.80, reject at
p <= 0.20. On the frozen test split that gives 24 percent automatic coverage,
77 percent approve precision and 93 percent reject precision. The approve
precision fell from 91 percent on validation, which is the small validation
set (100 issues) overfitting the threshold, and is exactly what the frozen test
split exists to reveal.

**Sections 19.6 and 19.7 on Verified.** The monotonic, early-stopped tree
scored 0.71 test AUC against 0.74 for the plain tree, within the bootstrap
interval, so the constraints cost a little on 500 issues rather than helping.
Cross-validated thresholds chosen on out-of-fold predictions over 400 issues
gave 76 percent approve precision on test, the same as the single split. The
conclusion is that the limit on Verified is the number of issues, not the
algorithm, which is the case for running the full set.

### Full set results (2,294 issues)

Built with `./run_pipeline.sh --split full --static`: 21,985 graded candidates
from the 10 systems with complete logs, 32 percent labeled 1. Static checks
covered 21,957 of them (99.4 percent applied, 99.5 percent of those parsed).
Test split of 459 issues, 4,414 candidates.

| Feature set | Features | Logistic | Gradient boosting |
|---|---|---|---|
| 1. Patch shape | 5 | 0.574 | 0.650 |
| 2. + agreement | 6 | 0.636 | 0.688 |
| 3. + code health | 13 | 0.638 | **0.690** |
| 4. + semantic | 16 | 0.647 | 0.689 |

Issue-level bootstrap: baseline 0.57 (0.54 to 0.60), best 0.69 (0.66 to 0.72).
The interval is half the width of the Verified one, which is what the larger
set was for. Leave-one-repository-out ranges from 0.56 (requests) to 0.75
(flask), weighted mean 0.685, again matching the random split. Code health and
text similarity add almost nothing on top of agreement here; agreement carries
the signal on both splits.

The monotonic tree (19.6) scored 0.68, calibrated ECE 0.03. Cross-validated
thresholds (19.7) over 1,835 out-of-fold issues could not reach 90 percent
approve precision; the best reachable with at least 5 percent auto-approvals
was 63 percent. The chosen gate, approve at p >= 0.60 and reject at p <= 0.50,
gave on test: 10 percent auto-approved at 58 percent precision, 89 percent
auto-rejected at 70 percent precision, 1 percent to human review.

**Reading the two splits together.** More issues delivered tighter, more
trustworthy estimates, which was the goal. The absolute AUC is lower on the
full set for three reasons that have nothing to do with the algorithm: the
full set contains the noisy issues that Verified's human review filtered out,
its ten systems are older and weaker, and only a third of its patches work, so
a 90 percent approve precision bar is far above the base rate. On the full set
the model is a useful rejecter and reviewer-prioritizer, not an approver.

**Next steps, in course order.** Sharpen the agreement feature (cluster size
per issue, function-level overlap via the syntax tree, within-issue ranking),
run a full error analysis, then try a learned code representation such as a
fine-tuned CodeBERT or CodeT5 on issue-plus-patch pairs. Keep an LLM judge as
a final ceiling experiment only: it is costly, hard to reproduce without an API
key, and the judge may recognise patches written by its own model family or
repositories it saw in training.

## Notebook sections 19 and 20

The pipeline feeds section 8. Sections 19 and 20 were added to use what it
produces:

- **19.1** TF-IDF similarity between the issue text and the patch's added lines, fitted on training issues only.
- **19.2** Feature ablation: patch shape, plus agreement, plus code health, plus semantic, for logistic regression and gradient boosting, with permutation importance for the best model.
- **19.3** Leave-one-repository-out evaluation.
- **19.4** Issue-level bootstrap intervals for the baseline and the best model.
- **19.5** The three-way gate with the best model, thresholds chosen on validation to meet a precision target.
- **19.6** A stronger tree: gradient boosting with monotonic constraints (more agreement can only raise the score, more static errors can only lower it), early stopping instead of a fixed tree count, and isotonic calibration fitted on the validation split.
- **19.7** Cross-validated thresholds: 5-fold grouped cross-validation over every non-test issue produces out-of-fold predictions, an isotonic calibrator and the approve and reject thresholds are fitted on those, and one final model is refit on all non-test issues and evaluated once on test.
- **19.8** Exports the final model, calibrator, feature list, thresholds and vectorizer to `models/trustgate_gate_verified.joblib` for `pipeline/score_patch.py`.
- **20** Production PR schema, label rules, and conversion to the candidate schema.

## Scoring a new patch

```bash
.venv/bin/python pipeline/score_patch.py --patch fix.diff --issue issue.txt --sibling other1.diff --sibling other2.diff
```

**What is executed.** Loads `models/trustgate_gate_<split>.joblib` (Verified by
default; set `TRUSTGATE_SPLIT=full` for the full-set model) written by notebook
cell 19.8, computes the same features for the new diff (patch shape from the
diff, agreement against any sibling patches, TF-IDF similarity if the issue
text is given and the model uses it), leaves unknown features NaN, runs the
model, applies the isotonic calibrator saved with it, and prints the
probability and the approve / human_review / reject decision using the
frozen cross-validated thresholds. `--feature name=value` overrides any feature, for example
to pass code-health results from your own CI. `--json` prints a machine
readable result. The same logic is importable: `from score_patch import score_patch`.

## Things to keep in mind

**One candidate per system per issue.** The candidates for an issue come from
different systems rather than repeated samples of one system. That is a
reasonable stand-in for independent attempts, and `self_consistency` measures
cross-system agreement. If you later add your own agent's samples, the same
schema applies.

**Do not add diff features to the CSV.** The notebook computes
`patch_additions` and friends itself from the `patch` column. Adding them to
the CSV would create duplicate column names after the notebook's concat.

**Leakage.** The CSV contains `resolved_status`, `fail_to_pass_rate` and
`pass_to_pass_rate` because the notebook's schema asks for them as diagnostic
fields. They are outcomes, not predictors. The notebook's feature lists
exclude them; keep it that way.

**Labels are benchmark correctness.** A 1 means the patch passed the issue's
tests in the harness environment. It says nothing about code quality,
security or whether a maintainer would merge it.

**Splitting.** Always split by `instance_id`. Seven candidates for the same
issue must land in the same fold, which the notebook's grouped split already
enforces.

## File map

| Path | Role |
|---|---|
| `run_pipeline.sh` | Runs steps 1, 2a, 2b, 3 and 5 in order |
| `pipeline/common.py` | Paths, HTTP session, S3 listing, dataset cache, schema |
| `pipeline/select_issues.py` | Step 1 |
| `pipeline/list_submissions.py` | Step 2a |
| `pipeline/fetch_candidates.py` | Step 2b |
| `pipeline/build_predictions.py` | Step 3 |
| `pipeline/run_harness.sh` | Step 4, optional |
| `pipeline/static_checks.py` | Step 5a, optional |
| `pipeline/build_candidate_table.py` | Step 5 |
| `pipeline/import_github_prs.py` | Step 8, production PR import |
| `pipeline/score_patch.py` | Score a new patch with the model exported by notebook cell 19.8 |
| `data/` | Verified outputs, ignored by git |
| `data/full/`, `data/lite/` | Outputs for the other splits |
