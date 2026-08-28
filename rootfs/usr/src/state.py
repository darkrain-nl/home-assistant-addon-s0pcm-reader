"""Global application state, event triggers, and error management."""

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from config import ConfigModel

logger = logging.getLogger(__name__)

type ErrorCategory = Literal["serial", "mqtt"]


class MeterState(BaseModel):
    """Current counter values and configuration for a single meter."""

    name: str | None = None
    total: int = 0
    today: int = 0
    yesterday: int = 0
    pulsecount: int = 0
    enabled: bool = True


class AppState(BaseModel):
    """Aggregate application state holding meters and rollover date."""

    date: datetime.date = Field(default_factory=datetime.date.today)
    meters: dict[int, MeterState] = Field(default_factory=dict)

    def reset_state(self) -> Self:
        """Reset all meter counters to zero and update current date."""
        self.date = datetime.date.today()
        self.meters = {}
        return self


class AppContext:
    """Shared application context passed across asynchronous tasks."""

    def __init__(self):
        self.recovery_event = asyncio.Event()
        self.trigger_event = asyncio.Event()

        self.state = AppState()
        self.config: ConfigModel | None = None

        self.lasterror_serial: str | None = None
        self.lasterror_mqtt: str | None = None
        self.lasterror_share: str | None = None

        self.startup_time: str = datetime.datetime.now(datetime.UTC).isoformat()
        self.s0pcm_firmware: str = "Unknown"
        self.s0pcm_reader_version: str = "Unknown"

    def set_error(
        self,
        message: str | None,
        category: ErrorCategory = "serial",
        trigger_event: bool = True,
        level: int | None = None,
    ):
        """Update error state and notify subscribers on change."""
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

            self.lasterror_share = " | ".join(errors) if errors else None

            if message:
                log_level = level if level is not None else logging.ERROR
                logger.log(log_level, f"[{category.upper()}] {message}")

            if trigger_event:
                self.trigger_event.set()


_context = AppContext()


def get_context() -> AppContext:
    """Return shared singleton application context."""
    return _context
