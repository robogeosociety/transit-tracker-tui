---
inclusion: auto
---

# Development Workflow

## Environments

There are two environments. Do not conflate them.

### Local (Development)

Run the Python server directly for development and testing:

```
uv run transit-tracker service    # WebSocket proxy :8000 + web :8080 + GUI tray
uv run transit-tracker web        # HTTP web server only
uv run transit-tracker simulator  # TUI LED matrix simulator (UAT visual check)
```

The TUI simulator (`transit-tracker simulator`) is the primary UAT tool during development — it renders the LED matrix output in the terminal so you can visually verify trip formatting, colors, and layout without the physical board. This will eventually be replaced by the web simulator (`/simulator` endpoint) running inside the configurator local webapp.

Jupyter notebooks live alongside scripts for data processing tasks (walkshed generation, GTFS analysis, route mapping). Use Playwright for browser-based validation of web endpoints (`/walkshed`, `/simulator`, `/spec`).

All code changes are tested here first. Run `uv run pytest -v -m "not e2e"` before pushing.

### Production

A native launchd agent on the Mac mini (`org.eastsideurbanism.transit-tracker`), installed by
`scripts/install_agent.sh`. `KeepAlive` is the supervisor; the agent auto-starts on login.

- Ports: 8000 (WS), 8080 (HTTP) — bound on `0.0.0.0`, no port mapping
- Config: `~/.local/share/transit-tracker/config/` via `SERVICE_SETTINGS_PATH` / `PROFILES_DIR`
- Status: `launchctl list | grep transit-tracker`, `curl http://localhost:8080/transit-tracker`
- Logs: `~/Library/Logs/transit-tracker.log`

**Do not rebuild, restart, or touch the production container unless explicitly instructed.** It is serving the physical transit board and connected ESP32 hardware.

The container is the final UAT phase in a spec job. After all tasks pass locally, the last step is building a new image, swapping the container, and verifying on the live board.

## Spec Task Lifecycle

1. Implement and test locally (Python server, pytest, Playwright)
2. All tests pass (`-m "not e2e"`)
3. Run TUI simulator (`transit-tracker simulator`) for visual UAT during development
4. When instructed: redeploy with `scripts/install_agent.sh`, verify on live hardware
5. UAT confirmation from user completes the spec

## Tools

| Tool | Purpose |
|------|---------|
| `uv run pytest -m "not e2e"` | Unit/integration tests |
| Jupyter notebooks | Data processing, walkshed generation, GTFS analysis |
| Playwright | Browser validation of web endpoints |
| `scripts/verify_cloud_equivalence.py` | Compare the local service against the cloud baseline |
| `scripts/install_agent.sh` | Install/redeploy the production launchd agent |
| `scripts/rotate_log.sh` | Rotate `~/Library/Logs/transit-tracker.log` |

## Service Management

The CLI manages the launchd agent:

```
transit-tracker service start    # launchctl load
transit-tracker service stop     # launchctl unload
transit-tracker service restart  # launchctl kickstart -k
transit-tracker service status   # launchctl list
```
