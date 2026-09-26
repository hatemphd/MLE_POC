# Observations: why the model is still weak on auto-approve and auto-reject

The question: is the weakness on the automatic buckets caused by the data or
by our solution approach? The evidence points at a third thing, the
information the model is allowed to see, and this note lays out the reasoning
using our own results.

## Where the model stands

| | Verified (500 issues) | Full (2,294 issues) |
|---|---|---|
| Best ROC-AUC | 0.74 | 0.69 |
| Auto-approve precision on test | 76% | 58% |
| Auto-reject precision on test | 93% | 70% |

Approve precision needs to be 90 to 95 percent before unattended merging is
defensible. The reject side is usable on Verified and not on the full set.

## It is not the quantity of data

Going from 500 to 2,294 issues halved the confidence interval and did not
raise the score. If the model were data-starved, four and a half times more
issues would have helped. The full set is also harder and has a lower base
rate, which lowered the absolute numbers, but the direction is clear: more
rows of the same features do not move the ceiling.

## It is not the learning algorithm

The tuned tree with monotonic constraints, early stopping and isotonic
calibration (cell 19.6) scored within the error bar of the plain tree from
section 10. Logistic regression and gradient boosting land within a few
points of each other on every feature set. When several very different
learners plateau at the same place, they have extracted what the features
contain. A bigger or cleverer model of the same sixteen numbers will not
change the picture.

## It is the features: three pieces of evidence

1. **The ablation is a one-feature story.** Agreement between candidates
   carries 0.19 of ROC-AUC under permutation; every other feature carries
   under 0.01. We are running a sixteen-feature model that is in practice a
   one-feature model with decoration.

2. **The selection test shows what is missing.** Used their way, to pick one
   candidate per bug, our model chooses correctly 64 percent of the time.
   Agreement alone also scores 64. The trivial rule "always trust the
   strongest system" scores 74. The oracle, any candidate works, scores 83.
   A ten-point gap is closed by one piece of information we exclude, who
   wrote the patch, and nine more points sit above that.

3. **The calibration curve bends at the top.** In the 0.9 to 1.0 bin the
   model says 0.93 on average and is right 82 percent of the time. It cannot
   separate a confident-looking wrong patch from a right one, because nothing
   in its inputs distinguishes them. That is exactly what caps approve
   precision at 76.

## Which of our choices caused the shortfall

These were deliberate constraints, each with a reason and each with a cost.

| Choice | Why we made it | What it costs |
|---|---|---|
| Patch-only, no execution | Cheap, no Docker, milliseconds per patch | The label is defined by tests and we never run any. The single biggest gap. |
| No author identity as a feature | Avoid learning "trust vendor X"; judge the code, not the brand | About ten points of selection accuracy on Verified |
| Agreement as mean pairwise similarity | Fast, dependency-free | Blurs the majority-cluster structure that Agentless exploits with voting |
| No semantics beyond TF-IDF | Reproducible, no API cost | Cannot tell whether the change addresses what the issue describes |
| One candidate per system per issue | That is what the leaderboard offers | Agreement is across ten heterogeneous writers, not several samples from one |

## Verdict in one sentence

The model is weak on the automatic buckets because we chose to judge patches
from their surface and their peers alone, and surface plus peers is worth
about 0.73 ROC-AUC on this benchmark, regardless of how much data or how good
a learner is brought to it.

## The verdict unpacked: what "surface plus peers is worth about 0.73" means

The sentence makes four claims. Each is defined and then backed by a
measurement from our own data.

### What "surface" and "peers" mean

**Surface** is everything the model can read off the patch text without
running it or understanding it: lines added and removed, files and hunks
touched, total size, whether it parses and compiles, how many warnings a
linter raises, how many words it shares with the bug report. Fifteen of our
sixteen features are surface.

**Peers** is the one feature that is not: how similar the patch is to the
other candidates for the same bug. It reads nothing about correctness
directly; it reads consensus.

Nothing else reaches the model. Not the tests, not the reference fix, not the
author, not what the code means, not what happens when it runs.

### What "worth about 0.73 AUC" means

It is an empirical ceiling, not a theoretical one. It is the best score any
learner we tried reached on the held-out Verified test split when given
those sixteen numbers, and the figure that several very different learners
converged on. Read it as: the information in surface plus peers is enough to
rank a working patch above a broken one 73 times in 100, and we found no way
to get more out of the same inputs. On the full set the same inputs are worth
0.69, because those issues are harder and the base rate lower. The ceiling is
a property of the features on a given data set, not a universal constant.

### Why "regardless of how much data"

We measured a learning curve: train the same tree model on a random 10, 25,
50, 75 and 100 percent of the training issues, score on the fixed test
split, five random draws per size.

| Training issues | Training patches | Tree model AUC | Logistic AUC |
|---|---|---|---|
| 30 | 293 | 0.682 ± 0.028 | 0.704 ± 0.009 |
| 75 | 731 | 0.723 ± 0.008 | 0.707 ± 0.008 |
| 150 | 1,478 | 0.733 ± 0.006 | 0.707 ± 0.005 |
| 225 | 2,197 | 0.731 ± 0.006 | 0.707 ± 0.002 |
| 300 | 2,936 | 0.737 | 0.705 |

The tree model is within noise of its final score from 150 issues onward.
The logistic model is flat from 30. Doubling the data from 150 to 300 issues
moved the score by 0.004. The full-set run is the same experiment at a larger
scale: 4.6 times the issues, tighter interval, no higher score. A model that
is limited by data keeps climbing as data grows. This one stopped.

### Why "regardless of how good a learner"

Five learners on the same features: logistic regression 0.72, plain
gradient boosting 0.74, gradient boosting with monotonic constraints and
early stopping 0.71, the same with isotonic calibration 0.71, and the
cross-validated final model 0.72. All within one confidence interval of each
other. When learners as different as a straight line and a boosted ensemble
plateau at the same place, the plateau belongs to the inputs, not to the
learners.

### The direct evidence: identical inputs, different answers

If the features do not contain the information, then patches with the same
feature values should sometimes have different labels, and no model can
separate those. We checked. Rounding agreement to one decimal and size to
the nearest 50 characters, 946 of the 4,908 Verified patches share their
feature vector with at least one other patch. Among those, 405 patches sit in
groups that contain both a working and a broken patch. For those 405 the
best any model can do is a coin flip, and that is not a modelling failure;
the inputs are literally the same.

Two more numbers say the same thing. The agreement feature used on its own,
with no model at all, scores 0.657 AUC. The best model with all sixteen
features scores 0.737. So the other fifteen features plus a boosted ensemble
together add 0.08 on top of one raw number. Patch size alone scores 0.525,
almost nothing.

### What the sentence does not claim

- It does not say 0.73 is the ceiling for any pre-test judge. It is the
  ceiling for these sixteen features. Sharper agreement (cluster membership
  instead of mean similarity), code embeddings or execution evidence are
  different information and can move it. The selection test suggests how far:
  author identity alone would close a ten-point gap, and the oracle sits nine
  points above that.
- It does not say the label is unpredictable. It says it is not predictable
  from the surface of the patch and the shape of its peers.
- It does not say more data is useless. More issues bought a much tighter
  estimate, which is what made this argument possible.

### How the conclusion was reached, in order

1. Ablation showed one feature carrying the signal and fifteen adding under
   0.01 each.
2. Swapping learners changed nothing outside the interval.
3. The learning curve flattened at half the training data, and the full-set
   run confirmed it at scale.
4. Feature-identical patches with opposite labels showed the irreducible
   part directly.
5. The selection test showed which excluded information would move the
   number, and by how much.

Each step rules out one explanation. What remains is the information the
model is given, which is a design choice we made deliberately and can
revisit.

## What would settle it empirically, and what has been measured

Two experiments, both in `TrustGateExperimentation.ipynb`. Both are side
experiments for measurement, not for deployment.

### Experiment 1, done: author identity as a feature

Same split and baseline as the main notebook, Verified test split of 100
issues and 986 patches. Reputation is encoded as the author's resolve rate on
the training issues only, so it cannot leak test information.

| Model | Test ROC-AUC | 95% interval | Approve precision (share) | Reject precision (share) | Top pick resolves |
|---|---|---|---|---|---|
| Baseline, 13 surface + agreement | 0.737 | 0.686 to 0.793 | 0.767 (15%) | 0.918 (10%) | 0.66 |
| + one-hot author | 0.768 | 0.722 to 0.814 | 0.783 (20%) | 0.947 (13%) | 0.68 |
| + author prior (train resolve rate) | 0.773 | 0.729 to 0.816 | 0.792 (19%) | 0.946 (15%) | 0.67 |
| Author prior alone, no patch information | 0.692 | 0.663 to 0.725 | 0.740 (10%) | 0.901 (9%) | 0.74 |
| Always take the strongest system | | | | | 0.74 |
| Oracle, any candidate works | | | | | 0.83 |

**Reading.** Reputation is real but modest. It adds 0.035 of AUC, which is
inside the baseline's bootstrap half-width, and lifts approve precision from
77 to 79 percent, still far from the 90 percent bar. Reputation alone scores
0.69 and, used as a selector, exactly reproduces the "always take the
strongest system" rule at 0.74; but adding it to the patch features does not
move the selection rate, which stays at 0.67. So the ten-point selection gap
noted earlier is not simply recoverable by knowing the author: the patch
features and the reputation signal overlap more than they add. Reputation is
a few points of the missing information, not most of it. The rest is
semantics and execution, which experiment 2 probes.

### Experiment 2, ready to run: an LLM judge as the ceiling

Built in `pipeline/llm_judge.py` and wired into the experimentation notebook.
It scores only the validation and test candidates (1,972 on Verified),
through the Message Batches API at half price, with structured JSON output.
Estimated cost for the whole run:

| Model | Batch price |
|---|---|
| claude-opus-5 | about 12.50 USD |
| claude-sonnet-5 | about 5.00 USD |
| claude-haiku-4-5 | about 2.50 USD |

To run it, once, with `ANTHROPIC_API_KEY` set:

```bash
.venv/bin/python pipeline/llm_judge.py submit --model claude-opus-5
.venv/bin/python pipeline/llm_judge.py collect
```

then rerun the experimentation notebook from experiment 2a. It evaluates the
judge alone, a logistic stack of judge plus TrustGate fitted on validation,
and a per-model-family breakdown as the contamination check. The decision
rule is written in the notebook: a stack above 0.80 means the shortfall was
information and our approach was the constraint; below it, the label is too
noisy to predict without running the tests and a pre-test gate should not
approve unattended.

## Implications for how we describe the project

- Present TrustGate as a prioritiser and rejecter today, not an approver.
- Present the 0.73 as the value of surface-plus-agreement information, a
  useful and reproducible number, rather than as a model shortfall.
- Present the next steps as changing the kind of information the model sees:
  sharper agreement, semantic signal, execution evidence, production labels.

## Related documents

- [MLReview.md](MLReview.md), the ablation and the ranked experiments
- [METRICS.md](METRICS.md), the calibration and gate figures cited above
- [SWEBench_TrustGate.md](SWEBench_TrustGate.md), the selection test and comparison to verifier work
