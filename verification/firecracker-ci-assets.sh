#!/usr/bin/env bash
# Build the owned x86_64 CI guest from pinned inputs on a disposable Linux runner.
set -euo pipefail
test "$(uname -m)" = x86_64
mkdir -p "$1"
assets=$(realpath "$1")
init=$(realpath verification/firecracker-init)
source=$(mktemp -d)
guest=
trap 'if [[ -n "$guest" ]]; then docker rm "$guest" >/dev/null; fi; sudo rm -rf -- "$source"' EXIT

curl --retry 3 -fsSLo "$source/firecracker.tgz" \
  https://github.com/firecracker-microvm/firecracker/releases/download/v1.18.0/firecracker-v1.18.0-x86_64.tgz
echo "1ac8eec866dd5eea14efecf6323e22b23eea24054545338a5b34bc5bca6623cd  $source/firecracker.tgz" | sha256sum -c
tar -C "$source" -xzf "$source/firecracker.tgz"
install "$source/release-v1.18.0-x86_64/firecracker-v1.18.0-x86_64" "$assets/firecracker"
curl --retry 3 -fsSLo "$assets/vmlinux" \
  https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/20261118-6d7cfa9c6b53-0/x86_64/vmlinux-6.1.188
echo "c7f899cbd24b856bca2a6db1736a48f90b4fe1f75cd3f53e775f36d8e8b00a40  $assets/vmlinux" | sha256sum -c

image=docker.io/library/python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
guest=$(docker create "$image")
mkdir "$source/root"
docker export "$guest" | sudo tar -C "$source/root" -xf -
sudo install -m 0755 "$init" "$source/root/sbin/adl-init"
truncate -s 128M "$assets/rootfs.ext4"
sudo mke2fs -q -F -t ext4 -d "$source/root" "$assets/rootfs.ext4"
