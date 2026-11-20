#!/usr/bin/env bash
set -euo pipefail

base=ac4c09993f474fc8091608f2f7cf85a69dfd012f
candidate=5b250f9f1dd07aa676ae388cf2e9f48632f6bde8
case_name=TestDockerPullSendsDockerHubAuthForBothImageNames
case_file=pkg/container/docker_pull_test.go
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p .adl/act-6236-evidence
evidence=$(cd .adl/act-6236-evidence && pwd)

git clone --quiet --no-checkout --filter=blob:none https://github.com/archit15singh/act.git "$work/act"
cd "$work/act"
git fetch --quiet origin "$candidate"
test "$(git rev-parse "$candidate^")" = "$base"
printf 'base=%s\ncandidate=%s\n' "$base" "$candidate" | tee "$evidence/revisions.txt"

git checkout --quiet --detach "$base"
git diff "$base" "$candidate" -- "$case_file" | git apply
if go test -race -v ./pkg/container -run "^${case_name}$" -count=1 2>&1 | tee "$evidence/before.log"; then
  echo "Expected qualified pull to omit the auth header on the base" >&2
  exit 1
fi
grep -F 'docker.io/nektos/act → docker.io/nektos/act, X-Registry-Auth present=false' "$evidence/before.log"
grep -F -- "--- FAIL: $case_name" "$evidence/before.log"

git restore -- "$case_file"
git checkout --quiet --detach "$candidate"
go test -race -v ./pkg/container -run "^(TestCleanImage|TestGetImagePullOptions|${case_name})$" -count=1 2>&1 | tee "$evidence/after.log"
grep -F 'docker.io/nektos/act → docker.io/nektos/act, X-Registry-Auth present=true' "$evidence/after.log"
