# Factory operations

The factory uses the existing Codex executor and the upstream action ledger. The new commands add evidence checks, trusted workflow steps, and an owned staging publisher. Run them from the checkout containing the reviewed factory code.

## Verify the judge and classify failures

```sh
python3 -m delivery factory self-check
python3 -m delivery factory classify head-checks.json base-checks.json
python3 -m delivery factory --output .adl/upstream-ci/portfolio.json portfolio \
  .adl/upstream-ci/current.json .adl/upstream-ci/actions.json
```

The control suite drives the actual HTTP verifier with positive and negative observations. For CI comparisons, provide two independent check receipts with `revision`, `environment`, `complete` and `failures`. The head receipt also gives `base`. Each failure has `check`, `test`, and a stable `signature` from the trusted check output. Match environment and baseline identity before attributing a failure. Partial log coverage leaves the result inconclusive.

The portfolio combines current CI, reviews, proposals, uncertain pushes and merge information. Supply `--evidence` with an array of evidence entries carrying `pr` and exact `head` to attach reproduction, control, or browser artifacts. Use `adoption events.json` for an append-log export. Each entry names `subject`, exact `revision`, an ISO timestamp with timezone in `at`, and an `event` from proposed, verified, published, merged, declined, reverted, released.

## Route work and pass evidence across roles

```sh
python3 -m delivery factory intake issue-facts.json --github-issue https://github.com/OWNER/REPO/issues/123
python3 -m delivery factory handoff pr-record.json findings.json
```

Record contributor policy, scope, reproduction, and an `acceptance` object with `expected`, `control`, and `boundary`. Provide `policy_checked` and `scope_agreed` booleans. The live option rechecks PR links, issue state, and assignment before scheduling. Keep maintainer-owned requirements and broader duplicate searches in the intake facts. Each review finding carries a head, disposition, and reproduction if confirmed. Use the generated handoff when a second Codex pass is warranted.

The reviewed outcome contract accepts the same three optional examples as strings. Codex receives them alongside the executable probes. Use `delivery propose --recipe-output FILE` to record the exact model, CLI version, skill digest, reviewed contract digest, time budget, and sandbox settings with its patch and event log.

## Run a pinned workflow

```sh
python3 -m delivery factory workflow plan.json --repo /path/to/checkout \
  --state .adl/factory-run --tier full
```

A trusted plan has `version: 1`, an exact `revision`, and ordered `steps`. A step has a unique `id`, a `kind` of `command` or `approval`, and a minimum `tier` of fast, full, or deep. Commands use an `argv` array, optional `timeout`, and optional `test_count_pattern` with one count capture. Declare any output files in `artifacts` and deterministic repeatability with `retry_safe: true`. Use `pin` for tool locks and skill files inside the checkout and `recipes` for model, skill, and budget declarations. Only operator-reviewed plans may supply commands.

The runner records platform, interpreter and Git versions. A matching workflow can reuse successful logs and declared artifact digests. It distinguishes approval, product failure, infrastructure failure, and uncertain interrupted effects. A retry-safe step has separate product and infrastructure ceilings. Use fast checks in the edit loop and deeper stages for wider changes. For caching expensive setup, use the environment and pinned file digests as dependency cache inputs. The runner checks the Git revision after each command. A clean commit change fails the step and stops the plan. Checkpoints created before this guard must be started again. Resume and approval always require the exact original plan and revision. At a pause, save the emitted `approval_request` object to an operator-controlled file and pass it as `--approval`. A changed revision or plan requires a new review.

For merge collisions, run `factory merge-preview --base SHA --candidate SHA` in the owned repository. It computes the combined Git tree and reports conflicts without moving a branch. Create a temporary commit from that tree and run an independent test plan on that exact checkout before deciding to merge overlapping changes.

## Browser proof and live rollout evidence

Use `node verification/browser-proof.mjs SPEC OUTPUT PLAYWRIGHT_MODULE BROWSER` with a pinned Playwright Core module and a local Chromium binary. The spec has two loopback deployments in `before` and `after` with `origin`, `revision`, and `deployment`. Supply `primary` and `control` scenarios with a URL `path`, a list of click or fill steps, and an `assert` containing selector and expected before/after text. Serve `/_revision` from each deployment. The command writes four screenshots, console results, and image digests. Include them as declared workflow artifacts. [Playwright browser API](https://playwright.dev/docs/api/class-browsertype)

For Argo, export the real AnalysisRun with a read-only Kubernetes identity and run `factory analysis RUN.json --contract CONTRACT --revision SHA --deployment ID --uid UID`. The run must be annotated with `adl/revision` and `adl/deployment`. The reviewed impact contract supplies the metric and observation floor. A completed run with matching identity and sufficient observations can verify the threshold. An unavailable or incomplete observation remains inconclusive. Use this adapter when a deployment has an Argo AnalysisRun.

## Pinned evals and evidence-backed publication

`factory benchmark --frozen evals/frozen.json` validates a six-issue manifest. Three cases use the Codex issue grader and three use exact upstream acceptance replays. Use the existing independent runners for the appropriate case class. For paired comparisons pass `--trials results.json` with `round`, `case`, `variant`, `verified`, `seconds`, `tokens` and `interventions`. Use `baseline` and `candidate` as variants. You can select an exact cohort using repeated `--case`. Promotion needs two complete paired rounds, preserved quality, and replicated efficiency gains.

The main-owned trusted judge emits a verified manifest with the contract, artifact, exact candidate, and policy revision. A separate GitHub Actions job attests that manifest. Run `factory publish MANIFEST --candidate SHA --contract pilot` to validate it. Add `--apply` for an explicitly authorized push to the owned `factory/verified-<sha>` staging namespace. The publisher verifies signer workflow identity and the current main policy, checks allowed changes, creates an immutable staging reference, and reads it back. An exact repeat returns the same result. The action ledger still governs the upstream PR workflow and maintainer approval remains authoritative. [Attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations#verifying-artifact-attestations-with-the-github-cli)

## Record runs and find repeated failures

`factory record-run SPEC --runs .adl/factory-runs` indexes one immutable run.
Provide a stable `id`, full `head` and `factory_revision`, and timezone-aware
`finished_at`. Add `pr` for an upstream PR and `base` when recording a Codex
recipe's starting point. In `receipts`, map the available kinds to approved local
paths, relative to the spec. Kinds include `workflow`, `recipe`, `readiness`,
`runtime`, `pr`, `browser`, and `assessment`. `trace` optionally names a raw
Codex log that stays local. The index stores its digest. `metrics` may contain
wall seconds, tokens, USD cost, and human interventions under
`wall_seconds`, `tokens`, `cost_usd`, and `human_interventions`. Omit unmeasured
values.

An assessment binds `head` and `dimensions`. Each dimension records `state`
(`passed`, `failed`, or `unknown`), a stable `reason` key and an `evidence`
reference. Use `skill_adherence`, `test_redundancy`, and `retry_efficiency` for
reviewed assessments. Use observed evidence to distinguish a missing required skill
from an unavailable transcript. An assessment supplies diagnostic evidence. It
cannot turn failed acceptance checks into a verified run.

```sh
python3 -m delivery factory --output .adl/upstream-ci/portfolio.json portfolio \
  .adl/upstream-ci/current.json .adl/upstream-ci/actions.json --runs .adl/factory-runs
python3 -m delivery factory --output .adl/factory-improvements.json mine-runs --runs .adl/factory-runs
```

The portfolio includes the indexed receipts for the exact PR head. The miner needs
two distinct runs with the same factory cause before emitting a stable proposal.
Runner outages do not count as factory defects. Start from the linked evidence and
reproduce against the old factory revision. Test the same behavior against the
proposed revision and preserve a held-out normal case. Keep the resulting factory
PR and later observation separate from the original application PR.

For UI changes, set `readiness.browser_required` in the reviewed upstream
contract and pass `--browser-proof PATH/browser.json` to `upstream-prepare`.
It checks both revisions, all four scenario outcomes, and the screenshot digests.
The preparation gate packages the artifacts alongside the generated PR body.
Upload the bundle to the PR's approved evidence destination.

Set `--runs .adl/factory-runs --pr PR_URL` on `upstream-prepare` to index the
readiness and browser receipts as part of verification. For other producers,
drop reviewed specifications in a private spool and pass `--spool DIR` to
`mine-runs`. A repeated scan retains each immutable run once.

## Replay a factory change and observe release events
```sh
python3 -m delivery factory --output .adl/replay.json replay-change \
  --baseline OLD_SHA --candidate FIXED_SHA \
  --contract contracts/factory/workflow-identity.json --logs .adl/replay-logs
python3 -m delivery factory lifecycle \
  --repository OWNER/REPO --environment hosted-staging
```

The replay executes a reviewed, digest-pinned driver against two detached factory
checkouts. It requires both a reproduced incident and a held-out control. Each
receipt lists the actual exit, behavior marker, elapsed time and log digest.
The workflow identity case came from the reported HEAD drift failure.

Lifecycle reads recent GitHub deployments and published release tags. Use
`--reverts FIRST LAST` to include first-parent Git revert messages from an exact
range. Mutable tags report their current resolution. A deployment status is
provider metadata and leaves runtime verification inconclusive. Revert messages
are historical declarations.

For a live Argo observation, use the existing `factory analysis` arguments for
the contract, candidate revision, deployment and UID, and supply
`--context CONTEXT --namespace NAMESPACE --name RUN` in place of a file. The
command performs one read through the configured kubeconfig. Use a read-only
Kubernetes identity and a reviewed runtime contract.

Use `factory measure-runs --runs .adl/factory-runs` to compare factory versions
on distinct verified changes, median wall time and known observation coverage.
Per-verified-change metrics include unsuccessful attempts in the numerator and
remain blank when a run is missing that metric. Read these reports alongside
the fixed-cohort benchmark before adopting a change. Use actual billed data
when putting USD amounts into a run spec.
