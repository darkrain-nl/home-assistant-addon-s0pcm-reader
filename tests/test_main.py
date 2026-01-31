"""
Tests for the main entry point and global application setup.
"""
import pytest
import threading
import signal
from unittest.mock import MagicMock, patch
import s0pcm_reader

def test_main_initialization(mocker):
    """Test that main() initializes config and starts tasks."""
    # Mock dependencies to prevent real initialization or threads
    mocker.patch('config.read_config')
    mock_t1_class = mocker.patch('s0pcm_reader.TaskReadSerial')
    mock_t2_class = mocker.patch('s0pcm_reader.TaskDoMQTT')
    mocker.patch('signal.signal')

    mock_t1 = MagicMock()
    mock_t2 = MagicMock()

    # Make them 'not alive' immediately so main exits
    mock_t1.is_alive.return_value = False
    mock_t2.is_alive.return_value = False

    mock_t1_class.return_value = mock_t1
    mock_t2_class.return_value = mock_t2

    # Patch logger to avoid stdout pollution
    mocker.patch('s0pcm_reader.logger')

    # Call main
    s0pcm_reader.main()

    # Verify read_config was called
    import config as config_module
    config_module.read_config.assert_called_once()

    # Verify tasks were created and started
    mock_t1_class.assert_called_once()
    mock_t1.start.assert_called_once()
    mock_t2_class.assert_called_once()
    mock_t2.start.assert_called_once()


def test_signal_handler(mocker):
    """Test the internal signal handler sets stopper and trigger."""
    mocker.patch('config.read_config')
    mocker.patch('s0pcm_reader.TaskReadSerial')
    mocker.patch('s0pcm_reader.TaskDoMQTT')
    mocker.patch('s0pcm_reader.logger')

    # Mock signal.signal to capture the handler
    captured_handler = None
    def mock_signal_call(sig, handler):
        nonlocal captured_handler
        captured_handler = handler

    mocker.patch('signal.signal', side_effect=mock_signal_call)

    # We need to mock the alive status to exit main
    # t1 and t2 are local to main, so this test is slightly tricky.
    # Instead, let's just verify the logic of the handler if we can extract it
    # but it's a nested function.

    # Let's use a patch on TaskReadSerial that makes it "alive" for 1 check
    # then "dead" for the next.
    mock_t1 = MagicMock()
    mock_t1.is_alive.side_effect = [True, False]
    mocker.patch('s0pcm_reader.TaskReadSerial', return_value=mock_t1)

    # Instantiate global mocks for main to use
    s0pcm_reader.stopper = threading.Event()
    s0pcm_reader.trigger = threading.Event()

    # Call main to set up the handler
    with patch('s0pcm_reader.TaskDoMQTT', return_value=MagicMock(is_alive=lambda: False)):
        s0pcm_reader.main()

    # Now verify the handler logic (it should set stopper and trigger)
    # The handler is defined inside main, so we captured it.
    assert captured_handler is not None

    captured_handler(signal.SIGINT, None)

    assert s0pcm_reader.stopper.is_set()
    assert s0pcm_reader.trigger.is_set()

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
