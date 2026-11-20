# Codex delivery eval

Compare Codex on pinned commits from three SWE-bench Verified issues. The trials share the model, snapshots, and CLI limits. The retained `equipped-feedback` workflow gives Codex the delivery skill and the results of a verified preflight. Work runs in fresh Git checkouts with no remote and with agent network and web search disabled.

## Run locally

Use Python 3.11 and an authenticated Codex CLI.

    python3.11 -m venv /tmp/adl-test-env
    /tmp/adl-test-env/bin/pip install -r evals/requirements.txt
    python3.11 -B evals/run.py --state /tmp/adl-evidence --python /tmp/adl-test-env/bin/python --round retained
    python3.11 -B evals/replay.py --python /tmp/adl-test-env/bin/python /tmp/adl-evidence retained
    python3.11 -B evals/summarize.py /tmp/adl-evidence retained

Use a fresh --round for a repeat. The runner reuses passing controls and completed trials within a round. Keep the scratch directory on local disk. It contains raw Codex tool output. The summarizer exports only score data.

A solved issue requires the trusted acceptance and existing regression checks to pass in a fresh grading checkout. The grader uses trusted test files. Controls establish that each acceptance test fails on the original snapshot and passes with the upstream fix. Stage replay applies the exact patch, checks its diff, runs the candidate's focused suite, and probes the resulting behavior. The workflow score records patch scope, test edits, and whether Codex observed a pytest failure before a later passing check. Time and token usage are recorded without estimating a dollar cost.

## Refinement rounds

- Run `--round pilot --variant plain equipped` to reproduce the skill-only comparison.
- Run `--round climb-1 --variant equipped-feedback` to test verified preflight handoff.
- Run `--round climb-2 --variant equipped-check` to add the candidate-facing test command.
- Run `--round climb-3 --variant equipped-receipt` to test a structured final report.
- Run `--round repeat --variant plain equipped equipped-feedback equipped-check` to replicate. To vary ordering, use separate `--case` invocations and rotate variant order across the three cases.
- Replay and summarize with the round names appended to each command.

The pilot uses an exploratory promotion rule. A change preserves all local delivery gates and observed workflow evidence, improves median paired elapsed time or uncached input tokens by at least 15%, and worsens the other metric by at most 10%. Prefer changes that clear the bar in exploration and replication. A rerun after a backend capacity failure keeps the timed-out attempt in the scorecard under `infra-retry`.

These are local patch and test gates. Upstream PR approval, actual deployment, and production behavior are outside this experiment. The public issue texts and fixes may be familiar to the model. Three selected issues show operational feasibility and provide weak evidence for general performance.
