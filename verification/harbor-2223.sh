#!/usr/bin/env bash
set -euo pipefail

phase="$1"
revision="$2"
repository="$3"
output="$PWD/.adl/harbor-2223"
mkdir -p "$output"
root="$(mktemp -d)"
git init -q "$root/source"
git -C "$root/source" fetch -q --depth=1 "https://github.com/$repository.git" "$revision"
git -C "$root/source" checkout --detach FETCH_HEAD
test "$(git -C "$root/source" rev-parse HEAD)" = "$revision"
printf '%s %s\n' "$phase" "$revision" > "$output/revision.txt"
docker version > "$output/docker.txt"
cd "$root/source"
uv sync --locked --no-dev --python 3.13
image='ubuntu:24.04@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289'
docker pull "$image"
export HARBOR_TELEMETRY=off NO_COLOR=1
for source in plain-bench my__benchmark__local; do
  task="$root/$source/sample"
  mkdir -p "$task/environment" "$task/tests"
  cat > "$task/task.toml" <<EOF
schema_version = "1.4"
[task]
name = "fixture/sample"
version = "1.0.0"
[environment]
docker_image = "$image"
[verifier]
timeout_sec = 30
EOF
  printf '%s\n' 'This deterministic fixture has no agent work.' > "$task/instruction.md"
  cat > "$task/tests/test.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/verifier
printf '1\n' > /logs/verifier/reward.txt
EOF
  chmod +x "$task/tests/test.sh"

  if .venv/bin/harbor run -p "$root/$source" -a nop -e docker --job-name "$source" -o "$root/jobs" > "$output/$source.log" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  printf 'Harbor CLI %s, exit %s\n' "$source" "$rc"
  job="$root/jobs/$source"
  test -f "$job/result.json"
  cp "$job/result.json" "$output/$source-job.json"
  test "$(find "$job" -mindepth 2 -maxdepth 2 -name result.json | wc -l)" -eq 1
  find "$job" -mindepth 2 -maxdepth 2 -name result.json -exec cp {} "$output/$source-trial.json" \;
  jq -e --arg source "$source" '.source == $source and .verifier_result.rewards.reward == 1' "$output/$source-trial.json"

  if [[ "$phase" == base && "$source" == my__benchmark__local ]]; then
    test "$rc" -ne 0
    grep -F "KeyError: 'local'" "$output/$source.log"
    jq -e '.finished_at == null' "$output/$source-job.json"
  else
    test "$rc" -eq 0
    jq -e --arg key "nop__$source" '.finished_at != null and .stats.evals[$key].metrics == [{"mean":1.0}]' "$output/$source-job.json"
    grep -F "$source • nop" "$output/$source.log"
  fi
done
