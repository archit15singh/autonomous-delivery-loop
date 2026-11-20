# Open-source tools for the Codex delivery loop

Research snapshot · 2026-11-20

This inventory follows the workflow from coding and session recovery through evaluation, CI, deployment, and outcome measurement. It covers the projects most relevant to this work. The topic has no exhaustive registry. Repository identity, visibility, archive status, and license metadata were checked against GitHub. For mixed or ambiguous results, the notes link to the applicable license text. Tool descriptions come from upstream sources. The contribution themes are judgments about fit. Individual issues, competing PRs, and build requirements need a fresh check when a project is selected.

## Shortlist

| Pick | Project | Where your existing work carries over | Upstream route |
| --- | --- | --- | --- |
| 1 | Herdr Core | Terminal handoff, process state, and session recovery. Reproduce with an isolated Core process. | Focused code PRs with regression tests. Agent-specific hooks belong in the relevant integration. [Guide](https://github.com/herdrdev/herdr-core/blob/master/CONTRIBUTING.md) |
| 2 | Harbor | Run reproducible Codex evals and improve task, runner, or result handling. Strongest follow-on to the SWE-bench work. | Accepts external PRs and AI-assisted code. You write the first and final drafts of upstream communications, including the PR description, and disclose agent involvement. [Guide](https://github.com/harbor-framework/harbor/blob/main/CONTRIBUTING.md) |
| 3 | OpenCode | Compare agent behavior using your existing CLI, PTY, and TUI testing experience. | Link a bug-fix PR to an existing issue. UI and core features need design review. [Guide](https://github.com/anomalyco/opencode/blob/dev/CONTRIBUTING.md) |
| 4 | Schemathesis | Turn OpenAPI acceptance criteria into reproducible success and failure cases. | External PRs. [Guide](https://github.com/schemathesis/schemathesis/blob/master/CONTRIBUTING.md) |
| 5 | act | Improve local reproduction of GitHub Actions workflows and clarify differences between local and hosted runs. | External bug-fix PRs linked to issues. [Guide](https://github.com/nektos/act/blob/main/CONTRIBUTING.md) |
| 6 | Promptfoo | Extend eval comparisons, deterministic assertions, or result exports used by CI. | External code and docs PRs. [Guide](https://www.promptfoo.dev/docs/contributing) |
| 7 | OpenHands Software Agent SDK | Exercise session, event, and workspace boundaries using small integration fixtures. | External contributions. The SDK defines narrower intake criteria for model providers. [Guide](https://github.com/OpenHands/software-agent-sdk/blob/main/CONTRIBUTING.md) |
| 8 | Inspect AI | Work on testable scoring and run records with a reusable evaluation framework. | Most new contributors need a maintainer-accepted issue before coding. [Guide](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/CONTRIBUTING.md) |
| 9 | Dagger | Reproduce the same build and independent verification on a developer machine and in CI. | Claim an issue first and sign off commits under the DCO. [Guide](https://github.com/dagger/dagger/blob/main/CONTRIBUTING.md) |
| 10 | Argo Rollouts | Verify canary behavior with concrete pass, fail, and inconclusive cases. | External PRs. End-to-end verification requires a Kubernetes cluster. [Guide](https://github.com/argoproj/argo-rollouts/blob/master/docs/CONTRIBUTING.md) |
| 11 | Herdr App | Fix a reproducible macOS or Linux app regression. Extend the workflow with a standalone mod when the API supports it. | Focused PRs. Bundled layouts and mods take fixes only. [Guide](https://github.com/herdrdev/herdr-app/blob/master/CONTRIBUTING.md) |

## Contribution and licensing boundaries

- **Codex CLI** welcomes issue reports, root-cause analyses, and feedback. The team handles code changes internally. [Contribution guide](https://github.com/openai/codex/blob/main/docs/contributing.md)
- **GitHub Agentic Workflows** takes community contributions through issue plans. Core maintainers open the implementation PRs. [Contribution guide](https://github.com/github/gh-aw/blob/main/CONTRIBUTING.md)
- **GitHub artifact upload and download actions** currently decline external contributions. They remain useful dependencies for the delivery loop. [Upload](https://github.com/actions/upload-artifact#contributions) · [Download](https://github.com/actions/download-artifact#contributions)
- **OpenTelemetry Collector Contrib** allows AI-assisted code with human-written PR descriptions and discussion. [Contribution guide](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/CONTRIBUTING.md#ai-assisted-contributions)
- **Daytona** archived its public core after moving development private. **Phoenix** uses Elastic License 2.0 and **Sentry server** uses a Functional Source License. They are outside the open-source shortlist. [Daytona](https://github.com/daytonaio/daytona) · [Phoenix license](https://github.com/Arize-ai/phoenix/blob/main/LICENSE) · [Sentry license](https://github.com/getsentry/sentry/blob/master/LICENSE.md)
- The **SWE-bench tasks** repo is public and relevant to the prior PR. GitHub returned no repository-wide license for it. Check the applicable task and source repository terms before redistributing a task. [Task repository](https://github.com/SWE-bench/swe-bench-tasks)
- **SWE-bench Pro** below refers to Scale's open-source repository and public benchmark materials. The benchmark also has held-out and commercial splits. [Upstream repository](https://github.com/scaleapi/SWE-bench_Pro-os) · [Benchmark paper](https://arxiv.org/abs/2509.16941)

## Inventory

### Coding agents and local workflow

| Repository | Role | License |
| --- | --- | --- |
| [openai/codex](https://github.com/openai/codex) | Codex coding CLI and local agent runtime | Apache-2.0 |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | Terminal-first coding agent across model providers | MIT |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | Coding agent platform with a UI and execution environments | MIT |
| [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) | Python SDK for agents, tools, events, and workspaces | MIT |
| [earendil-works/pi](https://github.com/earendil-works/pi) | Extensible terminal agent, agent loop, and TUI toolkit | MIT |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | Compact issue-solving agent for comparable benchmark runs | MIT |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | Issue-solving agent and benchmark baseline | MIT |
| [cline/cline](https://github.com/cline/cline) | Coding assistant for editor, CLI, and SDK workflows | Apache-2.0 |
| [aaif-goose/goose](https://github.com/aaif-goose/goose) | Extensible coding and tool-using agent | Apache-2.0 |
| [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | Gemini terminal coding agent | Apache-2.0 |
| [QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) | Qwen terminal coding agent | Apache-2.0 |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | Terminal pair programmer with Git integration | Apache-2.0 |
| [Kilo-Org/kilocode](https://github.com/Kilo-Org/kilocode) | Coding agent for the editor and CLI | MIT |
| [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) | Mistral terminal coding agent | Apache-2.0 |
| [zed-industries/zed](https://github.com/zed-industries/zed) | Editor with coding-agent integration | [GPL-3.0-or-later with Apache-2.0 components](https://github.com/zed-industries/zed#licensing) |
| [j178/prek](https://github.com/j178/prek) | Git hook runner compatible with pre-commit configurations | MIT |
| [herdrdev/herdr](https://github.com/herdrdev/herdr) | Terminal multiplexer for coding agents | Apache-2.0 |
| [herdrdev/herdr-app](https://github.com/herdrdev/herdr-app) | Herdr desktop app, layouts, and mods | Apache-2.0 |
| [herdrdev/herdr-core](https://github.com/herdrdev/herdr-core) | Terminal process runtime and session state | Apache-2.0 |
| [raine/workmux](https://github.com/raine/workmux) | Git worktree and multiplexer workflow tool | MIT |

### Agent interoperability and orchestration

| Repository | Role | License |
| --- | --- | --- |
| [agentclientprotocol/agent-client-protocol](https://github.com/agentclientprotocol/agent-client-protocol) | Protocol connecting editors and agents | Apache-2.0 |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | Portable skill format and documentation | Apache-2.0 |
| [agentsmd/agents.md](https://github.com/agentsmd/agents.md) | Repository guidance format for coding agents | MIT |
| [modelcontextprotocol/modelcontextprotocol](https://github.com/modelcontextprotocol/modelcontextprotocol) | Tool and context interoperability specification | [MIT and Apache-2.0 transition](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/LICENSE) |
| [modelcontextprotocol/inspector](https://github.com/modelcontextprotocol/inspector) | Interactive and deterministic checking of MCP servers | [MIT and Apache-2.0 transition](https://github.com/modelcontextprotocol/inspector/blob/main/LICENSE) |
| [modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk) | TypeScript client and server SDK | [MIT and Apache-2.0 transition](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/LICENSE) |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Python client and server SDK | MIT |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | Python agent workflows, tools, and traces | MIT |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Stateful agent workflows and durable execution | MIT |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | Typed Python agent and evaluation framework | MIT |
| [temporalio/temporal](https://github.com/temporalio/temporal) | Durable workflow execution and resumption | MIT |
| [kestra-io/kestra](https://github.com/kestra-io/kestra) | Declarative orchestration and scheduling | Apache-2.0 |
| [triggerdotdev/trigger.dev](https://github.com/triggerdotdev/trigger.dev) | Durable background tasks and workflow orchestration | Apache-2.0 |

### Software engineering benchmarks

| Repository | Role | License |
| --- | --- | --- |
| [harbor-framework/harbor](https://github.com/harbor-framework/harbor) | Reproducible agent eval runs, tasks, and sandboxes | Apache-2.0 |
| [harbor-framework/terminal-bench](https://github.com/harbor-framework/terminal-bench) | Benchmark tasks for terminal agents | Apache-2.0 |
| [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench) | Grade code patches against real repository issues | MIT |
| [SWE-bench/swe-bench-tasks](https://github.com/SWE-bench/swe-bench-tasks) | Task definitions and evaluation fixtures | Public, see licensing note above |
| [SWE-bench/sb-cli](https://github.com/SWE-bench/sb-cli) | CLI for remotely submitting and retrieving benchmark results | MIT |
| [scaleapi/SWE-bench_Pro-os](https://github.com/scaleapi/SWE-bench_Pro-os) | Long-horizon software engineering benchmark code and public tasks | MIT |
| [SWE-bench/SWE-smith](https://github.com/SWE-bench/SWE-smith) | Generate software engineering tasks at scale | MIT |
| [multi-swe-bench/multi-swe-bench](https://github.com/multi-swe-bench/multi-swe-bench) | Multilingual repository issue benchmark | Apache-2.0 |
| [microsoft/SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live) | Continuously curated repository issues including multilingual and Windows tasks | MIT |

### Eval scoring and trace analysis

| Repository | Role | License |
| --- | --- | --- |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | CLI evaluation, regression assertions, and result comparisons | MIT |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) | Eval framework with task, solver, sandbox, and scorer APIs | MIT |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | Python evaluation metrics and test workflows | Apache-2.0 |
| [braintrustdata/autoevals](https://github.com/braintrustdata/autoevals) | Reusable evaluation scorers | MIT |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | Agent tracing and experiment evaluation | [MIT core + enterprise terms](https://github.com/langfuse/langfuse/blob/main/LICENSE) |
| [comet-ml/opik](https://github.com/comet-ml/opik) | Agent tracing, evaluation, and feedback | Apache-2.0 |
| [wandb/weave](https://github.com/wandb/weave) | Trace and evaluation toolkit | Apache-2.0 |
| [open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector) | Collect, process, and export telemetry | Apache-2.0 |
| [open-telemetry/semantic-conventions](https://github.com/open-telemetry/semantic-conventions) | Standard names and attributes for telemetry | Apache-2.0 |

### Independent software verification

| Repository | Role | License |
| --- | --- | --- |
| [microsoft/playwright](https://github.com/microsoft/playwright) | Cross-browser automation and end-to-end tests | Apache-2.0 |
| [cypress-io/cypress](https://github.com/cypress-io/cypress) | Browser and component tests | MIT |
| [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | Python testing framework | MIT |
| [pytest-dev/pytest-xdist](https://github.com/pytest-dev/pytest-xdist) | Parallel pytest execution | MIT |
| [tox-dev/tox](https://github.com/tox-dev/tox) | Reproducible test environments for Python projects | MIT |
| [schemathesis/schemathesis](https://github.com/schemathesis/schemathesis) | Property-based testing from API schemas | MIT |
| [pact-foundation/pact-python](https://github.com/pact-foundation/pact-python) | Python consumer-driven contract tests | MIT |
| [testcontainers/testcontainers-python](https://github.com/testcontainers/testcontainers-python) | Real service dependencies in Python integration tests | Apache-2.0 |
| [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) | Python property-based testing | [MPL-2.0](https://github.com/HypothesisWorks/hypothesis/blob/master/LICENSE.txt) |
| [astral-sh/uv](https://github.com/astral-sh/uv) | Python package resolution, locks, and environments | Apache-2.0 |
| [dagger/dagger](https://github.com/dagger/dagger) | Portable build, test, and delivery pipelines | Apache-2.0 |
| [testcontainers/testcontainers-go](https://github.com/testcontainers/testcontainers-go) | Real service dependencies in Go integration tests | MIT |
| [pact-foundation/pact-cli](https://github.com/pact-foundation/pact-cli) | CLI for contract testing operations | MIT |
| [GoogleContainerTools/container-structure-test](https://github.com/GoogleContainerTools/container-structure-test) | Verify container image contents and behavior | Apache-2.0 |
| [devcontainers/cli](https://github.com/devcontainers/cli) | Reproduce repository development environments from configuration | MIT |

### PRs, CI and artifacts

| Repository | Role | License |
| --- | --- | --- |
| [cli/cli](https://github.com/cli/cli) | GitHub CLI for PRs, checks, and workflow runs | MIT |
| [github/gh-aw](https://github.com/github/gh-aw) | Agent workflows compiled to GitHub Actions | MIT |
| [nektos/act](https://github.com/nektos/act) | Run GitHub Actions workflows locally | MIT |
| [rhysd/actionlint](https://github.com/rhysd/actionlint) | Static validation of GitHub Actions workflows | MIT |
| [actions/runner](https://github.com/actions/runner) | GitHub Actions job runner | MIT |
| [actions/upload-artifact](https://github.com/actions/upload-artifact) | Publish workflow artifacts | MIT |
| [actions/download-artifact](https://github.com/actions/download-artifact) | Retrieve workflow artifacts | MIT |
| [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) | Generate build provenance attestations | MIT |
| [reviewdog/reviewdog](https://github.com/reviewdog/reviewdog) | Publish tool findings into code review | MIT |
| [tektoncd/pipeline](https://github.com/tektoncd/pipeline) | Kubernetes-native CI/CD pipelines | Apache-2.0 |
| [sigstore/cosign](https://github.com/sigstore/cosign) | Sign and verify release artifacts and images | Apache-2.0 |
| [woodpecker-ci/woodpecker](https://github.com/woodpecker-ci/woodpecker) | Self-hosted CI pipelines | Apache-2.0 |
| [actions/attest](https://github.com/actions/attest) | Create GitHub artifact attestations | MIT |
| [in-toto/in-toto](https://github.com/in-toto/in-toto) | Record and verify software supply-chain steps | [Apache-2.0](https://github.com/in-toto/in-toto/blob/develop/LICENSE) |
| [moby/buildkit](https://github.com/moby/buildkit) | Build container images and produce build metadata | Apache-2.0 |
| [open-policy-agent/opa](https://github.com/open-policy-agent/opa) | Evaluate deterministic policy rules | Apache-2.0 |

### Execution, deployment and impact

| Repository | Role | License |
| --- | --- | --- |
| [e2b-dev/E2B](https://github.com/e2b-dev/E2B) | Sandbox infrastructure and SDK for isolated code execution | Apache-2.0 |
| [gvisor/gvisor](https://github.com/gvisor/gvisor) | Application kernel for stronger container isolation | Apache-2.0 |
| [podman-container-tools/podman](https://github.com/podman-container-tools/podman) | OCI container and pod runtime tooling | Apache-2.0 |
| [kubernetes-sigs/kind](https://github.com/kubernetes-sigs/kind) | Local Kubernetes clusters for integration testing | Apache-2.0 |
| [argoproj/argo-workflows](https://github.com/argoproj/argo-workflows) | Kubernetes-native workflow execution | Apache-2.0 |
| [argoproj/argo-rollouts](https://github.com/argoproj/argo-rollouts) | Canary and blue-green delivery with analysis gates | Apache-2.0 |
| [argoproj/argo-cd](https://github.com/argoproj/argo-cd) | GitOps deployment and application synchronization | Apache-2.0 |
| [fluxcd/flux2](https://github.com/fluxcd/flux2) | GitOps toolkit and Kubernetes reconciliation | Apache-2.0 |
| [prometheus/prometheus](https://github.com/prometheus/prometheus) | Metrics collection and queries | Apache-2.0 |
| [grafana/k6](https://github.com/grafana/k6) | Scriptable load tests and performance thresholds | AGPL-3.0 |
| [grafana/grafana](https://github.com/grafana/grafana) | Dashboards, queries, and alerting | AGPL-3.0 |
| [PostHog/posthog](https://github.com/PostHog/posthog) | Product analytics, feature flags, and experiments | [MIT core + enterprise terms](https://github.com/PostHog/posthog#open-source-vs-paid) |
| [growthbook/growthbook](https://github.com/growthbook/growthbook) | Feature flags and experiment analysis | [MIT core + enterprise terms](https://github.com/growthbook/growthbook/blob/main/LICENSE) |
| [Unleash/unleash](https://github.com/Unleash/unleash) | Feature management and rollout controls | AGPL-3.0 |
| [opensandbox-group/OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) | Sandbox interfaces, SDKs, and runtimes | Apache-2.0 |
| [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | Kubernetes primitives for agent execution environments | Apache-2.0 |
| [firecracker-microvm/firecracker](https://github.com/firecracker-microvm/firecracker) | MicroVM runtime | Apache-2.0 |
| [fluxcd/flagger](https://github.com/fluxcd/flagger) | Progressive delivery with metric gates | Apache-2.0 |
| [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) | Network and HTTP synthetic probes | Apache-2.0 |
| [open-feature/flagd](https://github.com/open-feature/flagd) | OpenFeature-compatible feature flag evaluation service | Apache-2.0 |
| [checkly/checkly-cli](https://github.com/checkly/checkly-cli) | Configuration and CLI for browser and API checks | Apache-2.0 |
| [open-telemetry/opentelemetry-collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) | Collector connectors, receivers, processors, and exporters | Apache-2.0 |
| [jaegertracing/jaeger](https://github.com/jaegertracing/jaeger) | Distributed trace storage and inspection | Apache-2.0 |
| [grafana/loki](https://github.com/grafana/loki) | Log aggregation and querying | AGPL-3.0 |
| [grafana/tempo](https://github.com/grafana/tempo) | Distributed tracing backend | AGPL-3.0 |
| [open-feature/spec](https://github.com/open-feature/spec) | Vendor-neutral feature flag evaluation specification | Apache-2.0 |
