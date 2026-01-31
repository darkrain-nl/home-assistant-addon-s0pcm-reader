"""
S0PCM Reader State

Managed global state, threading locks, errors, and measurement data.
"""

import datetime
import logging
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


class AppState(BaseModel):
    """Complete application state (measurements and date)."""

    date: datetime.date = Field(default_factory=datetime.date.today)
    meters: dict[int, MeterState] = Field(default_factory=dict)

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
        self.state_share = AppState()  # Snapshot for MQTT

        # Configuration (To be populated as ConfigModel)
        self.config: dict[str, Any] = {}

        # Error State
        self.lasterror_serial: str | None = None
        self.lasterror_mqtt: str | None = None
        self.lasterror_share: str | None = None

        # Metadata
        self.startup_time: str = datetime.datetime.now(datetime.UTC).isoformat()
        self.s0pcm_firmware: str = "Unknown"
        self.s0pcm_reader_version: str = "Unknown"

    def register_trigger(self, event: threading.Event):
        """Register the main trigger event for MQTT publishing."""
        self.trigger_event = event

    def set_error(
        self, message: str | None, category: str = "serial", trigger_event: bool = True, level: int | None = None
    ):
        """Set or clear an error state."""
        changed = False
        if category == "serial":
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
