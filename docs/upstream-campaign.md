# 33-PR upstream campaign

The target is three verified, non-draft upstream PRs in each of 11 repositories. Verification uses the exact upstream base and candidate with a real CLI, UI, API, or CI replay. The PR or linked evidence records the commands, observed change, and test limits.

## Snapshot

GitHub state checked on November 21, 2026 at 04:48 UTC. Counts are **21 non-draft**, **3 drafts**, and **9 staged on public forks**. All 24 upstream PRs were open at their verified heads. The campaign window ends at 08:19 UTC.

| Repository | Non-draft / target | Shortfall | Verified PRs and review state |
| --- | ---: | ---: | --- |
| Herdr Core | 3 / 3 | 0 | Linux, macOS, and the independent Windows Server 2022 matrix passed. The required Windows Server 2025 job still fails on the same baseline Zig/Ghostty toolchain mismatch. [Windows replay](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44866263703). [#352](https://github.com/herdrdev/herdr-core/pull/352), [#353](https://github.com/herdrdev/herdr-core/pull/353), [#356](https://github.com/herdrdev/herdr-core/pull/356) |
| Harbor | 0 / 3 | 3 | Three fixes verified on the public fork. The PR descriptions need human-written first and final drafts. [Contribution guide](https://github.com/harbor-framework/harbor/blob/main/CONTRIBUTING.md#communication) |
| OpenCode | 3 / 3 | 0 | PR checks passed. Each PR includes a CLI, TUI, or browser reproduction for its exact head. [#65284](https://github.com/anomalyco/opencode/pull/65284), [#65291](https://github.com/anomalyco/opencode/pull/65291), [#65314](https://github.com/anomalyco/opencode/pull/65314) |
| Schemathesis | 3 / 3 | 0 | Independent replays and Read the Docs passed. Maintainer approval is pending for the first-contributor workflows. [#6198](https://github.com/schemathesis/schemathesis/pull/6198), [#6199](https://github.com/schemathesis/schemathesis/pull/6199), [#6200](https://github.com/schemathesis/schemathesis/pull/6200) |
| act | 3 / 3 | 0 | PR checks and independent replays passed. [#6265](https://github.com/nektos/act/pull/6265), [#6266](https://github.com/nektos/act/pull/6266), [#6267](https://github.com/nektos/act/pull/6267) |
| Promptfoo | 3 / 3 | 0 | PR checks and exact CLI replays passed. [#12534](https://github.com/promptfoo/promptfoo/pull/12534), [#12535](https://github.com/promptfoo/promptfoo/pull/12535), [#12536](https://github.com/promptfoo/promptfoo/pull/12536) |
| OpenHands SDK | 0 / 3 | 3 | Three verified drafts. Each needs the contributor's own HUMAN note before review. [#7040](https://github.com/OpenHands/software-agent-sdk/pull/7040), [#7041](https://github.com/OpenHands/software-agent-sdk/pull/7041), [#7047](https://github.com/OpenHands/software-agent-sdk/pull/7047) |
| Inspect AI | 3 / 3 | 0 | PR checks passed and the corrected examples ran. [#6699](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6699), [#6700](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6700), [#6701](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6701) |
| Dagger | 0 / 3 | 3 | Three fixes verified on the public fork. The contribution workflow requires an issue claim and author DCO sign-off. [Contribution guide](https://github.com/dagger/dagger/blob/main/CONTRIBUTING.md#contribution-workflow) |
| Argo Rollouts | 0 / 3 | 3 | Three fixes verified on the public fork. The PR checklist requires author DCO sign-off. [PR template](https://github.com/argoproj/argo-rollouts/blob/master/.github/pull_request_template.md) |
| Herdr App | 3 / 3 | 0 | Hosted checks and targeted application replays passed. Platform-specific coverage is listed in the PRs. [#1295](https://github.com/herdrdev/herdr-app/pull/1295), [#1297](https://github.com/herdrdev/herdr-app/pull/1297), [#1300](https://github.com/herdrdev/herdr-app/pull/1300) |

## Verified fork candidates

Each row links an exact candidate commit and a replay that shows the before-and-after result. Candidate SHAs can change during submission. Verification must follow the submitted head.

| Issue | Verified behavior | Candidate and evidence |
| --- | --- | --- |
| [Harbor #4414](https://github.com/harbor-framework/harbor/issues/4414) | The Pi compatibility option changes the gateway request from a rejected developer role to an accepted system role. | [Commit](https://github.com/archit15singh/harbor/commit/7b624095caa6720de01390ddf3a9a6f06fd269c6), [replay](https://gist.github.com/archit15singh/e529620bd6f065b966a0f2fca43dbe3a) |
| [Harbor #2805](https://github.com/harbor-framework/harbor/issues/2805) | Docker retry recovers from a seeded name conflict after a failed cleanup and preserves a neighboring project. | [Commit](https://github.com/archit15singh/harbor/commit/d91fcb7affe403a6a1c39bf720647305f6099d57), [replay](https://gist.github.com/archit15singh/eb6535de6bbc3f398f3da75b58f0a55e) |
| [Harbor #2223](https://github.com/harbor-framework/harbor/issues/2223) | A dataset name containing double underscores keeps its metric and displays its full title. | [Commit](https://github.com/archit15singh/harbor/commit/5274acdd682eb102a03a73e7e88ee551cc635bbd), [replay](https://gist.github.com/archit15singh/d37ecd2552c0cba67ab4fc672e5713fe) |
| [Dagger #13559](https://github.com/dagger/dagger/issues/13559) | The docs export and index use the same 144 canonical routes with resolved includes and absolute links. | [Commit](https://github.com/archit15singh/dagger/commit/cbc171fa4bdf23e63720741c679e372a0d587c74), [replay](https://github.com/archit15singh/autonomous-delivery-loop/blob/f5942b82faef956c37720995b5b5f3215781f0da/verification/dagger-13559.md) |
| [Dagger #13610](https://github.com/dagger/dagger/issues/13610) | The TypeScript SDK advertises the Node versions its dependency supports. The install matrix also checks a loopback SDK request. | [Commit](https://github.com/archit15singh/dagger/commit/6173169373d078cbb366e5c39cf80ed9b76332ff), [replay](https://github.com/archit15singh/autonomous-delivery-loop/blob/4a0ebe5e8475f94bf082e1e78a0b1097d04f06d6/verification/dagger-13610.md) |
| [Dagger #14081](https://github.com/dagger/dagger/issues/14081) | Released API references load only their release schema. The next reference loads its own schema. The glossary loads neither. | [Commit](https://github.com/archit15singh/dagger/commit/d3e63374bbd83702d623858e7098fe642a801446), [browser and release CLI evidence](https://gist.github.com/archit15singh/9a80b382706620a43f1752be09e94884) |
| [Argo Rollouts #4837](https://github.com/argoproj/argo-rollouts/issues/4837) | The documented recovery restores live NGINX canary routing while preserving the stable Ingress UID. | [Commit](https://github.com/archit15singh/argo-rollouts/commit/7d64fd23f32237314b498053688c32fc29b1fdbd), [live replay](#argo-rollouts-4837-live-nginx-replay) |
| [Argo Rollouts #2958](https://github.com/argoproj/argo-rollouts/issues/2958) | The controller accepts the documented ALB exact-header configuration, writes the routing annotations, and cleans them up. | [Commit](https://github.com/archit15singh/argo-rollouts/commit/4d0c34291171404cef26cd769a2613c45b847657), [replay](https://github.com/archit15singh/autonomous-delivery-loop/blob/5a6f62ba222e3e9a9a348440e4b6633563ea8cd5/verification/argo-2958.md) |
| [Argo Rollouts #1232](https://github.com/argoproj/argo-rollouts/issues/1232) | The analysis examples execute as written through the production evaluator for scalar, list, and map results. | [Commit](https://github.com/archit15singh/argo-rollouts/commit/34e0ea257586a035bc3f5beb4824635e4a34fbeb), [replay](https://github.com/archit15singh/autonomous-delivery-loop/blob/27943c903b6b9864cf467303098d4a24349d1dc5/verification/argo-1232.md) |

## Argo Rollouts #4837 live NGINX replay

The exact candidate's controller ran in an isolated kind Kubernetes 1.35.0 cluster with ingress-nginx 1.15.1. A stale restored owner reference triggered `TrafficRoutingError`. The documented recovery deleted the generated canary Ingress, after which Argo recreated it with the destination Rollout UID and preserved the stable Ingress UID.

| Observed state | HTTP with `X-Canary: always` | HTTP with `X-Canary: never` |
| --- | --- | --- |
| Before the simulated restore | Green canary | Blue stable |
| Generated canary Ingress absent | Blue stable | Blue stable |
| After Argo recreated the canary Ingress | Green canary | Blue stable |

The fixture simulated the stale reference and briefly paused the Argo controller to measure traffic while the object was absent. The replay covers the controller and NGINX HTTP behavior in that cluster. A full Velero restore was outside the replay. Both documentation revisions built, and the candidate's NGINX reconciler tests passed.

- Base `8c9c5ad2182ba7757bb6a35e79d2051afc31feee` and candidate `7d64fd23f32237314b498053688c32fc29b1fdbd`.
- Commands and pinned versions in the [replay script](https://github.com/archit15singh/autonomous-delivery-loop/blob/b42d8f6734f95f6b1401d3dd34c623e4f3b95fba/verification/argo-4837.sh). [Hosted job](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44867542476/job/136734486497). [Raw evidence](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44867542476/artifacts/14692149489).
