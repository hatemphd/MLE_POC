# setup_and_run.sh

`setup_and_run.sh` builds an isolated Python environment for the TrustGate
notebook using [uv](https://docs.astral.sh/uv/) and then opens the notebook in
Jupyter. It is safe to rerun, since it reuses whatever already exists.

## Usage

```bash
./setup_and_run.sh            # set up the environment and open Jupyter
./setup_and_run.sh --no-run   # set up the environment only
./setup_and_run.sh --harness  # also install the SWE-bench evaluation harness
```

Flags can be combined, for example `./setup_and_run.sh --harness --no-run`.

## Step by step

1. **Parses flags.** `--no-run` stops after setup instead of launching
   Jupyter. `--harness` adds the SWE-bench grading tool. Any other argument
   exits with an error.

2. **Locates itself.** It resolves the folder the script lives in and works
   from there, so it runs correctly no matter which directory you call it from.

3. **Installs uv if missing.** It checks for the `uv` command. If absent, it
   downloads the official installer over HTTPS and adds `~/.local/bin` to the
   PATH for the rest of the run. It then prints the uv version.

4. **Creates `.venv` with Python 3.11.** If the folder does not exist, uv
   creates a virtual environment and downloads Python 3.11 if that version is
   not on the machine. If `.venv` already exists, it is reused. The system
   Python 3.9 is deliberately avoided because current `datasets` and
   `matplotlib` releases need something newer.

5. **Installs the packages.** It installs `jupyter`, `datasets`,
   `scikit-learn`, `pandas`, `numpy`, and `matplotlib` into the venv, plus
   `pyarrow`, `pyyaml`, `requests` and `pyflakes` for the pipeline scripts. It also
   installs `pip` itself. uv environments normally ship without pip, and the
   notebook's first cell runs `!pip install`, so this keeps that cell from
   failing without you having to edit the notebook.

6. **Optionally installs the harness.** With `--harness`, it adds the
   `swebench` package and warns if Docker is not installed, since the harness
   cannot grade patches without it.

7. **Verifies the install.** It runs a short Python snippet inside the venv
   that imports every library and prints the Python and package versions. If
   any import fails, the script stops here.

8. **Launches Jupyter.** Unless `--no-run` was given, it `exec`s the venv's
   own `jupyter notebook` with the TrustGate notebook as the argument. Using
   `exec` replaces the shell process with Jupyter, so Ctrl-C shuts the server
   down cleanly. With `--no-run`, it instead prints the
   `source .venv/bin/activate` command for manual use.

## Working on a different benchmark split

The script passes environment variables through to Jupyter, so
`TRUSTGATE_SPLIT=full ./setup_and_run.sh` opens the notebook on the full
2,294-issue table under `data/full/`, built with `./run_pipeline.sh --split full`.

## Safety settings

The script starts with `set -euo pipefail`, which means it aborts on the first
failed command, on any reference to an unset variable, and on a failure
anywhere in a pipeline. That prevents it from launching Jupyter against a
half-installed environment.

## What it creates

| Path | Description |
|---|---|
| `.venv/` | The uv-managed virtual environment with Python 3.11 and all packages |
| `~/.local/bin/uv` | The uv binary, only if uv was not already installed |

Both are removed by `./cleanup.sh` (the venv) or by uv's own uninstall
instructions (the binary). Nothing else on the system is modified.

## Related files

- `README.md` for the full project overview and how to produce candidate labels
- `cleanup.sh` for removing the environment and caches
