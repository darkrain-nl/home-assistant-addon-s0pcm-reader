"""
Serial Handler Module

Contains the TaskReadSerial class for reading and parsing S0PCM data from serial port.
"""

import threading
import time
import datetime
import copy
import logging
import serial
import state as state_module
from protocol import parse_s0pcm_packet

logger = logging.getLogger(__name__)

class TaskReadSerial(threading.Thread):

    def __init__(self, trigger, stopper):
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._serialerror = 0

    def _connect(self):
        """Argument-less method to connect to serial port with retry logic."""
        while not self._stopper.is_set():
            logger.debug(f"Opening serialport '{state_module.config['serial']['port']}'")
            try:
                ser = serial.Serial(state_module.config['serial']['port'], 
                                    baudrate=state_module.config['serial']['baudrate'],
                                    parity=state_module.config['serial']['parity'],
                                    stopbits=state_module.config['serial']['stopbits'],
                                    bytesize=state_module.config['serial']['bytesize'],
                                    timeout=state_module.config['serial']['timeout'])
                self._serialerror = 0
                return ser
            except Exception as e:
                self._serialerror += 1
                state_module.SetError(f"Serialport connection failed: {type(e).__name__}: '{str(e)}'", category='serial')
                logger.error(f"Retry in {state_module.config['serial']['connect_retry']} seconds")
                time.sleep(state_module.config['serial']['connect_retry'])
        return None

    def _handle_header(self, datastr):
        """Parse header packet to extract firmware version."""
        logger.debug(f"Header Packet: '{datastr}'")
        # Example: /8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
        try:
            if ':' in datastr:
                state_module.s0pcm_firmware = datastr.split(':', 1)[1].strip()
            else:
                state_module.s0pcm_firmware = datastr[1:].strip()
        except Exception:
            state_module.s0pcm_firmware = datastr

    def _handle_data_packet(self, datastr):
        """Parse data packet and update measurements."""
        logger.debug(f"S0PCM Packet: '{datastr}'")

        try:
            parsed_data = parse_s0pcm_packet(datastr)
        except ValueError as e:
            state_module.SetError(f"Invalid Packet: {str(e)}. Packet: '{datastr}'", category='serial')
            return

        # Keep a copy to check for changes later (debug use, logic seems unused in original code but kept)
        # measurementstr = str(state_module.measurement) 

        # Loop through parsed data and update
        with state_module.lock:
            for count, data in parsed_data.items():
                self._update_meter(count, data['pulsecount'])

            # Update todays date if needed
            if str(state_module.measurement['date']) != str(datetime.date.today()):
                state_module.measurement['date'] = datetime.date.today()

            # Update shared state
            state_module.measurementshare = copy.deepcopy(state_module.measurement)
        
        # Valid packet processed
        state_module.SetError(None, category='serial')
        
        # Signal new data
        self._trigger.set()

    def _update_meter(self, count, pulsecount):
        """Update logic for a single meter."""
        # Initialize if missing
        if count not in state_module.measurement: state_module.measurement[count] = {}
        if 'pulsecount' not in state_module.measurement[count]: state_module.measurement[count]['pulsecount'] = 0
        if 'total' not in state_module.measurement[count]: state_module.measurement[count]['total'] = 0
        if 'today' not in state_module.measurement[count]: state_module.measurement[count]['today'] = 0
        if 'yesterday' not in state_module.measurement[count]: state_module.measurement[count]['yesterday'] = 0
        
        # Check date change
        if str(state_module.measurement['date']) != str(datetime.date.today()):
            logger.debug(f"Day changed from '{str(state_module.measurement['date'])}' to '{str(datetime.date.today())}', resetting today counter '{count}' to '0'. Yesterday counter is '{state_module.measurement[count]['today']}'")
            state_module.measurement[count]['yesterday'] = state_module.measurement[count]['today']
            state_module.measurement[count]['today'] = 0


        # Calculate delta
        if pulsecount > state_module.measurement[count]['pulsecount']:
            logger.debug(f"Pulsecount changed from '{state_module.measurement[count]['pulsecount']}' to '{pulsecount}'")
            delta = pulsecount - state_module.measurement[count]['pulsecount']
            state_module.measurement[count]['pulsecount'] = pulsecount
            state_module.measurement[count]['total'] += delta
            state_module.measurement[count]['today'] += delta

        elif pulsecount < state_module.measurement[count]['pulsecount']:
            # Pulsecount reset (e.g. device restart)
            if pulsecount == 0:
                state_module.SetError(f"S0PCM Reset detected for meter {count}: Pulsecounters cleared. Restoring from total {state_module.measurement[count]['total']}.", category='serial', level=logging.WARNING)
            else:
                state_module.SetError(f"Pulsecount anomaly detected for meter {count}: Stored pulsecount '{state_module.measurement[count]['pulsecount']}' is higher than read '{pulsecount}'.", category='serial')
            
            delta = pulsecount
            state_module.measurement[count]['pulsecount'] = pulsecount
            state_module.measurement[count]['total'] += delta
            state_module.measurement[count]['today'] += delta

    def _read_loop(self, ser):
        """Read loop using the connected serial object."""
        while not self._stopper.is_set():
            try:
                datain = ser.readline()
            except Exception as e:
                state_module.SetError(f"Serialport read error: {type(e).__name__}: '{str(e)}'", category='serial')
                break # Break to reconnect
            
            if len(datain) == 0:
                # Timeout
                state_module.SetError("Serialport read timeout: Failed to read any data", category='serial')
                break

            try:
                datastr = datain.decode('ascii').rstrip('\r\n')
            except UnicodeDecodeError:
                state_module.SetError(f"Failed to decode serial data: '{str(datain)}'", category='serial')
                continue

            if datastr.startswith('/'):
                self._handle_header(datastr)
            elif datastr.startswith('ID:'):
                self._handle_data_packet(datastr)
            elif datastr == '':
                logger.warning('Empty Packet received, this can happen during start-up')
            else:
                state_module.SetError(f"Invalid Packet: '{datastr}'", category='serial')

    def run(self):
        try:
            # Wait for MQTT recovery to complete before starting to process serial data
            logger.info("Serial Task: Waiting for MQTT/HA state recovery...")
            state_module.recovery_event.wait()
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
