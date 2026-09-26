# Experiment 2 runbook: the LLM judge as a ceiling

One-off measurement. A foundation model reads each bug report and candidate
patch and estimates the probability the patch works, before any test result is
known. The score is evaluated like any other feature. This answers whether the
TrustGate ceiling of about 0.73 to 0.74 ROC-AUC is a limit of our patch-only
features (the judge lifts it well past 0.80) or of the label itself (it does
not).

## What you need

- The project set up: `./setup_and_run.sh --no-run` and `./run_pipeline.sh --static` done once.
- An API key for one provider, exported in the terminal you run from:
  - OpenAI: `export OPENAI_API_KEY=...`
  - Anthropic: `export ANTHROPIC_API_KEY=...`
- About an hour of wall-clock time for the batch to complete. You do not need to stay.

Never paste a key into a file in the repository or into a chat. The scripts
read it from the environment only.

## The one-command path

```bash
cd /Users/hatem/MLE
export OPENAI_API_KEY=...
./pipeline/run_experiment2.sh --provider openai --model gpt-5
```

What happens, in order:

1. Checks the key is present; exits with a clear message if not.
2. Prints the token estimate for the 1,972 validation and test candidates.
   For an Anthropic model it also prints dollars. For an OpenAI model add
   `--price-in` and `--price-out` (USD per million tokens, from the pricing
   page) to see dollars; batch pricing is half the standard rate.
3. Asks you to confirm before anything is submitted. Add `--yes` to skip.
4. Uploads one batch, polls every minute until it ends, writes
   `data/llm_judge/verified_scores.jsonl`. Scores are cached, so rerunning
   never resubmits patches that already have a score.
5. Re-executes `TrustGateExperimentation.ipynb` headlessly, saves the executed
   copy to `docs/TrustGateExperimentation_executed.ipynb`, and prints the
   experiment 2 tables and verdict.

For an Anthropic judge instead: `./pipeline/run_experiment2.sh --provider anthropic --model claude-opus-5`.
For the full 2,294-issue split: prefix with `TRUSTGATE_SPLIT=full` (about 8,800
candidates, roughly 4.5 times the cost).

## The step-by-step path

If you prefer to control each stage:

```bash
.venv/bin/python pipeline/llm_judge.py estimate --provider openai --model gpt-5
.venv/bin/python pipeline/llm_judge.py submit   --provider openai --model gpt-5
.venv/bin/python pipeline/llm_judge.py status   --provider openai      # any time
.venv/bin/python pipeline/llm_judge.py collect  --provider openai      # waits, or --no-wait to check and return
```

Then open `TrustGateExperimentation.ipynb` and run from the cell "Experiment
2a" onward.

## What the notebook reports

- **Judge alone**: ROC-AUC on the 986 test patches with a bootstrap interval, the
  three-way gate at thresholds chosen on validation, and the best-of-N
  selection rate.
- **TrustGate + judge**: a two-input logistic regression fitted on validation
  only, evaluated on test. This is the number the decision rule uses.
- **Contamination check**: judge AUC broken down by the model family that wrote
  each candidate. If the judge is much better on candidates from its own family
  (GPT-written candidates for a GPT judge), discount the result.

## The decision rule

| Stack AUC on test | Conclusion | Consequence |
|---|---|---|
| 0.80 or above | The shortfall was information our patch-only design excluded; a semantic reader recovers it | Semantic signal is worth pursuing: code embeddings first for reproducibility, the judge as a paid option |
| Below 0.80 | Even a foundation model reading the code cannot predict the label well | The label is not predictable before the tests run; keep TrustGate as a prioritiser, and approval needs execution or production labels |

Record the outcome in `OBSERVATIONS.md` under experiment 2 and in the results
deck. A null result is as valuable as a positive one.

## Why an OpenAI judge is a reasonable first choice

Two of the ten systems that wrote our candidates used GPT models; eight did not.
A judge that has not seen most of the candidates' authors has less room to
recognise its own style, so the contamination check is likelier to come back
clean. Running a second judge from another provider afterwards, and comparing
the per-family tables, is the natural follow-up.

## Files involved

| Path | Role |
|---|---|
| `pipeline/llm_judge.py` | Prompt, schema, cost estimate, batch submit and collect for both providers |
| `pipeline/run_experiment2.sh` | The one-command wrapper |
| `data/llm_judge/<split>_batches.json` | Batch ids, so a run can be resumed |
| `data/llm_judge/<split>_scores.jsonl` | One line per candidate: probability, one-line reason, status |
| `TrustGateExperimentation.ipynb` | Cells 2a and 2b evaluate the scores |
| `docs/experiments_<split>.json` | Machine-readable results for the write-up |
