#!/usr/bin/env bash
set -euo pipefail

base=c7517808d64f06609e4ecf0db1757005373cc3a3
test_case=sweep::tests::a_process_older_than_its_token_is_never_read
output="$PWD/.adl/herdr-core-302-evidence"
mkdir -p "$output"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

git clone --filter=blob:none https://github.com/herdrdev/herdr-core.git "$scratch/source"
cd "$scratch/source"
git checkout --detach "$base"
git submodule update --init --depth 1
git rev-parse HEAD | tee "$output/base-revision.txt"

cargo test --locked -p herdr-core --lib --no-run --message-format=json \
  | jq -r 'select(.reason == "compiler-artifact" and .target.name == "herdr_core"
                  and .profile.test and .executable != null) | .executable' \
  > "$scratch/test-path"
binary=$(cat "$scratch/test-path")
test -x "$binary"
"${binary}" "$test_case" --exact --nocapture | tee "$output/normal-clock.log"
grep -F '1 passed' "$output/normal-clock.log"

exit_code=0
sudo unshare --time --fork --kill-child --boottime 1000000000 \
  setpriv --reuid "$(id -u)" --regid "$(id -g)" --init-groups \
  "$binary" "$test_case" --exact --nocapture > "$output/shifted-clock.log" 2>&1 || exit_code=$?
cat "$output/shifted-clock.log"
printf 'shifted_exit=%s\n' "$exit_code" | tee "$output/shifted-exit.txt"
test "$exit_code" -eq 101
grep -F 'a token from far ahead is newer than every process' "$output/shifted-clock.log"
