#!/usr/bin/env bash
set -euo pipefail

contract=${1:?supply an act replay contract}
candidate=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["candidate"])' "$contract")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git clone --quiet --no-checkout --filter=blob:none https://github.com/archit15singh/act.git "$work/act"
git -C "$work/act" fetch --quiet origin "$candidate"
status=0
output=${2:?supply an output directory}
python3 -m delivery upstream-replay --repo "$work/act" --contract "$contract" --output "$output" || status=$?
if [[ -f "$output/receipt.json" ]]; then
  cat "$output/receipt.json"
fi
exit "$status"
