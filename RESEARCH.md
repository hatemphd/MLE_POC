# Research note: Laya as a pre-step feature for TrustGate

Can Laya run before the model and supply a feature that improves it? Yes, and
it is the natural next design. There are two ways to do it and one trap to
avoid.

## The two ways to use Laya as a pre-step

**Stacking, already built.** Laya scores each patch, TrustGate scores it, and
a small logistic model fitted on the validation issues combines the two
probabilities. This is what experiment 2b in `TrustGateExperimentation.ipynb`
does for every judge file it finds. It needs Laya scores only for validation
and test. Cheap and honest, but the combination is a two-input line, so the
tree never sees Laya's number alongside the other sixteen features.

**A seventeenth feature, the stronger version.** Score every candidate,
including the training issues, and add `p_laya` as a column in the table the
tree trains on. The tree can then learn interactions such as "Laya says yes
and agreement is high", which a two-input stack cannot. This is the design to
pursue if Laya carries signal. It requires scoring the training rows too:
`laya_judge.py run --scope all`, about three extra hours on this CPU at 1,024
tokens, or minutes on a GPU.

## The trap: leakage through the pre-step

Zero-shot Laya has never seen our labels, so its scores can be used on any
row without concern.

**Fine-tuned Laya is different.** If it is fine-tuned on the training issues
and then scores those same issues to build the feature, the training rows get
scores from a model that has memorised their labels. The downstream tree
learns "trust Laya completely", and that lesson is false on new patches.

**The fix is cross-fitting.** Split the training issues into five folds.
Fine-tune Laya five times, each time on four folds, and score the fifth, so
every training row's Laya score comes from a model that never saw it.
Validation and test are scored by a Laya fine-tuned on all training issues.
This is the same out-of-fold discipline notebook cell 19.7 already applies to
threshold selection, one layer down. Never skip it; a leaky feature looks
spectacular on training data and collapses on test.

## What to expect

- **Zero-shot.** The smoke test scored every patch between 0.93 and 0.98,
  broken ones included, which is the over-confidence Laya's own card warns
  about. If the full run looks the same, the feature has almost no spread and
  will add nothing. That is the likely outcome and it is a legitimate null
  result, worth one line in the write-up.
- **Fine-tuned.** This is where a gain would come from. Laya reads the code's
  meaning; none of our sixteen features do. The ablation concluded that
  missing information is the ceiling, and a fine-tuned decision model is a
  reproducible, key-free way to add information.

## In production terms

Laya as a pre-step costs about 30 milliseconds per patch on a small GPU or a
couple of seconds on a CPU, well inside what a review gate can afford.
TrustGate then takes seventeen inputs instead of sixteen and stays exactly as
fast. `pipeline/score_patch.py` would call Laya first and pass its number
along with the other features.

## Result so far

Zero-shot Laya scored 0.553 AUC alone and left the baseline unchanged when
stacked (0.735 against 0.737). Its probabilities have almost no spread, so as
a seventeenth feature it would be a near-constant column. Step 2 and 3 of the
plan below are therefore deferred until a fine-tuned checkpoint exists; the
plan is unchanged otherwise.

## Plan

1. Finish the zero-shot scoring of validation and test (running), evaluate
   alone and stacked in experiment 2b, and record the result in
   `OBSERVATIONS.md`.
2. Score the training rows too (`--scope all`).
3. Add an experiment 4 cell to `TrustGateExperimentation.ipynb`: retrain the
   tree with `p_laya` as the seventeenth feature; compare against the baseline
   and the two-input stack with bootstrap intervals; rerun the ablation and
   permutation importance so Laya's contribution is a number.
4. Fine-tune on Kaggle with the exported dataset (`laya_judge.py
   export-finetune`, recipe in `EXPERIMENT2.md`), using five-fold
   cross-fitting for the training-row scores, and rerun experiment 4 with the
   fine-tuned scores.
5. If the seventeen-feature model beats the baseline outside the bootstrap
   interval, update `score_patch.py` to call Laya first, and re-export the
   gate bundle.

## Related

- [EDUCATIONAL.md](EDUCATIONAL.md), what System 1 decision models are
- [EXPERIMENT2.md](EXPERIMENT2.md), how to run Laya and how to fine-tune it
- [OBSERVATIONS.md](OBSERVATIONS.md), where results are recorded
