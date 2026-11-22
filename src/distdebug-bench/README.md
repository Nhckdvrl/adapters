## DistDebug-Bench → Harbor Adapter

## Overview

This adapter converts [DistDebug-Bench](https://github.com/OrderLab/distdebug-bench) into Harbor tasks.
Each task is one real failure from the issue tracker of a distributed system. The agent gets the bug report
(title, description, attached logs and stack traces) and the system's source at the pre-fix commit, and it
must write a `diagnosis.json` that lists the code blocks that caused the failure. It does not write a fix.
The diagnosis is scored against human-labeled root-cause blocks by the unmodified upstream scorer.

- **Size.** 34 tasks: the official **DistDebug-Bench Lite** subset (`benchmark/lite.txt`), covering
  11 systems (Elasticsearch, etcd, HBase, HDFS, Ignite, Ignite 3, Kafka, Kubernetes, Ray, TiKV, ZooKeeper)
  in Java, Go, Python/C++ and Rust. One task per Lite bug, no exclusions.
  `--split full` generates all 120 bugs of the full benchmark, but only Lite has been validated so far.
- **Source.** Benchmark v1.1 labels, upstream commit
  [`c3e929b`](https://github.com/OrderLab/distdebug-bench/tree/c3e929b9ee0082345337358e352ae37fc472df4c).
- **Reward.** `reward` = `block_coverage`, the paper's main metric. All other upstream metrics are also
  reported in `reward.json`.
- **Main adaptation.** Upstream runs each agent in a bubblewrap sandbox on the host. Here the same
  workspace is built as a container image, the agent phase uses Harbor's network allowlist, and scoring
  runs in a separate verifier container. The prompt, the files the agent sees, the output schema and the
  scorer are unchanged (see [Notes & Caveats](#notes--caveats)).

## What is DistDebug-Bench?

DistDebug-Bench ([paper](https://distdebug.com/assets/paper.pdf), NeurIPS 2026 Evaluations & Datasets,
[website](https://distdebug.com), [dataset](https://huggingface.co/datasets/OrderLab/distdebug-bench)) asks whether LLM agents
can diagnose real bugs in distributed systems. These bugs involve timing, message ordering and partial
failures, and they rarely come with a failing test. The benchmark has 120 bugs from 11 systems. Each bug
has human-labeled root-cause code blocks (`blocks.json`). A diagnosis is scored at four levels
(file, function, line, block) for precision and coverage, plus `strict_block_coverage` and
`mention_coverage`. `block_coverage` (labeled blocks hit by a predicted block in the same file, within a
5-line tolerance) is the headline metric. Upstream ships Mini-SWE-Agent, Codex CLI and OpenCode harnesses,
a leakage checker, and 6,120 scored agent traces.

## Adapter Features

- **Same task text.** `instruction.md` is byte-identical to the prompt upstream gives its Codex CLI and
  OpenCode harnesses (`distdebug_bench.harnesses.cli.cli_prompt`): the Mini-SWE-Agent instructions, the
  issue title and description, and the attachment list. `scripts/check_prompt_equivalence.py` checks
  this for all 34 tasks, including the staged attachments.
- **Same workspace.** `environment/build_snapshot.sh` re-implements upstream
  `repos._checkout_pruned_revision`. It fetches the pinned commit with all of its ancestors (agents do use
  `git log`/`git show`), checks it out detached, and deletes every ref, `FETCH_HEAD`/`ORIG_HEAD` and the
  reflog, so later commits, including the fix, cannot be reached. Upstream `branch` values (tags, full or
  abbreviated SHAs) are pinned to full SHAs in `snapshots.json`, and the build fails if `HEAD` differs.
  `.validate_diagnosis.py` and the issue attachments (`.artifacts/`) are staged exactly as in
  `distdebug_bench.agent.stage_workspace`.
- **Unmodified scorer, isolated from the agent.** `tests/` copies the upstream package
  (`distdebug_bench/*.py`, verified against pinned SHA-256 hashes at generation time) and only this bug's
  `report.json`/`blocks.json`. `tests/score_diagnosis.py` calls upstream `distdebug_bench.score.score_run`,
  the function behind `python -m distdebug_bench.score`. The verifier runs in a **separate container**
  (`[verifier] environment_mode = "separate"`) with no network (`network_mode = "no-network"`; scoring is
  pure stdlib). Only `/workspace/diagnosis.json` is passed to it (`artifacts`), so labels, fix links and
  the scorer never enter the agent's image.
- **Multi-metric reward.** `reward.json` contains `reward` (= `block_coverage`), `valid_diagnosis`, and
  `block_coverage`, `strict_block_coverage`, `block_precision`, `file_coverage`, `file_precision`,
  `function_coverage`, `function_precision`, `line_coverage`, `line_precision`, `mention_coverage`.
  `diagnosis_scores.json` (the upstream per-run record) and `scoring_details.json` are kept in the verifier logs.
- **Network isolation.** Upstream runs agent commands with no network. Here the agent phase uses
  `network_mode = "allowlist"`, limited to LLM API hosts (configurable with `--allowed-hosts`, or per run
  with Harbor's `extra_allowed_hosts`). The issue trackers, GitHub and the benchmark's own site are not
  reachable.
- **Oracle.** `solution/solve.sh` writes the labeled blocks as a schema-valid diagnosis. It scores
  `reward = 1.0` on all 34 tasks. All metrics are 1.0 except `strict_block_coverage` = 0.5 on
  `ray-25699`, because one of its labeled blocks has an empty line range (`start_line == end_line`). That
  is the upstream scorer's definition, not an adapter issue.
- **Parity tooling.** `configs/harbor_mini_swe_agent.yaml` makes Harbor's built-in `mini-swe-agent`
  render the exact upstream Mini-SWE-Agent system and instance messages from `instruction.md`
  (`scripts/check_mini_prompt.py` checks this byte for byte for every task).
  `scripts/harbor_job_to_distdebug.py` converts a Harbor job into the upstream results layout, so upstream
  `score.py` and `leakage.py` run unchanged on Harbor results. `scripts/parity_compare.py` rescores both
  sides with the same `score_run` and reports mean ± SEM, range overlap and per-bug MSE.
- No custom agents are added. Any Harbor agent can run the tasks with `instruction.md`.

## Generated Task Structure

```
distdebug-bench/
├── zookeeper-2845/
│   ├── task.toml                  # name, authors, metadata, allowlist, separate offline verifier, artifacts
│   ├── instruction.md             # upstream CLI-harness prompt (issue + output schema + workflow)
│   ├── environment/               # agent image
│   │   ├── Dockerfile             # ubuntu:24.04 + git/python3/ripgrep; pruned snapshot at /workspace
│   │   ├── build_snapshot.sh      # pinned commit + ancestors, no refs/remotes/reflog
│   │   ├── validate_diagnosis.py  # -> /workspace/.validate_diagnosis.py (upstream, verbatim)
│   │   └── artifacts/             # -> /workspace/.artifacts/ (only for bugs with attachments)
│   ├── solution/
│   │   └── solve.sh               # oracle: labeled blocks as diagnosis.json
│   └── tests/                     # verifier image (separate container)
│       ├── Dockerfile             # python:3.12-slim + COPY . /tests/
│       ├── test.sh                # runs score_diagnosis.py, guarantees a reward.json
│       ├── score_diagnosis.py     # upstream score_run -> reward.json
│       ├── distdebug_bench/       # upstream scorer package, verbatim
│       ├── benchmark/             # systems.json + this bug's report.json / blocks.json
│       ├── bug_id.txt
│       └── upstream_manifest.json # source commit + SHA-256 of the copied scorer files
```

Adapter code:

```
src/distdebug-bench/
├── README.md, adapter_metadata.json, parity_experiment.json, pyproject.toml, uv.lock
├── run_distdebug-bench.yaml            # oracle (default) / agents
├── run_distdebug-bench_parity.yaml     # Harbor side of the parity runs
├── configs/
│   ├── harbor_mini_swe_agent.yaml      # upstream Mini-SWE-Agent prompt for Harbor's mini-swe-agent
│   └── original/mini-swe-agent-step-5-preview.yaml  # original-side model config
├── scripts/                            # resolve_snapshots, check_mini_prompt, harbor_job_to_distdebug, parity_compare
├── tests/test_adapter.py
└── src/distdebug_bench/
    ├── adapter.py, main.py
    ├── snapshots.json                  # pinned commits for all 120 bugs
    ├── parity_subset.txt               # 12-bug parity split
    └── task-template/
```

## Run Evaluation / Harness

### Running with Datasets Registry

After the dataset is published:

```bash
# Oracle
harbor run -d orderlab/distdebug-bench
# An agent
harbor run -d orderlab/distdebug-bench -a <agent> -m "<model>"
```

### Using Job Configurations

From the adapters repository root, after generating the tasks (see [Usage](#usage-create-task-directories)):

```bash
# Oracle on all 34 tasks (expected mean reward 1.0)
harbor run -c src/distdebug-bench/run_distdebug-bench.yaml

# Any agent on the locally generated dataset
harbor run -p datasets/distdebug-bench -a codex -m "openai/gpt-5-mini"

# Mini-SWE-Agent with the exact upstream prompt
harbor run -p datasets/distdebug-bench -a mini-swe-agent -m "<model>" \
  --ak version=2.2.8 --ak config_file=src/distdebug-bench/configs/harbor_mini_swe_agent.yaml \
  --ak 'session_id_headers=[]'
```

Keep `session_id_headers=[]` for `mini-swe-agent`: without it the trial name, which contains the bug id,
ends up in an agent-readable log (see Notes & Caveats). For any agent, run the upstream leakage check on
the converted traces.

If your model endpoint is not in the default allowlist, add it for the run (`extra_allowed_hosts` in the
agent section of a job config) or regenerate with `--allowed-hosts`.

### Running Individual Trial

```bash
harbor trial start -p datasets/distdebug-bench/zookeeper-2845                         # oracle
harbor trial start -p datasets/distdebug-bench/zookeeper-2845 -a <agent> -m "<model>"
```

### Reading results

Harbor averages each key of `reward.json` over trials. `reward` is the mean `block_coverage`. Upstream
aggregates the same way (attempts averaged within a bug, then bugs averaged equally). To apply upstream
tooling directly:

```bash
python scripts/harbor_job_to_distdebug.py jobs/<job> results/<name>
cd /path/to/distdebug-bench   # commit c3e929b
python -m distdebug_bench.score  /abs/path/results/<name> --subset lite --attempts 1
python -m distdebug_bench.leakage /abs/path/results/<name>
```

## Usage: Create Task Directories

```bash
cd src/distdebug-bench
uv sync
uv run distdebug-bench --output-dir ../../datasets/distdebug-bench                        # Lite (34)
uv run distdebug-bench --split parity --output-dir ../../datasets/distdebug-bench-parity  # parity subset (12)
uv run distdebug-bench --task-ids zookeeper-2845 --overwrite
```

Flags:
- `--output-dir`, `--limit`, `--overwrite`, `--task-ids`: standard adapter flags.
- `--split {lite,full,parity}`: `lite` is the default. `full` (120 bugs) is not validated yet.
- `--source-dir`: an existing checkout of `OrderLab/distdebug-bench`. By default the pinned commit is
  cloned into `~/.cache/harbor-distdebug-bench/` (about 16 MB). Generation fails if the upstream scorer
  files differ from the pinned hashes (`--allow-unpinned-source` overrides this).
- `--agent-network {allowlist,public,no-network}` (default `allowlist`), `--allowed-hosts ...`,
  `--agent-timeout-sec` (default 3600, the upstream CLI-harness timeout).

Generation needs only `git` and network access to GitHub. Source snapshots are fetched when the task
images are built, not at generation time.

## Comparison with Original Benchmark (Parity)

**Status: matched.** 3 runs per side on the 12-bug parity split; all values are % (mean over the 12
bugs), reported as mean ± sample SEM over runs.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| mini-swe-agent@2.2.8 | step-5-preview | block_coverage | 3 | 12 of 34 (35%) | 60.19 ± 5.44 | 58.52 ± 2.48 |
| mini-swe-agent@2.2.8 | step-5-preview | file_coverage | 3 | 12 of 34 (35%) | 80.56 ± 7.22 | 75.46 ± 4.04 |

Links: original benchmark [OrderLab/distdebug-bench@c3e929b](https://github.com/OrderLab/distdebug-bench/tree/c3e929b9ee0082345337358e352ae37fc472df4c)
(original side run unmodified, plus `configs/original/mini-swe-agent-step-5-preview.yaml`; no fork needed) ·
adapter PR [harbor-index/adapters#32](https://github.com/harbor-index/adapters/pull/32) ·
dataset PR [harbor-framework/harbor-datasets#288](https://github.com/harbor-framework/harbor-datasets/pull/288) ·
parity artifacts: [harborframework/parity-experiments#294](https://huggingface.co/datasets/harborframework/parity-experiments/discussions/294)
(that repo is over the Hub's 1M-file limit, so the files are mirrored at
[Nhckdvrl/distdebug-bench-parity-experiments](https://huggingface.co/datasets/Nhckdvrl/distdebug-bench-parity-experiments)).

Per-run scores (block_coverage): original 49.31 / 65.97 / 65.28, Harbor 53.75 / 62.08 / 59.72.
Per-run scores (file_coverage): original 68.06 / 80.56 / 93.06, Harbor 76.39 / 81.94 / 68.06.

The run-score ranges overlap for every upstream metric, not only the two above:

| Metric | Original | Harbor |
|---|---|---|
| function_coverage | 45.83 ± 5.56 | 43.52 ± 6.52 |
| line_coverage | 52.49 ± 6.61 | 53.05 ± 3.19 |
| strict_block_coverage | 57.41 ± 5.16 | 53.70 ± 2.45 |
| block_precision | 51.58 ± 1.38 | 49.10 ± 1.31 |
| mention_coverage | 72.59 ± 1.77 | 74.72 ± 2.74 |

Checks on the parity runs:
- On 36 of 36 Harbor trials, the in-container `reward.json` equals upstream's offline rescoring of the
  same diagnosis (`scripts/harbor_job_to_distdebug.py` → upstream `score_run`).
- Upstream `distdebug_bench.leakage` flags 0 of 36 traces on either side. One earlier Harbor trial
  (run 2, elasticsearch-128583) had been flagged; it was caused by Harbor's session-ID header, was
  excluded and rerun after the fix (see Notes & Caveats).
- No missing or schema-invalid diagnoses on either side.
- The system and instance messages in the saved trajectories are byte-identical between the two sides,
  except Mini-SWE-Agent's `<system_information>` line. That line is `uname` output: an x86_64 Linux host
  for the original side and an aarch64 Linux VM for the Harbor side.
- Per-bug variance is large for this model, and it goes both ways. For example, hbase-28376 scores
  1.0 / 1.0 / 1.0 on the original side and 0.0 / 1.0 / 0.0 on Harbor, while kafka-13407 scores
  0.0 / 0.0 / 0.0 on the original side and 0.0 / 0.0 / 1.0 on Harbor. The low-scoring trajectories
  show normal completions that localize a different component, not environment failures.

Per-bug block_coverage (runs 1 / 2 / 3):

| Bug | Original | Harbor |
|---|---|---|
| elasticsearch-128583 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| etcd-17507 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| hbase-28376 | 1.0 / 1.0 / 1.0 | 0.0 / 1.0 / 0.0 |
| hdfs-10512 | 0.67 / 0.67 / 0.67 | 0.67 / 0.67 / 0.67 |
| ignite-6860 | 0.0 / 0.0 / 0.0 | 0.2 / 0.2 / 0.0 |
| ignite3-21827 | 0.5 / 0.5 / 0.5 | 0.5 / 0.5 / 0.5 |
| kafka-13407 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 1.0 |
| kafka-13668 | 0.25 / 0.25 / 0.5 | 0.25 / 0.25 / 0.5 |
| kubernetes-135981 | 0.5 / 0.5 / 0.5 | 0.5 / 0.5 / 0.5 |
| ray-14264 | 0.0 / 1.0 / 0.67 | 0.33 / 0.33 / 1.0 |
| tikv-18458 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| zookeeper-2581 | 0.0 / 1.0 / 1.0 | 1.0 / 1.0 / 0.0 |

**Protocol.**
- **Agent:** Mini-SWE-Agent 2.2.8, the harness behind the paper's main table. Harbor has a built-in
  `mini-swe-agent`, so no custom agent is needed (scenario 1).
- **Model:** StepFun `step-5-preview` through the Step Plan OpenAI-compatible endpoint
  (`https://api.stepfun.com/step_plan/v1`, chat completions), used identically on both sides.
- **Tasks:** the 12-bug `parity` split (`src/distdebug_bench/parity_subset.txt`): the first Lite bug of
  each of the 11 systems plus `kafka-13668`. That is 10% of the full 120-bug benchmark and 35% of Lite.
  If the team prefers, all 34 Lite tasks can be used instead.
- **Runs:** 3 per side, ramped as the guide requires: sanity on a few tasks → 1 full run on both sides →
  3 runs on both sides.
- **Protocol on both sides:** one attempt per bug per run. A missing or schema-invalid diagnosis scores 0.
  (Upstream's leaderboard instead retries until it has a valid diagnosis. Harbor cannot retry within a
  trial, so the parity comparison uses no retries on both sides.) Both sides are rescored offline with the
  same upstream `score_run` (`scripts/parity_compare.py`).
- **Reported:** `block_coverage` (primary) and `file_coverage`, as mean ± sample SEM over runs, with the
  range-overlap criterion, plus per-bug MSE between the sides as a supplementary statistic.
- **Settings held identical:** prompt (byte-identical, checked), `step_limit: 0`, `cost_limit: 3.0`
  (inactive: StepFun prices are unknown to LiteLLM, so `MSWEA_COST_TRACKING=ignore_errors`, as in the
  paper's MiMo/Hunyuan configs), 60 s command timeout, `drop_params: true`. Harbor's wall-clock limit is
  set to 2 h (`override_timeout_sec`) because the upstream runner has none. The Harbor side passes
  `session_id_headers: []` so that the bug id is not exposed to the agent (see Notes & Caveats).

**Reproduction.**

Original side (fork of `OrderLab/distdebug-bench` at `c3e929b`, plus `configs/original/mini-swe-agent-step-5-preview.yaml`):
```bash
pip install -e ".[agent]"     # Linux with bubblewrap
cp <adapter>/configs/original/mini-swe-agent-step-5-preview.yaml configs/mini-swe-agent/step-5-preview.yaml
export OPENAI_API_KEY=<Step Plan key>
for i in 1 2 3; do
  for b in $(cat <adapter>/src/distdebug_bench/parity_subset.txt); do
    python -m distdebug_bench.run --config configs/mini-swe-agent/step-5-preview.yaml \
      --bug $b --runs 1 --max-attempts 1 --output results/parity-original-$i
  done
done
python -m distdebug_bench.leakage results/parity-original-1   # repeat per run
```

Harbor side:
```bash
cd src/distdebug-bench && uv run distdebug-bench --split parity --output-dir ../../datasets/distdebug-bench-parity && cd ../..
export STEPFUN_API_KEY=<Step Plan key>
for i in 1 2 3; do harbor run -c src/distdebug-bench/run_distdebug-bench_parity.yaml --job-name distdebug-parity-$i; done
for i in 1 2 3; do python src/distdebug-bench/scripts/harbor_job_to_distdebug.py jobs/distdebug-parity-$i results/parity-harbor-$i --redact-env STEPFUN_API_KEY; done
```

Compare:
```bash
python src/distdebug-bench/scripts/parity_compare.py --upstream /path/to/distdebug-bench \
  --bugs src/distdebug-bench/src/distdebug_bench/parity_subset.txt \
  --original results/parity-original-{1,2,3} --harbor results/parity-harbor-{1,2,3}
```

## Notes & Caveats

- **Deviations from upstream, and why.**
  - *Sandbox.* Upstream runs Mini-SWE-Agent on the host and runs each command in bubblewrap with no
    network. CLI agents run inside bubblewrap behind a model-API gateway. Harbor runs the agent inside the
    task container, and the agent phase allows only the LLM API hosts. The isolation goal is the same
    (no issue tracker, no fix, no benchmark site), but it is enforced by Harbor's network policy rather
    than a gateway.
  - *Tools in the workspace.* Upstream commands see whatever the host has in `/usr`. The agent image is
    `ubuntu:24.04` with `git`, `python3`, `ripgrep`, `less`, `file` and `procps`, and no compilers or JDKs.
    `chafa`/`img2txt`, which upstream disables, are not installed.
  - *Workspace path.* Upstream uses a random `workspace-<uuid>` directory. Here it is `/workspace`, which
    is also neutral.
  - *Invalid diagnoses.* Upstream discards attempts without a schema-valid `diagnosis.json` and retries.
    Harbor scores them 0 with `valid_diagnosis = 0`. Exclude those trials and rerun them to reproduce the
    leaderboard protocol.
  - *Leakage check.* Upstream discards attempts in which the agent saw or typed the original issue key,
    the fix PR or the fix commit. Harbor does not run this inside the verifier, because it needs the
    agent's trace. Run upstream `distdebug_bench.leakage` on converted results
    (`scripts/harbor_job_to_distdebug.py`; Mini-SWE-Agent traces are supported directly). Some issue
    descriptions mention *other* issue keys (for example ZOOKEEPER-2678 in zookeeper-2845). That is
    upstream content and is unchanged.
  - *Agent-side session header (set `session_id_headers: []`).* By default Harbor's `mini-swe-agent`
    adds `-c model.model_kwargs.extra_headers.X-Session-ID=<trial name>` to its command line. The trial
    name starts with the bug id, and mini-swe-agent echoes its command-line specs into
    `/logs/agent/mini-swe-agent.txt`, which the agent can read from inside its own container. In one
    parity trial (Harbor run 2, elasticsearch-128583) the agent did exactly that and saw `128583`; the
    leakage check flagged it. `run_distdebug-bench_parity.yaml` therefore passes
    `session_id_headers: []`. With it, the bug id appears neither in that log, the process list, the
    environment nor the hostname (checked inside a running trial). The flagged trial was excluded and
    rerun with the fix. Use the same kwarg for any Harbor run of this benchmark with `mini-swe-agent`.
  - *API key in traces.* The same log line also contains the model API key. It is not task data, but an
    agent that reads the log copies it into its trajectory. Pass `--redact-env <KEY_VAR>` to
    `scripts/harbor_job_to_distdebug.py` before sharing converted traces.
- **How the Harbor-side parity runs were executed.** They ran on macOS (Apple silicon) with Docker via
  Colima, one task at a time. On that network, three local settings were needed. None of them changes the
  task, the prompt or the scorer:
  - Harbor's `--ae UV_DEFAULT_INDEX=<PyPI mirror>`, so that the agent installs from a PyPI mirror. It
    resolves the same package versions; for example, litellm is 1.110.2 on both sides.
  - An `--extra-docker-compose` overlay that pins `api.stepfun.com` in `/etc/hosts`. Colima's Docker
    embedded DNS cannot reach its upstream resolver once Harbor's allowlist is active.
  - A build-time-only proxy for GitHub.
- **Module-relative label paths.** Some HDFS and Ignite/Ignite 3 labels omit the leading module
  directory (e.g. `hadoop-hdfs/src/...` for `hadoop-hdfs-project/hadoop-hdfs/src/...`). Upstream's
  scorer matches a path that contains the other, so repository-relative answers still match. We checked
  that every labeled file of the 34 tasks resolves to exactly one file at its pinned commit, with line
  ranges inside the file.
- **Labels with empty ranges.** `ray-25699` has one labeled block with `start_line == end_line`. Under the
  half-open line ranges of the upstream scorer it covers no lines, so even the oracle gets
  `strict_block_coverage = 0.5` there (`block_coverage` = 1.0).
- **Image sizes.** Each image contains the full ancestor history of its system. Measured snapshot sizes
  (`.git` + worktree): Elasticsearch 1.4–1.6 GB and Kubernetes 1.5 GB. Every other Lite bug is at most
  0.45 GB (HBase, HDFS, Ignite and Ray are 0.1–0.45 GB; Kafka, etcd, TiKV, Ignite 3 and ZooKeeper are
  40–250 MB). All 34 together come to about 15 GB on top of the shared `ubuntu:24.04` layer. Builds fetch
  from GitHub; the largest fetch takes 65–90 s on a fast link, and `build_timeout_sec` is 3600 for
  Elasticsearch/Kubernetes and 1800 for the rest.
- **Full split.** `--split full` is implemented (all 120 snapshots are pinned) but its oracle runs have not
  been validated yet.
- **Windows hosts.** The tasks are Linux containers. With Docker Desktop (WSL2 backend) they run as usual.
  Check out the adapter with LF line endings (`git config core.autocrlf false`), because a CRLF `test.sh`
  or `build_snapshot.sh` fails inside the container. The generator always writes LF. The allowlist
  network mode needs nftables support in the Docker VM. If your setup lacks it, generate with
  `--agent-network public` and run the leakage check afterwards.

## Installation / Prerequisites

- Docker (or another Harbor environment that supports separate verifiers and `allowlist` networking,
  e.g. Daytona) and network access to GitHub during image builds.
- Harbor CLI: `uv tool install harbor`.
- Adapter: `cd src/distdebug-bench && uv sync` (Python ≥ 3.11, depends only on PyYAML).
- Model API keys for the agent you run. Make sure the model host is in the allowlist.
- For the original side of parity: Linux with bubblewrap and Python ≥ 3.10 (`pip install -e ".[agent]"`
  in the upstream repo).

## Troubleshooting

- **`snapshot ... fetch failed`** during the build: GitHub rate limiting or a flaky network. The fetch
  aborts if it stalls below 1 KB/s for 60 s and is retried 3 times. Rebuild the failed task. If your
  machine reaches GitHub through a proxy, give the Docker builds that proxy, for example via `proxies`
  in `~/.docker/config.json`. Do not leave that proxy set for the trial containers. The agent phase
  runs behind Harbor's egress control (allowlist), and proxy variables injected into the containers
  make agent setup fail (`apt-get` gets `502 Bad Gateway` from the proxy). Build the images first
  (e.g. an oracle pass with `--no-delete`), remove the proxy, then run agents. Without
  `--force-build`, Harbor reuses the built images.
- **Disk space on small machines:** each task image keeps its snapshot (up to about 1.6 GB for
  Elasticsearch and Kubernetes), plus the BuildKit cache. With little free disk, run with `-n 1` and
  prune between tasks (`docker builder prune`). For Colima or Docker Desktop, also cap the VM disk size,
  because a VM disk that outgrows the host's free space turns the VM filesystem read-only.
- **Agent cannot reach its model:** the endpoint host is not in `allowed_hosts`. Add it via
  `extra_allowed_hosts` or regenerate with `--allowed-hosts`.
- **`allowlist` not supported by the environment:** regenerate with `--agent-network public` (see
  Notes & Caveats).
- **`reward.json` shows `valid_diagnosis: 0`:** the agent wrote no `/workspace/diagnosis.json`, or one
  that fails the upstream schema. `scoring_details.json` in the verifier logs gives the reason.
- **Generation error "Upstream files differ from the pinned commit":** `--source-dir` points at a
  different upstream revision. Check out `c3e929b` or pass `--allow-unpinned-source`.

## Citation

```bibtex
@inproceedings{jiang2026distdebugbench,
  title     = {{DistDebug-Bench}: Can {LLM} Agents Diagnose Bugs in Distributed Systems?},
  author    = {Jiang, Yuxuan and Liu, Chenglin and Rose, John and Miller, Mason and Thavamani, Ruthesh and Wu, Juntao and Huang, Yinwei and Xu, Jiahao and Huang, Peng},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
  year      = {2026}
}
```

## Authors & Contributions

This adapter is developed and maintained by Xiang Ding (GitHub: Nhckdvrl) for Harbor Index v2.0.

**Issues and Contributions:**
- Submit issues and pull requests to the [Harbor adapters repository](https://github.com/harbor-index/adapters).
- Benchmark questions: [OrderLab/distdebug-bench](https://github.com/OrderLab/distdebug-bench).
