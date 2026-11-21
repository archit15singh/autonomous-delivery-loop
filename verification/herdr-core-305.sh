#!/usr/bin/env bash
set -euo pipefail

base=c7517808d64f06609e4ecf0db1757005373cc3a3
candidate=dc09f059bfa81aca8a9866d47c300199009c7c33
test_file=crates/herdr-core/tests/remote.rs
test_case=reconnect_preserves_a_viewers_scrollback
output="$PWD/.adl/herdr-core-305-evidence"
mkdir -p "$output"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
git clone --quiet --filter=blob:none --no-checkout https://github.com/archit15singh/herdr-core.git "$scratch/source"
cd "$scratch/source"
git fetch --quiet --no-tags origin "$candidate"
test "$(git rev-parse "$candidate^")" = "$base"
git checkout --detach "$base"
git submodule update --init --depth 1

replay() {
  local phase=$1 expected=$2 code=0
  git rev-parse HEAD > "$output/$phase-revision.txt"
  cargo test --locked -p herdr-core --test remote "$test_case" -- --exact --nocapture \
    > "$output/$phase.log" 2>&1 || code=$?
  cat "$output/$phase.log"
  printf 'exit=%s\n' "$code" | tee "$output/$phase-exit.txt"
  test "$code" -eq "$expected"
}

git diff "$base" "$candidate" -- "$test_file" | git apply --check
git diff "$base" "$candidate" -- "$test_file" | git apply
test "$(git diff --name-only)" = "$test_file"
replay base 101
grep -F 'the reconnect must not add the old screen or notice to history' "$output/base.log"
git restore -- "$test_file"
git checkout --detach "$candidate"
replay candidate 0
grep -F '1 passed' "$output/candidate.log"
