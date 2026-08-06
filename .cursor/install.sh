#!/usr/bin/env bash
# Idempotent Cloud Agent setup for the MTProto DC config service.
#
# Builds the upstream MTProtoDCConfigGenerator Rust binary (pinned by
# .upstream-sha) and installs it to ~/.local/bin so the repo's generate/serve
# scripts can run locally, exactly as they do inside the published container.
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
UPSTREAM_REPO="https://github.com/surge-networks/MTProtoDCConfigGenerator.git"
SRC_DIR="${HOME}/.cache/mtproto-generator-src"
BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/mtproto-dc-config"
STAMP_FILE="${BIN_DIR}/.mtproto-dc-config.sha"

UPSTREAM_SHA=$(tr -d '[:space:]' < "${REPO_ROOT}/.upstream-sha")
echo "[install] pinned upstream generator SHA: ${UPSTREAM_SHA}"

# edition = "2024" in the generator needs Rust >= 1.85; ensure a modern stable
# toolchain is present and selected (matches the rust:1-bookworm build image).
rustup toolchain install stable --profile minimal >/dev/null 2>&1 || true
rustup default stable >/dev/null 2>&1 || true
echo "[install] using $(rustc --version)"

mkdir -p "${BIN_DIR}"

if [ -x "${BIN_PATH}" ] && [ -f "${STAMP_FILE}" ] && [ "$(cat "${STAMP_FILE}")" = "${UPSTREAM_SHA}" ]; then
  echo "[install] generator already built for ${UPSTREAM_SHA}; skipping rebuild"
else
  mkdir -p "${SRC_DIR}"
  cd "${SRC_DIR}"
  if [ ! -d .git ]; then
    git init -q
  fi
  git remote add origin "${UPSTREAM_REPO}" 2>/dev/null || git remote set-url origin "${UPSTREAM_REPO}"
  git fetch --depth 1 origin "${UPSTREAM_SHA}"
  git checkout --force FETCH_HEAD
  cargo build --release --locked
  install -m 0755 "${SRC_DIR}/target/release/mtproto-dc-config" "${BIN_PATH}"
  echo "${UPSTREAM_SHA}" > "${STAMP_FILE}"
  echo "[install] installed generator to ${BIN_PATH}"
fi

test -x "${BIN_PATH}"
echo "[install] done"
