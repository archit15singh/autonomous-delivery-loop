# Product runtime

Run a candidate from a second Git repository using the factory CLI. The operator selects an approved product base commit and the spec path in that commit. A coding agent supplies a candidate commit. The factory verifies ancestry, restricts the diff to the service source, and reads the contract and runtime settings from the base. Keep approval of the base and permission to operate the backend with the operator.

## Run a product

Use the factory checkout at a committed revision. The existing provenance check requires clean factory policy files. Run the following from that checkout with PRODUCT_REPO, BASE, and CANDIDATE set to the product repository path and the two full Git commit IDs.

```sh
python3 -m delivery factory runtime plan --backend lima --repo "$PRODUCT_REPO" \
  --spec runtime.json --base "$BASE" --revision "$CANDIDATE"

python3 -m delivery factory runtime run --backend lima --repo "$PRODUCT_REPO" \
  --spec runtime.json --base "$BASE" --revision "$CANDIDATE" --state .adl/catalog-1

python3 -m delivery factory runtime inspect --state .adl/catalog-1
python3 -m delivery factory runtime cleanup --state .adl/catalog-1
```

Use a fresh state directory per run. Keep it under operator control. The run owns creation, execution, observation and normal teardown in one invocation. Inspect reads the durable backend receipt without contacting the runtime. Cleanup reuses the backend recorded in that receipt and checks resource ownership. For Compose and Kubernetes, pass the same connection arguments to run and cleanup. Exit zero from run requires both a verified outcome and confirmed teardown. An interrupted run can leave a pending receipt. Inspect it and use cleanup to reconcile the original environment.

| Backend | Operator input and workload boundary |
| --- | --- |
| Compose | Select a local Docker engine with `--socket /var/run/docker.sock`. The candidate uses an internal network and a trusted relay exposes the contract probes on loopback. |
| Lima | Start the existing dedicated `adl-runtime` instance. API and judge share a loopback-only network namespace. The VM has host mounts and SSH forwarding disabled. |
| Kubernetes | Specify `--kubeconfig FILE --context kind-adl-NAME`. Use operator-trusted code in a disposable local cluster. Network egress depends on the cluster. The adapter uses a scoped namespace, a read-only source mount and a pinned interpreter. |

## Version 1 product specification

The complete standalone example is in [examples/catalog](../examples/catalog). Copy that directory's contents into a product Git repository and commit them. File paths in the specification start at the product repository root. Select a single Python standard-library service, an unprivileged port, CPU and memory limits, an outcome contract, a fixture and automatic cleanup. The factory copies the committed source bytes into a pinned Python runtime. The application reads ADL_HOST and PORT for binding and ADL_REVISION and ADL_DEPLOYMENT for the required JSON identity endpoint at /_revision.

The outcome contract names the service source as its sole allowed change and defines GET probes with exact expected JSON objects. The none fixture runs the service alone. The redis-counter fixture supplies ADL_REDIS_HOST and checks that the probes leave the Redis key adl:counter equal to 2. CPU and memory limits apply to the application. The operator-controlled backend sets limits for supporting services. Browser jobs, Kubernetes rollback and staged publication retain their existing pilot commands and contracts.

## Verification plan and replay

1. Resolve both Git commits and verify the scope, source, spec and contract identities without runtime access.
2. Run the catalog service in the selected backend. The trusted judge checks deployment identity before and after reading /catalog. Inspect the evidence and confirm teardown.
3. Commit a source-only regression that returns an empty catalog. Verify that the same reviewed contract rejects it and teardown still completes. A candidate edit to the contract must fail before runtime creation.

Run the positive and negative controls against Lima with the following command. It creates an independent product repository and two receipts in a new directory. The runtime-operator CI workflow also runs both controls on Compose and kind.

```sh
python3 verification/product-runtime-check.py lima .adl/catalog-replay
```

The receipts establish runtime behavior for the checked artifact and deployment. Product receipts carry no authority to publish a release. Package installation, multi-file builds, custom images and additional fixture types require explicit future runtime profiles.
