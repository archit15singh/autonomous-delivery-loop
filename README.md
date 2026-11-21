# Autonomous Delivery Loop

Codex implements the change. A deterministic verifier checks the exact artifact in GitHub-hosted staging. The release operator controls merge and deployment.

```text
reviewed outcome contract
  → Codex change and pull request
  → unit checks and commit archive
  → live HTTP verification in a separate hosted job
  → verified, failed, or inconclusive evidence
  → complete, bounded repair, or escalate
```

- [Outcome contract](contracts/pilot.json)
- [Hosted workflow](.github/workflows/delivery.yml)
- [Paired Codex eval and scorecard](evals/README.md)
- [Ecosystem research](docs/ecosystem.md)
- [Live delivery evidence](docs/live-delivery.md)
- [Upstream contribution evidence](docs/upstream-delivery.md)
- [Open-source tool map](docs/open-source-tool-map.md) and [contribution pass](docs/contribution-pass.md)
- [Replay exact upstream regressions](docs/upstream-replay.md)
- [Follow upstream CI, reviews, and merge precedents](docs/ci-follow-up.md)
- [Operate factory verification, workflows, and publication](docs/factory-operations.md)
- [33-PR upstream campaign and verification status](docs/upstream-campaign.md)

From a clean checkout with Python 3.11 or later:

```sh
revision=$(git rev-parse HEAD)
python3 -m delivery build --revision "$revision" --deployment local-1 --output .adl/bundle
python3 -m delivery stage --contract contracts/pilot.json --bundle .adl/bundle \
  --revision "$revision" --deployment local-1 --output .adl/evidence.json
```

The GitHub workflow publishes a commit archive, a build receipt, and the runtime evidence from the same run attempt. A runtime instance identifies its revision and deployment before and after probing. Use a full workflow rerun so the archive and verify jobs share the same attempt.

Hosted staging is an ephemeral service inside an Actions runner. Runtime outcome means observed HTTP behavior for the selected build. Business impact requires an independent observation source and a contract that defines how to interpret it.

## Independently grade and repair a candidate

The trusted workflow is dispatched from reviewed `main`. It verifies that the candidate descends from the policy revision and that all changed paths are permitted. It then probes archived candidate code over loopback in a network-isolated container. The candidate runs as an unprivileged user with the verifier and bundle mounted read-only. The workflow publishes its own receipt even when a behavior check fails.

```sh
gh workflow run trusted-candidate.yml --ref main \
  -f candidate="$candidate_sha" -f contract=named-greeting -f repairs-used=0

python3 -m delivery propose --contract contracts/named-greeting.json \
  --evidence .adl/previous/evidence.json --output .adl/candidate.patch \
  --events .adl/codex.jsonl
```

Inspect the receipt from the exact dispatch, including candidate SHA, policy SHA, deployment, archive digest, and verdict. The operator owns receipt selection, the repair count, PR and merge. Use `gh pr merge --match-head-commit` after checking the current candidate. The proposal subprocess receives no Git remote or release authority.

## Impact evidence and refinement

An optional contract `impact` policy names the independently collected source, metric, cohort, minimum sample count, observation window, and success rate. Give `delivery stage` its receipt with `--impact-evidence`. The receipt binds the same revision and deployment and provides timezone-aware `started_at` and `ended_at` timestamps plus `samples` and `successes`. Missing, mismatched, or immature evidence leaves impact inconclusive even when runtime passes. The pilot contracts exercise HTTP behavior. They require no customer-impact observation.

The [refinement workflow](.github/workflows/refinements.yml) is opt-in. It evaluates parallel HTTP probes and caching the repeated revision read against the current verifier. Promotion requires every live and negative control to pass and at least a 15% median paired improvement. Trial timings and verdicts are downloadable from Actions.
