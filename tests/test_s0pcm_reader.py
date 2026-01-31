"""
Tests for main module (s0pcm_reader.py).
"""

import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

# import s0pcm_reader - lazy imported


def test_main_initialization(mocker):
    """Test that main() initializes config and starts tasks."""
    import s0pcm_reader

    # Mock dependencies to prevent real initialization or threads
    mocker.patch("config.read_config")
    mock_t1_class = mocker.patch("s0pcm_reader.TaskReadSerial")
    mock_t2_class = mocker.patch("s0pcm_reader.TaskDoMQTT")
    mocker.patch("signal.signal")

    mock_t1 = MagicMock()
    mock_t2 = MagicMock()

    # Make them 'not alive' immediately so main exits
    mocker.patch("time.sleep")  # Prevent sleep delays

    # Needs to simulate being alive initially to enter loop, then dead to exit
    # OR, since main() waits for them to be alive, we can just make them dead immediately
    # IF the logic is "while t1.is_alive()..."
    # Let's check main.py logic. Assuming it waits for threads to be *started* or *alive*.
    # Actually, main usually does: t1.start(); t2.start(); while t1.is_alive() and t2.is_alive(): ...

    # So to exit the loop, one of them must return False.
    # So to exit the loop, one of them must return False eventually.
    # To run the loop body at least once (if needed), side_effect=[True, False]
    # This ensures lines 80-82 are covered.
    # Iter 1: t1=True (enters loop)
    # Iter 2: t1=False, t2=False (exits loop)
    mock_t1.is_alive.side_effect = [True, False]
    mock_t2.is_alive.return_value = False

    mock_t1_class.return_value = mock_t1
    mock_t2_class.return_value = mock_t2

    # Patch logger to avoid stdout pollution
    mocker.patch("s0pcm_reader.logger")

    # Call main
    s0pcm_reader.main()

    # Verify read_config was called
    import config as config_module_imp

    config_module_imp.read_config.assert_called_once()

    # Verify tasks were created and started
    mock_t1_class.assert_called_once()
    mock_t1.start.assert_called_once()
    mock_t2_class.assert_called_once()
    mock_t2.start.assert_called_once()


def test_signal_handler(mocker):
    """Test the internal signal handler sets stopper and trigger."""
    import s0pcm_reader

    mocker.patch("config.read_config")
    mocker.patch("s0pcm_reader.TaskReadSerial")
    mocker.patch("s0pcm_reader.TaskDoMQTT")
    mocker.patch("s0pcm_reader.logger")

    # Mock signal.signal to capture the handler
    captured_handler = None

    def mock_signal_call(sig, handler):
        nonlocal captured_handler
        captured_handler = handler

    mocker.patch("signal.signal", side_effect=mock_signal_call)

    # We need to mock the alive status to exit main (run once then stop)
    mock_t1 = MagicMock()
    mock_t1.is_alive.side_effect = [True, False]
    mocker.patch("s0pcm_reader.TaskReadSerial", return_value=mock_t1)

    # Needs to be mocked to return something that isn't alive to exit loop
    mocker.patch("s0pcm_reader.TaskDoMQTT", return_value=MagicMock(is_alive=lambda: False))

    # Instantiate global mocks for main to use
    s0pcm_reader.stopper = threading.Event()
    s0pcm_reader.trigger = threading.Event()

    # Call main to set up the handler
    s0pcm_reader.main()

    # Now verify the handler logic (it should set stopper and trigger)
    assert captured_handler is not None

    captured_handler(signal.SIGINT, None)

    assert s0pcm_reader.stopper.is_set()
    assert s0pcm_reader.trigger.is_set()


def test_main_config_exception_exit(mocker):
    """Test main exit on config exception (lines 60-62)."""
    import s0pcm_reader

    # Defensive: Mock tasks to be dead on arrival, preventing infinite loop in main
    # if the exception is missed.
    mock_t1_cls = mocker.patch("s0pcm_reader.TaskReadSerial")
    mock_t2_cls = mocker.patch("s0pcm_reader.TaskDoMQTT")

    # Ensure instances created from these classes return False for is_alive()
    # explicitly setting return_value on the method mock.
    mock_t1_cls.return_value.is_alive.return_value = False
    mock_t2_cls.return_value.is_alive.return_value = False

    # Patch the exact reference used in s0pcm_reader
    # s0pcm_reader.py does 'import config as config_module'
    mocker.patch("s0pcm_reader.config_module.read_config", side_effect=Exception("Config Error"))
    mocker.patch("s0pcm_reader.logger")

    with pytest.raises(SystemExit) as excinfo:
        s0pcm_reader.main()

    assert excinfo.value.code == 1


def test_init_args_coverage():
    """Test init_args function coverage (line 55)."""
    import s0pcm_reader

    # We can just call it to cover the function definition, even if not run in main
    # But init_args parses sys.argv. We should mock argparse.
    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value.config = "/tmp/test"
        s0pcm_reader.init_args()
        assert s0pcm_reader.config_module.configdirectory.startswith("/tmp/test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
