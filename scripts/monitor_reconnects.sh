#!/usr/bin/env bash
# Capture 2h of transit-tracker logs, then analyze reconnect/handshake patterns.
# Writes raw logs + summary to /tmp/transit-monitor-<timestamp>/.
#
# Tails the launchd agent's log file (the Docker path was retired 2026-09-21).
# Override with TT_LOG when running against another host's copy.

set -euo pipefail

DURATION_SECS=${1:-7200}
OUTDIR="/tmp/transit-monitor-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"
RAW="$OUTDIR/raw.log"
SUMMARY="$OUTDIR/summary.txt"

TT_LOG="${TT_LOG:-$HOME/Library/Logs/transit-tracker.log}"

echo "Capturing ${DURATION_SECS}s of logs from $TT_LOG → $RAW"
tail -n 0 -F "$TT_LOG" >"$RAW" 2>&1 &
LOG_PID=$!
trap 'kill $LOG_PID 2>/dev/null || true' EXIT

sleep "$DURATION_SECS"
kill $LOG_PID 2>/dev/null || true
wait $LOG_PID 2>/dev/null || true

START_TS=$(head -1 "$RAW" | awk '{print $1}')
END_TS=$(tail -1 "$RAW" | awk '{print $1}')

{
  echo "=== Transit Tracker Reconnect Monitor ==="
  echo "Window: $START_TS → $END_TS"
  echo "Raw log: $RAW ($(wc -l <"$RAW") lines)"
  echo

  echo "--- Totals ---"
  printf "%-40s %s\n" "HTTP/WS requests"       "$(grep -c 'HTTP/WS request'       "$RAW" || true)"
  printf "%-40s %s\n" "Client connected"       "$(grep -c 'Client connected'      "$RAW" || true)"
  printf "%-40s %s\n" "Client disconnected"    "$(grep -c 'Client disconnected'   "$RAW" || true)"
  printf "%-40s %s\n" "Opening handshake failed" "$(grep -c 'opening handshake failed' "$RAW" || true)"
  printf "%-40s %s\n" "ConnectionClosedError 1002" "$(grep -c '1002 (protocol error)'    "$RAW" || true)"
  printf "%-40s %s\n" "write_eof RuntimeError" "$(grep -c 'Cannot call write() after write_eof' "$RAW" || true)"
  printf "%-40s %s\n" "429 rate limits"        "$(grep -c '429'                   "$RAW" || true)"
  echo

  echo "--- Connections by source peer IP ---"
  grep -oE "Client connected: \('[^']+'" "$RAW" \
    | sed "s/.*('//; s/'.*//" \
    | sort | uniq -c | sort -rn
  echo

  echo "--- Connections by User-Agent ---"
  grep 'Client connected' "$RAW" \
    | grep -oE "ua='[^']*'" \
    | sort | uniq -c | sort -rn
  echo

  echo "--- Per-hour connect counts ---"
  grep 'Client connected' "$RAW" \
    | awk '{print substr($1,1,13)}' \
    | sort | uniq -c
  echo

  echo "--- Per-hour handshake failures ---"
  grep 'opening handshake failed' "$RAW" \
    | awk '{print substr($1,1,13)}' \
    | sort | uniq -c
  echo

  echo "--- Connection durations (by client port) ---"
  echo "port,connect_ts,disconnect_ts,duration_sec,subscribed"
  awk '
    /Client connected:/ {
      match($0, /\('\''[0-9.]+'\'', [0-9]+\)/)
      key = substr($0, RSTART, RLENGTH)
      connect[key] = $1
    }
    /subscribed to/ {
      match($0, /\('\''[0-9.]+'\'', [0-9]+\)/)
      key = substr($0, RSTART, RLENGTH)
      subscribed[key] = 1
    }
    /Client disconnected:/ {
      match($0, /\('\''[0-9.]+'\'', [0-9]+\)/)
      key = substr($0, RSTART, RLENGTH)
      if (key in connect) {
        cmd = "date -j -u -f %Y-%m-%dT%H:%M:%S %%s " gensub(/\..*/, "", 1, connect[key])
        # just emit raw timestamps; downstream can diff
        sub_flag = (key in subscribed) ? "yes" : "no"
        gsub(/,/, "|", key)
        print key "," connect[key] "," $1 ",," sub_flag
        delete connect[key]
        delete subscribed[key]
      }
    }
  ' "$RAW" | head -100
  echo

  echo "--- Short-lived connections (<2s, candidate for reconnect storm) ---"
  python3 - <<'PY' "$RAW"
import re, sys
from datetime import datetime
path = sys.argv[1]
conn = {}
short = []
total_closed = 0
durations = []
ts_re = re.compile(r'^(\S+)')
key_re = re.compile(r"\('([0-9.]+)', (\d+)\)")
def parse(ts):
    # 2026-04-14T15:48:15.758640526Z → drop nanos beyond micro
    ts = ts.rstrip('Z')
    if '.' in ts:
        head, frac = ts.split('.')
        frac = frac[:6]
        ts = f"{head}.{frac}"
    return datetime.fromisoformat(ts)
with open(path) as f:
    for line in f:
        m_ts = ts_re.match(line)
        m_k = key_re.search(line)
        if not (m_ts and m_k): continue
        ts = parse(m_ts.group(1))
        key = m_k.group(0)
        if 'Client connected' in line:
            conn[key] = ts
        elif 'Client disconnected' in line and key in conn:
            dur = (ts - conn.pop(key)).total_seconds()
            durations.append(dur)
            total_closed += 1
            if dur < 2.0:
                short.append((key, dur))
print(f"Closed connections analyzed: {total_closed}")
if durations:
    durations.sort()
    n = len(durations)
    def pct(p): return durations[min(n-1, int(n*p))]
    print(f"Duration p50={pct(0.5):.2f}s  p90={pct(0.9):.2f}s  p99={pct(0.99):.2f}s  max={durations[-1]:.2f}s")
print(f"Short-lived (<2s): {len(short)}")
for k, d in short[:20]:
    print(f"  {k}  {d:.3f}s")
PY
  echo

  echo "--- Unique error tracebacks (top 10) ---"
  awk '/Traceback/,/^[^ ]/' "$RAW" \
    | grep -E '^[A-Za-z_.]+: ' \
    | sort | uniq -c | sort -rn | head -10
  echo

  echo "--- Sample ghost connections (connected, no subscribe, disconnect) ---"
  python3 - <<'PY' "$RAW"
import re, sys
path = sys.argv[1]
state = {}
ghosts = []
key_re = re.compile(r"\('([0-9.]+)', (\d+)\)")
with open(path) as f:
    for line in f:
        m = key_re.search(line)
        if not m: continue
        key = m.group(0)
        if 'Client connected' in line:
            state[key] = [line.strip(), False]
        elif 'subscribed to' in line and key in state:
            state[key][1] = True
        elif 'Client disconnected' in line and key in state:
            connect_line, subbed = state.pop(key)
            if not subbed:
                ghosts.append((connect_line, line.strip()))
print(f"Ghost count: {len(ghosts)}")
for c, d in ghosts[:10]:
    print("  C:", c[:200])
    print("  D:", d[:200])
PY

} | tee "$SUMMARY"

echo
echo "Done. Raw: $RAW  Summary: $SUMMARY"
