# Separation of Concerns Refactor

The original plan (ntfy.sh notification service) was superseded. The codebase grew into four
tangled concerns — a GTFS WebSocket proxy, a web monitor, an ESP32 firmware configurator,
and a TUI wrapper — all sharing one flat package with ad-hoc cross-module coupling. This
document tracks the refactor into cleanly separated packages within a single Python monorepo.

## Target Layout

```
src/
  tt_core/            Shared types, protocol models, metrics, logging, service-state I/O
  tt_proxy/           GTFS WebSocket proxy server + Mac container packaging
  tt_webmonitor/      Read-only observability web UI (dashboard, simulator, topology)
  tt_configurator/    Firmware management, device provisioning, config editing, dimming
  tt_tui/             Thin rich/questionary wrapper of uncertain utility
  transit_tracker/    Re-export shim (deleted last in Phase 7)
```

## Dependency Graph (enforced)

```
                   tt_tui
                  /  |   \
        tt_proxy  tt_configurator  tt_webmonitor
                  \  |   /
                   tt_core
```

No direct imports between `tt_proxy`, `tt_configurator`, and `tt_webmonitor`. Cross-process
communication happens only through `tt_core` types and the `service_state.json` file.

## Risky Couplings to Resolve First

- `SERVICE_STATE_FILE` read from 4 sites (`websocket_server.py:31`, `tui.py:85`, `web/server.py:177,428`, `monitor.py:53`) — consolidate into `tt_core.service_state`
- `dimming_loop` in proxy (`websocket_server.py:672`) owns configurator policy + ESPHome REST POST (`websocket_server.py:636–657`) — relocate to `tt_configurator` as a WebSocket client that emits `control:brightness` frames
- `_draft_config` module global in `web/api_handlers.py:105` — replace with `DraftConfigStore` class instance on the app
- Global `metrics` singleton (`metrics.py:188`) — keep in `tt_core`, document writer=proxy / reader=webmonitor contract
- `config.py` legacy-migration shim (`config.py:309–332`) absorbing old profile fields — keep in `tt_core.models`, make it a no-op on new configs

---

## Phase 0: Safety Net

- [ ] Freeze `scripts/ci_local.sh` as the green-bar oracle — full suite must pass before any moves
- [ ] Add `tests/test_import_layering.py` that AST-walks `src/` and asserts the dependency graph above (warn mode initially)
- [ ] Extract `schedule:subscribe` wire shape as typed pydantic models into `src/transit_tracker/protocol.py` (from implicit dicts in `websocket_server.py` ~280–360)
- [ ] Verify: full test suite green, `test_proxy_equivalence.py` and `test_cloud_equivalence.py` still pass

## Phase 1: Create `tt_core`

- [ ] Create `src/tt_core/__init__.py`
- [ ] `tt_core/models.py` — move from `config.py`: `TransitConfig`, `TransitStop`, `Abbreviation`, `ServiceSettings` (structure only), `TransitTrackerSettings`, `TransitConfig.load()`, `TransitConfig.save()`, legacy-migration helper. Drop dimming computation and `discover_profiles` (those move to configurator)
- [ ] `tt_core/protocol.py` — move pydantic wire models from Phase 0's `protocol.py`
- [ ] `tt_core/metrics.py` — move wholesale from `metrics.py`
- [ ] `tt_core/logging.py` — move wholesale from `logging.py`
- [ ] `tt_core/service_state.py` — extract `SERVICE_STATE_FILE` path constant, `read_snapshot()`, `write_snapshot()` helpers (replacing 5 duplicated read/write sites)
- [ ] `tt_core/display.py` — move display format formatter (`format_trip_line` and template helpers)
- [ ] Leave `src/transit_tracker/{config,metrics,logging,display,protocol}.py` as thin re-exports from `tt_core`
- [ ] Verify: `test_config*.py`, `test_metrics.py`, `test_logging_module.py`, `test_protocol_comparison.py`, `test_service_isolation.py` green

## Phase 2: Carve Out `tt_proxy`

- [ ] Create `src/tt_proxy/__init__.py`
- [ ] `tt_proxy/server.py` — move `TransitServer`, `data_refresh_loop`, `broadcast_loop`, rate-limit backoff, `WSF_VESSELS` ferry logic from `network/websocket_server.py` (lines 1–625). **Exclude** dimming_loop (lines 672–684) and ESPHome REST POST (lines 636–657). Keep `control:brightness` relay (lines 649–655)
- [ ] `tt_proxy/oba_client.py` — move `transit_api.py` wholesale
- [ ] `tt_proxy/gtfs.py` — move `gtfs_schedule.py` wholesale
- [ ] `tt_proxy/throttle.py` — extract rate-limit/backoff + `throttle_log.jsonl` writer from `websocket_server.py:96` area
- [ ] `tt_proxy/__main__.py` — `python -m tt_proxy` entry point (pure asyncio, no dimming)
- [ ] ~~`tt_proxy/container/`~~ — **obsolete:** the container was retired 2026-09-21 (PR #76);
      the deployment unit is a launchd agent (`scripts/install_agent.sh`). Original text: move `Dockerfile`, `docker/` contents, `scripts/start_container.sh`, `scripts/stop_container.sh`, `scripts/download_gtfs.py`, `scripts/verify_launch.py`
- [ ] `tt_proxy/container/compose.yaml` — new compose file: `tt-proxy` service, volumes for `service_state.json` + `gtfs_index.sqlite`, env vars (`OBA_API_KEY`, `GTFS_DB_PATH`, `TT_STATE_DIR`, `TT_LOG_LEVEL`), colima/docker-desktop agnostic for Mac
- [ ] Leave `src/transit_tracker/network/websocket_server.py` and `transit_api.py` and `gtfs_schedule.py` as re-export shims
- [ ] Verify: `test_network.py`, `test_transit_api.py`, `test_gtfs.py`, `test_proxy_equivalence.py`, `test_cloud_equivalence.py`, `test_metrics.py`, `test_container.py` green

## Phase 3: Carve Out `tt_configurator`

- [ ] Create `src/tt_configurator/__init__.py`
- [ ] `tt_configurator/api.py` — move entire `web/api_handlers.py`. Replace `_draft_config` module global with `DraftConfigStore` class instance bound to app
- [ ] `tt_configurator/pages.py` — configurator-only HTML stubs (station manager marked TODO/incomplete)
- [ ] `tt_configurator/spec.py` — configurator portion of `web/spec.py`
- [ ] `tt_configurator/server.py` — small HTTP app mounting configurator routes + WebSocket client that connects to `tt_proxy` for `control:brightness` emission
- [ ] `tt_configurator/hardware.py` — move `hardware.py` wholesale (ESPHomeFlasher, flash_hardware, load_hardware_config, flash_base_firmware, get_usb_devices, is_bootstrapped)
- [ ] `tt_configurator/capture.py` — move `capture.py` wholesale
- [ ] `tt_configurator/dimming.py` — move from `config.py`: `build_daylight_schedule`, `evaluate_dimming_schedule`, `DimmingEntry`, `DimmingScheduleSettings`. Move from `websocket_server.py`: `dimming_loop` (672–684) + ESPHome REST POST block (636–657). Loop now runs as a configurator-side WebSocket client
- [ ] `tt_configurator/profiles.py` — move `discover_profiles`, `save_service_settings`, profile-activation logic from `config.py`
- [ ] `tt_configurator/verify_client.py` — move `network/websocket_service.py`
- [ ] Leave `src/transit_tracker/{hardware,capture}.py` and `web/api_handlers.py` as re-export shims
- [ ] Verify: `test_flashing.py`, `test_serial_protocol.py`, `test_firmware_contracts.py`, `test_firmware_correctness.py`, `test_display.py`, `test_dimming*.py`, `test_brightness.py`, `test_profiles_menu.py`, `test_live_config_isolation.py` green

## Phase 4: Carve Out `tt_webmonitor`

- [ ] Create `src/tt_webmonitor/__init__.py`
- [ ] `tt_webmonitor/server.py` — kept routes from `web/server.py`: `/`, `/dashboard`, `/monitor`, `/simulator`, `/spec`, `/ws`, `/api/status`, `/api/metrics`, `/api/logs`, `/api/stops`. All `service_state.json` reads use `tt_core.service_state.read_snapshot()`
- [ ] `tt_webmonitor/pages.py` — move `generate_index_html`, `generate_monitor_html`, `generate_dashboard_html`, `generate_simulator_html` from `web/pages.py`
- [ ] `tt_webmonitor/spec.py` — monitor portion of `web/spec.py`
- [ ] `tt_webmonitor/simulator.py` — move `simulator.py` wholesale (read-only LED renderer)
- [ ] `tt_webmonitor/topology.py` — move `monitor.py` wholesale (read-only state observer)
- [ ] Leave `src/transit_tracker/web/` and `simulator.py` and `monitor.py` as re-export shims
- [ ] Verify: monitor half of `test_web.py`, `test_simulator.py`, `test_simulator_mock_equivalence.py` green

## Phase 5: Carve Out `tt_tui`

- [ ] Create `src/tt_tui/__init__.py`
- [ ] `tt_tui/cli.py` — move `cli.py` lifecycle logic. Docker compose path now points to `tt_proxy/container/compose.yaml`. Start configurator + webmonitor as local asyncio tasks or separate launchd plists on macOS
- [ ] `tt_tui/menus.py` — extract main_menu, profiles_menu, manage_service_menu from `tui.py`
- [ ] `tt_tui/wizards.py` — extract change_threshold_wizard, change_brightness_wizard, change_panels_wizard, manage_dimming_schedule_wizard from `tui.py`
- [ ] `tt_tui/live.py` — extract make_dashboard, ask_with_live_dashboard, hardware_monitor from `tui.py`
- [ ] All cross-talk uses public APIs of `tt_proxy`, `tt_configurator`, `tt_webmonitor` — no reaching into private state
- [ ] Leave `src/transit_tracker/{cli,tui}.py` as re-export shims
- [ ] Verify: `test_cli.py`, `test_tui_main_menu.py`, `test_tui_wizards.py`, `test_tui_live_refresh.py` green

## Phase 6: Rewire `pyproject.toml`

- [ ] Update `[project.scripts]`:
  - `transit-tracker = "tt_tui.cli:main"`
  - `transit-tracker-capture = "tt_configurator.capture:main"`
- [ ] Add direct-invocation entry points:
  - `tt-proxy = "tt_proxy.__main__:main"`
  - `tt-configurator = "tt_configurator.server:main"`
  - `tt-webmonitor = "tt_webmonitor.server:main"`
- [ ] Update `[tool.uv_build]` to list all five packages under `src/`
- [ ] Update `[tool.coverage.run]` source paths
- [ ] Update `[tool.mutmut]` paths
- [ ] Update `[tool.ruff.lint.per-file-ignores]` for new page file paths
- [ ] Verify: `uv sync` succeeds, all three new entry points start cleanly, `transit-tracker` still launches TUI, `./scripts/ci_local.sh` green

## Phase 7: Delete the Shim

- [ ] Convert remaining `scripts/*.py` imports from `transit_tracker.*` to new package imports
- [ ] Delete `src/transit_tracker/` entirely
- [ ] Flip `tests/test_import_layering.py` from warn to fail mode
- [ ] Verify: `grep -r "from transit_tracker" src/ scripts/` returns nothing
- [ ] Verify: full test suite green, `./scripts/ci_local.sh` green

---

## Test Reorganization

```
tests/
  conftest.py              Shared fixtures (stays)
  core/                    test_config*.py, test_metrics.py, test_logging_module.py,
                           test_protocol_comparison.py, test_service_isolation.py
  proxy/                   test_network.py, test_transit_api.py, test_gtfs.py,
                           test_proxy_equivalence.py, test_cloud_equivalence.py,
                           test_container.py
  configurator/            test_flashing.py, test_serial_protocol.py, test_firmware_*.py,
                           test_display.py, test_dimming*.py, test_brightness.py,
                           test_profiles_menu.py, test_live_config_isolation.py
  webmonitor/              test_simulator.py, test_simulator_mock_equivalence.py
  tui/                     test_cli.py, test_tui_*.py
```

Contract tests (`test_proxy_equivalence.py`, `test_cloud_equivalence.py`, `test_protocol_comparison.py`)
are the acceptance gate — must pass before any phase merges.

## Per-Phase Verification

| Phase | Gate tests |
|-------|-----------|
| 0 | Full suite + new `test_import_layering.py` |
| 1 | `test_config*`, `test_metrics`, `test_logging_module`, `test_protocol_comparison` |
| 2 | `tests/proxy/**` incl. `test_proxy_equivalence`, `test_cloud_equivalence` |
| 3 | `tests/configurator/**` incl. `test_dimming*`, `test_brightness`, `test_firmware_contracts` |
| 4 | `tests/webmonitor/**` incl. `test_simulator_mock_equivalence` |
| 5 | `tests/tui/**` + `./scripts/ci_local.sh` |
| 6 | Fresh `uv sync` + all entry points start + full suite |
| 7 | Zero `transit_tracker.*` imports + full suite + `ci_local.sh` |

## Files That Stay Put

`LICENSE`, `README.md`, `CLAUDE.md`, `TESTING.md`, `data/`, `notebooks/`, `docs/`,
`hardware_capture.json`, `validate_home.py`, and research/ops scripts in `scripts/`
(`auto_crop.py`, `average_timelapse.py`, `build_route_map.py`, `build_stations_geojson.py`,
`capture_cam.py`, `compare_*.py`, `process_hardware_img.py`, `render_sim.py`, etc.)

## Out of Scope

- No new features or API surface changes
- No removal of Docker/launchctl service management UX
- No new dependencies
- No changes to the `schedule:subscribe` wire protocol
- No changes to YAML config file format
