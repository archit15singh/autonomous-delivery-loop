# Runtime operations in the factory

ADL uses the same owned Redis API to verify a disposable Compose project and a Kubernetes namespace. The runbook also describes OpenTofu provisioning and read-only production diagnostics. Each target has its own identity, permissions, and evidence requirements. [Runtime runbook](factory-operations.md#run-the-disposable-redis-pilot)

## Fit with ADL today

The [issue dispatcher](factory-interfaces.md#owned-issue-pilot) approves a specific issue, contract, and base before Codex starts. The [workflow runner](factory-operations.md#run-a-pinned-workflow) pins commands and artifacts. The main-owned candidate workflow checks the approved contract in an isolated process, then runs the same service source against Redis in Compose. One command owns the Compose lifecycle. The signer receives a manifest only after both checks pass and Compose teardown is confirmed. The staging publisher demands this signed runtime evidence. [Outcome reporting](factory-interfaces.md#review-and-release-feedback) ties later release observations to a deployment and revision.

```text
Approved contract + exact candidate
  → trusted runtime step reserves the run and starts its Compose project
  → independent probes check behavior and deployment identity
  → fixed Redis readback confirms the backing state changed
  → diagnostics and bounded recovery if needed
  → remove the project's resources and confirm removal
  → bind the runtime and cleanup receipt into the staging manifest
```

## First runner

Use a dedicated Colima Docker profile with a fixed local socket, host mounts and SSH agent forwarding disabled, and automatic context switching off. Keep the VM available across runs and create a unique Compose project per run. Set CPU, memory, VM disk, process, and log limits. Start with one active stack and a preflight free-space check based on the image and build footprint. At the design snapshot, the Mac mini had about 178 MiB free and neither Colima nor Docker was on PATH. Host capacity and installation are prerequisites for the live Mac pilot. A disposable Linux CI runner can exercise the same stack and failure drills while that prerequisite is resolved. [Colima configuration](https://colima.run/docs/configuration/) · [Docker Compose project names](https://docs.docker.com/compose/how-tos/project-name/)

The approved plan chooses a named target and a reviewed Compose template from trusted main. It binds the template digest, candidate SHA, expected artifact digest, probe contract, and runtime limits. The trusted step resolves the target to the operator-configured socket and engine identity and rechecks it before writes. Use an explicit Compose project and file and a controlled process environment. Candidate code receives no daemon socket, host user-directory mount, production credential, or permission to alter the template. Build the artifact from the exact candidate with a reviewed recipe on the disposable runner. Pin fixture images by digest and use synthetic data. Expose the application probe on loopback only. Other services stay on the project's private network. [Docker Compose trust model](https://docs.docker.com/compose/trust-model/) · [Docker Engine security](https://docs.docker.com/engine/security/)

## One task for the runtime lifecycle

| Step | Behavior and evidence |
| --- | --- |
| Reserve | Use the existing durable ledgers and workflow state. Persist a unique project name and run identity before starting Compose. An orchestrator retry with the same reservation reconciles the actual resources before any further write. A different candidate, plan, or target needs a new reservation. |
| Provision and deploy | Start only the reviewed services. Wait with a deadline and collect the actual container IDs, image IDs, health results, and probe origin. A resource name alone does not establish ownership. Verify the target and the project and run ownership labels before mutating or deleting anything. |
| Investigate | Collect bounded logs, statuses, and health results from that project. Any in-container command uses an argv and service defined by reviewed policy, with its own timeout. Codex receives sanitized evidence and can propose an action. The trusted runner controls execution. |
| Verify and recover | The verifier matches the runtime identity to the trusted artifact and deployment record and runs the existing acceptance probes. Pin identity before and after the observation. Allow one reviewed, idempotent recovery attempt for an observed transient infrastructure failure. Preserve both receipts, collect diagnostics before restarting, and send product failures back to the candidate loop. |
| Clean up | Tear down this project's declared disposable resources in a finalizer. After interruption, a later reconciliation step claims the expired reservation and matches the current target and object identities before cleanup. Confirm absence before releasing the lease. Leave uncertain cleanup visible for an operator. Global prune and VM deletion require a separate operator action. |

Compose supplies bounded readiness and project-scoped teardown. ADL supplies behavior checks and verifies that cleanup actually happened. Store cleanup state separately from the probe verdict. A failed cleanup leaves the run unresolved and blocks promotion even when the probes passed. [Compose start options](https://docs.docker.com/reference/cli/docker/compose/up/) · [Compose teardown options](https://docs.docker.com/reference/cli/docker/compose/down/)

The runtime receipt binds the operator target, run and deployment IDs, policy revision, candidate, image and template digests, observation times, probe results, and diagnostic artifact hashes. The cleanup receipt records the project ownership check and whether its containers, networks, and volumes are absent. Index both with the existing run records. An approved run can place repeatable local operations inside the existing workflow. An approval or an investigation requiring human judgment ends the current attempt and waits for a new operator-triggered run.

## Authority by target

Local disposable targets can grant the trusted runner start, inspect, approved exec, restart, and cleanup for resources it created. Send third-party workloads to throwaway CI runners when they need capabilities beyond this profile. Treat logs and workload output as evidence.

An owned cloud test target needs an explicit account and region, a run-specific resource scope, an expiry deadline, and an agreed spending limit. Keep plan and apply separate and bind approval to the exact plan and environment. A production target starts with read-only access. Production changes run through the existing deployment pipeline with a narrowly scoped identity. Review data migrations and other irreversible effects independently of application rollback.

## Delivery phases

| Phase | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1. Owned Compose pilot | One owned ADL API plus Redis, with an acceptance probe that exercises a real write and read through the API. Run it under one reviewed local runtime step. | Show the exact image passing the normal probe. Show a wrong revision and an unavailable dependency leaving the run unverified. Show a transient failure using at most one restart and an interrupted run being cleaned up on reconciliation. Keep a second project running to prove cleanup stays scoped. Repeat on the Mac mini once its runner preflight passes. |
| 2. Kubernetes runtime | Run on a disposable loopback kind cluster. Apply the reviewed API and Redis objects, wait for rollout, then inspect the running pod and issue a fixed Redis PING. Reuse the trusted HTTP verifier. | Deploy the current image, restore the explicitly chosen prior image, and verify the Redis counter survives the API rollback. Delete the recorded namespace UID and confirm the neighboring namespace survives. |
| 3. Cloud provisioning | Use OpenTofu with one reviewed resource per plan, explicit sandbox account and region, and independent create and destroy approvals. Start with the built-in provider in CI. Use one disposable AWS SSM parameter for the real provider. | Reject missing or stale approval. Apply the exact approved plan and confirm the resource exists, then destroy it and confirm absence under a fresh approval. The AWS path requires a configured sandbox and a scoped identity. |
| 4. Production onboarding | Use the read-only Kubernetes diagnostic command and the existing Argo and outcome-report adapters. A future target must identify its deployment pipeline, scoped identities and immutable image source, approval policy, rollback procedure, and telemetry. | Rehearse in owned non-production first. Verify every rollout and rollback on the exact deployment and target. Operator approval must cover the selected target and image. Keep externally visible actions, migrations, and persistent data recovery under their own policy. |

The existing Delivery evidence workflow continues to exercise Compose. Runtime operator evidence adds kind and local OpenTofu checks on disposable Linux runners. Operators can call these same commands from reviewed workflow steps. GitHub Actions receipts for these runs describe CI fixtures. A real cloud sandbox and a production environment each need their own authorization and verified observations.

## Sandbox handoff

The developer machine needs Git and an authenticated GitHub CLI for the hosted
path. Dispatch the exact candidate to the existing main-owned runtime verifier.
Collect the result by run ID and attempt, check the signed manifest and the
runtime and cleanup receipts, then return failures to the existing repair loop.
Keep each attempt's state for diagnosis. Publication remains a separate action.

The local path starts with one dedicated Linux VM on the Mac using containerd.
It will prove the same Redis-backed pilot with the existing HTTP contract and
backing-store readback. The hosted path remains available for independent
attestation when the local VM is unavailable.

Extend the pilot in three steps. Add a browser interaction backed by Redis and
SQLite, checking the worker's persisted result and retaining a screenshot.
Then route confirmed product failures to one host-local Codex attempt in a disposable checkout
with host authentication, an offline shell, and a fixed scope. Finally
import only the scope-checked patch, rerun the same workload in a fresh stack,
and retain both receipts. Infrastructure or cleanup failures stop the loop.
