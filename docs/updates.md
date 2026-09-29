# Updates

A curated, reverse-chronological log of notable changes to Transit Tracker. Renders on the
dev-wiki at `/dev-wiki/transit-tracker-tui/docs/updates`. (Auto PR/commit history also appears
on the dev-wiki changelog page.)

## 2026-09-21 — Off Docker: the sign runs natively under launchd

The departure sign's proxy now runs as a native launchd agent on the Mac mini
([#76](https://github.com/robogeosociety/transit-tracker-tui/pull/76)). OrbStack is gone
from that box, so the container had been dark since late July; this is what brought the
board back.

- `scripts/install_agent.sh` stages the repo to `~/.local/share/transit-tracker/app` on the
  **internal** disk, builds a `uv sync --frozen --no-dev --no-editable` venv, writes
  `org.eastsideurbanism.transit-tracker.plist`, and **asserts the agent actually loaded** —
  `launchctl bootstrap` fails over ssh, and a silently-unloaded agent is a blank sign.
- `KeepAlive` (`SuccessfulExit=false` + `Crashed=true`) replaces `--restart=always`, so a
  deliberate `launchctl stop` stays stopped. `ProcessType Interactive` opts out of the I/O
  throttling macOS applies to background jobs.
- Paths come from `SERVICE_SETTINGS_PATH` / `PROFILES_DIR` / `GTFS_DB_PATH` — the env
  overrides originally added for the container — so resolution never depends on install mode
  or cwd.
- **Brightness now follows the board, not a static IP.** The ESP32 is a DHCP client and its
  lease moved (`192.168.4.33` → `.41`), which pointed the daylight-dimming REST calls at a
  stranger's phone. `TransitServer` records the peer address of the connecting ESP32 and uses
  it; `service.device_ip` is the fallback for before it connects.
- Logs are `~/Library/Logs/transit-tracker.log`; `scripts/rotate_log.sh` copy-truncates past
  20 MiB (launchd holds the fd open, so renaming would keep filling the old file).
- Retired with the container: `Dockerfile`, `docker/entrypoint.sh`, `start_container.sh`,
  `stop_container.sh`, `tests/test_container.py`, the `docker` workflow and pytest marker, the
  `--containers` A/B mode, and the dead InfluxDB validator.

Peer addresses are real now, so the success signal is `Push to 192.168.4.41` — not the old
`Push to 192.168.215.1`, which was OrbStack's NAT gateway masquerading every LAN client.

## 2026-06-28 — Single-process container (single in-process asyncio loop)

The container now runs one asyncio process instead of two glued by a shell supervisor
([#69](https://github.com/robogeosociety/transit-tracker-tui/pull/69)).

- `docker/entrypoint.sh` resolves the active profile, then `exec`s a single process
  (`python -m transit_tracker.cli service`) that serves the WebSocket proxy (`:8000`), the
  monitor client, and the web server (`:8080`) in one asyncio event loop. Python is PID 1, so
  `docker stop`'s SIGTERM reaches it directly for a clean shutdown.
- The web server and the TileCache client now run in the same process as the proxy
  (`network/websocket_server.py`, `web/server.py`, `web/tile_cache.py`), so both ports are
  served from the one loop with no inner `wait_for_exit` shell babysitting.
- `--restart=always` is the sole supervisor.
