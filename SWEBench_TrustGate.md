# SWE-bench and TrustGate: what they provide, what we built, and how to compare

This note answers four questions for the team: what the SWE-bench
organisation on GitHub actually provides, whether it publishes models our
project could mimic, who has attempted something like TrustGate, and how our
approach and findings differ. It closes with a reading list, ordered, with
the specific thing to check in each source so we can judge whether our
findings agree with the field or depart from it.

## 1. What github.com/SWE-bench provides

Three things, in decreasing order of how much our project uses them.

**The benchmark and the grader.** The `SWE-bench` repository holds the
datasets and the Docker evaluation harness.

| Dataset | Issues | Our use |
|---|---|---|
| SWE-bench (full test set) | 2,294 | Our `--split full` run |
| SWE-bench Verified | 500, human-confirmed solvable | Our default split |
| SWE-bench Lite | 300 | Supported, not run |
| Multimodal, Multilingual | separate task sets | Not used |

The harness applies a candidate patch inside a container at the issue's base
commit and runs the issue's tests. Its pass/fail verdict is the definition
behind every label in our tables.

**The public results.** The `experiments` repository is the leaderboard's
back office: one folder per submitted system with metadata, a README
describing the approach, per-repository results, and pointers to the
patches, grading reports and agent trajectories in a public S3 bucket. Our
pipeline downloads patches and reports from it; the 4,908 Verified and
21,985 full-set candidates in our tables are those submissions. The
leaderboard at swebench.com is rendered from this repository.

**Tools for building agents.** `SWE-smith` generates training tasks from any
repository and released `SWE-agent-LM-32B`, a fine-tuned Qwen 2.5 Coder that
reaches 40 percent on Verified. `sb-cli` runs evaluations in their cloud
instead of local Docker. The `SWE-agent` framework itself lives in a sibling
organisation. A `reading-list` repository catalogues related papers under
three headings: evaluation, agents, training.

## 2. Do they publish models we could mimic?

No, not for our problem. Every model the organisation has released, from the
original SWE-Llama 7B and 13B to SWE-agent-LM-32B, is a patch **writer**.
TrustGate is a patch **judge**. They sit on opposite sides of the same table:
their models produce the rows, ours scores them. The organisation publishes
no verifier, reward model or critic, and the harness has no notion of
confidence; it only says pass or fail after running the tests.

So there is nothing in the organisation's own code to copy. The relevant
prior work is in the leaderboard submissions and the papers they cite.

## 3. Who has done something like TrustGate

Four lines of work judge or select patches without, or before, running the
hidden tests. Each is on the Verified leaderboard or in its reading list.

**Agentless** (Xia et al., 2024). Generates several patches per issue, then
picks one by majority voting over normalised patches and by running
reproduction tests it writes itself. Its voting step is our agreement feature
under another name.

**SWE-Gym** (Pan et al., 2024). Trains a verifier, a fine-tuned language
model that reads an agent's whole trajectory and predicts whether it
succeeded, and uses it to choose the best of several attempts. This is the
"LLM judge" item on our next-steps list, done properly and measured.

**Skywork-SWE with test-time scaling** and **DeepSWE**. Both appear on the
Verified leaderboard twice, once as plain pass@1 and once with best-of-N
selection by a verifier. Skywork-SWE-32B goes from 38.0 to 47.0 percent with
best-of-8; DeepSWE-Preview from 42.2 to 58.8 percent with best-of-16. The gap
between the two rows is the measured value of a good judge, on the same 500
bugs we use.

**SWT-Bench** (Mündler et al., 2024). Judges a fix by generating tests for it
rather than by inspecting the patch. A different route to the same question.

## 4. How our approach differs

| | Their verifiers | TrustGate |
|---|---|---|
| Purpose | Pick the best of N samples from one system, to raise that system's pass rate | Approve, reject or route to a human, for a patch from any source |
| Model | A fine-tuned language model reading the trajectory or the patch | A gradient-boosted tree on 16 patch-level numbers |
| Candidates compared | Samples from the same agent on the same bug | Patches from ten different agents on the same bug |
| Output | A ranking; the top candidate is submitted | A calibrated probability and a three-way decision |
| Success metric | Pass@1 lift on the leaderboard | ROC-AUC, approve and reject precision, coverage, calibration |
| Cost per patch | An LLM call per candidate, sometimes with test execution | Microseconds; no model calls, no execution |
| Human in the loop | None | The middle bucket is the design centre |
| Training labels | Same harness verdicts | Same harness verdicts, plus a path to production merge and revert outcomes (section 20) |

Two consequences follow.

First, the published results support our headline finding rather than
contradicting it. Agreement among independent attempts is the strongest
signal anyone has reported without running tests, and expensive learned
verifiers are what buy the rest. Our ablation, in which agreement adds 0.11
of ROC-AUC and everything else adds nothing measurable, is consistent with
Agentless's majority voting being its most effective selection step.

Second, the field frames the task as ranking candidates within an issue,
not classifying each patch on its own. That is why learning to rank is item
two on our experiment list in `MLReview.md`. Our ROC-AUC is already a ranking
metric; a ranking objective would optimise it directly.

## 5. What to read, in order, and what to check in each

The goal of the reading is a one-page comparison: for each of our findings,
does the source agree, disagree, or not address it. The findings to test are
listed in section 6.

### Must read

1. **Agentless: Demystifying LLM-based Software Engineering Agents.**
   Xia, Deng, Dunn, Zhang. arXiv 2407.01489, 2024.
   https://arxiv.org/abs/2407.01489
   *Check:* section on patch selection and reranking. How much does majority
   voting alone add versus reproduction tests? Compare with our agreement
   feature's 0.11 gain. Note their normalisation of patches before voting;
   ours compares raw added lines and touched files, which is cruder.

2. **Training Software Engineering Agents and Verifiers with SWE-Gym.**
   Pan, Wang, Neubig, Jaitly, Ji, Suhr, Zhang. arXiv 2412.21139, 2024.
   https://arxiv.org/abs/2412.21139
   *Check:* the verifier section. What does the verifier read (trajectory,
   patch, both)? What best-of-N lift does it deliver, and how does verifier
   accuracy scale with training data? This is the ceiling experiment on our
   list, measured. Compare their verifier's discrimination with our 0.73.

3. **SWE-Gym's and Skywork-SWE's leaderboard entries.**
   `evaluation/verified/20250616_Skywork-SWE-32B+TTS_Bo8/README.md` and the
   Skywork blog it links, plus `20250629_deepswerl_r2eagent_tts/README.md` in
   https://github.com/SWE-bench/experiments.
   *Check:* the plain pass@1 row versus the test-time-scaling row for the
   same system. The difference is the value of a judge. Ask what their
   selector uses: a learned verifier, execution, or voting.

4. **SWE-bench: Can Language Models Resolve Real-World GitHub Issues?**
   Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan. ICLR 2024.
   https://arxiv.org/abs/2310.06770
   *Check:* the label definition (FAIL_TO_PASS and PASS_TO_PASS), and the
   leakage rules for submissions. Our leakage rules in the notebook derive
   from these. Also the difficulty distribution, which explains why our
   full-set results are lower than Verified.

5. **SWE-bench Verified announcement.** OpenAI, August 2024.
   https://openai.com/index/introducing-swe-bench-verified/
   *Check:* how the 500 were selected and what was filtered out. This is why
   Verified is cleaner and why our AUC dropped from 0.74 to 0.69 on the full
   set: the full set keeps the issues the annotators rejected.

### Should read

6. **SWT-Bench: Testing and Validating Real-World Bug-Fixes with Code
   Agents.** Mündler, Müller, He, Vechev. arXiv 2406.12952, 2024.
   https://arxiv.org/abs/2406.12952
   *Check:* whether test generation as a validation signal is something a
   cheap gate could use. It is execution-based, so it sits between our static
   features and the full harness.

7. **The `experiments` repository README and the submission checklist.**
   https://github.com/SWE-bench/experiments
   *Check:* the four checklist items every submission signs (pass@1, no test
   knowledge, no hints, no web browsing). Our candidate table inherits these
   guarantees, which is what makes the labels trustworthy.

8. **The SWE-bench reading list.**
   https://github.com/SWE-bench/reading-list
   *Check:* the evaluation section for anything on verification we have
   missed. As of our review it contained only SWT-Bench and SWE-Gym under
   that theme, which suggests patch judging without execution is thinly
   covered and our angle is less crowded than agent building.

### Background

9. **On Calibration of Modern Neural Networks.** Guo, Pleiss, Sun,
   Weinberger. ICML 2017. https://arxiv.org/abs/1706.04599
   *Check:* the definition of expected calibration error and reliability
   diagrams we use in `METRICS.md`, and temperature versus isotonic scaling.

10. **A Tutorial on Conformal Prediction.** Angelopoulos and Bates.
    arXiv 2107.07511, 2021. https://arxiv.org/abs/2107.07511
    *Check:* split conformal, section 1. This is the method behind the
    guaranteed-error-rate gate on our experiment list.

11. **Learning to Rank with LambdaMART.** Burges. Microsoft Research
    technical report MSR-TR-2010-82, 2010.
    https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/
    *Check:* the grouped objective; our groups are issues.

## 6. The findings to test against the reading

For each source, mark agree, disagree or silent.

| Our finding | Where we show it | Sources most likely to speak to it |
|---|---|---|
| Agreement between independent attempts is the dominant signal | Notebook cell 19.2, `METRICS.md` ablation | Agentless (voting), SWE-Gym (verifier versus voting baselines) |
| Patch size, code health and text similarity add little beyond agreement | Cell 19.2, both splits | Agentless ablations; SWE-Gym feature discussion |
| A cheap tabular model reaches 0.73 to 0.74 AUC on Verified | Cells 19.2 and 19.4 | SWE-Gym verifier accuracy; Skywork and DeepSWE best-of-N lifts |
| Approve precision of 76 percent is not enough for unattended merging | Cells 19.5 and 19.7, `METRICS.md` operational metrics | No direct comparison; the field reports pass@1 lift, not approval precision. This is a gap our project fills |
| More issues tighten the estimate but do not raise the score | `PIPELINE.md` Verified versus full results | SWE-bench Verified announcement (what the full set contains) |
| Model capacity is not the bottleneck; information is | Cell 19.6 versus 19.2 | SWE-Gym's data-scaling curves for verifiers |

Where a source disagrees, that is the most valuable finding in the course
write-up, provided we can say why: a different label, a different candidate
pool, a different metric, or a genuine contradiction.

## 7. Practical pointers

- **To read a submission's approach:** open
  `https://github.com/SWE-bench/experiments/blob/main/evaluation/verified/<submission>/README.md`.
  Every folder has one, with per-repository and per-year resolve rates.
- **To read a submission's raw trajectories:** they are in the same S3 prefix
  our pipeline reads, under `trajs/` instead of `logs/`. `fetch_candidates.py`
  could be extended to pull them.
- **To see the current leaderboard:** https://www.swebench.com, Verified tab.
- **To cite our data source:** the `experiments` repository plus the
  individual submission names listed in `data/submissions_catalog.csv`.

## 8. Is there room to combine our work with theirs?

Yes, in four concrete ways, and one measurement tells us where the room is.

### The measurement: TrustGate used their way

Their verifiers are used to pick the best of N candidates for a bug. We ran
our exported Verified gate the same way on the 100 test issues: for each
issue, take the candidate with the highest TrustGate probability and ask
whether it resolved the bug.

| Selection rule | Issues resolved |
|---|---|
| Pick a random candidate | 54% |
| Pick by the agreement feature alone | 64% |
| Pick TrustGate's top-scored candidate | 64% |
| Always take the best single system (live-SWE-agent, Gemini 3 Pro) | 74% |
| Oracle: any of the ten candidates works | 83% |

Three things to notice. Our model beats random by ten points, so it is a
real selector. It does not beat the agreement feature on its own, so for
selection the tree adds nothing over that one number. And it loses to the
trivial rule "trust the strongest system", which it is forbidden to use
because system identity is not a feature. The 74 to 83 gap is the headroom a
learned verifier such as SWE-Gym's is chasing; the 64 to 74 gap is what our
patch-only features cannot see.

### Four ways to combine

1. **Their selection framing, our evaluation.** Report the best-of-N
   resolve rate above alongside our AUC and gate metrics. It makes our
   numbers directly comparable to leaderboard pass@1 figures and to the
   Skywork and DeepSWE test-time-scaling rows. One cell in the notebook.

2. **Our gate as a cheap first stage in front of their verifier.** A learned
   verifier costs an LLM call per candidate. Run TrustGate first, auto-reject
   the bottom bucket, auto-approve the top, and spend verifier calls only on
   the middle. On Verified that middle is 80 percent of patches; with better
   features it shrinks. The combined system is measured with our operational
   metrics plus cost per issue.

3. **Their verifier score as our feature.** The SWE-Gym style verifier, or an
   LLM judge, produces a number per candidate; add it as a column and rerun
   the ablation. This is the ceiling experiment already on our list, and the
   selection table gives it a target: closing the gap from 64 to 74.

4. **Their trajectories as our feature source.** Every submission's agent
   trajectories are in the same S3 bucket as the patches. Steps taken, tests
   the agent ran on its own, files it opened, and any self-reported
   confidence are all available before the hidden tests run and are legal
   production features. Agentless's patch normalisation before voting is a
   direct upgrade to our agreement computation.

### Where Laya and Jev fit: System One decision models

Laya (Convai Innovations, Apache 2.0, open weights) and Jev (TypeSafe, closed,
metered API) are "System One" decision models. The name is Kahneman's: System 1
is fast, automatic judgement; System 2 is slow, step-by-step reasoning. A
chatbot that reasons in a chain of thought is System 2. These models skip the
prose: given a **state** (text, a ticket, JSON, or here an issue plus a diff)
and one or more **typed questions**, they return typed answers with calibrated
probabilities in one forward pass. Three question types exist: *choice* among
options you define, *score* on an ordinal rubric you define, and *noul*, a
yes-or-no answered with a probability.

Laya is non-autoregressive: a 421M-parameter ModernBERT encoder plus a small
decision head, about 33 ms per decision on a T4, no text generation and no
parsing. Its training method, RLCD, rewards honest probabilities with a
strictly proper scoring rule, so calibration is a design goal rather than an
afterthought. Its own card is candid about limits: zero-shot it scored 0.36
against a 0.46 majority baseline on its benchmark; fine-tuned on the target
workflow it reached 0.77; the shipped calibration is still over-confident.
Jev is the same idea behind an API at about 0.04 USD per million input tokens.

**Why this is close to TrustGate.** TrustGate is already a hand-built System
One model: sixteen numbers in, one calibrated probability out, in
microseconds, turned into approve, review or reject. Laya offers the same
contract with a learned reader in front of it:

| | TrustGate today | Laya, fine-tuned on our table |
|---|---|---|
| Input | 16 hand-built numbers | issue text plus the diff, up to about 4,000 tokens |
| Question | implicit: does it pass the tests | a noul: does this patch fully fix the issue |
| Output | calibrated probability | calibrated probability |
| Learns from | the 4,908 graded patches | the same 4,908 graded patches |
| Cost | microseconds on a CPU | tens of ms; a T4 for fine-tuning |
| Reproducible without a key | yes | yes, open weights |
| Reads the meaning of the change | no | yes, to the extent an encoder can |

The last row is the point. Our ablation concluded the ceiling is the
information in the features, and the missing piece we could not add without
an API was semantic understanding of the change. Laya is the reproducible,
key-free way to test whether semantics move the number, and it comes with the
calibration and typed-output machinery already built. It slots in as a third
judge beside GPT and Claude, and because it has never written a patch, the
contamination concern that applies to LLM judges largely disappears.

**Two risks.** The backbone was not trained mainly on code, so it may read a
diff poorly until fine-tuned. And fine-tuning needs a GPU this Mac lacks, so
that step runs on Kaggle or Colab using the published notebook, while
zero-shot scoring runs locally on the CPU.

**How we use it.** `pipeline/laya_judge.py` scores the validation and test
candidates zero-shot into the same scores format the experimentation notebook
reads, so Laya is evaluated exactly like the LLM judges: alone, stacked with
TrustGate, with bootstrap intervals and the three-way gate. Fine-tuning on our
training issues is the follow-up; see `OBSERVATIONS.md`, experiment 3.

## Related documents in this repository

- [MLReview.md](MLReview.md), algorithms used and the ranked experiments
- [METRICS.md](METRICS.md), every metric with our figures
- [PIPELINE.md](PIPELINE.md), how the candidate tables were built and the results tables
