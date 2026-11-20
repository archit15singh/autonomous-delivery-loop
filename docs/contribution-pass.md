# Upstream contribution pass

First pass completed 2026-11-21. The [tool map](open-source-tool-map.md) defines the 108 repositories. Intake read the issue and pull request metadata for all 108. Deeper issue, policy, and duplicate checks focused on the shortlisted projects and related tools with testable issues. An intake result is a routing decision, and the default deferred rows still need issue-level review before a future contribution.

## Submissions

| Project | Base → candidate | Evidence |
| --- | --- | --- |
| [Herdr Core #350](https://github.com/herdrdev/herdr-core/pull/350) | `c7517808d64f06609e4ecf0db1757005373cc3a3` → `4c0d10b876d766bdb4bba4c62f217c91a28befe1` | The source returned a numeric `status_ms` while a remote subscription returned `null`. The new event field and mirror update made both return the same timestamp in two isolated macOS Core processes with a local SSH shim. Library suite 181 passed, 1 ignored. Rustfmt and native all-target Clippy passed. The stock integration fixture timed out before its assertion on the Mac. The PR includes the assertion for upstream CI. |
| [SWE-smith #258](https://github.com/SWE-bench/SWE-smith/pull/258) | `9b74ac08118a85c39c356802f7961893af73e07f` → `b832f1b89b181ec872c5f7358ba079888a8ec0b0` | The regression asserted that a Surefire `<<< ERROR!` method line must be classified as `FAILED`. Base reported `PASSED`. Candidate passed all 52 Java profile tests plus Ruff format and lint. The test used captured-format text and exercised the actual parser. |

ADL's candidate check verified ancestry and file scope for both full commit pairs. Each upstream PR links the original report and includes the verification limits. Maintainers control upstream review and merge.

## Routing decisions

| Repository | Open issues at intake | Open PRs at intake | Disposition |
| --- | ---: | ---: | --- |
| [aaif-goose/goose](https://github.com/aaif-goose/goose) | 364 | 121 | Deferred after intake. No issue selected. |
| [actions/attest](https://github.com/actions/attest) | 14 | 6 | Deferred after intake. No issue selected. |
| [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) | 7 | 0 | Deferred after intake. No issue selected. |
| [actions/download-artifact](https://github.com/actions/download-artifact) | 124 | 33 | External contributions closed during intake. [Contribution policy](https://github.com/actions/download-artifact#contributions) |
| [actions/runner](https://github.com/actions/runner) | 439 | 127 | Deferred after intake. No issue selected. |
| [actions/upload-artifact](https://github.com/actions/upload-artifact) | 224 | 40 | External contributions closed during intake. [Contribution policy](https://github.com/actions/upload-artifact#contributions) |
| [agentclientprotocol/agent-client-protocol](https://github.com/agentclientprotocol/agent-client-protocol) | 3 | 25 | Deferred after intake. No issue selected. |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | 58 | 71 | Deferred after intake. No issue selected. |
| [agentsmd/agents.md](https://github.com/agentsmd/agents.md) | 101 | 89 | Deferred after intake. No issue selected. |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | 1419 | 552 | Deferred after intake. No issue selected. |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | 2681 | 1357 | The issue thread confirms the model display fix has an existing PR. [#65231](https://github.com/anomalyco/opencode/issues/65231) · [#58264](https://github.com/anomalyco/opencode/pull/58264) |
| [argoproj/argo-cd](https://github.com/argoproj/argo-cd) | 3583 | 942 | Deferred after intake. No issue selected. |
| [argoproj/argo-rollouts](https://github.com/argoproj/argo-rollouts) | 507 | 193 | Existing patches cover duplicate scaling and missing dashboard namespaces. [#5184](https://github.com/argoproj/argo-rollouts/pull/5184) · [#5144](https://github.com/argoproj/argo-rollouts/pull/5144) |
| [argoproj/argo-workflows](https://github.com/argoproj/argo-workflows) | 1025 | 360 | Deferred after intake. No issue selected. |
| [astral-sh/uv](https://github.com/astral-sh/uv) | 2406 | 682 | Deferred after intake. No issue selected. |
| [braintrustdata/autoevals](https://github.com/braintrustdata/autoevals) | 15 | 44 | Existing fixes cover explicit None scorer overrides and absent JSON properties. [#267](https://github.com/braintrustdata/autoevals/pull/267) · [#263](https://github.com/braintrustdata/autoevals/pull/263) |
| [checkly/checkly-cli](https://github.com/checkly/checkly-cli) | 1 | 15 | Deferred after intake. No issue selected. |
| [cli/cli](https://github.com/cli/cli) | 1081 | 59 | External PRs require a help-wanted issue with acceptance criteria. No selected issue on this pass. [Contribution guide](https://github.com/cli/cli/blob/trunk/.github/CONTRIBUTING.md) |
| [cline/cline](https://github.com/cline/cline) | 940 | 864 | Deferred after intake. No issue selected. |
| [comet-ml/opik](https://github.com/comet-ml/opik) | 74 | 145 | Deferred after intake. No issue selected. |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | 346 | 527 | Existing fixes cover Markdown report escaping and JSON export. [#3673](https://github.com/confident-ai/deepeval/pull/3673) · [#3687](https://github.com/confident-ai/deepeval/pull/3687) |
| [cypress-io/cypress](https://github.com/cypress-io/cypress) | 1042 | 94 | Deferred after intake. No issue selected. |
| [dagger/dagger](https://github.com/dagger/dagger) | 147 | 128 | Workspace search fallback already has a PR. [#15113](https://github.com/dagger/dagger/pull/15113) |
| [devcontainers/cli](https://github.com/devcontainers/cli) | 247 | 91 | Deferred after intake. No issue selected. |
| [e2b-dev/E2B](https://github.com/e2b-dev/E2B) | 48 | 88 | Deferred after intake. No issue selected. |
| [earendil-works/pi](https://github.com/earendil-works/pi) | 237 | 42 | Deferred after intake. No issue selected. |
| [firecracker-microvm/firecracker](https://github.com/firecracker-microvm/firecracker) | 63 | 88 | Deferred after intake. No issue selected. |
| [fluxcd/flagger](https://github.com/fluxcd/flagger) | 327 | 90 | Deferred after intake. No issue selected. |
| [fluxcd/flux2](https://github.com/fluxcd/flux2) | 198 | 46 | Deferred after intake. No issue selected. |
| [github/gh-aw](https://github.com/github/gh-aw) | 635 | 21 | Community issue plans with maintainer-owned code PRs. [Contribution guide](https://github.com/github/gh-aw/blob/main/CONTRIBUTING.md) |
| [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | 462 | 267 | Deferred after intake. No issue selected. |
| [GoogleContainerTools/container-structure-test](https://github.com/GoogleContainerTools/container-structure-test) | 83 | 35 | Deferred after intake. No issue selected. |
| [grafana/grafana](https://github.com/grafana/grafana) | 2571 | 715 | Deferred after intake. No issue selected. |
| [grafana/k6](https://github.com/grafana/k6) | 657 | 119 | Existing fix for QUERY in browser metric tag matching. [#6706](https://github.com/grafana/k6/pull/6706) |
| [grafana/loki](https://github.com/grafana/loki) | 653 | 433 | Deferred after intake. No issue selected. |
| [grafana/tempo](https://github.com/grafana/tempo) | 75 | 80 | Deferred after intake. No issue selected. |
| [growthbook/growthbook](https://github.com/growthbook/growthbook) | 544 | 378 | Deferred after intake. No issue selected. |
| [gvisor/gvisor](https://github.com/gvisor/gvisor) | 500 | 679 | Deferred after intake. No issue selected. |
| [harbor-framework/harbor](https://github.com/harbor-framework/harbor) | 396 | 512 | Existing fixes cover Hugging Face sandbox upload and OpenCode trajectory capture. [#4411](https://github.com/harbor-framework/harbor/pull/4411) · [#4344](https://github.com/harbor-framework/harbor/pull/4344) |
| [harbor-framework/terminal-bench](https://github.com/harbor-framework/terminal-bench) | 289 | 274 | Deferred after intake. No issue selected. |
| [herdrdev/herdr](https://github.com/herdrdev/herdr) | 503 | 26 | Deferred after intake. No issue selected. |
| [herdrdev/herdr-app](https://github.com/herdrdev/herdr-app) | 530 | 219 | Deferred panel refresh freeze. The report lacks a repeatable trigger. [#1253](https://github.com/herdrdev/herdr-app/issues/1253) |
| [herdrdev/herdr-core](https://github.com/herdrdev/herdr-core) | 155 | 69 | Submitted the remote snapshot fix. [PR #350](https://github.com/herdrdev/herdr-core/pull/350) |
| [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) | 36 | 16 | Deferred after intake. No issue selected. |
| [in-toto/in-toto](https://github.com/in-toto/in-toto) | 48 | 23 | Deferred after intake. No issue selected. |
| [j178/prek](https://github.com/j178/prek) | 20 | 22 | Existing fix for misleading empty-diff output. [#3057](https://github.com/j178/prek/pull/3057) |
| [jaegertracing/jaeger](https://github.com/jaegertracing/jaeger) | 423 | 187 | Deferred after intake. No issue selected. |
| [kestra-io/kestra](https://github.com/kestra-io/kestra) | 354 | 267 | Deferred after intake. No issue selected. |
| [Kilo-Org/kilocode](https://github.com/Kilo-Org/kilocode) | 632 | 313 | Deferred after intake. No issue selected. |
| [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | 128 | 70 | Deferred after intake. No issue selected. |
| [kubernetes-sigs/kind](https://github.com/kubernetes-sigs/kind) | 201 | 54 | Deferred after intake. No issue selected. |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 355 | 124 | Deferred after intake. No issue selected. |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | 332 | 860 | Deferred after intake. No issue selected. |
| [microsoft/playwright](https://github.com/microsoft/playwright) | 33 | 20 | Deferred after intake. No issue selected. |
| [microsoft/SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live) | 5 | 56 | Deferred after intake. No issue selected. |
| [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) | 328 | 197 | Deferred after intake. No issue selected. |
| [moby/buildkit](https://github.com/moby/buildkit) | 756 | 114 | Deferred after intake. No issue selected. |
| [modelcontextprotocol/inspector](https://github.com/modelcontextprotocol/inspector) | 19 | 0 | Maintainer-owned code PRs. The catalog precedence issue already has cross-platform evidence. [#3021](https://github.com/modelcontextprotocol/inspector/issues/3021) · [Contribution guide](https://github.com/modelcontextprotocol/inspector/blob/main/CONTRIBUTING.md) |
| [modelcontextprotocol/modelcontextprotocol](https://github.com/modelcontextprotocol/modelcontextprotocol) | 75 | 49 | Deferred after intake. No issue selected. |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | 308 | 112 | Deferred after intake. No issue selected. |
| [modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk) | 306 | 393 | Deferred after intake. No issue selected. |
| [multi-swe-bench/multi-swe-bench](https://github.com/multi-swe-bench/multi-swe-bench) | 20 | 4 | Deferred after intake. No issue selected. |
| [nektos/act](https://github.com/nektos/act) | 173 | 121 | Existing fixes cover triggering actor and host architecture. [#6248](https://github.com/nektos/act/pull/6248) · [#6197](https://github.com/nektos/act/pull/6197) |
| [open-feature/flagd](https://github.com/open-feature/flagd) | 119 | 40 | Deferred after intake. No issue selected. |
| [open-feature/spec](https://github.com/open-feature/spec) | 33 | 17 | Deferred after intake. No issue selected. |
| [open-policy-agent/opa](https://github.com/open-policy-agent/opa) | 259 | 12 | Deferred after intake. No issue selected. |
| [open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector) | 631 | 80 | Deferred after intake. No issue selected. |
| [open-telemetry/opentelemetry-collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) | 769 | 330 | Deferred after intake. No issue selected. |
| [open-telemetry/semantic-conventions](https://github.com/open-telemetry/semantic-conventions) | 729 | 41 | Deferred after intake. No issue selected. |
| [openai/codex](https://github.com/openai/codex) | 27960 | 160 | Issue reports and analysis only. [Contribution guide](https://github.com/openai/codex/blob/main/docs/contributing.md) |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | 32 | 19 | Deferred after intake. No issue selected. |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 633 | 585 | Deferred after intake. No issue selected. |
| [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) | 362 | 457 | The remote sender contract awaits a product decision. Existing patch covers missing terminal timeout. [#7004](https://github.com/OpenHands/software-agent-sdk/issues/7004) · [#6987](https://github.com/OpenHands/software-agent-sdk/pull/6987) |
| [opensandbox-group/OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) | 111 | 106 | Deferred after intake. No issue selected. |
| [pact-foundation/pact-cli](https://github.com/pact-foundation/pact-cli) | 3 | 3 | Deferred after intake. No issue selected. |
| [pact-foundation/pact-python](https://github.com/pact-foundation/pact-python) | 9 | 4 | Deferred after intake. No issue selected. |
| [podman-container-tools/podman](https://github.com/podman-container-tools/podman) | 885 | 132 | Deferred after intake. No issue selected. |
| [PostHog/posthog](https://github.com/PostHog/posthog) | 3375 | 1066 | Deferred after intake. No issue selected. |
| [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) | 56 | 71 | Deferred after intake. No issue selected. |
| [prometheus/prometheus](https://github.com/prometheus/prometheus) | 527 | 606 | Deferred after intake. No issue selected. |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | 167 | 842 | Existing fixes cover invalid CSV encoding and max-only tool counts. [#12527](https://github.com/promptfoo/promptfoo/pull/12527) · [#12405](https://github.com/promptfoo/promptfoo/pull/12405) |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 1356 | 502 | Deferred after intake. No issue selected. |
| [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | 693 | 254 | Deferred after intake. No issue selected. |
| [pytest-dev/pytest-xdist](https://github.com/pytest-dev/pytest-xdist) | 282 | 38 | Deferred after intake. No issue selected. |
| [QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) | 1937 | 552 | Deferred after intake. No issue selected. |
| [raine/workmux](https://github.com/raine/workmux) | 56 | 13 | Existing fixes cover the GitLab deprecation warning and nested worktree attribution. [#363](https://github.com/raine/workmux/pull/363) · [#359](https://github.com/raine/workmux/pull/359) |
| [reviewdog/reviewdog](https://github.com/reviewdog/reviewdog) | 119 | 15 | Deferred after intake. No issue selected. |
| [rhysd/actionlint](https://github.com/rhysd/actionlint) | 159 | 64 | Existing fixes cover the final JSONL record and string input to join. [#769](https://github.com/rhysd/actionlint/pull/769) · [#771](https://github.com/rhysd/actionlint/pull/771) |
| [scaleapi/SWE-bench_Pro-os](https://github.com/scaleapi/SWE-bench_Pro-os) | 40 | 16 | Deferred after intake. No issue selected. |
| [schemathesis/schemathesis](https://github.com/schemathesis/schemathesis) | 6 | 16 | Maintainer chose to own the phase statistics fix. [#5739](https://github.com/schemathesis/schemathesis/pull/5739) |
| [sigstore/cosign](https://github.com/sigstore/cosign) | 114 | 34 | Deferred after intake. No issue selected. |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 46 | 103 | Existing fixes cover blank inspector pages and unknown subcommand exit status. [#1028](https://github.com/SWE-agent/mini-swe-agent/pull/1028) · [#1024](https://github.com/SWE-agent/mini-swe-agent/pull/1024) |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | 69 | 143 | Deferred after intake. No issue selected. |
| [SWE-bench/sb-cli](https://github.com/SWE-bench/sb-cli) | 24 | 2 | Prior upstream submission. [#39](https://github.com/SWE-bench/sb-cli/pull/39) |
| [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench) | 34 | 39 | Prior upstream submission. [#726](https://github.com/SWE-bench/SWE-bench/pull/726) |
| [SWE-bench/swe-bench-tasks](https://github.com/SWE-bench/swe-bench-tasks) | 15 | 3 | Prior upstream submission. [#26](https://github.com/SWE-bench/swe-bench-tasks/pull/26) |
| [SWE-bench/SWE-smith](https://github.com/SWE-bench/SWE-smith) | 21 | 13 | Submitted the Maven parser fix. [PR #258](https://github.com/SWE-bench/SWE-smith/pull/258) |
| [tektoncd/pipeline](https://github.com/tektoncd/pipeline) | 463 | 110 | Deferred after intake. No issue selected. |
| [temporalio/temporal](https://github.com/temporalio/temporal) | 504 | 570 | Deferred after intake. No issue selected. |
| [testcontainers/testcontainers-go](https://github.com/testcontainers/testcontainers-go) | 129 | 96 | Deferred after intake. No issue selected. |
| [testcontainers/testcontainers-python](https://github.com/testcontainers/testcontainers-python) | 143 | 57 | Existing fix for status predicates handling accepted HTTP errors. [#1144](https://github.com/testcontainers/testcontainers-python/pull/1144) |
| [tox-dev/tox](https://github.com/tox-dev/tox) | 2 | 3 | Existing fix for TOML table references. [#4452](https://github.com/tox-dev/tox/pull/4452) |
| [triggerdotdev/trigger.dev](https://github.com/triggerdotdev/trigger.dev) | 206 | 63 | Deferred after intake. No issue selected. |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) | 405 | 130 | Accepted issues for missing CSV ids and seed-zero replay already have fixes under review. [#6382](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6382) · [#6388](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6388) |
| [Unleash/unleash](https://github.com/Unleash/unleash) | 24 | 26 | Deferred after intake. No issue selected. |
| [wandb/weave](https://github.com/wandb/weave) | 101 | 59 | Deferred after intake. No issue selected. |
| [woodpecker-ci/woodpecker](https://github.com/woodpecker-ci/woodpecker) | 267 | 111 | Deferred after intake. No issue selected. |
| [zed-industries/zed](https://github.com/zed-industries/zed) | 2287 | 791 | Deferred after intake. No issue selected. |
