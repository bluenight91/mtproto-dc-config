#!/bin/sh
# Generate DC config then normalize/dedupe addresses.
set -eu

OUTPUT_FILE=${1:-${OUTPUT_FILE:-/data/mtproto-dc-config.json}}

mtproto-dc-config "$OUTPUT_FILE"
python3 /usr/local/bin/normalize_config.py "$OUTPUT_FILE"
