#!/usr/bin/env bash
set -euo pipefail

base=317e673f1f1568b876cbaa0b41dabeb9153ecbea
candidate=95384777b9d585ba20c135a7adfac22c87dcc96a
core_rev=c7517808d64f06609e4ecf0db1757005373cc3a3
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
output="$PWD/.adl/herdr-app-1263-evidence"
mkdir -p "$output"
printf 'base=%s\ncandidate=%s\ncore=%s\n' "$base" "$candidate" "$core_rev" | tee "$output/revisions.txt"

git init -q "$scratch/core"
git -C "$scratch/core" fetch -q --depth=1 https://github.com/herdrdev/herdr-core.git "$core_rev"
git -C "$scratch/core" checkout -q --detach FETCH_HEAD
git -C "$scratch/core" submodule update --init --recursive --depth 1
(cd "$scratch/core" && cargo build --locked -p herdr-core) >"$output/core-build.log" 2>&1

git init -q "$scratch/app"
git -C "$scratch/app" fetch -q --depth=1 https://github.com/herdrdev/herdr-app.git "$base"
git -C "$scratch/app" checkout -q --detach FETCH_HEAD
git -C "$scratch/app" submodule update --init --recursive --depth 1
(cd "$scratch/app" && cargo build --locked --config 'profile.dev.package."*".opt-level=0') >"$output/base-build.log" 2>&1
cp "$scratch/app/target/debug/herdr-app" "$scratch/base"

git -C "$scratch/app" fetch -q --depth=1 https://github.com/archit15singh/herdr-app.git "$candidate"
git -C "$scratch/app" checkout -q --detach FETCH_HEAD
test "$(git -C "$scratch/app" rev-parse HEAD)" = "$candidate"
(cd "$scratch/app" && cargo build --locked --config 'profile.dev.package."*".opt-level=0') >"$output/candidate-build.log" 2>&1

for side in before after; do
    binary="$scratch/base"
    if [[ "$side" == after ]]; then binary="$scratch/app/target/debug/herdr-app"; fi
    xvfb-run -a -s '-screen 0 1400x900x24' python3 verification/herdr-app-1263.py \
        "$binary" "$scratch/core/target/debug/herdr-core" "$side" 2>&1 | tee "$output/$side.log"
done
