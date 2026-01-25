import threading
import logging
import sys
import signal
import copy
from serial_handler import TaskReadSerial
from mqtt_handler import TaskDoMQTT
from utils import GetVersion
import config as config_module
import state as state_module

"""
Description
-----------
This small Python application reads the pulse counters of a S0PCM-2 or S0PCM-5 and send the total and
daily counters via MQTT to your favorite home automation like Home Assistant. The S0PCM-2 or 5 are the
S0 Pulse Counter Module sold by http://www.smartmeterdashboard.nl

Pulse vs liter vs m3
--------------------
I use the S0PCM-Reader to measure my water meter and normally in the Netherlands the water usage is
easurement in m3 and not in liters. Only this S0PCM-Reader isn't really aware of liters vs m3, be
cause it counts the pulses. So it is important for you to check how your e.g. water meter is counting
the usage, my Itron water meter send 1 pulse per liter of water. This then means the 'measuremen
t.yaml' file, which stores the total and daily counters, all should be in liters and not in m3.

The conversion from m3 to liter is easy, because you can just multiple it by 1000.
E.g. 770.123 m3 is 770123 liter.

S0PCM
-----
The following S0PCM (ascii) protocol is used by this S0PCM-Reader, a simple S0PCM telegram:

Header record (once, after start-up):
/a: S0 Pulse Counter V0.6 - 30/30/30/30/30ms

Data record (repeated every interval):
For S0PCM-5: ID:a:I:b:M1:c:d:M2:e:f:M3:g:h:M4:i:j:M5:k:l
For S0PCM-2: ID:a:I:b:M1:c:d:M2:e:f

Legenda:
a -> Unique ID of the S0PCM
b -> interval between two telegrams in seconds, this is set in the firmware at 10 seconds.
c/e/g/i/k -> number of pulses in the last interval of register 1/2/3/4/5
d/f/h/j/l/ -> number of pulses since the last start-up of register 1/2/3/4/5

Data example:
/8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
ID:8237:I:10:M1:0:0:M2:0:0:M3:0:0:M4:0:0:M5:0:0

Also the S0PCM-Reader uses the following default serialport configuration (used by S0PCM-2 and S0PCM-5):
Speed: 9600 baud
Parity: Even
Databits: 7
Stopbit: 1
Xon/Xoff: No
Rts/Cts: No

MQTT
----
MQTT Topic - when split_topic=yes (default):
base_topic/status - online/offline
base_topic/error - if any?
base_topic/1/total
base_topic/1/today
base_topic/1/yesterday
base_topic/X/total
base_topic/X/today
base_topic/X/yesterday

MQTT Topic - when split_topic=no:
base_topic/status - online/offline
base_topic/error - if any?
base_topic/1 - json string e.g. '{"total": 12345, "today": 15, "yesterday": 77}'
base_topic/X - json string e.g. '{"total": 12345, "today": 15, "yesterday": 77}'
base_topic/X/total/set - write new total to meter X

MQTT Diagnostics:
base_topic/version
base_topic/firmware
base_topic/startup_time
base_topic/port
base_topic/info - json string with all diagnostic info

"""

# ------------------------------------------------------------------------------------
# Global State (delegated to state_module)
# ------------------------------------------------------------------------------------
# Re-exports for backwards compatibility
lock = state_module.lock
config = state_module.config
measurement = state_module.measurement
s0pcm_firmware = state_module.s0pcm_firmware
recovery_event = state_module.recovery_event

s0pcmreaderversion = GetVersion()
state_module.s0pcmreaderversion = s0pcmreaderversion



# ------------------------------------------------------------------------------------
# Parameters
# ------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------
# Parameters and Configuration Setup
# ------------------------------------------------------------------------------------
def init_args():
    """Initialize arguments and global configuration paths."""
    config_module.init_args()

# Only parse arguments if running as main script
if __name__ == "__main__":
    init_args()
else:
    config_module.init_defaults()

# Re-export for backwards compatibility (read-only, changes must go through config_module)
configdirectory = config_module.configdirectory

# ------------------------------------------------------------------------------------
# Error Handling (Delegated to state_module)
# ------------------------------------------------------------------------------------
SetError = state_module.SetError

# ------------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)




def ReadConfig():
    """Read and populate the global config dictionary."""
    config_module.read_config(config, s0pcmreaderversion)

# ------------------------------------------------------------------------------------
# Measurement Persistence (Delegated to state_module)
# ------------------------------------------------------------------------------------
SaveMeasurement = state_module.SaveMeasurement
ReadMeasurement = state_module.ReadMeasurement


# ------------------------------------------------------------------------------------
# Task to read the serial port. We continue to try to open the serialport, because
# we don't want to exit with such error.
# ------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------
# TaskReadSerial has been moved to serial_handler.py
# ------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------
# Task to do MQTT Publish
# ------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------
# TaskDoMQTT has been moved to mqtt_handler.py
# ------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------

def main():
    global trigger, stopper

    # Signal handling for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Signal {signum} received, stopping...")
        stopper.set()
        trigger.set() # Wake up threads waiting on trigger

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:

        ReadConfig()
        # Initialize measurementshare
        state_module.measurementshare = copy.deepcopy(measurement)
    except Exception:
        logger.error('Fatal exception during startup', exc_info=True)
        sys.exit(1)

    trigger = threading.Event()
    stopper = threading.Event()
    
    # Register trigger with state module so SetError can fire it
    state_module.register_trigger(trigger)

    logger.info('Starting s0pcm-reader...')

    # Start our SerialPort thread
    t1 = TaskReadSerial(trigger, stopper)
    t1.start()

    # Start our MQTT thread
    t2 = TaskDoMQTT(trigger, stopper)
    t2.start()

    # Wait for threads to finish (which happens when stopper is set)
    # We use a loop with timeout to allow signal handling to interrupt main thread in Python
    while t1.is_alive() or t2.is_alive():
        t1.join(1)
        t2.join(1)

    logger.info('Stop: s0pcm-reader')

if __name__ == "__main__":
    main()
