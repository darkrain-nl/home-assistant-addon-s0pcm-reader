"""
Tests for main module (s0pcm_reader.py).
"""

from unittest.mock import AsyncMock, patch

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
