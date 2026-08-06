"""Docker container integration tests for Transit Tracker.


Builds the transit-tracker image, starts a container, and verifies:
- WebSocket heartbeat on port 8000
- /api/spec returns valid JSON on port 8080

Requires Docker. Run with: pytest -m docker tests/test_container.py

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import websockets.sync.client

pytestmark = pytest.mark.e2e

def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False

if not _docker_available():
    pytest.skip("Docker not available", allow_module_level=True)
IMAGE_NAME = "transit-tracker"
CONTAINER_NAME = "transit-tracker-test"
WS_HOST_PORT = 18000
HTTP_HOST_PORT = 18080
CONFIG_MOUNT = ".local/home.yaml"
GTFS_DB = "data/gtfs_index.sqlite"
STARTUP_TIMEOUT = 60  # seconds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docker_image():
    """Build the Docker image. Yields the image name, no cleanup of image."""
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_NAME, "."],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"Docker build failed:\n{result.stderr}"
    yield IMAGE_NAME


@pytest.fixture(scope="module")
def docker_container(docker_image):
    """Start the container with unique test ports. Yields once ready, cleans up on exit."""
    # Remove any leftover test container
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
    )

    run_cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{WS_HOST_PORT}:8000",
        "-p", f"{HTTP_HOST_PORT}:8080",
        # This suite deliberately boots keyless and with no service.yaml, to
        # prove the image comes up on a bare host. The startup guard in
        # cli._assert_real_oba_key would otherwise (correctly) refuse to start
        # on the shared public OBA key, so opt in explicitly here.
        "-e", "TT_ALLOW_TEST_KEY=1",
    ]
    # Only mount config if it exists (CI environments won't have it)
    config_path = Path(CONFIG_MOUNT)
    if config_path.exists():
        run_cmd += ["-v", f"{config_path.resolve()}:/config/config.yaml:ro"]
    run_cmd.append(docker_image)
    result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"Container start failed:\n{result.stderr}"

    # Wait for WebSocket port to accept connections
    deadline = time.time() + STARTUP_TIMEOUT
    ready = False
    while time.time() < deadline:
        try:
            with websockets.sync.client.connect(
                f"ws://localhost:{WS_HOST_PORT}",
                open_timeout=2,
                close_timeout=1,
            ):
                ready = True
                break
        except Exception:
            time.sleep(1)

    if not ready:
        logs = subprocess.run(
            ["docker", "logs", CONTAINER_NAME],
            capture_output=True, text=True,
        )
        # Clean up before failing
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
        pytest.fail(
            f"Container did not accept WS connections within {STARTUP_TIMEOUT}s.\n"
            f"Logs:\n{logs.stdout}\n{logs.stderr}"
        )

    yield CONTAINER_NAME

    # Cleanup: stop and remove container
    subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True, timeout=30)
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=10)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.docker
def test_image_builds(docker_image):
    """Requirement 5.1: Dockerfile builds without errors."""
    result = subprocess.run(
        ["docker", "image", "inspect", docker_image],
        capture_output=True,
    )
    assert result.returncode == 0, "Built image not found"


@pytest.mark.docker
def test_websocket_heartbeat(docker_container):
    """Requirements 5.2, 5.3: WebSocket accepts connections and sends heartbeat."""
    with websockets.sync.client.connect(
        f"ws://localhost:{WS_HOST_PORT}",
        open_timeout=5,
        close_timeout=2,
    ) as ws:
        # Heartbeat is sent every 10s; wait up to 60s to receive one
        deadline = time.time() + 60
        heartbeat_received = False
        while time.time() < deadline:
            try:
                raw = ws.recv(timeout=15)
                msg = json.loads(raw)
                if msg.get("event") == "heartbeat":
                    heartbeat_received = True
                    break
            except TimeoutError:
                continue

        assert heartbeat_received, "Did not receive a heartbeat event within 60s"


@pytest.mark.docker
def test_openapi_returns_json(docker_container):
    """Requirement 5.4: /api/spec returns valid JSON."""
    resp = httpx.get(f"http://localhost:{HTTP_HOST_PORT}/transit-tracker/api/spec", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()  # raises if not valid JSON
    assert isinstance(data, dict), "/api/spec should return a JSON object"


# ---------------------------------------------------------------------------
# GTFS mount tests
# ---------------------------------------------------------------------------

GTFS_CONTAINER_NAME = "transit-tracker-gtfs-test"
GTFS_WS_PORT = 18001
GTFS_HTTP_PORT = 18081


def _start_container(image, name, ws_port, http_port, *, gtfs_mount=False):
    """Start a test container, optionally with GTFS volume. Returns True if ready."""
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    run_cmd = [
        "docker", "run", "-d",
        "--name", name,
        "-p", f"{ws_port}:8000",
        "-p", f"{http_port}:8080",
        "-e", "TT_ALLOW_TEST_KEY=1",  # see the fixture above
    ]
    config_path = Path(CONFIG_MOUNT)
    if config_path.exists():
        run_cmd += ["-v", f"{config_path.resolve()}:/config/config.yaml:ro"]
    if gtfs_mount:
        gtfs_path = Path(GTFS_DB)
        if gtfs_path.exists():
            run_cmd += [
                "-v", f"{gtfs_path.resolve()}:/data/gtfs/gtfs_index.sqlite:ro",
            ]
    run_cmd.append(image)
    result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return False

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            with websockets.sync.client.connect(
                f"ws://localhost:{ws_port}", open_timeout=2, close_timeout=1,
            ):
                return True
        except Exception:
            time.sleep(1)
    return False


def _stop_container(name):
    subprocess.run(["docker", "stop", name], capture_output=True, timeout=30)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)


def _subscribe_and_collect(ws_port, pairs_str, *, timeout=30):
    """Subscribe and collect schedule events until timeout. Returns list of messages."""
    messages = []
    with websockets.sync.client.connect(
        f"ws://localhost:{ws_port}", open_timeout=5, close_timeout=2,
    ) as ws:
        ws.send(json.dumps({
            "event": "schedule:subscribe",
            "data": {"routeStopPairs": pairs_str},
            "client_name": "gtfs-test",
        }))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv(timeout=5)
                msg = json.loads(raw)
                if msg.get("event") == "schedule":
                    messages.append(msg)
                    break  # first schedule response is enough
            except TimeoutError:
                continue
    return messages


@pytest.mark.docker
def test_container_without_gtfs_mount_sends_only_live(docker_image):
    """Without GTFS mount, subscribe response has no scheduled-only trips on cold start."""
    # docker_container fixture (no GTFS) is already running — reuse its port
    # Subscribe with a stop; on cold start with no GTFS, we expect either
    # empty trips or only live (realtime) trips once the OBA cache warms.
    messages = _subscribe_and_collect(WS_HOST_PORT, "1_100229,1_75403,0")
    if messages:
        trips = messages[0]["data"]["trips"]
        # Without GTFS mount, all trips must be live (realtime) — no scheduled-only trips
        assert all(
            t.get("isRealtime") is True for t in trips
        ), "Without GTFS mount, all trips should be realtime"


@pytest.mark.docker
def test_container_with_gtfs_mount_sends_scheduled(docker_image):
    """With GTFS mount, subscribe response includes scheduled (non-realtime) trips."""
    gtfs_path = Path(GTFS_DB)
    if not gtfs_path.exists():
        pytest.skip(f"GTFS index not found at {GTFS_DB} — run scripts/download_gtfs.py")

    ready = _start_container(
        docker_image, GTFS_CONTAINER_NAME,
        GTFS_WS_PORT, GTFS_HTTP_PORT, gtfs_mount=True,
    )
    try:
        assert ready, "GTFS container did not start"

        # Subscribe to a known Sound Transit stop — GTFS should return
        # scheduled trips immediately even before OBA cache warms.
        messages = _subscribe_and_collect(
            GTFS_WS_PORT, "1_100229,1_75403,0", timeout=15,
        )
        assert len(messages) > 0, "Expected at least one schedule message"
        trips = messages[0]["data"]["trips"]
        assert len(trips) > 0, "Expected trips from GTFS on cold start"
        # At least one trip should be scheduled (not realtime) from GTFS
        has_scheduled = any(not t.get("isRealtime") for t in trips)
        assert has_scheduled, "Expected scheduled (non-realtime) trips from GTFS mount"
    finally:
        _stop_container(GTFS_CONTAINER_NAME)
