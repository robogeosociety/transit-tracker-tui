"""The shared-TEST-key startup guard.

OneBusAway publishes a demo key called ``TEST``. Both key-resolution sites end
their chain with ``or "TEST"``, so a missing or unreadable ``service.yaml``
used to produce a service that started cleanly and ran on a throttled feed —
and the symptom on the sign (everything scheduled, nothing live) is
indistinguishable from a real upstream outage.

These pin the refusal, and pin the deliberate opt-out that
``tests/test_container.py`` depends on.
"""

from types import SimpleNamespace

import pytest

from transit_tracker import cli

pytestmark = pytest.mark.unit


def _config(key):
    return SimpleNamespace(service=SimpleNamespace(oba_api_key=key))


def test_real_key_starts(monkeypatch):
    monkeypatch.delenv("OBA_API_KEY", raising=False)
    monkeypatch.delenv(cli.ALLOW_TEST_KEY_ENV, raising=False)
    cli._assert_real_oba_key(_config("a-real-key"))  # must not raise


def test_env_key_starts(monkeypatch):
    monkeypatch.setenv("OBA_API_KEY", "a-real-key")
    monkeypatch.delenv(cli.ALLOW_TEST_KEY_ENV, raising=False)
    cli._assert_real_oba_key(_config(None))


def test_no_key_anywhere_refuses(monkeypatch):
    monkeypatch.delenv("OBA_API_KEY", raising=False)
    monkeypatch.delenv(cli.ALLOW_TEST_KEY_ENV, raising=False)
    with pytest.raises(cli.TestKeyRefused) as exc:
        cli._assert_real_oba_key(_config(None))
    # The message has to be actionable at 3am, not just correct.
    msg = str(exc.value)
    assert "oba_api_key" in msg
    assert cli.ALLOW_TEST_KEY_ENV in msg


def test_explicit_test_key_refuses(monkeypatch):
    """Setting it to TEST on purpose is the same trap, spelled differently."""
    monkeypatch.delenv("OBA_API_KEY", raising=False)
    monkeypatch.delenv(cli.ALLOW_TEST_KEY_ENV, raising=False)
    with pytest.raises(cli.TestKeyRefused):
        cli._assert_real_oba_key(_config("TEST"))


@pytest.mark.parametrize("value", ["1", "true", "yes", " 1 "])
def test_opt_out_allows_test_key(monkeypatch, value):
    """test_container.py boots the image keyless on purpose and needs this."""
    monkeypatch.delenv("OBA_API_KEY", raising=False)
    monkeypatch.setenv(cli.ALLOW_TEST_KEY_ENV, value)
    cli._assert_real_oba_key(_config(None))


@pytest.mark.parametrize("value", ["0", "", "no", "maybe"])
def test_unset_or_falsey_opt_out_still_refuses(monkeypatch, value):
    monkeypatch.delenv("OBA_API_KEY", raising=False)
    monkeypatch.setenv(cli.ALLOW_TEST_KEY_ENV, value)
    with pytest.raises(cli.TestKeyRefused):
        cli._assert_real_oba_key(_config(None))


def test_config_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("OBA_API_KEY", "TEST")
    monkeypatch.delenv(cli.ALLOW_TEST_KEY_ENV, raising=False)
    cli._assert_real_oba_key(_config("a-real-key"))


def test_settings_load_failure_is_logged_not_swallowed(tmp_path):
    """A broken service.yaml must say so — it silently meant 'no API key'."""
    import logging
    import os

    from transit_tracker import config as config_mod

    bad = tmp_path / "service.yaml"
    bad.write_text("oba_api_key: [unclosed\n")

    records = []

    class _Recorder(logging.Handler):
        def emit(self, record):
            records.append(record)

    # config's logger sets propagate=False, so caplog alone would not see this.
    recorder = _Recorder()
    config_mod.log.addHandler(recorder)
    os.environ["SERVICE_SETTINGS_PATH"] = str(bad)
    try:
        settings = config_mod.load_service_settings()
    finally:
        os.environ.pop("SERVICE_SETTINGS_PATH", None)
        config_mod.log.removeHandler(recorder)

    assert settings.oba_api_key is None, "a broken file must not invent a key"
    assert any(
        "Could not load service settings" in r.getMessage() for r in records
    ), "the failure must be logged, not swallowed"
