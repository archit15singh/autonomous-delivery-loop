# Verify an upstream fix

The Codex [upstream PR skill](../.agents/skills/upstream-pr/SKILL.md) covers issue intake, reproduction, patch review, and the evidence to include in a PR. It supports the [official Pstack skills](https://github.com/cursor/plugins/blob/main/pstack/README.md) through the local Codex adapters.

The replay command makes the same check in two detached worktrees. It applies only the regression fixture to the base. The base must fail with the expected output and the exact candidate must pass with its expected output. The command records both exits, the revisions, the contract digest, and the log digests. A timeout or unexpected output leaves the case unverified.

## Run a case

Use a contract you have reviewed. The command runs that contract's argument list as the current user. For hosted contributions, keep the contract and workflow in the ADL repo and run the replay in a job with read-only repository permissions.

```sh
python3 -m delivery upstream-replay \
  --repo /path/to/upstream-checkout \
  --contract contracts/upstream/act-6236.json \
  --output .adl/act-6236-replay
```

The source checkout must contain both full revisions. Install the toolchain named by the upstream repo before the run. Choose a new output directory for each attempt. Inspect `before.log`, `after.log`, and `receipt.json` in that directory.

The [act case](../contracts/upstream/act-6236.json) uses a real HTTP client and a loopback daemon fixture. [The hosted workflow](../.github/workflows/upstream-evidence.yml) publishes the same replay with its raw logs. The [pull request](https://github.com/nektos/act/pull/6265) uses a two-row table to show where the auth header changed.
