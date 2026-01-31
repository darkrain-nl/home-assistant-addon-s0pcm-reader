"""
S0PCM Reader State

Managed global state, threading locks, errors, and measurement data.
"""

import datetime
import logging
import sys
import threading
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------------

class MeterState(BaseModel):
    """Current state of a single meter."""
    name: str | None = None
    total: int = 0
    today: int = 0
    yesterday: int = 0
    pulsecount: int = 0
    enabled: bool = True

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def setdefault(self, key: str, default: Any) -> Any:
        if not hasattr(self, key) or getattr(self, key) is None:
            setattr(self, key, default)
        return getattr(self, key)

    def pop(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, default)
        if hasattr(self, key):
            setattr(self, key, None) # Or default value? Models usually don't "remove" fields
        return val

    def keys(self):
        return self.model_fields.keys()

    def items(self):
        return self.model_dump().items()

    def __iter__(self):
        return iter(self.keys())

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) is not None


class AppState(BaseModel):
    """Complete application state (measurements and date)."""
    date: datetime.date = Field(default_factory=datetime.date.today)
    meters: dict[int, MeterState] = Field(default_factory=dict)

    def __getitem__(self, key: Any) -> Any:
        if key == 'date':
            return self.date
        return self.meters[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        if key == 'date':
            if isinstance(value, str):
                try:
                    self.date = datetime.date.fromisoformat(value)
                except ValueError:
                    # Fallback or log? For tests, we'll try to keep going
                    pass
            else:
                self.date = value
        else:
            if isinstance(value, dict):
                self.meters[key] = MeterState(**value)
            else:
                self.meters[key] = value

    def __contains__(self, key: Any) -> bool:
        if key == 'date':
            return True
        return key in self.meters

    def update(self, data: dict[Any, Any]) -> None:
        if 'date' in data:
            self.date = data.pop('date')
            if isinstance(self.date, str):
                 try:
                     self.date = datetime.date.fromisoformat(self.date)
                 except ValueError:
                     pass

        for k, v in data.items():
            try:
                meter_id = int(k)
                if isinstance(v, dict):
                    if meter_id not in self.meters:
                        self.meters[meter_id] = MeterState(**v)
                    else:
                        # Update existing model fields
                        for field, val in v.items():
                            if hasattr(self.meters[meter_id], field):
                                setattr(self.meters[meter_id], field, val)
                elif isinstance(v, MeterState):
                    self.meters[meter_id] = v
                else:
                    # Possibly a legacy object or weird state
                    pass
            except (ValueError, TypeError):
                continue

    def get(self, key: Any, default: Any = None) -> Any:
        if key == 'date':
            return self.date
        return self.meters.get(key, default)

    def keys(self):
        return list(self.meters.keys()) + ['date']

    def values(self):
        return list(self.meters.values()) + [self.date]

    def items(self):
        return list(self.meters.items()) + [('date', self.date)]

    def __iter__(self):
        return iter(self.keys())

    def pop(self, key: Any, default: Any = None) -> Any:
        if key == 'date':
            val = self.date
            self.date = datetime.date.today()
            return val
        return self.meters.pop(key, default)

    def reset_state(self) -> None:
        """Reset state to defaults."""
        self.date = datetime.date.today()
        self.meters = {}


class AppContext:
    """
    Application context holding all shared state, locks, and events.

    This class is intended to be passed to components, reducing reliance on global state.
    """
    def __init__(self):
        # Threading & Events
        self.lock = threading.RLock()
        self.recovery_event = threading.Event()
        self.trigger_event: threading.Event | None = None

        # Application State
        self.state = AppState()
        self.state_share = AppState() # Snapshot for MQTT

        # Configuration (To be populated as ConfigModel)
        self.config: dict[str, Any] = {}

        # Error State
        self.lasterror_serial: str | None = None
        self.lasterror_mqtt: str | None = None
        self.lasterror_share: str | None = None

        # Metadata
        self.startup_time: str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.s0pcm_firmware: str = "Unknown"
        self.s0pcm_reader_version: str = "Unknown"

    def register_trigger(self, event: threading.Event):
        """Register the main trigger event for MQTT publishing."""
        self.trigger_event = event

    def set_error(self, message: str | None, category: str = 'serial', trigger_event: bool = True, level: int | None = None):
        """Set or clear an error state."""
        changed = False
        if category == 'serial':
            if message != self.lasterror_serial:
                self.lasterror_serial = message
                changed = True
        else:
            if message != self.lasterror_mqtt:
                self.lasterror_mqtt = message
                changed = True

        if changed:
            errors = []
            if self.lasterror_serial:
                errors.append(self.lasterror_serial)
            if self.lasterror_mqtt:
                errors.append(self.lasterror_mqtt)

            new_error = " | ".join(errors) if errors else None

            with self.lock:
                self.lasterror_share = new_error

            if message:
                log_level = level if level is not None else logging.ERROR
                logger.log(log_level, f"[{category.upper()}] {message}")

            if trigger_event and self.trigger_event:
                self.trigger_event.set()

    def save_measurement(self):
        """Deprecated: No-op. Persistence is handled via MQTT retained messages."""
        pass

    def read_measurement(self, measurement_file: str | None = None):
        """Deprecated: Startup recovery is now handled by recovery.py."""
        pass


# ------------------------------------------------------------------------------------
# Global Instance (for backwards compatibility during transition)
# ------------------------------------------------------------------------------------
_context = AppContext()

# For direct access to context if needed
def get_context() -> AppContext:
    return _context
