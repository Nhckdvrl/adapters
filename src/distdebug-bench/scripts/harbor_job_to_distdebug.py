"""Convert a Harbor job directory into the upstream DistDebug-Bench results layout.

    <out>/<bug>/run-NN/diagnosis.json        (only if the agent left one)
    <out>/<bug>/run-NN/trajectory.json       (Mini-SWE-Agent native trace, if present)
    <out>/<bug>/run-NN/session_stats.json    (tokens / cost from Harbor's result.json)
    <out>/<bug>/run-NN/harbor_trial.txt      (source trial directory)

The upstream tools can then be run unchanged on Harbor results:

    python -m distdebug_bench.score   <out> --subset lite --attempts 1
    python -m distdebug_bench.leakage <out>

Trials of the same bug are numbered run-01, run-02, ... in start-time order.

Usage: python harbor_job_to_distdebug.py <harbor-job-dir> <out-dir>
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def bug_of(task_name: str) -> str:
    # "orderlab/distdebug-bench__zookeeper-2845" -> "zookeeper-2845"
    return task_name.rsplit("/", 1)[-1].split("__", 1)[-1]


def main() -> int:
    job, out = Path(sys.argv[1]), Path(sys.argv[2])
    trials = []
    for result_path in job.glob("*/result.json"):
        result = json.loads(result_path.read_text())
        if "task_name" not in result:
            continue  # job-level result.json
        trials.append((result.get("started_at") or "", result_path.parent, result))
    trials.sort(key=lambda t: (bug_of(t[2]["task_name"]), t[0]))
    counts: dict[str, int] = {}
    for _, trial_dir, result in trials:
        bug = bug_of(result["task_name"])
        counts[bug] = counts.get(bug, 0) + 1
        run_dir = out / bug / f"run-{counts[bug]:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        diagnosis = trial_dir / "artifacts" / "workspace" / "diagnosis.json"
        if diagnosis.is_file():
            shutil.copyfile(diagnosis, run_dir / "diagnosis.json")
        trace = trial_dir / "agent" / "mini-swe-agent.trajectory.json"
        if trace.is_file():
            shutil.copyfile(trace, run_dir / "trajectory.json")
        agent = result.get("agent_result") or {}
        stats = {
            "input_tokens": agent.get("n_input_tokens"),
            "input_cached_tokens": agent.get("n_cache_tokens"),
            "output_tokens": agent.get("n_output_tokens"),
            "total_tokens": (agent.get("n_input_tokens") or 0) + (agent.get("n_output_tokens") or 0),
            "cost": agent.get("cost_usd"),
            "harbor_exception": (result.get("exception_info") or {}).get("exception_type"),
            "harbor_rewards": (result.get("verifier_result") or {}).get("rewards"),
        }
        (run_dir / "session_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
        (run_dir / "harbor_trial.txt").write_text(str(trial_dir.resolve()) + "\n")
    print(f"Converted {len(trials)} trials of {len(counts)} bugs into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
