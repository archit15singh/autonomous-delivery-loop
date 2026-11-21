# Verify an upstream fix

The Codex [upstream PR skill](../.agents/skills/upstream-pr/SKILL.md) covers issue intake, reproduction, patch review, and the evidence to include in a PR. It supports the [official Pstack skills](https://github.com/cursor/plugins/blob/main/pstack/README.md) through the local Codex adapters.

The replay command checks the base and candidate in detached worktrees, one at a time. It applies only the regression fixture to the base. The base must fail with the expected output and the exact candidate must pass with its expected output. The command records both exits, the revisions, the contract digest, and the log digests. A timeout or unexpected output leaves the case unverified.

## Run a case

Use a contract you have reviewed. The command runs that contract's argument list as the current user. For hosted contributions, keep the contract and workflow in the ADL repo and run the replay in a job with read-only repository permissions.

```sh
python3 -m delivery upstream-replay \
  --repo /path/to/upstream-checkout \
  --contract contracts/upstream/act-6236.json \
  --output .adl/act-6236-replay
```

The source checkout must contain both full revisions. Install the toolchain named by the upstream repo before the run. Choose a new output directory for each attempt. Inspect `before.log`, `after.log`, and `receipt.json` in that directory.

Keep the workflow's explicit Bash shell when adding hosted replays. GitHub Actions enables `pipefail` for `shell: bash`, so a failing replay still fails the job when its output is piped through `tee`. Check the expected diagnostics in the raw logs before treating a hosted result as verified. [GitHub Actions shell behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#defaultsrun-shell).

The [act case](../contracts/upstream/act-6236.json) uses a real HTTP client and a loopback daemon fixture. [The hosted workflow](../.github/workflows/upstream-evidence.yml) publishes the same replay with its raw logs. The [pull request](https://github.com/nektos/act/pull/6265) uses a two-row table to show where the auth header changed.

The [composite action case](../contracts/upstream/act-2517.json) uses the same replay job to verify an error-handling regression. The [Herdr Core clock case](../verification/herdr-core-302.sh) builds both versions of an existing test. It runs each with normal clocks and with a Linux time namespace that moves the boot clock ahead. Its logs show which failure the verifier expected and record the exact checkouts.

The [Herdr Core reconnect case](../verification/herdr-core-305.sh) starts two isolated cores and checks a viewer's scrollback after the relay reconnects. Both builds run the same regression test. The baseline must fail on the scrollback assertion, and the candidate must pass. The workflow uploads the revisions, logs, and exit codes.


## Prepare a PR

Develop in an isolated checkout with the repo’s pinned toolchain and dependencies. Reproduce the issue locally through the affected CLI, browser, service, SDK, or documentation example before editing. Keep fixture data and services isolated from the user's settings and running services.

Choose the checks that cover the most likely regressions. Use the issue reproduction, one representative unchanged flow, and the boundary or error path most exposed by the diff. Consider configuration precedence, platform differences, retries, cleanup, and concurrency when they affect the changed path. Run the relevant existing suite. Record concrete limits. A hosted run can add coverage for another platform.

Extend the [replay contract](../contracts/upstream/act-2708.json) with a local readiness profile. Use `name`, `command` (argument list), and `contains` (expected output) for each setup, control, and suite check. Give each control a `kind`. Commands must assert behavior before returning 0. For an expected rejection, have the probe validate the error and return 0 when it matches. The reproduction uses the existing `before` and `after` expectations. If an external probe needs no test-only patch, set `regression_paths` to an empty list.

```json
{
  "readiness": {
    "live_entrypoint": "Built CLI reads the selected config",
    "setup": {"name": "Build locked dependencies", "command": ["./check.sh", "setup"], "contains": "build ready"},
    "controls": [
      {"kind": "normal", "name": "Default config still loads", "command": ["./check.sh", "default"], "contains": "default loaded"},
      {"kind": "failure", "name": "Invalid config reports its path", "command": ["./check.sh", "invalid"], "contains": "path verified"}
    ],
    "exclusions": {"boundary": "Input length and parsing are unchanged"},
    "suite": {"name": "Config integration suite", "command": ["./check.sh", "suite"], "contains": "config suite passed"}
  }
}
```

1. Fill the upstream PR template with the issue, cause, and change. Include any required contributor fields.
2. Reserve a reviewer-accessible HTTPS location for sanitized logs and the receipt.
3. Run the gate from the factory checkout. Use a fresh output directory.

   ```sh
   python3 -m delivery upstream-prepare --repo /path/to/checkout \
     --contract /path/to/contract.json --template /path/to/pr-template.md \
     --evidence-url https://example.com/replay --output .adl/issue-readiness
   ```

4. Review and publish the receipt and relevant logs. Check that the evidence URL resolves and that the body accurately describes the tested scenarios and limits.
5. Open the PR with the generated `pr.md` once the published branch matches the verified SHA. If a check fails or the head changes, keep the receipt, fix the failure, and replay the exact head before presenting it as verified.

The command provisions both detached worktrees, runs the live comparison and controls on both, and runs the existing suite on the candidate. It records the execution platform, commands, signals, and log digests. It writes `pr.md` only when all checks pass and the local head still matches. The operator owns test selection, evidence publication, and the GitHub submission.

Browser proofs are bound to the declared base and candidate. PR preparation archives the receipt and four screenshot files captured during validation. The run index records the checked browser baseline in `provenance.browser_base`. When a historical browser run lacks this field, refresh the portfolio using the run index and repeat `upstream-prepare` with `--browser-proof`, `--pr`, and `--runs` in a fresh output directory. This creates a new indexed run with verified provenance for the current revisions.
