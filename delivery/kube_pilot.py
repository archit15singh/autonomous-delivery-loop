"""Operate the owned pilot in a disposable Kubernetes namespace."""
from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path
import re
import select
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4

from .candidate import FULL_REVISION
from .compose_pilot import CONTRACT, DOCKER_ERRORS, ROOT, now
from .factory_definition import running_definition
from .factory_workflow import lock, record
from .lima_pilot import PYTHON
from .verify import Contract, verify

NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
CONTEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,252}")
NAMESPACE = re.compile(r"adl-run-[a-f0-9]{16}")
DIGEST = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}")
REDIS = "redis@sha256:1273af45b299d2b8b60d0e400d90aa6c2c5b1794f01d6a7ca60ff3ba6e65efb5"


class Kubectl:
    def __init__(self, config, context):
        if not CONTEXT.fullmatch(context):
            raise ValueError("select an explicit Kubernetes context")
        self.command = ["kubectl", "--kubeconfig", str(config.resolve(strict=True)), "--context", context]

    def call(self, *args, namespace=None, payload=None, timeout=22):
        command = [*self.command, "--request-timeout=15s"]
        if namespace:
            command += ["--namespace", namespace]
        result = subprocess.run([*command, *args], input=payload, text=True, capture_output=True, timeout=timeout)
        if result.returncode:
            raise ValueError(f"kubectl {args[0]} failed: {result.stderr[-3000:]}")
        return result.stdout

    def get(self, *args, namespace=None):
        raw = self.call("get", *args, "-o", "json", namespace=namespace)
        return json.loads(raw) if raw.strip() else None


def diagnostics(kube, namespace, deployment):
    if not NAME.fullmatch(namespace) or not NAME.fullmatch(deployment):
        raise ValueError("select an explicit namespace and deployment")
    workload = kube.get("deployment", deployment, namespace=namespace)
    selector = workload["spec"]["selector"].get("matchLabels", {})
    report = {"deployment": workload["metadata"]["uid"], "observed_at": now(),
              "generation": workload["metadata"]["generation"], "status": workload.get("status", {}),
              "images": [c["image"] for c in workload["spec"]["template"]["spec"]["containers"]]}
    if selector:
        pods = kube.get("pods", "-l", ",".join(f"{k}={v}" for k, v in sorted(selector.items())), namespace=namespace)
        report["pods"] = [{"name": x["metadata"]["name"], "status": x.get("status", {})}
                          for x in pods.get("items", [])[:20]]
    events = kube.get("events", "--field-selector", f"involvedObject.name={deployment}", namespace=namespace)
    report["events"] = [x.get("message", "") for x in events.get("items", [])[-20:]]
    try:
        report["logs"] = kube.call("logs", f"deployment/{deployment}", "--tail=25",
                                   "--limit-bytes=8192", namespace=namespace)
    except DOCKER_ERRORS as exc:
        report["log_error"] = str(exc)
    return report


def manifests(namespace, image, revision, product=None):
    def deployment(name, container):
        labels = {"app": name}
        return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name},
                "spec": {"selector": {"matchLabels": labels},
                         "template": {"metadata": {"labels": labels},
                                      "spec": {"automountServiceAccountToken": False, "containers": [container]}}}}

    def container(name, ref, port):
        return {"name": name, "image": ref, "ports": [{"containerPort": port}],
                "resources": {"requests": {"cpu": "25m", "memory": "16Mi"},
                              "limits": {"cpu": "500m", "memory": "96Mi"}},
                "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}}

    redis = container("redis", REDIS, 6379)
    redis.update(args=["redis-server", "--save", "", "--appendonly", "no"],
                 readinessProbe={"exec": {"command": ["redis-cli", "ping"]}, "periodSeconds": 1})
    redis["securityContext"].update(runAsUser=999, runAsNonRoot=True)
    port = product.port if product else 8080
    api = container("api", image, port)
    api.update(imagePullPolicy="Never" if image.startswith("adl-kube:") else "IfNotPresent",
               readinessProbe={"httpGet": {"path": "/health", "port": 8080}, "periodSeconds": 1},
               env=[{"name": key, "value": value} for key, value in
                    (("ADL_REVISION", revision), ("ADL_DEPLOYMENT", namespace), ("ADL_REDIS_HOST", "redis"))])
    service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "redis"},
               "spec": {"selector": {"app": "redis"}, "ports": [{"port": 6379}]}}
    items = []
    if not product or product.redis:
        items.extend([service, deployment("redis", redis)])
    workload = deployment("api", api)
    if product:
        # Project the reviewed Git bytes directly into the pod, inside a read-only mount.
        items.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "product-source"},
                      "immutable": True, "binaryData": {"service.py": b64encode(product.source).decode("ascii")}})
        workload["spec"]["template"]["spec"]["volumes"] = [
            {"name": "source", "configMap": {"name": "product-source"}}
        ]
        api.update(command=["python", "-I", "-B", "/product/service.py"],
                   volumeMounts=[{"name": "source", "mountPath": "/product", "readOnly": True}],
                   readinessProbe={"tcpSocket": {"port": port}, "periodSeconds": 1})
        api["securityContext"].update(runAsUser=65534, runAsNonRoot=True, readOnlyRootFilesystem=True)
        api["resources"]["limits"] = {"cpu": str(product.cpu_limit), "memory": f"{product.memory_mb}Mi"}
        if not product.redis:
            api["env"] = [env for env in api["env"] if env["name"] != "ADL_REDIS_HOST"]
        api["env"].extend({"name": key, "value": value} for key, value in
                          (("HOST", "0.0.0.0"), ("ADL_HOST", "0.0.0.0"),
                           ("PORT", str(port)), ("ADL_PORT", str(port))))
    return {"apiVersion": "v1", "kind": "List", "items": [*items, workload]}


def ownership(kube, receipt):
    if kube.get("namespace", "kube-system")["metadata"]["uid"] != receipt["cluster"]:
        raise ValueError("Kubernetes cluster identity changed")
    namespace = receipt["deployment"]
    if not NAMESPACE.fullmatch(namespace):
        raise ValueError("invalid disposable namespace")
    item = kube.get("namespace", namespace, "--ignore-not-found")
    if item:
        meta = item["metadata"]
        if (meta.get("labels", {}).get("adl.run") != namespace
                or receipt.get("namespace_uid", meta["uid"]) != meta["uid"]):
            raise ValueError("namespace ownership changed")
    return item


def cleanup(kube, receipt):
    try:
        item = ownership(kube, receipt)
        if item:
            options = {"apiVersion": "v1", "kind": "DeleteOptions",
                       "preconditions": {"uid": item["metadata"]["uid"]}}
            kube.call("delete", f"--raw=/api/v1/namespaces/{receipt['deployment']}", "-f", "-",
                      payload=json.dumps(options))
            kube.call("wait", "--for=delete", f"namespace/{receipt['deployment']}",
                      "--timeout=75s", timeout=85)
        if ownership(kube, receipt):
            raise ValueError("namespace still exists")
        return {"status": "confirmed"}
    except DOCKER_ERRORS as exc:
        return {"status": "unconfirmed", "error": str(exc)}


def probe(kube, receipt, contract, port=8080):
    namespace = receipt["deployment"]
    pods = [pod for pod in kube.get("pods", "-l", "app=api", namespace=namespace)["items"]
            if not pod["metadata"].get("deletionTimestamp")]
    if len(pods) != 1:
        raise ValueError("expected one API pod")
    pod = pods[0]
    image = pod["status"]["containerStatuses"][0]["imageID"]
    if pod["spec"]["containers"][0]["image"] != receipt["image"] or "sha256:" not in image:
        raise ValueError("API pod image identity is unavailable")
    with subprocess.Popen([*kube.command, "-n", namespace, "port-forward", "--address=127.0.0.1",
                           f"pod/{pod['metadata']['name']}", f":{port}"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True) as forward:
        try:
            ready, _, _ = select.select([forward.stdout], [], [], 10)
            line = forward.stdout.readline() if ready else ""
            match = re.fullmatch(rf"Forwarding from (127\.0\.0\.1:\d+) -> {port}\s*", line)
            if not match:
                raise ValueError("API port forward did not start")
            revision = receipt["revision"]
            report = verify(contract, f"http://{match[1]}", revision, namespace,
                            {"status": "passed", "revision": revision, "deployment": namespace,
                             "source": "kubernetes_rollout"})
            observed = kube.get("pod", pod["metadata"]["name"], namespace=namespace)
            if (observed["metadata"]["uid"] != pod["metadata"]["uid"]
                    or observed["status"]["containerStatuses"][0]["imageID"] != image):
                raise ValueError("API pod changed during verification")
            return report, image
        finally:
            forward.terminate()
            try:
                forward.wait(timeout=3)
            except subprocess.TimeoutExpired:
                forward.kill()


def rollout(kube, namespace, name):
    kube.call("rollout", "status", f"deployment/{name}", "--timeout=60s", namespace=namespace, timeout=68)


def wait_for_redis_service(kube, namespace):
    # Redis readiness only proves the local socket. Check DNS and the Service from the API pod.
    command = (
        "import socket, time\n"
        "deadline = time.monotonic() + 20\n"
        "while True:\n"
        "    try:\n"
        "        with socket.create_connection(('redis', 6379), timeout=2) as connection:\n"
        "            connection.sendall(b'PING\\r\\n')\n"
        "            with connection.makefile('rb') as response:\n"
        "                reply = response.readline(256)\n"
        "        if reply != b'+PONG\\r\\n':\n"
        "            raise ValueError(repr(reply))\n"
        "        print('PONG')\n"
        "        break\n"
        "    except (OSError, ValueError):\n"
        "        if time.monotonic() >= deadline:\n"
        "            raise\n"
        "        time.sleep(1)\n"
    )
    return kube.call("exec", "deployment/api", "--", "python", "-c", command,
                     namespace=namespace, timeout=32).strip()


def run(config, context, state, revision=None, image=None, *, retry=False, cleanup_only=False,
        rollback_revision=None, product=None):
    if product:
        if cleanup_only or image or rollback_revision or (retry and not product.redis):
            raise ValueError("product runs build from reviewed source; image, rollback, cleanup, and HTTP-only retry are unsupported")
        if revision and revision != product.revision:
            raise ValueError("product revision differs from the requested revision")
        if len(product.source) > 1024 * 1024:
            raise ValueError("Kubernetes product source exceeds the 1 MiB ConfigMap limit")
        revision, image = product.revision, PYTHON
    kube = Kubectl(config, context)
    selected = json.loads(kube.call("config", "view", "--minify", "-o", "json"))
    endpoint = urlsplit(selected["clusters"][0]["cluster"]["server"])
    if not context.startswith("kind-adl-") or endpoint.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("pilot writes require an owned, loopback kind-adl-* cluster")
    state = state.resolve()
    path = state / "runtime.json"
    with lock(state):
        if cleanup_only:
            receipt = json.loads(path.read_text())
            if receipt["cleanup"]["status"] != "confirmed":
                receipt["cleanup"] = cleanup(kube, receipt)
                record(path, receipt)
            return receipt
        if path.exists():
            raise ValueError("use a new state directory or reconcile the existing run")
        if not FULL_REVISION.fullmatch(revision or ""):
            raise ValueError("provide the full candidate revision")
        local = context.startswith("kind-adl-") and image == f"adl-kube:{revision}"
        if not local and not DIGEST.fullmatch(image or ""):
            raise ValueError("provide an immutable image digest or use an owned kind pilot cluster")
        if rollback_revision and (not FULL_REVISION.fullmatch(rollback_revision) or rollback_revision == revision):
            raise ValueError("select a different full revision for the disposable rollback rehearsal")
        policy = running_definition(ROOT)
        contract = product.contract if product else Contract.read(CONTRACT)
        ns = f"adl-run-{uuid4().hex[:16]}"
        payload = json.dumps(manifests(ns, image, revision, product))
        receipt = {"revision": revision, "deployment": ns, "image": image, "started_at": now(),
                   "cluster": kube.get("namespace", "kube-system")["metadata"]["uid"],
                   "context": context, "policy_revision": policy["revision"], "contract_sha256": contract.digest,
                   "manifest_sha256": sha256(payload.encode()).hexdigest(),
                   "verdict": "inconclusive", "reason": "interrupted", "cleanup": {"status": "pending"}}
        if product:
            receipt.update(product=product.identity, source_sha256=sha256(product.source).hexdigest())
        if ownership(kube, receipt):
            raise ValueError("pilot namespace already exists")
        record(path, receipt)
        try:
            raw = kube.call("create", "-f", "-", "-o", "json", payload=json.dumps({
                "apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns, "labels": {"adl.run": ns}}
            }))
            receipt["namespace_uid"] = json.loads(raw)["metadata"]["uid"]
            record(path, receipt)
            ownership(kube, receipt)
            kube.call("create" if product else "apply", "-f", "-", namespace=ns, payload=payload)
            if not product or product.redis:
                try:
                    rollout(kube, ns, "redis")
                except (ValueError, subprocess.TimeoutExpired) as exc:
                    if not retry or (isinstance(exc, ValueError) and "timed out waiting" not in str(exc)):
                        raise
                    receipt["before_retry"] = diagnostics(kube, ns, "redis")
                    record(path, receipt)
                    ownership(kube, receipt)
                    kube.call("rollout", "restart", "deployment/redis", namespace=ns)
                    rollout(kube, ns, "redis")
            rollout(kube, ns, "api")
            if not product or product.redis:
                receipt["redis_ping"] = wait_for_redis_service(kube, ns)
                if receipt["redis_ping"] != "PONG":
                    raise ValueError("Redis did not answer PING")
            observation, actual = probe(kube, receipt, contract, product.port if product else 8080)
            receipt.update(observation=observation, image_id=actual,
                           verdict=observation["verdict"], reason=observation["reason"])
            if product and product.redis and receipt["verdict"] == "verified":
                receipt["redis_counter"] = kube.call("exec", "deployment/redis", "--", "redis-cli",
                                                     "--raw", "GET", "adl:counter", namespace=ns).strip()
                if receipt["redis_counter"] != "2":
                    receipt.update(verdict="failed", reason="redis_readback_mismatch")
            if rollback_revision and receipt["verdict"] == "verified":
                ownership(kube, receipt)
                prior = {"revision": rollback_revision, "deployment": ns, "image": f"adl-kube:{rollback_revision}"}
                deployment = manifests(ns, prior["image"], rollback_revision)["items"][-1]
                kube.call("apply", "-f", "-", namespace=ns, payload=json.dumps(deployment))
                rollout(kube, ns, "api")
                wait_for_redis_service(kube, ns)
                rollback_contract = Contract.read(ROOT / "contracts/kube-rollback.json")
                rollback_report, previous_image = probe(kube, prior, rollback_contract)
                receipt["rollback"] = {"image_id": previous_image, "observation": rollback_report}
                if rollback_report["verdict"] != "verified":
                    receipt.update(verdict=rollback_report["verdict"], reason="rollback_unverified")
        except DOCKER_ERRORS as exc:
            receipt.update(verdict="inconclusive", reason="runtime_unavailable", error=str(exc))
        finally:
            try:
                if ownership(kube, receipt):
                    receipt["diagnostics"] = diagnostics(kube, ns, "api")
            except DOCKER_ERRORS as exc:
                receipt["diagnostics_error"] = str(exc)
            receipt["cleanup"] = cleanup(kube, receipt)
            if receipt["cleanup"]["status"] != "confirmed":
                receipt.update(verdict="inconclusive", reason="cleanup_unconfirmed")
            receipt["finished_at"] = now()
            record(path, receipt)
        return receipt
