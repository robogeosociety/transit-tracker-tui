#!/usr/bin/env bash
# Rotate ~/Library/Logs/transit-tracker.log.
#
# launchd's StandardOutPath does not rotate the way Docker's json-file driver
# did, and the service writes ~1.5 MB/week. Run from cron/launchd daily, or by
# hand; it is a no-op below the threshold.
#
# COPY-TRUNCATE, not rename: launchd holds the fd open, so a renamed file keeps
# receiving writes and the fresh one stays empty.
set -euo pipefail

LOG="${TT_LOG:-$HOME/Library/Logs/transit-tracker.log}"
MAX_BYTES="${TT_LOG_MAX_BYTES:-20971520}"   # 20 MiB
KEEP="${TT_LOG_KEEP:-3}"

[ -f "$LOG" ] || exit 0
size=$(stat -f%z "$LOG")
[ "$size" -lt "$MAX_BYTES" ] && exit 0

for i in $(seq $((KEEP - 1)) -1 1); do
  [ -f "$LOG.$i.gz" ] && mv "$LOG.$i.gz" "$LOG.$((i + 1)).gz"
done
rm -f "$LOG.$((KEEP + 1)).gz"
cp "$LOG" "$LOG.1"
: > "$LOG"
gzip -f "$LOG.1"
echo "rotated $LOG ($size bytes) -> $LOG.1.gz"
