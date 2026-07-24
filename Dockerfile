# syntax=docker/dockerfile:1

ARG GENERATOR_REF=main

FROM rust:1-bookworm AS build
ARG GENERATOR_REF
WORKDIR /src
RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && git init \
  && git remote add origin https://github.com/surge-networks/MTProtoDCConfigGenerator.git \
  && git fetch --depth 1 origin "${GENERATOR_REF}" \
  && git checkout --force FETCH_HEAD \
  && cargo build --release --locked

FROM debian:bookworm-slim
ARG TARGETARCH
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    python3 \
  && rm -rf /var/lib/apt/lists/* \
  && case "${TARGETARCH}" in \
       amd64) SC_ARCH=amd64 ;; \
       arm64) SC_ARCH=arm64 ;; \
       *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
     esac \
  && curl -fsSL -o /usr/local/bin/supercronic \
    "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${SC_ARCH}" \
  && chmod +x /usr/local/bin/supercronic \
  && useradd --system --uid 10001 --home-dir /data --create-home app

COPY --from=build /src/target/release/mtproto-dc-config /usr/local/bin/mtproto-dc-config
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY serve.py /usr/local/bin/serve.py

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/serve.py \
  && chown -R app:app /data

ENV PORT=8080 \
    DATA_DIR=/data \
    OUTPUT_FILE=/data/mtproto-dc-config.json \
    CRON_SCHEDULE="0 0 * * *" \
    TZ=UTC

WORKDIR /data
USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/mtproto-dc-config.json\", timeout=3)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
