# System 1 decision models, explained, and what they have to do with TrustGate

A teaching note. It answers three questions: what "System 1" means, what an
open-source non-autoregressive System 1 decision model is, and why its value
proposition is close to what TrustGate already does.

## What "System 1" means

The term comes from Daniel Kahneman's *Thinking, Fast and Slow*. He describes
two modes of thought:

- **System 1** is fast and automatic: recognising a face, sensing that a
  sentence is off, judging in a glance that a code change looks suspicious.
- **System 2** is slow and deliberate: working through a proof, tracing an
  execution path step by step, writing out an argument.

A chatbot that reasons in a long chain of thought before answering is
behaving like System 2. TypeSafe, the company behind Jev, borrowed Kahneman's
label for a class of models that do the opposite: no reasoning text, just an
immediate, typed answer with a confidence attached. Convai Innovations released
Laya as the open-source counterpart.

## What an open-source, non-autoregressive System 1 decision model is

Take the phrase apart.

**Decision model.** Instead of generating prose, it answers a fixed question
about a piece of text. You hand it a *state*, which can be an email, a
ticket, a JSON blob, or in our case an issue plus a patch, and one or more
*typed questions*. Three question types exist:

| Type | What it asks | What comes back |
|---|---|---|
| choice | pick one of the options you define | the option and a probability for each |
| score | place the item on an ordinal rubric you define | the rubric level and its probability |
| noul | a yes-or-no question | the probability of yes |

The output is a number, never a sentence.

**Non-autoregressive.** A language model writes one token at a time, each
conditioned on the last. That is why it is slow and why its output must be
parsed and can be malformed. Laya is an encoder: a 421-million-parameter
ModernBERT that reads the whole input once and emits every answer in a single
forward pass, about 33 milliseconds on a modest GPU. There is nothing to
parse and no malformed output. Jev is the closed, API-only version of the
same idea; Laya has open weights under Apache 2.0 and a published fine-tuning
recipe that runs on Kaggle's free GPUs in about four hours.

**Trained for calibration.** The training method, RLCD, pays the model with a
strictly proper scoring rule, which is maximised only by honest
probabilities. A calibrated 0.7 should be right seven times in ten. That is
exactly the property our own notebook spends two cells and an isotonic
regression trying to obtain.

**The caveat the authors state themselves.** Zero-shot, Laya scored 0.36 on
its benchmark against a 0.46 majority baseline. Fine-tuned on the target
workflow it reached 0.77. It is a specialist that learns your decision, not a
general oracle, and its shipped calibration is admittedly still
over-confident. Expect little from it until it has seen our labels.

## Why this maps onto TrustGate almost one to one

TrustGate already *is* a System 1 decision model, built by hand: sixteen
numbers in, one calibrated probability out, in microseconds, turned into
approve, review or reject. Laya offers the same contract with a learned
reader in front of it.

| | TrustGate today | Laya, fine-tuned on our table |
|---|---|---|
| Input | 16 hand-built numbers about the patch | the issue text plus the diff, up to about 4,000 tokens |
| Question | implicit: does it pass the tests | a noul: does this patch fully fix the issue |
| Output | calibrated probability | calibrated probability |
| Learns from | 4,908 graded patches | the same 4,908 graded patches |
| Cost | microseconds on a CPU | tens of milliseconds; a T4 to fine-tune |
| Reproducible without an API key | yes | yes, open weights |
| Reads the meaning of the change | no | yes, to the extent an encoder can |

The last row is the whole point. Our ablation concluded that the ceiling is
the information in the features, and the piece we could not add without an
API was semantic understanding of the change. Laya is the reproducible,
key-free way to test whether semantics move the number, with the calibration
and typed-output machinery already built. It slots in as a third judge beside
GPT and Claude, and because it has never written a patch, the contamination
concern that applies to LLM judges largely disappears.

## Two risks to state plainly

1. Laya's backbone was not trained mainly on code, so it may read a diff
   poorly until it is fine-tuned on our examples.
2. Fine-tuning needs a GPU this Mac does not have, so that step runs on
   Kaggle or Colab with the published notebook. Zero-shot scoring runs here on
   the CPU in its own environment, because the PyTorch build for Intel macOS
   clashes with the main environment's NumPy. It is slow on a CPU: about 30
   seconds per candidate when reading 4,096 tokens, a few seconds at 1,024, so
   the default reads 1,024 tokens and the 1,972 candidates take a few hours.

## How it is wired into the project

- `./setup_and_run.sh --laya` creates `.venv-laya`.
- `.venv-laya/bin/python pipeline/laya_judge.py run` scores the validation and
  test candidates zero-shot into `data/llm_judge/<split>_scores_laya-<checkpoint>.jsonl`.
- `TrustGateExperimentation.ipynb`, experiment 2, evaluates every judge scores
  file it finds: alone, stacked with TrustGate, with bootstrap intervals, the
  three-way gate, and the per-model-family contamination check.
- The follow-up, fine-tuning on our 300 training issues, uses Laya's Kaggle
  notebook with our labelled table as the dataset.

## Related

- [SWEBench_TrustGate.md](SWEBench_TrustGate.md), section 8, how Laya and Jev fit the comparison with verifier research
- [MLReview.md](MLReview.md), where System One models sit in the algorithm landscape
- [OBSERVATIONS.md](OBSERVATIONS.md), experiment 3, where the results will be recorded
