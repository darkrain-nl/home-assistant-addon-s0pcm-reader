"""Unit tests for s0pcm_reader main orchestration loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_main_initialization(mocker):
    """Test that main() initializes config and starts tasks."""
    import s0pcm_reader

    mocker.patch("s0pcm_reader.get_version", new_callable=AsyncMock)
    mock_read_config = mocker.patch("s0pcm_reader.config_module.read_config", new_callable=AsyncMock)

    mock_serial_task = mocker.patch("s0pcm_reader.serial_task", new_callable=AsyncMock)
    mock_mqtt_task = mocker.patch("s0pcm_reader.mqtt_task", new_callable=AsyncMock)

    mocker.patch("s0pcm_reader.logger")

    await s0pcm_reader.main()

    mock_read_config.assert_called_once()
    mock_serial_task.assert_called_once()
    mock_mqtt_task.assert_called_once()


async def test_main_config_exception_exit(mocker):
    """Test main exit on config exception."""
    import s0pcm_reader

    mocker.patch("s0pcm_reader.get_version", new_callable=AsyncMock)
    mocker.patch(
        "s0pcm_reader.config_module.read_config", new_callable=AsyncMock, side_effect=Exception("Config Error")
    )
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
    """Test a termination signal cancels the task group cleanly."""
    import s0pcm_reader

    mocker.patch("s0pcm_reader.get_version", new_callable=AsyncMock)
    mocker.patch("s0pcm_reader.config_module.read_config", new_callable=AsyncMock)
    mocker.patch("s0pcm_reader.logger")

    mock_loop = MagicMock()
    mocker.patch("asyncio.get_running_loop", return_value=mock_loop)
    cancelled = []

    async def blocking_task(context):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append("serial")
            raise

    async def signalling_task(context):
        mock_loop.add_signal_handler.call_args.args[1]()

    mocker.patch("s0pcm_reader.serial_task", side_effect=blocking_task)
    mocker.patch("s0pcm_reader.mqtt_task", side_effect=signalling_task)

    # Fail rather than hang when the signal leaves the group running.
    async with asyncio.timeout(1):
        await s0pcm_reader.main()

    assert mock_loop.add_signal_handler.call_count == 2
    assert cancelled == ["serial"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
