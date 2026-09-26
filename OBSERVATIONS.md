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

## What would settle it empirically

Two cheap experiments, both already on the list in `MLReview.md`.

1. **Add author identity as a feature in a side experiment**, not for
   deployment, only to measure how much of the gap is reputation. If AUC
   jumps, the shortfall is information the current design excludes on
   purpose, and the write-up can say so with a number.

2. **Run the LLM judge once on Verified as a ceiling.** If a foundation
   model's rating lifts AUC well past 0.8, the shortfall was information and
   our approach was the constraint. If it does not, the label itself is too
   noisy to predict from anything short of running the tests, and the honest
   conclusion becomes that a pre-test gate cannot approve unattended at all.

Either answer is a strong finding. The first says "here is the information to
add and what it is worth"; the second says "this decision needs execution,
and here is the proof".

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
