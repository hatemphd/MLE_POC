# Machine learning review

A teaching document in three parts. Part 1 explains ablation, the method that
produced this project's main finding. Part 2 is one table of the machine
learning algorithms a student should know, in plain English, with a verdict
on each for this problem. Part 3 is the shortlist of experiments most likely
to make the model perform better, and why.

**The problem in one sentence.** Given a proposed code fix, predict whether it
will pass the bug's tests, using 16 numbers we can compute before running
anything, and turn that prediction into approve, reject or ask a human.

**Where we stand.** The best model ranks a good patch above a bad one 73 times
out of 100 on the 500-issue set (ROC-AUC 0.73) and 69 times on the
2,294-issue set. Only one feature really matters: how much the patch agrees
with the other candidates for the same bug. Everything else we tried added
little. The bottleneck is the information in the features, not the learning
algorithm.

---

## Part 1: Ablation in plain English

### The idea

Imagine a car that will not start. You unplug one part at a time and try the
key. When you unplug the battery, nothing happens at all; when you unplug the
radio, it starts fine. Now you know which part matters. That is ablation.

The word is medical. Nineteenth-century scientists worked out what each part
of the brain did by removing it in animals and watching what ability was
lost. Machine learning borrowed the word around 2010 for the same procedure
applied to a model: take one piece out, measure again, and the drop in the
score is what that piece was worth.

### Why we need it

A single final score cannot tell you why a model works. Two models can reach
the same score with entirely different parts doing the work. Ablation tells
you which parts are essential, which are redundant, and which are decoration.
It is the difference between "the model scored 0.74" and "the model scored
0.74, and 0.19 of that comes from one feature".

### The two ways we did it

**Adding features one family at a time** (notebook cell 19.2). Train with only
patch size and shape. Add the agreement feature and train again. Add code
health. Add text similarity. Same data split, same random seeds every time, so
each row's gain over the row above is exactly what that family added.

| Feature set | Features | Logistic regression | Gradient boosting |
|---|---|---|---|
| 1. Patch shape only | 5 | 0.528 | 0.612 |
| 2. + agreement with sibling patches | 6 | 0.687 | 0.726 |
| 3. + code health (parse, compile, lint) | 13 | 0.705 | 0.737 |
| 4. + text similarity to the bug report | 16 | 0.724 | 0.734 |

Verified test split, ROC-AUC. Read down the right column: agreement adds
0.11, code health adds 0.01, text adds nothing. The uncertainty on this test
split is about plus or minus 0.05, so only the agreement step is real.

**Scrambling one feature at a time** (same cell, called permutation
importance). Keep the trained model. Shuffle one feature's column so the
values are still realistic but no longer belong to the right patches. Score
again. The drop is how much the model was relying on that feature.

| Feature scrambled | Drop in ROC-AUC |
|---|---|
| Agreement with sibling patches | 0.19 |
| Lines added | 0.04 |
| Files touched | 0.03 |
| Everything else | under 0.01 each |

### Four rules for reading an ablation

1. **Compare gaps to the uncertainty, not to zero.** A gain of 0.01 when the
   error bar is 0.05 is not a finding.
2. **Order matters when adding cumulatively.** Code health looks useless added
   after agreement, but might have looked useful added first, because the two
   overlap: patches that agree with their siblings usually also parse. The
   cumulative table answers "what does this add to what we already have",
   which is the question that matters for deployment.
3. **Twins share credit when scrambling.** If two features carry the same
   information, scrambling either one costs little because the other covers
   for it. A low score means "not needed given the rest", not "useless".
4. **Ablation is local.** It describes this model on this data. A different
   model class or a different label could rank the features differently.

### What it decided here

Agreement between independent attempts is the only feature that matters.
Hand-built additions beyond it are null results on both data sets. The tuned
tree with monotonic constraints (cell 19.6) scored within the error bar of the
plain tree, so a bigger model is not the answer either. The next steps in
Part 3 therefore change the *kind* of information the model sees rather than
the model that sees it.

---

## Part 2: The algorithm landscape

One row per algorithm. **Plain-English idea** is what it does in a sentence.
**Status** is Used, Try or Skip for this project. **Why** is the reasoning.

### 2a. Models that predict a label from a table of numbers

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Logistic regression | Draw the straightest possible line between the two classes; each feature pushes the score up or down by a fixed amount. | **Used** | The honest baseline. Easy to explain, coefficients are readable. Reaches 0.72 but cannot learn "only when both X and Y" rules. |
| Lasso and ridge logistic regression | Same line, but penalised for using many features, so weak ones shrink to zero. | Try, low priority | Would confirm the ablation automatically by zeroing the useless features. Not a performance lever. |
| Decision tree | A flowchart of yes/no questions: is agreement above 0.4? are more than three files touched? | Try, for teaching only | Draw a depth-3 tree on a slide and students see how the features combine. Not competitive on its own. |
| Random forest | Grow hundreds of trees on random subsets of the data and features; let them vote. | Try, low priority | Robust and needs no tuning. Usually a point or two behind boosting on tabular data. Good second opinion. |
| Gradient boosting (`HistGradientBoostingClassifier`) | Grow small trees one after another, each one correcting the mistakes of the ones before. | **Used** | Best performer on both data sets. Handles missing values, learns thresholds and interactions, fast. Also used with monotonic constraints so agreement can only raise the score and lint errors can only lower it. |
| XGBoost, LightGBM, CatBoost | Same idea as above, different engineering; LightGBM also offers a ranking objective. | Try, medium priority | Accuracy gain will be within noise. The reason to install LightGBM is the ranking objective in 2d, not a better classifier. |
| k-nearest neighbours | Find the most similar patches seen before and copy their outcome. | Skip | Distances over mixed count features are unreliable, and the underlying idea is already captured directly by the agreement feature. |
| Naive Bayes | Assume every word or feature is independent and multiply the odds. | Try, as a text baseline | Cheap way to test whether the raw words in a patch carry signal the hand-built features miss. |
| Support vector machine | Find the boundary with the widest margin between classes, optionally bent by a kernel. | Skip | Slow past 10,000 rows, gives no probabilities without extra work, rarely beats boosting on tables. |
| Gaussian process | Treat the prediction as a smooth random function with built-in uncertainty. | Skip | Cost grows with the cube of the row count; 22,000 rows is out of reach. |
| Neural network on the 16 features | Layers of weighted sums and squashing functions. | Skip | On small tables, neural networks rarely beat gradient boosting and are harder to explain. |

### 2b. Turning scores into honest probabilities

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Isotonic regression | Learn a staircase that maps raw scores to probabilities so that "0.7" really means seven in ten. | **Used** | Fitted on held-out predictions in cells 19.6 and 19.7. Needs a few hundred points, which we have. |
| Platt scaling | Fit a two-parameter S-curve instead of a staircase. | Try | More stable when the calibration set is small, as on the 100-issue Verified validation split. Direct comparison is cheap. |
| Temperature scaling | Divide the scores by one number. | Skip | Built for neural-network outputs, too rigid here. |

### 2c. Turning probabilities into decisions

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Threshold grid search | Try every pair of approve and reject cut-offs; keep the one that meets the precision targets with the most coverage. | **Used** | Section 14 and cells 19.5, 19.7. |
| Cross-validated thresholds | Choose the cut-offs on predictions for every non-test issue, not one small slice. | **Used** | Cell 19.7. Removes the dependence on one 100-issue validation split. |
| Cost-sensitive learning | Tell the model during training that a false approval costs, say, five times a false rejection. | Try | Moves the trade-off into the model instead of only into the threshold. Balanced class weights in the logistic baseline are the simplest form. |
| Conformal prediction | Produce a *set* of plausible labels with a guaranteed error rate: {works}, {broken}, or {both}. | **Try, high priority** | A set of one label is an automatic decision; a set of both is a human review. It gives the approve bucket a mathematical guarantee on its false-approval rate, which is exactly what the project lacks. About fifty lines of code. |

### 2d. Ranking instead of classifying

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Learning to rank within a group (LambdaMART, `lambdarank`, pairwise objectives) | Instead of "is this patch good", learn "which of these ten patches for the same bug is best". | **Try, high priority** | Our data comes in groups of up to ten candidates per bug, and the agreement feature already compares within the group. A ranking objective optimises that comparison directly, and ROC-AUC, our headline metric, is a ranking metric. The most natural unexplored algorithm for this data. |

### 2e. Building better features

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| TF-IDF (term frequency, inverse document frequency) | Represent text by which rare words it contains. | **Used** | Cell 19.1, issue-versus-patch similarity. Added nothing on top of agreement. |
| Sequence matching and set overlap | Measure how much two patches change the same files and the same lines. | **Used** | The algorithmic core of the agreement feature. Not learning, but the best thing in the project. |
| Static analysis (pyflakes) | Rule-based checks: does it parse, are names defined, are imports used. | **Used** | Code-health features. Small gain. |
| Clustering candidates within an issue | Group the ten patches for a bug into families of similar fixes; record which family each belongs to and how big it is. | **Try, high priority** | "Member of the majority family of four" is a sharper signal than "average similarity 0.31". Unsupervised, cheap, explainable, and it sharpens the one feature that works. |
| Pretrained code models (CodeBERT, CodeT5, UniXcoder) | Neural networks trained on millions of programs that turn code into vectors capturing meaning, not just words. | Try, medium priority | The reproducible route to semantic signal that TF-IDF cannot give. Use as frozen embeddings first, fine-tune second. Feasible on one GPU with 27,000 issue-patch pairs. |
| System One decision models (Laya, open weights; Jev, API) | A non-autoregressive encoder that reads a document and answers a typed yes/no, choice or score question with a calibrated probability in one pass, no text generation. | **Try, high priority** | Same contract as TrustGate itself: calibrated probability in, three-way decision out. Fine-tuned on our graded patches it is the key-free, reproducible way to test whether reading the code's meaning moves the ceiling, with calibration built in and no contamination from having written patches. Zero-shot is weak by its own card; fine-tuning needs a T4 (Kaggle or Colab). |
| Large language model as a judge | Ask a model like Claude or GPT to read the bug and the patch and rate the fix. | Try, last, as a ceiling | Possibly the largest gain, but costly, hard for a grader to reproduce, and the judge may recognise patches written by its own model family or repositories it saw in training. Run once to learn how much headroom exists. |
| Word2vec, doc2vec | Older word-vector methods. | Skip | Superseded by the code models above. |

### 2f. Explaining predictions

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Permutation importance | Scramble one feature and see how much the score drops. | **Used** | Cell 19.2. Global view. |
| SHAP values | For one prediction, split the score into a contribution from each feature. | Try | "Approved mainly because it agreed with four siblings and touched one file" is what a reviewer wants to see next to a patch. |
| Partial dependence plots | Show the shape of one feature's effect while averaging the others. | Try, low priority | Would visually confirm the monotonic constraints point the right way. |

### 2g. Combining models

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Stacking and blending | Feed several models' predictions into one final model. | Try, low priority | Typically a point or two. Worth it only once a genuinely different signal, such as a code model, exists to blend. |
| Bagging | Train on bootstrap samples and average. | Skip | Random forest is bagging; boosting with subsampling covers the rest. |

### 2h. Learning without labels

| Algorithm | Plain-English idea | Status | Why |
|---|---|---|---|
| Clustering | Group similar items with no labels. | Try, high priority | See 2e, agreement clustering. |
| PCA and UMAP | Squash many dimensions into two for a picture. | Try, for exploration | A UMAP of code embeddings coloured by label would be a good teaching figure. Not needed for modelling 16 features. |
| Anomaly detection (isolation forest) | Flag items unlike anything seen in training. | Try, low priority | Lets the gate abstain on patches from unfamiliar territory. A cheap safety net. |
| Semi-supervised and self-training | Use unlabelled data to help. | Skip | Every candidate already has an official label. |
| Active learning | Let the model choose which items a human should label next. | Skip for now | Matters in production, where each review is an expensive label. Section 20 sets that up. |

### 2i. Families that do not fit this problem

| Family | Why not |
|---|---|
| Regression | The target is yes or no, not a quantity. |
| Time series and survival analysis | A patch verdict has no time dimension. |
| Reinforcement learning | No sequence of actions with delayed reward; each patch is judged once. |
| Generative models | TrustGate judges patches; it does not write them. The coding agents that wrote the candidates are generative, but they are the data source. |
| Recommender systems | No users choosing among items. |
| Topic models | Bug-report topics are a weak proxy for whether a fix works. |

---

## Part 3: The experiments most likely to improve performance

Ordered by expected payoff per unit of effort, with the reasoning a student
could defend. Each can be scored with the ablation machinery already in
section 19, so the result is a row in a table, not an opinion.

### 1. Cluster the candidates within each issue

**What.** For each bug, group its ten candidate patches into families of
similar fixes (agglomerative clustering or DBSCAN on the same similarity the
agreement feature already computes). New features per patch: size of its
family, whether it is in the largest family, how many families exist.

**Why it should help.** Agreement is the only feature that works, and today
it is an average. Averages hide structure. Four patches that all make the
same change and six that each do something different is a strong signal for
the four; the average similarity for one of the four is dragged down by the
six. Cluster membership sees the structure the average blurs.

**Expected gain.** A few points of ROC-AUC. Cheap. No new dependencies.

### 2. Learn to rank within the issue

**What.** Switch the objective from "is this patch good" to "order these ten
patches from best to worst" using LightGBM's `lambdarank` or XGBoost's
pairwise objective, with the issue as the group.

**Why it should help.** The model currently compares a patch against every
other patch in the data set. Most of those comparisons are pointless: a
Django patch versus a Sympy patch tells us nothing. The useful comparison is
against the other attempts at the same bug, and a ranking objective spends all
of its effort there. Our headline metric is already a ranking metric.

**Expected gain.** Uncertain but potentially the largest of the classical
options. The absolute probability for the gate would then come from a
calibration step on top of the ranking score.

### 3. Conformal prediction for the gate

**What.** Replace the hand-tuned approve threshold with a procedure that
outputs, for each patch, the set of labels it is at least 95 percent sure
contains the truth. One label in the set is an automatic decision; both
labels means human review.

**Why it should help.** It does not raise ROC-AUC, but it fixes the project's
actual failure: approve precision promised 90 percent and delivered 76. With
conformal prediction the false-approval rate is guaranteed by construction on
future data drawn like the calibration data, and coverage falls out as the
honest consequence rather than being tuned.

**Expected gain.** A trustworthy approve bucket, probably smaller than today's.

### 4. A System One decision model fine-tuned on our patches (Laya)

**What.** Laya is an open-weights, non-autoregressive decision model: give it
the issue and the diff as the state and ask one yes-or-no question, does this
patch fully fix the issue, and it returns a calibrated probability in a single
forward pass. Score the validation and test candidates zero-shot first
(`pipeline/laya_judge.py`, runs on the CPU), then fine-tune on the training
issues with the published Kaggle notebook and score again.

**Why it should help.** It reads the code's meaning, which none of our sixteen
features do, and it is trained to be calibrated, which the gate depends on. It
is reproducible by a grader without an API key, and it has never written a
patch, so the contamination worry attached to LLM judges does not apply.

**Expected gain.** Zero-shot, little or none; its own benchmark card says so.
Fine-tuned, this is the experiment most likely to move the ceiling among the
key-free options.

### 5. Pretrained code embeddings

**What.** Run the issue text and the patch through CodeBERT or UniXcoder,
take the vectors, and add their cosine similarity and a few projected
dimensions as features. Later, fine-tune the model on the issue-patch pairs.

**Why it should help.** Text similarity by TF-IDF added nothing because it
only sees shared words. A code model knows that `close()` and `release the
handle` are about the same thing. It is the only route to semantic signal
that stays reproducible and free of API cost.

**Expected gain.** Modest, a few points, with the fine-tuned version doing
better than frozen embeddings.

### 6. Cost-sensitive boosting

**What.** Weight false approvals more heavily than false rejections while
training the tree model.

**Why it should help.** Today the model is trained to be right on average and
the asymmetry is applied afterwards by the threshold. Building the asymmetry
in lets the model spend its capacity where mistakes are expensive.

**Expected gain.** Better approve precision at the same coverage; small
effect on ROC-AUC.

### 7. SHAP explanations

**What.** Compute per-patch feature contributions for the exported model.

**Why it matters.** Not a performance lever, but the human-review bucket
holds 80 percent of patches on Verified. A reviewer who sees "the model was
unsure because the patch agreed with no sibling and touched five files" works
faster and catches more. That is a system-level performance gain even though
the model's score does not move.

### 8. Platt versus isotonic calibration

**What.** Fit the two-parameter S-curve alongside the isotonic staircase and
compare Brier score and expected calibration error on the test split.

**Why.** The Verified validation set is 100 issues; the staircase may be
overfitting it. A half-hour experiment.

### 9. LLM judge, once

**What.** Ask a foundation model to rate each of the 4,908 Verified patches
before seeing the outcome; add the rating as a feature; rerun the ablation.

**Why last.** It could be the biggest single gain, but it costs money, cannot
be reproduced by a grader without an API key, and the judge may recognise
patches its own model family wrote or repositories it trained on. Run it once
to learn how much headroom exists above the classical methods, and frame the
result as a ceiling rather than a solution.

### What not to spend time on

More hyperparameter tuning of the tree model, more hand-built size or lint
features, deeper networks on the 16 features. The ablation already shows the
returns are inside the noise. Performance now comes from new information,
not from a better learner of the same information.

---

---

## Note: what "trustworthy candidate labels" means, and where Docker and Modal fit

The notebook's original plan (section 7) says "Use Docker or Modal to create
trustworthy candidate labels." Three definitions unpack it.

**Candidate labels.** The answers the model trains on: for each candidate
patch, 1 if it fixed the bug and 0 if it did not. Everything the model learns
rests on these being right, which is why the label source matters more than
the model choice.

**Trustworthy.** The label came from actually running the bug's tests
against the patch, inside the exact software environment the project used at
the time, rather than from a guess, a heuristic or a model's opinion. A patch
for a 2019 Django bug has to be tested against 2019 Django with its 2019
dependencies, or the verdict is meaningless. Reproducing that environment
faithfully is the hard part of labelling.

**Docker or Modal.** The two ways to get such an environment. Docker builds
an isolated container on the local machine with the right repository version
and dependencies, applies the patch, runs the tests and reports pass or fail.
Modal is a cloud service that runs those same containers on rented machines,
so local memory and disk stop being the limit. The SWE-bench harness supports
both behind one flag.

**Why this project did not run either.** The SWE-bench maintainers already
ran that Docker process on every leaderboard submission and published the
verdicts. The pipeline downloads them. The labels are equally trustworthy,
because they were produced the same way, and the 16 GB of memory and hours of
container time were skipped. The optional `pipeline/run_harness.sh` remains
for the day a patch nobody has graded needs a label, for example one from an
agent of our own; see `DOCKER.md`.

## Related documents

- [METRICS.md](METRICS.md), every evaluation metric with formulas and figures
- [PIPELINE.md](PIPELINE.md), the results tables the ablation numbers come from
- [TrustGate_Results_Summary_and_Next_Steps.pptx](TrustGate_Results_Summary_and_Next_Steps.pptx), the same priorities as slides
