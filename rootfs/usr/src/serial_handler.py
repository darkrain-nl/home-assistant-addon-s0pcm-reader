"""
Serial Handler Module

Contains the TaskReadSerial class for reading and parsing S0PCM data from serial port.
"""

import threading
import time
import datetime
import logging
from typing import Optional

import serial
import state as state_module
from protocol import parse_s0pcm_packet

logger = logging.getLogger(__name__)

class TaskReadSerial(threading.Thread):
    """
    Task to read the serial port and update meter measurements.
    
    This thread continuously reads from the configured serial port, parses S0PCM packets,
    and updates the application state.
    """

    def __init__(self, trigger: threading.Event, stopper: threading.Event) -> None:
        """
        Initialize the serial reader task.
        
        Args:
            trigger: Event to signal when new data is available.
            stopper: Event to signal when the task should stop.
        """
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._serialerror = 0
        self._context = state_module.get_context()

    def _connect(self) -> Optional[serial.Serial]:
        """
        Established a connection to the serial port.
        
        Returns:
            serial.Serial: The connected serial object, or None if failed and stopped.
        """
        while not self._stopper.is_set():
            logger.debug(f"Opening serialport '{self._context.config['serial']['port']}'")
            try:
                ser = serial.Serial(self._context.config['serial']['port'], 
                                    baudrate=self._context.config['serial']['baudrate'],
                                    parity=self._context.config['serial']['parity'],
                                    stopbits=self._context.config['serial']['stopbits'],
                                    bytesize=self._context.config['serial']['bytesize'],
                                    timeout=self._context.config['serial']['timeout'])
                self._serialerror = 0
                return ser
            except Exception as e:
                self._serialerror += 1
                self._context.set_error(f"Serialport connection failed: {type(e).__name__}: '{str(e)}'", category='serial')
                logger.error(f"Retry in {self._context.config['serial']['connect_retry']} seconds")
                time.sleep(self._context.config['serial']['connect_retry'])
        return None

    def _handle_header(self, datastr: str) -> None:
        """
        Parse header packet to extract firmware version.
        
        Args:
            datastr: Raw header string from serial port.
        """
        logger.debug(f"Header Packet: '{datastr}'")
        try:
            if ':' in datastr:
                self._context.s0pcm_firmware = datastr.split(':', 1)[1].strip()
            else:
                self._context.s0pcm_firmware = datastr[1:].strip()
        except Exception:
            self._context.s0pcm_firmware = datastr

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
            self._context.set_error(f"Invalid Packet: {str(e)}. Packet: '{datastr}'", category='serial')
            return

        with self._context.lock:
            for meter_id, data in parsed_data.items():
                self._update_meter(meter_id, data['pulsecount'])

            # Update shared state snapshot for MQTT
            self._context.state_share = self._context.state.model_copy(deep=True)
        
        # Clear serial error
        self._context.set_error(None, category='serial')
        
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
        if meter_id not in self._context.state.meters:
            self._context.state.meters[meter_id] = state_module.MeterState()
        
        meter = self._context.state.meters[meter_id]
        
        # Handle day-rollover
        today = datetime.date.today()
        if self._context.state.date != today:
             logger.debug(f"Day changed from '{self._context.state.date}' to '{today}', rolling over counter '{meter_id}'.")
             meter.yesterday = meter.today
             meter.today = 0
             # Note: context.state.date update should ideally happen once. 
             # We'll update it here so subsequent meters in the same packet also see the change.
             self._context.state.date = today
        
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
                self._context.set_error(f"S0PCM Reset detected for meter {meter_id}: Pulsecounters cleared. Restoring from total {meter.total}.", category='serial', level=logging.WARNING)
            else:
                self._context.set_error(f"Pulsecount anomaly detected for meter {meter_id}: Stored pulsecount '{meter.pulsecount}' is higher than read '{pulsecount}'.", category='serial')
            
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
                self._context.set_error(f"Serialport read error: {type(e).__name__}: '{str(e)}'", category='serial')
                break # Break to reconnect
            
            if len(datain) == 0:
                # Timeout
                self._context.set_error("Serialport read timeout: Failed to read any data", category='serial')
                break

            try:
                datastr = datain.decode('ascii').rstrip('\r\n')
            except UnicodeDecodeError:
                self._context.set_error(f"Failed to decode serial data: '{str(datain)}'", category='serial')
                continue

            if datastr.startswith('/'):
                self._handle_header(datastr)
            elif datastr.startswith('ID:'):
                self._handle_data_packet(datastr)
            elif datastr == '':
                logger.warning('Empty Packet received, this can happen during start-up')
            else:
                self._context.set_error(f"Invalid Packet: '{datastr}'", category='serial')

    def run(self) -> None:
        """Main thread execution."""
        try:
            # Wait for MQTT recovery to complete before starting to process serial data
            logger.info("Serial Task: Waiting for MQTT/HA state recovery...")
            self._context.recovery_event.wait()
            logger.info("Serial Task: Recovery complete, starting serial read loop.")

            while not self._stopper.is_set():
                ser = self._connect()
                if ser:
                    self._read_loop(ser)
                    ser.close()
        except Exception:
            logger.error('Fatal exception in Serial Task', exc_info=True)
        finally:
            self._stopper.set()
