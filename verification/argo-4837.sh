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
  if [[ -n "${ingress_forward_pid:-}" ]]; then kill "$ingress_forward_pid" || true; fi
  if [[ -n "${controller_pid:-}" ]]; then
    kill -CONT "$controller_pid" || true
    kill "$controller_pid" || true
  fi
  kubectl -n ingress-nginx logs deployment/ingress-nginx-controller > "$output/ingress-controller.log" 2>&1 || true
  kubectl -n "$namespace" get events -o json > "$output/events.json" || true
  kubectl -n "$namespace" get rollout,ingress,pod -o yaml > "$output/objects.yaml" || true
  kind delete cluster --name "$name"
}
trap cleanup EXIT
kind version
kind create cluster --name "$name" --image kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f --wait 120s
kubectl version
curl -fsSL https://raw.githubusercontent.com/kubernetes/ingress-nginx/0a5901f3c64f11e92e487799b8da3f00cca37515/deploy/static/provider/cloud/deploy.yaml -o "$output/nginx-deploy.yaml"
printf '%s  %s\n' 502fddca66b09c20dd48b6d0a792a9671cd663a3a0d2a8bda5ae990d13b6c5b2 "$output/nginx-deploy.yaml" | sha256sum -c -
kubectl apply -f "$output/nginx-deploy.yaml"
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s
kubectl -n ingress-nginx wait --for=condition=complete --timeout=60s job/ingress-nginx-admission-patch
kubectl -n ingress-nginx port-forward --address 127.0.0.1 service/ingress-nginx-controller 18979:80 > "$output/port-forward.log" 2>&1 &
ingress_forward_pid=$!
kubectl apply --server-side -k "$source_dir/manifests/crds"
kubectl wait --for=condition=Established --timeout=45s crd/rollouts.argoproj.io
kubectl create namespace argo-rollouts
kubectl create namespace "$namespace"
for manifest in services ingress rollout; do
  kubectl -n "$namespace" apply -f "$source_dir/docs/getting-started/nginx/$manifest.yaml"
done
kubectl -n "$namespace" patch rollout "$rollout" --type=merge -p '{
  "spec":{"strategy":{"canary":{"trafficRouting":{"nginx":{"additionalIngressAnnotations":{"canary-by-header":"X-Canary"}}}}}}
}'
kubectl -n "$namespace" patch rollout "$rollout" --type=json -p '[
  {"op":"replace","path":"/spec/template/spec/containers/0/image","value":"argoproj/rollouts-demo:blue@sha256:211345b036e25b71ac57eb73d2742c399dc773d514fe97714c7f12a376d7e6e0"},
  {"op":"add","path":"/spec/template/spec/containers/0/env","value":[{"name":"COLOR","value":"blue"}]}
]'
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

route_color() {
  local selector=$1 expected_color=$2 phase=$3 actual
  for attempt in {1..60}; do
    if actual=$(curl -fsS --max-time 3 -H 'Host: rollouts-demo.local' -H "X-Canary: $selector" http://127.0.0.1:18979/color 2>/dev/null | jq -er '.') && [[ "$actual" = "$expected_color" ]]; then
      printf '%s: X-Canary=%s → %s\n' "$phase" "$selector" "$actual"
      return 0
    fi
    sleep 2
  done
  printf '%s failed. Expected color %s, last result %s\n' "$phase" "$expected_color" "${actual:-<none>}" >&2
  return 1
}

route_color never blue initial
kubectl -n "$namespace" patch rollout "$rollout" --type=json -p '[
  {"op":"replace","path":"/spec/template/spec/containers/0/env/0/value","value":"green"}
]'
route_color always green before-restore
route_color never blue before-restore

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

route_color always green stale-owner
kill -STOP "$controller_pid"
kubectl -n "$namespace" delete ingress "$canary"
route_color always blue while-canary-ingress-absent
route_color never blue while-canary-ingress-absent
kill -CONT "$controller_pid"
for attempt in {1..45}; do
  if current_owner=$(owner_uid 2>/dev/null) && [[ "$current_owner" = "$expected" ]]; then break; fi
  kill -0 "$controller_pid"
  sleep 2
done
test "$(owner_uid)" = "$expected"
test "$(canary_uid)" != "$original_canary"
test "$(stable_uid)" = "$original_stable"
printf 'Recreated Ingress owner matches destination Rollout UID. Stable Ingress UID unchanged.\n'
route_color always green recreated
route_color never blue recreated
