# Git guide for this project

How the repository is organised, what to commit, when to bump the version, and
how to cut a release. Repository: [github.com/hatemphd/MLE_POC](https://github.com/hatemphd/MLE_POC).

## Two folders on this Mac

| Folder | Role |
|---|---|
| `/Users/hatem/MLE` | Working folder where the code, notebook and docs are edited and run. Not a git checkout. |
| `/Users/hatem/MLE_POC` | The git checkout that tracks GitHub. |

Changes flow from `MLE` to `MLE_POC` with rsync, then get committed there:

```bash
rsync -av --exclude '.venv' --exclude 'data' --exclude '.ipynb_checkpoints' --exclude '.claude' --exclude '__pycache__' --exclude 'note.txt' --exclude '.git' /Users/hatem/MLE/ /Users/hatem/MLE_POC/
```

The simpler long-term arrangement is one folder: move `MLE_POC/.git` into `MLE`
and delete `MLE_POC`. Until then, always rsync before committing so the two do
not drift.

## One-time setup per clone

```bash
git clone https://github.com/hatemphd/MLE_POC.git trustgate && cd trustgate
git config core.hooksPath .githooks        # enables the notebook version stamp
./setup_and_run.sh --no-run                # also sets hooksPath when inside a checkout
```

## What is tracked and what is not

**Tracked:** the notebook, `pipeline/`, the shell scripts, all `.md` files, the
two decks, `VERSION`, `.githooks/`, `.gitignore`, and `models/` (two bundles of
about 3 MB each so the scorer works on a fresh clone).

**Never tracked**, enforced by `.gitignore`:

- `.venv/` and `__pycache__/`: rebuilt by `setup_and_run.sh`
- `data/` in all its forms: 7.7 GB, fully reproducible by `run_pipeline.sh`,
  and several files exceed GitHub's 100 MB limit
- `logs/` from the Docker regrade
- `.ipynb_checkpoints/`, `.claude/`, `.DS_Store`
- Office lock files `~$*.pptx` and editor backups `*~`

**Never commit credentials.** `GITHUB_TOKEN` and `HF_TOKEN` are read from the
environment, never from a file in the repository.

Large artefacts you want to share go on a GitHub Release, not in the tree:

```bash
gh release create v1.0 data/trustgate_candidate_results.csv --title "TrustGate 1.0" --notes "Verified-split candidate table from the reference run"
```

## Everyday workflow

1. Edit and run in `MLE`. Execute the notebook end to end before committing
   anything that touches it.
2. rsync to `MLE_POC`.
3. `git status` and read the list. Anything under `data/` or a `~$` file means
   the ignore rules were bypassed; stop and check.
4. `git add -A && git commit -m "<message>"`. The pre-commit hook stamps the
   notebook with `VERSION`, today's date and the branch, and stages it.
5. `git push`.

### Commit messages

One line, imperative, saying what changed and why if it is not obvious:

```text
Add cross-validated threshold selection (cell 19.7)
Balance default submissions across model families
Fix Colab bootstrap when pipeline/ is missing from the clone
```

Group related changes into one commit. Do not mix a data-pipeline change with
a documentation rewrite unless one required the other.

### Branches

`main` is always runnable: `./run_pipeline.sh` and Run All must succeed from a
fresh clone of `main`. For anything that takes more than a sitting, or that
might break the notebook, use a branch and merge when it is green:

```bash
git checkout -b feature/agreement-clustering
# ... commits ...
git checkout main && git merge --no-ff feature/agreement-clustering && git push
```

The version stamp records the branch, so a notebook opened from a feature
branch says so in its first cell.

## Versioning

The version is Major.Minor in the `VERSION` file. The hook writes it, with the
release date and branch, into the notebook on every commit. The date is
automatic; the number is a human decision.

**Bump Minor** (1.0 to 1.1) when the results or the interface change but a
reader of the previous version is not misled:

- a new notebook section or experiment
- a new pipeline script or flag
- a rebuilt candidate table with different default submissions
- retrained model bundles

**Bump Major** (1.x to 2.0) when earlier numbers or files stop being
comparable:

- the label definition changes, for example from benchmark tests to
  production merge outcomes
- the `CANDIDATE_COLUMNS` schema changes
- the benchmark split or dataset changes in a way that invalidates the results tables
- a leakage fix that changes previously reported results

**Do not bump** for documentation, typo fixes, comments, or refactors that
leave outputs identical. The date still updates, which is enough.

Bump by editing `VERSION` in the same commit as the change that justifies it:

```bash
echo "1.1" > VERSION
git add -A && git commit -m "Add agreement clustering feature; bump to 1.1"
```

## Cutting a release

A release is a tagged commit on `main` whose notebook has been executed end to
end, with the results tables in `PIPELINE.md` and the decks matching it.

```bash
# 1. on main, everything committed, notebook executed and verified
echo "1.1" > VERSION
git add -A && git commit -m "Release 1.1"
git tag -a v1.1 -m "TrustGate 1.1: <one line on what changed>"
git push && git push --tags

# 2. attach the artefacts a reader needs without running the pipeline
gh release create v1.1 data/trustgate_candidate_results.csv models/trustgate_gate_verified.joblib --title "TrustGate 1.1" --notes-file RELEASE_NOTES.md
```

Keep a short `RELEASE_NOTES.md` or write the notes inline: what changed, the
headline numbers, anything a user must do differently.

## Notebook outputs

Commit the notebook **with outputs** at release tags, so a grader or reader
sees the tables and figures on GitHub without running anything. Between
releases, either is fine, but be aware that outputs make diffs large. To strip
them before an ordinary commit:

```bash
.venv/bin/jupyter nbconvert --clear-output --inplace TrustGate_SWEBench_PoC_ML_v3.ipynb
```

## Troubleshooting

**The stamp did not update.** The hook is not enabled in this clone. Run
`git config core.hooksPath .githooks` and commit again, or stamp by hand with
`python pipeline/stamp_notebook.py`.

**Push rejected as non-fast-forward.** Someone or something committed to
GitHub since your last pull. `git pull --rebase` then `git push`. Never force
push to `main`.

**A `~$...pptx` file shows up in `git status`.** PowerPoint has the deck open.
It is ignored by `.gitignore`; if it still shows, it was added before the rule
existed: `git rm --cached '~$TrustGate_Notebook_and_Pipeline.pptx'`.

**Accidentally staged `data/`.** `git reset data/` before committing. If it was
already committed, `git rm -r --cached data/ && git commit -m "Remove data from tracking"`;
history will still contain it, so if the files were large, rewrite history
before pushing or ask for help.

**Colab cannot find `pipeline/`.** The push did not include it. `git status`
in the checkout, add it, push, then `!rm -rf /content/trustgate` on Colab.

## Related documents

- [GETTING_STARTED.md](GETTING_STARTED.md), first-time walkthrough
- [LOCAL.md](LOCAL.md), what each step does and where files live
- [COLAB.md](COLAB.md), running in the browser
