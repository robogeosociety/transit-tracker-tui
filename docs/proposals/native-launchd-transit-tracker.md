---
type: proposal
implemented_by: []
tracking: 0
---

# Proposal — take the departure sign off Docker: native launchd + a uv venv

`transit-tracker` is one of the last two OrbStack tenants on the Mac mini. The
other is `discobot-valkey`, owned by `robogeosociety/infra`. The four discobot
workloads have their own proposal — [robogeosociety/discobots#135][d135] — and
that one says, correctly, that it *does not* remove OrbStack, because this
container and valkey keep the engine resident. This is the missing half.

Unlike the discobots, this workload is not a Discord panel that can be dark for
a day. It drives a physical ESP32 LED departure board on the wall at
`192.168.4.33`. **Dead is a blank sign.** Everything below is arranged around
that one constraint, and the migration is deliberately slower and more paranoid
than [#135][d135]'s as a result.

Everything numeric here was measured read-only on the mini on 2026-07-29/30.
Nothing on the mini was started, stopped, or modified to write this.

[d135]: https://github.com/robogeosociety/discobots/pull/135

---

## 1. What runs today

```
$ docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
transit-tracker   Up 24 hours   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp,
                                0.0.0.0:8080->8080/tcp, [::]:8080->8080/tcp
```

| | |
|---|---|
| Image | `transit-tracker:latest`, `sha256:b833353b…`, **431.8 MB**, built **2026-06-30** |
| Live memory | **54.8 MiB** RSS |
| Supervision | `--restart=always`. Nothing else. No health check, no memory limit, no CPU limit. |
| Ports | `8000` WebSocket (the ESP32), `8080` HTTP UI — both published on `0.0.0.0` **and** `[::]` |
| Label | `dev.orbstack.http-port=8080` → `https://transit-tracker.orb.local` |
| Entry | `docker/entrypoint.sh` → resolves a profile → `exec python -m transit_tracker.cli service` |
| User | non-root `transit` (uid 1000), `WORKDIR /app` |

Bind mounts, as deployed:

```
~/.local/share/transit-tracker/config                     -> /config/profiles          ro
~/.local/share/transit-tracker/config/service.yaml        -> /config/service.yaml      rw
~/.local/share/transit-tracker/data/gtfs_index.sqlite     -> /data/gtfs/…              ro
```

That layout comes from **PR #74**, which is **still open** but whose branch is
what is checked out and running on the mini (`/Volumes/dev/transit_tracker` at
`fcd23d3`, clean). Worth knowing before reading anything else: *the box is
ahead of `main`.*

The GTFS index is **209,166,336 bytes (199.5 MiB)**, last written **2026-03-18**,
mounted read-only, produced by `scripts/download_gtfs.py`.

InfluxDB is retired. `scripts/start_container.sh` still has the
`--env-file` / `--network influxdb_default` branch, and a stale
`config/.env.influx` (188 bytes, May 25) still sits in the profiles directory —
but the `influxdb_default` network is gone, so the branch never fires. It should
be deleted with the rest of the container path in Phase 4, not before.

### Health, verified live

```
$ curl -o /dev/null -w '%{http_code}' localhost:8080/transit-tracker
200
$ curl -s localhost:8080/transit-tracker/api/tiles
{"tiles":[{"stop_id":"st:40_E01-T2", … "is_realtime":true,
  "trip_id":"40_LLR_2026-07-30_…_2LINE_4036"} …
```

Both realtime (`is_realtime: true`) and GTFS-schedule-backed (`false`)
departures are present, which is the proof that the relocated 199 MB index is
actually being read.

---

## 2. The dependency question, and it resolves cleanly

The interesting claim about this workload is that the Dockerfile deliberately
strips macOS-only dependencies so the image can build on Linux — which would
make the *native macOS* target the easier one. That is broadly right, but the
details differ from the folklore, and two of them matter.

**`pyproject.toml` has exactly one platform-marked dependency:**

```toml
"pyobjc-framework-quartz>=12.1; sys_platform == 'darwin'",
```

`pyobjc-core` and `pyobjc-framework-cocoa` arrive transitively. **`rumps` is not
a dependency at all** — it is not in `pyproject.toml` and it is not in
`uv.lock`. The Dockerfile's `--no-install-package rumps` is a no-op, and its
`--no-install-package pyobjc-*` flags are redundant with the `sys_platform`
marker that would have excluded them on Linux anyway. The "exclusion mechanism"
is belt-and-braces around a marker that already does the work.

**Nothing on the service path imports them.** Grepping `src/` for `Quartz`,
`AppKit`, `Cocoa`, `pyobjc`, `rumps` returns **zero hits**. The only users are
three diagnostic scripts — `scripts/check_window.py`, `scripts/check_gui_init.py`,
`scripts/diagnose_gui.py` — none of which the service touches. (`check_gui_init.py`
imports `rumps`, which isn't installed in *any* environment; that script is
already broken and this proposal doesn't change that.)

**And it was tested, not assumed.** On a macOS arm64 box, from a scratch copy of
`pyproject.toml` + `uv.lock` + `src/` + `data/`, pinned to 3.13:

```
$ uv sync --no-dev --frozen
… + pyobjc-core==12.1
  + pyobjc-framework-cocoa==12.1
  + pyobjc-framework-quartz==12.1
  + numpy==2.4.3  opencv-python==4.13.0.92  opencv-python-headless==4.13.0.92
  + pillow==12.1.1  pydantic==2.12.5  websockets==16.0  …
$ .venv/bin/python -V
Python 3.13.14
$ .venv/bin/python -c 'import transit_tracker.cli; \
    from transit_tracker.network.websocket_server import run_server; \
    from transit_tracker.web import run_web; print("imports OK")'
[INFLUXDB] InfluxDB writer disabled (INFLUXDB_TOKEN unset)
imports OK
```

Resolved from the lockfile, no build-from-source, no compiler. Venv size
**206 MB** — versus a 431.8 MB image. So the answer is: **the macOS-native
runtime is a strict superset of the container's, and it installs and imports
clean.** This is the least risky part of the migration.

Two caveats, stated rather than buried:

- The image is `python:3.13-slim` (`PYTHON_VERSION=3.13.14` per `docker inspect`).
  `requires-python = ">=3.13"`. The mini's `python3` is **3.14.5** (Homebrew) and
  its uv already has 3.14.3 and 3.12.12 downloaded but **not 3.13**. A
  `.python-version` of `3.13` makes uv fetch a managed CPython 3.13.14 — the
  same patch the image runs. **`uv.lock` + a pinned managed 3.13 is a tighter
  pin than `FROM python:3.13-slim`**, which floats within 3.13. Do not let the
  venv fall through to the Homebrew 3.14.
- The image installs with `--no-editable`; a plain `uv sync` installs the project
  **editable**. That is not cosmetic here — see §5.

---

## 3. Target layout

Everything on the **internal disk**. `/Volumes/dev` is the external disk that
wedged twice ([tommybot#101][t101], [infra#25][i25]); PR #74 exists precisely
because a wedge there took the sign down, and re-introducing a runtime
dependency on it would undo that PR.

```
~/.local/share/transit-tracker/
├── app/                  # rsync'd checkout of the repo (code only)
│   ├── src/  data/  pyproject.toml  uv.lock
│   └── .venv/            # uv venv, managed CPython 3.13, 206 MB
├── config/               # ALREADY EXISTS — profiles + service.yaml + keys
└── data/                 # ALREADY EXISTS — gtfs_index.sqlite (199.5 MiB)
```

`config/` and `data/` are untouched by this proposal. They are already on the
internal disk, already the live source of truth, and the container already reads
them. The migration only changes *what process opens those files.*

Why `app/` is a staged copy rather than running out of `/Volumes/dev/transit_tracker`:
launchd + external volume is the exact combination that produces
`Interrupted system call`, which `com.discobots.minivitals.plist` documents in
its own header and which [#135][d135] found 45 consecutive times in the
discobots CD log. Not worth re-learning.

[t101]: https://github.com/robogeosociety/tommybot/issues/101
[i25]: https://github.com/robogeosociety/infra/issues/25

### What happens to `TT_RUNTIME_DIR`

PR #74 added `TT_RUNTIME_DIR` (default `~/.local/share/transit-tracker`) and
`scripts/sync_runtime.sh` so the *container* could bind-mount off the internal
disk. A native process needs no bind mounts, so the obvious reading is that both
become vestigial.

They don't, and the reason is the one PR #74 was written for. `_PROJECT_ROOT` in
`config.py` and `gtfs_schedule.py` is module-relative:

```python
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVICE_SETTINGS_FILE = os.path.join(_PROJECT_ROOT, ".local", "service.yaml")
```

Under an **editable** install — which is what plain `uv sync` gives you —
`__file__` is in the checkout, so `_PROJECT_ROOT` is the checkout, so
`.local/service.yaml` and `data/gtfs_index.sqlite` resolve **back into the repo**.
Run the venv out of `/Volumes/dev/transit_tracker` and the service silently
re-acquires the external-disk dependency PR #74 removed, with no bind mount
anywhere to make it visible.

So the recommendation is: **keep `TT_RUNTIME_DIR` as the naming convention, keep
`sync_runtime.sh` for seeding a fresh box, and make the plist set the two env
overrides explicitly** so path resolution never depends on install mode or cwd:

| Env var | Value | Where it's read |
|---|---|---|
| `SERVICE_SETTINGS_PATH` | `…/transit-tracker/config/service.yaml` | `config.py:_resolve_settings_path` (highest priority) |
| `PROFILES_DIR` | `…/transit-tracker/config` | `config.py:list_profiles` |
| `GTFS_DB_PATH` | `…/transit-tracker/data/gtfs_index.sqlite` | `gtfs_schedule.py` |
| `TZ` | `America/Los_Angeles` | matches the container's env today |

All three overrides already exist in the code — they were added *for* the
container. The native agent reuses them verbatim.

### 3a. The config landmine

This is the single most likely way to blank the sign, and it is not obvious.

`run_full_service()` does:

```python
path = get_last_config_path()
if path and os.path.exists(path):
    config = TransitConfig.load(path)
else:
    config = TransitConfig.load()          # <- defaults
```

The live, bind-mounted-rw, service-written `service.yaml` currently contains:

```yaml
last_config_path: /config/profiles/home-train.yaml
device_ip: 192.168.4.33
use_local_api: true
```

`/config/profiles/…` is a **container path**. A native process will find
`os.path.exists()` false and fall through to `TransitConfig.load()` defaults —
the sign will not crash, it will come up **subscribed to nothing**. The
container never hits this because `entrypoint.sh` has a `_resolve_default_profile`
step that rewrites `last_config_path` when it's dangling, preferring `home.yaml`
— which points at `wss://tt.horner.tj/`, not the local server, and is *not* the
active profile. Falling into the entrypoint's fallback would be its own quiet
wrong answer.

**Therefore:** installing the native agent must rewrite `last_config_path` to
`~/.local/share/transit-tracker/config/home-train.yaml` — and, because
`service.yaml` is written back by the running service, that rewrite has to happen
with the container **stopped**, in the same window as the switchover, or it will
be clobbered. Phase 2 below is built around this.

---

## 4. The launchd agent

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.eastsideurbanism.transit-tracker</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/tommydoerr/.local/share/transit-tracker/app/.venv/bin/python</string>
    <string>-m</string><string>transit_tracker.cli</string>
    <string>service</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/tommydoerr/.local/share/transit-tracker/app</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>/Users/tommydoerr</string>
    <key>TZ</key><string>America/Los_Angeles</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>SERVICE_SETTINGS_PATH</key>
      <string>/Users/tommydoerr/.local/share/transit-tracker/config/service.yaml</string>
    <key>PROFILES_DIR</key>
      <string>/Users/tommydoerr/.local/share/transit-tracker/config</string>
    <key>GTFS_DB_PATH</key>
      <string>/Users/tommydoerr/.local/share/transit-tracker/data/gtfs_index.sqlite</string>
  </dict>

  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>10</integer>

  <key>StandardOutPath</key>
  <string>/Users/tommydoerr/Library/Logs/transit-tracker.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/tommydoerr/Library/Logs/transit-tracker.log</string>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
```

Notes, each of which is a decision:

- **The label already exists in the code.** `cli.py` defines
  `PLIST_NAME = "org.eastsideurbanism.transit-tracker.plist"` and
  `_manage_service_launchctl()` already implements start/stop/restart/status via
  `launchctl` — including `kickstart -k gui/$UID/$label`. `manage_service()`
  currently prefers Docker and falls back to launchd only when no container
  exists, so **removing the container automatically re-activates the launchd
  path that is already written**. `transit-tracker service status` keeps working.
  There is no `transit-tracker install` command, though `cli.py:129` tells you to
  run one; writing the plist is the installer's job, and that error string should
  be corrected in the same PR.
- **`KeepAlive` as a dict, not `<true/>`.** Plain `KeepAlive` also restarts after
  a *deliberate* `launchctl stop`, which turns every maintenance action into a
  fight. `SuccessfulExit=false` + `Crashed=true` gives `--restart=always`
  semantics — respawn on crash or non-zero exit — while still letting an operator
  stop it. `ThrottleInterval 10` keeps a crash loop from hammering the OBA API.
- **`ProcessType Interactive`.** The default `Standard` lets macOS throttle
  I/O and CPU on a background job. This is a soft-realtime feed pushing every 30 s
  to a wall display; `Interactive` opts out of that throttling. (The other option,
  `Background`, is what `com.tommy.orbstack-log-capture` uses — appropriate for a
  daily snapshotter, wrong here.)
- **No memory or CPU limit.** Same as today: the container sets none. 54.8 MiB of
  a 8 GB box that is already at **7.6 GB of 9.2 GB swap used** — worth watching,
  not worth capping, and capping would be a *new* behaviour rather than parity.
- **LaunchAgent, not LaunchDaemon** — see open question 1. An agent in
  `gui/$(id -u)` needs a logged-in session, which is exactly the constraint
  OrbStack.app already has today, so this is parity, not a regression. A
  LaunchDaemon would be strictly better for unattended reboot and is worth doing;
  it needs `sudo` and is therefore a human task, not an agent one.

### LAN reachability — the part that can silently blank the sign

The service **already binds `0.0.0.0`** with no change required:

```
websocket_server.py:953   async def run_server(host: str = "0.0.0.0", port: int = 8000, …)
web/server.py:306         async def run_web(config, host: str = "0.0.0.0", port: int = None, …)
```

So a native process listens on every interface, exactly as `-p 8000:8000` does.
The difference is *who owns the socket*, and macOS cares:

```
$ lsof -nP -iTCP:8000 -sTCP:LISTEN
OrbStack  30343  tommydoerr  75u  IPv4  TCP *:8000 (LISTEN)

$ socketfilterfw --getglobalstate ; --getstealthmode
Firewall is enabled. (State = 1)
Firewall stealth mode is on
```

The Application Firewall is **on, with stealth mode on**. Today it permits
`OrbStack Helper`, which is in the allow list. A new `python` binary is not — and
the "Do you want to accept incoming network connections?" dialog **cannot be
answered by a headless launchd job over ssh.** Left unhandled, the agent starts,
logs `Starting Transit Tracker API on 0.0.0.0:8000`, looks perfectly healthy in
`launchctl list`, and the ESP32 simply never connects. That is the blank-sign
failure mode, arriving with a green status light.

Two mitigating facts and one required step:

1. `--getallowsigned` reports **"Automatically allow downloaded signed software
   ENABLED"** — uv's managed CPython builds are signed, so this may pass
   silently. *May.*
2. There is precedent in the allow list already:
   `~/.local/share/uv/python/cpython-3.14.3-macos-aarch64-none/bin/python3.14 —
   (Allow incoming connections)`. A uv-managed interpreter has been through this
   before. But it is keyed on the **resolved binary path**, and a 3.13 venv
   symlinks to a *different* path, so the existing entry does not cover us.
3. **Required, and it needs `sudo`:**

   ```sh
   PY=$(readlink -f ~/.local/share/transit-tracker/app/.venv/bin/python)
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY"
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PY"
   ```

   This is a **human task** — file it with `/gh-task-human` before Phase 2, not
   during it. And it must be re-run whenever the pinned CPython patch changes,
   because the path changes with it. That recurring trap deserves a line in the
   installer that checks `--listapps` for the current binary and refuses to
   proceed if it's missing.

Also note the mini has **two interfaces on the LAN** — `en0 192.168.5.232` and
`en1 192.168.5.233`, both in `192.168.4.0/22`, gateway `192.168.4.1`. Binding
`0.0.0.0` covers both, plus Tailscale `100.119.31.10`. That is identical exposure
to what the published container gives today; it is not a new surface.

### The success observable changes, and you must expect that

The container's logs read:

```
[SERVER] Push to 192.168.215.1: 2  Downtown Redmond  ◉ Now | …
[SERVER] Client connected: ('192.168.215.1', 61219) ua='ESP32 Websocket Client'
```

`192.168.215.1` is **not the ESP32.** It is `bridge101`, OrbStack's NAT gateway —
every LAN client is masqueraded behind it, so the container has never seen a real
peer address. The ESP32 is `192.168.4.33` (`device_ip` in `service.yaml`).

**Natively there is no NAT, so the correct success signal is
`Push to 192.168.4.33`, not `Push to 192.168.215.1`.** Anyone grepping for the
old string will conclude the migration failed when it succeeded — or, worse,
write a health check on the old string that can never pass. This is a small
observability *gain* (real peer addresses in `Client connected:` lines, and the
per-stop UA logging from #60 finally distinguishes clients), but it invalidates
every existing log expectation.

### Logs and rotation

`docker logs` goes away. Output is plain text on stdout (`PrettyFormatter`; the
`--log-json` / `TT_LOG_JSON` path exists and could be turned on later) and
launchd appends it to `~/Library/Logs/transit-tracker.log`.

**Rotation is genuinely lost, not mitigated.** Docker's json-file driver rotates;
launchd's `StandardOutPath` does not. This is not hypothetical — [#135][d135]
measured `/tmp/discobots-minivitals.log` at 4.06 MB unrotated. This service logs
roughly 4 lines per 30 s refresh plus one per push, so estimate 10–20 MB/month.
`/` has **35 GiB available**, so it is a tidiness problem before it is an outage,
but it should still be handled: either a `newsyslog.d` conf (needs `sudo`; the
directory currently holds only Apple's five defaults) or a size check in the
installer. Same open question as [#135][d135] item 7 — it should get **one**
answer across both repos, not two.

The in-app `/transit-tracker/logs` live tail is served from an in-process ring
buffer and is unaffected.

---

## 5. Cutover — the sign does not go dark

Four phases. **The image, `scripts/start_container.sh`, and `stop_container.sh`
all stay usable and untouched until Phase 4.** Rollback is one command at every
point before that.

### Phase 0 — clear the stale supervisor. Blocking.

This is the prerequisite everything else rests on, and it is live right now:

```
$ ps auxww | grep supervise
tommydoerr 30909  /bin/zsh /Volumes/dev/observability/orbstack/nomad/supervise.sh transit-tracker
```

`ctl-transit-tracker` is **deregistered** — `nomad job status ctl-transit-tracker`
returns "No job(s) with prefix or ID … found" — but a Nomad executor is still
running its supervisor, tracked in
[robogeosociety/observability-config#173][oc173]. Reading `supervise.sh`, this is
not a benign leftover:

```zsh
docker start "$container" >/dev/null       # ensure running
docker wait "$container" >/dev/null 2>&1 & # then block until it exits
wait $wpid                                 # container exits -> script exits 0
```

The executor reruns the task when the script exits. So **`docker stop
transit-tracker` causes `docker wait` to return, the script to exit, the executor
to rerun it, and `docker start` to bring the container straight back** — into a
port-8000 collision with whatever the native agent is doing. A cutover attempted
without dealing with this doesn't just fail; it fails in a confusing way, with
two processes fighting over the ESP32.

**#173 must land first** (or at minimum the orphaned executor must be cleared and
confirmed not to return). This proposal supersedes the rest of #173's plan: its
second checkbox is "re-register `ctl-transit-tracker` from
`orbstack/nomad/ctl-transit-tracker.hcl` with the #170 policy intact" — under
this proposal that job should be **retired instead of re-registered**, because
launchd `KeepAlive` becomes the supervisor and re-registering would create a
second one. #173's first, third and fourth checkboxes stay exactly as written.
Someone should say so on #173 rather than letting the two plans race.

[oc173]: https://github.com/robogeosociety/observability-config/issues/173

### Phase 1 — build the native runtime alongside, on alternate ports

Stage `app/`, create the venv, pin 3.13, allowlist the binary in ALF, and run the
service **by hand in the foreground** on ports that don't collide:

```sh
PORT=18080 .venv/bin/python -m transit_tracker.cli service
```

**One small code change is required for this phase**, and it should be its own PR
first: `PORT` overrides the web port (`web/server.py:319`) but **the WebSocket
port has no env override** — `run_full_service()` calls
`run_server(config=config, server=server)` and takes the `8000` default. Add a
`TT_WS_PORT` env read alongside it so the native process can be exercised
end-to-end on `18000`/`18080` while the container keeps the real ports. This is a
four-line change and it is what makes a non-destructive parallel run possible at
all.

Verify against the parallel instance, container untouched:

```sh
curl -o /dev/null -w '%{http_code}' localhost:18080/transit-tracker         # 200
curl -s localhost:18080/transit-tracker/api/tiles | \
  python3 -c 'import json,sys; d=json.load(sys.stdin);
              print(len(d["tiles"]), any(x["is_realtime"] for t in d["tiles"] for x in t["departures"]))'
```

Success = ≥2 tiles, at least one `is_realtime: true`, `trip_id` populated. That
proves the venv, the GTFS index at its new path, the OBA key, and the profile
resolution all work — **before anything that matters is touched.** The sign has
not blinked.

Then point the ESP32 at `192.168.5.232:18000` for a few minutes (a firmware
config write, reversible) and confirm `Push to 192.168.4.33` in the foreground
log. If that works, the migration is proven. Move it back to `:8000` and stop the
foreground process.

### Phase 2 — the swap. Target: seconds, and it is scheduled.

Do this in a window when the sign being briefly stale is acceptable — not at
07:30. The ESP32 renders its last frame while disconnected, so the visible
failure of a slow swap is a *stale* sign, not a blank one, provided the gap is
short enough that it reconnects before anyone notices.

Order matters, because `service.yaml` is written by the running service:

1. `scripts/stop_container.sh` — stops **and removes** the container. Removal is
   what stops `manage_service()` preferring Docker, and (post-Phase-0) nothing
   respawns it.
2. Rewrite `last_config_path` in `config/service.yaml` from
   `/config/profiles/home-train.yaml` to
   `/Users/tommydoerr/.local/share/transit-tracker/config/home-train.yaml`.
   Keep a copy of the original. **This is §3a and it is the step that quietly
   ruins the cutover if skipped.**
3. Install and load the plist — via the assertion helper in §6.
4. Verify, in order:

   ```sh
   launchctl list | grep org.eastsideurbanism.transit-tracker      # present, PID, status 0
   lsof -nP -iTCP:8000 -sTCP:LISTEN                                 # python, not OrbStack
   curl -o /dev/null -w '%{http_code}' localhost:8080/transit-tracker
   grep 'Push to 192.168.4.33' ~/Library/Logs/transit-tracker.log   # the real signal
   ```

   The last one is the only one that proves the **sign** works rather than the
   service. Do not declare victory on the first three.

### Phase 3 — soak, one week

Nothing is deleted. Watch for: the agent still loaded after a reboot; RSS not
growing past ~60 MiB; no `ThrottleInterval` respawn loop in the log; the log file
not past ~20 MB; `Push to 192.168.4.33` continuous. A week catches the
once-a-day and once-a-boot failures that an hour does not, and this is a wall
display, so the operator notices regressions the metrics wouldn't.

### Phase 4 — the one-way door

Only after a green week: delete the `transit-tracker` image (431.8 MB),
`Dockerfile`, `docker/entrypoint.sh`, `scripts/start_container.sh`,
`scripts/stop_container.sh`, and the dead InfluxDB branch and `.env.influx` with
them. Retire `ctl-transit-tracker.hcl` in `observability-config`. Update
`CLAUDE.md`, `README.md`, and the `docker`/`e2e` pytest markers that gate on
Docker.

**Do not do Phase 4 early.** Phases 0–3 are all reversible; this one is not, and
it is the only reason to keep the container path alive after Phase 2.

---

## 6. Rollback

**Before Phase 4, rollback is one command:**

```sh
launchctl bootout gui/$(id -u)/org.eastsideurbanism.transit-tracker
scripts/start_container.sh --detach
```

The image is still local, the bind mounts still point at the same `config/` and
`data/`, and `--restart=always` comes back with it. The only thing that must also
be undone is the `last_config_path` rewrite from Phase 2 step 2 — restore the
saved copy, or the container's `entrypoint.sh` will "helpfully" repoint it at
`home.yaml`. Keep that backup next to the plist, not in `/tmp`.

Measured expectation: `start_container.sh --detach` waits up to 60 s for `:8000`
and normally returns in a few seconds on a warm image.

After Phase 4, rollback means `docker build` — several minutes, and it needs
network. That asymmetry is the whole argument for the phase ordering.

---

## 7. What is lost

Even-handed. Some of these are real.

| Lost | Severity | Mitigation / acceptance |
|---|---|---|
| **Image pinning** — `FROM python:3.13-slim` + a frozen image digest | Low, arguably *improves* | `uv.lock` + a `.python-version` pinned managed CPython 3.13.14 is a **tighter** pin than a floating `3.13-slim` tag. What is genuinely lost is the pinning of the *OS layer* — but nothing outside the venv is used: no apt packages, no compiled extension built at image time. |
| **`docker logs`** — rotation, `--since`, `--tail`, timestamps | **Real** | Text file + `tail -f`. Rotation must be re-added (open question 4). `--since` becomes `grep`. `com.tommy.orbstack-log-capture` already exists as a precedent for host-side log handling. Accept, then fix rotation. |
| **`transit-tracker.orb.local` HTTPS name** | Low, but unquantified | Provided by the `dev.orbstack.http-port=8080` label; disappears with the engine. Per direction from Tommy, whether anything consumes it was **not investigated** — the LAN ports are the requirement. If something does depend on it, the replacement is a Tailscale serve entry or a Caddy/`rgs-dev-tunnel` route, both of which the mini already runs. **Flagged, not resolved** — see open question 3. |
| **Clean rebuild** — `docker build` from scratch guarantees no stale state | **Real** | `rm -rf .venv && uv sync --frozen` is the equivalent and takes seconds, but it is not enforced by the deploy path the way a rebuild was. The installer should support a `--clean` flag. |
| **Filesystem isolation** — container ran as uid 1000 with three bind mounts | **Real, and widens** | The agent runs as `tommydoerr` with that user's entire home readable. Same regression [#135][d135] states rather than argues away. Worth stating twice: this service parses untrusted-ish JSON from a public transit API. Accepted, but it is a genuine cost. |
| **Process/network namespace** | Low | Nothing depended on it. The NAT it provided was actively *hiding* peer addresses (§4). |
| **Resource isolation** | None | Costs nothing: the container sets no memory limit, no CPU limit, and no health check. There is nothing to lose. |
| **`docker inspect` as documentation** | Low | The plist is more readable and lives in git, which `docker run` flags in a shell script did not. |

Gained, for balance: ~54.8 MiB of container memory and 431.8 MB of image;
`uv sync --frozen` instead of a multi-stage rebuild per deploy; real ESP32 peer
addresses in the logs; and — the actual point — one of the two remaining reasons
OrbStack (**438 MB RSS**, measured) stays resident on an 8 GB box currently at
7.6 GB of 9.2 GB swap.

---

## 8. The launchd deploy gotcha, designed in

`launchctl bootstrap gui/$(id -u) <plist>` fails with **`5: Input/output error`**
over ssh. The usual `bootout … || true` then `bootstrap …` idiom therefore boots
the agent **out** and fails to put it back — silently. `com.tommydoerr.stack-watchdog`
sat unloaded from 2026-07-21 onward for exactly this reason and was dark through
both `/Volumes/dev` wedges it existed to detect. Tracked as
[robogeosociety/robot-geographical-society#181][rgs181].

For *this* agent that failure mode is worse than a dark watchdog: it is a blank
sign that `launchctl list` reports nothing about, because the label isn't there
to report on. So the installer asserts:

```sh
install_agent() {
  local label="org.eastsideurbanism.transit-tracker"
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  local domain="gui/$(id -u)"

  launchctl bootout "$domain/$label" 2>/dev/null || true
  launchctl bootstrap "$domain" "$plist" 2>/dev/null \
    || launchctl load -w "$plist"                      # ssh fallback

  # Assert. Never trust the exit code of either command above.
  if ! launchctl list | grep -q "$label"; then
    echo "FATAL: $label is not loaded after install — the sign is dark." >&2
    exit 1
  fi
  echo "OK: $label loaded"
}
```

`bootstrap || load -w`, then **prove it with `launchctl list` and exit non-zero
if absent.** Same helper shape as [#135][d135] proposes for the discobots
installers; the two should share one implementation rather than diverging, and
`.github` is the natural home for it.

Worth going one step further here, given the stakes: a periodic check that the
agent is both loaded *and* pushing — `launchctl list` plus a `Push to
192.168.4.33` line newer than ~3 minutes in the log — POSTed to the deploy-gate
`/notify` endpoint on failure. That is the supervision `--restart=always` never
provided and that #170's Nomad reschedule policy was reaching for before the job
was deregistered. It is a follow-up, not part of this migration.

[rgs181]: https://github.com/robogeosociety/robot-geographical-society/issues/181

---

## 9. This is one of three; here is the order

Uninstalling OrbStack from the mini needs **all three** of:

| # | Workload | Owner | Status |
|---|---|---|---|
| 1 | `vault`, `minimem`, `orbmem`, `heatmap` | `robogeosociety/discobots` | [#135][d135], draft proposal |
| 2 | `transit-tracker` | this repo | **this proposal** |
| 3 | `discobot-valkey` | `robogeosociety/infra` (Terraform-managed) | **no decision yet** |

Neither #1 nor #2 alone removes OrbStack; [#135][d135] says so in its second
section, and this one repeats it. Order:

1. **[#135][d135] first**, and specifically its Phase 0/1. It is the cheap,
   reversible one — a Discord panel being dark for an hour costs nothing, and it
   establishes the launchd + uv venv pattern, the shared `install_agent` helper,
   and the answer to log rotation. Let this workload inherit a pattern that has
   already been debugged on something disposable.
2. **[observability-config#173][oc173]** — Phase 0 here. It is a hard blocker for
   this repo and independent of #135.
3. **This proposal**, Phases 1–3. It is the one with a physical failure mode, so
   it goes second-to-last and slowest, on a proven pattern.
4. **The valkey decision in `robogeosociety/infra`.** [#135][d135] measured it:
   `DBSIZE` = 1, `PUBSUB CHANNELS` empty, the sole key
   `retain:fleet.supervisor.tick`, the only clients Telegraf scraping metrics. If
   the discobots stop needing a bus after step 1, the last reason for that
   container may go with them — but that is Terraform-managed state in another
   repo, and it points the opposite way from `discobots/docs/proposals/valkey-expansion.md`.
   Those two want reconciling before anything is torn down.
5. **Only then**: uninstall OrbStack. Which also removes
   `com.tommy.orbstack-log-capture`, the `bridge100`/`bridge101` interfaces, and
   ~2.2 GB of images plus 1.2 GB of build cache.

Phase 4 of *this* proposal (deleting the Dockerfile) does not need to wait for
steps 4–5. But **do not uninstall OrbStack until Phase 3 has soaked**, because
uninstalling it deletes the rollback.

---

## 10. Open questions

1. **LaunchAgent or LaunchDaemon?** An agent in `gui/$(id -u)` needs a logged-in
   session — same constraint OrbStack.app has today, so it is parity. But
   FileVault blocks auto-login on this box, so after a power cut *nothing* comes
   back until someone logs in, and this is a wall display. A LaunchDaemon in
   `/Library/LaunchDaemons` with `UserName tommydoerr` fixes that and is strictly
   better for the stated constraint. It needs `sudo`, so it is a human task.
   **Recommend LaunchDaemon; defaulting to LaunchAgent because it is the
   contained choice and matches every other agent on the box.** Your call.
2. **`TT_RUNTIME_DIR`: keep, or fold into the plist env?** §3 argues keep — it
   still names the internal-disk convention and `sync_runtime.sh` still seeds a
   fresh box — but its bind-mount rationale is gone, and a case could be made for
   deleting both and letting the plist be the only source of paths. Related:
   **should PR #74 be merged first?** It is open, but its branch is what is
   running on the mini, so `main` currently does not describe reality.
3. **Does anything consume `https://transit-tracker.orb.local`?** Explicitly not
   investigated per your direction. Home Assistant is the obvious candidate given
   `/api/tiles` was built for it (#63, #64). If it uses `192.168.5.232:8080` it is
   unaffected; if it uses the `orb.local` name it breaks at Phase 2 and needs a
   Tailscale-serve or `rgs-dev-tunnel` replacement. **A one-line answer from you
   is cheaper than any amount of investigation.**
4. **Log rotation — `newsyslog.d` (sudo) or a size check in the installer?**
   Should get the *same* answer as [#135][d135] question 7, decided once.
5. **Should `TT_WS_PORT` land as its own PR first?** Phase 1's parallel run is
   impossible without it. It is four lines, but it is a code change to the
   service that drives the sign, so it deserves its own merge and its own soak
   rather than riding in with the migration.
6. **`entrypoint.sh`'s profile-resolution logic — port it, or drop it?** Its
   `_resolve_default_profile` is what makes a dangling `last_config_path`
   self-heal. Natively that becomes a fallback to *defaults* (§3a). Porting it
   into `run_full_service()` makes the service more robust; dropping it makes the
   failure loud instead of silent. **Loud is arguably better for a wall display** —
   a crash triggers `KeepAlive` and a log line, where a silent fallback to an
   empty subscription list looks healthy. Leaning drop-and-fail-loud, but it is a
   behaviour change either way.
7. **Health check.** There is none today, in the container or in Nomad. §8
   sketches one. Is "the sign is stale and nothing tells anyone" acceptable
   post-migration, or should the notify hook land as part of Phase 3 rather than
   as a follow-up?
8. **Does the ESP32 firmware hold `192.168.5.232` or a hostname?**
   Phase 1's parallel-port test assumes the device can be repointed via config
   write. If it holds a bare IP that is fine; if it resolves an mDNS name that the
   container's label provides, Phase 1 needs rethinking. `service.yaml` gives us
   `device_ip: 192.168.4.33` — the mini's address *as the ESP32 sees it* is not
   recorded anywhere we read.
