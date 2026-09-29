from unittest.mock import MagicMock, patch
import pytest
from transit_tracker.cli import main

pytestmark = pytest.mark.unit


def test_cli_main_ui_launch():
    """Verifies that running with no args (default 'ui') attempts to launch the TUI."""
    # Mock everything that main calls
    with (
        patch("transit_tracker.cli.get_last_config_path", return_value=None),
        patch("transit_tracker.cli.TransitConfig.load") as mock_load,
        patch("transit_tracker.cli.run_cli") as mock_tui,
        patch("argparse.ArgumentParser.parse_args") as mock_args,
    ):
        # Setup mock args for 'ui'
        mock_args.return_value = MagicMock()
        mock_args.return_value.command = ["ui"]

        # Run main
        main()

        # Assertions
        mock_load.assert_called()
        mock_tui.assert_called_once()


def test_cli_main_simulator_launch():
    """Verifies that 'simulator' command works."""
    with (
        patch("transit_tracker.cli.get_last_config_path", return_value=None),
        patch("transit_tracker.cli.TransitConfig.load") as mock_load,
        patch("transit_tracker.cli.run_cli"),
        patch("transit_tracker.simulator.run_simulator") as mock_sim,
        patch("argparse.ArgumentParser.parse_args") as mock_args,
    ):
        mock_args.return_value = MagicMock()
        mock_args.return_value.command = ["simulator"]

        main()

        mock_sim.assert_called_once()


def test_service_start_idempotency():
    """Verifies that 'service start' does nothing if the agent is already loaded."""
    mock_list = MagicMock()
    mock_list.returncode = 0
    mock_list.stdout = ""

    with (
        patch("subprocess.run", return_value=mock_list) as mock_run,
        patch("os.system") as mock_system,
        patch("argparse.ArgumentParser.parse_args") as mock_args,
    ):
        mock_args.return_value = MagicMock()
        mock_args.return_value.command = ["service", "start"]

        main()

        # launchctl list is consulted; nothing is loaded and docker is never touched
        assert any("launchctl" in str(c) for c in mock_run.call_args_list)
        assert not any("docker" in str(c) for c in mock_run.call_args_list)
        mock_system.assert_not_called()


def test_service_stop_cleanup():
    """Verifies that 'service stop' unloads the agent, never docker."""
    with (
        patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        patch("os.system") as mock_system,
        patch("argparse.ArgumentParser.parse_args") as mock_args,
    ):
        mock_args.return_value = MagicMock()
        mock_args.return_value.command = ["service", "stop"]

        main()

        assert any("launchctl unload" in str(c) for c in mock_system.call_args_list)
        assert not any("docker" in str(c) for c in mock_run.call_args_list)
