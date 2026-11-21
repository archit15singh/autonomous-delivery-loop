#!/usr/bin/env bash
set -euo pipefail

source_dir=$1
output=$2
name=adl-argo-2958
namespace=header-replay
export KUBECONFIG="$RUNNER_TEMP/argo-2958-kubeconfig"
export EXAMPLE="$RUNNER_TEMP/alb-example.yaml"
awk '/^### Route to the canary by request header/{section=1} section && /^\x60\x60\x60yaml$/{block=1;next} block && /^\x60\x60\x60$/{exit} block{print}' \
  "$source_dir/docs/features/traffic-management/alb.md" > "$EXAMPLE"
test -s "$EXAMPLE"
fixture="$RUNNER_TEMP/alb-fixture.yaml"
yq '
  if .kind == "Ingress" then
    .metadata.name = "ingress" |
    .spec.rules[0].http.paths[0].backend.service.name = "stable-service"
  elif .kind == "Rollout" then
    .spec.replicas = 1 |
    .spec.strategy.canary.trafficRouting = load(strenv(EXAMPLE)).trafficRouting |
    .spec.strategy.canary.steps = load(strenv(EXAMPLE)).steps
  elif .kind == "Service" then
    .spec.ports[0].port = 80
  else . end
' "$source_dir/test/e2e/header-routing/alb-header-route.yaml" > "$fixture"

cleanup() {
  if [[ -n "${controller_pid:-}" ]]; then kill "$controller_pid" || true; fi
  kubectl -n "$namespace" get events,rollout,ingress,pod -o yaml > "$output/objects.yaml" || true
  kind delete cluster --name "$name"
}
trap cleanup EXIT
kind create cluster --name "$name" --wait 120s
kubectl apply --server-side -k "$source_dir/manifests/crds"
kubectl wait --for=condition=Established --timeout=45s crd/rollouts.argoproj.io
kubectl create namespace argo-rollouts
kubectl create namespace "$namespace"
"$RUNNER_TEMP/argo-rollouts-controller" --kubeconfig "$KUBECONFIG" --aws-verify-target-group=false > "$output/controller.log" 2>&1 &
controller_pid=$!
kubectl -n "$namespace" apply -f "$fixture"

for attempt in {1..75}; do
  if [[ "$(kubectl -n "$namespace" get rollout rollouts-demo -o jsonpath='{.status.phase}')" = Healthy ]]; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done
test "$(kubectl -n "$namespace" get rollout rollouts-demo -o jsonpath='{.status.phase}')" = Healthy
kubectl -n "$namespace" get ingress ingress -o json > "$output/before.json"
jq -e '.metadata.annotations | has("alb.ingress.kubernetes.io/actions.preview-header") | not' "$output/before.json"

kubectl -n "$namespace" patch rollout rollouts-demo --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"argoproj/rollouts-demo:blue"}]'
for attempt in {1..75}; do
  if kubectl -n "$namespace" get ingress ingress -o json | jq -e '.metadata.annotations."alb.ingress.kubernetes.io/actions.preview-header"' >/dev/null; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done
kubectl -n "$namespace" get ingress ingress -o json > "$output/matching.json"
jq -e '.metadata.annotations."alb.ingress.kubernetes.io/conditions.preview-header" | fromjson |
  any(.[]; .field == "http-header" and .httpHeaderConfig.httpHeaderName == "X-Preview" and .httpHeaderConfig.values == ["true"])' "$output/matching.json"
jq -e '.metadata.annotations."alb.ingress.kubernetes.io/actions.preview-header" | fromjson |
  .forwardConfig.targetGroups == [{serviceName:"canary-service",servicePort:"80",weight:100}]' "$output/matching.json"
jq -e 'any(.spec.rules[].http.paths[]; .backend.service.name == "preview-header")' "$output/matching.json"
kubectl -n "$namespace" patch rollout rollouts-demo --subresource=status --type=merge -p '{"status":{"pauseConditions":null}}'
for attempt in {1..45}; do
  if kubectl -n "$namespace" get ingress ingress -o json | jq -e '.metadata.annotations | has("alb.ingress.kubernetes.io/actions.preview-header") | not' >/dev/null; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done
kubectl -n "$namespace" get ingress ingress -o json > "$output/removed.json"
jq -e '.metadata.annotations |
  (has("alb.ingress.kubernetes.io/actions.preview-header") or has("alb.ingress.kubernetes.io/conditions.preview-header")) | not' "$output/removed.json"
jq -e 'any(.spec.rules[].http.paths[]; .backend.service.name == "preview-header") | not' "$output/removed.json"
printf 'The documented header route added X-Preview=true to the canary at weight 100 and removed it after promotion.\n'
