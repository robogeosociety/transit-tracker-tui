---
inclusion: auto
---

# Transit Board Configuration

## What Config Files Are

Config files are subscription configurations for the transit board hardware (ESP32 LED matrix displays). They define which stops and routes the board displays, not how the service itself runs. The same config should work whether connected to the reference container (`ghcr.io/tjhorner/transit-tracker-api`) or this project's custom container.

## Two-File Config System

Configuration is split into two concerns:

### 1. Board Subscription Profiles (per-profile YAML files)
Pure subscription data under the `transit_tracker:` key. These match the public reference schema and contain only stops, routes, display preferences, and abbreviations. No API keys, no polling intervals, no hardware config.

### 2. Service Settings (`.local/service.yaml`, gitignored)
Dev environment and instance settings: API credentials (`oba_api_key`), polling intervals (`check_interval_seconds`, `request_spacing_ms`), hardware config (`num_panels`, `panel_width`, `panel_height`), filtering (`arrival_threshold_minutes`), and service mode flags (`use_local_api`, `auto_launch_gui`). The `ServiceSettings` Pydantic model validates these; `SERVICE_SETTINGS_PATH`, `PROFILES_DIR` and `GTFS_DB_PATH` override the paths they load from. Falls back to `~/.config/transit-tracker/settings.yaml` for legacy installs.

At runtime, `TransitConfig` loads both and merges them into a single composite object. Access board settings via `config.transit_tracker.*` and service settings via `config.service.*`.

## Running Services

The transit tracker runs as a native launchd agent in production, or as local Python processes
in development:

**Production (launchd, Mac mini):**
- `launchctl list | grep transit-tracker` — check agent state
- `transit-tracker service [start|stop|restart|status]` — manages the launchd agent
- Serves WebSocket (:8000) + HTTP (:8080) from one asyncio process on `0.0.0.0`
- `KeepAlive` is the supervisor, auto-starts on login

**Development (local Python):**
- `uv run transit-tracker service` — WebSocket proxy + web server + GUI tray
- `uv run transit-tracker web` — HTTP web server only
- `transit-tracker gui` — macOS tray icon (auto-launched by service when `auto_launch_gui: true`)

## Config Profiles (`.local/` directory)

- `.local/home.yaml` — standard board config: two Sound Transit stops, public API, no extras. Valid for both reference and custom containers.
- `.local/adventure.yaml` — extended board config: ferries + Sound Transit + abbreviations. Only works with the custom container.
- `.local/needle_stops.yaml` — minimal board config: two Space Needle area stops
- `.local/config.yaml` — empty/default (no stops subscribed)
- `.local/accurate_config.yaml` — reference config for accuracy testing
- `.local/test_isolation_config.yaml` — test-only config

Reference config in the repo: `data/needle_stops.yaml` — the canonical example of a clean board subscription profile.

## Config Structure

Board subscription profiles use the `TransitTrackerSettings` Pydantic model nested under `transit_tracker:`:

```yaml
transit_tracker:
  base_url: "wss://tt.horner.tj/"
  time_display: arrival
  scroll_headsigns: false
  display_format: "{ROUTE}  {HEADSIGN}  {LIVE} {TIME}"
  stops:
    - stop_id: "st:1_8494"
      time_offset: "-7min"
      routes:
        - "st:40_100240"
  abbreviations: []
```

Service settings (`.local/service.yaml`, gitignored):

```yaml
last_config_path: /path/to/home.yaml
oba_api_key: your-key-here
check_interval_seconds: 30
request_spacing_ms: 500
arrival_threshold_minutes: 5
num_panels: 2
panel_width: 64
panel_height: 32
use_local_api: false
auto_launch_gui: true
```

## Config Loading Order

1. Check `get_last_config_path()` from `.local/service.yaml`
2. Check explicit path argument
3. Check `.local/<path>` fallback
4. Default to `TransitConfig()` (public API at `wss://tt.horner.tj/`)

## ID Prefix Conventions

- `st:` — Sound Transit / OneBusAway (e.g., `st:1_8494`, `st:40_100240`)
- `wsf:` — Washington State Ferries (e.g., `wsf:7`, `wsf:73`) — custom container only
- Bare numbers — raw OBA agency_id format

## Port Assignments

| Service | Port | Protocol |
|---------|------|----------|
| WebSocket server | 8000 | WS |
| HTTP web server | 8080 | HTTP |

## Key Environment Variables

- `OBA_API_KEY` — OneBusAway API key (fallback when not set in service settings)
- `PORT` — override HTTP web server port (default: 8080)
