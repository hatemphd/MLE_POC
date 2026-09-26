# The candidate-label pipeline, explained in plain English

Companion to `PIPELINE.md`, which has the technical detail. This file answers
two questions: what the pipeline does.

## What the pipeline does

### The problem

The notebook can only train a model once it has a table of real examples:
candidate patches for real bugs, each stamped with "this one worked" or "this
one did not." The notebook itself had no way to make that table. It just said
"generate patches with an AI coding agent and grade them in Docker," which
would have meant paying for thousands of AI calls and running a very heavy
grading setup that this Mac cannot handle.

### The shortcut

SWE-bench is a public benchmark. Over the last two years, dozens of teams have
pointed their AI coding tools at the same 500 bugs and published every patch
their tool wrote. The benchmark maintainers then ran the official tests on
each patch and published the results too. So the work we needed done already
exists on the internet: real patches, real pass/fail grades, free to download.
Instead of generating our own candidates, we borrow theirs.

### The steps, in order

1. **Pick the bugs.** Download the list of 500 bugs and decide which to use.
   By default it uses all of them, but it can take a smaller sample that still
   covers every codebase and every difficulty level.

2. **Make a catalog of who has submitted.** Look at the 182 teams that
   published results and note, for each one, which AI tool they used, how well
   it scored, and whether their patches are downloadable. About 170 of them
   are.

3. **Download the patches and their grades.** For ten chosen teams, fetch
   two small files per bug: the patch that team's tool wrote, and the official
   report saying whether it passed the tests. That is about 5,000 patches,
   downloaded in a few minutes over ordinary web requests.

4. **Turn the grades into labels.** Read each report and decide: did the patch
   fully fix the bug, partly fix it, or not fix it at all? "Fully fixed"
   becomes a 1. Everything else becomes a 0. Patches that never got graded,
   because a report is missing, are set aside in a separate file rather than
   being mislabeled as failures.

5. **Add signals the model is allowed to see.** For each patch, compute things
   you could know before running any tests. The main one is agreement: how
   similar is this patch to the other nine patches for the same bug? If ten
   independent tools all changed the same file in the same way, that is a hint
   the fix is right. Optionally, the pipeline can also apply each patch to the
   real codebase and check whether the code still parses and whether a linter
   complains.

6. **Hand it to the notebook.** Write everything into one spreadsheet-style
   file in exactly the column layout the notebook expects. The notebook now
   finds that file automatically, so all the previously dormant cells light
   up and run: the train/test split, the baseline model, the calibration
   plots, and the approve/review/reject thresholds.

### What came out

A table of 4,908 candidate patches covering all 500 bugs, 58 percent of
which worked and 42 percent of which did not. That balance is good for training.
The first simple model, using only the size and shape of each patch, barely
beats a coin flip. Adding one feature, how much a patch agrees with the other
candidates for the same bug, lifts it to a clearly useful 0.73. The rest of
section 19 in the notebook explores that further.

| Measure | Value |
|---|---|
| Graded candidates | 4,908 |
| Bugs covered | 500 of 500 |
| Codebases covered | 12 of 12 |
| Patches that fully worked (label 1) | 2,830 |
| Patches that did not (label 0) | 2,078 |
| Ungraded, kept in a separate file | 10 |
| Baseline ROC-AUC, patch shape only | 0.53 |
| Best model ROC-AUC, plus agreement feature | 0.73 |

### What is optional

There is a script that can regrade the patches yourself using the official
Docker harness, if you ever want to verify the public results or grade patches
from a new source. It is heavy and this Mac is under the recommended memory,
so it is there but not required.

## Which systems the patches come from

The pipeline never calls any AI model. The names below are the leaderboard
teams whose already-published patches we download, and the model each team
used when it generated them.

| Submission | Agent framework | Model | Resolve rate |
|---|---|---|---|
| 20251120_livesweagent_gemini-3-pro-preview | live-SWE-agent | Gemini 3 Pro | 78% |
| 20250522_tools_claude-4-sonnet | Anthropic tools harness | Claude 4 Sonnet | 72% |
| 20251014_Lingxi_kimi_k2 | Lingxi | Kimi K2 | 71% |
| 20250807_openhands_gpt5 | OpenHands | GPT-5 | 72% |
| 20250805_openhands-Qwen3-Coder-480B | OpenHands | Qwen3 Coder | 70% |
| 20250930_zai_glm4-6 | undisclosed | GLM-4.6 | 69% |
| 20241202_amazon-q-developer-agent | Amazon Q | undisclosed | 55% |
| 20241028_agentless-1.5_gpt4o | Agentless | GPT-4o | 39% |
| 20240620_sweagent_claude3.5sonnet | SWE-agent | Claude 3.5 Sonnet | 35% |
| 20250720_mini-v0.0.0-Llama-4-Scout | mini-SWE-agent | Llama 4 Scout | 9% |

Two Claude, two GPT, and one each of Gemini, Qwen, Kimi, GLM, Llama and
undisclosed. An earlier default list was four-sevenths Claude-based; it was
replaced because a pool dominated by one model family makes the agreement
feature measure "agrees with that family" rather than "independent attempts
agree." Which system wrote a patch is deliberately not a feature.

Your own 99-system table from the 23rd is kept as
`data/trustgate_candidate_results_99systems.csv`.

## What the experiments found

Section 19 of the notebook runs the comparisons. On a held-out set of 100
bugs the model never trained on:

- **Patch size and shape alone** give 0.53 AUC, barely better than a coin flip.
- **Adding agreement**, how similar a patch is to the other candidates for the
  same bug, lifts that to 0.73. It is by far the most important feature.
- **Adding code health**, whether the patch applies, parses, compiles and what
  a linter says, reaches 0.74, the best result.
- **Adding text similarity** between the bug report and the patch adds nothing
  on top of that. A clean negative result.
- **Holding out whole repositories** gives 0.62 to 0.80 depending on the
  project, averaging the same 0.74, so the model transfers to codebases it
  has never seen.
- **The gate**: thresholds tuned to 90 percent approve precision on the
  validation bugs delivered 77 percent on the test bugs, with about a quarter
  of patches decided automatically. The drop is the small validation set
  overfitting the threshold, which is precisely what the frozen test split is
  there to catch.

## Why we added the full 2,294-issue set

The study's real sample size is the number of bugs, not the number of
patches, because ten patches for one bug rise and fall together. With 500
bugs, the slice used to pick the approve cut-off holds only 100, and a
cut-off picked on 100 bugs wobbles: it promised 90 percent approve precision
and delivered 76. The full SWE-bench test set has 2,294 bugs, and the same
leaderboard mechanism publishes graded patches for it, so
`./run_pipeline.sh --split full` builds a second table under `data/full/`
with about four and a half times the bugs. Its systems are older and weaker,
and only about a third of their patches work, which is fine: the point is
more bugs, not stronger patches.

**What happened.** The uncertainty halved, exactly as hoped: the best model's
score is known to within plus or minus 0.03 instead of 0.05. The score itself
is lower, 0.69 against 0.74, because the full set keeps the messy bugs that
Verified's human reviewers threw out, its patch-writing systems are a
generation older, and only one patch in three works. At that base rate the
model cannot find a group of patches it is 90 percent sure about. It can still
reject with 71 percent precision and route the rest to a reviewer, so on the
full set TrustGate is a triage tool, not an approver.

## Two more algorithms, in plain English

**A tree model that respects common sense.** The upgraded gradient boosting
model in section 19.6 is told which way each clue must point: more agreement
with other patches can only raise the score, more lint errors can only lower
it. It also stops adding trees when they stop helping, and its probabilities
are re-mapped so that "70 percent" really means seven in ten. On the 500-bug
set this scored about the same as the plain tree; the constraints matter more
as a safety property than as an accuracy gain.

**Cut-offs chosen on every bug, not one small slice.** Section 19.7 rotates
through the non-test bugs five times, each time predicting the fifth it held
out, so every bug gets a prediction from a model that never saw it. The approve
and reject cut-offs are then chosen on all of those predictions at once, and
one final model is trained on everything and checked exactly once on the
untouched test bugs. That model, its calibration and its cut-offs are what
`score_patch.py` uses.

## Scoring a new patch

The notebook saves the best model to `models/trustgate_gate_verified.joblib`. From the
terminal:

```bash
.venv/bin/python pipeline/score_patch.py --patch fix.diff --issue issue.txt --sibling other.diff
```

It prints the probability and approve, human review or reject. Give it the
other candidates for the same bug as siblings whenever you have them.
