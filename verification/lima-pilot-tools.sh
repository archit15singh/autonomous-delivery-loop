#!/bin/sh
# Run from the trusted host by streaming this file to the dedicated Lima guest.
set -eu
test "$(uname -s)-$(uname -m)" = Linux-aarch64
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/adl/playwright-core-1.64.1"

curl -fsSL --max-time 180 -o "$scratch/codex.tar.gz" \
    https://github.com/openai/codex/releases/download/rust-v0.170.0/codex-aarch64-unknown-linux-musl.tar.gz
printf '%s  %s\n' 0da6b061f6b5223901a5a73e841bd1466596e2ef620d68823360febed2ff7ebc \
    "$scratch/codex.tar.gz" | sha256sum -c
tar -xzf "$scratch/codex.tar.gz" -C "$scratch"
install -m 0755 "$scratch/codex-aarch64-unknown-linux-musl" "$HOME/.local/bin/codex"

curl -fsSL --max-time 60 -o "$scratch/playwright.tgz" \
    https://registry.npmjs.org/playwright-core/-/playwright-core-1.64.1.tgz
test "$(openssl dgst -sha512 -binary "$scratch/playwright.tgz" | base64 -w0)" = \
    'BC4s8y6SEVA6Q1rSxZTto8hI1KUI3xXlHGZgvGqP4IqPdI/a6FX9H29IDNz7vKo9l21b6LfYosScPL6M3xxyDQ=='
tar -xzf "$scratch/playwright.tgz" --strip-components=1 \
    -C "$HOME/.local/share/adl/playwright-core-1.64.1"
if ! command -v bwrap >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq bubblewrap
fi
"$HOME/.local/bin/codex" --version
