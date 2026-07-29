#!/usr/bin/env bash
# =============================================================================
# Copy the config + GTFS index the container needs onto the internal disk.
#
# Why this exists: the repo lives on /Volumes/dev, an external NVMe. OrbStack
# shares /Volumes/* into its Linux VM, and that sharing layer has wedged the
# entire volume — readdir starts returning EINTR while SMART, df and the kernel
# log all stay clean (robogeosociety/infra#25). With no container binding
# /Volumes, that sharing can be switched off and the failure mode disappears.
#
# So the repo stays the source of truth, and the *running service* reads from a
# copy on the internal disk. This script moves data one way: repo -> runtime.
#
# Usage:
#   scripts/sync_runtime.sh            # sync config + GTFS index
#   scripts/sync_runtime.sh --config   # config only (skip the 199 MB index)
#   scripts/sync_runtime.sh --force    # also overwrite runtime service.yaml
#
# After syncing, recreate the container so it picks up the new paths:
#   docker rm -f transit-tracker && scripts/start_container.sh --detach
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TT_RUNTIME_DIR="${TT_RUNTIME_DIR:-$HOME/.local/share/transit-tracker}"

CONFIG_ONLY=false
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --config) CONFIG_ONLY=true ;;
        --force)  FORCE=true ;;
        *) echo "Unknown option: $arg"; echo "Usage: $0 [--config] [--force]"; exit 1 ;;
    esac
done

SRC_CONFIG="$PROJECT_DIR/.local"
SRC_DB="$PROJECT_DIR/data/gtfs_index.sqlite"

if [ ! -d "$SRC_CONFIG" ]; then
    echo "Error: no config to sync from: $SRC_CONFIG"
    exit 1
fi

case "$TT_RUNTIME_DIR" in
    /Volumes/*)
        echo "Error: TT_RUNTIME_DIR is on an external volume: $TT_RUNTIME_DIR"
        echo "  That defeats the point — it must sit on the internal disk."
        exit 1
        ;;
esac

mkdir -p "$TT_RUNTIME_DIR/config" "$TT_RUNTIME_DIR/data"

# -p preserves modes: mapbox.key / OBA.key / .env.influx are 0600 and must stay
# that way. Dotfiles are matched explicitly since * skips them.
#
# service.yaml is the one file the *service* writes (it's bound rw), so once a
# runtime copy exists it is authoritative — copying the repo version over it
# would roll back live settings. --force overrides that if you really mean to.
echo "Config: $SRC_CONFIG -> $TT_RUNTIME_DIR/config"
for f in "$SRC_CONFIG"/*.yaml "$SRC_CONFIG"/*.key "$SRC_CONFIG"/.env.*; do
    [ -f "$f" ] || continue
    if [ "$(basename "$f")" = "service.yaml" ] \
       && [ -f "$TT_RUNTIME_DIR/config/service.yaml" ] \
       && [ "$FORCE" != true ]; then
        echo "  skip service.yaml (runtime copy is authoritative; --force to overwrite)"
        continue
    fi
    cp -p "$f" "$TT_RUNTIME_DIR/config/"
done

if [ "$CONFIG_ONLY" = true ]; then
    echo "Skipping GTFS index (--config)."
elif [ -f "$SRC_DB" ]; then
    # service.yaml is written by the running service, so the runtime copy is
    # authoritative for it. Everything else flows repo -> runtime.
    echo "GTFS index: $SRC_DB -> $TT_RUNTIME_DIR/data ($(du -h "$SRC_DB" | cut -f1))"
    cp -p "$SRC_DB" "$TT_RUNTIME_DIR/data/gtfs_index.sqlite"
else
    echo "No GTFS index at $SRC_DB — skipping."
    echo "  Build it with: uv run python scripts/download_gtfs.py"
fi

echo
echo "Synced. Recreate the container to pick it up:"
echo "  docker rm -f transit-tracker && scripts/start_container.sh --detach"
