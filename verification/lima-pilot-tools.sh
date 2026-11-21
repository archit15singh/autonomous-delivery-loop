#!/bin/sh
# Run from the trusted host by streaming this file to the dedicated Lima guest.
set -eu
test "$(uname -s)-$(uname -m)" = Linux-aarch64
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$HOME/.local/share/adl/playwright-core-1.64.1"

curl -fsSL --max-time 60 -o "$scratch/playwright.tgz" \
    https://registry.npmjs.org/playwright-core/-/playwright-core-1.64.1.tgz
test "$(openssl dgst -sha512 -binary "$scratch/playwright.tgz" | base64 -w0)" = \
    'BC4s8y6SEVA6Q1rSxZTto8hI1KUI3xXlHGZgvGqP4IqPdI/a6FX9H29IDNz7vKo9l21b6LfYosScPL6M3xxyDQ=='
tar -xzf "$scratch/playwright.tgz" --strip-components=1 \
    -C "$HOME/.local/share/adl/playwright-core-1.64.1"
