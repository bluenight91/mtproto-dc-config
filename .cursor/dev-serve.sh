#!/usr/bin/env bash
# Local dev runner: generate + normalize the DC config, then serve it on $PORT.
# Mirrors the container entrypoint (minus the cron) using the repo's own
# serve.py / normalize_config.py and the locally built generator binary.
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PATH="${HOME}/.local/bin:${PATH}"

export PORT="${PORT:-8080}"
export DATA_DIR="${DATA_DIR:-${HOME}/mtproto-data}"
export OUTPUT_FILE="${OUTPUT_FILE:-${DATA_DIR}/mtproto-dc-config.json}"
export DROP_SECRET_ENDPOINTS="${DROP_SECRET_ENDPOINTS:-0}"
export MERGE_FLAGS="${MERGE_FLAGS:-1}"

mkdir -p "${DATA_DIR}"

echo "[dev-serve] generating ${OUTPUT_FILE} ..."
if mtproto-dc-config "${OUTPUT_FILE}"; then
  python3 "${REPO_ROOT}/normalize_config.py" "${OUTPUT_FILE}"
else
  echo "[dev-serve] generation failed (network to Telegram?); serving whatever exists" >&2
fi

echo "[dev-serve] serving ${OUTPUT_FILE} on 0.0.0.0:${PORT}"
exec python3 "${REPO_ROOT}/serve.py"
