import datetime
import os
import re
import socket
import tempfile
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .logging import get_logger

log = get_logger("transit_tracker.config")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVICE_SETTINGS_FILE = os.path.join(_PROJECT_ROOT, ".local", "service.yaml")

# Legacy path — read-only fallback for existing installs
_LEGACY_SETTINGS_DIR = os.path.expanduser("~/.config/transit-tracker")
_LEGACY_SETTINGS_FILE = os.path.join(_LEGACY_SETTINGS_DIR, "settings.yaml")


class DimmingEntry(BaseModel):
    time: str  # "HH:MM" format
    brightness: int = Field(ge=0, le=255)

    @field_validator("time")
    @classmethod
    def validate_time_format(cls, v):
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("time must be in HH:MM format")
        h, m = v.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError("time must be valid HH:MM (00:00-23:59)")
        return v


class ServiceSettings(BaseModel):
    """Dev environment / service settings stored at .local/service.yaml.

    These are environment/instance concerns: credentials, polling intervals,
    hardware dimensions, and service mode flags.  They are NOT part of the
    board subscription schema and should never appear inside profile YAMLs.
    """

    last_config_path: Optional[str] = None

    # Credentials (env var OBA_API_KEY is still the primary fallback)
    oba_api_key: Optional[str] = None

    # Server polling / rate limiting
    check_interval_seconds: int = Field(default=30, ge=10)
    request_spacing_ms: int = Field(default=500, ge=0, le=2000)

    # Filtering
    arrival_threshold_minutes: int = Field(default=5, ge=1)

    # Hardware config
    num_panels: int = Field(default=2)
    panel_width: int = Field(default=64)
    panel_height: int = Field(default=32)

    # Service mode
    use_local_api: bool = Field(default=False)
    # Display brightness / scheduled dimming
    display_brightness: int = Field(default=128, ge=0, le=255)
    device_ip: Optional[str] = None
    dimming_schedule: List[DimmingEntry] = Field(default_factory=list)

    # Daylight-based automatic dimming
    daylight_dimming_enabled: bool = False
    daylight_dimming_timezone: str = "America/Los_Angeles"
    daylight_latitude: Optional[float] = None
    daylight_longitude: Optional[float] = None
    dawn_ramp_minutes: int = Field(default=30, ge=5, le=120)
    dawn_ramp_steps: int = Field(default=6, ge=2, le=20)
    dusk_ramp_minutes: int = Field(default=60, ge=5, le=120)
    dusk_ramp_steps: int = Field(default=6, ge=2, le=20)


def _resolve_settings_path() -> str:
    """Return the path to the service settings file.

    Priority: SERVICE_SETTINGS_PATH env var (container override)
    Then: .local/service.yaml  (project-local, gitignored)
    Fallback: ~/.config/transit-tracker/settings.yaml  (legacy installs)
    """
    env_path = os.environ.get("SERVICE_SETTINGS_PATH")
    if env_path:
        return env_path
    if os.path.exists(SERVICE_SETTINGS_FILE):
        return SERVICE_SETTINGS_FILE
    if os.path.exists(_LEGACY_SETTINGS_FILE):
        return _LEGACY_SETTINGS_FILE
    return SERVICE_SETTINGS_FILE


def load_service_settings() -> ServiceSettings:
    """Load service settings from .local/service.yaml (or legacy fallback)."""
    path = _resolve_settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
                return ServiceSettings.model_validate(data)
        except Exception:
            pass
    return ServiceSettings()


def save_service_settings(settings: ServiceSettings):
    """Persist service settings to the resolved service.yaml path.

    Merges the in-memory model onto the existing file so that fields not
    present in the model (e.g. oba_api_key, device_ip set via REST) are
    preserved rather than silently dropped.
    """
    path = _resolve_settings_path()
    log.info("Saving service settings to %s", path, extra={"component": "config"})
    settings_dir = os.path.dirname(path)
    os.makedirs(settings_dir, exist_ok=True)
    # Read existing file to preserve fields not in the in-memory model
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass
    data = settings.model_dump(exclude_none=True)
    # Only merge explicitly-set fields when there's existing data on disk,
    # so default values (e.g. dimming_schedule=[]) don't clobber fields
    # that were set via a different code path (REST, another process).
    if existing and settings.model_fields_set:
        data = {k: v for k, v in data.items() if k in settings.model_fields_set}
    existing.update(data)
    # Use settings_dir for tempfile when possible; fall back to /tmp for
    # container environments where the parent dir may be read-only.
    try:
        fd, tmp_path = tempfile.mkstemp(dir=settings_dir, suffix=".yaml")
    except PermissionError:
        fd, tmp_path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(existing, f)
        os.replace(tmp_path, path)
    except OSError:
        # os.replace fails across filesystems; fall back to copy
        import shutil

        shutil.copy2(tmp_path, path)
        os.unlink(tmp_path)
    except Exception:
        os.unlink(tmp_path)
        raise


def get_last_config_path() -> Optional[str]:
    return load_service_settings().last_config_path


def set_last_config_path(path: str):
    """Update only the last_config_path field without disturbing other settings."""
    settings_path = _resolve_settings_path()
    log.info(
        "Switching active profile to %s",
        os.path.basename(path),
        extra={"component": "config", "profile": path, "settings_path": settings_path},
    )
    existing = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r") as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass
    existing["last_config_path"] = os.path.abspath(path)
    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=settings_dir, suffix=".yaml")
    except PermissionError:
        fd, tmp_path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(existing, f)
        os.replace(tmp_path, settings_path)
    except OSError:
        import shutil

        shutil.copy2(tmp_path, settings_path)
        os.unlink(tmp_path)
    except Exception:
        os.unlink(tmp_path)
        raise


def list_profiles() -> List[str]:
    """Lists available .yaml config files in project root and .local/.

    When PROFILES_DIR is set (as the launchd agent does), scans that
    directory instead of the project tree.
    """
    _EXCLUDE = {"service.yaml", "service_state.json", "test_isolation_config.yaml"}

    profiles_dir = os.environ.get("PROFILES_DIR")
    if profiles_dir and os.path.isdir(profiles_dir):
        profiles = []
        for f in os.listdir(profiles_dir):
            if f.endswith(".yaml") and f not in _EXCLUDE:
                profiles.append(os.path.abspath(os.path.join(profiles_dir, f)))
        return sorted(profiles)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    profiles = []

    # Check .local directory
    local_dir = os.path.join(project_root, ".local")
    if os.path.exists(local_dir):
        for f in os.listdir(local_dir):
            if (
                f.endswith(".yaml")
                and f not in _EXCLUDE
                and f != "accurate_config.yaml"
            ):
                profiles.append(os.path.abspath(os.path.join(local_dir, f)))

    # Check project root
    for f in os.listdir(project_root):
        if f.endswith(".yaml") and f != "accurate_config.yaml":
            profiles.append(os.path.abspath(os.path.join(project_root, f)))

    # Include accurate_config.yaml if it exists
    acc_path_local = os.path.join(project_root, ".local", "accurate_config.yaml")
    acc_path_root = os.path.join(project_root, "accurate_config.yaml")

    if os.path.exists(acc_path_local):
        profiles.append(os.path.abspath(acc_path_local))
    elif os.path.exists(acc_path_root):
        profiles.append(os.path.abspath(acc_path_root))

    return sorted(list(set(profiles)))


class TransitSubscription(BaseModel):
    feed: str
    route: str
    stop: str
    label: str
    direction: Optional[str] = None
    time_offset: str = "0min"


class Abbreviation(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class TransitStop(BaseModel):
    stop_id: str
    time_offset: str = "0min"
    label: Optional[str] = None
    direction: Optional[str] = None
    routes: List[str] = Field(default_factory=list)

    @field_validator("time_offset")
    @classmethod
    def validate_offset(cls, v):
        if not re.match(r"^-?\d+min$", v):
            raise ValueError("time_offset must be in format like '5min' or '-2min'")
        return v


class RouteStyle(BaseModel):
    route_id: str
    name: Optional[str] = None
    color: Optional[str] = None


class TransitTrackerSettings(BaseModel):
    """Board subscription schema — matches the public reference project format.

    Profile YAML files contain only this block under the ``transit_tracker:`` key.
    """

    base_url: str = Field(default="wss://tt.horner.tj/")
    time_display: str = Field(default="arrival")
    scroll_headsigns: bool = Field(default=False)
    display_format: str = Field(default="{ROUTE}  {HEADSIGN}  {LIVE} {TIME}")
    stops: List[TransitStop] = Field(default_factory=list)
    styles: List[RouteStyle] = Field(default_factory=list)
    abbreviations: List[Abbreviation] = Field(default_factory=list)


# Keys that used to live inside transit_tracker but now belong in ServiceSettings
_LEGACY_TT_KEYS = {
    "oba_api_key",
    "check_interval_seconds",
    "request_spacing_ms",
    "num_panels",
    "panel_width",
    "panel_height",
    "arrival_threshold_minutes",
    "display_brightness",
    "device_ip",
    "dimming_schedule",
}

# Keys that used to live at the root of the config YAML
_LEGACY_ROOT_KEYS = {"use_local_api"}

# Dead fields that should be silently stripped
_DEAD_KEYS = {"mapbox_access_token", "show_units", "list_mode"}


def _migrate_legacy_fields(data: dict, svc: ServiceSettings):
    """If an old-format profile YAML has service-level fields, absorb them."""
    tt_data = data.get("transit_tracker", {})

    for key in _LEGACY_TT_KEYS:
        if key in tt_data:
            current_default = ServiceSettings.model_fields[key].default
            if getattr(svc, key) == current_default:
                setattr(svc, key, tt_data.pop(key))
            else:
                tt_data.pop(key)

    for key in _LEGACY_ROOT_KEYS:
        if key in data:
            current_default = ServiceSettings.model_fields[key].default
            if getattr(svc, key) == current_default:
                setattr(svc, key, data.pop(key))
            else:
                data.pop(key)

    # Strip dead fields
    for key in _DEAD_KEYS:
        tt_data.pop(key, None)
        data.pop(key, None)


class TransitConfig(BaseModel):
    """Runtime composite: merges a board subscription profile with service settings."""

    # Board subscription (from profile YAML)
    transit_tracker: TransitTrackerSettings = Field(
        default_factory=TransitTrackerSettings
    )

    # Service settings (from .local/service.yaml)
    service: ServiceSettings = Field(default_factory=ServiceSettings)

    # Derived fields (computed, not persisted)
    api_url: str = ""
    subscriptions: List[TransitSubscription] = Field(default_factory=list)

    # Testing state (runtime only)
    mock_state: Optional[List[Dict[str, Any]]] = None
    captures: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_internal_state(self) -> "TransitConfig":
        tt = self.transit_tracker
        svc = self.service

        # Compute api_url
        if svc.use_local_api:
            self.api_url = "ws://localhost:8000/"
        elif not self.api_url or tt.base_url != "wss://tt.horner.tj/":
            self.api_url = tt.base_url

        # Build flattened subscriptions from stops
        self.subscriptions = []
        for stop in tt.stops:
            for route in stop.routes:
                feed = route.split(":")[0] if ":" in route else "st"
                self.subscriptions.append(
                    TransitSubscription(
                        feed=feed,
                        route=route,
                        stop=stop.stop_id,
                        label=stop.label or f"Route {route}",
                        direction=stop.direction,
                        time_offset=stop.time_offset,
                    )
                )
        return self

    @classmethod
    def load(
        cls, path: str = "config.yaml", service_settings: ServiceSettings | None = None
    ) -> "TransitConfig":
        if service_settings is None:
            service_settings = load_service_settings()

        if not os.path.exists(path):
            local_path = os.path.join(".local", path)
            if os.path.exists(local_path):
                path = local_path
            else:
                return cls(service=service_settings)

        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        # Backward compat: absorb any legacy service fields from old profile YAMLs
        _migrate_legacy_fields(data, service_settings)

        tt_data = data.get("transit_tracker", data)
        return cls(
            transit_tracker=TransitTrackerSettings.model_validate(tt_data),
            service=service_settings,
        )

    def save(self, path: str = "config.yaml") -> None:
        """Save only the board subscription profile (transit_tracker block)."""
        if not os.path.dirname(path) and os.path.exists(".local"):
            path = os.path.join(".local", path)

        data = {
            "transit_tracker": self.transit_tracker.model_dump(exclude_defaults=False, by_alias=True)
        }
        with open(path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)


# ---------------------------------------------------------------------------
# Daylight schedule builder
# ---------------------------------------------------------------------------

# Timezone → representative (lat, lon) for astral sunrise/sunset calculation.
# Users configure only the timezone; coordinates are an implementation detail.
_TIMEZONE_COORDS: Dict[str, tuple] = {
    "America/Los_Angeles": (47.6062, -122.3321),   # Seattle
    "America/Denver": (39.7392, -104.9903),         # Denver
    "America/Chicago": (41.8781, -87.6298),         # Chicago
    "America/New_York": (40.7128, -74.0060),        # New York
    "America/Phoenix": (33.4484, -112.0740),        # Phoenix
    "America/Anchorage": (61.2181, -149.9003),      # Anchorage
    "Pacific/Honolulu": (21.3069, -157.8583),       # Honolulu
    "US/Pacific": (47.6062, -122.3321),
    "US/Mountain": (39.7392, -104.9903),
    "US/Central": (41.8781, -87.6298),
    "US/Eastern": (40.7128, -74.0060),
}
_DEFAULT_COORDS = (39.8283, -98.5795)  # Geographic center of CONUS


def build_daylight_schedule(
    dt: datetime.date,
    timezone: str,
    dawn_ramp_minutes: int = 30,
    dawn_ramp_steps: int = 6,
    dusk_ramp_minutes: int = 60,
    dusk_ramp_steps: int = 6,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> List[DimmingEntry]:
    """Build a dimming schedule from sunrise/sunset for the given date.

    Returns a list of DimmingEntry objects that ramp brightness up before
    sunrise and down after sunset, with full brightness during the day
    and off at night.
    """
    from astral import LocationInfo
    from astral.sun import sun

    if latitude is not None and longitude is not None:
        lat, lon = latitude, longitude
    else:
        fallback = _TIMEZONE_COORDS.get(timezone)
        if fallback is None:
            log.warning(
                "No coordinates for timezone %r and no lat/lon configured — "
                "using US default coords. Set daylight_latitude/daylight_longitude "
                "in service.yaml for accurate sunrise/sunset times.",
                timezone,
            )
        lat, lon = fallback or _DEFAULT_COORDS
    location = LocationInfo(
        name="auto", region="auto", timezone=timezone, latitude=lat, longitude=lon
    )
    s = sun(location.observer, date=dt, tzinfo=location.timezone)
    sunrise = s["sunrise"]
    sunset = s["sunset"]

    entries: List[DimmingEntry] = []

    # Dawn ramp: brightness 0→255 over dawn_ramp_minutes ending at sunrise
    for i in range(dawn_ramp_steps):
        fraction = (i + 1) / dawn_ramp_steps
        minutes_before = dawn_ramp_minutes * (1 - fraction)
        t = sunrise - datetime.timedelta(minutes=minutes_before)
        brightness = int(255 * fraction)
        entries.append(DimmingEntry(time=t.strftime("%H:%M"), brightness=brightness))

    # Dusk ramp: brightness 255→0 over dusk_ramp_minutes starting at sunset
    for i in range(dusk_ramp_steps):
        fraction = (i + 1) / dusk_ramp_steps
        minutes_after = dusk_ramp_minutes * fraction
        t = sunset + datetime.timedelta(minutes=minutes_after)
        brightness = int(255 * (1 - fraction))
        entries.append(DimmingEntry(time=t.strftime("%H:%M"), brightness=brightness))

    return entries


def evaluate_dimming_schedule(
    schedule: List[DimmingEntry], now_time: datetime.time
) -> Optional[int]:
    """Find the brightness from the most recent past schedule entry.

    Returns None if schedule is empty.
    Handles midnight wraparound: if current time is before all entries,
    uses the last entry from the sorted list (active from "yesterday").
    """
    if not schedule:
        return None

    sorted_entries = sorted(schedule, key=lambda e: e.time)
    # Walk backwards to find the latest entry at or before now
    result = None
    for entry in sorted_entries:
        entry_time = datetime.time(int(entry.time[:2]), int(entry.time[3:]))
        if entry_time <= now_time:
            result = entry.brightness
    # If no entry is at or before now, wrap around to the last entry
    if result is None:
        result = sorted_entries[-1].brightness
    return result
