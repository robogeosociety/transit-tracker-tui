---
inclusion: auto
---

# macOS Menu Bar (Tray) Icon — `gui.py`

## Overview

`TransitTrackerApp` is a `rumps.App` that lives in the macOS menu bar as a 🚉 icon. It monitors the background WebSocket proxy service and displays live transit data, connected clients, and profile management. Entry point: `transit-tracker gui` CLI command (calls `gui.main()`).

## Architecture

- The app reads shared state from `~/.config/transit-tracker/service_state.json` (written by `TransitServer.sync_state()` in `websocket_server.py`)
- A `rumps.Timer` fires `update_state()` every 2 seconds to refresh all menu items
- A background daemon thread (`bg_fetch_loop`) does an initial WebSocket subscribe for immediate trip data, then polls the state file every 10 seconds
- Singleton enforcement via PID file at `$TMPDIR/transit_tracker_gui.pid`
- Auto-quits if the proxy service is dead for >10 seconds after startup

## Menu Structure

```
🚉 (or 📵 when rate-limited)
├── Status: Running (up Xm)
├── ✅ Healthy — N/M throttled (X%)    ← or 📵 Rate Limited
├── Last Proxy: HH:MM:SS
├── Messages Processed: N
├── ─────────────
├── 👥 Profiles
│   ├── ● active_config.yaml           ← checkmark + live trip rows
│   │   ├── 554  Downtown Seattle  ◉ 3m
│   │   ├── 271  Eastgate  ○ 12m
│   │   ├── ─────────────
│   │   ├── File: /path/to/config.yaml
│   │   └── Last Refresh: HH:MM:SS
│   └──   other_profile.yaml           ← one-shot preview trips
│       ├── SEA-BI  Seattle  ◉ 25m
│       └── File: /path/to/other.yaml
├── 🛜 Clients (N)
│   ├── transit-tracker-ec7db4 (192.168.5.248)
│   └── BackgroundMonitor (127.0.0.1)
├── ─────────────
├── 🐳 Container: Running (2 clients)  ← or "Stopped"
│   ├── Uptime: 1.2h
│   ├── Messages: 4,201
│   ├── Refresh Interval: 30s
│   ├── ✅ Healthy — 3/891 (0.3%)
│   ├── ─────────────
│   ├── transit-tracker-ec7db4 (172.17.0.1) [4 subs]
│   └── BackgroundMonitor (172.17.0.1) [4 subs]
├── Restart Container
├── Stop Container
├── ─────────────
├── Restart Transit Tracker Proxy
└── Shutdown Transit Tracker Proxy
```

## Visual Reference

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="620" font-family="SF Pro Text, Helvetica Neue, sans-serif" font-size="13">
  <defs>
    <linearGradient id="menubg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#3a3a3c"/>
      <stop offset="100%" stop-color="#2c2c2e"/>
    </linearGradient>
    <filter id="shadow" x="-4%" y="-2%" width="108%" height="108%">
      <feDropShadow dx="0" dy="2" stdDeviation="4" flood-opacity="0.5"/>
    </filter>
  </defs>

  <!-- macOS menu bar slice -->
  <rect width="320" height="28" rx="0" fill="#1e1e1e"/>
  <text x="290" y="19" text-anchor="middle" fill="#e5e5e7" font-size="16">🚉</text>

  <!-- Dropdown menu -->
  <rect x="16" y="36" width="288" height="568" rx="10" fill="url(#menubg)" filter="url(#shadow)"/>

  <!-- Status: Running -->
  <text x="30" y="62" fill="#e5e5e7">Status: Running (up 42m)</text>

  <!-- Rate limit healthy -->
  <text x="30" y="84" fill="#32d74b" font-size="12">✅ Healthy — 3/891 throttled (0.3%)</text>

  <!-- Last Proxy -->
  <text x="30" y="106" fill="#8e8e93">Last Proxy: 14:32:07</text>

  <!-- Messages -->
  <text x="30" y="128" fill="#8e8e93">Messages Processed: 2,847</text>

  <!-- Separator -->
  <line x1="30" y1="140" x2="290" y2="140" stroke="#48484a" stroke-width="0.5"/>

  <!-- Profiles header -->
  <text x="30" y="162" fill="#e5e5e7">👥 Profiles</text>
  <text x="276" y="162" fill="#48484a" font-size="11">▶</text>

  <!-- Active profile (expanded submenu hint) -->
  <rect x="36" y="172" width="256" height="108" rx="6" fill="#3a3a3c" opacity="0.6"/>
  <text x="46" y="192" fill="#0a84ff" font-size="12">● accurate_config.yaml</text>
  <text x="56" y="212" fill="#e5e5e7" font-size="11">554  Downtown Seattle  ◉ 3m</text>
  <text x="56" y="230" fill="#e5e5e7" font-size="11">271  Eastgate P&amp;R  ○ 12m</text>
  <text x="56" y="248" fill="#e5e5e7" font-size="11">SEA-BI  Seattle  ◉ 25m</text>
  <line x1="56" y1="258" x2="280" y2="258" stroke="#48484a" stroke-width="0.5"/>
  <text x="56" y="274" fill="#8e8e93" font-size="10">File: .local/accurate_config.yaml</text>

  <!-- Inactive profile -->
  <rect x="36" y="286" width="256" height="32" rx="6" fill="transparent"/>
  <text x="46" y="308" fill="#8e8e93" font-size="12">  home.yaml</text>

  <!-- Separator -->
  <line x1="30" y1="326" x2="290" y2="326" stroke="#48484a" stroke-width="0.5"/>

  <!-- Clients -->
  <text x="30" y="348" fill="#e5e5e7">🛜 Clients (2)</text>
  <text x="276" y="348" fill="#48484a" font-size="11">▶</text>

  <!-- Client list (expanded hint) -->
  <rect x="36" y="358" width="256" height="48" rx="6" fill="#3a3a3c" opacity="0.6"/>
  <text x="46" y="378" fill="#e5e5e7" font-size="11">transit-tracker-ec7db4 (192.168.5.248)</text>
  <text x="46" y="396" fill="#e5e5e7" font-size="11">BackgroundMonitor (127.0.0.1)</text>

  <!-- Separator -->
  <line x1="30" y1="418" x2="290" y2="418" stroke="#48484a" stroke-width="0.5"/>

  <!-- Container section -->
  <text x="30" y="440" fill="#e5e5e7">🐳 Container: Running (2 clients)</text>
  <text x="276" y="440" fill="#48484a" font-size="11">▶</text>

  <rect x="36" y="450" width="256" height="68" rx="6" fill="#3a3a3c" opacity="0.6"/>
  <text x="46" y="468" fill="#8e8e93" font-size="11">Uptime: 1.2h  ·  Messages: 4,201</text>
  <text x="46" y="486" fill="#8e8e93" font-size="11">Refresh Interval: 30s</text>
  <text x="46" y="504" fill="#32d74b" font-size="11">✅ Healthy — 3/891 (0.3%)</text>

  <!-- Container actions -->
  <text x="30" y="530" fill="#e5e5e7">Restart Container</text>
  <text x="30" y="552" fill="#e5e5e7">Stop Container</text>

  <!-- Separator -->
  <line x1="30" y1="562" x2="290" y2="562" stroke="#48484a" stroke-width="0.5"/>

  <!-- Restart -->
  <text x="30" y="580" fill="#e5e5e7">Restart Transit Tracker Proxy</text>

  <!-- Shutdown -->
  <text x="30" y="600" fill="#ff453a">Shutdown Transit Tracker Proxy</text>
</svg>
```

## Key Behaviors

- Icon changes to 📵 when `is_rate_limited` is true in service state
- Profile switching: clicking a profile calls `set_last_config_path()` and sends a `rumps.notification`; the proxy picks up the new config on its next refresh cycle
- Trip lines use `format_trip_line()` from `display.py` with the active profile's `display_format` template
- Inactive profiles get one-shot preview trips fetched via a separate WebSocket connection at startup (`_fetch_profile_preview`)
- Client list updates only when the set of client addresses changes (diffed via sorted address string)
- Profiles menu rebuilds when the profile list changes or every ~10 seconds for trip freshness

## Service Monitoring

- The GUI polls `http://localhost:8080/api/status` every 2 seconds (same timer as local state)
- The `/api/status` endpoint is served by the service's web server (`web.py`) and reads `service_state.json` live on each request (strips `last_message` to keep it lean)
- The service submenu shows: uptime, message count, refresh interval, throttle stats, and per-client details with subscription counts
- Restart/Stop buttons drive the launchd agent in background threads to avoid blocking the UI
- When the service is stopped, the submenu shows "Not running" and the restart button label changes to "Start Service"
- The icon switches to 📵 when `is_rate_limited` is true

## Service State File

`TransitServer.sync_state()` writes to `~/.config/transit-tracker/service_state.json`:

| Field | Type | Description |
|:---|:---|:---|
| `last_update` | float | Timestamp of last data refresh |
| `heartbeat` | float | Timestamp of last sync_state call |
| `start_time` | float | Server start timestamp |
| `messages_processed` | int | Total WebSocket messages sent |
| `pid` | int | Server process ID |
| `status` | str | Always `"active"` |
| `clients` | list | `[{address, name, subscriptions}]` |
| `client_count` | int | Number of connected WebSocket clients |
| `is_rate_limited` | bool | True if any stop is hitting 429s |
| `refresh_interval` | int | Current polling interval (with backoff) |
| `throttle_total` | int | Lifetime 429 count |
| `api_calls_total` | int | Lifetime OBA API calls |
| `throttle_rate` | float | `throttle_total / api_calls_total` |
| `uptime_hours` | float | Hours since server start |
| `last_message` | dict | Last broadcast payload (for bg_fetch_loop) |
| `config_path` | str | Active config file path |

## Dependencies

- `rumps` — macOS menu bar framework (macOS-only; not actually a declared dependency, see the proposal)
- `websockets` — sync client for initial trip fetch
- Reads from: `config.py` (`list_profiles`, `get_last_config_path`, `set_last_config_path`), `cli.py` (`PLIST_NAME`, `get_service_status`), `display.py` (`format_trip_line`)

## Service Management

- Restart: unloads/reloads the LaunchAgent plist at `~/Library/LaunchAgents/{PLIST_NAME}`
- Shutdown: unloads plist + sends SIGTERM to the proxy PID from state file, then quits the rumps app
- The GUI is macOS-only and is not started by the launchd service agent
