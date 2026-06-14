"""
Tests for main module (s0pcm_reader.py).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_main_initialization(mocker):
    """Test that main() initializes config and starts tasks."""
    import s0pcm_reader

    mocker.patch("config.read_config")

    # Mock serial_task and mqtt_task as async functions
    mock_serial_task = mocker.patch("s0pcm_reader.serial_task", new_callable=AsyncMock)
    mock_mqtt_task = mocker.patch("s0pcm_reader.mqtt_task", new_callable=AsyncMock)

    mocker.patch("s0pcm_reader.logger")

    await s0pcm_reader.main()

    # Verify read_config was called
    import config as config_module_imp

    config_module_imp.read_config.assert_called_once()

    # Verify tasks were started (called as coroutines in TaskGroup)
    mock_serial_task.assert_called_once()
    mock_mqtt_task.assert_called_once()


async def test_main_config_exception_exit(mocker):
    """Test main exit on config exception."""
    import s0pcm_reader

    mocker.patch("s0pcm_reader.config_module.read_config", side_effect=Exception("Config Error"))
    mocker.patch("s0pcm_reader.logger")

    with pytest.raises(SystemExit) as excinfo:
        await s0pcm_reader.main()

    assert excinfo.value.code == 1


def test_init_args_coverage():
    """Test init_args function coverage."""
    import config as config_module_imp

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value.config = "/tmp/test"
        result_path = config_module_imp.init_args()
        assert str(result_path) == "/tmp/test"


async def test_main_signal_handler(mocker):
    """Test signal handler registration and execution."""
    import s0pcm_reader

    mocker.patch("config.read_config")
    mocker.patch("s0pcm_reader.serial_task", new_callable=AsyncMock)
    mocker.patch("s0pcm_reader.mqtt_task", new_callable=AsyncMock)
    mocker.patch("s0pcm_reader.logger")

    mock_loop = MagicMock()
    mocker.patch("asyncio.get_running_loop", return_value=mock_loop)

    mock_task = MagicMock()
    mocker.patch("asyncio.all_tasks", return_value={mock_task})

    await s0pcm_reader.main()

    # Verify add_signal_handler was called for SIGINT and SIGTERM
    assert mock_loop.add_signal_handler.call_count == 2

    # Extract the registered signal handler function
    sig_handler = mock_loop.add_signal_handler.call_args[0][1]

    # Call the signal handler
    sig_handler()

    # Verify it cancelled the tasks
    mock_task.cancel.assert_called_once()


async def test_main_cancellation_handling(mocker):
    """Test that main() handles CancelledError ExceptionGroup gracefully."""
    import s0pcm_reader

    mocker.patch("config.read_config")
    mocker.patch("s0pcm_reader.logger")

    # Mock TaskGroup to raise BaseExceptionGroup containing CancelledError
    class MockTaskGroup:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise BaseExceptionGroup("group", [asyncio.CancelledError()])

        def create_task(self, coro):
            pass

    mocker.patch("asyncio.TaskGroup", return_value=MockTaskGroup())

    # This should run without raising because BaseExceptionGroup containing CancelledError is caught by except*
    await s0pcm_reader.main()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
