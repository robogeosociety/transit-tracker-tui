#!/usr/bin/env bash
# =============================================================================
# Start the Transit Tracker Docker container.
#
# Usage:
#   scripts/start_container.sh                        # foreground (--rm)
#   scripts/start_container.sh --detach               # background (detached)
#   scripts/start_container.sh --config path/to.yaml  # custom config
#   scripts/start_container.sh --detach --config path/to.yaml
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="transit-tracker"
CONTAINER_NAME="transit-tracker"
WS_PORT=8000
HTTP_PORT=8080
PROFILES_DIR="$PROJECT_DIR/.local"
SERVICE_YAML="$PROJECT_DIR/.local/service.yaml"
GTFS_DB="$PROJECT_DIR/data/gtfs_index.sqlite"
INFLUX_ENV_FILE="$PROJECT_DIR/.local/.env.influx"
INFLUX_NETWORK="influxdb_default"
DETACH=false

# ---- Parse arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --detach)
            DETACH=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--detach]"
            exit 1
            ;;
    esac
done

if [ ! -d "$PROFILES_DIR" ]; then
    echo "Error: Profiles directory not found: $PROFILES_DIR"
    exit 1
fi

cd "$PROJECT_DIR"

# ---- GTFS static schedule (optional) ----
GTFS_MOUNT=()
if [ -f "$GTFS_DB" ]; then
    echo "GTFS index found — scheduled trips will be merged with live data."
    GTFS_MOUNT=(-v "$GTFS_DB:/data/gtfs/gtfs_index.sqlite:ro")
else
    echo "No GTFS index at $GTFS_DB — only live data will be served."
    echo "  Run 'uv run python scripts/download_gtfs.py' to build it."
fi

# ---- Build image if not present ----
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Image '$IMAGE_NAME' not found — building..."
    docker build -t "$IMAGE_NAME" .
else
    echo "Image '$IMAGE_NAME' found."
fi

# ---- InfluxDB observability (optional) ----
INFLUX_MOUNT=()
INFLUX_NET_ARGS=()
if [ -f "$INFLUX_ENV_FILE" ]; then
    if docker network inspect "$INFLUX_NETWORK" >/dev/null 2>&1; then
        echo "InfluxDB env found — service will mirror metrics + trips to InfluxDB."
        INFLUX_MOUNT=(--env-file "$INFLUX_ENV_FILE")
        INFLUX_NET_ARGS=(--network "$INFLUX_NETWORK")
    else
        echo "InfluxDB env found at $INFLUX_ENV_FILE but docker network '$INFLUX_NETWORK' is missing — running without InfluxDB."
    fi
else
    echo "No InfluxDB env at $INFLUX_ENV_FILE — running without InfluxDB observability."
fi

# ---- Run container ----
# NOTE: the optional mount/network arrays below are expanded as
# ${ARR[@]+"${ARR[@]}"}, not the usual "${ARR[@]}". Under macOS's system bash
# (3.2) with `set -u`, expanding an EMPTY array the normal way is an "unbound
# variable" fatal error. That went unnoticed while InfluxDB was always up —
# INFLUX_NET_ARGS was never empty. InfluxDB was retired 2026-07-22, so both
# Influx arrays are now always empty and `--detach` died on line 94 before
# `docker run` ever ran. Do not "simplify" these back.
if [ "$DETACH" = true ]; then
    echo "Starting container '$CONTAINER_NAME' (detached, restart=always)..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart=always \
        -l dev.orbstack.http-port="$HTTP_PORT" \
        -p "$WS_PORT:$WS_PORT" \
        -p "$HTTP_PORT:$HTTP_PORT" \
        -v "$PROFILES_DIR:/config/profiles:ro" \
        -v "$SERVICE_YAML:/config/service.yaml" \
        ${GTFS_MOUNT[@]+"${GTFS_MOUNT[@]}"} \
        ${INFLUX_NET_ARGS[@]+"${INFLUX_NET_ARGS[@]}"} \
        ${INFLUX_MOUNT[@]+"${INFLUX_MOUNT[@]}"} \
        -e PROFILES_DIR=/config/profiles \
        -e SERVICE_SETTINGS_PATH=/config/service.yaml \
        -e TZ=America/Los_Angeles \
        "$IMAGE_NAME"

    # Wait for WebSocket port to accept connections (up to 60s)
    echo "Waiting for WebSocket port $WS_PORT to accept connections..."
    TIMEOUT=60
    ELAPSED=0
    while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
        if docker exec "$CONTAINER_NAME" sh -c "echo > /dev/tcp/localhost/$WS_PORT" 2>/dev/null || \
           nc -z localhost "$WS_PORT" 2>/dev/null; then
            echo "Container '$CONTAINER_NAME' is ready (WebSocket on :$WS_PORT)."
            exit 0
        fi
        sleep 1
        ELAPSED=$((ELAPSED + 1))
    done

    echo "Warning: WebSocket port $WS_PORT did not respond within ${TIMEOUT}s."
    echo "Container is running — check logs with: docker logs $CONTAINER_NAME"
    exit 1
else
    echo "Starting container '$CONTAINER_NAME' (foreground)..."
    docker run --rm \
        --name "$CONTAINER_NAME" \
        -p "$WS_PORT:$WS_PORT" \
        -p "$HTTP_PORT:$HTTP_PORT" \
        -v "$PROFILES_DIR:/config/profiles:ro" \
        -v "$SERVICE_YAML:/config/service.yaml" \
        ${GTFS_MOUNT[@]+"${GTFS_MOUNT[@]}"} \
        ${INFLUX_NET_ARGS[@]+"${INFLUX_NET_ARGS[@]}"} \
        ${INFLUX_MOUNT[@]+"${INFLUX_MOUNT[@]}"} \
        -e PROFILES_DIR=/config/profiles \
        -e SERVICE_SETTINGS_PATH=/config/service.yaml \
        -e TZ=America/Los_Angeles \
        "$IMAGE_NAME"
fi
