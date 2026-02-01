"""
Serial Handler Module

Contains the TaskReadSerial class for reading and parsing S0PCM data from serial port.
"""

from dataclasses import dataclass
import datetime
import logging
import threading
import time

import serial

from constants import SerialPacketType
from protocol import parse_s0pcm_packet
import state as state_module

logger = logging.getLogger(__name__)


@dataclass
class SerialTaskState:
    """Internal state for Serial task."""

    serialerror: int = 0


class TaskReadSerial(threading.Thread):
    """
    Task to read the serial port and update meter measurements.

    This thread continuously reads from the configured serial port, parses S0PCM packets,
    and updates the application state.
    """

    def __init__(self, context: state_module.AppContext, trigger: threading.Event, stopper: threading.Event) -> None:
        """
        Initialize the serial reader task.

        Args:
            context: Application context.
            trigger: Event to signal when new data is available.
            stopper: Event to signal when the task should stop.
        """
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._state = SerialTaskState()
        self.app_context = context

    def _connect(self) -> serial.Serial | None:
        """
        Established a connection to the serial port.

        Returns:
            serial.Serial: The connected serial object, or None if failed and stopped.
        """
        while not self._stopper.is_set():
            logger.debug(f"Opening serialport '{self.app_context.config['serial']['port']}'")
            try:
                ser = serial.serial_for_url(
                    self.app_context.config["serial"]["port"],
                    baudrate=self.app_context.config["serial"]["baudrate"],
                    parity=self.app_context.config["serial"]["parity"],
                    stopbits=self.app_context.config["serial"]["stopbits"],
                    bytesize=self.app_context.config["serial"]["bytesize"],
                    timeout=self.app_context.config["serial"]["timeout"],
                    do_not_open=True,
                )
                ser.open()
                self._state.serialerror = 0
                return ser
            except Exception as e:
                self._state.serialerror += 1
                self.app_context.set_error(
                    f"Serialport connection failed: {type(e).__name__}: '{e}'", category="serial"
                )
                logger.error(f"Retry in {self.app_context.config['serial']['connect_retry']} seconds")
                time.sleep(self.app_context.config["serial"]["connect_retry"])
        return None

    def _handle_header(self, datastr: str) -> None:
        """
        Parse header packet to extract firmware version.

        Args:
            datastr: Raw header string from serial port.
        """
        logger.debug(f"Header Packet: '{datastr}'")
        try:
            if ":" in datastr:
                self.app_context.s0pcm_firmware = datastr.split(":", 1)[1].strip()
            else:
                self.app_context.s0pcm_firmware = datastr[1:].strip()
        except IndexError:
            self.app_context.s0pcm_firmware = datastr

    def _handle_data_packet(self, datastr: str) -> None:
        """
        Parse data packet and update measurements in state.

        Args:
            datastr: Raw data packet string from serial port.
        """
        logger.debug(f"S0PCM Packet: '{datastr}'")

        try:
            parsed_data = parse_s0pcm_packet(datastr)
        except ValueError as e:
            self.app_context.set_error(f"Invalid Packet: {e}. Packet: '{datastr}'", category="serial")
            return

        with self.app_context.lock:
            for meter_id, data in parsed_data.items():
                self._update_meter(meter_id, data["pulsecount"])

            # Update shared state snapshot for MQTT
            self.app_context.state_share = self.app_context.state.model_copy(deep=True)

        # Clear serial error
        self.app_context.set_error(None, category="serial")

        # Signal MQTT task that new data is available
        self._trigger.set()

    def _update_meter(self, meter_id: int, pulsecount: int) -> None:
        """
        Update logic for a single meter.

        Handles day-rollover and pulsecount increment/reset logic.

        Args:
            meter_id: The ID of the meter to update.
            pulsecount: The current pulsecount from the device.
        """
        # Ensure meter exists
        if meter_id not in self.app_context.state.meters:
            self.app_context.state.meters[meter_id] = state_module.MeterState()

        meter = self.app_context.state.meters[meter_id]

        # Handle day-rollover
        today = datetime.date.today()
        if self.app_context.state.date != today:
            logger.debug(
                f"Day changed from '{self.app_context.state.date}' to '{today}', rolling over counter '{meter_id}'."
            )
            meter.yesterday = meter.today
            meter.today = 0
            # Note: context.state.date update should ideally happen once.
            # We'll update it here so subsequent meters in the same packet also see the change.
            self.app_context.state.date = today

        # Check delta and update
        if pulsecount > meter.pulsecount:
            logger.debug(f"Pulsecount changed from '{meter.pulsecount}' to '{pulsecount}' for meter {meter_id}")
            delta = pulsecount - meter.pulsecount
            meter.pulsecount = pulsecount
            meter.total += delta
            meter.today += delta

        elif pulsecount < meter.pulsecount:
            # Pulsecount reset (e.g. device restart)
            if pulsecount == 0:
                self.app_context.set_error(
                    f"S0PCM Reset detected for meter {meter_id}: Pulsecounters cleared. Restoring from total {meter.total}.",
                    category="serial",
                    level=logging.WARNING,
                )
            else:
                self.app_context.set_error(
                    f"Pulsecount anomaly detected for meter {meter_id}: Stored pulsecount '{meter.pulsecount}' is higher than read '{pulsecount}'.",
                    category="serial",
                )

            delta = pulsecount
            meter.pulsecount = pulsecount
            meter.total += delta
            meter.today += delta

    def _read_loop(self, ser: serial.Serial) -> None:
        """
        Continuous read loop from serial port.

        Args:
            ser: The connected serial object.
        """
        while not self._stopper.is_set():
            try:
                datain = ser.readline()
            except Exception as e:
                self.app_context.set_error(f"Serialport read error: {type(e).__name__}: '{e}'", category="serial")
                break  # Break to reconnect

            if len(datain) == 0:
                # Timeout
                self.app_context.set_error("Serialport read timeout: Failed to read any data", category="serial")
                break

            try:
                datastr = datain.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                self.app_context.set_error(f"Failed to decode serial data: '{datain}'", category="serial")
                continue

            match datastr:
                case str(s) if s.startswith(SerialPacketType.HEADER):
                    self._handle_header(datastr)
                case str(s) if s.startswith(SerialPacketType.DATA):
                    self._handle_data_packet(datastr)
                case "":
                    logger.warning("Empty Packet received, this can happen during start-up")
                case _:
                    self.app_context.set_error(f"Invalid Packet: '{datastr}'", category="serial")

    def run(self) -> None:
        """Main thread execution."""
        try:
            # Wait for MQTT recovery to complete before starting to process serial data
            logger.info("Serial Task: Waiting for MQTT/HA state recovery...")
            self.app_context.recovery_event.wait()
            logger.info("Serial Task: Recovery complete, starting serial read loop.")

            while not self._stopper.is_set():
                ser = self._connect()
                if ser:
                    self._read_loop(ser)
                    ser.close()
        except Exception:
            logger.error("Fatal exception in Serial Task", exc_info=True)
        finally:
            self._stopper.set()
