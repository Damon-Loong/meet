#!/bin/sh
# 2026-10-20，wyy 新增：会后任务镜像构建入口，所有源码来自 main；不启动服务。
set -eu
THIS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$THIS_DIR/../.." && pwd)
docker build --network="${BUILD_NETWORK:-default}" --target production --build-arg DOCKER_USER=0 \
  -t lasuite-meet/summary:wyy-postmeeting-20261020 "$REPO_ROOT/src/summary"
docker build --network="${BUILD_NETWORK:-default}" -f "$THIS_DIR/Dockerfile.worker" \
  --build-arg ALPINE_MIRROR="${ALPINE_MIRROR:-https://dl-cdn.alpinelinux.org/alpine}" \
  -t lasuite-meet/postmeeting-worker:wyy-20261020 "$THIS_DIR"
docker build --network="${BUILD_NETWORK:-default}" -f "$THIS_DIR/Dockerfile.runner" \
  --build-arg DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://deb.debian.org}" \
  --build-arg PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}" \
  -t lasuite-meet/postmeeting-runner:wyy-20261020 "$THIS_DIR"
if ! docker network inspect meet-postmeeting-egress >/dev/null 2>&1; then
  docker network create --driver bridge meet-postmeeting-egress >/dev/null
fi
