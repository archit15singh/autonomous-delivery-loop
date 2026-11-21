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
