# Live delivery record

2026-11-20 · Private GitHub-hosted staging

| Step | Evidence |
| --- | --- |
| Bootstrap build and runtime verification | [PR #1](https://github.com/archit15singh/autonomous-delivery-loop/pull/1) · [Hosted staging](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44774698312) |
| Main-owned verification and Codex repair | [PR #2](https://github.com/archit15singh/autonomous-delivery-loop/pull/2) |
| Named greeting before repair | [Expected failed run](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44775213789) · [Receipt](evidence/named-before.json) |
| Codex patch and independent preview | [PR #3](https://github.com/archit15singh/autonomous-delivery-loop/pull/3) · [Trusted preview](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44775593565) · [Receipt](evidence/named-candidate.json) |
| Separate impact gate and refinement grader | [PR #4](https://github.com/archit15singh/autonomous-delivery-loop/pull/4) · [Standard main staging](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44776021337) |
| Named greeting after merge and later verifier changes | [Isolated staging](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44776030448) · [Receipt](evidence/named-deployed.json) |

The independent verifier observed the default greeting at the named endpoint and requested a repair. Codex produced a patch to the one approved source file. The patched PR passed ordinary checks and the main-owned preview before merge. A later main deployment verified the named greeting with 13 unit checks in the pipeline. Its archived service digest matched the standard hosted staging run.

## Refinement decision

The promotion threshold was a 15% median paired gain with every control preserved. The local and hosted runs each started the actual service 18 times per variant and checked healthy, incorrect, wrong-deployment and mid-probe rollout responses.

| Variant | Local paired gain | Hosted paired gain | Decision |
| --- | ---: | ---: | --- |
| Parallel probes | −0.05% | −2.46% | Kept sequential probes |
| Cached revision read | +0.33% | −0.74% | Kept both revision reads because the cache accepted a rollout change |

[Local raw timings](evidence/refinements-local.json) · [Hosted raw timings](evidence/refinements-hosted.json) · [Hosted eval](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44776036698)

## Boundaries verified

- The hosted service was live for a staging job and stopped with that job.
- The impact evaluator passed tests for sufficient, insufficient, stale and below-target observations. The greeting rollout required runtime evidence. It produced no customer impact result.
- This private GitHub plan returned HTTP 403 for branch protection. Merges used checked receipts and an exact PR head guard. The repository plan does not enforce that gate for other operators.
