"""
Tests for signal handling in S0PCM Reader main.
"""

import signal
from unittest.mock import MagicMock, patch

import s0pcm_reader


def test_signal_handler_sets_events():
    """Test that the signal handler sets both stopper and trigger events."""
    # We need to simulate how signal_handler is defined inside main()
    # or just test the logic if we can extract it. 
    # Since it's nested, we'll mock signal.signal to capture the handler.
    
    # Reset events
    s0pcm_reader.stopper.clear()
    s0pcm_reader.trigger.clear()
    
    handlers = {}
    
    def mock_signal(sig, handler):
        handlers[sig] = handler
        
    with patch("signal.signal", side_effect=mock_signal), \
         patch("s0pcm_reader.get_version", return_value="3.0.0"), \
         patch("s0pcm_reader.config_module.read_config"), \
         patch("s0pcm_reader.state_module.get_context"), \
         patch("s0pcm_reader.TaskReadSerial"), \
         patch("s0pcm_reader.TaskDoMQTT"):
        
        # We don't want to run the whole main loop, so we mock the tasks to not start 
        # or we mock the while loop.
        
        # Instead of running main, let's just find where it registers the signals 
        # and call that handler.
        
        # Re-verify the handler logic in s0pcm_reader.py:
        # def signal_handler(signum: int, frame: Any) -> None:
        #     logger.info(f"Signal {signum} received, stopping...")
        #     stopper.set()
        #     trigger.set()
        
        # We can trigger it by actually running main in a thread and sending a signal,
        # but mocking is cleaner.
        
        # Let's mock main's blocking part (the while loop)
        # We need to ensure that the while loop in s0pcm_reader.main() terminates.
        # It waits for t1 or t2 to be alive.
        
        # We'll use a side_effect to make it run once
        with patch("s0pcm_reader.TaskReadSerial") as mock_t1_class, \
             patch("s0pcm_reader.TaskDoMQTT") as mock_t2_class:
            
            mock_t1 = mock_t1_class.return_value
            mock_t2 = mock_t2_class.return_value
            
            mock_t1.is_alive.return_value = True
            # We need to make is_alive return False on the next call to exit the loop
            # But in s0pcm_reader.main it's a method call! t1.is_alive()
            mock_t1.is_alive.side_effect = [True, False]
            mock_t2.is_alive.return_value = False
            
            s0pcm_reader.main()
            
            # Now we should have the handler captured in our 'handlers' dict
            handler = handlers.get(signal.SIGINT)
            assert handler is not None
            
            # Call the handler
            handler(signal.SIGINT, None)
            
            assert s0pcm_reader.stopper.is_set()
            assert s0pcm_reader.trigger.is_set()
