"""
S0PCM Reader State

Managed global state, threading locks, errors, and measurement data.
"""

import datetime
import json
import logging
import threading
from pathlib import Path

import config as config_module

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------
# Threading & Events
# ------------------------------------------------------------------------------------
lock = threading.RLock()
recovery_event = threading.Event()

# ------------------------------------------------------------------------------------
# Global State
# ------------------------------------------------------------------------------------
config = {}
measurement = {'date': datetime.date.today()}
measurementshare = {}

# ------------------------------------------------------------------------------------
# Error State
# ------------------------------------------------------------------------------------
lasterror_serial = None
lasterror_mqtt = None
lasterrorshare = None

# ------------------------------------------------------------------------------------
# Metadata
# ------------------------------------------------------------------------------------
startup_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
s0pcm_firmware = "Unknown"
s0pcmreaderversion = "Unknown"


def set_error(message, category='serial', trigger_event=True):
    """
    Set or clear an error state for a specific category.
    
    Updates shared error string and optionally triggers the event loop (via global trigger).
    Note: Requires 'trigger' to be injected into this module or set globally if using
    legacy architecture.
    """
    global lasterror_serial, lasterror_mqtt, lasterrorshare
    
    # We need access to the main trigger event. 
    # In the refactored design, this might be better returned or handled via callback.
    # For now, we assume 'trigger' is available in the importing scope or injected.
    # To break the circular dependency, we might need a registry.
    
    # IMPROVEMENT: For this refactor step, we'll import trigger from main ONLY if needed
    # but strictly speaking, circular imports are bad. 
    # Better approach: Allow registering a callback.
    pass 

# Temporary hook for trigger event (will be set by main)
_trigger_event = None


def register_trigger(event):
    global _trigger_event
    _trigger_event = event


def set_error_impl(message, category='serial', trigger_event=True, level=None):
    """Implementation of SetError logic."""
    global lasterror_serial, lasterror_mqtt, lasterrorshare

    changed = False
    if category == 'serial':
        if message != lasterror_serial:
            lasterror_serial = message
            changed = True
    else:
        if message != lasterror_mqtt:
            lasterror_mqtt = message
            changed = True

    if changed:
        # Update the shared state
        errors = []
        if lasterror_serial:
            errors.append(lasterror_serial)
        if lasterror_mqtt:
            errors.append(lasterror_mqtt)
        
        new_error = " | ".join(errors) if errors else None
        
        with lock:
            lasterrorshare = new_error

        if message:
            # Use requested level for log (defaults to ERROR)
            llvl = level if level is not None else logging.ERROR
            logger.log(llvl, f"[{category.upper()}] {message}")
        
        if trigger_event and _trigger_event:
            # Trigger MQTT publish
            _trigger_event.set()


# ------------------------------------------------------------------------------------
# Measurement Persistence (Stateless Mode)
# ------------------------------------------------------------------------------------
def save_measurement():
    """No-op in stateless mode. Persistence is handled via MQTT retained messages."""
    pass


def read_measurement():
    """Read measurement.json (legacy) or initialize defaults."""
    global measurement
    path = Path(config_module.measurementname)

    try:
        if not path.exists():
            logger.warning(f"No '{config_module.measurementname}' found, using defaults.")
            measurement = {}
        else:
            data = json.loads(path.read_text())
            measurement = data if isinstance(data, dict) else {}
            if not isinstance(data, dict):
                logger.error(f"'{config_module.measurementname}' content is not a dictionary ({type(data)}). Using defaults.")
    except Exception as e:
        logger.error(f"Failed to read '{config_module.measurementname}': {e}. Using defaults.")
        measurement = {}

    # JSON keys are always strings, convert meter IDs back to integers
    new_measurement = {}
    for k, v in measurement.items():
        try:
            new_measurement[int(k)] = v
        except ValueError:
            new_measurement[k] = v
    measurement = new_measurement

    # Handle Date
    saved_date = measurement.get('date')
    if saved_date:
        try:
            if isinstance(saved_date, str):
                measurement['date'] = datetime.date.fromisoformat(saved_date)
            elif isinstance(saved_date, datetime.datetime):
                measurement['date'] = saved_date.date()
            elif not isinstance(saved_date, datetime.date):
                measurement['date'] = datetime.date.fromisoformat(str(saved_date))
        except ValueError:
            set_error_impl(f"'{config_module.measurementname}' has an invalid date field '{saved_date}', defaulting to today.", category='serial')
            measurement['date'] = datetime.date.today()
    else:
        measurement['date'] = datetime.date.today()

    logger.debug(f"Measurement: {str(measurement)}")


# Backwards compatibility aliases
SetError = set_error_impl
SaveMeasurement = save_measurement
ReadMeasurement = read_measurement
