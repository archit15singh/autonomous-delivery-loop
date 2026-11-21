#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
receipts="$PWD/.adl/harbor-2805"
mkdir -p "$receipts"
export REAL_DOCKER="$(command -v docker)"
image=alpine:3.23.4@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11
export REPLAY_IMAGE="$image"
"$REAL_DOCKER" version > "$receipts/docker.txt"
"$REAL_DOCKER" compose version >> "$receipts/docker.txt"
"$REAL_DOCKER" pull "$image"
source_root="$(mktemp -d)"
wrapper="$(mktemp -d)"
cat > "$wrapper/docker" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" compose --project-name ${ADL_FAIL_INITIAL_DOWN:-unused} "*" down --remove-orphans ")
    echo "Injected failure for this project's pre-start compose down" >&2
    echo "fixture: initial down failed" >> "$ADL_DOCKER_LOG"
    exit 19
    ;;
esac
exec "$REAL_DOCKER" "$@"
WRAP
chmod +x "$wrapper/docker"
export ADL_DOCKER_LOG="$receipts/injection.log"
base=cee2a5eb0a13dd374bbc9b56008c92227981f704
git init -q "$source_root"
git -C "$source_root" fetch -q --depth=1 https://github.com/harbor-framework/harbor.git "$base"
git -C "$source_root" checkout --detach FETCH_HEAD
git -C "$source_root" rev-parse HEAD | tee "$receipts/revision.txt"
cd "$source_root"
uv sync --locked --no-dev --python 3.13
PATH="$wrapper:$PATH" .venv/bin/python "$here/harbor-2805.py" 2>&1 | tee "$receipts/baseline.log"
test "$(grep -Fc 'fixture: initial down failed' "$ADL_DOCKER_LOG")" -eq 1
