import argparse
import asyncio
import os
import subprocess
import sys
import time

from .config import TransitConfig, get_last_config_path
from .logging import get_logger, setup_logging
from .network.websocket_server import run_server
from .network.websocket_service import run_service as run_client
from .tui import run_cli

log = get_logger("transit_tracker.cli")

PLIST_NAME = "org.eastsideurbanism.transit-tracker.plist"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_NAME}")
CONTAINER_NAME = "transit-tracker"


def _container_running() -> bool:
    """Check if the transit-tracker Docker container is running."""
    res = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0 and "true" in res.stdout.lower()


def get_service_status():
    """Returns True if the service is running (container or launchctl)."""
    if _container_running():
        return True
    label = PLIST_NAME.replace(".plist", "")
    res = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
    return res.returncode == 0


def manage_service(action: str):
    """Manage the transit-tracker service.

    Prefers Docker container management. Falls back to launchctl for
    legacy non-containerised setups.
    """
    # If a container exists (running or stopped), manage via Docker
    res = subprocess.run(
        ["docker", "inspect", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        _manage_service_docker(action)
    else:
        _manage_service_launchctl(action)


def _manage_service_docker(action: str):
    if action == "start":
        if _container_running():
            print(f"[yellow]Container {CONTAINER_NAME} is already running.[/yellow]")
            return
        print(f"Starting container {CONTAINER_NAME}...")
        result = subprocess.run(
            ["docker", "start", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[green]Container {CONTAINER_NAME} started.[/green]")
        else:
            print(f"[red]Failed to start: {result.stderr.strip()}[/red]")

    elif action == "stop":
        print(f"Stopping container {CONTAINER_NAME}...")
        result = subprocess.run(
            ["docker", "stop", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[green]Container {CONTAINER_NAME} stopped.[/green]")
        else:
            print(f"[red]Failed to stop: {result.stderr.strip()}[/red]")

    elif action == "restart":
        print(f"Restarting container {CONTAINER_NAME}...")
        result = subprocess.run(
            ["docker", "restart", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[green]Container {CONTAINER_NAME} restarted.[/green]")
        else:
            print(f"[red]Failed to restart: {result.stderr.strip()}[/red]")

    elif action == "status":
        if _container_running():
            # Get uptime from container inspect
            res = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.StartedAt}}", CONTAINER_NAME],
                capture_output=True,
                text=True,
            )
            started = res.stdout.strip() if res.returncode == 0 else "unknown"
            print(
                f"● {CONTAINER_NAME} is [bold green]running[/bold green] (since {started})"
            )
        else:
            print(f"○ {CONTAINER_NAME} is [red]stopped[/red]")


def _manage_service_launchctl(action: str):
    label = PLIST_NAME.replace(".plist", "")

    if action == "start":
        if sys.platform != "darwin":
            print("[red]Service management requires macOS.[/red]")
            return
        if get_service_status():
            print(f"[yellow]Service {label} is already running.[/yellow]")
            return
        if os.path.exists(PLIST_PATH):
            print(f"Starting {label} via launchctl...")
            os.system(f"launchctl load {PLIST_PATH}")
        else:
            print(
                f"[red]Error: {PLIST_PATH} not found. Run 'transit-tracker install' first.[/red]"
            )

    elif action == "stop":
        if sys.platform != "darwin":
            print("[red]Service management requires macOS.[/red]")
            return
        print(f"Stopping {label} via launchctl...")
        os.system(f"launchctl unload {PLIST_PATH}")
        subprocess.run(["pkill", "-f", "transit-tracker service"], capture_output=True)
        print("[green]Service stopped.[/green]")

    elif action == "restart":
        if sys.platform != "darwin":
            manage_service("stop")
            time.sleep(1)
            manage_service("start")
            return
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Service {label} restarted.")
        else:
            print(
                f"kickstart failed ({result.stderr.strip()}), falling back to stop/start..."
            )
            _manage_service_launchctl("stop")
            time.sleep(1)
            _manage_service_launchctl("start")

    elif action == "status":
        res = subprocess.run(
            ["launchctl", "list", label], capture_output=True, text=True
        )
        if res.returncode == 0:
            print(f"● {label} is [bold green]running[/bold green]")
        else:
            print(f"○ {label} is [red]stopped[/red]")


SHARED_TEST_KEY = "TEST"
ALLOW_TEST_KEY_ENV = "TT_ALLOW_TEST_KEY"


class TestKeyRefused(RuntimeError):
    """The resolved OBA key is the shared public one, and that was not opted into."""


def _assert_real_oba_key(config: TransitConfig) -> None:
    """Refuse to start on the shared public OneBusAway key unless told to.

    OneBusAway publishes a demo key literally called ``TEST``. Both key
    resolution sites in this codebase end their chain with ``or "TEST"``, so a
    missing or unreadable ``service.yaml`` yields a service that starts
    cleanly, polls happily, and gets aggressively rate-limited — whose symptom
    on the sign (every departure showing scheduled, none live) is
    indistinguishable from a genuine upstream feed outage. Telling those two
    apart took a direct probe of the OBA API.

    Raising is the idiomatic fatal here: it propagates out of the service
    entrypoint, the process exits non-zero, and the container restart policy is
    the supervisor.

    ``TT_ALLOW_TEST_KEY=1`` opts in deliberately — ``tests/test_container.py``
    sets it, because that suite boots the image with no key and no config mount
    on purpose, to prove the container comes up keyless.
    """
    if os.environ.get(ALLOW_TEST_KEY_ENV, "").strip() in ("1", "true", "yes"):
        return
    key = config.service.oba_api_key or os.environ.get("OBA_API_KEY") or SHARED_TEST_KEY
    if key != SHARED_TEST_KEY:
        return
    raise TestKeyRefused(
        "Refusing to start on the shared public OneBusAway %r key. It is "
        "rate-limited, and its symptom — every departure rendered as scheduled "
        "with no live marker — looks exactly like an upstream outage, so this "
        "fails silently on the sign. Set oba_api_key in service.yaml (or "
        "OBA_API_KEY in the environment), or set %s=1 to accept the shared key "
        "deliberately." % (SHARED_TEST_KEY, ALLOW_TEST_KEY_ENV)
    )


async def run_full_service():
    """Run the proxy, web server, and (in cloud mode) the verification monitor
    in a single asyncio event loop.

    One ``TransitServer`` instance backs everything. Hardware connects to the
    ``:8000`` WebSocket server; the ``:8080`` web server shares that same server,
    so browser ``/ws`` clients and the Home-Assistant tile cache register with
    it in-process — no loopback TCP hops. In cloud mode the monitor still
    connects out to the public API to verify it; in local mode the server
    already holds the data in-process, so no self-connection is made.
    """
    from .network.websocket_server import TransitServer
    from .web import run_web

    path = get_last_config_path()
    if path and os.path.exists(path):
        log.info("Loading config from %s", path, extra={"component": "service"})
        config = TransitConfig.load(path)
    else:
        config = TransitConfig.load()

    # Before anything binds a port or polls upstream.
    _assert_real_oba_key(config)

    server = TransitServer(config)

    tasks = [
        run_server(config=config, server=server),  # :8000 hardware + background loops
        run_web(config, server=server),            # :8080 web, in-process /ws + tiles
    ]

    if not config.service.use_local_api:
        # Cloud mode: verify the public API with a real (non-loopback) client.
        if "localhost" in config.api_url or "127.0.0.1" in config.api_url:
            config.api_url = "wss://tt.horner.tj/"
        tasks.append(run_client(config=config))

    await asyncio.gather(*tasks)


def main():
    # Use saved config path if available
    path = get_last_config_path()
    if path and os.path.exists(path):
        config = TransitConfig.load(path)
    else:
        config = TransitConfig.load()

    parser = argparse.ArgumentParser(description="Transit Tracker Configuration")
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to run: 'ui' (default), 'service [start|stop|restart|status]', 'simulator', 'web'.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("TT_LOG_LEVEL", "INFO"),
        help="Log level: DEBUG, INFO, WARNING, ERROR",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        default=os.environ.get("TT_LOG_JSON", "").lower() in ("1", "true"),
        help="Emit structured JSON logs (for containers)",
    )
    parser.add_argument(
        "--log-messages",
        action="store_true",
        default=os.environ.get("TT_LOG_MESSAGES", "").lower() in ("1", "true"),
        help="Log all WebSocket messages sent/received",
    )

    args = parser.parse_args()

    # Configure logging before anything else
    setup_logging(
        level=args.log_level,
        json_output=args.log_json,
        message_logging=args.log_messages,
    )

    cmd_list = args.command
    primary_cmd = cmd_list[0] if cmd_list else "ui"
    sub_cmd = cmd_list[1] if len(cmd_list) > 1 else None

    if primary_cmd == "service":
        if sub_cmd in ["start", "stop", "restart", "status"]:
            manage_service(sub_cmd)
        else:
            # This is the actual long-running service process
            try:
                asyncio.run(run_full_service())
            except KeyboardInterrupt:
                pass
    elif primary_cmd == "simulator":
        from .simulator import run_simulator

        # `--demo-alert` injects a sample service alert in-memory to preview the
        # alert banner; it changes nothing in the profile served to the firmware.
        demo_alert = "--demo-alert" in sys.argv
        run_simulator(config, force_live=True, demo_alert=demo_alert)
    elif primary_cmd == "web":
        from .web import run_web

        asyncio.run(run_web(config))
    elif primary_cmd == "ui":
        run_cli()
    else:
        # Default fallback
        run_cli()


if __name__ == "__main__":
    main()
