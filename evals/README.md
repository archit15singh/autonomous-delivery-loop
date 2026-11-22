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

## Evidence for workflow adoption

Add `--pair plain equipped-feedback` to the summarizer to emit the paired
decision for the selected rounds. Promotion requires complete frozen cases in
each round, the same agent and model across each comparison, independently
verified stage outcomes and regression checks, and observed time, token and
intervention metrics. Cost-based routing separately requires actual billed cost.
An incomplete round stays visible and retains the baseline.

The native run uses a fresh solver checkout and an independent grading checkout.
Use `--protect-grader` to deny reads of the grader paths in native Codex trials.
A preflight checks that the selected Codex sandbox denies the read before starting
a model call. The receipt records whether the trial used that boundary.
For a strict separation of protected tests, give the solver an isolated worker
that has access only to the solver checkout and required dependencies. The
local sandbox and separate grader checkout support exact replay. Use isolated
workers for studies that require protected benchmark files to be inaccessible
to the solver.

The optional `--agent opencode` and `--agent claude` adapters take an explicit
model ID and an absolute `--isolated-worker` executable. Codex also accepts an
isolated worker when you need all arms under the same environment boundary.
The operator's launcher receives the provider argv from the solver directory.
It runs the command inside the isolated worker, forwards stdin/stdout/stderr,
and persists only edits to the solver checkout. Configure provider credentials
inside the worker. Give the worker no mounts for grader assets or the
operator's home. The launcher receives a minimal environment from ADL.
Use the same timeout, task set, dependencies and grading checks across arms.
Provider cost remains unknown until matched to billing observations.
