# Running on Google Colab

Colab does not need any data from your machine or from GitHub. It fetches
everything itself. The only prerequisites are internet access and the
repository at [github.com/hatemphd/MLE_POC](https://github.com/hatemphd/MLE_POC).

## Open the notebook

Click the **Open in Colab** badge at the top of the notebook, or open
[this link](https://colab.research.google.com/github/hatemphd/MLE_POC/blob/main/TrustGate_SWEBench_PoC_ML_v3.ipynb).
Then choose **Runtime > Run all**.

## What happens on Colab, in order

1. **The pip cell** installs the libraries the notebook needs.
2. **The bootstrap cell**, directly below the pip cell, detects that it is
   running on Colab and clones `hatemphd/MLE_POC` into `/content/trustgate`.
   The repository contains code and docs only. On later runs in the same
   session it pulls new commits instead of cloning.
3. **The same cell runs three pipeline steps** inside Colab:
   `select_issues.py`, `fetch_candidates.py` and `build_candidate_table.py`.
   They download the 500 SWE-bench Verified issues from Hugging Face and
   about 5,000 candidate patches plus their official grading reports from the
   public S3 bucket, then write `data/trustgate_candidate_results.csv` in
   Colab's own filesystem. About five minutes.
4. **The imports cell** downloads the SWE-bench issues again from Hugging Face
   for the benchmark EDA. Same source; Colab caches it after the first call.
5. **From section 8 onward** the notebook reads the CSV the bootstrap cell
   just built, and every modeling cell runs.

The `data/` folder is deliberately ignored by git because Colab rebuilds it.

## What Colab will not have unless you run it there

**Code-health features.** The bootstrap cell runs only the fast steps, so
`syntax_ok`, `compile_ok` and the lint counts are empty and the third feature
set in the ablation (section 19.2) equals the second. To fill them, add this
line to the bootstrap cell before `build_candidate_table.py`:

```python
get_ipython().system("python pipeline/static_checks.py --workers 4")
```

and change the build line to
`python pipeline/build_candidate_table.py --static data/static_features.csv`.
Expect about 45 minutes and roughly 1 GB of repository clones in the session.

**The full 2,294-issue split.** Colab runs the Verified split by default. To
run the full set, add a cell above the bootstrap cell containing

```python
import os
os.environ["TRUSTGATE_SPLIT"] = "full"
```

The download takes roughly 25 minutes and the static checks over two hours,
so the full split is better suited to a local machine.

## Colab sessions are temporary

Everything under `/content/` is deleted when the runtime disconnects,
typically after about 90 minutes idle or 12 hours total. Rerunning the
bootstrap cell rebuilds it in five minutes; nothing is lost because nothing
was unique to the session.

To keep the table between sessions, mount Google Drive and point the notebook
at a copy there. The bootstrap cell has these two lines commented out:

```python
from google.colab import drive; drive.mount("/content/drive")
os.environ["TRUSTGATE_CANDIDATES"] = "/content/drive/MyDrive/trustgate_candidate_results.csv"
```

Copy `data/trustgate_candidate_results.csv` to that Drive path once, then use
those lines instead of the pipeline steps on later runs.

## If the bootstrap cell reports missing pipeline files

The cell checks that `pipeline/select_issues.py`, `fetch_candidates.py`,
`build_candidate_table.py` and `common.py` exist after cloning. If it prints
that they are missing, the repository on GitHub does not yet contain the
`pipeline/` folder. Push the full project from your machine, then in Colab run

```python
!rm -rf /content/trustgate
```

and rerun the bootstrap cell.

## Scoring a patch on Colab

After **Run all**, cell 19.8 has written `models/trustgate_gate_verified.joblib`
inside `/content/trustgate`. In a new cell:

```python
!python pipeline/score_patch.py --patch path/to/fix.diff --issue path/to/issue.txt
```

## Related documents

- [GETTING_STARTED.md](GETTING_STARTED.md), the local walkthrough
- [PIPELINE.md](PIPELINE.md), what every pipeline step executes
- [PIPELINE_EXPLAINED.md](PIPELINE_EXPLAINED.md), the plain-English version
