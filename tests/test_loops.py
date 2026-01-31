"""
Integration tests for the task loops.
"""
import pytest
import threading
from unittest.mock import MagicMock, patch
import s0pcm_reader
import state as state_module

def test_task_do_mqtt_loop_execution(mocker):
    """Integrate TaskDoMQTT loop without infinite blocking."""
    context = state_module.get_context()
    context.config.update({
        'mqtt': {
            'base_topic': 's0', 'discovery': True, 'discovery_prefix': 'ha',
            'online': 'on', 'offline': 'off', 'retain': True, 'client_id': None, 'version': 5,
            'split_topic': True
        }
    })

    # Update shared state
    context.state_share.reset_state()
    context.state_share.update({1: {'name': 'Water', 'total': 10}})

    trigger = threading.Event()
    stopper = threading.Event()
    task = s0pcm_reader.TaskDoMQTT(trigger, stopper)

    # Mock connection and client
    task._connected = True
    task._mqttc = MagicMock()

    # Counter to allow one loop then exit
    loop_count = 0
    def stop_logic():
        nonlocal loop_count
        loop_count += 1
        if loop_count >= 1:
            stopper.set()
            trigger.set() # Wake up!

    mocker.patch.object(task, '_publish_diagnostics', side_effect=stop_logic)
    mocker.patch('mqtt_handler.discovery.send_global_discovery')
    mocker.patch('mqtt_handler.discovery.send_meter_discovery')

    # Run the loop
    task._main_loop()
    assert stopper.is_set()

def test_task_read_serial_loop_execution(mocker):
    """Integrate TaskReadSerial loop."""
    context = state_module.get_context()
    context.config.update({'serial': {'connect_retry': 0.1}})

    stopper = threading.Event()
    task = s0pcm_reader.TaskReadSerial(threading.Event(), stopper)

    # CRITICAL: Serial task waits for recovery event!
    context.recovery_event.set()

    mocker.patch.object(task, '_connect', return_value=MagicMock())

    def stop_logic(ser):
        stopper.set()
    mocker.patch.object(task, '_read_loop', side_effect=stop_logic)

    task.run()
    assert stopper.is_set()
