#!/usr/bin/env bash
set -euo pipefail

contract=contracts/upstream/act-6236.json
candidate=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["candidate"])' "$contract")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git clone --quiet --no-checkout --filter=blob:none https://github.com/archit15singh/act.git "$work/act"
git -C "$work/act" fetch --quiet origin "$candidate"
status=0
output=${1:-.adl/act-6236-evidence}
python3 -m delivery upstream-replay --repo "$work/act" --contract "$contract" --output "$output" || status=$?
if [[ -f "$output/receipt.json" ]]; then
  cat "$output/receipt.json"
fi
exit "$status"
