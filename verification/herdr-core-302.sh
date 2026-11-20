#!/usr/bin/env bash
set -euo pipefail

base=c7517808d64f06609e4ecf0db1757005373cc3a3
candidate=99f82453f5c45bce03f82fc535719454a3aad5d7
test_case=sweep::tests::a_process_older_than_its_token_is_never_read
output="$PWD/.adl/herdr-core-302-evidence"
mkdir -p "$output"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

git clone --filter=blob:none https://github.com/herdrdev/herdr-core.git "$scratch/source"
cd "$scratch/source"
git fetch --no-tags https://github.com/archit15singh/herdr-core.git "$candidate"
git merge-base --is-ancestor "$base" "$candidate"
test "$(git diff --name-only "$base" "$candidate")" = crates/herdr-core/src/sweep.rs
git checkout --detach "$base"
git submodule update --init --depth 1

replay() {
  local stage=$1 revision=$2 expected_exit=$3 binary exit_code=0
  git checkout --detach "$revision"
  git rev-parse HEAD | tee "$output/$stage-revision.txt"

  cargo test --locked -p herdr-core --lib --no-run --message-format=json \
    | jq -r 'select(.reason == "compiler-artifact" and .target.name == "herdr_core"
                    and .profile.test and .executable != null) | .executable' \
    > "$scratch/test-path"
  binary=$(cat "$scratch/test-path")
  test -x "$binary"
  "$binary" "$test_case" --exact --nocapture | tee "$output/$stage-normal.log"
  grep -F '1 passed' "$output/$stage-normal.log"

  sudo unshare --time --fork --kill-child --boottime 1000000000 \
    setpriv --reuid "$(id -u)" --regid "$(id -g)" --init-groups \
    "$binary" "$test_case" --exact --nocapture > "$output/$stage-shifted.log" 2>&1 || exit_code=$?
  cat "$output/$stage-shifted.log"
  printf 'shifted_exit=%s\n' "$exit_code" | tee "$output/$stage-shifted-exit.txt"
  test "$exit_code" -eq "$expected_exit"
}

replay base "$base" 101
grep -F 'a token from far ahead is newer than every process' "$output/base-shifted.log"
replay candidate "$candidate" 0
grep -F '1 passed' "$output/candidate-shifted.log"
