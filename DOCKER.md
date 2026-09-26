# Docker: when it is needed and how to use it

Docker is **not** required for the default project. Every step in
`run_pipeline.sh`, the static checks, the notebook and the scorer runs without
it. The labels come from grading reports that the SWE-bench maintainers
already produced in Docker and published, so the pipeline downloads results
instead of recomputing them.

Docker is needed for exactly one optional script: `pipeline/run_harness.sh`,
which regrades patches with the official SWE-bench harness.

## When you would run it

- To verify the public grades independently rather than trust them.
- To label patches you generated yourself, with your own agent, so they can
  join the candidate table.
- To audit a single disagreement between a report and what you expect.

If none of these apply, skip this document.

## What the harness does

For each issue it pulls or builds a Docker image containing the repository at
the issue's base commit with its dependencies installed, applies the candidate
patch inside a container, runs the issue's tests, and writes a `report.json`
in the same format as the public ones under
`logs/run_evaluation/<run_id>/<model>/<instance_id>/`.

## Requirements

| | Recommended by SWE-bench | This Mac |
|---|---|---|
| RAM | 16 GB or more | 8 GB |
| Free disk | about 120 GB for a full run | 82 GB |
| Docker | running | Docker Desktop 29 installed |
| Python for the `swebench` package | 3.10 or newer | 3.11 in `.venv` |

This machine is under the recommendations, so keep the parallelism at 1 or 2
and limit the scope with `--instances` or `--only`, or offload to Modal with
`--modal`.

## Commands

The script installs the `swebench` package into `.venv` on first use and
checks that Docker is running.

**Sanity check the environment first.** This grades one issue's reference
patch, which must come back resolved:

```bash
./pipeline/run_harness.sh --gold -i django__django-11099
```

**Regrade a small subset:**

```bash
./pipeline/run_harness.sh --only 20250522_tools_claude-4-sonnet --instances "django__django-11099 sympy__sympy-20590" -j 1
```

**Regrade everything in `data/predictions/`, slowly:**

```bash
./pipeline/run_harness.sh -j 2 -t 1800
```

Each prediction file holds one candidate per issue, because the harness keys
predictions by issue id. The script runs one harness invocation per file with
run id `trustgate-<submission>`.

**Run on Modal instead of local Docker:**

```bash
./pipeline/run_harness.sh --modal
```

Requires a Modal account and the `modal` CLI logged in. The harness then
builds and runs containers in Modal's cloud, so local RAM and disk do not
matter.

## Feeding results back into the table

```bash
.venv/bin/python pipeline/build_candidate_table.py --local-reports logs/run_evaluation
```

Local reports override the public ones for the candidates they cover. Rerun
the notebook from section 8 afterwards.

## Grading your own patches

1. Write a predictions file with one JSON object per line:
   `{"instance_id": "...", "model_patch": "diff --git ...", "model_name_or_path": "my-agent"}`
   and save it under `data/predictions/`.
2. Run `./pipeline/run_harness.sh --only my-agent`.
3. Add the same patches to `data/candidates_raw.jsonl` as rows with
   `submission: "my-agent"` and `report: null`, then rebuild the table with
   `--local-reports`. The local reports fill in the grades.

## Disk and cleanup

Images are cached per environment by default and can reach 100 GB for a full
run. Limit scope, and remove the images when done:

```bash
./cleanup.sh --docker          # removes SWE-bench containers and images
docker system df               # see what Docker is holding
```

## Related documents

- [LOCAL.md](LOCAL.md), everything that runs without Docker
- [PIPELINE.md](PIPELINE.md), step 4 describes the regrade in the pipeline's order
