#!/bin/bash
# Install the transit-tracker proxy as a system LaunchDaemon and retire the old
# per-user LaunchAgent.
#
# Run it on the mini as the service user (console or ssh — sudo needs a tty for
# the password prompt):
#
#     ~/.local/share/transit-tracker/app/deploy/launchd/install-daemon.sh
#
# Idempotent: re-run it after updating the app or the plist.
set -euo pipefail

LABEL="org.eastsideurbanism.transit-tracker"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="${SRC_DIR}/${LABEL}.plist"
WRAPPER_SRC="${SRC_DIR}/transit-tracker-daemon"
PLIST_DST="/Library/LaunchDaemons/${LABEL}.plist"
WRAPPER_DST="/usr/local/libexec/transit-tracker-daemon"

RUN_USER="${TRANSIT_TRACKER_USER:-tommydoerr}"
RUN_HOME="/Users/${RUN_USER}"
APP_DIR="${TRANSIT_TRACKER_APP_DIR:-${RUN_HOME}/.local/share/transit-tracker/app}"
LOG_DIR="${RUN_HOME}/Library/Logs"
AGENT_PLIST="${RUN_HOME}/Library/LaunchAgents/${LABEL}.plist"

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

[[ "$(uname -s)" == "Darwin" ]] || die "macOS only"
[[ -f "$PLIST_SRC" ]] || die "missing ${PLIST_SRC}"
[[ -f "$WRAPPER_SRC" ]] || die "missing ${WRAPPER_SRC}"
[[ "$(id -u)" != "0" ]] || die "run as ${RUN_USER}, not root — the script sudo's the parts that need it"
[[ "$(id -un)" == "$RUN_USER" ]] || die "run as ${RUN_USER} (currently $(id -un)); the daemon's UserName is baked into the plist"

# The plist hard-codes paths; a different user needs a different plist.
grep -q "<string>${RUN_USER}</string>" "$PLIST_SRC" \
    || die "${PLIST_SRC} does not name UserName ${RUN_USER} — edit the plist before installing"

step "checking the app install"
[[ -d "$APP_DIR" ]] || die "app dir ${APP_DIR} not found — install the app there first"
if [[ ! -x "${APP_DIR}/.venv/bin/transit-tracker" && ! -x "${RUN_HOME}/.local/bin/transit-tracker" ]]; then
    echo "warning: no transit-tracker executable in ${APP_DIR}/.venv/bin or ${RUN_HOME}/.local/bin;" >&2
    echo "         the wrapper will fall back to PATH, and KeepAlive will retry if it can't find one." >&2
fi

step "retiring the user LaunchAgent (if present)"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null \
    && echo "booted out gui/$(id -u)/${LABEL}" \
    || echo "no running user agent (fine)"
if [[ -f "$AGENT_PLIST" ]]; then
    mv -f "$AGENT_PLIST" "${AGENT_PLIST}.retired-$(date -u +%Y%m%dT%H%M%SZ)"
    echo "moved ${AGENT_PLIST} aside"
fi
pkill -f 'transit-tracker service' 2>/dev/null && echo "killed a stray manual service" || true

step "creating log files owned by ${RUN_USER}"
mkdir -p "$LOG_DIR"
touch "${LOG_DIR}/transit-tracker.log" "${LOG_DIR}/transit-tracker.err.log"

step "installing the wrapper and the plist (sudo)"
sudo mkdir -p /usr/local/libexec
sudo install -o root -g wheel -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
sudo install -o root -g wheel -m 0644 "$PLIST_SRC" "$PLIST_DST"
sudo plutil -lint "$PLIST_DST"

step "loading the daemon (sudo)"
sudo launchctl bootout "system/${LABEL}" 2>/dev/null \
    && echo "booted out the previous daemon" \
    || echo "no previous daemon loaded (fine)"
sudo launchctl bootstrap system "$PLIST_DST"
sudo launchctl enable "system/${LABEL}"
sudo launchctl kickstart -k "system/${LABEL}"

step "verifying"
sleep 2
sudo launchctl print "system/${LABEL}" | sed -n '1,40p'

cat <<EOF

Done. The proxy now runs as a LaunchDaemon and survives \`sudo fdesetup authrestart\`
with nobody logged in.

  logs     tail -f ${LOG_DIR}/transit-tracker.log
  state    sudo launchctl print system/${LABEL}
  restart  sudo launchctl kickstart -k system/${LABEL}

To let ${RUN_USER} (and the bot / the runner) restart it without a password, add
this one line with \`sudo visudo -f /etc/sudoers.d/transit-tracker\`:

  ${RUN_USER} ALL=(root) NOPASSWD: /bin/launchctl kickstart -k system/${LABEL}
EOF
