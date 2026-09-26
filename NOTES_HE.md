# Notes: is it still machine learning engineering with an LLM judge?

Yes, provided the judge stays in the role the design gives it. The distinction
is between using a model as a component you measure and using it as a
substitute for the work.

## What makes this project ML engineering

It has nothing to do with which learner sits in the middle. It is:

- the data pipeline that turns published artifacts into a labelled table
- the leakage rules: no tests, no reference fix, no author identity as a production feature
- the issue-grouped splits and the leave-one-repository-out check
- the feature engineering and the ablation that attributes the score to its causes
- the calibration and the threshold selection on validation, frozen before test
- the bootstrap intervals on every headline number
- the operational metrics for the three-way gate
- the export and scoring path, and the honest write-up of a ceiling

None of that changes when a new feature arrives.

## The judge, as scaffolded, is a feature

Its output is one column. It is:

- evaluated on a held-out split with a bootstrap interval
- combined with the existing model through a logistic stack fitted on validation only
- ablated against the baseline, so its marginal contribution is a number
- audited for contamination by the model family that wrote each candidate

Stacking a foundation model's score into a supervised learner is a standard
technique. Treating an expensive model as a label-free oracle and then
measuring exactly what it buys is arguably more engineering, not less: cost per
candidate, latency, reproducibility and failure modes all become design
questions.

## Where it would stop being ML engineering

If the project became "send the patch to a language model and use its answer"
with no labels, no held-out evaluation, no calibration and no comparison to
the cheap model, it would be prompt engineering wearing an ML title. The
guard-rails against that drift are already in the design:

- the judge is framed as a ceiling experiment, run once
- it never replaces the trained gate
- the results table states its marginal contribution in ROC-AUC points and in dollars

## Two things that keep it defensible in front of a reviewer

1. **Commit the scores file** (`data/llm_judge/<split>_scores.jsonl`) once the
   run completes, so anyone can reproduce the evaluation without an API key.
2. **Report cost and latency next to accuracy.** A reviewer who sees 0.85 AUC
   at about 12 dollars per 2,000 patches and half an hour of batch time,
   against 0.74 in microseconds for free, is looking at an engineering
   trade-off. That trade-off is the whole point of the field.

## Related

- [EXPERIMENT2.md](EXPERIMENT2.md), how to run the judge
- [MLReview.md](MLReview.md), the algorithm landscape and why the judge ranks last among the experiments for a course
- [OBSERVATIONS.md](OBSERVATIONS.md), where the outcome gets recorded
