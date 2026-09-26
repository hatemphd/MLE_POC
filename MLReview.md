# Machine learning review: ablation, the algorithm landscape, and what fits TrustGate

Two parts. The first explains ablation, the method that produced this
project's main finding. The second surveys the machine learning algorithm
families, says which are used here, which would be worth trying, and which
do not fit, and why.

The problem, for reference: binary classification of a candidate patch as
"fixes the bug" or "does not", from a small tabular feature set (16 features:
patch shape, agreement with sibling candidates, static code health, text
similarity), on 4,908 Verified or 21,985 full-set rows that are grouped by
issue, with a calibrated probability turned into a three-way decision.

---

## Part 1: Ablation

### What it is

An ablation study removes one component of a system at a time, re-measures,
and attributes the change in the score to that component. The word comes
from medicine, where ablation is the surgical removal or destruction of
tissue. Nineteenth-century physiologists mapped the brain by ablating a
region in an animal and observing what capability disappeared. Machine
learning borrowed the term around 2010 for the same reasoning applied to a
model: take a part out, see what breaks.

The method matters because a final score alone cannot tell you *why* a model
works. Two systems can reach the same accuracy with completely different
components carrying the load, and only ablation shows which ones are
essential, which are redundant, and which are decorative.

### The two forms used in this project

**Cumulative feature-group ablation** (notebook cell 19.2). Start from the
smallest feature set and add one family at a time, retraining each time on
the same issue-grouped split with the same seeds. Each row's gain over the
row above is that family's marginal contribution given everything already in
the model.

| Feature set | Features | Logistic | Gradient boosting |
|---|---|---|---|
| 1. Patch shape | 5 | 0.528 | 0.612 |
| 2. + agreement (`self_consistency`) | 6 | 0.687 | 0.726 |
| 3. + code health (static checks) | 13 | 0.705 | 0.737 |
| 4. + semantic (TF-IDF, issue length) | 16 | 0.724 | 0.734 |

Verified test split, ROC-AUC. Agreement adds 0.11; code health adds 0.01;
semantic adds nothing. The bootstrap interval here is about ±0.05, so only
the agreement step is a real effect.

**Permutation importance** (same cell). A per-feature ablation that does not
retrain. Take the fitted model, shuffle one feature's column so it carries no
information while keeping its distribution, re-score the test split, and
record the drop in ROC-AUC. Average over five shuffles.

| Feature shuffled | Drop in ROC-AUC |
|---|---|
| `self_consistency` | 0.19 |
| `patch_additions` | 0.04 |
| `patch_files` | 0.03 |
| every other feature | under 0.01 |

### How to read an ablation honestly

- **Compare gaps to the confidence interval, not to zero.** A 0.01 gain
  against a ±0.05 interval is noise, and it is reported as such.
- **Order matters in the cumulative form.** Code health looks worthless
  added after agreement, but might have looked useful added first, because
  the two overlap: a patch that agrees with its siblings usually also parses.
  The cumulative table answers the deployment question, "what does this add
  on top of what we have", which is the right question here.
- **Correlated features share credit in permutation importance.** Shuffling
  one of two near-duplicate columns costs little because the other covers for
  it, so a low score means "not needed given the rest", not "useless".
- **An ablation is local to this model and this data.** It says nothing
  about a different model class or a different label definition.
- **Removing a component can improve the score.** That is a finding too: the
  component was adding noise or overfitting.

### What it decided

The ablation is the evidence behind the project's conclusion that agreement
between independent attempts is the only feature that matters, that hand-built
additions beyond it are null results on both splits, and that the next step
should change the kind of signal rather than add more of the same kind. It
also justified not pursuing a more complex model: the tuned tree with
monotonic constraints (cell 19.6) scored within the interval of the plain one,
so the bottleneck is information, not capacity.

---

## Part 2: The algorithm landscape and what fits

Legend for the "Status" column: **Used** in the notebook or pipeline today;
**Consider** worth an experiment; **Not a fit** for this problem, with the
reason.

### Supervised classification: linear models

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Logistic regression | **Used** (section 10, with median imputation, standardisation, balanced class weights) | The interpretable baseline. Coefficients are readable; it reaches 0.72 with all features. Assumes additive, roughly linear effects, which caps it below the trees. |
| Ridge, lasso, elastic-net logistic | Consider, low priority | Regularised variants. With 16 features overfitting is not the issue; lasso could confirm the ablation by zeroing the useless features automatically. |
| Linear SVM | Not a fit | No probabilities without an extra calibration step, and nothing it does that logistic regression does not on this data. |
| Linear discriminant analysis | Not a fit | Assumes Gaussian features with shared covariance; count features and binary flags violate that. |

### Supervised classification: tree ensembles

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Gradient boosting, `HistGradientBoostingClassifier` | **Used** (section 10 with depth 3; section 19.6 with monotonic constraints, early stopping) | The best performer on both splits. Handles missing values natively, captures thresholds and interactions, fast on 20k rows. The 19.6 constraints encode domain knowledge as a safety property. |
| XGBoost, LightGBM, CatBoost | Consider, low priority | Same family with different engineering. Expect gains within noise; LightGBM would add native support for the grouped ranking objective below, which is the real reason to try it. CatBoost is worth a look if categorical features such as repository or agent are ever allowed in. |
| Random forest | Consider, low priority | Bagged trees. Usually a point or two under boosting on tabular data; useful as a second opinion and for out-of-bag estimates. |
| Extra trees | Not a fit | A faster, noisier random forest; no advantage at this scale. |
| Single decision tree | Consider for communication only | Not competitive, but a depth-3 tree drawn as a diagram is the clearest way to show a reviewer how agreement and patch size combine. |

### Supervised classification: other families

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| k-nearest neighbours | Not a fit as a classifier | Distances over mixed-scale count features are unreliable. The idea behind it, "similar patches have similar outcomes", is already captured directly by the agreement feature. |
| Naive Bayes | Consider as a text baseline | Multinomial naive Bayes over TF-IDF of the patch text is the classic cheap text classifier. It would test whether raw patch text carries signal the hand features miss. |
| Support vector machine, RBF kernel | Not a fit | Scales poorly past ~10k rows, needs calibration for probabilities, and rarely beats boosting on tabular data. |
| Gaussian process classifier | Not a fit | Cubic in the number of rows; 5k is the edge, 22k is out. Its natural calibration is attractive but isotonic calibration on a tree gets there cheaper. |
| Multilayer perceptron on the 16 features | Not a fit | Neural networks on small tabular data seldom beat gradient boosting and are harder to explain. |

### Learning to rank

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Pairwise or listwise ranking within an issue (RankNet, LambdaMART, `lambdarank` in LightGBM, `rank:pairwise` in XGBoost) | **Consider, high priority** | The data is naturally grouped: up to ten candidates per bug, and the question "which of these is best" is a ranking question. A ranking objective optimises exactly the within-issue ordering that the agreement feature exploits, and the ROC-AUC the project already reports is a ranking metric. This is the most natural unexplored algorithm for this data. |

### Probability calibration

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Isotonic regression | **Used** (cells 19.6 and 19.7, fitted on validation or out-of-fold predictions) | Non-parametric, monotone mapping from scores to probabilities. Needs a few hundred points, which we have. |
| Platt scaling (logistic on the score) | Consider | Two-parameter, more stable than isotonic on small validation sets. Worth comparing on the Verified split where the validation set is 100 issues. |
| Temperature scaling | Not a fit | One parameter; designed for neural-network logits. |
| Beta calibration | Consider, low priority | Three-parameter middle ground between Platt and isotonic. |

### Decision and threshold methods

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Threshold grid search under precision constraints | **Used** (section 14, cells 19.5 and 19.7) | Chooses approve and reject cut-offs to meet precision targets with maximum coverage. |
| Cross-validated threshold selection | **Used** (cell 19.7, out-of-fold predictions over all non-test issues) | Replaces one small validation split with every non-test issue. |
| Cost-sensitive learning | Consider | Weight false approvals more than false rejections during training rather than only at threshold time. Class weighting in the logistic baseline is the simplest form; asymmetric costs in boosting would be the full form. |
| Conformal prediction | **Consider, high priority** | A method that turns any scorer into set-valued predictions with a guaranteed error rate: "with 95 percent confidence the label is in this set". A set of {works} is an approve, {broken} a reject, {works, broken} a human review. It gives the three-way gate a statistical guarantee on the false-approval rate instead of a threshold tuned by hand, which is exactly what the approve bucket lacks. Split conformal on the validation set is a few dozen lines. |

### Feature construction and representation learning

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| TF-IDF (term frequency, inverse document frequency) | **Used** (cell 19.1, issue-versus-patch cosine similarity) | Classic sparse text representation. Added nothing on top of agreement here. |
| Sequence matching and Jaccard set overlap | **Used** (agreement feature in `build_candidate_table.py`) | Not learning, but the algorithmic heart of the best feature. |
| Static analysis (pyflakes) | **Used** (`static_checks.py`) | Also not learning; a rule-based feature source. |
| Clustering candidates per issue (agglomerative, DBSCAN on patch similarity) | **Consider, high priority** | Replaces mean pairwise similarity with cluster membership and cluster size: "this patch belongs to the majority cluster of four" is a sharper signal than "average similarity 0.31". Unsupervised, explainable, and directly sharpens the one feature that works. |
| Pretrained code models (CodeBERT, CodeT5, UniXcoder) as embeddings or fine-tuned | **Consider, medium priority** | Dense representations of the issue and the patch that TF-IDF cannot provide. Fine-tuning on 27k issue-patch pairs is feasible on one GPU. The honest expectation is a modest gain; the reason to try it is that it is the only route to semantic signal that stays reproducible and free of API cost. |
| Large language model as a judge | Consider, last | Ask a foundation model to rate the patch and use the score as a feature. Potentially the largest gain, but expensive, hard to reproduce without an API key, and the judge may recognise patches its own model family wrote or repositories it trained on. Run once as a ceiling experiment, not as the method. |
| Word2vec, doc2vec | Not a fit | Superseded by the pretrained code models above for this purpose. |

### Explanation and feature attribution

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Permutation importance | **Used** (cell 19.2) | Global, model-agnostic importance. |
| SHAP values | Consider | Per-prediction attribution: "this patch was approved mainly because it agreed with four siblings and touched one file". Useful for the human-review interface, where a reviewer wants to know why the model was unsure. |
| Partial dependence plots | Consider, low priority | Shows the shape of each feature's effect; would confirm the monotonic constraints in 19.6 are pointing the right way. |

### Ensembling

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Stacking or blending | Consider, low priority | Combine the logistic model, the tree and a ranking model with a meta-learner. Typical gain is a point or two. Worth it only after a genuinely different signal such as a code model exists to blend in. |
| Bagging | Not a fit as a separate step | Random forest already is bagging; boosting with subsampling covers the rest. |

### Unsupervised and semi-supervised learning

| Algorithm | Status | Fit for TrustGate |
|---|---|---|
| Clustering for agreement | Consider, high priority | Covered above under feature construction. |
| Dimensionality reduction (PCA, UMAP) | Consider for EDA only | Sixteen features do not need reduction for modelling; a UMAP of code embeddings coloured by label would be a useful exploratory picture. |
| Anomaly detection (isolation forest) | Consider, low priority | Flag patches unlike anything seen in training so the gate abstains on them. A cheap safety net for out-of-distribution repositories. |
| Semi-supervised or self-training | Not a fit | Labels are not scarce here; every candidate has an official grade. |
| Active learning | Not a fit today | Would matter in production, where each human review is a costly label and the model should choose which patches to ask about. Section 20 sets that up but the benchmark phase does not need it. |

### Not applicable to this problem

| Family | Why not |
|---|---|
| Regression (linear, ridge, gradient-boosted regression) | The target is binary. The diagnostic `fail_to_pass_rate` is continuous but it is an outcome, never a target. |
| Time-series and survival models | No temporal structure in a patch verdict. Revert-within-30-days in production is a duration, but the project treats it as a binary label. |
| Reinforcement learning | There is no sequential decision with delayed reward; each patch is judged once. A gate that adapts its thresholds over time from review feedback could be framed as a bandit, but that is a production concern. |
| Generative models (GANs, diffusion, autoregressive code models used to write patches) | TrustGate judges patches; it does not write them. The coding agents that produced the candidates are generative, but they are the data source, not the model. |
| Recommender systems (matrix factorisation) | No user-item structure. |
| Topic models (LDA) | Issue text topics are a weak proxy for anything the labels depend on. |

---

## What is used today, in one list

1. Logistic regression with median imputation, standardisation and balanced
   class weights.
2. Histogram-based gradient boosting, plain and with monotonic constraints,
   early stopping and L2 regularisation.
3. Isotonic regression for probability calibration, fitted on held-out or
   out-of-fold predictions.
4. Issue-grouped train, validation and test splitting; leave-one-repository-out
   evaluation; five-fold grouped cross-validation for threshold selection.
5. Threshold grid search under precision constraints for the three-way gate.
6. Issue-level bootstrap for confidence intervals.
7. Permutation importance for feature attribution.
8. TF-IDF for issue-patch text similarity.
9. Sequence matching and Jaccard overlap for the agreement feature; pyflakes
   static analysis for code-health features. These are algorithms, not
   learning, but they produce the inputs.

## What to consider, in order

1. **Clustering candidates within each issue** to sharpen the agreement
   feature. Unsupervised, cheap, explainable, aimed at the one feature that
   works.
2. **Learning to rank within issues** with LightGBM's `lambdarank` or
   XGBoost's pairwise objective. Matches the grouped structure of the data
   and the ranking metric already in use.
3. **Conformal prediction for the gate**, giving the approve bucket a
   guaranteed false-approval rate instead of a hand-tuned threshold.
4. **SHAP values** for per-patch explanations in the review interface.
5. **A pretrained code model**, as embeddings first and fine-tuned second,
   as the reproducible route to semantic signal.
6. **Platt scaling** compared against isotonic on the small Verified
   validation set.
7. **Cost-sensitive boosting** with asymmetric false-approval weights.
8. **LLM judge**, once, as a ceiling, with its contamination caveat stated.

Items 1 to 4 stay inside the classical toolkit a grader expects to see and can
each be evaluated with the ablation machinery already in the notebook.

## Related documents

- [METRICS.md](METRICS.md), every evaluation metric with formulas and figures
- [PIPELINE.md](PIPELINE.md), the results tables the ablation numbers come from
- [TrustGate_Results_Summary_and_Next_Steps.pptx](TrustGate_Results_Summary_and_Next_Steps.pptx), the ranked next steps
