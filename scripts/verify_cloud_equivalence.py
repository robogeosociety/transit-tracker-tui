"""Transit Tracker Equivalence Verifier.

Compares the locally running service against the cloud baseline
(``wss://tt.horner.tj``).

Usage:
  python scripts/verify_cloud_equivalence.py

The ``--containers`` mode (local image vs ghcr.io/tjhorner/transit-tracker-api,
the A/B in #33) went with the Docker path on 2026-09-21 — see
docs/proposals/native-launchd-transit-tracker.md. Reviving that comparison means
running the reference container somewhere that still has a container runtime.
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Any, Dict, Optional

import websockets

CLOUD_URL = "wss://tt.horner.tj/"
LOCAL_URL = "ws://localhost:8000"

# Standard test pairs
HANDSHAKE_PAIRS = "40_100240,1_8494,-420;1_100039,1_11920,-540"

async def get_update(url: str, name: str, timeout: int = 120) -> Optional[Dict[str, Any]]:
    """Connects to a proxy and waits for the first schedule update."""
    print(f"[{name}] Connecting to {url}...")
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(url) as ws:
                handshake = {
                    "event": "schedule:subscribe",
                    "data": {
                        "routeStopPairs": HANDSHAKE_PAIRS,
                        "limit": 5,
                    },
                }
                await ws.send(json.dumps(handshake))

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("event") == "schedule":
                        return data["data"]
    except Exception as e:
        print(f"[{name}] Error: {e}")
        return None


def format_trip(t: Dict[str, Any]) -> str:
    arr = t.get("arrivalTime", 0)
    now = int(time.time())
    diff = (arr - now) // 60
    is_live = "✅" if t.get("isRealtime") else "❌"
    return (
        f"{str(t.get('routeName', '')):<10} | "
        f"{str(t.get('headsign', '')):<25} | "
        f"{diff:>3}m | {is_live:<5} | {t.get('tripId')}"
    )


def print_trips(label: str, data: Dict[str, Any]) -> None:
    trips = data.get("trips", [])
    print(f"{label} ({len(trips)} trips):")
    for t in trips:
        print(f"  {format_trip(t)}")


def structural_comparison(
    a_data: Dict[str, Any],
    b_data: Dict[str, Any],
    a_label: str,
    b_label: str,
) -> None:
    """Compare top-level keys and per-trip field names between two responses."""
    print("\n" + "=" * 60)
    print("STRUCTURAL VALIDATION")

    a_keys = set(a_data.keys())
    b_keys = set(b_data.keys())

    if a_keys == b_keys:
        print(f"✅ Top-level schema matches ({a_label} vs {b_label})")
    else:
        print(f"❌ Schema mismatch!")
        print(f"   {a_label} keys: {sorted(a_keys)}")
        print(f"   {b_label} keys: {sorted(b_keys)}")
        missing_in_a = b_keys - a_keys
        extra_in_a = a_keys - b_keys
        if missing_in_a:
            print(f"   Missing in {a_label}: {missing_in_a}")
        if extra_in_a:
            print(f"   Extra in {a_label}: {extra_in_a}")

    a_trips = a_data.get("trips", [])
    b_trips = b_data.get("trips", [])

    if a_trips and b_trips:
        a_fields = set(a_trips[0].keys())
        b_fields = set(b_trips[0].keys())
        if a_fields == b_fields:
            print("✅ Trip object fields match exactly")
        else:
            print("❌ Trip field divergence detected!")
            missing = b_fields - a_fields
            extra = a_fields - b_fields
            if missing:
                print(f"   Missing in {a_label}: {missing}")
            if extra:
                print(f"   Extra in {a_label}: {extra}")
    elif not a_trips:
        print(f"⚠️  No trips from {a_label} — cannot compare trip fields")
    elif not b_trips:
        print(f"⚠️  No trips from {b_label} — cannot compare trip fields")


# ---------------------------------------------------------------------------
# Local-vs-cloud mode (original behavior)
# ---------------------------------------------------------------------------

async def local_vs_cloud() -> None:
    """Runs a live comparison between the local proxy and the cloud baseline."""
    print("🏙️  Transit Tracker Equivalence Verifier")
    print("Comparing local proxy against cloud baseline...\n")

    local_data = await get_update(LOCAL_URL, "LOCAL")
    cloud_data = await get_update(CLOUD_URL, "CLOUD")

    if not local_data:
        print("\n❌ FAILED: Could not retrieve data from LOCAL proxy.")
        print("   Ensure 'transit-tracker service' is running locally.")
        sys.exit(1)

    if not cloud_data:
        print("\n⚠️  WARNING: Could not retrieve data from CLOUD proxy.")
        print("   This is often due to cloud-side rate limiting or connection issues.")
        print("   Local data is still provided below for manual verification.")

    print("\n" + "=" * 60)
    print(f"{'ROUTE':<10} | {'HEADSIGN':<25} | {'DUE':<5} | {'LIVE':<5} | {'ID'}")
    print("-" * 60)

    print_trips("LOCAL PROXY", local_data)

    if cloud_data:
        print()
        print_trips("CLOUD PROXY", cloud_data)
        structural_comparison(local_data, cloud_data, "LOCAL", "CLOUD")


# ---------------------------------------------------------------------------
# Container-vs-container mode
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transit Tracker Equivalence Verifier",
    )
    return parser.parse_args()


if __name__ == "__main__":
    parse_args()
    try:
        asyncio.run(local_vs_cloud())
    except KeyboardInterrupt:
        pass
