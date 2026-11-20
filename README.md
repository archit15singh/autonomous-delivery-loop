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

From a clean checkout with Python 3.11 or later:

```sh
revision=$(git rev-parse HEAD)
python3 -m delivery build --revision "$revision" --deployment local-1 --output .adl/bundle
python3 -m delivery stage --contract contracts/pilot.json --bundle .adl/bundle \
  --revision "$revision" --deployment local-1 --output .adl/evidence.json
```

The GitHub workflow publishes a commit archive, a build receipt, and the runtime evidence from the same run attempt. A runtime instance identifies its revision and deployment before and after probing. Use a full workflow rerun so the archive and verify jobs share the same attempt.

Hosted staging is an ephemeral service inside an Actions runner. Runtime outcome means observed HTTP behavior for the selected build. Business impact requires an independent observation source and a contract that defines how to interpret it.
