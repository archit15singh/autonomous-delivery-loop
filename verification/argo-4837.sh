#!/usr/bin/env bash
set -euo pipefail

source_dir=$1
output=$2
name=adl-argo-4837
namespace=restore-replay
rollout=rollouts-demo
stable=rollouts-demo-stable
canary=rollouts-demo-rollouts-demo-stable-canary
export KUBECONFIG="$RUNNER_TEMP/argo-4837-kubeconfig"

cleanup() {
  if [[ -n "${controller_pid:-}" ]]; then kill "$controller_pid" || true; fi
  kubectl -n "$namespace" get events -o json > "$output/events.json" || true
  kubectl -n "$namespace" get rollout,ingress,pod -o yaml > "$output/objects.yaml" || true
  kind delete cluster --name "$name"
}
trap cleanup EXIT
kind version
kind create cluster --name "$name" --wait 120s
kubectl version
kubectl apply --server-side -k "$source_dir/manifests/crds"
kubectl wait --for=condition=Established --timeout=45s crd/rollouts.argoproj.io
kubectl create namespace argo-rollouts
kubectl create namespace "$namespace"
for manifest in services ingress rollout; do
  kubectl -n "$namespace" apply -f "$source_dir/docs/getting-started/nginx/$manifest.yaml"
done

"$RUNNER_TEMP/argo-rollouts-controller" --kubeconfig "$KUBECONFIG" > "$output/controller.log" 2>&1 &
controller_pid=$!
for attempt in {1..60}; do
  if kubectl -n "$namespace" get ingress "$canary" > /dev/null 2>&1; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done

rollout_uid() {
  kubectl get rollout "$rollout" -n "$namespace" -o jsonpath='{.metadata.uid}{"\n"}'
}
owner_uid() {
  kubectl get ingress "$canary" -n "$namespace" -o jsonpath='{.metadata.ownerReferences[?(@.controller==true)].uid}{"\n"}'
}
canary_uid() {
  kubectl get ingress "$canary" -n "$namespace" -o jsonpath='{.metadata.uid}'
}
stable_uid() {
  kubectl get ingress "$stable" -n "$namespace" -o jsonpath='{.metadata.uid}'
}

expected=$(rollout_uid)
original_canary=$(canary_uid)
original_stable=$(stable_uid)
test -n "$expected"
test "$(owner_uid)" = "$expected"
printf 'Initial generated Ingress owner matches the Rollout UID\n'

# Recreate a stale reference from a restore. The stable Ingress is a second
# live owner in the fixture so Kubernetes GC does not race this check.
stale=22222222-2222-4222-8222-222222222222
owners=$(jq -cn --arg rollout "$rollout" --arg stable "$stable" --arg stable_uid "$original_stable" --arg stale "$stale" '{
  metadata: {ownerReferences: [
    {apiVersion:"argoproj.io/v1alpha1",kind:"Rollout",name:$rollout,uid:$stale,controller:true},
    {apiVersion:"networking.k8s.io/v1",kind:"Ingress",name:$stable,uid:$stable_uid}
  ]}
}')
kubectl -n "$namespace" patch ingress "$canary" --type=merge -p "$owners" -o json > "$output/restored-ingress.json"
jq -e --arg stale "$stale" 'any(.metadata.ownerReferences[]; .controller == true and .uid == $stale)' "$output/restored-ingress.json"
kubectl -n "$namespace" annotate rollout "$rollout" adl.example.test/replay=stale --overwrite
for attempt in {1..30}; do
  if grep -q 'canary ingress controlled by different object' "$output/controller.log"; then break; fi
  sleep 2
done
grep -m1 'canary ingress controlled by different object' "$output/controller.log"
observed=$(owner_uid)
# Kubernetes may strip the dangling Rollout reference while retaining the Ingress.
[[ "$observed" = "$stale" || -z "$observed" ]]
printf 'Restored fixture has controller UID %s, destination Rollout has %s\n' "${observed:-<missing>}" "$expected"
kubectl -n "$namespace" get events -o json | jq -e 'any(.items[]; .reason == "TrafficRoutingError")'

kubectl -n "$namespace" delete ingress "$canary"
for attempt in {1..45}; do
  if current_owner=$(owner_uid 2>/dev/null) && [[ "$current_owner" = "$expected" ]]; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done
test "$(owner_uid)" = "$expected"
test "$(canary_uid)" != "$original_canary"
test "$(stable_uid)" = "$original_stable"
printf 'Recreated Ingress owner matches destination Rollout UID. Stable Ingress UID unchanged.\n'
