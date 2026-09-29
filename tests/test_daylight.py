"""Tests for daylight-based automatic brightness scheduling."""

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from transit_tracker.config import (
    DimmingEntry,
    ServiceSettings,
    TransitSubscription,
    build_daylight_schedule,
    evaluate_dimming_schedule,
    load_service_settings,
    save_service_settings,
)
from transit_tracker.network.websocket_server import TransitServer

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# build_daylight_schedule — pure function tests
# ---------------------------------------------------------------------------


def test_build_returns_dimming_entries():
    """Schedule should return a list of DimmingEntry objects."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    assert len(schedule) > 0
    assert all(isinstance(e, DimmingEntry) for e in schedule)


def test_build_entry_count_matches_steps():
    """Number of entries = dawn_ramp_steps + dusk_ramp_steps."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=4,
        dusk_ramp_steps=5,
    )
    assert len(schedule) == 9  # 4 dawn + 5 dusk


def test_build_dawn_ramp_reaches_full_brightness():
    """Last dawn entry should be 255 (full brightness at sunrise)."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    # Dawn entries are first dawn_ramp_steps entries
    dawn_entries = schedule[:6]
    assert dawn_entries[-1].brightness == 255


def test_build_dawn_ramp_starts_low():
    """First dawn entry should have low brightness."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    dawn_entries = schedule[:6]
    assert dawn_entries[0].brightness < 50


def test_build_dusk_ramp_ends_at_zero():
    """Last dusk entry should be 0 (fully off)."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    dusk_entries = schedule[6:]
    assert dusk_entries[-1].brightness == 0


def test_build_dusk_ramp_starts_high():
    """First dusk entry should be high brightness (just dimmed from 255)."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    dusk_entries = schedule[6:]
    assert dusk_entries[0].brightness > 150


def test_build_dawn_brightnesses_increase():
    """Dawn ramp entries should monotonically increase."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    dawn_entries = schedule[:6]
    brightnesses = [e.brightness for e in dawn_entries]
    assert brightnesses == sorted(brightnesses)
    assert len(set(brightnesses)) == len(brightnesses)  # all distinct


def test_build_dusk_brightnesses_decrease():
    """Dusk ramp entries should monotonically decrease."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=6,
        dusk_ramp_steps=6,
    )
    dusk_entries = schedule[6:]
    brightnesses = [e.brightness for e in dusk_entries]
    assert brightnesses == sorted(brightnesses, reverse=True)
    assert len(set(brightnesses)) == len(brightnesses)  # all distinct


def test_build_valid_time_format():
    """All entries should have valid HH:MM time strings."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    import re

    for entry in schedule:
        assert re.match(r"^\d{2}:\d{2}$", entry.time), f"Bad time: {entry.time}"
        h, m = entry.time.split(":")
        assert 0 <= int(h) <= 23
        assert 0 <= int(m) <= 59


def test_build_winter_solstice():
    """Schedule should work for short winter days."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 12, 21), "America/Los_Angeles"
    )
    assert len(schedule) == 12  # default 6+6


def test_build_summer_solstice():
    """Schedule should work for long summer days."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    assert len(schedule) == 12  # default 6+6


def test_build_different_timezones():
    """Schedule times should differ between timezones."""
    pacific = build_daylight_schedule(datetime.date(2025, 6, 21), "America/Los_Angeles")
    eastern = build_daylight_schedule(datetime.date(2025, 6, 21), "America/New_York")
    # Dawn times should be different
    assert pacific[0].time != eastern[0].time


def test_build_unknown_timezone_uses_default_coords():
    """Unknown timezone should still produce a valid schedule."""
    schedule = build_daylight_schedule(datetime.date(2025, 6, 21), "Europe/London")
    assert len(schedule) == 12
    assert all(isinstance(e, DimmingEntry) for e in schedule)


def test_build_custom_ramp_minutes():
    """Changing ramp minutes should shift timing but not entry count."""
    short = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_minutes=10,
        dusk_ramp_minutes=10,
    )
    long = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_minutes=120,
        dusk_ramp_minutes=120,
    )
    assert len(short) == len(long)
    # Short ramp dawn entries should be closer together in time
    # (we just verify they're different)
    assert short[0].time != long[0].time


def test_build_minimum_steps():
    """Should work with minimum 2 steps."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21),
        "America/Los_Angeles",
        dawn_ramp_steps=2,
        dusk_ramp_steps=2,
    )
    assert len(schedule) == 4
    # Dawn: midpoint + full
    assert schedule[0].brightness < 255
    assert schedule[1].brightness == 255
    # Dusk: dimmed + off
    assert schedule[2].brightness > 0
    assert schedule[3].brightness == 0


# ---------------------------------------------------------------------------
# Daylight schedule integrates with evaluate_dimming_schedule
# ---------------------------------------------------------------------------


def test_evaluate_daylight_schedule_midday():
    """During daytime, evaluate should return 255 (full brightness)."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    result = evaluate_dimming_schedule(schedule, datetime.time(12, 0))
    assert result == 255


def test_evaluate_daylight_schedule_midnight():
    """At midnight, evaluate should return 0 (off)."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    result = evaluate_dimming_schedule(schedule, datetime.time(0, 0))
    assert result == 0


def test_evaluate_daylight_schedule_late_night():
    """Late at night should be off."""
    schedule = build_daylight_schedule(
        datetime.date(2025, 6, 21), "America/Los_Angeles"
    )
    result = evaluate_dimming_schedule(schedule, datetime.time(23, 59))
    assert result == 0


# ---------------------------------------------------------------------------
# ServiceSettings persistence — daylight fields
# ---------------------------------------------------------------------------


def test_daylight_fields_default():
    """New ServiceSettings should have daylight dimming disabled by default."""
    settings = ServiceSettings()
    assert settings.daylight_dimming_enabled is False
    assert settings.daylight_dimming_timezone == "America/Los_Angeles"
    assert settings.dawn_ramp_minutes == 30
    assert settings.dawn_ramp_steps == 6
    assert settings.dusk_ramp_minutes == 60
    assert settings.dusk_ramp_steps == 6


def test_daylight_fields_round_trip(tmp_path):
    """Daylight settings should survive save/load cycle."""
    from unittest import mock

    settings_file = tmp_path / "service.yaml"
    with mock.patch("transit_tracker.config.SERVICE_SETTINGS_FILE", str(settings_file)):
        svc = ServiceSettings(
            daylight_dimming_enabled=True,
            daylight_dimming_timezone="America/New_York",
            dawn_ramp_minutes=15,
            dawn_ramp_steps=3,
            dusk_ramp_minutes=45,
            dusk_ramp_steps=8,
        )
        save_service_settings(svc)
        loaded = load_service_settings()
        assert loaded.daylight_dimming_enabled is True
        assert loaded.daylight_dimming_timezone == "America/New_York"
        assert loaded.dawn_ramp_minutes == 15
        assert loaded.dawn_ramp_steps == 3
        assert loaded.dusk_ramp_minutes == 45
        assert loaded.dusk_ramp_steps == 8


def test_daylight_ramp_minutes_validation():
    """dawn/dusk_ramp_minutes must be 5-120."""
    with pytest.raises(ValidationError):
        ServiceSettings(dawn_ramp_minutes=4)
    with pytest.raises(ValidationError):
        ServiceSettings(dusk_ramp_minutes=121)


def test_daylight_ramp_steps_validation():
    """dawn/dusk_ramp_steps must be 2-20."""
    with pytest.raises(ValidationError):
        ServiceSettings(dawn_ramp_steps=1)
    with pytest.raises(ValidationError):
        ServiceSettings(dusk_ramp_steps=21)


# ---------------------------------------------------------------------------
# Server integration — _apply_dimming_schedule with daylight mode
# ---------------------------------------------------------------------------


@pytest.fixture
def daylight_config():
    config = MagicMock()
    config.subscriptions = [
        TransitSubscription(
            feed="st", route="st:40_100240", stop="st:1_8494", label="Test"
        )
    ]
    config.service = MagicMock()
    config.service.use_local_api = True
    config.service.arrival_threshold_minutes = 5
    config.service.check_interval_seconds = 30
    config.service.request_spacing_ms = 250
    config.transit_tracker = MagicMock()
    config.transit_tracker.time_display = "arrival"
    config.service.display_brightness = 128
    config.service.oba_api_key = None
    config.transit_tracker.abbreviations = []
    config.service.device_ip = "192.168.5.248"

    # Daylight mode enabled
    config.service.daylight_dimming_enabled = True
    config.service.daylight_dimming_timezone = "America/Los_Angeles"
    config.service.dawn_ramp_minutes = 30
    config.service.dawn_ramp_steps = 6
    config.service.dusk_ramp_minutes = 60
    config.service.dusk_ramp_steps = 6

    # Legacy fields
    config.service.dimming_schedule = []
    return config


# Fixed schedules for server integration tests (decouple from astral computation)
_DAY_SCHEDULE = [
    DimmingEntry(time="05:30", brightness=42),
    DimmingEntry(time="05:35", brightness=85),
    DimmingEntry(time="05:40", brightness=127),
    DimmingEntry(time="05:45", brightness=170),
    DimmingEntry(time="05:50", brightness=212),
    DimmingEntry(time="05:55", brightness=255),
    DimmingEntry(time="20:40", brightness=212),
    DimmingEntry(time="20:50", brightness=170),
    DimmingEntry(time="21:00", brightness=127),
    DimmingEntry(time="21:10", brightness=85),
    DimmingEntry(time="21:20", brightness=42),
    DimmingEntry(time="21:30", brightness=0),
]


@pytest.mark.asyncio
async def test_daylight_mode_applies_brightness(daylight_config):
    """Daylight mode should compute schedule and apply brightness."""
    server = TransitServer(daylight_config)
    server.display_brightness = 128  # current

    mock_client = AsyncMock()

    _patch_build = patch(
        "transit_tracker.network.websocket_server"
        ".build_daylight_schedule",
        return_value=_DAY_SCHEDULE,
    )
    with _patch_build, patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.time(12, 0)
        await server._apply_dimming_schedule(mock_client)

    # At noon, brightness should be 255 (last dawn entry is the most recent)
    assert server.display_brightness == 255


@pytest.mark.asyncio
async def test_daylight_mode_disabled_returns_false(daylight_config):
    """When daylight mode is off, _apply_dimming_schedule returns False."""
    daylight_config.service.daylight_dimming_enabled = False
    server = TransitServer(daylight_config)
    mock_client = AsyncMock()

    result = await server._apply_dimming_schedule(mock_client)
    assert result is False


@pytest.mark.asyncio
async def test_daylight_mode_broadcasts_to_clients(daylight_config):
    """Daylight mode brightness change should broadcast to WS clients."""
    server = TransitServer(daylight_config)
    server.display_brightness = 128

    ws1 = AsyncMock()
    ws1.remote_address = ("10.0.0.1", 12345)
    server.clients = {ws1}

    mock_client = AsyncMock()

    _patch_build = patch(
        "transit_tracker.network.websocket_server"
        ".build_daylight_schedule",
        return_value=_DAY_SCHEDULE,
    )
    with _patch_build, patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.time(12, 0)
        await server._apply_dimming_schedule(mock_client)

    ws1.send.assert_called_once()
    sent = json.loads(ws1.send.call_args[0][0])
    assert sent["event"] == "control:brightness"
    assert sent["data"]["value"] == 255


@pytest.mark.asyncio
async def test_daylight_mode_posts_to_esphome(daylight_config):
    """Daylight mode should POST brightness to ESPHome device."""
    server = TransitServer(daylight_config)
    server.display_brightness = 128

    mock_client = AsyncMock()

    _patch_build = patch(
        "transit_tracker.network.websocket_server"
        ".build_daylight_schedule",
        return_value=_DAY_SCHEDULE,
    )
    with _patch_build, patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.time(12, 0)
        await server._apply_dimming_schedule(mock_client)

    mock_client.post.assert_called_once()
    url = mock_client.post.call_args[0][0]
    assert "brightness=255" in url


@pytest.mark.asyncio
async def test_daylight_mode_night_turns_off(daylight_config):
    """At night, daylight mode should set brightness to 0."""
    server = TransitServer(daylight_config)
    server.display_brightness = 255

    mock_client = AsyncMock()

    _patch_build = patch(
        "transit_tracker.network.websocket_server"
        ".build_daylight_schedule",
        return_value=_DAY_SCHEDULE,
    )
    with _patch_build, patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.time(1, 0)
        await server._apply_dimming_schedule(mock_client)

    assert server.display_brightness == 0
    # Should use turn_off endpoint for brightness=0
    url = mock_client.post.call_args[0][0]
    assert "turn_off" in url


# ---------------------------------------------------------------------------
# device_ip follows the connected ESP32 (its DHCP lease moves)
# ---------------------------------------------------------------------------


def test_device_ip_follows_connected_esp32(daylight_config):
    from transit_tracker.network.websocket_server import TransitServer

    server = TransitServer(daylight_config)
    assert server._resolve_device_ip() == "192.168.5.248"  # static fallback

    server._note_device_addr(("192.168.4.41", 64854), "ESP32 Websocket Client")
    assert server._resolve_device_ip() == "192.168.4.41"

    # Browsers and the in-process TileCache never count as the board
    server._note_device_addr(("192.168.5.188", 1), "Mozilla/5.0")
    server._note_device_addr(("127.0.0.1", 0), "ESP32 Websocket Client")
    assert server._resolve_device_ip() == "192.168.4.41"
