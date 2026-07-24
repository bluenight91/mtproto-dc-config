#!/bin/sh
set -eu

DATA_DIR=${DATA_DIR:-/data}
OUTPUT_FILE=${OUTPUT_FILE:-$DATA_DIR/mtproto-dc-config.json}
PORT=${PORT:-8080}
CRON_SCHEDULE=${CRON_SCHEDULE:-"0 0 * * *"}
CRON_FILE=${CRON_FILE:-/tmp/mtproto-crontab}

mkdir -p "$DATA_DIR"

echo "Generating MTProto DC config..."
mtproto-dc-config "$OUTPUT_FILE"

printf '%s mtproto-dc-config %s\n' "$CRON_SCHEDULE" "$OUTPUT_FILE" > "$CRON_FILE"
echo "Cron schedule: $CRON_SCHEDULE"

supercronic "$CRON_FILE" &
exec python3 /usr/local/bin/serve.py
