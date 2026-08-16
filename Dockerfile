# syntax=docker/dockerfile:1

ARG GENERATOR_REF=main

FROM rust:1-bookworm AS build
ARG GENERATOR_REF
WORKDIR /src
ENV DEBIAN_FRONTEND=noninteractive \
    CARGO_TERM_COLOR=never
RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*
RUN git init \
  && git remote add origin https://github.com/surge-networks/MTProtoDCConfigGenerator.git \
  && git fetch --depth 1 origin "${GENERATOR_REF}" \
  && git checkout --force FETCH_HEAD
# Cache crates + target across CI builds; copy the binary out of the cache mount.
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=/src/target,sharing=locked \
    cargo build --release --locked \
    && cp /src/target/release/mtproto-dc-config /mtproto-dc-config

FROM debian:bookworm-slim
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    python3 \
    python3-cryptography \
  && rm -rf /var/lib/apt/lists/* \
  && case "${TARGETARCH}" in \
       amd64) SC_ARCH=amd64 ;; \
       arm64) SC_ARCH=arm64 ;; \
       *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
     esac \
  && curl -fsSL -o /usr/local/bin/supercronic \
    "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${SC_ARCH}" \
  && chmod +x /usr/local/bin/supercronic \
  && useradd --uid 10001 --home-dir /home/app --create-home app \
  && mkdir -p /data \
  && chown app:app /data

COPY --from=build /mtproto-dc-config /usr/local/bin/mtproto-dc-config
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY generate.sh /usr/local/bin/generate.sh
COPY merge_extra_backups.py /usr/local/bin/merge_extra_backups.py
COPY normalize_config.py /usr/local/bin/normalize_config.py
COPY serve.py /usr/local/bin/serve.py

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/generate.sh /usr/local/bin/merge_extra_backups.py /usr/local/bin/normalize_config.py /usr/local/bin/serve.py

ENV PORT=8080 \
    DATA_DIR=/data \
    OUTPUT_FILE=/data/mtproto-dc-config.json \
    CRON_SCHEDULE="0 0 * * *" \
    DROP_SECRET_ENDPOINTS=0 \
    MERGE_FLAGS=1 \
    EXTRA_BACKUP_SOURCES=1 \
    TZ=UTC

WORKDIR /data
USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/\", timeout=3)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
