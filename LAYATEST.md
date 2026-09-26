# What the Laya zero-shot run is doing, in plain English

A note for anyone watching `pipeline/laya_judge.py run` occupy the CPU for a
few hours and wondering whether the machine is training a model.

## It is not training anything

The process only asks Laya questions. Laya's weights never change. This is
inference, the same thing that happens when you ask a chatbot a question,
except the answer is a number instead of a sentence.

## What it does, one patch at a time

1. Takes one candidate patch and the text of the bug it tries to fix.
2. Hands both to Laya as a single document, trimmed to about 1,000 tokens,
   with one yes-or-no question: does this patch fully fix the issue?
3. Laya reads the document once and answers with a probability, for example
   0.94.
4. The process appends that number, next to the patch's id, to
   `data/llm_judge/verified_scores_laya-multilingual.jsonl` and moves to the
   next patch.

Laya is in its stock, zero-shot state. It has never seen a code patch or any
of our labels. The smoke test showed what that means: probabilities of 0.93 to
0.98 for good and bad patches alike. The full run measures exactly how much
an untrained code reader knows before any effort is spent teaching it.

## Which patches

Not the full 2,294-issue set and not the training set. It scores 1,972
patches: the validation and test candidates of the 500-issue Verified split.
Those are the only rows needed to evaluate a judge, because a judge is
measured on test and any combination with TrustGate is fitted on validation.
The 2,936 training patches are untouched; they would be scored later only for
the seventeenth-feature experiment described in `RESEARCH.md`.

## Where it runs and what it costs

On this Mac's CPU, in the dedicated `.venv-laya` environment, using several
cores. It downloaded the 1.3 GB multilingual checkpoint into the Hugging Face
cache on first use. Nothing leaves the machine. At about eight patches a
minute the run takes roughly four hours; a small GPU would do it in minutes.
If the Mac sleeps or the process is killed, rerunning the same command resumes
from the patches already written.

## What training Laya would look like, for contrast

That is the fine-tuning step in `EXPERIMENT2.md`: show Laya the 2,936
training patches with their pass/fail labels, adjust its weights over a few
epochs so its probabilities start to track our labels, then fit its
calibration on the validation patches. It needs a GPU and is planned for
Kaggle's free T4s, not this Mac. The dataset export for it already exists
under `data/llm_judge/finetune/`; the training run has not happened.

## What happens when the run finishes

The experimentation notebook's experiment 2 cells pick up the scores file
automatically and report Laya alone, Laya stacked with TrustGate, bootstrap
intervals, the three-way gate, and the per-model-family contamination check.
The outcome is recorded in `OBSERVATIONS.md` under experiment 3.

## Outcome of the run

The run finished in about 75 minutes. Laya rated the 1,972 patches with a
mean probability of 0.96 and almost no spread, good and bad alike. Alone it
scored 0.553 ROC-AUC on the test patches, barely above a coin flip; stacked
onto TrustGate it left the baseline unchanged, 0.735 against 0.737. A clean
null result: the stock checkpoint carries no usable signal about patches. It
says nothing about what a fine-tuned Laya could do, which is the next step.
Details in `OBSERVATIONS.md`, experiment 3.

## Related

- [EDUCATIONAL.md](EDUCATIONAL.md), what a System 1 decision model is
- [RESEARCH.md](RESEARCH.md), Laya as a pre-step feature and the cross-fitting rule
- [EXPERIMENT2.md](EXPERIMENT2.md), how to run and fine-tune it
