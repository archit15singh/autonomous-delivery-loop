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
base=cee2a5eb0a13dd374bbc9b56008c92227981f704
candidate=d91fcb7affe403a6a1c39bf720647305f6099d57
for phase in base candidate; do
    source_root="$(mktemp -d)"
    git init -q "$source_root"
    if [[ "$phase" == base ]]; then
        repo=https://github.com/harbor-framework/harbor.git
        revision="$base"
    else
        repo=https://github.com/archit15singh/harbor.git
        revision="$candidate"
    fi
    git -C "$source_root" fetch -q --depth=1 "$repo" "$revision"
    git -C "$source_root" checkout --detach FETCH_HEAD
    test "$(git -C "$source_root" rev-parse HEAD)" = "$revision"
    printf '%s %s\n' "$phase" "$revision" | tee -a "$receipts/revisions.txt"
    (
        cd "$source_root"
        uv sync --locked --no-dev --python 3.13
        export ADL_DOCKER_LOG="$receipts/$phase-injection.log"
        PATH="$wrapper:$PATH" .venv/bin/python "$here/harbor-2805.py" "$phase" 2>&1 | tee "$receipts/$phase.log"
        test "$(grep -Fc 'fixture: initial down failed' "$ADL_DOCKER_LOG")" -eq 1
    )
done
